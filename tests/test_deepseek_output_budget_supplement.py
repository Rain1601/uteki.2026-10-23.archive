"""One scoped supplemental request through the real SDK and synthetic HTTP only."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI

from tests import test_small_model_comparison as original_test


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'experiments/model_comparison/2026-10-07-deepseek-output-budget-v2/run_supplement.py'
spec = importlib.util.spec_from_file_location('deepseek_supplement', SCRIPT)
supplement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supplement)


class DeepSeekOutputBudgetSupplementTests(unittest.TestCase):
    def test_one_pinned_high_24k_call_with_remaining_budget_and_no_gold_or_secret(self):
        # Reuse the independent Cedar evidence fixture, not the experiment reference answers.
        fixture = original_test.SmallModelComparisonTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, expected_messages, input_metadata = original_test.runner.load_prepared(fixture.prepared)
        pins = {key: input_metadata[key] for key in supplement.INPUT_PINS}
        prior = {'input': input_metadata, 'budget': {'unknown_requests': 0, 'in_flight_requests': 0,
                 'held_usd': '0', 'estimated_spent_usd': supplement.PRIOR_SPENT_USD}}
        prior_bytes = json.dumps(prior).encode()
        prior_path = fixture.root / 'prior-summary.json'
        prior_path.write_bytes(prior_bytes)
        requests, clients, key_providers, configurations = [], [], [], []
        secret = 'test-deepseek-supplement-SECRET'

        def respond(request):
            requests.append(json.loads(request.content))
            payload = fixture.payload()
            payload['usage'] = {'prompt_tokens': 1000, 'completion_tokens': 1000,
                                'completion_tokens_details': {'reasoning_tokens': 900}}
            payload['model'] = secret
            return httpx.Response(200, json=payload, headers={'x-request-id': 'supplement-mock'})

        def factory(**kwargs):
            configurations.append({key: value for key, value in kwargs.items() if key != 'api_key'})
            client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
            clients.append(client)
            return client

        output = fixture.root / 'supplement'
        with patch.multiple(supplement, PREPARED=fixture.prepared, ORIGINAL_SUMMARY=prior_path,
                            SUMMARY_SHA256=hashlib.sha256(prior_bytes).hexdigest(), INPUT_PINS=pins), \
             patch.dict(os.environ, {'DEEPSEEK_API_KEY': secret}):
            module, audit = supplement.load_configuration()
            self.assertEqual(audit['inspection']['budget_limit_usd'], '0.14895104')
            self.assertEqual(len(audit['inspection']['arms']), 1)
            self.assertEqual(module.MAX_TOKENS, 24000)
            self.assertEqual(original_test.runner.MAX_TOKENS, 4000)
            result = asyncio.run(supplement.run_supplement(output,
                client_factory=factory, key_loader=lambda root, provider: key_providers.append(provider)))
            with self.assertRaises(FileExistsError):
                asyncio.run(supplement.run_supplement(output,
                    client_factory=factory, key_loader=lambda *_: self.fail('No second credential load')))
        self.assertEqual(key_providers, ['deepseek'])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['model'], 'deepseek-v4-pro')
        self.assertEqual(requests[0]['max_tokens'], 24000)
        self.assertEqual(requests[0]['thinking'], {'type': 'enabled'})
        self.assertEqual(requests[0]['reasoning_effort'], 'high')
        self.assertEqual(requests[0]['messages'], expected_messages)
        self.assertEqual(configurations, [{'base_url': 'https://api.deepseek.com', 'max_retries': 0, 'timeout': 180}])
        self.assertTrue(all(client.is_closed() for client in clients))
        self.assertEqual(result['budget']['limit_usd'], '0.14895104')
        self.assertEqual(result['budget']['estimated_spent_usd'], '0.00528')
        self.assertEqual(result['combined_estimated_spent_usd'], '0.05632896')
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('PRIVATE_GOLD', json.dumps(requests))
        self.assertNotIn('NEVER_SEND_REFERENCE_HASH', json.dumps(requests))
        self.assertNotIn(secret, json.dumps(result))
        for path in output.rglob('*.json'):
            text = path.read_text()
            self.assertNotIn(secret, text)
            self.assertNotIn('PRIVATE_REASONING_MUST_NOT_BE_SAVED', text)
        config = json.loads((output / 'configuration.json').read_text())
        self.assertEqual(config['original_runner_sha256'], supplement.RUNNER_SHA256)
        self.assertEqual(config['pricing_snapshot']['checked_on'], '2026-10-07')
        self.assertEqual(config['overrides']['automatic_retries'], 0)


if __name__ == '__main__':
    unittest.main()
