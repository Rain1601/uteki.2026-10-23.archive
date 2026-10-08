"""Literal search diagnostics cannot become permanent material gaps; no models."""
import json
import unittest

from tests.unit import test_analysis_evidence_runtime as fixtures
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from uteki.agents.data_query.answer_handoff import prepare_review_packet


def search(phrase, limit=8):
    return {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
        'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': phrase, 'limit': limit}}


class SearchDiagnosticsTests(unittest.TestCase):
    setUp = fixtures.AnalysisEvidenceRuntimeTests.setUp
    run_actions = fixtures.AnalysisEvidenceRuntimeTests.run_actions

    def test_no_match_and_search_pagination_do_not_poison_later_complete_delivery(self):
        result, planner, output = self.run_actions([source_plan(), search('not in this original'),
            search('production equipment', limit=1), context_read(block='b1'), context_read(block='b2'),
            choose('b1', 'b2'), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['gaps'], [])
        self.assertEqual(result['coverage'][0]['gap_ids'], [])
        no_match = json.loads((output/'turn-002/feedback.json').read_text())['result']
        limited = json.loads((output/'turn-003/feedback.json').read_text())['result']
        self.assertEqual(no_match['status'], 'no_literal_match')
        self.assertEqual(no_match['gaps'][0]['reason'], 'no_literal_match')
        self.assertEqual(limited['status'], 'limited')
        self.assertTrue(limited['next_cursor'])
        self.assertEqual(limited['gaps'][0]['reason'], 'limited')
        self.assertEqual(planner.packets[2]['observation']['result']['gaps'], no_match['gaps'])
        packet = prepare_review_packet(output, self.dataset, expected_scope=self.scope,
            max_packet_bytes=100000, source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual({f['value']['block_id'] for f in packet['facts']}, {'b1', 'b2'})

    def test_search_only_cannot_finish_without_material_delivery(self):
        result, planner, _ = self.run_actions([source_plan(), search('not in this original'),
                                              search('production equipment', limit=1), {'action': 'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertIn('source_body_not_delivered',
                      {x['reason'] for x in planner.packets[-1]['completion']['unmet']})
        self.assertFalse(any(g['reason'] == 'tool_gap' for g in result['gaps']))

    def test_explicit_material_gap_stays_partial_after_reading(self):
        result, _, _ = self.run_actions([source_plan(), search('not in this original'),
            context_read(), choose('b1'), {'action': 'gap', 'requirement_ids': ['business'],
                'reason': 'The actual disclosure does not answer the requested future evidence.'},
            {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['gaps'])
        self.assertTrue(result['coverage'][0]['gap_ids'])

    def test_incomplete_declared_node_read_is_not_cured_by_search(self):
        plan = {'action': 'plan', 'reason': 'Read the declared chapter.', 'requirements': [
            {'kind': 'read_node', 'requirement_id': 'chapter', 'description': 'Entire business chapter',
             'source_id': 'acme-annual', 'node_id': 'business'},
            *source_plan()['requirements']]}
        result, planner, _ = self.run_actions([plan, search('not in this original'), context_read(),
                                              choose('b1'), {'action': 'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertIn('read_node_coverage_incomplete',
                      {x['reason'] for x in planner.packets[-1]['completion']['unmet']})


if __name__ == '__main__':
    unittest.main()
