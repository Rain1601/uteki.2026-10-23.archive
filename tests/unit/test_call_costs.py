import asyncio
from dataclasses import dataclass
import json
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uteki.agents.call_costs import MeteredModel, estimate, pricing_snapshot, summarize
from uteki.agents.run_budget import BudgetExceeded, RequestEnvelopeTooLarge, RunBudget, reserve_request
from uteki.agents.runtime.call_costs import estimate_anthropic_usage


class CostTests(unittest.TestCase):
    def test_registered_claude_prices_support_bounded_budget_without_alias_fallback(self):
        from decimal import Decimal
        with tempfile.TemporaryDirectory() as tmp:
            for model, input_rate, output_rate, expected in (
                    ('claude-opus-5-5', '4', '20', '24'),
                    ('claude-sonnet-5-5', '2', '10', '12')):
                with self.subTest(model=model):
                    price = pricing_snapshot('aihubmix', model)
                    self.assertEqual(price['input_per_million'], input_rate)
                    self.assertEqual(price['output_per_million'], output_rate)
                    self.assertEqual(price['cached_input_per_million'], '0.2')
                    self.assertEqual(price['source'], 'https://aihubmix.com/model/' + model)
                    self.assertEqual(price['checked_on'], '2026-10-06')
                    self.assertEqual(estimate({'input_tokens': 1000000, 'output_tokens': 1000000,
                        'input_tokens_details': {'cached_tokens': 1000000}}, price), expected)
                    budget = RunBudget(Path(tmp)/(model + '.sqlite'), '0.10')
                    token, reserved = reserve_request(budget, price, (), {
                        'input': 'Synthetic tool probe', 'model_settings': SimpleNamespace(max_tokens=1000)})
                    self.assertGreater(Decimal(reserved), 0)
                    self.assertLessEqual(Decimal(reserved), Decimal('0.10'))
                    self.assertEqual(budget.summary()['in_flight_requests'], 1)
                    budget.settle(token, estimate({'input_tokens': 100, 'output_tokens': 20}, price))
                    self.assertEqual(budget.summary()['unknown_requests'], 0)
                    self.assertEqual(budget.summary()['in_flight_requests'], 0)
            self.assertIsNone(pricing_snapshot('aihubmix', 'claude-5.5'))
            with self.assertRaises(BudgetExceeded):
                reserve_request(budget, pricing_snapshot('aihubmix', 'claude-5.5'), (), {
                    'model_settings': SimpleNamespace(max_tokens=1000)})

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

    def test_unobserved_invalid_extra_body_preserves_original_failure_and_settlement(self):
        class Reject:
            async def get_response(self, **kwargs):
                raise ValueError('invalid fixture settings')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            budget = RunBudget(root/'budget.sqlite', '1')
            model = MeteredModel(Reject(), root/'calls', 'planner', 'aihubmix', 'gpt-5.4-mini',
                pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget)
            with self.assertRaisesRegex(ValueError, 'invalid fixture settings'):
                asyncio.run(model.get_response(model_settings=SimpleNamespace(max_tokens=100, extra_body=['invalid'])))
            self.assertEqual(budget.summary()['in_flight_requests'], 0)
            self.assertEqual(budget.summary()['unknown_requests'], 1)
            self.assertEqual(summarize(root/'calls')['records'][0]['error_type'], 'ValueError')

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

    def test_native_exact_body_capacity_and_price_include_schema_without_double_encoding(self):
        from decimal import Decimal
        body = json.dumps({'system':'Schema: {"properties":{"answer":{"type":"string"}}}',
                           'messages':[{'role':'user','content':'Quoted "value" and 中文'}]}).encode()
        budget = Mock()
        budget.reserve.return_value = 'bounded'
        price = pricing_snapshot('aihubmix','claude-sonnet-5-5')
        kwargs = {'input':body.decode(), 'model_settings':SimpleNamespace(max_tokens=24000)}
        expected = (Decimal(len(body)+16000)*2+Decimal(24000)*10)/1000000
        self.assertEqual(reserve_request(budget,price,(),kwargs,serialized_body=body,max_request_bytes=len(body)),
                         ('bounded',str(expected)))
        budget.reserve.assert_called_once_with(expected)
        budget.reset_mock()
        with self.assertRaises(RequestEnvelopeTooLarge):
            reserve_request(budget,price,(),kwargs,serialized_body=body,max_request_bytes=len(body)-1)
        with self.assertRaisesRegex(ValueError,'exact request bytes'):
            reserve_request(budget,price,(),kwargs,serialized_body=body.decode())
        budget.reserve.assert_not_called()


class NativeClaudeCostTests(unittest.TestCase):
    """Known raw usage is charged even when the provider answer is unusable."""

    def execute(self, root, *, usage, stop='end_turn', text='{"action":"inspect"}', timeout=False,
                model_settings=None):
        from agents import Agent, ModelSettings, Runner, RunConfig
        from agents.agent_output import AgentOutputSchema
        from pydantic import BaseModel
        import httpx2 as httpx
        from uteki.agents.runtime.claude_messages import ClaudeMessagesModel
        class Decision(BaseModel):
            action: str
        self.requests = []
        def respond(request):
            self.requests.append(request)
            if timeout:
                raise httpx.ReadTimeout('offline-secret-key', request=request)
            return httpx.Response(200, headers={'request-id': 'req_native'}, json={
                'id': 'msg_native', 'model': 'claude-sonnet-5-5', 'stop_reason': stop, 'usage': usage,
                'content': [{'type': 'thinking', 'thinking': 'HIDDEN_PRIVATE', 'signature': 'OPAQUE_SIGNATURE'},
                            {'type': 'text', 'text': text}]})
        def factory(**kwargs):
            kwargs['transport'] = httpx.MockTransport(respond)
            return httpx.AsyncClient(**kwargs)
        self.budget = RunBudget(root/'budget.sqlite', '2')
        price = pricing_snapshot('aihubmix', 'claude-sonnet-5-5')
        async def invoke():
            self.inner = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, client_factory=factory)
            try:
                model = MeteredModel(self.inner, root/'calls', 'planner', 'aihubmix', 'claude-sonnet-5-5', price, self.budget)
                agent = Agent(name='Planner', instructions='Use explicit source evidence.', model=model,
                    model_settings=model_settings or ModelSettings(max_tokens=1000),
                    output_type=AgentOutputSchema(Decision, strict_json_schema=False))
                return await Runner.run(agent, 'One source packet', max_turns=1,
                                        run_config=RunConfig(tracing_disabled=True))
            finally:
                await self.inner.aclose()
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-secret-key'}):
            return asyncio.run(invoke())

    def test_native_usage_cache_and_configuration_match_actual_request(self):
        from decimal import Decimal
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute(root, usage={'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 10})
            row = summarize(root/'calls')['records'][0]
            self.assertEqual(row['estimated_usd'], '0.000402')
            self.assertEqual(row['usage']['input_tokens'], 100)
            self.assertEqual(row['usage']['cache_read_input_tokens'], 10)
            self.assertEqual(self.budget.summary()['estimated_spent_usd'], '0.000402')
            self.assertEqual(row['usage_source'], 'provider_raw')
            self.assertEqual(row['request_sha256'], hashlib.sha256(self.requests[0].content).hexdigest())
            body = json.loads(self.requests[0].content)
            config = row['configuration_snapshot']
            self.assertEqual(config['fields']['temperature']['status'], 'not_sent')
            self.assertEqual(config['fields']['reasoning_effort']['value'], 'high')
            self.assertEqual(row['reasoning_effort'], 'high')
            self.assertEqual(config['fingerprints']['system_sha256'], hashlib.sha256(body['system'].encode()).hexdigest())
            minimum = (Decimal(len(self.requests[0].content) + 16000) * 2 + Decimal(1000) * 10) / 1000000
            self.assertEqual(Decimal(row['reserved_usd']), minimum)
            self.assertIn('"action"', body['system'])
            saved = ''.join(p.read_text() for p in (root/'calls').glob('*.json'))
            for hidden in ('offline-secret-key', 'HIDDEN_PRIVATE', 'OPAQUE_SIGNATURE', 'One source packet'):
                self.assertNotIn(hidden, saved)
            self.assertEqual(len(self.requests), 1)

    def test_truncated_and_invalid_schema_responses_settle_known_cost(self):
        from agents.exceptions import ModelBehaviorError
        for stop, text in (('max_tokens', '{"action":"inspect"}'), ('end_turn', '{"wrong":true}')):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(ModelBehaviorError):
                    self.execute(root, usage={'input_tokens': 100, 'output_tokens': 20}, stop=stop, text=text)
                row = summarize(root/'calls')['records'][0]
                self.assertEqual(row['status'], 'failed_or_cancelled')
                self.assertEqual(row['stop_reason'], stop)
                self.assertEqual(row['estimated_usd'], '0.0004')
                self.assertEqual(self.budget.summary()['unknown_requests'], 0)

    def test_missing_malformed_or_unpriced_usage_holds_budget(self):
        for usage in (None, {}, {'input_tokens': 10}, {'input_tokens': True, 'output_tokens': 20},
                      {'input_tokens': 10, 'output_tokens': 20, 'cache_read_input_tokens': 'bad'},
                      {'input_tokens': 10, 'output_tokens': 20, 'cache_write_input_tokens': 5},
                      {'input_tokens': 10, 'output_tokens': 20, 'server_tool_use': {'web_search_requests': 1}},
                      {'input_tokens': 10, 'output_tokens': 20, 'cache_creation_input_tokens': 5},
                      {'input_tokens': 10, 'output_tokens': 20, 'cache_creation': {'ephemeral_1h_input_tokens': 5}}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.execute(root, usage=usage)
                self.assertIsNone(summarize(root/'calls')['records'][0]['estimated_usd'])
                self.assertEqual(self.budget.summary()['unknown_requests'], 1)
                with self.assertRaises(BudgetExceeded):
                    self.budget.reserve('0.001')

    def test_reported_zero_is_distinct_from_missing_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute(root, usage={'input_tokens': 0, 'output_tokens': 0})
            row = summarize(root/'calls')['records'][0]
            self.assertEqual(row['usage_presence'], 'reported')
            self.assertEqual(row['estimated_usd'], '0')
            self.assertEqual(self.budget.summary()['unknown_requests'], 0)

    def test_unsupported_settings_precede_budget_and_http(self):
        from agents import ModelSettings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                self.execute(root, usage=None, model_settings=ModelSettings(max_tokens=1000, temperature=0))
            self.assertEqual(self.requests, [])
            self.assertEqual(self.budget.summary()['requests'], 0)
            self.assertEqual(list((root/'calls').glob('*.json')), [])

    def test_timeout_is_unknown_with_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(TimeoutError):
                self.execute(root, usage=None, timeout=True)
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.budget.summary()['unknown_requests'], 1)
            row = summarize(root/'calls')['records'][0]
            self.assertEqual(row['transport_error_type'], 'ReadTimeout')
            self.assertIsNone(row['estimated_usd'])
            self.assertNotIn('offline-secret-key', json.dumps(summarize(root/'calls')))

    def test_absent_cache_price_and_invalid_rates_fail_closed(self):
        price = pricing_snapshot('aihubmix', 'claude-sonnet-5-5')
        usage = {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 10}
        self.assertIsNone(estimate_anthropic_usage(usage, price | {'cached_input_per_million': None}))
        self.assertIsNone(estimate_anthropic_usage(usage, price | {'input_per_million': 'NaN'}))
        self.assertIsNone(estimate_anthropic_usage(usage | {'cache_write_input_tokens': 5}, price))
