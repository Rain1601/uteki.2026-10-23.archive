"""Source-only self-review tests with synthetic companies and mock HTTP only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from uteki.agents.business_map import product_run as base, self_review
from uteki.agents.business_map.product_contract import BUSINESS_DRAFT_VERSION

spec = importlib.util.spec_from_file_location('self_review_fixture', Path(__file__).with_name('test_business_only_run.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class SelfReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.requests, self.responses = [], []
        env = patch.dict(os.environ, {'AIHUBMIX_API_KEY':'offline-test-key'})
        env.start()
        self.addCleanup(env.stop)
        native = self_review.ClaudeMessagesModel
        def factory(*args, **kwargs):
            return native(*args, **dict(kwargs, client_factory=self.client))
        p = patch.object(self_review, 'ClaudeMessagesModel', side_effect=factory)
        p.start()
        self.addCleanup(p.stop)

    def client(self, **kwargs):
        return httpx.AsyncClient(**dict(kwargs, transport=httpx.MockTransport(self.respond)))

    def respond(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json=self.responses.pop(0))

    def answer(self, value, *, usage=True, stop='end_turn'):
        data = dict(id='msg_test', model='claude-sonnet-5-5', stop_reason=stop,
                    content=[dict(type='text', text=json.dumps(value))])
        if usage: data['usage'] = dict(input_tokens=180, output_tokens=120)
        return data

    async def candidate(self, company='quartz', period='2020-09-30'):
        self.packet, self.draft = fixture.fixture(self.root, company, period)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'skill.md').write_text('Extract supported graph objects only. No references or fixed node count.')
        prepared = base.prepare(root=self.root, packet_path='packet.json', skill_path='skill.md',
            company_id=company, document_id=self.packet['document_id'], period_end=period,
            model='claude-sonnet-5-5', effort='high', max_tokens=3000, timeout_seconds=30,
            contract_version=BUSINESS_DRAFT_VERSION)
        prepared['native']._client_factory = self.client
        self.responses = [self.answer(self.draft)]
        await base.execute(prepared, root=self.root, output=self.root/'original',
                           observation_root=self.root/'observations', budget_limit_usd='1')
        self.requests.clear()

    async def run_review(self, budget='1'):
        return await self_review.execute(root=self.root, input_run='original', output=self.root/'review-run',
            observation_root=self.root/'observations', budget_limit_usd=budget)

    def issue(self):
        return dict(status='needs_revision', issues=[dict(category='unsupported_definition',
            source_block_ids=['product'], node_ids=['beacon'], explanation='Recheck the selected definition.')])

    async def test_pass_reuses_candidate_without_new_extraction(self):
        await self.candidate()
        self.responses = [self.answer(dict(status='pass', issues=[]))]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['candidate_path'], 'original')
        self.assertEqual(result['self_review_status'], 'pass')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
        self.assertFalse(result['independent_evaluation'])
        payload = json.loads(self.requests[0]['messages'][0]['content'])
        self.assertEqual(set(payload), {'frozen_source_packet','own_candidate'})
        self.assertEqual(payload['frozen_source_packet'], self.packet)
        self.assertEqual(payload['own_candidate'], json.loads((self.root/'original/draft.json').read_text()))
        self.assertFalse((self.root/'review-run/revision').exists())
        manifest = json.loads((self.root/'review-run/review/manifest.json').read_text())
        self.assertEqual(manifest['output_contract_version'], 'business-semantic-review-v1')
        self.assertEqual(manifest['source_business_contract_version'], BUSINESS_DRAFT_VERSION)

    async def test_revision_only_own_answer_and_review_preserves_scope(self):
        await self.candidate('cobalt','2023-03-31')
        self.responses = [self.answer(self.issue()), self.answer(self.draft)]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['candidate_path'], 'review-run/revision')
        payload = json.loads(self.requests[1]['messages'][0]['content'])
        self.assertEqual(set(payload), {'frozen_source_packet','own_candidate','own_self_review'})
        self.assertEqual(payload['own_self_review'], self.issue())
        self.assertEqual(payload['frozen_source_packet']['company_id'], 'cobalt')
        self.assertEqual(payload['frozen_source_packet']['period_end'], '2023-03-31')
        output = json.loads((self.root/'review-run/revision/result.json').read_text())
        self.assertEqual(output['semantic_acceptance'], 'not_evaluated')
        self.assertEqual(output['output_contract_version'], BUSINESS_DRAFT_VERSION)
        self.assertEqual(output['source_business_contract_version'], BUSINESS_DRAFT_VERSION)
        self.assertEqual(result['budget']['requests'], 2)
        self.assertEqual(result['estimated_spent_usd'], output['budget']['estimated_spent_usd'])
        self.assertNotIn('reference_answer', payload)
        self.assertNotIn('human_feedback', payload)

    async def test_revision_failure_preserves_original_and_no_third_call(self):
        await self.candidate()
        bad = copy.deepcopy(self.draft)
        bad['company_id'] = 'other'
        self.responses = [self.answer(self.issue()), self.answer(bad)]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['candidate_path'], 'original')
        self.assertIn('revision_failed', result['stop_reason'])

    async def test_unknown_usage_stops_before_revision(self):
        await self.candidate()
        self.responses = [self.answer(self.issue(), usage=False)]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['unknown_requests'], 1)
        self.assertEqual(result['candidate_path'], 'original')
        self.assertEqual(result['status'], 'failed')

    async def test_budget_prevents_billable_request(self):
        await self.candidate()
        result = await self.run_review('0.00001')
        self.assertEqual(len(self.requests), 0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['candidate_path'], 'original')

    async def test_truncated_review_does_not_revision(self):
        await self.candidate()
        self.responses = [self.answer(self.issue(), stop='max_tokens')]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')

    async def test_foreign_review_block_is_rejected(self):
        await self.candidate()
        value = self.issue()
        value['issues'][0]['source_block_ids'] = ['foreign-block']
        self.responses = [self.answer(value)]
        result = await self.run_review()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')

    async def test_edited_draft_rejected_before_dispatch(self):
        await self.candidate()
        draft_file = self.root/'original/draft.json'
        value = json.loads(draft_file.read_text())
        value['summary'] = 'manual answer'
        draft_file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'draft_raw_response'):
            await self.run_review()
        self.assertEqual(len(self.requests), 0)

    async def test_reference_execution_mode_rejected(self):
        await self.candidate()
        for name in ('manifest.json','result.json'):
            file = self.root/'original'/name
            value = json.loads(file.read_text())
            value['execution_mode'] = 'typed_graph_completion'
            file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'source_only_initial'):
            await self.run_review()
        self.assertEqual(len(self.requests), 0)

    async def test_scope_tamper_rejected_before_dispatch(self):
        await self.candidate()
        file = self.root/'original/source_packet.json'
        packet = json.loads(file.read_text())
        packet['company_id'] = ''
        file.write_text(json.dumps(packet))
        with self.assertRaises(ValueError): await self.run_review()
        self.assertEqual(len(self.requests), 0)


if __name__ == '__main__': unittest.main()
