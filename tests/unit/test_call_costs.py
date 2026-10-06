import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uteki.agents.call_costs import MeteredModel, estimate, pricing_snapshot, summarize
from uteki.agents.run_budget import BudgetExceeded, RequestEnvelopeTooLarge, RunBudget, reserve_request


class CostTests(unittest.TestCase):
    def test_estimate_does_not_double_count_cache_or_reasoning(self):
        price = pricing_snapshot('aihubmix', 'gpt-5.4-mini')
        usage = {'input_tokens': 1000000, 'output_tokens': 1000000,
                 'input_tokens_details': {'cached_tokens': 100},
                 'output_tokens_details': {'reasoning_tokens': 500}}
        self.assertEqual(estimate(usage, price), '5.25')
        self.assertIsNone(estimate(None, price))
        self.assertIsNone(estimate(usage, None))

    def test_success_and_failure_persist_independently(self):
        @dataclass
        class Usage:
            input_tokens: int = 100
            output_tokens: int = 20
        class Fake:
            async def get_response(self):
                return SimpleNamespace(usage=Usage(), response_id='response-test', request_id='request-test')
        class Fail:
            async def get_response(self):
                raise TimeoutError('secret must not be logged')
        with tempfile.TemporaryDirectory() as tmp:
            p = pricing_snapshot('aihubmix', 'gpt-5.4-mini')
            asyncio.run(MeteredModel(Fake(), tmp, 'analyst', 'aihubmix', 'gpt-5.4-mini', p).get_response())
            with self.assertRaises(TimeoutError):
                asyncio.run(MeteredModel(Fail(), tmp, 'reviewer', 'aihubmix', 'gpt-5.4-mini', p).get_response())
            report = summarize(tmp)
            self.assertEqual(report['requests'], 2)
            self.assertEqual(report['unknown_cost_requests'], 1)
            self.assertNotIn('secret', json.dumps(report))
            self.assertEqual(len(list(Path(tmp).glob('*-start.json'))), 2)

    def test_cancelled_request_is_recorded(self):
        class Cancel:
            async def get_response(self):
                raise asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(MeteredModel(Cancel(), tmp, 'a', 'unknown', 'm', None).get_response())
            self.assertEqual(summarize(tmp)['unknown_cost_requests'], 1)

    def test_default_envelope_rejection_precedes_reservation_and_inner_call(self):
        class Never:
            async def get_response(self, **kwargs):
                raise AssertionError('Oversized request must not reach provider')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            budget = RunBudget(root/'budget.sqlite', None, enforce=False)
            model = MeteredModel(Never(), root/'calls', 'review', 'aihubmix', 'gpt-5.4-mini',
                pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget)
            with self.assertRaisesRegex(RequestEnvelopeTooLarge, '400000 bytes') as error:
                asyncio.run(model.get_response(input='x' * 400000,
                    model_settings=SimpleNamespace(max_tokens=100)))
            self.assertIsInstance(error.exception, BudgetExceeded)
            self.assertEqual(budget.summary()['requests'], 0)
            self.assertEqual(list((root/'calls').iterdir()), [])

    def test_explicit_capacity_accepts_boundary_without_changing_estimate(self):
        price = pricing_snapshot('aihubmix', 'gpt-5.4-mini')
        budget = Mock()
        budget.reserve.return_value = 'reservation'
        # A bounded output plus a 500 kB text payload exceeds the historical capacity.
        kwargs = {'input': 'x' * 500000, 'model_settings': SimpleNamespace(max_tokens=100)}
        size = len(json.dumps([(), kwargs], default=lambda value: type(value).__name__,
            ensure_ascii=False).encode())
        from decimal import Decimal
        expected = (Decimal(size + 16000) * Decimal(price['input_per_million'])
            + Decimal(100) * Decimal(price['output_per_million'])) / Decimal(1000000)
        self.assertEqual(reserve_request(budget, price, (), kwargs, max_request_bytes=size),
                         ('reservation', str(expected)))
        budget.reserve.assert_called_once_with(expected)
        budget.reset_mock()
        with self.assertRaises(RequestEnvelopeTooLarge):
            reserve_request(budget, price, (), kwargs, max_request_bytes=size - 1)
        budget.reserve.assert_not_called()

    def test_invalid_capacity_fails_before_reservation_or_meter_directory(self):
        budget = Mock()
        price = pricing_snapshot('aihubmix', 'gpt-5.4-mini')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'calls'
            for value in (0, -1, True, False, None, 2.5, '2500000'):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, 'positive integer'):
                        reserve_request(budget, price, (), {}, max_request_bytes=value)
                    with self.assertRaisesRegex(ValueError, 'positive integer'):
                        MeteredModel(object(), path, 'review', 'aihubmix', 'gpt-5.4-mini',
                                     price, budget, max_request_bytes=value)
            self.assertFalse(path.exists())
        budget.reserve.assert_not_called()
