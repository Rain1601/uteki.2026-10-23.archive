"""Source-body requirements over independent synthetic data; no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AutonomousDataAgent, Requirement
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_worker import delegate, numeric_query
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import attach_synthetic_quotes, pin_dataset


def source_plan(source='acme-annual'):
    return {'action': 'plan', 'reason': 'Read the original disclosure from the selected source.',
            'requirements': [{'kind': 'source_evidence', 'requirement_id': 'business',
                              'description': 'Original business disclosure', 'source_id': source}]}


def context_read(source='acme-annual', block='b1', requirement='business'):
    return {'action': 'read_context', 'requirement_ids': [requirement],
            'context': {'source_snapshot_id': source, 'block_id': block}}


class AutonomousSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        attach_synthetic_quotes(self.dataset)

    def open_dataset(self, *, sources=('acme-annual',), large_table=False):
        if large_table:
            index_dir = self.dataset / 'indexes/acme-annual'
            path = index_dir / 'blocks.jsonl'
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            target = next(block for block in blocks if block['block_id'] == 'b1')
            target.update(type='table', text='acme products ' + 'x' * 2126 + ' END_DISCLOSURE',
                          table={'rows': [[{'text': 'metadata ' + 'x' * 100}] for _ in range(160)]})
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest_path = index_dir / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
            pin_dataset(self.dataset)
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=sources, source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Show operating margin for 2031 and read the original business disclosure.',
                        'scope': self.scope.model_dump(mode='json')}

    def run_actions(self, actions, *, worker=None, materialize=None, name='run', limits=None):
        parent = ScriptedPlanner(actions)
        output = self.root / name
        agent = AutonomousDataAgent(self.port, parent, worker_planner=worker, materialize=materialize,
            limits={'max_steps': len(actions) + (6 if worker else 0),
                    'max_packet_bytes': 64000, **(limits or {})})
        result = asyncio.run(agent.run(self.request, output=output))
        return result, parent, output

    def assert_unmet(self, packet):
        self.assertIs(packet['completion']['reference_checks_passed'], False)
        self.assertTrue(any(item['requirement_id'] == 'business'
                            for item in packet['completion']['unmet']))
        self.assertEqual(packet['completion']['semantic_completeness'], 'not_evaluated')

    def test_source_requirement_rejects_missing_node_unknown_and_out_of_scope_sources(self):
        self.open_dataset()
        requirement = source_plan()['requirements'][0]
        missing = {key: value for key, value in requirement.items() if key != 'source_id'}
        for value in (missing, {**requirement, 'source_id': ''},
                      {**requirement, 'node_id': 'business'}):
            with self.subTest(requirement=value), self.assertRaises(ValidationError):
                Requirement.model_validate(value)
        for index, source in enumerate(('unknown-source', 'other-annual', 'acme-amended')):
            with self.subTest(source=source):
                result, parent, output = self.run_actions([source_plan(source)], name=f'invalid-{index}')
                self.assertEqual(result['trace'][0]['status'], 'rejected')
                self.assertNotEqual(result['status'], 'evidence_ready')
                self.assertEqual(load_evidence_bundle(output)['items'], [])
                self.assertEqual(parent.packets[0]['active_scope'], self.request['scope'])

    def test_records_and_citations_only_supply_persistent_navigation_until_body_is_read(self):
        self.open_dataset()
        state = {}

        def early_finish(packet):
            self.assert_unmet(packet)
            self.assertTrue(packet['coverage'][0]['evidence_ids'])
            self.assertEqual(packet['retained_body']['items'], [])
            lead = next(item for item in packet['source_leads']
                        if item['source_snapshot_id'] == 'acme-annual' and item['block_id'] == 'b9')
            self.assertEqual(lead['scope'], self.request['scope'])
            self.assertIn('business', lead['requirement_ids'])
            self.assertEqual(lead['origin'], 'citation')
            self.assertEqual(lead['read_status'], 'located')
            self.assertEqual(lead['read_request'], {'source_snapshot_id': 'acme-annual', 'block_id': 'b9'})
            state['lead'] = deepcopy(lead)
            state['evidence_ids'] = deepcopy(packet['coverage'][0]['evidence_ids'])
            return {'action': 'finish'}

        def load_skill(packet):
            self.assertEqual(packet['observation']['status'], 'rejected')
            self.assert_unmet(packet)
            return {'action': 'load_skill', 'skill': 'query'}

        def follow_lead(packet):
            self.assert_unmet(packet)
            self.assertIn(state['lead'], packet['source_leads'])
            self.assertEqual(packet['coverage'][0]['evidence_ids'], state['evidence_ids'])
            return {'action': 'read_context', 'requirement_ids': ['business'],
                    'context': state['lead']['read_request']}

        def finish(packet):
            self.assertIs(packet['completion']['reference_checks_passed'], True)
            lead = next(item for item in packet['source_leads']
                        if item['source_snapshot_id'] == 'acme-annual' and item['block_id'] == 'b9')
            self.assertEqual(lead['read_status'], 'body_delivered')
            return {'action': 'finish'}

        result, _, output = self.run_actions([
            source_plan(), numeric_query(), early_finish, load_skill, follow_lead, finish])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        bundle = load_evidence_bundle(output)
        self.assertTrue(any(item['kind'] == 'record' for item in bundle['items']))
        self.assertTrue(any(item['kind'] == 'citation' for item in bundle['items']))
        self.assertFalse(any(item['kind'] == 'source_lead' for item in bundle['items']))

    def test_other_allowed_source_cannot_satisfy_requirement_but_exact_own_extract_can(self):
        self.open_dataset(sources=('acme-annual', 'acme-amended'))
        plan = source_plan()
        plan['requirements'].append({'kind': 'information', 'requirement_id': 'research',
                                     'description': 'Read a passage before extracting it.'})

        def reject_wrong_source(packet):
            self.assert_unmet(packet)
            self.assertTrue(any(item['source_snapshot_id'] == 'acme-amended'
                                for item in packet['retained_body']['items']))
            return {'action': 'finish'}

        def extract(packet):
            self.assert_unmet(packet)
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b1',
                'quote': 'acme sales from products.', 'label': 'Original annual disclosure'}]}

        result, _, output = self.run_actions([
            plan, context_read('acme-amended'), reject_wrong_source,
            context_read(requirement='research'), extract, {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        bundle = load_evidence_bundle(output)
        candidate, = [item for item in bundle['items'] if item['kind'] == 'candidate_extract']
        parent = next(item for item in bundle['items']
                      if item['evidence_id'] == candidate['value']['source_evidence_id'])
        self.assertEqual(parent['value']['source_snapshot_id'], 'acme-annual')
        self.assertEqual(candidate['value']['quote'], 'acme sales from products.')

    def test_start_block_requires_full_delivery_and_last_prepared_page_does_not_count(self):
        self.open_dataset(large_table=True)
        initial = {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
            'source_snapshot_id': 'acme-annual', 'node_id': 'business',
            'start_block_id': 'b1', 'count': 1}}

        def premature_finish(packet):
            self.assert_unmet(packet)
            self.assertTrue(any(item['block_id'] == 'b1' for item in packet['pending_body_reads']))
            return {'action': 'finish'}

        def read_or_finish(packet):
            pending = [item for item in packet['pending_body_reads'] if item['block_id'] == 'b1']
            if not pending:
                self.assertIs(packet['completion']['reference_checks_passed'], True)
                return {'action': 'finish'}
            self.assert_unmet(packet)
            target, = pending
            self.assertEqual(target['source_snapshot_id'], 'acme-annual')
            self.assertIn('business', target['requirement_ids'])
            self.assertEqual(target['read_request']['pointer'], '/blocks/1/text')
            return {'action': 'read_artifact', 'requirement_ids': ['business'],
                    'artifact_read': target['read_request']}

        actions = [source_plan(), initial, premature_finish, *([read_or_finish] * 16)]
        result, _, _ = self.run_actions(actions, limits={'observation_bytes': 1800})
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertGreater(sum(step['action'] == 'read_artifact' for step in result['trace']), 1)
        limited, _, output = self.run_actions(actions, name='last-page-not-delivered',
            limits={'observation_bytes': 1800, 'max_steps': len(result['trace']) - 1})
        self.assertEqual(limited['status'], 'limited')
        self.assertEqual(limited['trace'][-1]['action'], 'read_artifact')
        target, = [item for item in limited['pending_body_reads'] if item['block_id'] == 'b1']
        bundle = load_evidence_bundle(output)
        self.assertNotIn('b1', bundle['delivered_body'].get(target['context_evidence_id'], []))
        self.assertTrue(any(gap['reason'] == 'requested_body_not_delivered' for gap in limited['gaps']))

    def test_explicit_source_gap_only_allows_partial(self):
        self.open_dataset()
        result, _, output = self.run_actions([
            source_plan(), {'action': 'gap', 'requirement_ids': ['business'],
                            'reason': 'Original source body has not been read.'}, {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial', result['trace'])
        self.assertEqual(load_evidence_bundle(output)['items'], [])
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')

    def test_unknown_read_or_search_node_is_rejected_without_creating_a_data_gap(self):
        self.open_dataset()
        invalid_navigation = [
            {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
                'source_snapshot_id': 'acme-annual', 'node_id': 'not-a-node', 'count': 1}},
            {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
                'source_snapshot_id': 'acme-annual', 'node_id': 'not-a-node', 'phrase': 'products'}}]

        def premature_finish(packet):
            self.assertEqual(packet['observation']['status'], 'rejected')
            self.assertEqual(packet['gaps'], [])
            self.assert_unmet(packet)
            return {'action': 'finish'}

        for index, navigation in enumerate(invalid_navigation):
            with self.subTest(action=navigation['action']):
                result, _, _ = self.run_actions([
                    source_plan(), navigation, premature_finish, context_read(), {'action': 'finish'}],
                    name=f'unknown-node-{index}')
                self.assertEqual(result['trace'][1]['status'], 'rejected')
                self.assertEqual(result['trace'][2]['status'], 'rejected')
                self.assertEqual(result['status'], 'evidence_ready', result['trace'])
                self.assertEqual(result['gaps'], [])

    def test_worker_body_does_not_satisfy_parent_source_completion(self):
        self.open_dataset()
        worker = ScriptedPlanner([context_read(), {'action': 'finish'}])

        def premature_finish(packet):
            self.assert_unmet(packet)
            self.assertEqual(packet['coverage'][0]['evidence_ids'], [])
            self.assertEqual(packet['retained_body']['items'], [])
            self.assertTrue(worker.packets[-1]['retained_body']['items'])
            self.assertEqual(packet['delegations'][0]['result_status'], 'evidence_ready')
            return {'action': 'finish'}

        result, _, output = self.run_actions([
            source_plan(), delegate(), premature_finish, context_read(), {'action': 'finish'}], worker=worker)
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        contexts = [item for item in load_evidence_bundle(output)['items'] if item['kind'] == 'context']
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]['value']['source_snapshot_id'], 'acme-annual')

    def test_materialization_preserves_old_source_scope_and_new_requirement_needs_new_body(self):
        self.open_dataset()
        dataset = self.root / 'materialized'
        dataset.mkdir()
        make_scoped_dataset(dataset)
        manifest_path = dataset / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['snapshot_id'] = 'new-materialized-snapshot'
        manifest_path.write_text(json.dumps(manifest))
        new_port = QueryDataPort(dataset)
        self.addCleanup(new_port.close)
        next_scope = self.scope.model_copy(update={
            'snapshot_id': new_port.snapshot_id,
            'source_snapshot_ids': ('acme-annual', 'acme-amended')})
        state = {}

        async def materialize(arguments, *, scope, output):
            self.assertEqual(scope, self.scope)
            return {'port': new_port, 'scope': next_scope}

        def extend_plan(packet):
            self.assertEqual(packet['active_scope'], next_scope.model_dump(mode='json'))
            self.assertEqual(packet['coverage'][0]['source_scope'], self.request['scope'])
            self.assertIs(packet['completion']['reference_checks_passed'], True)
            state['old_context'] = next(item['evidence_id'] for item in packet['evidence_index']
                                        if item['kind'] == 'context')
            plan = source_plan()
            plan['requirements'].append({'kind': 'source_evidence', 'requirement_id': 'refreshed',
                'source_id': 'acme-annual', 'description': 'Read original disclosure in the refreshed snapshot.'})
            return plan

        def extract_old_body(packet):
            rows = {row['requirement_id']: row for row in packet['coverage']}
            self.assertEqual(rows['business']['source_scope'], self.request['scope'])
            self.assertEqual(rows['refreshed']['source_scope'], next_scope.model_dump(mode='json'))
            self.assertEqual({item['requirement_id'] for item in packet['completion']['unmet']}, {'refreshed'})
            return {'action': 'extract', 'requirement_ids': ['refreshed'], 'extracts': [{
                'context_id': state['old_context'], 'block_id': 'b1',
                'quote': 'acme sales from products.', 'label': 'Verified text from the older snapshot'}]}

        def reject_old_evidence(packet):
            self.assertEqual(len(packet['observation']['evidence_ids']), 1)
            self.assertIs(packet['completion']['reference_checks_passed'], False)
            self.assertEqual({item['requirement_id'] for item in packet['completion']['unmet']}, {'refreshed'})
            return {'action': 'finish'}

        result, _, output = self.run_actions([
            source_plan(), context_read(),
            {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}},
            extend_plan, extract_old_body, reject_old_evidence,
            context_read(requirement='refreshed'), {'action': 'finish'}], materialize=materialize)
        self.assertEqual(result['trace'][5]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        rows = {row['requirement_id']: row for row in result['coverage']}
        self.assertEqual(rows['business']['source_scope'], self.request['scope'])
        self.assertEqual(rows['refreshed']['source_scope'], next_scope.model_dump(mode='json'))
        self.assertTrue(all(row['program_check'] == 'source_body_delivered' for row in rows.values()))
        bundle = load_evidence_bundle(output)
        candidate, = [item for item in bundle['items'] if item['kind'] == 'candidate_extract']
        self.assertEqual(candidate['scope'], self.request['scope'])
        self.assertEqual(candidate['value']['source_evidence_id'], state['old_context'])


if __name__ == '__main__':
    unittest.main()
