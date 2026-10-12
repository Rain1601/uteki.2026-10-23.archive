"""Record reviewer SDK/HTTP fixtures; never real provider calls or historical ledgers."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents.exceptions import ModelBehaviorError
import httpx2 as httpx
from openai import AsyncOpenAI, InternalServerError
from pydantic import BaseModel

from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.data_query.question_review_generation import (
    PROJECTION, QuestionCoverageGeneration, project_question_generation,
)
from uteki.agents.data_query.question_coverage_review import (
    project_question_review, validate_question_review, question_review_repair_input, QuestionReviewProtocolError,
)
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded, RequestEnvelopeTooLarge
from uteki.infrastructure.research_data.financial_records import digest


class RecordReviewModelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.clients, self.requests = [], []
        self.enterContext(patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'review-fixture-key'}))
        self.raw = '{\n  "accepted": true, "notes": "原文核验"\n}'

    def response(self, request, *, raw=None, finish_reason='stop'):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'review-fixture-' + str(len(self.requests)), 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': finish_reason,
                'message': {'role': 'assistant', 'content': self.raw if raw is None else raw,
                            'reasoning_content': 'private-review-reasoning'}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 100, 'total_tokens': 300}})

    def reviewer(self, handler=None, *, maximum=5, enforce=False, budget=None, name='review', **kwargs):
        def factory(**options):
            self.assertEqual(options['max_retries'], 0)
            self.assertEqual(options['timeout'], kwargs.get('request_timeout', 180))
            client = AsyncOpenAI(**options, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler or self.response)))
            self.clients.append(client)
            return client
        return SdkRecordReviewer('deepseek', 'deepseek-flash',
            budget=budget if budget is not None else RunBudget(self.root/'budget.sqlite', '1', enforce=enforce),
            max_requests_total=maximum, output=self.root/name, credentials_root=self.root,
            prompt='Review only the supplied original evidence; return a JSON object.', client_factory=factory, **kwargs)

    def close_and_snapshot(self, reviewer):
        self.assertTrue(all(c.is_closed() for c in self.clients))
        ref = reviewer.snapshot_usage()
        self.assertEqual(ref['sha256'], digest((reviewer.output/ref['path']).read_bytes()))
        for item in ref['summary']['artifacts']:
            self.assertEqual(item['sha256'], digest((reviewer.output/item['path']).read_bytes()))
        self.assertEqual(ref['summary']['plan_origin'], 'scripted_fixture')
        self.assertEqual(ref['summary']['business_validation'], 'not_evaluated')
        artifacts = '\n'.join(p.read_text() for p in reviewer.output.rglob('*.json'))
        self.assertNotIn('review-fixture-key', artifacts)
        self.assertNotIn('private-review-reasoning', artifacts)
        self.assertNotIn('reasoning_content', artifacts)
        return ref['summary']

    def test_success_keeps_exact_raw_text_request_and_independent_parsed_result(self):
        reviewer = self.reviewer()
        packet = {'record_id': 'candidate-1', 'original_quote': '收入 100'}
        async def run():
            try: return await reviewer.review(packet)
            finally: await reviewer.aclose()
        self.assertEqual(asyncio.run(run()), {'accepted': True, 'notes': '原文核验'})
        record = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        self.assertEqual(record['raw_text'], self.raw)
        self.assertEqual(record['response_text'], self.raw)
        self.assertIn('actual_upstream_model', record['response_metadata'])
        self.assertIn('request_id', record['response_metadata'])
        self.assertEqual(record['response_metadata']['finish_reason'], 'stop')
        self.assertEqual(record['response_metadata']['response_id'], 'review-fixture-1')
        self.assertEqual(json.loads((reviewer.output/record['request']['path']).read_text())['packet'], packet)
        self.assertEqual(self.requests[0]['response_format'], {'type': 'json_object'})
        self.assertEqual(self.requests[0]['max_tokens'], 8192)
        self.assertEqual(self.requests[0]['thinking'], {'type': 'disabled'})
        self.assertEqual(self.requests[0]['reasoning_effort'], 'none')
        self.assertEqual(self.requests[0]['temperature'], 0)
        summary = self.close_and_snapshot(reviewer)
        for value in (reviewer.frozen_config, summary):
            self.assertEqual(value['reasoning_effort'], 'none')
            self.assertEqual(value['thinking_mode'], 'disabled')
        self.assertEqual(summary['calls']['requests'], 1)
        self.assertEqual(summary['shared_budget']['requests'], 1)
        self.assertIsNone(summary['calls']['actual_billed_usd'])
        with self.assertRaises(AttributeError): reviewer.plan_origin = 'model'

    def test_reasoning_effort_reaches_provider_and_frozen_usage_without_private_reasoning(self):
        for effort in ('high', 'low', 'max', 'none'):
            with self.subTest(effort=effort):
                reviewer = self.reviewer(name=effort, reasoning_effort=effort, request_timeout=75)
                async def run():
                    try: await reviewer.review({'record_id': 'candidate-1'})
                    finally: await reviewer.aclose()
                asyncio.run(run())
                thinking = 'disabled' if effort == 'none' else 'enabled'
                body = self.requests[-1]
                self.assertEqual(body['thinking'], {'type': thinking})
                self.assertEqual(body['reasoning_effort'], effort)
                if thinking == 'enabled':
                    self.assertNotIn('temperature', body)
                else:
                    self.assertEqual(body['temperature'], 0)
                summary = self.close_and_snapshot(reviewer)
                saved = json.loads((reviewer.output/'model-config.json').read_text())
                for value in (saved, reviewer.frozen_config, summary):
                    self.assertEqual(value['reasoning_effort'], effort)
                    self.assertEqual(value['thinking_mode'], thinking)
                self.assertEqual(saved['request_timeout'], 75)
                self.assertEqual(saved['provider_sdk_retries'], 0)
                self.assertEqual(summary['model_config_sha256'], digest((reviewer.output/'model-config.json').read_bytes()))

    def test_reasoning_configuration_is_frozen_before_each_review(self):
        reviewer = self.reviewer(reasoning_effort='high')
        copied = reviewer.frozen_config
        copied['reasoning_effort'] = 'low'
        self.assertEqual(reviewer.frozen_config['reasoning_effort'], 'high')
        path = reviewer.output/'model-config.json'
        path.write_text(json.dumps(copied))
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'Frozen review model configuration changed'):
                    await reviewer.review({'record_id': 'must-not-send'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertFalse(self.requests)
        self.assertFalse(list(reviewer.output.glob('review-*.json')))
        self.assertTrue(all(c.is_closed() for c in self.clients))

    def test_explicit_envelope_capacity_sends_complete_large_packet_and_is_recorded(self):
        reviewer = self.reviewer(max_request_bytes=2500000)
        packet = {'record_id': 'large-original', 'original_text': '证据' * 263000}
        self.assertGreater(len(json.dumps(packet, ensure_ascii=False).encode()), 1570000)
        async def run():
            try: return await reviewer.review(packet)
            finally: await reviewer.aclose()
        self.assertEqual(asyncio.run(run()), {'accepted': True, 'notes': '原文核验'})
        self.assertEqual(len(self.requests), 1)
        user_messages = [message for message in self.requests[0]['messages'] if message['role'] == 'user']
        self.assertEqual(json.loads(user_messages[0]['content']), packet)
        summary = self.close_and_snapshot(reviewer)
        saved = json.loads((reviewer.output/'model-config.json').read_text())
        for value in (saved, reviewer.frozen_config, summary):
            self.assertEqual(value['max_request_bytes'], 2500000)
        self.assertEqual(summary['shared_budget']['requests'], 1)

    def test_default_and_explicit_envelope_rejections_make_no_http_or_reservation(self):
        for name, capacity in (('default-capacity', None), ('explicit-capacity', 500000)):
            with self.subTest(name=name):
                options = {} if capacity is None else {'max_request_bytes': capacity}
                reviewer = self.reviewer(name=name, max_retries=1, **options)
                async def run():
                    try:
                        with self.assertRaises(RequestEnvelopeTooLarge):
                            await reviewer.review({'original_text': 'x' * 600000})
                    finally: await reviewer.aclose()
                asyncio.run(run())
                summary = self.close_and_snapshot(reviewer)
                self.assertEqual(summary['max_request_bytes'], capacity or 400000)
                self.assertEqual(summary['shared_budget']['requests'], 0)
                self.assertEqual(summary['calls']['requests'], 0)
                self.assertEqual(list((reviewer.output/'calls').iterdir()), [])
                attempt = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
                self.assertEqual(attempt['error_type'], 'RequestEnvelopeTooLarge')
                self.assertEqual(attempt['calls'], [])
                self.assertIsNone(attempt['raw_text'])
                self.assertFalse((reviewer.output/'review-0001-attempt-02.json').exists())
        self.assertFalse(self.requests)

    def test_larger_envelope_does_not_disable_finite_cost_budget(self):
        budget = RunBudget(self.root/'finite.sqlite', '.00001')
        reviewer = self.reviewer(budget=budget, max_request_bytes=2500000)
        async def run():
            try:
                with self.assertRaises(BudgetExceeded) as error:
                    await reviewer.review({'original_text': 'x' * 600000})
                self.assertNotIsInstance(error.exception, RequestEnvelopeTooLarge)
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertFalse(self.requests)
        self.assertEqual(self.close_and_snapshot(reviewer)['shared_budget']['requests'], 0)

    def test_envelope_capacity_is_frozen_before_any_review_call(self):
        reviewer = self.reviewer(max_request_bytes=2500000)
        copied = reviewer.frozen_config
        copied['max_request_bytes'] = 400000
        self.assertEqual(reviewer.frozen_config['max_request_bytes'], 2500000)
        (reviewer.output/'model-config.json').write_text(json.dumps(copied))
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'Frozen review model configuration changed'):
                    await reviewer.review({'record_id': 'must-not-send'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertFalse(self.requests)
        self.assertFalse(list(reviewer.output.glob('review-*.json')))

    def test_invalid_envelope_capacity_fails_before_credentials_or_output(self):
        values = {'provider': 'deepseek', 'model': 'deepseek-flash',
                  'budget': RunBudget(self.root/'budget.sqlite', '1'), 'max_requests_total': 1,
                  'output': self.root/'invalid', 'credentials_root': self.root, 'prompt': 'Review'}
        with patch('uteki.agents.data_query.record_review_model.load_provider_key') as credentials:
            for capacity in (0, -1, True, False, None, 2.5, '2500000'):
                with self.subTest(capacity=capacity), self.assertRaisesRegex(ValueError, 'positive integer'):
                    SdkRecordReviewer(**values, max_request_bytes=capacity)
            credentials.assert_not_called()
        self.assertFalse((self.root/'invalid').exists())
        self.assertFalse(self.clients)
        self.assertFalse(self.requests)

    def test_invalid_reasoning_fails_before_credentials_and_does_not_echo_supplied_values(self):
        values = {'provider': 'deepseek', 'model': 'deepseek-flash',
                  'budget': RunBudget(self.root/'budget.sqlite', '1'), 'max_requests_total': 1,
                  'output': self.root/'invalid', 'credentials_root': self.root, 'prompt': 'Review'}
        cases = [{'reasoning_effort': value} for value in ('medium', '', True, ['high'], 'private-effort-value')]
        cases += [{'provider': 'aihubmix', 'model': 'gpt-5.4-mini', 'reasoning_effort': value}
                  for value in ('high', 'none')]
        with patch('uteki.agents.data_query.record_review_model.load_provider_key') as credentials:
            for changes in cases:
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'reasoning effort') as error:
                    SdkRecordReviewer(**{**values, **changes})
                self.assertNotIn('private-effort-value', str(error.exception))
            credentials.assert_not_called()
        self.assertFalse((self.root/'invalid').exists())
        self.assertFalse(self.clients)
        self.assertFalse(self.requests)

    def test_unlimited_reviewers_share_record_only_ledger_and_preserve_unknown_costs(self):
        budget = RunBudget(self.root/'unlimited.sqlite', None, enforce=False)
        attempts = 0
        def once_failed(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                self.requests.append(json.loads(request.content))
                return httpx.Response(500, json={'error': {'message': 'synthetic transient failure',
                                                         'type': 'server_error'}})
            return self.response(request)
        reviewer = self.reviewer(once_failed, maximum=None, budget=budget, reasoning_effort='high', max_retries=1)
        auditor = self.reviewer(name='audit', maximum=None, budget=budget, reasoning_effort='low')
        async def run():
            try:
                for index in range(3):
                    await reviewer.review({'record_id': f'candidate-{index}'})
                for index in range(2):
                    await auditor.review({'record_id': f'audit-{index}'})
            finally:
                await reviewer.aclose()
                await auditor.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.requests), 6)
        summary = RunBudget(self.root/'unlimited.sqlite', None, enforce=False).summary()
        self.assertIsNone(summary['limit_usd'])
        self.assertEqual(summary['enforcement'], 'record_only')
        self.assertEqual(summary['requests'], 6)
        self.assertEqual(summary['unknown_requests'], 1)
        self.assertEqual(summary['in_flight_requests'], 0)
        self.assertGreater(float(summary['estimated_spent_usd']), 0)
        self.assertIsNone(summary['actual_billed_usd'])
        for adapter, count in ((reviewer, 4), (auditor, 2)):
            usage = self.close_and_snapshot(adapter)
            self.assertEqual(usage['shared_budget'], summary)
            self.assertEqual(usage['calls']['requests'], count)
            self.assertIsNone(adapter.frozen_config['max_requests_total'])
            self.assertIsNone(adapter.frozen_config['budget_at_start']['limit_usd'])
            self.assertEqual(adapter.frozen_config['budget_policy'], 'record_only')
        self.assertEqual(reviewer.snapshot_usage()['summary']['calls']['unknown_cost_requests'], 1)

    def test_existing_shared_request_policy_cannot_change_to_or_from_unlimited(self):
        for index, (initial, replacement) in enumerate(((1, None), (None, 1))):
            with self.subTest(initial=initial):
                budget = RunBudget(self.root/f'policy-{index}.sqlite', None, enforce=False)
                reviewer = self.reviewer(name=f'policy-{index}', maximum=initial, budget=budget)
                async def run():
                    try:
                        await reviewer.review({'record_id': 'first'})
                        with self.assertRaisesRegex(ValueError, 'cannot be silently changed'):
                            self.reviewer(name=f'changed-{index}', maximum=replacement, budget=budget)
                        if initial is None:
                            await reviewer.review({'record_id': 'second'})
                        else:
                            with self.assertRaises(BudgetExceeded):
                                await reviewer.review({'record_id': 'second'})
                    finally: await reviewer.aclose()
                asyncio.run(run())
                self.assertFalse((self.root/f'changed-{index}').exists())
                self.assertEqual(self.close_and_snapshot(reviewer)['shared_budget']['requests'],
                                 2 if initial is None else 1)

    def test_invalid_json_is_saved_and_not_silently_retried(self):
        raw = '{"accepted": true, invalid JSON'
        reviewer = self.reviewer(lambda request: self.response(request, raw=raw), max_retries=1)
        async def run():
            try:
                with self.assertRaises(ModelBehaviorError): await reviewer.review({'record_id': 'bad-json'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        record = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        self.assertEqual(record['raw_text'], raw)
        self.assertEqual(record['status'], 'failed_or_cancelled')
        self.assertFalse((reviewer.output/'review-0001-parsed.json').exists())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.close_and_snapshot(reviewer)['calls']['unknown_cost_requests'], 0)

    def test_truncated_response_keeps_content_finish_reason_and_billable_usage(self):
        raw = '{"accepted": false, "notes": "cut off'
        reviewer = self.reviewer(lambda request: self.response(request, raw=raw, finish_reason='length'))
        async def run():
            try:
                with self.assertRaises(ModelBehaviorError): await reviewer.review({'record_id': 'truncated'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        record = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        self.assertEqual(record['raw_text'], raw)
        self.assertEqual(record['response_metadata']['finish_reason'], 'length')
        self.assertEqual(record['response_metadata']['raw_usage']['completion_tokens'], 100)
        summary = self.close_and_snapshot(reviewer)
        self.assertEqual(summary['calls']['requests'], 1)
        self.assertIsNotNone(summary['calls']['records'][0]['estimated_usd'])

    def test_shared_limit_rejection_does_not_reuse_previous_raw_response(self):
        reviewer = self.reviewer(maximum=1)
        async def run():
            try:
                await reviewer.review({'record_id': 'first'})
                with self.assertRaises(BudgetExceeded): await reviewer.review({'record_id': 'second'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.requests), 1)
        record = json.loads((reviewer.output/'review-0002-attempt-01.json').read_text())
        self.assertIsNone(record['raw_text']); self.assertIsNone(record['response_metadata'])
        self.assertEqual(record['calls'], [])
        self.assertEqual(self.close_and_snapshot(reviewer)['shared_budget']['requests'], 1)

    def test_http_failures_and_explicit_retries_are_all_metered(self):
        def fail(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(500, json={'error': {'message': 'mock error', 'type': 'server_error'}})
        reviewer = self.reviewer(fail, max_retries=1)
        async def run():
            try:
                with self.assertRaises(InternalServerError): await reviewer.review({'record_id': 'failed'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.requests), 2)
        summary = self.close_and_snapshot(reviewer)
        self.assertEqual(summary['shared_budget']['requests'], 2)
        self.assertEqual(summary['shared_budget']['unknown_requests'], 2)
        records = [json.loads(p.read_text()) for p in sorted(reviewer.output.glob('review-0001-attempt-*.json'))]
        self.assertEqual([r['retry'] for r in records], [False, True])
        self.assertTrue(all(r['raw_text'] is None for r in records))

    def test_timeout_and_cancellation_save_attempt_and_usage(self):
        started = asyncio.Event()
        async def slow(request):
            self.requests.append(json.loads(request.content)); started.set()
            await asyncio.sleep(20)
            raise AssertionError('Mock should have been cancelled')
        reviewer = self.reviewer(slow, request_timeout=1)
        async def run():
            try:
                with self.assertRaises(TimeoutError): await reviewer.review({'record_id': 'timeout'})
                started.clear()
                task = asyncio.create_task(reviewer.review({'record_id': 'cancel'}))
                await asyncio.wait_for(started.wait(), 0.8)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            finally: await reviewer.aclose()
        asyncio.run(run())
        first = json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())
        second = json.loads((reviewer.output/'review-0002-attempt-01.json').read_text())
        self.assertEqual(first['status'], 'timed_out')
        self.assertEqual(second['error_type'], 'CancelledError')
        self.assertEqual(self.close_and_snapshot(reviewer)['calls']['requests'], 2)

    def test_optional_output_type_is_validated_but_raw_response_still_saved(self):
        class Review(BaseModel):
            required_field: str
        reviewer = self.reviewer(output_schema=Review)
        async def run():
            try:
                with self.assertRaises(ModelBehaviorError): await reviewer.review({'record_id': 'schema-invalid'})
            finally: await reviewer.aclose()
        asyncio.run(run())
        self.assertEqual(json.loads((reviewer.output/'review-0001-attempt-01.json').read_text())['raw_text'], self.raw)
        self.close_and_snapshot(reviewer)

    def test_question_generation_is_projected_and_raw_generated_and_repair_inputs_are_preserved(self):
        text = 'Beacon revenue was 42. Cinder revenue was 18.'
        initial = project_question_review({'schema_version': 'data-answer-review-input-v1',
            'packet_id': 'packet', 'purpose': 'analysis_evidence', 'source_delivery': 'query_evidence_v1',
            'question': 'For Beacon and Cinder, provide revenue for FY2031.',
            'scope': {'execution_schema_version': 'research-execution-v1', 'snapshot_id': 'dataset',
                'company_ids': ['example'], 'source_snapshot_ids': ['annual'],
                'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2032-05-01', 'include_candidates': True},
            'source_documents': [{'source_snapshot_id': 'annual', 'index_id': 'idx', 'source_sha256': 'a'*64,
                'company_id': 'example', 'source_url': 'https://example.org/annual',
                'source_period_end': '2031-12-31', 'available_at': '2032-02-01',
                'blocks': [{'block_id': 'table', 'type': 'paragraph', 'text': text,
                            'text_hash': digest(text.encode()), 'table': None}]}]})
        generated = {'packet_id': 'packet', 'projection_id': initial['projection_id'], 'checks': [{
            'request': {'question_quote': 'provide revenue for FY2031', 'requested_subject': 'revenue',
                'requested_dimension': 'metric',
                'scope': {'kind': 'self_contained', 'reason': 'The model incorrectly treats revenue as self contained.'}},
            'judgment': {'source_subject': 'Beacon revenue', 'relation': 'same', 'coverage': 'complete',
                'support_basis': 'direct', 'citations': [{'kind': 'block_quote', 'source_snapshot_id': 'annual',
                    'block_id': 'table', 'quote': 'Beacon revenue was 42.'}], 'gap': None,
                'rationale': 'Original disclosure supports this requested amount.'}}],
            'output_constraints': [], 'uncovered_requests': [],
            'question_coverage': 'complete', 'coverage_reason': 'Both disclosed amounts are present.'}
        generated['checks'].append(deepcopy(generated['checks'][0]))
        generated['checks'][1]['judgment']['source_subject'] = 'Cinder revenue'
        generated['checks'][1]['judgment']['citations'][0]['quote'] = 'Cinder revenue was 18.'
        repaired = deepcopy(generated)
        for check, subject in zip(repaired['checks'], ('Beacon', 'Cinder')):
            check['request']['scope'] = {'kind': 'qualified', 'quotes': [subject, 'FY2031']}
        raw_outputs = [json.dumps(item, ensure_ascii=False, indent=2) for item in (generated, repaired)]
        def handler(request):
            return self.response(request, raw=raw_outputs[len(self.requests)])
        reviewer = self.reviewer(handler, output_schema=QuestionCoverageGeneration, output_projection=PROJECTION)
        expected_first = project_question_generation(generated)
        repair = question_review_repair_input(initial, expected_first)
        before = deepcopy(repair)
        async def run():
            try:
                first = await reviewer.review(initial)
                with self.assertRaises(QuestionReviewProtocolError) as caught:
                    validate_question_review(initial, first)
                self.assertEqual(caught.exception.diagnostic['code'], 'duplicate_check_requires_distinct_scope')
                actual_repair = question_review_repair_input(initial, first)
                self.assertEqual(actual_repair, repair)
                second = await reviewer.review(actual_repair)
                self.assertTrue(validate_question_review(initial, second)[1])
                return first, second
            finally:
                await reviewer.aclose()
        first, second = asyncio.run(run())
        self.assertEqual(first, expected_first)
        self.assertEqual(second, project_question_generation(repaired))
        self.assertEqual(repair, before)
        self.assertEqual(reviewer.frozen_config['output_projection'], PROJECTION)
        for number, output in enumerate((generated, repaired), 1):
            stem = f'review-{number:04d}'
            stored = json.loads((reviewer.output/f'{stem}-generated.json').read_text())
            canonical = json.loads((reviewer.output/f'{stem}-parsed.json').read_text())
            provenance = json.loads((reviewer.output/f'{stem}-projection.json').read_text())
            attempt = json.loads((reviewer.output/f'{stem}-attempt-01.json').read_text())
            self.assertEqual(stored, QuestionCoverageGeneration.model_validate(output).model_dump(mode='json'))
            self.assertEqual(canonical, project_question_generation(output))
            self.assertEqual(provenance['generated_sha256'], digest(stored))
            self.assertEqual(provenance['canonical_sha256'], digest(canonical))
            self.assertEqual(provenance['protocol'], PROJECTION)
            self.assertEqual(provenance['operation'], 'field_projection_only_no_semantic_repair')
            self.assertEqual(attempt['raw_text'], raw_outputs[number-1])
        sent = [m for m in self.requests[1]['messages'] if m['role'] == 'user']
        self.assertEqual(json.loads(sent[0]['content']), repair)
        saved = json.loads((reviewer.output/'review-0002-input.json').read_text())
        self.assertEqual(saved['packet'], repair)
        summary = self.close_and_snapshot(reviewer)
        self.assertEqual(summary['calls']['requests'], 2)
        paths = {item['path'] for item in summary['artifacts']}
        for number in (1, 2):
            for suffix in ('generated', 'projection', 'parsed'):
                self.assertIn(f'review-{number:04d}-{suffix}.json', paths)

    def test_explicit_prompt_budget_and_supported_raw_capture_are_required(self):
        values = {'provider': 'deepseek', 'model': 'deepseek-flash', 'budget': RunBudget(self.root/'budget.sqlite', '1'),
                  'max_requests_total': 1, 'output': self.root/'invalid', 'credentials_root': self.root, 'prompt': 'Review'}
        for changes in ({'prompt': ''}, {'budget': None}, {'provider': 'aihubmix', 'model': 'gpt-5.4-mini'}, {'model': 'unknown'}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError): SdkRecordReviewer(**{**values, **changes})
        self.assertFalse((self.root/'invalid').exists())
        self.assertFalse(self.requests)
