"""Synthetic protocol checks for per-run immutable navigation reuse; no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import pin_dataset


def outline(requirement='business', source='acme-annual'):
    return {'action': 'outline_source', 'requirement_ids': [requirement],
            'outline': {'source_snapshot_id': source}}


class AutonomousNavigationCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)

    def open_dataset(self, *, sources=('acme-annual',), large=False):
        if large:
            folder = self.dataset / 'indexes/acme-annual'
            path = folder / 'blocks.jsonl'
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            target = next(block for block in blocks if block['block_id'] == 'b1')
            target.update(type='table', text='acme products ' + 'x' * 2200 + ' END_DISCLOSURE',
                          table={'rows': [[{'text': 'cell ' + 'x' * 100}] for _ in range(160)]})
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest = json.loads((folder / 'manifest.json').read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            pin_dataset(self.dataset)
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=sources, source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Read the original 2031 business disclosure.',
                        'scope': self.scope.model_dump(mode='json')}

    def run_actions(self, actions, *, name='run', limits=None, **options):
        planner = ScriptedPlanner(actions)
        output = self.root / name
        agent = AutonomousDataAgent(self.port, planner,
            limits={'max_steps': len(actions), 'max_packet_bytes': 64000,
                    'observation_bytes': 6000, **(limits or {})}, **options)
        result = asyncio.run(agent.run(self.request, output=output))
        return result, planner, output

    def spy(self, method):
        calls, original = [], getattr(ScopedQueryDataPort, method)
        def call(port, *args, **kwargs):
            calls.append({'scope': port.scope.model_dump(mode='json'),
                          'args': deepcopy(args), 'kwargs': deepcopy(kwargs)})
            return original(port, *args, **kwargs)
        return calls, patch.object(ScopedQueryDataPort, method, call)

    def test_repeated_outline_skips_port_but_not_reading_requirements(self):
        self.open_dataset()
        calls, spy = self.spy('outline_source')
        with spy:
            result, planner, output = self.run_actions([
                source_plan(), outline(), outline(), context_read(), {'action': 'finish'}])
        self.assertEqual(len(calls), 1)
        duplicate = planner.packets[3]['observation']
        self.assertTrue(duplicate['cache_hit'])
        self.assertIn('read_artifact', duplicate['cache_guidance'])
        self.assertFalse(duplicate['receipt']['progress_delta'])
        self.assertEqual(planner.packets[3]['retained_body']['items'], [])
        self.assertFalse(planner.packets[3]['completion']['reference_checks_passed'])
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(json.loads((output/'turn-002/feedback.json').read_text())['result_artifact'],
                         json.loads((output/'turn-003/feedback.json').read_text())['result_artifact'])

    def test_body_cache_keeps_new_requirement_attachment_and_distinct_contexts(self):
        self.open_dataset()
        plan = source_plan()
        plan['requirements'].append({**plan['requirements'][0], 'requirement_id': 'second'})
        calls, spy = self.spy('read_context')
        with spy:
            result, planner, _ = self.run_actions([
                plan, context_read(), context_read(),
                context_read(requirement='second'), context_read(block='b2', requirement='second'),
                {'action': 'finish'}])
        self.assertEqual(len(calls), 3)
        self.assertTrue(planner.packets[3]['observation']['cache_hit'])
        self.assertFalse(planner.packets[4]['observation']['cache_hit'])
        self.assertFalse(planner.packets[5]['observation']['cache_hit'])
        self.assertEqual(result['status'], 'evidence_ready')
        rows = {row['requirement_id']: row for row in result['coverage']}
        self.assertTrue(set(rows['business']['evidence_ids']) & set(rows['second']['evidence_ids']))

    def test_read_payload_count_and_source_identity_are_not_coalesced(self):
        self.open_dataset(sources=('acme-annual', 'acme-amended'))
        first = {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
            'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'count': 1}}
        second = deepcopy(first); second['read']['count'] = 2
        third = deepcopy(second); third['read']['source_snapshot_id'] = 'acme-amended'
        calls, spy = self.spy('read_source')
        with spy:
            _, planner, _ = self.run_actions([source_plan(), first, second, third, {'action': 'finish'}])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(not planner.packets[i]['observation']['cache_hit'] for i in (2, 3, 4)))

    def test_same_payload_after_scope_transition_reads_new_snapshot(self):
        self.open_dataset()
        newer = self.root / 'newer'; newer.mkdir(); make_scoped_dataset(newer)
        path = newer / 'manifest.json'
        manifest = json.loads(path.read_text()); manifest['snapshot_id'] = 'synthetic-new-snapshot'
        path.write_text(json.dumps(manifest))
        next_port = QueryDataPort(newer); self.addCleanup(next_port.close)
        next_scope = self.scope.model_copy(update={'snapshot_id': next_port.snapshot_id})
        def materialize(arguments, *, scope, output):
            return {'port': next_port, 'scope': next_scope}
        calls, spy = self.spy('outline_source')
        with spy:
            _, planner, _ = self.run_actions([source_plan(), outline(),
                {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}},
                outline(), context_read(), {'action': 'finish'}], materialize=materialize)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]['scope'], calls[1]['scope'])
        self.assertFalse(planner.packets[4]['observation']['cache_hit'])

    def test_incomplete_cached_body_still_requires_real_artifact_pages(self):
        self.open_dataset(large=True)
        calls, spy = self.spy('read_context')
        offsets = []
        def next_page(packet):
            pending = [p for p in packet['pending_body_reads'] if p['block_id'] == 'b1']
            if not pending:
                return {'action': 'finish'}
            self.assertFalse(packet['completion']['reference_checks_passed'])
            read = pending[0]['read_request']
            offsets.append(read['offset'])
            return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': read}
        with spy:
            result, planner, output = self.run_actions([
                source_plan(), context_read(), context_read(), *([next_page] * 12)],
                limits={'observation_bytes': 1800})
        self.assertEqual(len(calls), 1)
        self.assertTrue(planner.packets[3]['observation']['cache_hit'])
        self.assertTrue(planner.packets[3]['pending_body_reads'])
        self.assertFalse(planner.packets[3]['observation']['receipt']['progress_delta'])
        self.assertGreater(len(offsets), 1)
        self.assertEqual(offsets, sorted(set(offsets)))
        self.assertEqual(result['status'], 'evidence_ready')
        bundle = load_evidence_bundle(output)
        self.assertTrue(any('b1' in bids for bids in bundle['delivered_body'].values()))

    def test_search_success_is_cached_but_gaps_are_retried(self):
        self.open_dataset()
        search = {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
            'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': 'products'}}
        miss = deepcopy(search); miss['search']['phrase'] = 'not in this source'
        calls, spy = self.spy('search_source')
        with spy:
            _, planner, _ = self.run_actions([source_plan(), search, search, context_read(), miss, miss,
                                               {'action': 'finish'}])
        self.assertEqual(len(calls), 3)
        self.assertTrue(planner.packets[3]['observation']['cache_hit'])
        self.assertFalse(planner.packets[5]['observation']['cache_hit'])
        self.assertFalse(planner.packets[6]['observation']['cache_hit'])

    def test_cache_does_not_survive_a_second_run(self):
        self.open_dataset()
        calls, spy = self.spy('outline_source')
        planner = ScriptedPlanner([source_plan(), outline(), source_plan(), outline()])
        agent = AutonomousDataAgent(self.port, planner, limits={'max_steps': 2})
        with spy:
            asyncio.run(agent.run(self.request, output=self.root / 'first'))
            asyncio.run(agent.run(self.request, output=self.root / 'second'))
        self.assertEqual(len(calls), 2)
