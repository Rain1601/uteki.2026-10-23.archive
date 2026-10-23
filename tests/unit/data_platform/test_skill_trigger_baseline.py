"""Check the case set and prevent missing/error trials being counted as passes."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[3]
EVAL = runpy.run_path(str(ROOT/'scripts/data_agent/skill_trigger_baseline.py'))
CASES = ROOT/'tests/fixtures/data_platform/skill_trigger_queries.json'


class TriggerBaselineTests(unittest.TestCase):
    def test_cases_are_interleaved_and_only_query_is_model_input(self):
        data, _ = EVAL['load_cases'](CASES)
        for case in data['cases']:
            self.assertEqual(EVAL['model_input'](case), case['query'])
        self.assertEqual(sum(bool(c['expected_skills']) for c in data['cases']), 30)
        self.assertTrue({'near_miss', 'quoted_trigger', 'comparison', 'scope', 'missing'} <=
            {c['category'] for c in data['cases']})

    def test_missing_errors_and_failed_load_are_not_passes(self):
        data, _ = EVAL['load_cases'](CASES)
        positives = [c for c in data['cases'] if c['expected_skills']]
        negatives = [c for c in data['cases'] if not c['expected_skills']]
        def row(case, selected, loaded, status='ok'):
            return dict(id=case['id'], selected_skills=selected, loaded_skills=loaded, status=status)
        skill = [data['target_skill']]
        observations = [row(positives[0], skill, []), row(positives[1], [], []),
            row(negatives[0], skill, skill), row(negatives[1], [], []), row(negatives[2], [], [], 'error')]
        result = EVAL['score'](data, observations)
        self.assertEqual(result['counts'], dict(true_positive=1, false_negative=1,
            false_positive=1, true_negative=1, unknown=36, load_failed=1, unexpected_skill=0))
        self.assertEqual(result['coverage'], 0.1)
        self.assertFalse(result['complete'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            EVAL['score'](data, observations+observations[:1])


if __name__ == '__main__':
    unittest.main()
