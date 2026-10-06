"""Coordinator -> metered autonomous planner -> real SDK over mock HTTP only."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI

from uteki.agents.data_query.autonomous_model import SdkAutonomousPlanner
from uteki.agents.data_query.coordinator import inspect_run
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_company_coordinator as coordinator_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


class CompanyCoordinatorModelTests(unittest.TestCase):
    def setUp(self):
        self.fixture = coordinator_fixtures.CompanyCoordinatorTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.clients, self.model_requests = [], []
        self.client_settings = []
        self.enterContext(patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'offline-coordinator-key'}))
        self.credentials = self.enterContext(patch('uteki.agents.data_query.autonomous_model.load_provider_key',
                                                   return_value='offline_fixture'))
        self.model_config = {'provider': 'deepseek', 'model': 'deepseek-flash',
            'budget_ledger': str(self.root/'shared-model.sqlite'), 'budget_usd': '1', 'budget_policy': 'record_only',
            'max_requests_total': 6, 'max_tokens': 4096, 'request_timeout': 5, 'max_retries': 0}
        self.request = {'question': 'Provide FY2025 revenue and operating margin.',
            'company_config': self.fixture.config, 'include_candidates': True,
            'limits': {'max_steps': 3, 'turn_timeout': 10}}

    def patch_transport(self, handler):
        def factory(**kwargs):
            self.assertEqual(kwargs['max_retries'], 0)
            self.client_settings.append({'timeout': kwargs['timeout'], 'max_retries': kwargs['max_retries']})
            client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            self.clients.append(client)
            return client
        def build(*args, **kwargs):
            # Keep the coordinator's real _planner model_config/budget path intact.
            return SdkAutonomousPlanner(*args, **kwargs, client_factory=factory)
        return self.enterContext(patch('uteki.agents.data_query.autonomous_model.SdkAutonomousPlanner', side_effect=build))

    def respond_with_numeric_actions(self):
        actions = iter(self.fixture.numeric_actions())
        def respond(request):
            body = json.loads(request.content); self.model_requests.append(body)
            packet = json.loads(body['messages'][-1]['content'])
            action = next(actions)
            decision = action(packet) if callable(action) else action
            return httpx.Response(200, json={'id': 'coordinator-mock-' + str(len(self.model_requests)),
                'object': 'chat.completion', 'created': 1, 'model': 'deepseek-flash',
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(decision)}}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})
        return respond

    def respond_with_delegated_numeric_actions(self):
        plan, query, finish = self.fixture.numeric_actions()
        def resume(packet):
            self.assertEqual(packet['role'], 'planner')
            observation = packet['observation']
            self.assertEqual(observation['status'], 'worker_returned')
            self.assertTrue(observation['result']['candidate_only'])
            self.assertEqual(observation['result']['scope'], packet['active_scope'])
            # The parent verifies the numeric requirement using its own query.
            return query(packet)
        actions = {'planner': iter([plan, {'action': 'delegate', 'requirement_ids': ['numbers'],
                                          'delegation': {'instruction': 'Retrieve the specified numeric evidence.'}}, resume, finish]),
                   'worker': iter([query, finish])}
        def respond(request):
            body = json.loads(request.content); self.model_requests.append(body)
            packet = json.loads(body['messages'][-1]['content'])
            action = next(actions[packet['role']])
            decision = action(packet) if callable(action) else action
            return httpx.Response(200, json={'id': 'delegation-mock-' + str(len(self.model_requests)),
                'object': 'chat.completion', 'created': 1, 'model': body['model'],
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(decision)}}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})
        return respond

    def run_query(self, *, name='run', worker_model_config=None):
        return asyncio.run(self.fixture.coordinator.query(self.request, model_config=self.model_config,
            credential_root=self.root, output=self.root/name, worker_model_config=worker_model_config))

    def assert_sealed_and_closed(self, *, name='run'):
        output = self.root/name
        self.assertTrue(self.fixture.ports)
        self.fixture.assert_closed()
        self.assertTrue(self.clients)
        self.assertTrue(all(client.is_closed() for client in self.clients))
        self.assertEqual(inspect_run(output)['status'], 'verified')
        files = json.loads((output/'manifest.json').read_text())['files']
        for key in ('model/model-config.json', 'model-usage.json'):
            self.assertIn(key, files)
            self.assertEqual(files[key], digest((output/key).read_bytes()))
        ref = json.loads((output/'model-usage.json').read_text())
        self.assertIn('model/' + ref['path'], files)
        self.assertEqual(ref['sha256'], files['model/' + ref['path']])
        self.assertEqual(ref['summary']['plan_origin'], 'scripted_fixture')
        for item in ref['summary']['artifacts']:
            self.assertEqual(item['sha256'], files['model/' + item['path']])
        self.assertNotIn('offline-coordinator-key', '\n'.join(p.read_text() for p in (output/'model').rglob('*.json')))
        return files, ref['summary']

    def test_model_config_path_returns_cited_numbers_and_seals_model_artifacts(self):
        constructor = self.patch_transport(self.respond_with_numeric_actions())
        result = self.run_query()
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(constructor.call_count, 1)
        self.assertFalse((self.root/'run/worker-model').exists())
        self.assertFalse((self.root/'run/worker-model-usage.json').exists())
        self.assertEqual(len(self.model_requests), 3)
        files, usage = self.assert_sealed_and_closed()
        self.assertEqual(usage['calls']['requests'], 3)
        self.assertEqual(usage['shared_budget']['requests'], 3)
        self.assertEqual(usage['calls']['unknown_cost_requests'], 0)
        self.assertEqual(len([name for name in files if name.startswith('model/calls/') and name.endswith('-end.json')]), 3)
        self.assertIn('query/turn-001/decision.json', files)
        receipt = json.loads((self.root/'run/query/turn-002/query-receipt.json').read_text())
        self.assertTrue(receipt['result']['computed_facts'])
        self.assertTrue(receipt['result']['evidence'])
        self.assertTrue(any(a['kind'] == 'source_quote' for a in receipt['package']['artifacts']))
        checks = json.loads((self.root/'run/query/result.json').read_text())['coverage'][0]['query_checks']
        self.assertTrue(all(c['status'] == 'satisfied' for c in checks))

    def test_worker_model_has_own_config_and_usage_with_same_persistent_allowance(self):
        worker_config = {**self.model_config, 'model': 'deepseek-v4-pro', 'budget_usd': '1.00',
                         'budget_ledger': str(self.root/'unused/../shared-model.sqlite')}
        constructor = self.patch_transport(self.respond_with_numeric_actions())
        result = self.run_query(worker_model_config=worker_config)
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual([call.kwargs['role'] for call in constructor.call_args_list], ['planner', 'worker'])
        files, usage = self.assert_sealed_and_closed()
        self.assertEqual(len(self.clients), 2)
        self.assertEqual(usage['role'], 'planner')
        worker_usage = json.loads((self.root/'run/worker-model-usage.json').read_text())
        self.assertEqual(worker_usage['summary']['role'], 'worker')
        self.assertEqual(worker_usage['summary']['model'], worker_config['model'])
        self.assertEqual(worker_usage['summary']['calls']['requests'], 0)
        self.assertEqual(worker_usage['summary']['shared_budget']['requests'], 3)
        self.assertEqual(worker_usage['summary']['shared_budget'], usage['shared_budget'])
        self.assertEqual(files['worker-model/' + worker_usage['path']], worker_usage['sha256'])
        for item in worker_usage['summary']['artifacts']:
            self.assertEqual(files['worker-model/' + item['path']], item['sha256'])
        self.assertIn('worker-model-config.input.json', files)

    def test_delegation_uses_distinct_models_and_resumes_parent_with_shared_costs(self):
        self.request['limits']['max_steps'] = 7
        self.model_config.update(reasoning_effort='high', request_timeout=180)
        self.patch_transport(self.respond_with_delegated_numeric_actions())
        result = self.run_query(worker_model_config={**self.model_config, 'model': 'deepseek-v4-pro',
                                                    'reasoning_effort': 'low', 'request_timeout': 75})
        self.assertEqual(result['status'], 'evidence_ready', result)
        _, usage = self.assert_sealed_and_closed()
        worker_usage = json.loads((self.root/'run/worker-model-usage.json').read_text())['summary']
        self.assertEqual([json.loads(body['messages'][-1]['content'])['role'] for body in self.model_requests],
                         ['planner', 'planner', 'worker', 'worker', 'planner', 'planner'])
        self.assertEqual([body['model'] for body in self.model_requests],
                         ['deepseek-flash', 'deepseek-flash', 'deepseek-v4-pro', 'deepseek-v4-pro', 'deepseek-flash', 'deepseek-flash'])
        self.assertEqual([body['reasoning_effort'] for body in self.model_requests],
                         ['high', 'high', 'low', 'low', 'high', 'high'])
        self.assertTrue(all(body['thinking'] == {'type': 'enabled'} for body in self.model_requests))
        self.assertTrue(all('temperature' not in body for body in self.model_requests))
        self.assertEqual(self.client_settings, [{'timeout': 180, 'max_retries': 0},
                                               {'timeout': 75, 'max_retries': 0}])
        self.assertEqual(usage['reasoning_effort'], 'high')
        self.assertEqual(worker_usage['reasoning_effort'], 'low')
        self.assertEqual(usage['thinking_mode'], 'enabled')
        self.assertEqual(worker_usage['thinking_mode'], 'enabled')
        for folder, effort in (('model', 'high'), ('worker-model', 'low')):
            config = json.loads((self.root/'run'/folder/'model-config.json').read_text())
            self.assertEqual(config['reasoning_effort'], effort)
            self.assertEqual(config['thinking_mode'], 'enabled')
        self.assertEqual(usage['calls']['requests'], 4)
        self.assertEqual(worker_usage['calls']['requests'], 2)
        self.assertEqual(usage['shared_budget']['requests'], 6)
        self.assertEqual(worker_usage['shared_budget'], usage['shared_budget'])

    def test_invalid_role_reasoning_is_rejected_before_preparation(self):
        cases = [
            {'provider': 'aihubmix', 'model': 'gpt-5.4-mini', 'reasoning_effort': 'high'},
            {'provider': 'aihubmix', 'model': 'gpt-5.4-mini', 'reasoning_effort': 'none'},
            *[{'reasoning_effort': value} for value in ('medium', '', True, ['low'])],
        ]
        original = dict(self.model_config)
        with patch.object(self.fixture.coordinator, 'prepare', side_effect=AssertionError('must not prepare')) as prepare, \
                patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')) as constructor:
            for role in ('planner', 'worker'):
                for index, invalid in enumerate(cases):
                    self.model_config = {**original, **(invalid if role == 'planner' else {})}
                    worker_config = {**original, **(invalid if role == 'worker' else {})}
                    name = f'invalid-{role}-reasoning-{index}'
                    with self.subTest(role=role, invalid=invalid), self.assertRaisesRegex(ValueError, 'reasoning effort'):
                        self.run_query(name=name, worker_model_config=worker_config)
                    self.assertFalse((self.root/name).exists())
            prepare.assert_not_called()
            constructor.assert_not_called()
        self.credentials.assert_not_called()
        self.assertFalse(self.model_requests)
        self.assertFalse(self.fixture.requests)
        self.assertFalse(self.client_settings)
        self.assertFalse((self.root/'shared-model.sqlite').exists())

    def test_unlimited_shared_budget_runs_both_models_and_keeps_null_limits(self):
        self.model_config.update(budget_usd=None, max_requests_total=None)
        self.request['limits']['max_steps'] = 7
        self.patch_transport(self.respond_with_delegated_numeric_actions())
        result = self.run_query(worker_model_config={**self.model_config, 'model': 'deepseek-v4-pro'})
        self.assertEqual(result['status'], 'evidence_ready', result)
        files, usage = self.assert_sealed_and_closed()
        worker_reference = json.loads((self.root/'run/worker-model-usage.json').read_text())
        worker_usage = worker_reference['summary']
        self.assertEqual([json.loads(body['messages'][-1]['content'])['role'] for body in self.model_requests],
                         ['planner', 'planner', 'worker', 'worker', 'planner', 'planner'])
        self.assertEqual(usage['calls']['requests'], 4)
        self.assertEqual(worker_usage['calls']['requests'], 2)
        self.assertEqual(usage['shared_budget']['requests'], 6)
        self.assertIsNone(usage['shared_budget']['limit_usd'])
        self.assertEqual(usage['shared_budget']['enforcement'], 'record_only')
        self.assertEqual(worker_usage['shared_budget'], usage['shared_budget'])
        self.assertEqual(files['worker-model/' + worker_reference['path']], worker_reference['sha256'])
        for folder in ('model', 'worker-model'):
            config = json.loads((self.root/'run'/folder/'model-config.json').read_text())
            self.assertIsNone(config['max_requests_total'])
            self.assertIsNone(config['budget_at_start']['limit_usd'])
        for item in worker_usage['artifacts']:
            self.assertEqual(files['worker-model/' + item['path']], item['sha256'])

    def test_unlimited_budget_does_not_remove_the_shared_task_step_limit(self):
        self.model_config.update(budget_usd=None, max_requests_total=None)
        self.request['limits']['max_steps'] = 5
        self.patch_transport(self.respond_with_delegated_numeric_actions())
        result = self.run_query(worker_model_config={**self.model_config, 'model': 'deepseek-v4-pro'})
        self.assertEqual(result['status'], 'limited', result)
        self.assertNotEqual(result['stop_reason'], 'BudgetExceeded')
        self.assertEqual(len(self.model_requests), 5)
        _, usage = self.assert_sealed_and_closed()
        worker_usage = json.loads((self.root/'run/worker-model-usage.json').read_text())['summary']
        self.assertEqual(usage['calls']['requests'], 3)
        self.assertEqual(worker_usage['calls']['requests'], 2)
        self.assertEqual(usage['shared_budget']['requests'], 5)
        self.assertIsNone(usage['shared_budget']['limit_usd'])
        self.assertEqual(worker_usage['shared_budget'], usage['shared_budget'])
        query_result = json.loads((self.root/'run/query/result.json').read_text())
        self.assertEqual(query_result['decision_budget'], {'limit': 5, 'used': 5})

    def test_null_and_finite_role_limits_cannot_be_mixed_before_preparation(self):
        cases = [
            ({'budget_usd': None, 'max_requests_total': None}, {'budget_usd': '1'}),
            ({'budget_usd': '1', 'max_requests_total': None}, {'budget_usd': None}),
            ({'budget_usd': None, 'max_requests_total': None}, {'max_requests_total': 6}),
            ({'budget_usd': None, 'max_requests_total': 6}, {'max_requests_total': None}),
        ]
        original = dict(self.model_config)
        with patch.object(self.fixture.coordinator, 'prepare', side_effect=AssertionError('must not prepare')) as prepare, \
                patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')) as constructor:
            for index, (parent_values, worker_values) in enumerate(cases):
                self.model_config = {**original, **parent_values}
                worker_config = {**self.model_config, **worker_values}
                name = f'null-mismatch-{index}'
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'must share'):
                    self.run_query(name=name, worker_model_config=worker_config)
                self.assertFalse((self.root/name).exists())
            prepare.assert_not_called()
            constructor.assert_not_called()
        self.credentials.assert_not_called()
        self.assertFalse(self.model_requests)
        self.assertFalse(self.fixture.requests)
        self.assertFalse((self.root/'shared-model.sqlite').exists())

    def test_null_usd_budget_with_enforcement_is_rejected_before_preparation(self):
        self.model_config.update(budget_usd=None, max_requests_total=None, budget_policy='enforced')
        with patch.object(self.fixture.coordinator, 'prepare', side_effect=AssertionError('must not prepare')) as prepare, \
                patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')) as constructor:
            with self.assertRaisesRegex(ValueError, 'record_only'):
                self.run_query()
            prepare.assert_not_called()
            constructor.assert_not_called()
        self.credentials.assert_not_called()
        self.assertFalse(self.model_requests)
        self.assertFalse((self.root/'run').exists())
        self.assertFalse((self.root/'shared-model.sqlite').exists())

    def test_worker_requests_exhaust_parent_allowance_without_reset_on_resume(self):
        self.request['limits']['max_steps'] = 7
        self.model_config['max_requests_total'] = 4
        self.patch_transport(self.respond_with_delegated_numeric_actions())
        result = self.run_query(worker_model_config={**self.model_config, 'model': 'deepseek-v4-pro'})
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stop_reason'], 'BudgetExceeded')
        _, usage = self.assert_sealed_and_closed()
        worker_usage = json.loads((self.root/'run/worker-model-usage.json').read_text())['summary']
        self.assertEqual(len(self.model_requests), 4)
        self.assertEqual(usage['shared_budget']['requests'], 4)
        self.assertEqual(usage['calls']['requests'], 2)
        self.assertEqual(worker_usage['calls']['requests'], 2)

    def test_worker_initialization_failure_still_closes_and_seals_parent(self):
        self.patch_transport(self.respond_with_numeric_actions())
        result = self.run_query(worker_model_config={**self.model_config, 'model': 'unsupported-fixture-model'})
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stop_reason'], 'ValueError')
        _, usage = self.assert_sealed_and_closed()
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(usage['calls']['requests'], 0)
        self.assertFalse(self.model_requests)

    def test_worker_budget_mismatch_is_rejected_before_preparation_or_model_creation(self):
        changed = {'budget_ledger': str(self.root/'separate.sqlite'), 'budget_usd': '2',
                   'budget_policy': 'enforced', 'max_requests_total': 7}
        with patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')) as constructor:
            for key, value in changed.items():
                with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'must share'):
                    self.run_query(name=key, worker_model_config={**self.model_config, key: value})
                self.assertFalse((self.root/key).exists())
            constructor.assert_not_called()
        self.credentials.assert_not_called()
        self.assertFalse(self.fixture.requests)
        self.assertFalse((self.root/'shared-model.sqlite').exists())

    def test_worker_input_modes_are_validated_before_preparation(self):
        invalid_inputs = [
            {'planner': ScriptedPlanner([]), 'worker_model_config': self.model_config},
            {'model_config': self.model_config, 'worker_model_config': self.model_config,
             'worker_planner': ScriptedPlanner([])},
            {'model_config': self.model_config, 'worker_planner': ScriptedPlanner([])},
            {'planner': ScriptedPlanner([]), 'worker_planner': object()},
        ]
        with patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')) as constructor, \
                patch.object(self.fixture.coordinator, 'prepare', side_effect=AssertionError('must not prepare')) as prepare:
            for index, options in enumerate(invalid_inputs):
                output = self.root/f'invalid-worker-{index}'
                with self.subTest(index=index), self.assertRaises(ValueError):
                    asyncio.run(self.fixture.coordinator.query(self.request, output=output, **options))
                self.assertFalse(output.exists())
            constructor.assert_not_called()
            prepare.assert_not_called()
        self.credentials.assert_not_called()
        self.assertFalse(self.fixture.requests)

    def test_injected_worker_preserves_fixture_path_without_model_construction(self):
        worker = ScriptedPlanner([])
        with patch.object(self.fixture.coordinator, '_planner', side_effect=AssertionError('must not initialize')):
            result = asyncio.run(self.fixture.coordinator.query(self.request, output=self.root/'fixture-worker',
                planner=ScriptedPlanner(self.fixture.numeric_actions()), worker_planner=worker))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertFalse(worker.packets)
        self.credentials.assert_not_called()
        self.assertEqual(inspect_run(self.root/'fixture-worker')['status'], 'verified')

    def test_existing_shared_allowance_exhaustion_cannot_report_success(self):
        budget = RunBudget(self.model_config['budget_ledger'], '1', enforce=False)
        token = budget.reserve('.01'); budget.settle(token, '.01')
        self.model_config['max_requests_total'] = 2
        self.patch_transport(self.respond_with_numeric_actions())
        result = self.run_query()
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stop_reason'], 'BudgetExceeded')
        self.assertEqual(len(self.model_requests), 1)
        _, usage = self.assert_sealed_and_closed()
        self.assertEqual(usage['calls']['requests'], 1)
        self.assertEqual(usage['shared_budget']['requests'], 2)
        self.assertTrue(result['gaps'])

    def test_rerun_same_prepared_sources_preserves_old_result_and_spent_allowance(self):
        self.model_config['max_requests_total'] = 3
        self.patch_transport(self.respond_with_numeric_actions())
        first = self.run_query(name='first')
        self.assertEqual(first['status'], 'evidence_ready', first)
        frozen_manifest = (self.root/'first/manifest.json').read_bytes()
        self.request = {'question': self.request['question'], 'prepared_run': str(self.root/'first/prepare'),
                        'include_candidates': True, 'limits': self.request['limits']}
        second = self.run_query(name='second')
        self.assertEqual(second['status'], 'failed', second)
        self.assertEqual(second['stop_reason'], 'BudgetExceeded')
        self.assertEqual(len(self.model_requests), 3)
        self.assertEqual((self.root/'first/manifest.json').read_bytes(), frozen_manifest)
        self.assertEqual(second['dataset'], first['dataset'])
        self.assert_sealed_and_closed(name='first')
        _, usage = self.assert_sealed_and_closed(name='second')
        self.assertEqual(usage['calls']['requests'], 0)
        self.assertEqual(usage['shared_budget']['requests'], 3)

    def test_retrying_model_exception_preserves_each_attempt_and_closes_ports(self):
        def fail(request):
            self.model_requests.append(json.loads(request.content))
            return httpx.Response(500, json={'error': {'message': 'mock failure', 'type': 'server_error'}})
        self.model_config['max_retries'] = 1
        self.patch_transport(fail)
        result = self.run_query()
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stop_reason'], 'InternalServerError')
        _, usage = self.assert_sealed_and_closed()
        self.assertEqual(len(self.model_requests), 2)
        self.assertEqual(usage['calls']['requests'], 2)
        self.assertEqual(usage['shared_budget']['unknown_requests'], 2)
        self.assertTrue(all(record['status'] == 'failed_or_cancelled' for record in usage['calls']['records']))

    def test_model_timeout_is_failed_and_accounted_in_final_manifest(self):
        async def slow(request):
            self.model_requests.append(json.loads(request.content))
            await asyncio.sleep(20)
            raise AssertionError('Mock should have been cancelled')
        self.model_config['request_timeout'] = 1
        self.patch_transport(slow)
        result = self.run_query()
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stop_reason'], 'TimeoutError')
        _, usage = self.assert_sealed_and_closed()
        self.assertEqual(usage['calls']['requests'], 1)
        self.assertEqual(usage['shared_budget']['unknown_requests'], 1)
        attempt = json.loads((self.root/'run/model/decision-0001-attempt-01.json').read_text())
        self.assertEqual(attempt['status'], 'timed_out')

    def test_cancelled_model_attempt_is_drained_and_sealed_without_success(self):
        started = asyncio.Event()
        async def slow(request):
            self.model_requests.append(json.loads(request.content)); started.set()
            await asyncio.sleep(20)
            raise AssertionError('Mock should have been cancelled')
        self.patch_transport(slow)
        async def run():
            task = asyncio.create_task(self.fixture.coordinator.query(self.request, model_config=self.model_config,
                worker_model_config={**self.model_config, 'model': 'deepseek-v4-pro'},
                credential_root=self.root, output=self.root/'run'))
            await asyncio.wait_for(started.wait(), 4)
            task.cancel(); await asyncio.sleep(0); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(run())
        _, usage = self.assert_sealed_and_closed()
        result = inspect_run(self.root/'run')['result']
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(usage['calls']['requests'], 1)
        self.assertEqual(usage['shared_budget']['unknown_requests'], 1)
        self.assertEqual(usage['calls']['records'][0]['error_type'], 'CancelledError')
        worker_usage = json.loads((self.root/'run/worker-model-usage.json').read_text())['summary']
        self.assertEqual(len(self.clients), 2)
        self.assertEqual(worker_usage['calls']['requests'], 0)
        self.assertEqual(worker_usage['shared_budget'], usage['shared_budget'])
