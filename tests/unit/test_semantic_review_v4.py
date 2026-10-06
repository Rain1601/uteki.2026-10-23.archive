"""V4 fixture legality, frozen-key isolation and independent scoring compatibility."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit import test_semantic_fixture_evaluation as scoring_fixture
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import validate_semantic_packet

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'benchmarks/data_agent/semantic_review/v4'
SPEC = importlib.util.spec_from_file_location('v4_scorer', ROOT/'experiments/data_agent_query/semantic-review-v4/benchmark.py')
benchmark = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(benchmark)


class SemanticReviewV4Tests(unittest.TestCase):
    def test_frozen_hashes_and_packet_contracts_match(self):
        seal = json.loads((FIXTURES/'frozen-hashes.json').read_text())
        for name, sha in seal['files'].items(): self.assertEqual(digest((FIXTURES/name).read_bytes()), sha)
        suite = json.loads((FIXTURES/'cases.json').read_text())
        self.assertEqual(len(suite['cases']), 2)
        self.assertEqual(sum(len(c['packet']['assertions']) for c in suite['cases']), 8)
        for case in suite['cases']: validate_semantic_packet(case['packet'])
        self.assertEqual(len({c['packet']['source']['company_id'] for c in suite['cases']}), 2)
        self.assertEqual(len({c['packet']['source']['source_snapshot_id'] for c in suite['cases']}), 2)

    def test_preparation_works_with_no_expected_file_and_preserves_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = root/'cases.json'; cases.write_bytes((FIXTURES/'cases.json').read_bytes())
            output = root/'inputs'
            result = benchmark.prepare(cases, output)
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual(len(result['packets']), 2)
            _verify_manifest(output)
            suite = json.loads(cases.read_text())
            for case, ref in zip(suite['cases'], result['packets']):
                self.assertEqual(json.loads((output/ref['path']).read_text()), case['packet'])
            self.assertNotIn('expected', (output/'input-manifest.json').read_text())
            with self.assertRaises(FileExistsError): benchmark.prepare(cases, output)

    def test_independent_key_shapes_are_supported_only_on_scoring_side(self):
        # The test oracle is never used by preparation, runtime or model input construction.
        gold = json.loads((FIXTURES/'expected.json').read_text())['cases']
        cases = json.loads((FIXTURES/'cases.json').read_text())['cases']
        for case in cases:
            with self.subTest(case=case['case_id']):
                packet, expected = case['packet'], gold[case['case_id']]
                response = scoring_fixture.gold_response(packet, expected)
                result = scoring_fixture.evaluation.score_response(packet, response, expected)
                self.assertTrue(result['mechanical_pass'], 'Fixed-rule scoring compatibility failed')


if __name__ == '__main__': unittest.main()
