"""Explicit recovery preserves historical unknown charges; no provider calls."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.runtime.run_budget import BudgetExceeded, RunBudget
from uteki.infrastructure.research_data.financial_tasks import FinancialTaskGateway
from tests.unit import test_autonomous_model as model_fixtures
from tests.unit import test_company_financial_tasks as financial_fixtures


class QueryUnknownBudgetPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {'provider': 'deepseek', 'model': 'deepseek-flash',
                       'budget_ledger': str(self.root/'budget.sqlite'), 'budget_usd': '1',
                       'budget_policy': 'enforced', 'max_requests_total': 5}

    def planner_budget(self, **changes):
        with patch('uteki.agents.data_query.autonomous_model.SdkAutonomousPlanner',
                   side_effect=lambda *args, **kwargs: kwargs['budget']):
            return CompanyDataCoordinator._planner({**self.config, **changes}, self.root/'model', self.root)

    def test_default_blocks_unknown_while_explicit_recovery_keeps_hold_and_limit(self):
        budget = self.planner_budget()
        token = budget.reserve('0.4')
        budget.settle(token, None)
        with self.assertRaisesRegex(BudgetExceeded, 'cost unknown'):
            self.planner_budget().reserve('0.1')
        resumed = self.planner_budget(allow_unknown_reservations=True)
        call = resumed.reserve('0.2')
        resumed.settle(call, '0.1')
        self.assertEqual(resumed.summary()['unknown_requests'], 1)
        self.assertEqual(Decimal(resumed.summary()['held_usd']), Decimal('0.4'))
        self.assertEqual(Decimal(resumed.summary()['estimated_spent_usd']), Decimal('0.1'))
        with self.assertRaisesRegex(BudgetExceeded, 'budget exhausted'):
            resumed.reserve('0.6')
        with self.assertRaisesRegex(BudgetExceeded, 'cost unknown'):
            self.planner_budget().reserve('0.1')

    def test_policy_is_strict_bool_even_with_unlimited_record_only_budget(self):
        for value in (None, 'true', 1, 0, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'must be a boolean'):
                CompanyDataCoordinator._validate_model_config({**self.config, 'budget_usd': None,
                    'budget_policy': 'record_only', 'allow_unknown_reservations': value})

    def test_shared_roles_require_same_effective_recovery_policy(self):
        CompanyDataCoordinator._validate_shared_model_configs(self.config,
            {**self.config, 'allow_unknown_reservations': False})
        enabled = {**self.config, 'allow_unknown_reservations': True}
        CompanyDataCoordinator._validate_shared_model_configs(enabled, enabled)
        for left, right in ((self.config, enabled), (enabled, self.config)):
            with self.assertRaisesRegex(ValueError, 'share the same budget'):
                CompanyDataCoordinator._validate_shared_model_configs(left, right)

    def test_model_snapshot_records_effective_policy_without_dispatch(self):
        fixture = model_fixtures.AutonomousModelTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for enabled in (False, True):
            budget = RunBudget(fixture.root/f'budget-{enabled}.sqlite', '1',
                               allow_unknown_reservations=enabled)
            planner = fixture.planner(name=f'model-{enabled}', budget=budget)
            try:
                config = json.loads((planner.output/'model-config.json').read_text())
                self.assertIs(config['allow_unknown_reservations'], enabled)
                self.assertEqual(budget.summary()['requests'], 0)
            finally:
                asyncio.run(planner.aclose())
        self.assertEqual(fixture.requests, [])

    def test_unsupported_financial_path_rejects_recovery_before_writing(self):
        fixture = financial_fixtures.CompanyFinancialTaskTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for value in (True, 'true', 1):
            output = fixture.root/'rejected-financial'
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'allow_unknown_reservations'):
                FinancialTaskGateway(fixture.dataset, fixture.scope, [fixture.task],
                    method_root=fixture.root, output=output,
                    model_config={**fixture.config, 'allow_unknown_reservations': value},
                    credentials_root=fixture.root)
            self.assertFalse(output.exists())
