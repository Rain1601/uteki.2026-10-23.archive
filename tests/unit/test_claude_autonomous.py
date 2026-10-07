"""Native Messages through Uteki's coordinator; fixture behavior, not model quality."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx2 as httpx

from uteki.agents.data_query.autonomous_model import SdkAutonomousPlanner
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.agents.runtime.run_budget import RunBudget
from tests.unit import test_company_coordinator as coordinator_fixtures


class ClaudeAutonomousTests(unittest.TestCase):
    def setUp(self):
        self.fixture = coordinator_fixtures.CompanyCoordinatorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        self.enterContext(patch.dict('os.environ', {'AIHUBMIX_API_KEY': 'offline-claude-key'}))
        self.credentials = self.enterContext(patch(
            'uteki.agents.data_query.autonomous_model.load_provider_key', return_value='offline_fixture'))
        self.requests, self.clients = [], []
        self.config = {'provider': 'aihubmix', 'model': 'claude-sonnet-5-5',
            'reasoning_effort': 'high', 'max_tokens': 4096, 'request_timeout': 15, 'max_retries': 0,
            'budget_ledger': str(self.root/'shared.sqlite'), 'budget_usd': '1',
            'budget_policy': 'enforced', 'max_requests_total': 4}

    def transport(self, handler):
        def factory(**kwargs):
            kwargs['transport'] = httpx.MockTransport(handler)
            client = httpx.AsyncClient(**kwargs)
            self.clients.append(client)
            return client
        return factory

    def response(self, request, text):
        self.requests.append(json.loads(request.content))
        self.assertEqual(str(request.url), 'https://aihubmix.com/v1/messages')
        return httpx.Response(200, json={'id': 'msg-fixture', 'type': 'message',
            'role': 'assistant', 'model': 'claude-sonnet-5-5', 'stop_reason': 'end_turn',
            'content': [{'type': 'thinking', 'thinking': 'private-thinking-not-to-save',
                         'signature': 'private-signature-not-to-save'}, {'type': 'text', 'text': text}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}})

    def test_coordinator_native_route_uses_host_query_and_seals_traceable_evidence(self):
        actions = iter(self.fixture.numeric_actions())
        def handler(request):
            body = json.loads(request.content)
            packet = json.loads(body['messages'][0]['content'])
            action = next(actions)
            return self.response(request, json.dumps(action(packet) if callable(action) else action))
        factory = self.transport(handler)
        def planner(*args, **kwargs):
            return SdkAutonomousPlanner(*args, **kwargs, client_factory=factory)
        with patch('uteki.agents.data_query.autonomous_model.SdkAutonomousPlanner', side_effect=planner):
            result = asyncio.run(self.fixture.coordinator.query({
                'question': 'Provide FY2025 revenue and operating margin.',
                'company_config': self.fixture.config, 'include_candidates': True,
                'limits': {'max_steps': 3, 'turn_timeout': 30}}, model_config=self.config,
                credential_root=self.root, output=self.root/'run', observation_root=self.root/'observations'))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['active_scope']['company_ids'], ['sec-0000000123'])
        self.assertEqual(len(self.requests), 3)
        for body in self.requests:
            self.assertEqual(body['thinking'], {'type': 'adaptive'})
            self.assertEqual(body['output_config'], {'effort': 'high'})
            self.assertFalse(body['stream'])
            self.assertTrue(set(body).isdisjoint({'tools', 'temperature', 'top_p', 'top_k', 'seed'}))
        checked = inspect_run(self.root/'run')
        self.assertEqual(checked['status'], 'verified')
        receipt = json.loads((self.root/'run/query/turn-002/query-receipt.json').read_text())
        self.assertTrue(receipt['result']['computed_facts'])
        self.assertTrue(receipt['result']['evidence'])
        usage = json.loads((self.root/'run/model-usage.json').read_text())['summary']
        self.assertEqual(usage['calls']['requests'], 3)
        self.assertEqual(usage['calls']['unknown_cost_requests'], 0)
        self.assertEqual(usage['shared_budget']['estimated_spent_usd'], '0.0021')
        for record in usage['calls']['records']:
            snapshot = record['configuration_snapshot']
            self.assertEqual(snapshot['capture_layer'], 'http_request_before_dispatch')
            self.assertEqual(snapshot['fields']['api_format']['value'], 'anthropic_messages')
            self.assertEqual(snapshot['fields']['temperature']['status'], 'not_sent')
        saved = '\n'.join(p.read_text() for p in self.root.rglob('*.json'))
        self.assertNotIn('private-thinking-not-to-save', saved)
        self.assertNotIn('private-signature-not-to-save', saved)
        self.assertNotIn('offline-claude-key', saved)
        self.assertTrue(all(c.is_closed for c in self.clients))
        self.fixture.assert_closed()

    def test_invalid_native_json_records_visible_output_and_cost_for_host_feedback(self):
        budget = RunBudget(self.root/'budget.sqlite', '1')
        planner = SdkAutonomousPlanner('aihubmix', 'claude-sonnet-5-5', budget=budget,
            max_requests_total=2, output=self.root/'model', credentials_root=self.root,
            reasoning_effort='high', client_factory=self.transport(
                lambda request: self.response(request, 'invalid decision text')))
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'invalid_model_decision'):
                    await planner.decide({'question': 'Explicit synthetic request'})
            finally:
                await planner.aclose()
        asyncio.run(run())
        self.assertEqual(budget.summary()['estimated_spent_usd'], '0.0007')
        self.assertEqual(budget.summary()['unknown_requests'], 0)
        output, = list((self.root/'model').glob('decision-*-output.json'))
        self.assertEqual(json.loads(output.read_text())['content'], 'invalid decision text')
        self.assertEqual(len(self.requests), 1)

    def test_unsupported_native_profile_fails_before_credentials_or_artifacts(self):
        for index, update in enumerate(({'reasoning_effort': None}, {'reasoning_effort': 'max'},
                                        {'max_retries': 1}, {'model': 'claude-unknown', 'reasoning_effort': 'high'})):
            config = {**self.config, **update}
            with self.subTest(update=update), self.assertRaises(ValueError):
                CompanyDataCoordinator._planner(config, self.root/f'invalid-{index}', self.root)
            self.assertFalse((self.root/f'invalid-{index}').exists())
        self.credentials.assert_not_called()


if __name__ == '__main__':
    unittest.main()
