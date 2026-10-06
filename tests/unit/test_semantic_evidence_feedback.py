"""Feedback repairs source coverage without weakening the claim-local acceptance rules."""
from copy import deepcopy
import unittest

from tests.unit import test_semantic_review_loop as loop_fixture


class SemanticEvidenceFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.loop = loop_fixture.SemanticReviewLoopTests()
        self.loop.setUp(); self.addCleanup(self.loop.doCleanups)

    def header_only(self, number, axes=('dimensions',)):
        response = self.loop.propose(self.loop.packet, number)
        header = 'Actual annual results in USD millions. FY2025 FY2024.'
        citation = self.loop.factory.citation(self.loop.packet, header)
        citation['source_start'] = None
        for check in response['checks']:
            if check['axis'] in axes: check['constraints'][0]['citations'] = [deepcopy(citation)]
        return response

    @staticmethod
    def corrected_from_feedback(feedback):
        response = deepcopy(feedback['previous_assessment'])
        for violation in feedback['details']['violations']:
            target = response
            parts = violation['location'].split('.')
            for part in parts[:-1]: target = target[int(part)] if isinstance(target, list) else target[part]
            citations, seen = [], set()
            for item in violation['missing_anchors']:
                span = item['required_span']
                key = (span['source_snapshot_id'], span['block_id'], span['start'], span['end'])
                if key in seen: continue
                seen.add(key)
                citations.append({'source_snapshot_id': span['source_snapshot_id'], 'block_id': span['block_id'],
                                  'source_start': span['start'], 'quote': span['text']})
            target[parts[-1]] = citations
        return response

    def test_header_only_four_records_receives_original_draft_and_all_missing_anchors_then_passes(self):
        raw = self.header_only(1)
        def propose(packet, number):
            if number == 1: return deepcopy(raw)
            return self.corrected_from_feedback(packet['host_validation_feedback'])
        result, reviewer, auditor, events = self.loop.run_loop(reviewer=propose)
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 2); self.assertEqual(len(auditor.requests), 1)
        feedback = reviewer.requests[1]['host_validation_feedback']
        self.assertEqual(feedback['previous_assessment'], raw)
        self.assertEqual(feedback['previous_assessment_status'], 'unvalidated')
        self.assertIsNone(feedback['previous_assessment']['checks'][0]['constraints'][0]['citations'][0]['source_start'])
        details = feedback['details']
        self.assertEqual(details['location'], 'checks.0.constraints.0.citations')
        self.assertEqual(details['code'], 'record_anchor_uncovered')
        self.assertEqual({m['record_id'] for m in details['missing_anchors']}, set(self.loop.packet['record_anchors']))
        self.assertEqual(len(details['missing_anchors']), 4)
        self.assertEqual(details['record_id'], details['missing_anchors'][0]['record_id'])
        self.assertEqual(details['required_span'], details['missing_anchors'][0]['required_span'])
        for item in details['missing_anchors']:
            expected = self.loop.packet['record_anchors'][item['record_id']]
            for key in ('source_snapshot_id', 'block_id', 'start', 'end', 'text', 'kind'):
                self.assertEqual(item['required_span'][key], expected[key])
        self.assertEqual(len(result['assessments'][0]['checks'][0]['constraints'][0]['citations']), 2)
        self.assertNotIn('expected', feedback)

    def test_multiple_invalid_groups_are_reported_together_in_one_rejection(self):
        raw = self.header_only(1, axes=('dimensions', 'value'))
        def propose(packet, number):
            return deepcopy(raw) if number == 1 else self.corrected_from_feedback(packet['host_validation_feedback'])
        result, reviewer, auditor, events = self.loop.run_loop(reviewer=propose)
        self.assertEqual(result['status'], 'assessed')
        violations = reviewer.requests[1]['host_validation_feedback']['details']['violations']
        self.assertEqual({v['location'] for v in violations},
                         {'checks.0.constraints.0.citations', 'checks.1.constraints.0.citations'})
        self.assertTrue(all(len(v['missing_anchors']) == 4 for v in violations))
        self.assertEqual(len(reviewer.requests), 2)

    def test_partial_or_forged_repairs_never_reach_critic(self):
        # Separate fresh workspaces keep each run immutable and independently bounded.
        for mode in ('profit-omitted', 'wrong-source', 'wrong-period-record', 'forged-offset'):
            harness = loop_fixture.SemanticReviewLoopTests(); harness.setUp()
            self.addCleanup(harness.doCleanups)
            raw = harness.propose(harness.packet, 1)
            header = harness.factory.citation(harness.packet,
                'Actual annual results in USD millions. FY2025 FY2024.')
            raw['checks'][0]['constraints'][0]['citations'] = [header]
            def propose(packet, number):
                if number == 1: return deepcopy(raw)
                response = self.corrected_from_feedback(packet['host_validation_feedback'])
                constraint = response['checks'][0]['constraints'][0]
                if mode == 'profit-omitted': constraint['citations'] = constraint['citations'][:1]
                elif mode == 'wrong-source': constraint['citations'][0]['source_snapshot_id'] = 'birch-foreign-source'
                elif mode == 'wrong-period-record': constraint['record_ids'][0] = 'birch-annual-a-revenue-2023'
                else: constraint['citations'][0]['source_start'] += 1
                return response
            with self.subTest(mode=mode):
                result, reviewer, auditor, events = harness.run_loop(reviewer=propose)
                self.assertEqual(result['status'], 'partial')
                self.assertEqual(result['assessments'], [])
                self.assertEqual(len(reviewer.requests), 2); self.assertEqual(len(auditor.requests), 0)


if __name__ == '__main__': unittest.main()
