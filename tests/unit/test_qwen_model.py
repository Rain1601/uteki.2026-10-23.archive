"""Qwen adapter/planner through real SDK over mocked HTTP; no paid calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI
from agents.exceptions import ModelBehaviorError

from uteki.agents.data_query.autonomous_model import SdkAutonomousPlanner, reasoning_configuration
from uteki.agents.runtime.call_costs import estimate_qwen_usage, pricing_snapshot, summarize
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.runtime.model_configuration import validate_configuration_snapshot


class QwenPlannerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict('os.environ', {'AIHUBMIX_API_KEY': 'fixture-key'}))
        self.requests = []
        self.content, self.finish = '{"action":"finish"}', 'stop'
        self.usage = {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150,
                      'prompt_tokens_details': {'cached_tokens': 20},
                      'completion_tokens_details': {'reasoning_tokens': 40}}

    def invoke(self, *, effort='low'):
        def respond(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, headers={'x-request-id': 'fixture-request'}, json={
                'id': 'fixture', 'object': 'chat.completion', 'created': 1, 'model': 'qwen3.8-flash',
                'choices': [{'index': 0, 'finish_reason': self.finish, 'message': {
                    'role': 'assistant', 'content': self.content, 'reasoning_content': 'private reasoning'}}],
                'usage': self.usage})
        def factory(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        async def run():
            self.planner = SdkAutonomousPlanner('aihubmix', 'qwen3.8-flash',
                budget=RunBudget(self.root/'cost.sqlite', '1'), max_requests_total=2,
                output=self.root/'model', credentials_root=self.root, max_tokens=8192,
                reasoning_effort=effort, client_factory=factory, purpose='analysis_evidence')
            try:
                return await self.planner.decide({'question': 'Retrieve bounded original evidence.'})
            finally:
                await self.planner.aclose()
        return asyncio.run(run())

    def test_explicit_low_total_output_json_strict_metering_and_config(self):
        self.assertEqual(self.invoke().action, 'finish')
        body = self.requests[0]
        self.assertEqual(body['model'], 'qwen3.8-flash')
        self.assertEqual(body['reasoning_effort'], 'low')
        self.assertEqual(body['max_completion_tokens'], 8192)
        self.assertFalse(body['preserve_thinking'])
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        for key in ('max_tokens','temperature','top_p','thinking','thinking_budget','store'):
            self.assertNotIn(key, body)
        self.assertIn('AutonomousDecision', body['messages'][0]['content'])
        call = summarize(self.root/'model/calls')['records'][0]
        self.assertEqual(call['usage_source'], 'provider_raw')
        self.assertEqual(call['raw_usage'], self.usage)
        self.assertEqual(call['estimated_usd'], '0.00002829')
        self.assertEqual(call['actual_upstream_model'], 'qwen3.8-flash')
        config = validate_configuration_snapshot(call['configuration_snapshot'])
        self.assertEqual(config['fields']['max_completion_tokens']['value'], 8192)
        self.assertIsNone(config['fields']['max_tokens']['value'])
        self.assertEqual(config['fields']['response_format']['value'], {'type': 'json_object'})
        self.assertTrue(self.planner.frozen_config['strict_visible_json'])
        self.assertEqual(self.planner.frozen_config['thinking_mode'], 'enabled')
        persisted = '\n'.join(p.read_text() for p in (self.root/'model').rglob('*.json'))
        self.assertNotIn('private reasoning', persisted)
        self.assertNotIn('fixture-key', persisted)

    def test_duplicate_json_keys_are_rejected_and_preserved(self):
        self.content = '{"action":"gap","action":"finish"}'
        with self.assertRaisesRegex(ValueError, 'invalid_model_decision'):
            self.invoke()
        output = json.loads(next((self.root/'model').glob('decision-*-output.json')).read_text())
        self.assertEqual(output['content'], self.content)
        self.assertEqual(summarize(self.root/'model/calls')['unknown_cost_requests'], 0)

    def test_truncated_json_is_not_executed_but_usage_is_recorded(self):
        self.finish = 'length'
        with self.assertRaises(ModelBehaviorError):
            self.invoke()
        call = summarize(self.root/'model/calls')['records'][0]
        self.assertEqual(call['finish_reason'], 'length')
        self.assertEqual(call['usage']['output_tokens'], 50)
        self.assertNotEqual(call['estimated_usd'], None)

    def test_missing_usage_remains_unknown_not_sdk_zero(self):
        self.usage = None
        self.invoke()
        self.assertEqual(summarize(self.root/'model/calls')['unknown_cost_requests'], 1)
        self.assertEqual(RunBudget(self.root/'cost.sqlite', '1').summary()['unknown_requests'], 1)

    def test_qwen_requires_effort_and_does_not_register_unknown_model_aliases(self):
        for effort in (None, '', 'high', True, []):
            with self.subTest(effort=effort), self.assertRaises(ValueError):
                reasoning_configuration('aihubmix', 'qwen3.8-flash', effort)
        self.assertIsNone(pricing_snapshot('aihubmix', 'qwen-flash'))

    def test_cache_and_reasoning_not_double_counted_unexpected_charges_unknown(self):
        price = pricing_snapshot('aihubmix', 'qwen3.8-flash')
        self.assertEqual(estimate_qwen_usage(self.usage, price), '0.00002829')
        for usage in ({**self.usage, 'cache_creation_input_tokens': 10},
                      {**self.usage, 'prompt_tokens_details': {'cached_tokens': 101}},
                      {**self.usage, 'completion_tokens': None}):
            self.assertIsNone(estimate_qwen_usage(usage, price))


if __name__ == '__main__':
    unittest.main()
