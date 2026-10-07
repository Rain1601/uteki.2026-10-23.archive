"""Offline transport tests for bounded independent generation; no model calls."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from uteki.agents.business_map import independent_run as independent
from uteki.agents.business_map import product_run as base
from uteki.agents.business_map.product_contract import BUSINESS_DRAFT_VERSION

spec = importlib.util.spec_from_file_location('business_fixture', Path(__file__).with_name('test_business_only_run.py'))
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


class IndependentBusinessRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.requests = []
        self.responses = []
        self.env = patch.dict(os.environ, {'AIHUBMIX_API_KEY':'offline-test-key'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def prepare(self, company='quartz', period='2020-09-30'):
        self.packet, self.draft = fixture_module.fixture(self.root, company, period)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'skill.md').write_text('Extract only supported business objects and relationships. No references.')
        prepared = base.prepare(root=self.root, packet_path='packet.json', skill_path='skill.md',
            company_id=company, document_id=self.packet['document_id'], period_end=period,
            model='claude-sonnet-5-5', effort='high', max_tokens=3000, timeout_seconds=30,
            contract_version=BUSINESS_DRAFT_VERSION)
        prepared['native']._client_factory = self.client
        return prepared

    def client(self, **kwargs):
        kwargs['transport'] = httpx.MockTransport(self.respond)
        return httpx.AsyncClient(**kwargs)

    def respond(self, request):
        self.requests.append(json.loads(request.content))
        payload = self.responses.pop(0)
        return httpx.Response(200, json=payload)

    def answer(self, draft=None, *, stop='end_turn', usage=True):
        value = dict(id='msg_test', model='claude-sonnet-5-5', stop_reason=stop,
                     content=[dict(type='text', text=json.dumps(self.draft if draft is None else draft))])
        if usage:
            value['usage'] = dict(input_tokens=180, output_tokens=120)
        return value

    async def execute(self, prepared, **options):
        return await independent.execute(prepared, root=self.root, output=self.root/'execution',
            observation_root=self.root/'observations', budget_limit_usd=options.pop('budget_limit_usd','1'), **options)

    async def test_valid_initial_runs_once_and_preserves_explicit_company_and_period(self):
        prepared = self.prepare()
        self.responses = [self.answer()]
        result = await self.execute(prepared)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['candidate_path'], 'execution/attempt-01')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
        self.assertEqual(json.loads(self.requests[0]['messages'][0]['content']), self.packet)
        candidate = json.loads((self.root/result['candidate_path']/'business_map.json').read_text())
        self.assertEqual(candidate['company_id'], 'quartz')
        self.assertEqual(candidate['metadata']['period_end'], '2020-09-30')

    async def test_contract_failure_revises_only_own_response_and_automatic_feedback(self):
        prepared = self.prepare('cobalt','2022-03-31')
        bad = copy.deepcopy(self.draft)
        bad['source_sha256'] = '0'*64
        self.responses = [self.answer(bad), self.answer()]
        result = await self.execute(prepared)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['candidate_path'], 'execution/attempt-02')
        self.assertEqual(len(self.requests), 2)
        payload = json.loads(self.requests[1]['messages'][0]['content'])
        self.assertEqual(set(payload), {'frozen_source_packet','prior_response','validation_error'})
        self.assertEqual(payload['frozen_source_packet'], self.packet)
        self.assertEqual(json.loads(payload['prior_response']), bad)
        self.assertIn('source_sha256', payload['validation_error'])
        self.assertIn('self_revision', self.requests[1]['system'])
        self.assertNotIn('search_news_ads', json.dumps(self.requests))
        self.assertNotIn('review-feedback', json.dumps(self.requests))
        first, second = result['attempts']
        self.assertEqual(first['status'], 'failed')
        self.assertEqual(second['mode'], 'self_revision')
        from decimal import Decimal
        self.assertEqual(Decimal(second['budget']['limit_usd']), Decimal('1')-Decimal(first['budget']['estimated_spent_usd']))
        self.assertEqual(Decimal(result['estimated_spent_usd']), sum(Decimal(x['budget']['estimated_spent_usd']) for x in result['attempts']))
        manifest = json.loads((self.root/'execution/attempt-02/manifest.json').read_text())
        request = (self.root/'execution/attempt-02/request.json').read_bytes()
        self.assertEqual(manifest['request_sha256'], base.digest(request))
        self.assertEqual(manifest['parent_trace_id'], first['trace_id'])
        self.assertFalse((self.root/'execution/attempt-01/business_map.json').exists())

    async def test_second_contract_failure_stops_without_candidate(self):
        prepared = self.prepare()
        bad = copy.deepcopy(self.draft)
        bad['source_sha256'] = '0'*64
        self.responses = [self.answer(bad), self.answer(bad)]
        result = await self.execute(prepared)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['candidate_path'])
        self.assertFalse((self.root/'execution/attempt-02/business_map.json').exists())

    async def test_truncation_is_not_automatically_retried(self):
        prepared = self.prepare()
        self.responses = [self.answer(stop='max_tokens')]
        result = await self.execute(prepared)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['candidate_path'])

    async def test_unknown_usage_stops_without_retry(self):
        prepared = self.prepare()
        bad = copy.deepcopy(self.draft)
        bad['source_sha256'] = '0'*64
        self.responses = [self.answer(bad, usage=False)]
        result = await self.execute(prepared)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['unknown_requests'], 1)
        self.assertIsNone(result['candidate_path'])

    async def test_budget_reservation_failure_makes_no_http_request(self):
        prepared = self.prepare()
        result = await self.execute(prepared, budget_limit_usd='0.0001')
        self.assertEqual(self.requests, [])
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['candidate_path'])

    async def test_cancellation_keeps_settled_attempt_cost_in_outer_summary(self):
        prepared = self.prepare()
        self.responses = [self.answer()]
        with patch.object(base, 'validate_draft', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.execute(prepared)
        result = json.loads((self.root/'execution/summary.json').read_text())
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(len(result['attempts']), 1)
        self.assertGreater(float(result['estimated_spent_usd']), 0)
        self.assertEqual(result['estimated_spent_usd'], result['attempts'][0]['budget']['estimated_spent_usd'])
        self.assertEqual(result['cost_reconciliation'], 'settled_estimates')
        self.assertEqual(result['initial_request_sha256'], prepared['manifest']['request_sha256'])
        self.assertIn('independent_run.py', result['implementation_sha256'])
        self.assertIsNone(result['candidate_path'])

    async def test_zero_revisions_and_invalid_scope(self):
        prepared = self.prepare()
        bad = copy.deepcopy(self.draft)
        bad['source_sha256'] = '0'*64
        self.responses = [self.answer(bad)]
        result = await self.execute(prepared, max_revisions=0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        prepared['packet']['company_id'] = 'other'
        with self.assertRaises(ValueError):
            await independent.execute(prepared, root=self.root, output=self.root/'invalid',
                observation_root=self.root/'observations', budget_limit_usd='1')
        self.assertFalse((self.root/'invalid').exists())


if __name__ == '__main__':
    unittest.main()
