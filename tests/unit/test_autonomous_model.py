"""Real SDK over injected HTTP fixtures; no real provider calls or historical ledger."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AUTONOMOUS_PROMPT, WORKER_PROMPT
from uteki.agents.data_query.autonomous_model import SdkAutonomousPlanner, _RequestLimitedBudget, _decision_validation_hints
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from uteki.agents.runtime.call_costs import pricing_snapshot, summarize
from uteki.infrastructure.research_data.financial_records import digest


class AutonomousModelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'fixture-key', 'AIHUBMIX_API_KEY': 'fixture-key'}))
        self.credentials = self.enterContext(patch('uteki.agents.data_query.autonomous_model.load_provider_key',
                                                   return_value='offline_fixture'))
        self.requests = []
        self.client_settings = []

    def response(self, request, decision=None):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'fixture-response-' + str(len(self.requests)), 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': json.dumps(decision or {'action': 'finish'})}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})

    def raw_response(self, request, content, *, finish_reason='stop'):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'x-fixture-secret': 'diagnostic-header-secret'}, json={
            'id': 'diagnostic-response-' + str(len(self.requests)), 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-flash',
            'choices': [{'index': 0, 'finish_reason': finish_reason, 'message': {
                'role': 'assistant', 'content': content,
                'reasoning_content': 'diagnostic-hidden-reasoning'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})

    def planner(self, respond=None, *, name='model', enforce=False, maximum=5, budget=None,
                provider='deepseek', model='deepseek-flash', **kwargs):
        def factory(**options):
            self.assertEqual(options['max_retries'], 0)
            self.client_settings.append({'timeout': options['timeout'], 'max_retries': options['max_retries']})
            return AsyncOpenAI(**options, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond or self.response)))
        return SdkAutonomousPlanner(provider, model, budget=budget or RunBudget(self.root/'budget.sqlite', '1', enforce=enforce),
            max_requests_total=maximum, output=self.root/name, credentials_root=self.root,
            client_factory=factory, **kwargs)

    def test_sdk_decision_is_metered_frozen_and_fixture_labelled(self):
        planner = self.planner()
        async def run():
            try:
                decision = await planner.decide({'question': 'Retrieve evidence', 'observation': None})
                self.assertEqual(decision.action, 'finish')
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(planner.plan_origin, 'scripted_fixture')
        with self.assertRaises(AttributeError): planner.plan_origin = 'model'
        config = planner.frozen_config
        self.assertEqual(config['role'], 'planner')
        self.assertEqual(config['prompt'], AUTONOMOUS_PROMPT)
        self.assertEqual(config['prompt_sha256'], digest(AUTONOMOUS_PROMPT))
        self.assertEqual(config['reasoning_effort'], 'none')
        self.assertEqual(config['thinking_mode'], 'disabled')
        self.assertEqual(self.client_settings, [{'timeout': 90, 'max_retries': 0}])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]['thinking'], {'type': 'disabled'})
        self.assertEqual(self.requests[0]['reasoning_effort'], 'none')
        self.assertEqual(self.requests[0]['response_format'], {'type': 'json_object'})
        self.assertIn('AutonomousDecision', self.requests[0]['messages'][0]['content'])
        self.assertEqual(RunBudget(self.root/'budget.sqlite', '1', enforce=False).summary()['requests'], 1)
        snapshot = planner.snapshot_usage()
        self.assertEqual(snapshot['summary']['role'], 'planner')
        self.assertEqual(snapshot['summary']['reasoning_effort'], 'none')
        self.assertEqual(snapshot['summary']['thinking_mode'], 'disabled')
        self.assertEqual(snapshot['summary']['calls']['requests'], 1)
        self.assertEqual(snapshot['summary']['calls']['unknown_cost_requests'], 0)
        self.assertIsNone(snapshot['summary']['calls']['actual_billed_usd'])
        for ref in snapshot['summary']['artifacts']:
            self.assertEqual(digest((planner.output/ref['path']).read_bytes()), ref['sha256'])
        self.assertNotIn('fixture-key', '\n'.join(p.read_text() for p in planner.output.rglob('*.json')))

    def test_deepseek_effort_reaches_provider_body_and_role_usage(self):
        for effort, role, timeout in (('high', 'planner', 180), ('low', 'worker', 75), ('none', 'worker', 30)):
            with self.subTest(effort=effort, role=role):
                planner = self.planner(name=effort, role=role, reasoning_effort=effort,
                                       request_timeout=timeout)

                async def run():
                    try:
                        await planner.decide({'question': 'Verify the explicitly assigned research task.'})
                    finally:
                        await planner.aclose()

                asyncio.run(run())
                thinking = 'disabled' if effort == 'none' else 'enabled'
                body = self.requests[-1]
                self.assertEqual(body['thinking'], {'type': thinking})
                self.assertEqual(body['reasoning_effort'], effort)
                if thinking == 'enabled':
                    self.assertNotIn('temperature', body)
                else:
                    self.assertEqual(body['temperature'], 0)
                self.assertEqual(self.client_settings[-1], {'timeout': timeout, 'max_retries': 0})
                config = planner.frozen_config
                usage = planner.snapshot_usage()['summary']
                for value in (config, usage):
                    self.assertEqual(value['role'], role)
                    self.assertEqual(value['reasoning_effort'], effort)
                    self.assertEqual(value['thinking_mode'], thinking)
                self.assertEqual(config['request_timeout'], timeout)
                self.assertEqual(usage['model_config_sha256'], digest((planner.output/'model-config.json').read_bytes()))

    def test_invalid_reasoning_configuration_fails_before_credentials_or_artifacts(self):
        cases = [
            {'provider': 'aihubmix', 'model': 'gpt-5.4-mini', 'reasoning_effort': 'high'},
            {'provider': 'aihubmix', 'model': 'gpt-5.4-mini', 'reasoning_effort': 'none'},
            *[{'reasoning_effort': value} for value in ('medium', '', True, ['high'])],
        ]
        for index, options in enumerate(cases):
            name = f'invalid-reasoning-{index}'
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'reasoning effort'):
                self.planner(name=name, **options)
            self.assertFalse((self.root/name).exists())
        self.credentials.assert_not_called()
        self.assertFalse(self.requests)
        self.assertFalse(self.client_settings)

    def test_distinct_roles_and_models_share_request_allowance_and_keep_separate_records(self):
        planner = self.planner(maximum=2)
        worker = self.planner(name='worker', maximum=2, role='worker',
                              provider='aihubmix', model='gpt-5.4-mini')
        async def run():
            try:
                await planner.decide({'question': 'Plan the bounded request'})
                await worker.decide({'question': 'Retrieve the assigned evidence'})
                with self.assertRaises(BudgetExceeded):
                    await planner.decide({'question': 'No fresh allowance on resume'})
            finally:
                await planner.aclose()
                await worker.aclose()
        asyncio.run(run())
        self.assertEqual([request['model'] for request in self.requests], ['deepseek-flash', 'gpt-5.4-mini'])
        self.assertIn(WORKER_PROMPT, self.requests[1]['messages'][0]['content'])
        self.assertEqual(worker.frozen_config['prompt'], WORKER_PROMPT)
        self.assertEqual(worker.frozen_config['prompt_sha256'], digest(WORKER_PROMPT))
        for adapter, role in ((planner, 'planner'), (worker, 'worker')):
            usage = adapter.snapshot_usage()['summary']
            self.assertEqual(usage['role'], role)
            self.assertEqual(usage['shared_budget']['requests'], 2)
            self.assertEqual(usage['calls']['requests'], 1)
            self.assertEqual(usage['calls']['records'][0]['stage'], f'autonomous_{role}_decision')
            attempts = [json.loads(path.read_text()) for path in adapter.output.glob('decision-*-attempt-*.json')]
            self.assertTrue(all(attempt['role'] == role for attempt in attempts))

    def test_unlimited_roles_preserve_usage_and_unknown_costs_without_a_ceiling(self):
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

        planner = self.planner(once_failed, budget=budget, maximum=None, max_retries=1)
        worker = self.planner(budget=budget, maximum=None, name='worker', role='worker',
                              provider='aihubmix', model='gpt-5.4-mini')

        async def run():
            try:
                for index in range(3):
                    await planner.decide({'question': f'Parent decision {index}'})
                for index in range(2):
                    await worker.decide({'question': f'Worker decision {index}'})
            finally:
                await planner.aclose()
                await worker.aclose()

        asyncio.run(run())
        self.assertEqual(len(self.requests), 6)
        reopened = RunBudget(self.root/'unlimited.sqlite', None, enforce=False)
        summary = reopened.summary()
        self.assertIsNone(summary['limit_usd'])
        self.assertEqual(summary['enforcement'], 'record_only')
        self.assertEqual(summary['requests'], 6)
        self.assertEqual(summary['unknown_requests'], 1)
        self.assertEqual(summary['in_flight_requests'], 0)
        self.assertGreater(float(summary['estimated_spent_usd']), 0)
        self.assertIsNone(summary['actual_billed_usd'])
        for adapter, expected_calls in ((planner, 4), (worker, 2)):
            self.assertIsNone(adapter.frozen_config['max_requests_total'])
            self.assertIsNone(adapter.frozen_config['budget_at_start']['limit_usd'])
            usage = adapter.snapshot_usage()['summary']
            self.assertEqual(usage['shared_budget'], summary)
            self.assertEqual(usage['calls']['requests'], expected_calls)
            self.assertEqual(usage['plan_origin'], 'scripted_fixture')
            for reference in usage['artifacts']:
                self.assertEqual(digest((adapter.output/reference['path']).read_bytes()), reference['sha256'])
        self.assertEqual(planner.snapshot_usage()['summary']['calls']['unknown_cost_requests'], 1)

    def test_persistent_request_policy_cannot_change_between_finite_and_unlimited(self):
        for index, (initial, replacement) in enumerate(((2, None), (None, 2))):
            with self.subTest(initial=initial, replacement=replacement):
                budget = RunBudget(self.root/f'policy-{index}.sqlite', '1', enforce=False)
                original = _RequestLimitedBudget(budget, initial)
                token = original.reserve('.001')
                original.settle(token, '.001')
                with self.assertRaisesRegex(ValueError, 'cannot be silently changed'):
                    _RequestLimitedBudget(budget, replacement)
                unchanged = _RequestLimitedBudget(budget, initial)
                token = unchanged.reserve('.001')
                unchanged.settle(token, '.001')
                if initial is None:
                    token = unchanged.reserve('.001')
                    unchanged.settle(token, '.001')
                    self.assertEqual(budget.summary()['requests'], 3)
                else:
                    with self.assertRaises(BudgetExceeded):
                        unchanged.reserve('.001')
                    self.assertEqual(budget.summary()['requests'], 2)

    def test_invalid_role_is_rejected_before_credentials_or_model_artifacts(self):
        with self.assertRaisesRegex(ValueError, 'Role'):
            self.planner(role='unconfigured')
        self.credentials.assert_not_called()
        self.assertFalse((self.root/'model').exists())
        self.assertFalse(self.requests)

    def test_explicit_http_retry_counts_both_requests(self):
        count = 0
        def respond(request):
            nonlocal count; count += 1
            if count == 1: return httpx.Response(500, json={'error': {'message': 'temporary', 'type': 'server_error'}})
            return self.response(request)
        planner = self.planner(respond, max_retries=1)
        async def run():
            try: await planner.decide({'question': 'Retry once'})
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(count, 2)
        self.assertEqual(summarize(planner.output/'calls')['requests'], 2)
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['unknown_requests'], 1)
        attempts = [json.loads(p.read_text()) for p in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertEqual([a['retry'] for a in attempts], [False, True])
        self.assertEqual([a['status'] for a in attempts], ['failed_or_cancelled', 'decision_returned'])

    def test_invalid_decision_is_metered_but_never_returned_or_silently_retried(self):
        planner = self.planner(lambda request: self.response(request, {'action': 'query'}), max_retries=1)
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'invalid_model_decision'):
                    await planner.decide({'question': 'Invalid query payload'})
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(summarize(planner.output/'calls')['records'][0]['status'], 'succeeded')
        attempt, = planner.output.glob('decision-*-attempt-*.json')
        self.assertEqual(json.loads(attempt.read_text())['status'], 'invalid_model_decision')

    def test_complete_invalid_outputs_have_safe_feedback_and_visible_artifact(self):
        cases = [
            'not JSON: visible-only-value',
            json.dumps({'action': 'finish', 'untrusted-key-visible-only-value': 'visible-only-value'}),
            json.dumps({'reason': 'visible-only-value'}),
        ]
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                planner = self.planner(lambda request: self.raw_response(request, content),
                                       name=f'invalid-output-{index}', max_retries=1)
                async def run():
                    try:
                        with self.assertRaisesRegex(ValueError, 'invalid_model_decision') as raised:
                            await planner.decide({'question': 'Return an explicitly scoped decision.'})
                        return str(raised.exception)
                    finally:
                        await planner.aclose()
                feedback = asyncio.run(run())
                self.assertNotIn('visible-only-value', feedback)
                self.assertNotIn('diagnostic-hidden-reasoning', feedback)
                output, = planner.output.glob('decision-*-output.json')
                saved = json.loads(output.read_text())
                self.assertEqual(saved['content'], content)
                self.assertEqual(saved['content_sha256'], digest(content))
                self.assertFalse(saved['truncated'])
                self.assertIn(output.name, feedback)
                self.assertIn('validation=', feedback)
                attempt_path, = planner.output.glob('decision-*-attempt-*.json')
                attempt = json.loads(attempt_path.read_text())
                self.assertEqual(attempt['status'], 'invalid_model_decision')
                self.assertEqual(attempt['error_type'], 'ModelBehaviorError')
                self.assertEqual(attempt['visible_output'], {'path': output.name, 'sha256': digest(output.read_bytes())})
                usage = planner.snapshot_usage()['summary']
                self.assertIn(attempt['visible_output'], usage['artifacts'])
                self.assertEqual(usage['calls']['requests'], 1)
                self.assertEqual(usage['calls']['unknown_cost_requests'], 0)
                self.assertGreater(float(usage['calls']['known_estimated_usd']), 0)
                artifacts = '\n'.join(path.read_text() for path in planner.output.rglob('*.json'))
                for forbidden in ('diagnostic-hidden-reasoning', 'diagnostic-header-secret', 'fixture-key', 'reasoning_content'):
                    self.assertNotIn(forbidden, artifacts)
        self.assertEqual(len(self.requests), 3)

    def test_invalid_decision_can_be_corrected_on_the_next_host_turn(self):
        responses = iter(['{"action":', '{"action":"finish"}'])
        planner = self.planner(lambda request: self.raw_response(request, next(responses)), max_retries=1)
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'invalid_model_decision') as raised:
                    await planner.decide({'question': 'Return the next action.'})
                return await planner.decide({'question': 'Return the next action.', 'observation': {
                    'status': 'rejected', 'error_type': 'ValueError', 'reason': str(raised.exception)}})
            finally:
                await planner.aclose()
        decision = asyncio.run(run())
        self.assertEqual(decision.action, 'finish')
        self.assertEqual(len(self.requests), 2)
        attempts = [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertEqual([attempt['status'] for attempt in attempts], ['invalid_model_decision', 'decision_returned'])
        self.assertTrue(all(attempt['attempt'] == 1 and not attempt['retry'] for attempt in attempts))
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['requests'], 2)
        self.assertEqual(len(list(planner.output.glob('decision-*-output.json'))), 2)

    def test_search_with_requirements_receives_safe_repair_on_next_host_turn(self):
        search = {'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': 'equipment'}
        invalid = {'action': 'search_source', 'search': search, 'requirement_ids': ['req-equipment'],
                   'requirements': [{'requirement_id': 'req-equipment', 'description': 'Find equipment evidence'}]}
        corrected = {key: value for key, value in invalid.items() if key != 'requirements'}
        def respond(request):
            if not self.requests:
                return self.raw_response(request, json.dumps(invalid))
            messages = json.dumps(json.loads(request.content)['messages'])
            self.assertIn('one_action_payload', messages)
            self.assertIn('requirements is allowed only with action=plan', messages)
            self.assertIn('use requirement_ids to reference existing requirements', messages)
            return self.raw_response(request, json.dumps(corrected))
        planner = self.planner(respond, max_retries=1)
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'one_action_payload') as raised:
                    await planner.decide({'question': 'Find scoped equipment evidence.'})
                return await planner.decide({'question': 'Find scoped equipment evidence.', 'observation': {
                    'status': 'rejected', 'error_type': 'ValueError', 'reason': str(raised.exception)}})
            finally:
                await planner.aclose()
        decision = asyncio.run(run())
        self.assertEqual(decision.action, 'search_source')
        self.assertEqual(decision.search.source_snapshot_id, 'acme-annual')
        self.assertEqual(decision.requirement_ids, ('req-equipment',))
        self.assertEqual(decision.requirements, ())
        self.assertEqual(len(self.requests), 2)
        attempts = [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertEqual([a['status'] for a in attempts], ['invalid_model_decision', 'decision_returned'])
        self.assertEqual(attempts[0]['validation'][0]['type'], 'value_error')
        self.assertEqual(attempts[0]['validation'][0]['location'], [])
        self.assertTrue(all(a['attempt'] == 1 and not a['retry'] for a in attempts))
        calls = planner.snapshot_usage()['summary']['calls']
        self.assertEqual(calls['requests'], 2)
        self.assertEqual(calls['unknown_cost_requests'], 0)
        self.assertTrue(all(float(record['estimated_usd']) > 0 for record in calls['records']))

    def test_known_contract_errors_have_static_repair_guidance(self):
        cases = [
            ({'action': 'finish', 'evidence_ids': ['ev-existing']},
             'one_action_payload', 'including evidence_ids'),
            ({'action': 'search_source'},
             'selected_action_requires_payload', 'search_source=search'),
            ({'action': 'query'},
             'selected_action_requires_payload', 'query=plan'),
            ({'action': 'answer'},
             'selected_action_requires_payload', 'answer=answer'),
            ({'action': 'plan', 'reason': 'Explicit research scope', 'requirements': [
                {'requirement_id': 'req-business', 'description': 'Read business information',
                 'kind': 'information', 'source_id': 'acme-annual', 'node_id': 'business'}]},
             'requirement_source_fields', 'source_id is allowed for kind=read_node, kind=source_evidence or kind=source_answer'),
            ({'action': 'plan', 'reason': 'Verify original source text', 'requirements': [
                {'requirement_id': 'req-original', 'description': 'Verify the source text',
                 'kind': 'source_evidence'}]},
             'source_evidence_requires_source', 'provide a nonblank source_id'),
            ({'action': 'plan', 'reason': 'Verify original source text', 'requirements': [
                {'requirement_id': 'req-original', 'description': 'Verify the source text',
                 'kind': 'source_evidence', 'source_id': '   '}]},
             'source_evidence_requires_source', 'provide a nonblank source_id'),
            ({'action': 'plan', 'reason': 'Verify original source text', 'requirements': [
                {'requirement_id': 'req-original', 'description': 'Verify the source text',
                 'kind': 'source_evidence', 'source_id': 'acme-annual', 'node_id': 'business'}]},
             'requirement_source_fields', 'For source_evidence or source_answer provide source_id and omit node_id'),
            ({'action': 'plan', 'reason': 'Answer using source citations', 'requirements': [
                {'requirement_id': 'req-answer', 'description': 'Answer the scoped question',
                 'kind': 'source_answer'}]},
             'source_answer_requires_source', 'provide a nonblank source_id'),
            ({'action': 'plan', 'reason': 'Answer using source citations', 'requirements': [
                {'requirement_id': 'req-answer', 'description': 'Answer the scoped question',
                 'kind': 'source_answer', 'source_id': '   '}]},
             'source_answer_requires_source', 'provide a nonblank source_id'),
            ({'action': 'plan', 'reason': 'Answer using source citations', 'requirements': [
                {'requirement_id': 'req-answer', 'description': 'Answer the scoped question',
                 'kind': 'source_answer', 'source_id': 'acme-annual', 'node_id': 'business'}]},
             'requirement_source_fields', 'For source_evidence or source_answer provide source_id and omit node_id'),
            ('{"action":"finish"}{"action":"finish"}',
             'single_json_object', 'exactly one valid JSON object'),
        ]
        for content, rule, suggestion in cases:
            with self.subTest(rule=rule):
                hints = _decision_validation_hints(content if isinstance(content, str) else json.dumps(content))
                self.assertEqual(hints[0]['rule'], rule)
                self.assertIn(suggestion, hints[0]['suggestion'])
                self.assertIn('type', hints[0])
                self.assertIn('location', hints[0])

    def test_source_evidence_missing_source_is_corrected_without_changing_kind(self):
        requirement = {'requirement_id': 'req-original', 'description': 'Verify original source text',
                       'kind': 'source_evidence'}
        invalid = {'action': 'plan', 'reason': 'Original-text verification is required',
                   'requirements': [requirement]}
        corrected = {**invalid, 'requirements': [{**requirement, 'source_id': 'acme-annual'}]}
        def respond(request):
            if not self.requests:
                return self.raw_response(request, json.dumps(invalid))
            messages = json.dumps(json.loads(request.content)['messages'])
            self.assertIn('source_evidence_requires_source', messages)
            self.assertIn('provide a nonblank source_id from the scoped catalog and omit node_id', messages)
            return self.raw_response(request, json.dumps(corrected))
        planner = self.planner(respond)
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'source_evidence_requires_source') as raised:
                    await planner.decide({'question': 'Verify original source text.'})
                return await planner.decide({'question': 'Verify original source text.', 'observation': {
                    'status': 'rejected', 'error_type': 'ValueError', 'reason': str(raised.exception)}})
            finally:
                await planner.aclose()
        decision = asyncio.run(run())
        self.assertEqual(decision.action, 'plan')
        self.assertEqual(decision.requirements[0].kind, 'source_evidence')
        self.assertEqual(decision.requirements[0].source_id, 'acme-annual')
        self.assertIsNone(decision.requirements[0].node_id)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(planner.snapshot_usage()['summary']['calls']['requests'], 2)

    def test_partial_source_answer_receives_safe_guidance_and_keeps_unresolved_work(self):
        answer = {'claims': [{'statement': 'Acme describes a planned capacity expansion.',
            'temporal_basis': 'forward_looking', 'period_context': 'A future period in the selected source',
            'citations': [{'context_id': 'ev-acme-context', 'block_id': 'acme-plan-block',
                           'quote': 'We plan to expand capacity.', 'label': 'Future capacity plan'}]}],
            'model_claimed_coverage': 'partial', 'coverage_note': 'Reported spending still needs verification.',
            'unresolved_questions': []}
        invalid = {'action': 'answer', 'requirement_ids': ['req-answer'], 'answer': answer}
        corrected = {**invalid, 'answer': {**answer, 'unresolved_questions': ['What spending was actually reported?']}}
        cases = [
            (answer, 'answer_coverage_consistency'),
            ({**answer, 'model_claimed_coverage': 'claimed_complete',
              'unresolved_questions': ['What spending was actually reported?']}, 'answer_coverage_consistency'),
            ({**answer, 'unresolved_questions': ['   ']}, 'answer_unresolved_questions'),
        ]
        for value, rule in cases:
            with self.subTest(rule=rule, coverage=value['model_claimed_coverage']):
                hint = _decision_validation_hints(json.dumps({**invalid, 'answer': value}))[0]
                self.assertEqual(hint['rule'], rule)
                self.assertEqual(hint['type'], 'value_error')
                self.assertEqual(hint['location'], ['answer'])
                self.assertNotIn('What spending was actually reported?', json.dumps(hint))
        def respond(request):
            if not self.requests:
                return self.raw_response(request, json.dumps(invalid))
            messages = json.dumps(json.loads(request.content)['messages'])
            self.assertIn('answer_coverage_consistency', messages)
            self.assertIn('keep model_claimed_coverage=partial', messages)
            self.assertIn('Do not claim completion merely to satisfy validation', messages)
            return self.raw_response(request, json.dumps(corrected))
        planner = self.planner(respond, max_retries=1)
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'answer_coverage_consistency') as raised:
                    await planner.decide({'question': 'Separate reported spending from future plans.'})
                return await planner.decide({'question': 'Separate reported spending from future plans.',
                    'observation': {'status': 'rejected', 'error_type': 'ValueError', 'reason': str(raised.exception)}})
            finally:
                await planner.aclose()
        decision = asyncio.run(run())
        self.assertEqual(decision.action, 'answer')
        self.assertEqual(decision.answer.model_claimed_coverage, 'partial')
        self.assertEqual(decision.answer.unresolved_questions, ('What spending was actually reported?',))
        self.assertEqual(decision.answer.claims[0].temporal_basis, 'forward_looking')
        self.assertEqual(len(self.requests), 2)
        attempts = [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertEqual([a['status'] for a in attempts], ['invalid_model_decision', 'decision_returned'])
        self.assertTrue(all(a['attempt'] == 1 and not a['retry'] for a in attempts))
        usage = planner.snapshot_usage()['summary']['calls']
        self.assertEqual(usage['requests'], 2)
        self.assertEqual(usage['unknown_cost_requests'], 0)

    def test_unrecognized_validation_message_never_enters_safe_guidance(self):
        secret = 'private-validation-message-and-input'
        for message in (secret, 'unrelated action payloads are not allowed ' + secret):
            with self.subTest(message=message):
                failure = ValidationError.from_exception_data('AutonomousDecision', [{
                    'type': 'value_error', 'loc': ('reason',), 'input': {'secret': secret},
                    'ctx': {'error': ValueError(message)}}])
                with patch('uteki.agents.data_query.autonomous_model.AutonomousDecision.model_validate_json',
                           side_effect=failure):
                    hints = _decision_validation_hints('{}')
                self.assertEqual(hints, [{'type': 'value_error', 'location': ['reason']}])
                self.assertNotIn(secret, json.dumps(hints))

    def test_normal_stop_with_empty_or_whitespace_content_can_be_corrected_by_host(self):
        for index, content in enumerate(('', ' \n\t' * 36)):
            with self.subTest(content_length=len(content)):
                responses = iter([content, '{"action":"finish"}'])
                def respond(request):
                    output = next(responses)
                    if output == '{"action":"finish"}':
                        messages = json.dumps(json.loads(request.content)['messages'])
                        self.assertIn('single_json_object', messages)
                        self.assertIn('Return exactly one valid JSON object', messages)
                    return self.raw_response(request, output)
                planner = self.planner(respond, name=f'empty-stop-{index}', max_retries=1)
                async def run():
                    try:
                        with self.assertRaisesRegex(ValueError, 'single_json_object') as raised:
                            await planner.decide({'question': 'Return a scoped decision.'})
                        return await planner.decide({'question': 'Return a scoped decision.', 'observation': {
                            'status': 'rejected', 'error_type': 'ValueError', 'reason': str(raised.exception)}})
                    finally:
                        await planner.aclose()
                self.assertEqual(asyncio.run(run()).action, 'finish')
                attempts = [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]
                self.assertEqual([a['status'] for a in attempts], ['invalid_model_decision', 'decision_returned'])
                self.assertTrue(all(a['attempt'] == 1 and not a['retry'] for a in attempts))
                self.assertEqual(attempts[0]['validation'][0]['type'], 'json_invalid')
                output = json.loads((planner.output/attempts[0]['visible_output']['path']).read_text())
                self.assertEqual(output['content'], content)
                self.assertEqual(output['content_sha256'], digest(content))
                self.assertEqual(output['finish_reason'], 'stop')
                usage = planner.snapshot_usage()['summary']
                self.assertIn(attempts[0]['visible_output'], usage['artifacts'])
                self.assertEqual(usage['calls']['requests'], 2)
                self.assertEqual(usage['calls']['unknown_cost_requests'], 0)
                self.assertTrue(all(float(r['estimated_usd']) > 0 for r in usage['calls']['records']))
        self.assertEqual(len(self.requests), 4)

    def test_incomplete_filtered_or_missing_provider_output_remains_a_hard_failure(self):
        cases = [('length', '{"action":"finish"}'), ('content_filter', '{"action":"finish"}'),
                 ('length', '   '), ('content_filter', ''), ('stop', None)]
        for index, (finish_reason, content) in enumerate(cases):
            with self.subTest(finish_reason=finish_reason, content=content):
                planner = self.planner(lambda request: self.raw_response(request, content, finish_reason=finish_reason),
                                       name=f'incomplete-output-{index}', max_retries=1)
                async def run():
                    try:
                        with self.assertRaises(ModelBehaviorError):
                            await planner.decide({'question': 'Do not accept an incomplete decision.'})
                    finally:
                        await planner.aclose()
                asyncio.run(run())
                attempt_path, = planner.output.glob('decision-*-attempt-*.json')
                attempt = json.loads(attempt_path.read_text())
                self.assertEqual(attempt['status'], 'failed_or_cancelled')
                self.assertEqual(attempt['error_type'], 'ModelBehaviorError')
                usage = planner.snapshot_usage()['summary']
                self.assertEqual(usage['calls']['requests'], 1)
                self.assertEqual(usage['calls']['unknown_cost_requests'], 0)
                self.assertGreater(float(usage['calls']['known_estimated_usd']), 0)
                if content is None:
                    self.assertNotIn('visible_output', attempt)
                else:
                    self.assertIn(attempt['visible_output'], usage['artifacts'])
                    output = json.loads((planner.output/attempt['visible_output']['path']).read_text())
                    self.assertEqual(output['content'], content)
                    self.assertEqual(output['finish_reason'], finish_reason)
        self.assertEqual(len(self.requests), len(cases))

    def test_visible_output_is_bounded_with_hash_of_the_complete_content(self):
        content = json.dumps({'action': 'finish', 'unexpected': 'x' * 140000})
        planner = self.planner(lambda request: self.raw_response(request, content))
        async def run():
            try:
                with self.assertRaisesRegex(ValueError, 'invalid_model_decision'):
                    await planner.decide({'question': 'Reject unsupported fields.'})
            finally:
                await planner.aclose()
        asyncio.run(run())
        output_path, = planner.output.glob('decision-*-output.json')
        output = json.loads(output_path.read_text())
        self.assertTrue(output['truncated'])
        self.assertLessEqual(len(output['content']), 128000)
        self.assertEqual(output['content_chars'], len(content))
        self.assertEqual(output['content_sha256'], digest(content))
        self.assertTrue(content.startswith(output['content']))

    def test_budget_rejection_does_not_reuse_the_prior_visible_output(self):
        planner = self.planner(maximum=1)
        async def run():
            try:
                await planner.decide({'question': 'One permitted call.'})
                with self.assertRaises(BudgetExceeded):
                    await planner.decide({'question': 'No second provider response exists.'})
            finally:
                await planner.aclose()
        asyncio.run(run())
        attempts = [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertIn('visible_output', attempts[0])
        self.assertNotIn('visible_output', attempts[1])
        self.assertEqual(len(list(planner.output.glob('decision-*-output.json'))), 1)
        self.assertEqual(len(self.requests), 1)

    def test_timeout_and_cancellation_leave_reserved_requests_and_end_records(self):
        async def slow(request):
            await asyncio.sleep(10)
            return self.response(request)
        planner = self.planner(slow, request_timeout=1)
        async def run():
            try:
                with self.assertRaises(TimeoutError): await planner.decide({'question': 'timeout'})
                task = asyncio.create_task(planner.decide({'question': 'cancel'}))
                # Wait until the second request's start event exists, then cancel.
                for _ in range(500):
                    if len(list((planner.output/'calls').glob('*-start.json'))) == 2: break
                    await asyncio.sleep(0.001)
                self.assertEqual(len(list((planner.output/'calls').glob('*-start.json'))), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(list((planner.output/'calls').glob('*-end.json'))), 2)
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['requests'], 2)
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['unknown_requests'], 2)
        attempts = [json.loads(p.read_text()) for p in sorted(planner.output.glob('decision-*-attempt-*.json'))]
        self.assertEqual(attempts[0]['status'], 'timed_out')
        self.assertEqual(attempts[1]['error_type'], 'CancelledError')

    def test_existing_requests_and_multiple_adapters_share_persistent_limit(self):
        budget = RunBudget(self.root/'budget.sqlite', '1', enforce=False)
        prior = budget.reserve('.01'); budget.settle(prior, '.01')
        first = self.planner(budget=budget, maximum=2)
        second = self.planner(budget=budget, maximum=2, name='second')
        async def run():
            try:
                await first.decide({'question': 'One remaining request'})
                with self.assertRaises(BudgetExceeded): await second.decide({'question': 'Exhausted'})
            finally:
                await first.aclose(); await second.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(budget.summary()['requests'], 2)
        with self.assertRaises(ValueError): _RequestLimitedBudget(budget, 3)

    def test_shared_request_limit_is_atomic_across_concurrent_reservations(self):
        budget = RunBudget(self.root/'budget.sqlite', '1', enforce=False)
        cap = _RequestLimitedBudget(budget, 3)
        def reserve(_):
            try: return cap.reserve('.001')
            except BudgetExceeded: return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(reserve, range(12)))
        self.assertEqual(sum(value is not None for value in values), 3)
        self.assertEqual(budget.summary()['requests'], 3)

    def test_enforced_unknown_cost_blocks_retry_before_second_network_attempt(self):
        count = 0
        def respond(request):
            nonlocal count; count += 1
            return httpx.Response(500, json={'error': {'message': 'temporary', 'type': 'server_error'}})
        planner = self.planner(respond, enforce=True, max_retries=1)
        async def run():
            try:
                with self.assertRaises(BudgetExceeded): await planner.decide({'question': 'Unknown cost blocks retry'})
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(count, 1)
        self.assertEqual(summarize(planner.output/'calls')['requests'], 1)

    def test_unmetered_unknown_price_and_mutated_config_are_rejected(self):
        with self.assertRaises(ValueError):
            SdkAutonomousPlanner('deepseek', 'deepseek-flash', budget=None, max_requests_total=1,
                output=self.root/'bad', credentials_root=self.root)
        with self.assertRaises(ValueError):
            SdkAutonomousPlanner('deepseek', 'unknown-model', budget=RunBudget(self.root/'budget.sqlite', '1'),
                max_requests_total=1, output=self.root/'bad', credentials_root=self.root)
        planner = self.planner(pricing=pricing_snapshot('deepseek', 'deepseek-flash'))
        (planner.output/'model-config.json').write_text('{}')
        async def run():
            try:
                with self.assertRaises(ValueError): await planner.decide({'question': 'tamper'})
            finally: await planner.aclose()
        asyncio.run(run())
        self.assertEqual(self.requests, [])
