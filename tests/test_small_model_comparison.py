"""Independent, synthetic evidence and real SDK requests through MockTransport only."""
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'experiments/model_comparison/2026-10-06-sonnet-deepseek-small-v1/run_comparison.py'
spec = importlib.util.spec_from_file_location('small_model_comparison', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SmallModelComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared = self.root / 'prepared'
        self.prepared.mkdir()
        self.output = self.root / 'result'
        self.text = 'r2: c0: Operating cash flow | c3..4: 17 | c9..10: 11'
        self.packet = {
            'schema_version': 'bounded-model-comparison-packet-v1',
            'scope': {'company_id': 'synthetic-cedar', 'source_snapshot_ids': ['cedar-2031'],
                      'comparison_years': [2031, 2030], 'currency': 'USD',
                      'comparison_periods': [{'fiscal_year': 2031, 'period_end': '2031-06-30'},
                                             {'fiscal_year': 2030, 'period_end': '2030-06-30'}]},
            'source': {'source_snapshot_id': 'cedar-2031'},
            'task': 'Extract the explicitly scoped cash flow and explain evidence limits.',
            'blocks': [{'block_id': 'cedar-table', 'text': self.text,
                        'text_hash': hashlib.sha256(self.text.encode()).hexdigest()}]}
        self.pin_packet()
        (self.prepared / 'reference-review.json').write_text('PRIVATE_GOLD_MUST_NOT_BE_SENT')
        self.answer = {'facts': [{'metric': 'operating_cash_flow', 'period': '2031',
            'period_end': '2031-06-30', 'value': 17, 'unit': 'million', 'currency': 'USD',
            'block_id': 'cedar-table', 'row': 2, 'column': 'c3..4', 'quote': self.text}],
            'analysis': [{'claim': '仅节选支持这个结论。', 'block_ids': ['cedar-table']}],
            'gaps': ['未覆盖其他期间。', '无法判断未来现金流。']}
        self.requests = []
        self.clients = []
        self.factory_kwargs = []
        self.responses = []
        self.keys = {'AIHUBMIX_API_KEY': 'fake-aihubmix-SECRET', 'DEEPSEEK_API_KEY': 'fake-deepseek-SECRET'}

    def pin_packet(self):
        text = json.dumps(self.packet)
        (self.prepared / 'packet.json').write_text(text)
        (self.prepared / 'manifest.json').write_text(json.dumps({
            'packet_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'reference_sha256': 'NEVER_SEND_REFERENCE_HASH'}))

    def payload(self, *, usage=True, finish='stop', answer=None):
        result = {'id': 'response-example', 'object': 'chat.completion', 'created': 1,
                  'model': 'provider-returned-pinned-version',
                  'choices': [{'index': 0, 'finish_reason': finish, 'message': {
                      'role': 'assistant', 'content': json.dumps(answer if answer is not None else self.answer),
                      'reasoning_content': 'PRIVATE_REASONING_MUST_NOT_BE_SAVED'}}]}
        if usage:
            result['usage'] = {'prompt_tokens': 200, 'completion_tokens': 100, 'total_tokens': 300,
                               'prompt_tokens_details': {'cached_tokens': 20},
                               'completion_tokens_details': {'reasoning_tokens': 30},
                               'private_extra': 'DO_NOT_SAVE_USAGE_EXTRA'}
        return result

    def execute(self):
        def respond(request):
            self.requests.append(json.loads(request.content))
            response = self.responses.pop(0) if self.responses else self.payload()
            if isinstance(response, Exception):
                raise response
            if isinstance(response, tuple):
                return httpx.Response(response[0], json=response[1])
            return httpx.Response(200, json=response, headers={
                'x-request-id': 'request-safe', 'x-private-header': 'DO_NOT_SAVE_HEADER'})

        def factory(**kwargs):
            self.factory_kwargs.append({k: v for k, v in kwargs.items() if k != 'api_key'})
            client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
            self.clients.append(client)
            return client

        with patch.dict(os.environ, self.keys):
            result = asyncio.run(runner.run_comparison(self.prepared, self.output,
                root=self.root, client_factory=factory, key_loader=lambda *_: None))
        self.assertTrue(all(client.is_closed() for client in self.clients))
        return result

    def saved_text(self):
        return '\n'.join(path.read_text() for path in self.output.rglob('*')
                         if path.is_file() and path.suffix in {'.json', '.txt'})

    def test_two_arms_same_prompt_no_reference_no_tools_no_store(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.requests), 2)
        first, second = self.requests
        self.assertEqual(first['messages'], second['messages'])
        self.assertEqual(first['model'], 'claude-sonnet-5-5')
        self.assertEqual(second['model'], 'deepseek-v4-pro')
        self.assertEqual(second['thinking'], {'type': 'enabled'})
        self.assertEqual(second['reasoning_effort'], 'high')
        self.assertNotIn('thinking', first)
        for request in self.requests:
            self.assertEqual(request['max_tokens'], 4000)
            self.assertNotIn('tools', request)
            self.assertNotIn('store', request)
            self.assertNotIn('temperature', request)
            self.assertNotIn('PRIVATE_GOLD', json.dumps(request))
            self.assertNotIn('NEVER_SEND_REFERENCE_HASH', json.dumps(request))
        self.assertTrue(all(item['max_retries'] == 0 and item['timeout'] == 90 for item in self.factory_kwargs))
        self.assertEqual(result['budget']['unknown_requests'], 0)
        self.assertEqual(result['budget']['estimated_spent_usd'], '0.00206')
        self.assertEqual(result['arms'][0]['returned_model'], 'provider-returned-pinned-version')
        self.assertEqual(result['arms'][0]['raw_usage']['prompt_tokens_details']['cached_tokens'], 20)
        for text in ['PRIVATE_REASONING', 'DO_NOT_SAVE_HEADER', 'DO_NOT_SAVE_USAGE_EXTRA']:
            self.assertNotIn(text, self.saved_text())

    def test_http_failure_stops_without_retry_and_keeps_unknown_reservation(self):
        self.responses = [(503, {'error': {'message': 'fake-aihubmix-SECRET raw error', 'type': 'service_error'}})]
        result = self.execute()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'stopped_request_failure')
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertEqual(result['arms'][0]['http_status'], 503)
        self.assertNotIn('raw error', self.saved_text())
        self.assertNotIn('fake-aihubmix-SECRET', self.saved_text())
        self.assertFalse((self.output / '02-deepseek').exists())

    def test_absent_usage_stops_after_recording_visible_response(self):
        self.responses = [self.payload(usage=False)]
        result = self.execute()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'stopped_usage_unknown')
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertIsNone(result['arms'][0]['estimated_usd'])
        self.assertTrue((self.output / '01-sonnet/visible-output.txt').is_file())

    def test_absolute_request_timeout_stops_and_closes_client(self):
        async def slow_response(request):
            self.requests.append(json.loads(request.content))
            await asyncio.sleep(0.2)
            return httpx.Response(200, json=self.payload())

        def factory(**kwargs):
            client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(slow_response)))
            self.clients.append(client)
            return client

        with patch.dict(os.environ, self.keys), patch.object(runner, 'TIMEOUT_SECONDS', 0.01):
            result = asyncio.run(runner.run_comparison(self.prepared, self.output,
                client_factory=factory, key_loader=lambda *_: None))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['arms'][0]['error_type'], 'TimeoutError')
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertTrue(all(client.is_closed() for client in self.clients))

    def test_invalid_raw_usage_is_unknown_but_explicit_zero_is_reported(self):
        for usage in ({'prompt_tokens': True, 'completion_tokens': 2},
                      {'prompt_tokens': -1, 'completion_tokens': 2},
                      {'prompt_tokens': 1, 'completion_tokens': '2'},
                      {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': -3},
                      {'prompt_tokens': 1, 'completion_tokens': 2,
                       'completion_tokens_details': {'reasoning_tokens': True}}):
            self.assertIsNone(runner.select_usage(usage))
        self.assertEqual(runner.select_usage({'prompt_tokens': 0, 'completion_tokens': 0}),
                         {'prompt_tokens': 0, 'completion_tokens': 0})

    def test_invalid_quote_and_truncation_are_invalid_without_repair_calls(self):
        bad = json.loads(json.dumps(self.answer))
        bad['facts'][0]['quote'] = 'invented source text'
        self.responses = [self.payload(answer=bad), self.payload(finish='length')]
        result = self.execute()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'completed_with_invalid_outputs')
        self.assertIn('quote_not_in_block', result['arms'][0]['validation']['errors'])
        self.assertIn('non_stop_finish_reason', result['arms'][1]['validation']['errors'])
        self.assertTrue(all(arm['validation']['gold_scoring'] == 'not_performed' for arm in result['arms']))

    def test_cross_scope_and_bad_cell_coordinates_are_invalid(self):
        for field, value, error in [('block_id', 'other-company-table', 'fact_block_outside_scope'),
                                    ('period', '2029', 'fact_period_outside_scope'),
                                    ('period_end', '2031-12-31', 'fact_period_end_outside_scope'),
                                    ('currency', 'EUR', 'fact_currency_outside_scope'),
                                    ('row', 10, 'quote_or_column_outside_row'),
                                    ('column', 'c99', 'quote_or_column_outside_row')]:
            bad = json.loads(json.dumps(self.answer))
            bad['facts'][0][field] = value
            report, _ = runner.validate_output(json.dumps(bad), self.packet, 'stop')
            self.assertIn(error, report['errors'])

    def test_hash_change_rejected_before_credentials_or_output(self):
        with (self.prepared / 'packet.json').open('a') as stream:
            stream.write(' ')
        with patch.object(runner, 'AsyncOpenAI') as client, patch.object(runner, 'load_provider_key') as keys:
            with self.assertRaises(ValueError):
                asyncio.run(runner.run_comparison(self.prepared, self.output))
        client.assert_not_called()
        keys.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_block_hash_and_company_conflict_rejected(self):
        self.packet['blocks'][0]['text_hash'] = '0' * 64
        self.pin_packet()
        with self.assertRaises(ValueError):
            runner.inspect_prepared(self.prepared)
        self.packet['blocks'][0]['text_hash'] = hashlib.sha256(self.text.encode()).hexdigest()
        self.packet['blocks'][0]['company_id'] = 'other-company'
        self.pin_packet()
        with self.assertRaises(ValueError):
            runner.inspect_prepared(self.prepared)

    def test_source_or_manifest_block_conflict_rejected(self):
        self.packet['source']['source_snapshot_id'] = 'other-source'
        self.pin_packet()
        with self.assertRaises(ValueError):
            runner.inspect_prepared(self.prepared)
        self.packet['source']['source_snapshot_id'] = 'cedar-2031'
        self.pin_packet()
        manifest_path = self.prepared / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['input_block_ids'] = ['another-block']
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            runner.inspect_prepared(self.prepared)

    def test_secret_redacted_in_visible_output_and_returned_metadata_and_logs_disabled(self):
        payload = self.payload()
        payload['model'] = self.keys['AIHUBMIX_API_KEY']
        payload['choices'][0]['message']['content'] = self.keys['DEEPSEEK_API_KEY']
        self.responses = [payload]
        result = self.execute()
        self.assertEqual(result['status'], 'completed_with_invalid_outputs')
        for secret in self.keys.values():
            self.assertNotIn(secret, self.saved_text())
            self.assertNotIn(secret, json.dumps(result))
        self.assertIn('[REDACTED]', self.saved_text())
        with runner.quiet_sdk():
            self.assertEqual(logging.root.manager.disable, logging.CRITICAL)

    def test_existing_output_rejected_without_model_requests(self):
        self.output.mkdir()
        marker = self.output / 'marker.txt'
        marker.write_text('preserve')
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertEqual(self.requests, [])

    def test_dry_inspection_does_not_load_credentials_or_use_network(self):
        with patch.object(runner, 'load_provider_key', side_effect=AssertionError), \
             patch.object(runner, 'AsyncOpenAI', side_effect=AssertionError):
            result = runner.inspect_prepared(self.prepared)
        self.assertEqual(result['budget_limit_usd'], '0.20')
        self.assertEqual(result['block_count'], 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(result['arms']), 2)


if __name__ == '__main__':
    unittest.main()
