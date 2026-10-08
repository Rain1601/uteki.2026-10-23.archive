"""Independent question review keeps the original shared-credit boundary on replay."""
from copy import deepcopy
import importlib.util
import json
import unittest
from unittest.mock import patch

from tests.unit import test_e1_replay_config as fixtures
from uteki.agents.data_query.retrieval_cycle import review_roles, question_reviewer_factory

replay, ROOT = fixtures.replay, fixtures.ROOT


class QuestionReviewerConfigTests(unittest.TestCase):
    def setUp(self):
        fixtures.E1ReplayConfigTests.setUp(self)
        self.config['question_review_policy'] = 'independent-question-v2'
        self.config['question_reviewer'] = deepcopy(self.config['reviewer'])
        self.save_template()

    def save_template(self):
        self.template.write_text(json.dumps(self.config))

    def test_four_roles_relocate_together_without_new_credit_or_scope_change(self):
        config, evidence = replay.build_config(**self.kwargs)
        self.assertEqual(review_roles(config), ('planner', 'worker', 'reviewer', 'question_reviewer'))
        for role in review_roles(config):
            self.assertEqual(config[role]['budget_ledger'], str(self.ledger.resolve()))
            self.assertEqual(config[role]['budget_usd'], '5')
        self.assertEqual(config['question_reviewer']['model'], self.config['reviewer']['model'])
        self.assertEqual(config['request']['scope'], self.config['request']['scope'])
        self.assertEqual(evidence['restored_budget']['committed_usd'], '0.7')
        self.assertFalse(evidence['new_allowance_created'])
        self.assertFalse(self.kwargs['output_dir'].exists())

    def test_original_role_mismatch_rejected_before_restored_ledger_is_read(self):
        alterations = {'budget_ledger': str(self.root/'other.sqlite'), 'budget_usd': '6',
                       'max_requests_total': 501, 'budget_policy': 'record_only',
                       'allow_unknown_reservations': not self.config['planner'].get('allow_unknown_reservations', False)}
        original = deepcopy(self.config['question_reviewer'])
        for key, value in alterations.items():
            with self.subTest(field=key):
                self.config['question_reviewer'] = {**original, key: value}
                self.save_template()
                with patch.object(replay, 'restored_budget', side_effect=AssertionError('validate original roles first')):
                    with self.assertRaises(ValueError):
                        replay.build_config(**self.kwargs)

    def test_half_configured_or_unknown_policy_is_rejected(self):
        for field in ('question_reviewer', 'question_review_policy'):
            config = deepcopy(self.config); config.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                review_roles(config)
        config = deepcopy(self.config); config['question_review_policy'] = 'unknown'
        with self.assertRaises(ValueError): review_roles(config)

    def test_legacy_three_role_template_does_not_gain_a_reviewer(self):
        self.config.pop('question_reviewer'); self.config.pop('question_review_policy')
        self.save_template()
        config, _ = replay.build_config(**self.kwargs)
        self.assertEqual(review_roles(config), ('planner', 'worker', 'reviewer'))
        self.assertNotIn('question_review_policy', config)
        with self.assertRaisesRegex(ValueError, 'not configured'):
            question_reviewer_factory(config)

    def test_legacy_analysis_handoff_cli_rejects_new_policy_instead_of_bypassing_it(self):
        spec = importlib.util.spec_from_file_location('handoff_question_config_test', ROOT/'scripts/run_data_handoff.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        config = deepcopy(self.config)
        config.pop('max_attempts')
        config.pop('reviewer_max_request_bytes', None)
        config['analyst'] = deepcopy(config['reviewer'])
        with self.assertRaisesRegex(ValueError, 'unknown fields rejected'):
            module.validate(config, self.root/'handoff')


if __name__ == '__main__':
    unittest.main()
