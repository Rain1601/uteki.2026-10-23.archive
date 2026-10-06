"""Independent gold scoring and preparation separation; no model calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('semantic_benchmark',
    ROOT/'experiments/data_agent_query/semantic-review-v1/benchmark.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
FIXTURES = ROOT/'benchmarks/data_agent/semantic_review/v1'


def response_for(packet, expected):
    """Test-only oracle; never used by preparation or model execution."""
    block = packet['source_blocks'][0]
    citation = {k: block[k] for k in ('source_snapshot_id', 'block_id')}
    citation['quote'] = block['text']
    checks = []
    for axis, rule in expected['checks'].items():
        status = rule['allowed_statuses'][0]
        checks.append({'axis': axis, 'status': status, 'reason': 'Fixture test response.',
            'constraints': [{'record_ids': [r['record']['record_id'] for r in packet['records']],
                'statement': 'Bounded source qualification.', 'citations': [citation]}] if status == 'constraints_found' else [],
            'unresolved_questions': ['Which adjustments are included?'] if status == 'insufficient_evidence' else []})
    return {'packet_id': packet['packet_id'], 'checks': checks,
        'assertions': [{'assertion_id': aid, 'verdict': verdict, 'reason': 'Fixture test response.',
            'citations': [citation] if verdict != 'insufficient_evidence' else []}
            for aid, verdict in expected['assertions'].items()], 'limitations': []}


class SemanticReviewBenchmarkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.expected = json.loads((FIXTURES/'expected.json').read_text())['cases']
        # A small supplied schema isolates benchmark unit checks from concurrent domain work.
        self.spec = benchmark.prepare(FIXTURES/'cases.json', self.root/'inputs', output_schema={'type': 'object'})

    def case(self, index):
        ref = self.spec['packets'][index]
        packet = json.loads((self.root/'inputs'/ref['path']).read_text())
        return packet, self.expected[ref['case_id']]

    @staticmethod
    def identity_validator(packet, response):
        return deepcopy(response)

    def test_twelve_neutral_cases_have_balanced_expected_verdicts(self):
        from collections import Counter
        self.assertEqual(len(self.spec['packets']), 12)
        self.assertEqual([r['case_id'] for r in self.spec['packets']], [f'sr-{i:03d}' for i in range(1, 13)])
        self.assertEqual(Counter(v for e in self.expected.values() for v in e['assertions'].values()),
                         {'supported': 6, 'contradicted': 5, 'insufficient_evidence': 1})

    def test_preparation_does_not_read_or_embed_expected_answers(self):
        isolated = self.root/'isolated'; isolated.mkdir()
        (isolated/'cases.json').write_bytes((FIXTURES/'cases.json').read_bytes())
        spec = benchmark.prepare(isolated/'cases.json', self.root/'isolated-inputs', output_schema={'type': 'object'})
        for ref, old in zip(spec['packets'], self.spec['packets']):
            new_packet = (self.root/'isolated-inputs'/ref['path']).read_bytes()
            self.assertEqual(new_packet, (self.root/'inputs'/old['path']).read_bytes())
            value = json.loads(new_packet)
            self.assertNotIn('expected', value); self.assertNotIn('case_id', value)
            self.assertNotIn('rationale', value); self.assertNotIn('citation_anchors', value)
            self.assertEqual(value['scope']['source_snapshot_ids'], [value['source']['source_snapshot_id']])
            self.assertEqual(value['source_origin'], 'synthetic_fixture')

    def test_fixed_expected_correct_responses_pass(self):
        for index in range(12):
            packet, expected = self.case(index)
            with self.subTest(index=index):
                result = benchmark.score_case(packet, response_for(packet, expected), expected,
                                              validator=self.identity_validator)
                self.assertTrue(result['passed'], result)

    def test_wrong_year_unit_and_standalone_verdict_cannot_pass(self):
        for index in (1, 3, 7):
            packet, expected = self.case(index)
            response = response_for(packet, expected)
            response['assertions'][0]['verdict'] = 'supported'
            result = benchmark.score_case(packet, response, expected, validator=self.identity_validator)
            self.assertFalse(result['passed'])
            self.assertIn('assertion_verdict_mismatch', result['issues'])

    def test_wrong_axis_status_fails_even_when_assertion_verdict_matches(self):
        packet, expected = self.case(9)
        response = response_for(packet, expected)
        response['checks'][0]['status'] = 'none_found_in_context'
        result = benchmark.score_case(packet, response, expected, validator=self.identity_validator)
        self.assertIn('axis_status_mismatch', result['issues'])

    def test_value_axis_representation_is_flexible_but_missing_context_is_not(self):
        for index in (0, 1, 2, 3):
            packet, expected = self.case(index)
            for status in ('constraints_found', 'none_found_in_context'):
                response = response_for(packet, expected)
                response['checks'][0]['status'] = status
                if status == 'none_found_in_context': response['checks'][0]['constraints'] = []
                with self.subTest(index=index, status=status):
                    self.assertTrue(benchmark.score_case(packet, response, expected)['passed'])
        packet, expected = self.case(10)
        response = response_for(packet, expected)
        response['checks'][0]['status'] = 'none_found_in_context'
        result = benchmark.score_case(packet, response, expected)
        self.assertFalse(result['passed'])
        self.assertIn('axis_status_mismatch', result['issues'])

    def test_expected_anchor_in_constraint_alone_does_not_ground_assertion(self):
        packet, expected = self.case(5)
        response = response_for(packet, expected)
        response['assertions'][0]['citations'] = []
        result = benchmark.score_case(packet, response, expected, validator=self.identity_validator)
        self.assertFalse(result['passed'])
        self.assertIn('required_assertion_evidence_missing', result['issues'])

    def test_host_rejection_is_failed_without_exception_body_leak(self):
        packet, expected = self.case(0)
        def reject(packet, response): raise ValueError('sensitive diagnostic body')
        result = benchmark.score_case(packet, response_for(packet, expected), expected, validator=reject)
        self.assertEqual(result, {'passed': False, 'status': 'invalid_response', 'error_type': 'ValueError'})

    def test_not_run_outputs_are_not_counted_as_passed(self):
        (self.root/'responses').mkdir()
        report = benchmark.evaluate(self.root/'inputs', self.root/'responses', FIXTURES/'expected.json', self.root/'score.json')
        self.assertEqual(report['passed'], 0)
        self.assertEqual(report['statuses'], {'not_run': 12})

    def test_real_host_validator_accepts_all_grounded_test_responses(self):
        for index in range(12):
            packet, expected = self.case(index)
            with self.subTest(index=index):
                result = benchmark.score_case(packet, response_for(packet, expected), expected)
                self.assertTrue(result['passed'], result)

    def test_real_host_rejects_fabricated_quote_and_missing_axis(self):
        packet, expected = self.case(0)
        for change in ('quote', 'axis', 'foreign_source'):
            response = response_for(packet, expected)
            if change == 'quote': response['assertions'][0]['citations'][0]['quote'] = 'invented source wording'
            elif change == 'axis': response['checks'] = []
            else: response['assertions'][0]['citations'][0]['source_snapshot_id'] = 'another-company'
            with self.subTest(change=change):
                result = benchmark.score_case(packet, response, expected)
                self.assertFalse(result['passed'])
                self.assertEqual(result['status'], 'invalid_response')

    def test_evaluation_reads_runner_assessments_and_keeps_partial_cases_not_run(self):
        responses = self.root/'responses'; responses.mkdir()
        packet, expected = self.case(0)
        (responses/'result.json').write_text(json.dumps({'assessments': [response_for(packet, expected)]}))
        report = benchmark.evaluate(self.root/'inputs', responses, FIXTURES/'expected.json', self.root/'score.json')
        self.assertEqual(report['passed'], 1)
        self.assertEqual(report['statuses'], {'scored': 1, 'not_run': 11})


if __name__ == '__main__': unittest.main()
