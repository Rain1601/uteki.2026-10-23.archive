"""Claude review/Analysis transport integration; provider calls are HTTP fixtures."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents.exceptions import ModelBehaviorError
import httpx2 as httpx
from pydantic import BaseModel

from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded, RequestEnvelopeTooLarge


class Assessment(BaseModel):
    summary: str
    fact_ids: list[str]


class ClaudeRecordReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict('os.environ', {'AIHUBMIX_API_KEY': 'claude-review-fixture-key'}))
        self.requests, self.clients = [], []
        self.budget = RunBudget(self.root/'budget.sqlite', '1')

    def reviewer(self, *, model='claude-sonnet-5-5', raw=None, stop='end_turn', **kwargs):
        def respond(request):
            self.requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), 'https://aihubmix.com/v1/messages')
            return httpx.Response(200, headers={'request-id': 'review-req-1'}, json={
                'id': 'msg_review_1', 'model': model, 'stop_reason': stop,
                'content': [{'type': 'thinking', 'thinking': 'PRIVATE_HIDDEN_REASONING'},
                            {'type': 'text', 'text': raw if raw is not None else
                             '{"summary":"Supported conclusion","fact_ids":["fact-1"]}'}],
                'usage': {'input_tokens': 100, 'output_tokens': 40}})
        def factory(**options):
            self.assertEqual(options['timeout'], 90)
            options['transport'] = httpx.MockTransport(respond)
            client = httpx.AsyncClient(**options)
            self.clients.append(client)
            return client
        return SdkRecordReviewer('aihubmix', model, budget=self.budget,
            max_requests_total=1, output=self.root/'review', credentials_root=self.root,
            prompt='Analyze only facts in the supplied data handoff.', output_schema=Assessment,
            reasoning_effort='high', request_timeout=90, client_factory=factory, **kwargs)

    def test_sonnet_uses_native_generic_json_and_accounted_raw_output(self):
        self.assert_native_model('claude-sonnet-5-5')

    def test_opus_uses_native_generic_json_and_accounted_raw_output(self):
        self.assert_native_model('claude-opus-5-5')

    def assert_native_model(self, model):
        reviewer = self.reviewer(model=model)
        packet = {'question': 'What changed?', 'facts': [{'id': 'fact-1', 'quote': 'Original fact'}]}
        async def run():
            try: return await reviewer.review(packet)
            finally: await reviewer.aclose()
        result = asyncio.run(run())
        self.assertEqual(result['fact_ids'], ['fact-1'])
        body = self.requests[0]
        self.assertEqual(json.loads(body['messages'][0]['content']), packet)
        self.assertEqual(body['thinking'], {'type': 'adaptive'})
        self.assertEqual(body['output_config'], {'effort': 'high'})
        self.assertFalse(body['stream'])
        self.assertNotIn('temperature', body)
        self.assertNotIn('load_skill', body['system'])
        self.assertNotIn('action field', body['system'])
        self.assertIn('fact_ids', body['system'])
        frozen = reviewer.frozen_config
        self.assertEqual(frozen['api_format'], 'anthropic_messages')
        self.assertEqual(frozen['schema_protocol'], 'json_object')
        attempt = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        self.assertEqual(attempt['response_metadata']['request_id'], 'review-req-1')
        self.assertEqual(json.loads(attempt['raw_text']), result)
        usage = reviewer.snapshot_usage()['summary']
        self.assertEqual(usage['shared_budget']['requests'], 1)
        self.assertEqual(usage['shared_budget']['unknown_requests'], 0)
        self.assertGreater(float(usage['shared_budget']['estimated_spent_usd']), 0)
        saved = '\n'.join(p.read_text() for p in reviewer.output.rglob('*.json'))
        self.assertNotIn('PRIVATE_HIDDEN_REASONING', saved)
        self.assertNotIn('claude-review-fixture-key', saved)
        self.assertTrue(all(c.is_closed for c in self.clients))

    def test_rejected_json_retains_raw_text_and_settles_reported_usage(self):
        raw = '{"summary": "cut off'
        reviewer = self.reviewer(raw=raw, stop='max_tokens')
        async def run():
            try:
                with self.assertRaises(ModelBehaviorError):
                    await reviewer.review({'facts': []})
            finally: await reviewer.aclose()
        asyncio.run(run())
        attempt = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        self.assertEqual(attempt['raw_text'], raw)
        self.assertFalse((reviewer.output/'review-0001-parsed.json').exists())
        self.assertEqual(self.budget.summary()['unknown_requests'], 0)
        self.assertEqual(len(self.requests), 1)

    def test_second_call_cannot_inherit_prior_response_when_budget_rejects(self):
        reviewer = self.reviewer()
        async def run():
            try:
                await reviewer.review({'facts': []})
                with self.assertRaises(BudgetExceeded):
                    await reviewer.review({'facts': []})
            finally: await reviewer.aclose()
        asyncio.run(run())
        attempt = json.loads((reviewer.output/'review-0002-attempt-01.json').read_text())
        self.assertIsNone(attempt['raw_text'])
        self.assertIsNone(attempt['response_metadata'])
        self.assertEqual(len(self.requests), 1)

    def test_envelope_limit_rejects_before_dispatch_or_reservation(self):
        reviewer = self.reviewer(max_request_bytes=1000)
        async def run():
            try:
                with self.assertRaises(RequestEnvelopeTooLarge):
                    await reviewer.review({'text': 'x'*2000})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertEqual(self.requests, [])
        self.assertEqual(self.budget.summary()['requests'], 0)

    def test_unsupported_native_modes_fail_before_credentials_or_artifacts(self):
        for settings in ({'max_tokens': 16384}, {'max_retries': 4}, {'input_format': 'review_turns_v1'}):
            with self.subTest(settings=settings), patch(
                    'uteki.agents.data_query.record_review_model.load_provider_key') as credential:
                with self.assertRaises(ValueError):
                    self.reviewer(**settings)
                credential.assert_not_called()
                self.assertFalse((self.root/'review').exists())
