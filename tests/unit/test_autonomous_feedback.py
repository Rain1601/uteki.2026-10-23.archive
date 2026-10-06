"""Scripted feedback-state checks over synthetic data; no model evaluation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import json_size, load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, plan, read
from tests.unit.test_autonomous_worker import delegate
from tests.unit.test_scoped_query_service import make_scoped_dataset


def read_context(block_id='b1'):
    return {'action': 'read_context', 'requirement_ids': ['business'],
            'context': {'source_snapshot_id': 'acme-annual', 'block_id': block_id}}


class AutonomousFeedbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)

    def open_dataset(self, *, large_table=False, text=None):
        if large_table:
            index_dir = self.dataset / 'indexes/acme-annual'
            block_path = index_dir / 'blocks.jsonl'
            blocks = [json.loads(line) for line in block_path.read_text().splitlines()]
            target = next(block for block in blocks if block['block_id'] == 'b1')
            target['type'] = 'table'
            if text is not None:
                target['text'] = text
            # Keep the source below the reader limit but make the complete table
            # too large for a preview, even when its actual text is very short.
            target['table'] = {'row_count': 160, 'column_count': 1, 'cells': [
                {'text': 'metadata ' + 'x' * 70, 'row': row, 'column': 0,
                 'rowspan': 1, 'colspan': 1, 'is_header': False}
                for row in range(160)]}
            block_path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            (index_dir / 'manifest.json').write_text(json.dumps({
                'status': 'candidate', 'artifacts': {
                    name: {'sha256': digest((index_dir / name).read_bytes())}
                    for name in ('index.json', 'blocks.jsonl')}}))
            manifest_path = self.dataset / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['files'] = {
                str(path.relative_to(self.dataset)): digest(path.read_bytes())
                for path in self.dataset.rglob('*')
                if path.is_file() and path != manifest_path}
            manifest_path.write_text(json.dumps(manifest))
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id,
            company_ids=('acme',), source_snapshot_ids=('acme-annual',),
            source_policy_id='local-frozen-v1', knowledge_cutoff='2032-05-01',
            include_candidates=True)
        self.request = {'question': 'Read the products and services business for 2031.',
                        'scope': self.scope.model_dump(mode='json')}

    def run_actions(self, actions, *, worker=None, limits=None):
        planner = ScriptedPlanner(actions)
        output = self.root / 'run'
        agent = AutonomousDataAgent(self.port, planner, worker_planner=worker,
            limits={'max_steps': len(actions) + (6 if worker else 0),
                    'max_packet_bytes': 16000, 'observation_bytes': 1800,
                    'page_items': 2, **(limits or {})})
        result = asyncio.run(agent.run(self.request, output=output))
        return result, planner, output

    def assert_completion(self, packet, *, passed, reason=None):
        completion = packet['completion']
        self.assertIs(completion['reference_checks_passed'], passed)
        self.assertEqual(completion['semantic_completeness'], 'not_evaluated')
        if reason:
            self.assertIn({'requirement_id': 'business', 'reason': reason},
                          completion['unmet'])
        if passed:
            self.assertEqual(completion['unmet'], [])

    def target_pending(self, packet):
        targets = [item for item in packet['pending_body_reads']
                   if item['block_id'] == 'b1']
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target['source_snapshot_id'], 'acme-annual')
        self.assertEqual(target['requirement_ids'], ['business'])
        self.assertTrue(target['context_evidence_id'])
        self.assertTrue(target['read_request']['artifact_id'])
        self.assertEqual(target['read_request']['pointer'], '/blocks/1/text')
        self.assertEqual(target['read_request']['limit'], 1000)
        return target

    def test_target_text_pointer_survives_rejection_then_allows_extract_and_finish(self):
        self.open_dataset(large_table=True)
        state = {}

        def early_finish(packet):
            self.assert_completion(packet, passed=False, reason='requested_body_not_delivered')
            target = self.target_pending(packet)
            self.assertEqual(target['read_request'].get('offset', 0), 0)
            self.assertNotIn('acme sales from products.', json.dumps(packet['observation']))
            state['target'] = deepcopy(target)
            return {'action': 'finish'}

        def read_target(packet):
            self.assertEqual(packet['observation']['status'], 'rejected')
            self.assertIn('requested_body_not_delivered', json.dumps(packet['observation']))
            self.assert_completion(packet, passed=False, reason='requested_body_not_delivered')
            self.assertEqual(self.target_pending(packet), state['target'])
            return {'action': 'read_artifact', 'requirement_ids': ['business'],
                    'artifact_read': packet['pending_body_reads'][0]['read_request']}

        def extract_target(packet):
            self.assertEqual(packet['pending_body_reads'], [])
            self.assert_completion(packet, passed=True)
            self.assertIn('acme sales from products.', json.dumps(packet['observation']))
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': state['target']['context_evidence_id'], 'block_id': 'b1',
                'quote': 'acme sales from products.', 'label': 'Products business'}]}

        def extract_services(packet):
            self.assertEqual(packet['pending_body_reads'], [])
            self.assert_completion(packet, passed=True)
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b2',
                'quote': 'acme sales from services.', 'label': 'Services business'}]}

        def finish(packet):
            self.assert_completion(packet, passed=True)
            self.assertEqual(packet['pending_body_reads'], [])
            self.assertEqual(len(packet['recent_actions']), 6)
            return {'action': 'finish'}

        result, planner, output = self.run_actions([
            plan('business'), read_context(), early_finish, read_target,
            extract_target, read_context('b2'), extract_services, finish])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        for index, packet in enumerate(planner.packets):
            expected = [{key: row[key] for key in ('step', 'action', 'status')}
                        for row in result['trace'][max(0, index - 6):index]]
            self.assertEqual(packet['recent_actions'], expected)
            self.assertLessEqual(json_size(packet), 16000)
        bundle = load_evidence_bundle(output)
        self.assertIn('b1', bundle['delivered_body'][state['target']['context_evidence_id']])
        self.assertEqual({item['value']['quote'] for item in bundle['items']
                          if item['kind'] == 'candidate_extract'},
                         {'acme sales from products.', 'acme sales from services.'})

    def test_last_step_storage_does_not_deliver_requested_body(self):
        self.open_dataset(large_table=True)

        def prepare_text(packet):
            target = self.target_pending(packet)
            return {'action': 'read_artifact', 'requirement_ids': ['business'],
                    'artifact_read': target['read_request']}

        result, planner, output = self.run_actions([
            plan('business'), read_context(), prepare_text])
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(len(planner.packets), 3)
        self.assertEqual(result['trace'][-1]['status'], 'tool_returned')
        feedback = json.loads((output / result['trace'][-1]['feedback']).read_text())
        self.assertEqual(feedback['result']['items'], 'acme sales from products.')
        target, = result['pending_body_reads']
        self.assertEqual(target['read_request'].get('offset', 0), 0)
        bundle = load_evidence_bundle(output)
        context = next(item for item in bundle['items']
                       if item['evidence_id'] == target['context_evidence_id'])
        self.assertEqual(next(block['text'] for block in context['value']['blocks']
                              if block['block_id'] == 'b1'), 'acme sales from products.')
        self.assertNotIn('b1', bundle['delivered_body'].get(target['context_evidence_id'], []))
        self.assertTrue(any(gap['reason'] == 'requested_body_not_delivered'
                            for gap in result['gaps']))

    def test_explicit_requirement_gap_allows_partial_without_faking_delivery(self):
        self.open_dataset(large_table=True)

        def report_gap(packet):
            self.target_pending(packet)
            self.assert_completion(packet, passed=False, reason='requested_body_not_delivered')
            return {'action': 'gap', 'requirement_ids': ['business'],
                    'reason': 'Requested table text has not been read; business analysis remains incomplete.'}

        def finish(packet):
            self.target_pending(packet)
            self.assert_completion(packet, passed=True)
            return {'action': 'finish'}

        result, _, output = self.run_actions([
            plan('business'), read_context(), report_gap, finish])
        self.assertEqual(result['status'], 'partial', result['trace'])
        target, = result['pending_body_reads']
        bundle = load_evidence_bundle(output)
        self.assertNotIn('b1', bundle['delivered_body'].get(target['context_evidence_id'], []))
        self.assertFalse(any(item['kind'] == 'candidate_extract' for item in bundle['items']))
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')

    def test_pending_text_offset_advances_only_after_delivered_pages(self):
        text = 'acme products ' + 'x' * 3200 + ' TAIL_REQUIRED'
        self.open_dataset(large_table=True, text=text)
        offsets = []

        def read_or_finish(packet):
            retained = packet['retained_body']
            self.assertEqual(retained['byte_limit'], 2000)
            self.assertFalse(any(item['block_id'] == 'b1' for item in retained['items']))
            if not packet['pending_body_reads']:
                self.assert_completion(packet, passed=True)
                self.assertIn('TAIL_REQUIRED', json.dumps(packet['observation']))
                self.assertGreaterEqual(retained['omitted_count'], 1)
                return {'action': 'finish'}
            self.assert_completion(packet, passed=False, reason='requested_body_not_delivered')
            target = self.target_pending(packet)
            offset = target['read_request'].get('offset', 0)
            if offsets:
                self.assertGreater(offset, offsets[-1])
                self.assertEqual(offset, packet['observation']['result']['end_offset'])
            offsets.append(offset)
            return {'action': 'read_artifact', 'requirement_ids': ['business'],
                    'artifact_read': target['read_request']}

        result, planner, output = self.run_actions([
            plan('business'), read_context(), *([read_or_finish] * 16)])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(offsets[0], 0)
        self.assertGreater(len(offsets), 1)
        self.assertEqual(result['pending_body_reads'], [])
        self.assertTrue(all(json_size(packet) <= 16000 for packet in planner.packets))
        bundle = load_evidence_bundle(output)
        self.assertTrue(any('b1' in blocks for blocks in bundle['delivered_body'].values()))

    def test_complete_paged_body_stays_visible_after_skill_and_query_replace_observation(self):
        text = 'acme products ' + 'x' * 3200 + ' TAIL_REQUIRED'
        self.open_dataset(large_table=True, text=text)
        state = {}

        def read_or_review(packet):
            retained = packet['retained_body']
            self.assertEqual(retained['byte_limit'], 8000)
            targets = [item for item in retained['items'] if item['block_id'] == 'b1']
            if packet['pending_body_reads']:
                self.assertEqual(targets, [])
                self.assert_completion(packet, passed=False, reason='requested_body_not_delivered')
                target = self.target_pending(packet)
                state['target'] = deepcopy(target)
                return {'action': 'read_artifact', 'requirement_ids': ['business'],
                        'artifact_read': target['read_request']}
            self.assert_completion(packet, passed=True)
            item, = targets
            self.assertEqual(item['context_evidence_id'], state['target']['context_evidence_id'])
            self.assertEqual(item['source_snapshot_id'], 'acme-annual')
            self.assertEqual(item['scope'], self.request['scope'])
            self.assertEqual(item['text'], text)
            self.assertEqual(item['read_request']['artifact_id'],
                             state['target']['read_request']['artifact_id'])
            self.assertEqual(item['read_request']['pointer'], '/blocks/1/text')
            self.assertEqual(retained['omitted_count'], 0)
            if 'retained' not in state:
                self.assertIn('TAIL_REQUIRED', json.dumps(packet['observation']))
                self.assertNotIn(text, json.dumps(packet['observation']))
                state['retained'] = deepcopy(item)
                return {'action': 'load_skill', 'skill': 'query'}
            self.assertEqual(item, state['retained'])
            if packet['recent_actions'][-1]['action'] == 'load_skill':
                self.assertNotIn('TAIL_REQUIRED', json.dumps(packet['observation']))
                state['after_skill'] = True
                return {'action': 'query', 'requirement_ids': ['business'], 'plan': {'documents': [{
                    'company_id': 'acme', 'form': '10-K', 'period_end': '2031-12-31',
                    'phrase': 'acme sales from services.'}]}}
            self.assertEqual(packet['recent_actions'][-1]['action'], 'query')
            state['after_query'] = True
            return {'action': 'finish'}

        result, planner, _ = self.run_actions([
            plan('business'), read_context(), *([read_or_review] * 16)],
            limits={'max_packet_bytes': 64000})
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertTrue(state['after_skill'])
        self.assertTrue(state['after_query'])
        self.assertTrue(all(json_size(packet) <= 64000 for packet in planner.packets))
        for packet in planner.packets:
            for item in packet['retained_body']['items']:
                self.assertEqual(item['scope'], self.request['scope'])
                self.assertEqual(item['source_snapshot_id'], 'acme-annual')

    def test_worker_history_persists_after_query_and_read_without_inheriting_completion(self):
        self.open_dataset()
        worker = ScriptedPlanner([read(), {'action': 'finish'}])
        state = {}

        def inspect_return(packet):
            self.assertEqual(packet['observation']['status'], 'worker_returned')
            delegation, = packet['delegations']
            self.assertEqual(delegation['requirement_ids'], ['business'])
            self.assertEqual(delegation['status'], 'worker_returned')
            self.assertEqual(delegation['result_status'], 'evidence_ready')
            self.assertTrue(delegation['path'])
            self.assertTrue(delegation['handoff_artifact_id'])
            state['delegation'] = deepcopy(delegation)
            self.assertEqual(packet['coverage'][0]['evidence_ids'], [])
            self.assertEqual(packet['evidence_index'], [])
            self.assertEqual(packet['retained_body']['items'], [])
            self.assertEqual(packet['retained_body']['omitted_count'], 0)
            self.assertTrue(worker.packets[-1]['retained_body']['items'])
            self.assert_completion(packet, passed=False, reason='evidence_or_explicit_gap_required')
            return {'action': 'query', 'requirement_ids': ['business'], 'plan': {'documents': [{
                'company_id': 'acme', 'form': '10-K', 'period_end': '2031-12-31',
                'phrase': 'acme sales from products.'}]}}

        def read_after_query(packet):
            self.assertEqual(packet['observation']['status'], 'tool_returned')
            self.assertEqual(packet['delegations'], [state['delegation']])
            return read_context('b2')

        def finish(packet):
            self.assertEqual(packet['observation']['status'], 'tool_returned')
            self.assertEqual(packet['delegations'], [state['delegation']])
            self.assert_completion(packet, passed=True)
            return {'action': 'finish'}

        result, planner, output = self.run_actions([
            plan('business'), delegate(), inspect_return, read_after_query, finish], worker=worker)
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['worker_runs'], [state['delegation']])
        self.assertTrue((output / state['delegation']['path'] / 'manifest.json').is_file())
        artifact_index = json.loads((output / 'artifact-index.json').read_text())
        handoff = next(item for item in artifact_index
                       if item['artifact_id'] == state['delegation']['handoff_artifact_id'])
        self.assertEqual(handoff['kind'], 'worker_handoff')
        self.assertTrue((output / handoff['path']).is_file())
        self.assertTrue(all(json_size(packet) <= 16000 for packet in planner.packets))
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')


if __name__ == '__main__':
    unittest.main()
