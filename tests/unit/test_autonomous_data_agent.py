"""Scripted fixture orchestration checks; never a real-model evaluation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import ScopedQueryDataPort

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes


class ScriptedPlanner:
    plan_origin = 'scripted_fixture'

    def __init__(self, actions):
        self.actions = iter(actions)
        self.packets = []

    async def decide(self, packet):
        self.packets.append(deepcopy(packet))
        value = next(self.actions)
        return value(packet) if callable(value) else value


def plan(*ids):
    return {'action': 'plan', 'reason': 'Explicit test requirements',
            'requirements': [{'requirement_id': i, 'description': 'Read source ' + i} for i in ids]}


def read(rid='business', source='acme-annual'):
    return {'action': 'read_source', 'requirement_ids': [rid],
            'read': {'source_snapshot_id': source, 'node_id': 'business', 'count': 3}}


class AutonomousDataAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); dataset = self.root / 'dataset'; dataset.mkdir()
        make_scoped_dataset(dataset)
        attach_synthetic_quotes(dataset)
        self.port = QueryDataPort(dataset); self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Read business and show operating margin for 2031', 'scope': self.scope.model_dump(mode='json')}

    def run_actions(self, actions, **options):
        planner = ScriptedPlanner(actions)
        agent = AutonomousDataAgent(self.port, planner, limits={'max_steps': len(actions)}, **options)
        result = asyncio.run(agent.run(self.request, output=self.root / 'run'))
        return result, planner

    def test_plan_read_extract_reread_and_manifest(self):
        def extract(packet):
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b1',
                'quote': 'acme sales from products.', 'label': 'Business description'}]}
        def reread(packet):
            return {'action': 'reread', 'requirement_ids': ['business'],
                    'evidence_ids': [packet['evidence_index'][0]['evidence_id']]}
        result, planner = self.run_actions([plan('business'), read(), extract, reread, {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        self.assertEqual(len(load_evidence_bundle(self.root / 'run')['items']), 2)
        self.assertIn('sha256', result['plans'][0])
        self.assertIn('sha256', planner.packets[0]['skills']['query'])
        manifest = json.loads((self.root / 'run/manifest.json').read_text())
        self.assertIn('evidence-bundle.json', manifest['files'])

    def test_finish_rejects_navigation_only(self):
        result, _ = self.run_actions([plan('business'), {'action': 'outline_source', 'requirement_ids': ['business'],
            'outline': {'source_snapshot_id': 'acme-annual'}}, {'action': 'finish'}])
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(load_evidence_bundle(self.root / 'run')['items'], [])
        self.assertTrue(result['gaps'])

    def test_exact_quote_rejects_invented_number(self):
        def invented(packet):
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b1',
                'quote': 'Margin is 93%', 'label': 'Margin'}]}
        result, _ = self.run_actions([plan('business'), read(), invented])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(len(load_evidence_bundle(self.root / 'run')['items']), 1)

    def test_plan_revisions_preserve_requirements_and_gaps(self):
        result, _ = self.run_actions([plan('business'), read(), plan('business', 'missing'),
            {'action': 'gap', 'requirement_ids': ['missing'], 'reason': 'No approved risk source'}, {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['plans']), 2)
        self.assertEqual(len(result['coverage']), 2)
        self.assertEqual(result['coverage'][1]['program_check'], 'missing_evidence')

    def test_revision_cannot_remove_old_requirements(self):
        result, _ = self.run_actions([plan('business', 'missing'), plan('business'), read(), {'action': 'finish'}])
        self.assertEqual(len(result['plans']), 1)
        self.assertEqual(result['status'], 'limited')

    def test_cross_company_source_and_missing_callback_rejected(self):
        result, _ = self.run_actions([plan('business'), read(source='other-annual'),
            {'action': 'acquire', 'requirement_ids': ['business'], 'arguments': {'source': 'requested'}}])
        self.assertEqual(result['trace'][1]['status'], 'rejected')
        self.assertEqual(result['gaps'][0]['reason'], 'acquire_unavailable')
        self.assertEqual(load_evidence_bundle(self.root / 'run')['items'], [])

    def test_callback_cannot_expand_company_or_cutoff(self):
        async def acquire(arguments, *, scope, output):
            return {'port': self.port, 'scope': scope.model_copy(update={'company_ids': ('acme', 'other')})}
        result, _ = self.run_actions([plan('business'), {'action': 'acquire', 'requirement_ids': ['business'],
            'arguments': {}}], acquire=acquire)
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(result['active_scope'], self.scope.model_dump(mode='json'))

    def test_callback_can_explicitly_add_source_within_scope(self):
        async def acquire(arguments, *, scope, output):
            return {'port': self.port, 'scope': scope.model_copy(update={'source_snapshot_ids': ('acme-annual', 'acme-amended')})}
        result, _ = self.run_actions([plan('business'), {'action': 'acquire', 'requirement_ids': ['business'],
            'arguments': {}}, read(source='acme-amended'), {'action': 'finish'}], acquire=acquire)
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(len(result['active_scope']['source_snapshot_ids']), 2)

    def test_numeric_calculation_is_host_computed(self):
        result, _ = self.run_actions([plan('business'), {'action': 'query', 'requirement_ids': ['business'],
            'plan': {'calculations': [{'formula_id': 'operating_margin', 'entity_id': 'acme-services', 'periods': [year(2031)]}]}},
            {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')
        computed = [r for r in load_evidence_bundle(self.root / 'run')['items'] if r['kind'] == 'computed']
        self.assertEqual(computed[0]['value']['display_decimal'], '15.00')

    def test_missing_scope_fails_before_execution(self):
        planner = ScriptedPlanner([])
        agent = AutonomousDataAgent(self.port, planner)
        with self.assertRaises(ValueError):
            asyncio.run(agent.run({'question': 'Read business'}, output=self.root / 'run'))
        self.assertEqual(planner.packets, [])
        self.assertFalse((self.root / 'run').exists())

    def test_wrong_period_is_not_reinterpreted(self):
        result, _ = self.run_actions([plan('business'), {'action': 'query', 'requirement_ids': ['business'],
            'plan': {'calculations': [{'formula_id': 'operating_margin', 'entity_id': 'acme-services', 'periods': [year(2030)]}]}}])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertFalse(load_evidence_bundle(self.root / 'run')['items'])

    def test_materialize_new_snapshot_preserves_old_evidence(self):
        dataset = self.root / 'new-dataset'; dataset.mkdir(); make_scoped_dataset(dataset)
        manifest_path = dataset / 'manifest.json'
        manifest = json.loads(manifest_path.read_text()); manifest['snapshot_id'] = 'new-snapshot'
        manifest_path.write_text(json.dumps(manifest))
        new_port = QueryDataPort(dataset); self.addCleanup(new_port.close)
        before = (self.port.dataset / 'manifest.json').read_bytes()
        async def materialize(arguments, *, scope, output):
            return {'port': new_port, 'scope': scope.model_copy(update={'snapshot_id': new_port.snapshot_id}),
                    'artifacts': [{'snapshot_id': new_port.snapshot_id}]}
        result, _ = self.run_actions([plan('business'), read(), {'action': 'materialize', 'requirement_ids': ['business'],
            'arguments': {}}, read(), {'action': 'finish'}], materialize=materialize)
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual({v['scope']['snapshot_id'] for v in load_evidence_bundle(self.root / 'run')['items']},
                         {self.port.snapshot_id, 'new-snapshot'})
        self.assertEqual((self.port.dataset / 'manifest.json').read_bytes(), before)

    def test_callback_future_source_is_rejected(self):
        async def acquire(arguments, *, scope, output):
            return {'port': self.port, 'scope': scope.model_copy(update={
                'source_snapshot_ids': ('acme-annual', 'acme-future')})}
        result, _ = self.run_actions([plan('business'), {'action': 'acquire', 'requirement_ids': ['business'],
            'arguments': {}}], acquire=acquire)
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(result['active_scope'], self.scope.model_dump(mode='json'))

    def test_read_node_requires_all_body_blocks(self):
        chapter = {'action': 'plan', 'reason': 'Read complete chapter', 'requirements': [{
            'requirement_id': 'business', 'description': 'Complete Business chapter', 'kind': 'read_node',
            'source_id': 'acme-annual', 'node_id': 'business'}]}
        first = read(); first['read']['count'] = 1
        rest = read(); rest['read'].update(start_block_id='b1', count=2)
        result, planner = self.run_actions([chapter, first, {'action': 'finish'}, rest, {'action': 'finish'}])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['coverage'][0]['unread_block_ids'], [])
        self.assertEqual(len(result['coverage'][0]['returned_block_ids']), 3)
        self.assertEqual(len(planner.packets[2]['coverage'][0]['unread_block_ids']), 2)

    def test_partial_read_node_explicit_gap_is_partial(self):
        chapter = {'action': 'plan', 'reason': 'Read complete chapter', 'requirements': [{
            'requirement_id': 'business', 'description': 'Complete Business chapter', 'kind': 'read_node',
            'source_id': 'acme-annual', 'node_id': 'business'}]}
        first = read(); first['read']['count'] = 1
        result, _ = self.run_actions([chapter, first, {'action': 'gap', 'requirement_ids': ['business'],
            'reason': 'Remaining chapter not yet read'}, {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['coverage'][0]['unread_block_ids']), 2)

    def test_three_repeated_reads_stop_without_progress(self):
        result, _ = self.run_actions([plan('business'), read(), read(), read(), read(), {'action': 'finish'}])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(len(result['trace']), 5)
        self.assertEqual(len(load_evidence_bundle(self.root / 'run')['items']), 1)

    def test_skills_are_loaded_on_demand(self):
        result, planner = self.run_actions([{'action': 'load_skill', 'skill': 'query'}, plan('business'), read(), {'action': 'finish'}])
        self.assertNotIn('content', planner.packets[0]['skills']['query'])
        self.assertIsNone(planner.packets[0]['loaded_skill'])
        self.assertIn('content', planner.packets[1]['loaded_skill'])
        self.assertEqual(planner.packets[1]['loaded_skill']['name'], 'query')
        self.assertEqual(result['status'], 'evidence_ready')


    def numeric_plan(self, period=None):
        return {'action': 'plan', 'reason': 'Verify requested numeric result', 'requirements': [{
            'kind': 'query', 'requirement_id': 'business', 'description': 'Operating margin for 2031',
            'query': {'calculations': [{'formula_id': 'operating_margin', 'entity_id': 'acme-services',
                                      'periods': [period or year(2031)]}]}}]}

    def numeric_query(self, period=None):
        return {'action': 'query', 'requirement_ids': ['business'],
                'plan': self.numeric_plan(period)['requirements'][0]['query']}

    def test_numeric_requirement_needs_calculation_not_business_quote(self):
        result, _ = self.run_actions([self.numeric_plan(), read(), {'action': 'finish'},
                                     self.numeric_query(), {'action': 'finish'}])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['coverage'][0]['program_check'], 'satisfied')
        self.assertTrue(any(c['reason'] == 'calculation_verified' for c in result['coverage'][0]['query_checks']))
        self.assertTrue((self.root / 'run/turn-004/query-receipt.json').exists())

    def test_numeric_query_cannot_change_required_period(self):
        self.request['question'] = 'Compare operating margin for 2030 and for 2031'
        result, _ = self.run_actions([self.numeric_plan(), self.numeric_query(year(2030)), {'action': 'finish'}])
        self.assertEqual(result['trace'][1]['status'], 'rejected')
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(result['coverage'][0]['program_check'], 'missing_evidence')

    def test_numeric_query_cannot_change_pinned_sources(self):
        async def acquire(arguments, *, scope, output):
            return {'port': self.port, 'scope': scope.model_copy(update={
                'source_snapshot_ids': ('acme-annual', 'acme-amended')})}
        result, _ = self.run_actions([self.numeric_plan(), {'action': 'acquire', 'requirement_ids': ['business'],
            'arguments': {}}, self.numeric_query(), {'action': 'finish'}], acquire=acquire)
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'limited')

    def test_numeric_receipt_missing_citation_cannot_finish(self):
        original = ScopedQueryDataPort.query_data
        def missing(port, request):
            value = original(port, request)
            value['evidence'] = {}
            return value
        with patch.object(ScopedQueryDataPort, 'query_data', missing):
            result, _ = self.run_actions([self.numeric_plan(), self.numeric_query(), {'action': 'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertNotEqual(result['coverage'][0]['program_check'], 'satisfied')

    def test_numeric_record_with_wrong_operand_unit_cannot_finish(self):
        dataset = self.port.dataset
        self.port.close()
        db = duckdb.connect(str(dataset / 'research.duckdb'))
        rid = 'acme-annual-operating_income-2031'
        payload = json.loads(db.execute('SELECT payload FROM observations WHERE record_id = ?', [rid]).fetchone()[0])
        payload['unit'] = 'EUR'
        db.execute('UPDATE observations SET unit = ?, payload = ? WHERE record_id = ?', ['EUR', json.dumps(payload), rid])
        db.close()
        manifest = json.loads((dataset / 'manifest.json').read_text())
        manifest['files']['research.duckdb'] = digest((dataset / 'research.duckdb').read_bytes())
        (dataset / 'manifest.json').write_text(json.dumps(manifest))
        self.port = QueryDataPort(dataset); self.addCleanup(self.port.close)
        result, _ = self.run_actions([self.numeric_plan(), self.numeric_query(), {'action': 'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertNotEqual(result['coverage'][0]['program_check'], 'satisfied')
        self.assertFalse(any(e['kind'] == 'computed' for e in load_evidence_bundle(self.root / 'run')['items']))

    def test_distinct_navigation_is_exploration_not_body_coverage(self):
        chapter = {'action': 'plan', 'reason': 'Read chapter', 'requirements': [{
            'requirement_id': 'business', 'description': 'Read Business', 'kind': 'read_node',
            'source_id': 'acme-annual', 'node_id': 'business'}]}
        outline = {'action': 'outline_source', 'requirement_ids': ['business'], 'outline': {'source_snapshot_id': 'acme-annual'}}
        def search(phrase):
            return {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
                'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': phrase}}
        result, planner = self.run_actions([chapter, outline, search('products'), search('services'), read(), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual([t['consecutive_no_progress'] for t in result['trace'][1:4]], [0, 0, 0])
        self.assertEqual(planner.packets[4]['coverage'][0]['returned_block_ids'], [])

    def test_repeated_navigation_and_errors_still_stop(self):
        outline = {'action': 'outline_source', 'requirement_ids': ['business'], 'outline': {'source_snapshot_id': 'acme-annual'}}
        result, _ = self.run_actions([plan('business'), outline, outline, outline, outline, read()])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(len(result['trace']), 5)

    def test_changed_reason_does_not_reset_stagnation(self):
        actions = [plan('business')]
        for i in range(4):
            value = plan('business'); value['reason'] = 'Different wording ' + str(i); actions.append(value)
        actions.append(read())
        result, _ = self.run_actions(actions)
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(len(result['trace']), 4)

    def test_gap_reason_changes_do_not_reset_stagnation(self):
        result, _ = self.run_actions([plan('business')] + [
            {'action': 'gap', 'requirement_ids': ['business'], 'reason': 'Reword gap ' + str(i)} for i in range(5)] + [read()])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(len(result['trace']), 5)

    def test_skills_freeze_even_if_files_change_during_run(self):
        skills = self.root / 'skills'
        for name in ('query', 'acquire', 'materialize'):
            (skills / name).mkdir(parents=True)
            (skills / name / 'SKILL.md').write_text('Original skill ' + name)
        def change_skill(packet):
            (skills / 'query/SKILL.md').write_text('Rewritten skill')
            return read()
        result, planner = self.run_actions([plan('business'), change_skill, {'action': 'finish'}], skills=skills)
        hashes = {t['skill_hashes']['query'] for t in result['trace']}
        self.assertEqual(len(hashes), 1)
        self.assertEqual(planner.packets[-1]['loaded_skill']['content'], 'Original skill query')

    def test_fiscal_mapping_is_grounded_per_entity_company(self):
        self.request['question'] = 'Operating margin for FY2031'
        self.scope = self.scope.model_copy(update={'company_ids': ('acme', 'other'),
            'source_snapshot_ids': ('acme-annual', 'other-annual')})
        self.request['scope'] = self.scope.model_dump(mode='json')
        original = ScopedQueryDataPort.get_schema
        def schema(port, *args):
            value = original(port, *args)
            value['fiscal_periods'] = [{'company_id': 'acme', 'fiscal_year': 2031, 'period': year(2031)},
                {'company_id': 'other', 'fiscal_year': 2031, 'period': {'kind': 'year', 'start': '2030-07-01', 'end': '2031-06-30'}}]
            return value
        with patch.object(ScopedQueryDataPort, 'get_schema', schema):
            result, _ = self.run_actions([self.numeric_plan(), self.numeric_query(), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')

    def test_other_company_fiscal_mapping_cannot_fill_missing_mapping(self):
        self.request['question'] = 'Operating margin for FY2031'
        original = ScopedQueryDataPort.get_schema
        def schema(port, *args):
            value = original(port, *args)
            value['fiscal_periods'] = [{'company_id': 'other', 'fiscal_year': 2031, 'period': year(2031)}]
            return value
        with patch.object(ScopedQueryDataPort, 'get_schema', schema):
            result, _ = self.run_actions([self.numeric_plan(), self.numeric_query(), {'action': 'finish'}])
        self.assertEqual(result['trace'][0]['status'], 'rejected')
        self.assertEqual(result['status'], 'limited')

    def test_acquire_materialize_outline_are_exploration_progress(self):
        dataset = self.root / 'materialized'; dataset.mkdir(); make_scoped_dataset(dataset)
        path = dataset / 'manifest.json'; manifest = json.loads(path.read_text())
        manifest['snapshot_id'] = 'new-materialized-snapshot'; path.write_text(json.dumps(manifest))
        new_port = QueryDataPort(dataset); self.addCleanup(new_port.close)
        async def acquire(arguments, *, scope, output):
            return {'port': self.port, 'scope': scope.model_copy(update={
                'source_snapshot_ids': ('acme-annual', 'acme-amended')})}
        async def materialize(arguments, *, scope, output):
            return {'port': new_port, 'scope': scope.model_copy(update={'snapshot_id': new_port.snapshot_id})}
        actions = [plan('business'), {'action': 'load_skill', 'skill': 'acquire'},
            {'action': 'load_skill', 'skill': 'materialize'},
            {'action': 'acquire', 'requirement_ids': ['business'], 'arguments': {}},
            {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}},
            {'action': 'outline_source', 'requirement_ids': ['business'], 'outline': {'source_snapshot_id': 'acme-annual'}},
            read(), {'action': 'finish'}]
        result, planner = self.run_actions(actions, acquire=acquire, materialize=materialize)
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual([r['consecutive_no_progress'] for r in result['trace'][3:6]], [0, 0, 0])
        self.assertEqual(planner.packets[6]['coverage'][0]['evidence_ids'], [])

    def test_repeated_error_stops_even_with_changed_reason(self):
        wrong = read(source='other-annual')
        actions = [plan('business')] + [{**wrong, 'reason': str(i)} for i in range(4)] + [read()]
        result, _ = self.run_actions(actions)
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(len(result['trace']), 4)

    def test_different_search_phrases_same_hit_do_not_create_new_progress(self):
        def search(phrase):
            return {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
                'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': phrase}}
        result, _ = self.run_actions([plan('business'), search('products'), search('from products'),
            search('sales from products'), search('acme sales from products'), read()])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual([r['consecutive_no_progress'] for r in result['trace'][1:]], [0, 1, 2, 3])

    def test_extract_old_context_after_materialize_keeps_parent_scope(self):
        dataset = self.root / 'materialized'; dataset.mkdir(); make_scoped_dataset(dataset)
        path = dataset / 'manifest.json'; manifest = json.loads(path.read_text())
        manifest['snapshot_id'] = 'new-materialized-snapshot'; path.write_text(json.dumps(manifest))
        new_port = QueryDataPort(dataset); self.addCleanup(new_port.close)
        async def materialize(arguments, *, scope, output):
            return {'port': new_port, 'scope': scope.model_copy(update={'snapshot_id': new_port.snapshot_id})}
        extended = plan('business')
        extended['requirements'].append({'requirement_id': 'new-chapter', 'description': 'Read new snapshot Business',
            'kind': 'read_node', 'source_id': 'acme-annual', 'node_id': 'business'})
        def extract(packet):
            parent = next(e['evidence_id'] for e in packet['evidence_index'] if e['kind'] == 'context')
            return {'action': 'extract', 'requirement_ids': ['new-chapter'], 'extracts': [{
                'context_id': parent, 'block_id': 'b1', 'quote': 'acme sales from products.', 'label': 'Product sales'}]}
        result, planner = self.run_actions([plan('business'), read(),
            {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}}, extended, extract,
            {'action': 'finish'}, read(rid='new-chapter'), {'action': 'finish'}], materialize=materialize)
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['trace'][5]['status'], 'rejected')
        self.assertEqual(planner.packets[5]['coverage'][1]['returned_block_ids'], [])
        items = {item['evidence_id']: item for item in load_evidence_bundle(self.root / 'run')['items']}
        candidate = next(item for item in items.values() if item['kind'] == 'candidate_extract')
        parent = items[candidate['value']['source_evidence_id']]
        self.assertEqual(candidate['scope'], parent['scope'])
        self.assertEqual(candidate['scope']['snapshot_id'], self.scope.snapshot_id)
        payload = {k: candidate[k] for k in ('kind', 'value', 'scope')}
        self.assertEqual(candidate['sha256'], digest(payload))
        self.assertEqual(candidate['evidence_id'], 'ev-' + digest(payload)[:24])
        self.assertEqual(len(result['coverage'][1]['returned_block_ids']), 3)

    def test_extract_label_changes_preserve_artifacts_but_not_progress(self):
        def extract(label, quote='acme sales from products.'):
            def action(packet):
                parent = next(e['evidence_id'] for e in packet['evidence_index'] if e['kind'] == 'context')
                return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                    'context_id': parent, 'block_id': 'b1', 'quote': quote, 'label': label}]}
            return action
        result, _ = self.run_actions([plan('business'), read()] + [extract(str(i)) for i in range(5)] + [{'action': 'finish'}])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual([t['consecutive_no_progress'] for t in result['trace'][2:]], [0, 1, 2, 3])
        candidates = [e for e in load_evidence_bundle(self.root / 'run')['items'] if e['kind'] == 'candidate_extract']
        self.assertEqual(len(candidates), 4)
        self.assertEqual(len({e['value']['label'] for e in candidates}), 4)

    def test_distinct_quotes_remain_distinct_progress(self):
        def extract(quote):
            def action(packet):
                parent = next(e['evidence_id'] for e in packet['evidence_index'] if e['kind'] == 'context')
                return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                    'context_id': parent, 'block_id': 'b1', 'quote': quote, 'label': 'Source wording'}]}
            return action
        result, _ = self.run_actions([plan('business'), read(), extract('acme sales'),
            extract('sales from products'), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual([t['consecutive_no_progress'] for t in result['trace'][2:4]], [0, 0])
