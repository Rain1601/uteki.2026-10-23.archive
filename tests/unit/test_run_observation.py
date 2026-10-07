"""Offline observation acceptance: synthetic tools and mocked HTTP, never live models."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from uteki.agents.runtime import observation as module
from uteki.agents.runtime.observation import ObservationRecorder, observed_run
from uteki.domain.runs.observation import ObservationError
from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from tests.unit import test_autonomous_model as sdk_fixtures
from tests.unit import test_company_coordinator as coordinator_fixtures
from tests.unit import test_autonomous_worker as worker_fixtures
from tests.unit import test_extraction_batches as extraction_fixtures


def events(root):
    return [json.loads(path.read_text()) for path in sorted(root.glob('*/events/*.json'))]


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 20


class FakeModel:
    def __init__(self, usage=None):
        self.calls = 0
        self.usage = usage or Usage()
    async def get_response(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(usage=self.usage, response_id='offline-response', request_id=None)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.observation_root = self.root/'observations'
        self.output = self.root/'business'

    def recorder(self, **options):
        return ObservationRecorder(self.observation_root, self.output, kind='query', role='planner',
                                   origin='scripted_fixture', **options)

    def test_atomic_parallel_events_keep_contiguous_sequence_and_no_overwrite(self):
        recorder = self.recorder()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: recorder.context.for_step(i).emit('step.started', ordinal=i), range(1, 21)))
        recorder.finish(recorder.context, result={'status': 'partial'})
        records = events(self.observation_root)
        self.assertEqual([event['seq'] for event in records], list(range(1, 23)))
        self.assertEqual(len({event['event_id'] for event in records}), 22)
        self.assertEqual(records[-1]['type'], 'run.finished')
        path = recorder.directory/'events/000000000001.json'
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            module._atomic(path, {'unexpected': True})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(recorder.directory.rglob('.pending-*')))
        with self.assertRaises(ObservationError): recorder.context.guard()

    def test_separate_roots_symlinks_and_cross_process_writer_are_rejected(self):
        for root in (self.output, self.output/'inside', self.root):
            with self.assertRaises(ValueError):
                ObservationRecorder(root, self.output, kind='query', role='planner', origin='scripted_fixture')
        link = self.root/'linked'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            ObservationRecorder(link/'obs', self.output, kind='query', role='planner', origin='scripted_fixture')
        recorder = self.recorder()
        with patch.object(module.os, 'getpid', return_value=recorder._pid + 1):
            with self.assertRaises(ObservationError): recorder.context.guard()
        recorder.finish(recorder.context)

    def test_record_failure_before_provider_releases_only_known_unsent_reservation(self):
        recorder = self.recorder()
        self.output.mkdir()
        budget = RunBudget(self.root/'budget.sqlite', '1')
        inner = FakeModel()
        metered = MeteredModel(inner, self.output/'calls', 'planner', 'aihubmix', 'gpt-5.4-mini',
            pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget, observation_context=recorder.context.for_step(1))
        atomic = module._atomic
        def fail(path, value, **kwargs):
            if value.get('type') == 'model_call.started': raise OSError('private detail')
            return atomic(path, value, **kwargs)
        try:
            with patch.object(module, '_atomic', side_effect=fail), self.assertRaises(ObservationError):
                asyncio.run(metered.get_response(input='offline', model_settings=SimpleNamespace(max_tokens=20)))
            self.assertEqual(inner.calls, 0)
            self.assertEqual(budget.summary()['in_flight_requests'], 0)
            self.assertEqual(budget.summary()['unknown_requests'], 0)
            with self.assertRaises(ObservationError):
                asyncio.run(metered.get_response(input='offline', model_settings=SimpleNamespace(max_tokens=20)))
            self.assertEqual(budget.summary()['requests'], 1)
            self.assertNotIn('private detail', json.dumps(events(self.observation_root)))
        finally: recorder.finish(recorder.context)

    def test_finished_event_failure_still_saves_raw_call_and_settles_budget(self):
        recorder = self.recorder()
        self.output.mkdir()
        budget = RunBudget(self.root/'budget.sqlite', '1')
        inner = FakeModel()
        model = MeteredModel(inner, self.output/'calls', 'planner', 'aihubmix', 'gpt-5.4-mini',
            pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget, observation_context=recorder.context.for_step(1))
        atomic = module._atomic
        def fail(path, value, **kwargs):
            if value.get('type') == 'model_call.finished': raise OSError('offline disk failure')
            return atomic(path, value, **kwargs)
        try:
            with patch.object(module, '_atomic', side_effect=fail), self.assertRaises(ObservationError):
                asyncio.run(model.get_response(input='offline', model_settings=SimpleNamespace(max_tokens=20)))
            self.assertEqual(inner.calls, 1)
            report = summarize(self.output/'calls')
            self.assertEqual(report['unknown_cost_requests'], 0)
            self.assertEqual(budget.summary()['in_flight_requests'], 0)
            self.assertEqual(report['records'][0]['status'], 'succeeded')
        finally: recorder.finish(recorder.context)

    def test_budget_block_has_no_fake_call_and_sdk_default_zero_remains_unknown(self):
        recorder = self.recorder()
        self.output.mkdir()
        budget = RunBudget(self.root/'tiny.sqlite', '0.00000001')
        inner = FakeModel(Usage(0, 0))
        model = MeteredModel(inner, self.output/'calls', 'planner', 'aihubmix', 'gpt-5.4-mini',
            pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget, observation_context=recorder.context)
        try:
            with self.assertRaises(BudgetExceeded):
                asyncio.run(model.get_response(input='offline', model_settings=SimpleNamespace(max_tokens=20)))
            self.assertFalse(any(e['type'].startswith('model_call.') for e in events(self.observation_root)))
            self.assertEqual(inner.calls, 0)
            model.budget = None
            asyncio.run(model.get_response())
            record = summarize(self.output/'calls')['records'][0]
            self.assertEqual(record['usage_presence'], 'unknown')
            self.assertIsNone(record['usage'])
            self.assertIsNone(record['estimated_usd'])
        finally: recorder.finish(recorder.context)

    def test_real_sdk_mock_transport_links_calls_without_prompt_changes(self):
        fixture = sdk_fixtures.AutonomousModelTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.root = fixture.root.resolve()
        output = fixture.root/'model'
        async def run():
            with observed_run(output=output, kind='query', role='planner', origin='scripted_fixture',
                              observation_root=fixture.root/'observations') as context:
                planner = fixture.planner()
                try:
                    await planner.decide({'question': 'Offline fixture'}, observation_context=context.for_step(1))
                finally:
                    await planner.aclose()
        asyncio.run(run())
        records = events(fixture.root/'observations')
        calls = [e for e in records if e['type'].startswith('model_call.')]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['call_id'], calls[1]['call_id'])
        self.assertEqual(calls[1]['step_id'], calls[0]['run_id']+'-turn-001')
        self.assertEqual(calls[1]['data']['attempt'], 1)
        record = json.loads((output/calls[1]['data']['record_ref']['path']).read_text())
        self.assertEqual(record['usage_presence'], 'reported')
        self.assertEqual(record['usage']['input_tokens'], 100)
        self.assertNotIn(calls[0]['run_id'], json.dumps(fixture.requests))
        self.assertEqual(json.loads(fixture.requests[0]['messages'][1]['content']), {'question': 'Offline fixture'})

    def test_query_preparation_rejections_and_worker_keep_original_artifacts(self):
        fixture = coordinator_fixtures.CompanyCoordinatorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        output = fixture.root.resolve()/'observed-query'
        obs = fixture.root.resolve()/'observations'
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner
        planner = ScriptedPlanner([{'action': 'not_valid'}, *fixture.numeric_actions()])
        result = asyncio.run(fixture.coordinator.query({'question': 'FY2025 revenue',
            'company_config': fixture.config, 'include_candidates': True, 'limits': {'max_steps': 4}},
            planner=planner, output=output, observation_root=obs))
        self.assertEqual(result['status'], 'evidence_ready')
        records = events(obs)
        phases = {e['data'].get('phase') for e in records if e['type'] == 'step.started'}
        self.assertTrue({'prepare', 'acquire', 'materialize', 'planning'} <= phases)
        steps = [e for e in records if e['type'] == 'step.finished' and e['data'].get('action')]
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0]['data']['status'], 'rejected')
        self.assertEqual(steps[0]['data']['action'], 'invalid')
        self.assertEqual(records[-1]['type'], 'run.finished')
        self.assertEqual(coordinator_fixtures.inspect_run(output)['status'], 'verified')
        fixture.assert_closed()
        self.assertFalse(any('observations' in name for name in json.loads((output/'manifest.json').read_text())['files']))

    def test_verified_scope_transition_reaches_reader_at_its_own_revision(self):
        from apps.review_workbench.data import agent_runs_live as view
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner
        fixture = coordinator_fixtures.CompanyCoordinatorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        output, obs = fixture.root.resolve()/'observed-query', fixture.root.resolve()/'observations'
        result = asyncio.run(fixture.coordinator.query({'question': 'Read Business and get 2024 original.',
            'company_config': fixture.config, 'include_candidates': True, 'limits': {'max_steps': 6}},
            planner=ScriptedPlanner(fixture.callback_actions()), output=output, observation_root=obs))
        records = events(obs)
        rid = records[0]['run_id']
        scope_events = [e for e in records if e['type'] == 'artifact.published'
                        and e['data']['ref']['path'].endswith('scope.json')]
        self.assertEqual(len(scope_events), 2)
        before = view.load_run(obs, rid, output_roots=(fixture.root.resolve(),), revision=scope_events[1]['seq']-1)
        after = view.load_run(obs, rid, output_roots=(fixture.root.resolve(),))
        self.assertEqual(len(before['scope']['source_snapshot_ids']), 1)
        self.assertEqual(len(after['scope']['source_snapshot_ids']), 2)
        self.assertEqual(after['scope']['snapshot_id'], result['active_scope']['snapshot_id'])
        self.assertTrue(after['root_terminal'])
        self.assertEqual(coordinator_fixtures.inspect_run(output)['status'], 'verified')

    def test_worker_child_has_explicit_ownership(self):
        fixture = worker_fixtures.AutonomousWorkerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner, plan, read
        worker = ScriptedPlanner([read(), {'action': 'finish'}])
        agent, parent = fixture.make_agent([plan('business'), worker_fixtures.delegate(), read(), {'action': 'finish'}], worker,
                                          limits={'max_steps': 6})
        output = fixture.root.resolve()/'observed'
        obs = fixture.root.resolve()/'observations'
        with observed_run(output=output, kind='query', role='planner', origin='scripted_fixture',
                          observation_root=obs, scope=fixture.scope) as context:
            agent.observation_context = context
            result = asyncio.run(agent.run(fixture.request, output=output))
        self.assertEqual(result['status'], 'evidence_ready')
        starts = [e for e in events(obs) if e['type'] == 'run.started']
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts[1]['parent_run_id'], starts[0]['run_id'])
        self.assertEqual(starts[1]['parent_step_id'], starts[0]['run_id']+'-turn-002')
        child_artifacts = [e['data']['ref'] for e in events(obs) if e['type'] == 'artifact.published'
                           and e['run_id'] == starts[1]['run_id']]
        self.assertTrue(child_artifacts)
        self.assertTrue(all(r['run_id'] == starts[1]['run_id'] for r in child_artifacts))
        self.assertEqual(events(obs)[-1]['run_id'], starts[0]['run_id'])

    def test_worker_calls_in_shared_model_folder_keep_child_run_owner(self):
        self.output.mkdir()
        # Recorder starts before business output exists; this pre-existing-output case must reject.
        with self.assertRaises(ValueError): self.recorder()
        self.output.rmdir()
        recorder = self.recorder()
        self.output.mkdir()
        inner = FakeModel()
        with observed_run(output=self.output/'query/worker', kind='worker', role='worker',
                          origin='scripted_fixture', observation_context=recorder.context.for_step(2), child=True) as child:
            model = MeteredModel(inner, self.output/'shared-worker-model', 'autonomous_worker',
                'aihubmix', 'gpt-5.4-mini', pricing_snapshot('aihubmix', 'gpt-5.4-mini'),
                observation_context=child.for_step(1))
            asyncio.run(model.get_response())
            child_id = child.run_id
        recorder.finish(recorder.context)
        records = events(self.observation_root)
        call_events = [e for e in records if e['type'].startswith('model_call.')]
        self.assertEqual(len(call_events), 2)
        self.assertTrue(all(e['run_id'] == child_id and e['data']['record_ref']['run_id'] == child_id for e in call_events))
        call_refs = [e for e in records if e['type'] == 'artifact.published' and
                     'shared-worker-model/' in e['data']['ref']['path']]
        self.assertEqual(len(call_refs), 2)
        self.assertTrue(all(e['run_id'] == child_id for e in call_refs))

    def test_query_financial_batch_is_one_extractor_child_and_reuse_adds_no_run(self):
        from tests.unit import test_company_financial_tasks as fixtures
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner
        fixture = fixtures.CompanyFinancialTaskTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        task_id = fixture.task['task_id']
        plan = {'action': 'plan', 'reason': 'Explicit offline batch', 'requirements': [{
            'kind': 'financial_extract', 'requirement_id': 'table', 'description': 'Assets batch',
            'financial_task_id': task_id, 'batch_index': 1}]}
        extract = {'action': 'financial_extract', 'requirement_ids': ['table'],
                   'financial_extraction': {'task_id': task_id, 'batch_index': 1}}
        planner = ScriptedPlanner([plan, extract, extract, {'action': 'finish'}])
        output, obs = fixture.root/'observed-query', fixture.root/'observations'
        request = {**fixture.request, 'limits': {'max_steps': 4}}
        result = asyncio.run(fixture.coordinator.query(request, planner=planner,
            financial_extractor=fixture.fixture_extract, extractor_model_config=fixture.config,
            method_root=fixture.root, credential_root=fixture.root, output=output, observation_root=obs))
        self.assertEqual(result['status'], 'candidate_ready', result)
        records = events(obs)
        starts = [e for e in records if e['type'] == 'run.started']
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts[1]['data']['role'], 'extractor')
        self.assertEqual(starts[1]['parent_step_id'], starts[0]['run_id']+'-turn-002')
        self.assertFalse(any(e['type'].startswith('model_call.') for e in records))
        reuse = [e for e in records if e['type'] == 'artifact.published' and e['data'].get('reused')]
        self.assertEqual(len(reuse), 1)
        self.assertEqual(reuse[0]['step_id'], starts[0]['run_id']+'-turn-003')
        self.assertEqual(reuse[0]['data']['ref']['run_id'], starts[1]['run_id'])
        self.assertEqual(fixtures.inspect_run(output)['status'], 'verified')

    def test_standalone_extraction_and_batch_are_observed_without_fake_model_calls(self):
        from uteki.infrastructure.research_data.direct_extraction import run_direct_extraction
        from uteki.infrastructure.research_data.extraction_batches import run_extraction_batch
        fixture = extraction_fixtures.ExtractionBatchTests()
        fixture.method(self.root)
        dataset, job = fixture.source(self.root/'material')
        async def model(packet): return {'records': [], 'relations': [], 'gaps': []}
        for batch in (False, True):
            output = self.root/('batch' if batch else 'direct')
            if batch:
                result = asyncio.run(run_extraction_batch(dataset, job, output, task_profile=self.root/'task.json',
                    method_root=self.root, batch_index=0, model_config=fixture.config(self.root),
                    credentials_root=self.root, model_call=model, observation_root=self.observation_root))
            else:
                result = asyncio.run(run_direct_extraction(dataset, job, output, strategy='direct',
                    model_call=model, observation_root=self.observation_root))
            self.assertEqual(result['status'], 'candidate')
        records = events(self.observation_root)
        self.assertEqual(sum(e['type'] == 'run.started' for e in records), 2)
        self.assertEqual(sum(e['type'] == 'run.finished' for e in records), 2)
        self.assertFalse(any(e['type'].startswith('model_call.') for e in records))
        self.assertTrue(any(e['data'].get('phase') == 'normalize_and_project' for e in records))

    def test_cancel_and_forced_termination_do_not_invent_completion(self):
        with self.assertRaises(asyncio.CancelledError):
            with observed_run(output=self.output, kind='query', role='planner', origin='scripted_fixture',
                              observation_root=self.observation_root):
                raise asyncio.CancelledError()
        self.assertEqual(events(self.observation_root)[-1]['data']['status'], 'cancelled')
        crashed = self.root/'crashed-observations'
        script = ('from uteki.agents.runtime.observation import ObservationRecorder; import time; '
                  'r=ObservationRecorder(__import__("sys").argv[1], __import__("sys").argv[2], '
                  'kind="query", role="planner", origin="scripted_fixture", heartbeat_seconds=0.05); time.sleep(30)')
        process = subprocess.Popen([sys.executable, '-c', script, str(crashed), str(self.root/'crashed-output')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while not list(crashed.glob('*/heartbeat.json')) and time.monotonic() < deadline:
                if process.poll() is not None: self.fail(process.stderr.read().decode())
                time.sleep(0.01)
            self.assertTrue(list(crashed.glob('*/heartbeat.json')))
            process.kill()
            process.wait(timeout=5)
            self.assertFalse(any(e['type'] == 'run.finished' for e in events(crashed)))
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            process.stderr.close()
