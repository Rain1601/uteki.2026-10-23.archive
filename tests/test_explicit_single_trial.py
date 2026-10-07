"""Check the actual outgoing wire request with independent synthetic evidence."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx2 as httpx

from tests import test_small_model_comparison as original_tests

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'experiments/model_comparison/2026-10-07-explicit-single-trial-v1'
spec = importlib.util.spec_from_file_location('explicit_single_trial', FOLDER / 'run_once.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ExplicitSingleTrialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = original_tests.SmallModelComparisonTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.requests = []
        self.secret = 'fake-explicit-trial-secret'

    def execute(self, profile, response, *, output=None, budget_path=None):
        def respond(request):
            self.requests.append(request)
            return response
        def client(**kwargs):
            return httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(respond))
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': self.secret, 'DEEPSEEK_API_KEY': self.secret}):
            path = profile if isinstance(profile, Path) else FOLDER / 'profiles' / (profile+'.json')
            return asyncio.run(runner.run_once(path,
                self.fixture.prepared, output or self.fixture.output, '0.30', client_factory=client,
                key_loader=lambda *_: None, budget_path=budget_path))

    def test_sonnet_native_wire_and_frozen_configuration_match(self):
        payload = {'id': 'msg-safe', 'model': 'claude-sonnet-5-5', 'stop_reason': 'end_turn',
            'content': [{'type': 'thinking', 'thinking': 'PRIVATE_REASONING'},
                        {'type': 'text', 'text': json.dumps(self.fixture.answer)}],
            'usage': {'input_tokens': 100, 'output_tokens': 90, 'cache_read_input_tokens': 20,
                      'output_tokens_details': {'thinking_tokens': 30}}}
        result = self.execute('sonnet-native-high-8k', httpx.Response(200, json=payload,
            headers={'request-id': 'request-safe'}))
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://aihubmix.com/v1/messages')
        self.assertEqual(request.headers['anthropic-version'], '2023-06-01')
        body = json.loads(request.content)
        self.assertEqual(body['thinking'], {'type': 'adaptive'})
        self.assertEqual(body['output_config'], {'effort': 'high'})
        self.assertEqual(body['max_tokens'], 8000)
        self.assertEqual(json.loads(body['messages'][0]['content'])['scope']['company_id'], 'synthetic-cedar')
        self.assertNotIn('PRIVATE_GOLD', str(body))
        self.assertEqual(result['status'], 'completed')
        call = result['arms'][0]
        self.assertEqual((call['response_id'], call['request_id'], call['http_status']), ('msg-safe', 'request-safe', 200))
        self.assertEqual(call['raw_usage']['prompt_tokens'], 120)
        self.assertEqual(call['raw_usage']['completion_tokens_details']['reasoning_tokens'], 30)
        start = json.loads((self.fixture.output/'01-model/start.json').read_text())
        self.assertEqual(call['configuration_snapshot'], start['configuration_snapshot'])
        fields = call['configuration_snapshot']['fields']
        self.assertEqual(fields['reasoning_effort']['value'], 'high')
        self.assertEqual(fields['temperature']['status'], 'not_sent')
        self.assertEqual(call['configuration_snapshot']['effective_configuration'], 'unverified')
        text = '\n'.join(f.read_text() for f in self.fixture.output.rglob('*.json'))
        self.assertNotIn(self.secret, text)
        self.assertNotIn('PRIVATE_REASONING', text)
        with self.assertRaises(FileExistsError):
            self.execute('sonnet-native-high-8k', httpx.Response(200,json=payload))
        self.assertEqual(len(self.requests), 1)

    def test_deepseek_low_is_explicit_and_keeps_original_task(self):
        with patch.object(runner, 'prepare', wraps=runner.prepare) as prepare:
            result = self.execute('deepseek-low-16k', httpx.Response(200,json=self.fixture.payload()))
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(result['limits']['configuration_snapshot'], result['arms'][0]['configuration_snapshot'])
        self.assertEqual(len(self.requests), 1)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body['reasoning_effort'], 'low')
        self.assertEqual(body['thinking'], {'type': 'enabled'})
        self.assertEqual(body['max_tokens'], 16000)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['budget']['requests'], 1)
        self.assertEqual(result['arms'][0]['configuration_snapshot']['fields']['api_format'],
                         {'value': 'chat_completions', 'status': 'explicit', 'source': 'http_request'})

    def test_incomplete_profile_blocks_without_credentials_and_http_failure_never_retries(self):
        profile=json.loads((FOLDER/'profiles/sonnet-native-high-8k.json').read_text())
        del profile['reasoning_effort']
        p=self.fixture.root/'bad-profile.json';p.write_text(json.dumps(profile))
        with self.assertRaises(ValueError):
            runner.inspect(p,self.fixture.prepared,'0.3')
        result=self.execute('sonnet-native-high-8k',httpx.Response(503,json={'error':{'message':self.secret}}))
        self.assertEqual(len(self.requests),1)
        self.assertEqual(result['budget']['unknown_requests'],1)
        self.assertEqual(result['status'],'stopped_request_failure')
        self.assertEqual(result['arms'][0]['http_status'],503)
        self.assertNotIn(self.secret,(self.fixture.output/'01-model/failure.json').read_text())

    def test_native_usage_never_prices_unknown_cache_writes_or_invalid_reasoning_as_zero(self):
        self.assertIsNone(runner.native_usage({'usage':{'input_tokens':10,'output_tokens':20,'cache_creation_input_tokens':100}}))
        self.assertIsNone(runner.native_usage({'usage':{'input_tokens':True,'output_tokens':20}}))
        self.assertIsNone(runner.native_usage({'usage':{'input_tokens':10,'output_tokens':20,'output_tokens_details':{'thinking_tokens':21}}}))
        value=runner.native_usage({'usage':{'input_tokens':10,'output_tokens':20}})
        self.assertNotIn('completion_tokens_details',value)

    def test_malformed_provider_receipt_cannot_store_nested_content(self):
        hidden = {'reasoning': 'PRIVATE_NESTED_CONTENT'}
        payload = {'id': hidden, 'model': hidden, 'stop_reason': hidden,
            'content': [{'type': 'text', 'text': json.dumps(self.fixture.answer)}],
            'usage': {'input_tokens': 100, 'output_tokens': 90}}
        result = self.execute('sonnet-native-high-8k', httpx.Response(200, json=payload,
            headers={'request-id': 'x' * 257}))
        call = result['arms'][0]
        for key in ('response_id', 'returned_model', 'request_id', 'provider_finish_reason'):
            self.assertIsNone(call[key])
        self.assertEqual(result['status'], 'completed_with_invalid_outputs')
        self.assertNotIn('PRIVATE_NESTED_CONTENT', '\n'.join(f.read_text() for f in self.fixture.output.rglob('*.json')))

    def test_explicit_sampling_policy_matches_wire_and_rejects_false_controls(self):
        profiles = ROOT/'experiments/model_comparison/2026-10-07-reproducibility-pilot-v1/profiles'
        path = profiles/'deepseek-low-16k-repro.json'
        result = self.execute(path, httpx.Response(200,json=self.fixture.payload()))
        body = json.loads(self.requests[0].content)
        self.assertEqual(body['top_p'], .95)
        for key in ('temperature','top_k','seed'):
            self.assertNotIn(key,body)
        fields=result['arms'][0]['configuration_snapshot']['fields']
        self.assertEqual(fields['top_p']['value'], .95)
        self.assertEqual(fields['temperature']['source'], 'policy.deepseek_thinking_sampling_ignored')
        self.assertEqual(fields['top_k']['status'], 'not_sent')
        for name,key,value in [('sonnet55-high-8k-repro','temperature',0),
                               ('deepseek-low-16k-repro','top_p',.8),
                               ('deepseek-low-16k-repro','seed',42)]:
            profile=json.loads((profiles/(name+'.json')).read_text())
            profile['sampling'][key]=value
            p=self.fixture.root/'unsupported.json';p.write_text(json.dumps(profile))
            with self.assertRaises(ValueError): runner.inspect(p,self.fixture.prepared,'0.3')

    def test_shared_budget_stops_after_an_unknown_request_without_retry(self):
        ledger=self.fixture.root/'shared.sqlite'
        self.execute('sonnet-native-high-8k',httpx.Response(503,json={}),budget_path=ledger)
        from uteki.agents.runtime.run_budget import BudgetExceeded
        with self.assertRaises(BudgetExceeded):
            self.execute('deepseek-low-16k',httpx.Response(200,json=self.fixture.payload()),
                         output=self.fixture.root/'next-output',budget_path=ledger)
        self.assertEqual(len(self.requests),1)
        stopped=json.loads((self.fixture.root/'next-output/summary.json').read_text())
        self.assertEqual(stopped['status'],'stopped_before_dispatch')
        self.assertEqual(stopped['arms'],[])
        arm=self.fixture.output/'01-model'
        self.assertEqual(json.loads((arm/'response-metadata.json').read_text())['status'],'failed')
        self.assertEqual((arm/'visible-output.txt').read_text(),'')


if __name__ == '__main__':
    unittest.main()
