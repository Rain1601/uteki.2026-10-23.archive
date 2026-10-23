"""A late worker observation must not absorb work performed by its recovery host."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.openai_state import OpenAIState
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class RecoveryTimingTests(unittest.TestCase):
    def test_expired_or_cancelled_restore_does_not_start_another_model_request(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for cancelled in (False,True):
            with self.subTest(cancelled=cancelled):
                case=F['case']();self.addCleanup(case.doCleanups)
                request=deepcopy(case.request);request['run_policy']['max_wall_seconds']=5
                case.context=case.service.create_context(request,request_key='bounded-restore')['context_ref']
                case.catalog.close()
                with (case.root/'bounded-restore.log').open('w') as log:
                    worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                        str(case.root),case.context,str(ROOT/'config/data_platform'),'native_tool_response_committed@1'],
                        cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                    observed=worker.wait(timeout=30)
                self.assertEqual(observed['returncode'],79,(case.root/'bounded-restore.log').read_text())
                with Catalog.open(case.root) as catalog:
                    worker.record(catalog,case.context)
                    before=Session(catalog,case.context).data;unused=F['ScriptedModel']()
                    load=OpenAIState.load
                    async def exercise():
                        entered=asyncio.Event()
                        async def held_load(state,agent):
                            value=await load(state,agent)
                            entered.set()
                            if cancelled:await asyncio.Event().wait()
                            else:await asyncio.sleep(5.05)
                            return value
                        with patch.object(OpenAIState,'load',held_load):
                            task=asyncio.create_task(run_offline(DataService(catalog),case.context,profile,
                                model=unused,limits=F['runtime_limits'](),recover=True))
                            await asyncio.wait_for(entered.wait(),5)
                            if cancelled:task.cancel()
                            return await asyncio.wait_for(task,10)
                    result=asyncio.run(exercise())
                    self.assertEqual(unused.inputs,[])
                    self.assertEqual(result['delivery']['delivery']['stop_reason'],'cancelled' if cancelled else 'wall_time')
                    after=Session(catalog,case.context).data
                    self.assertGreaterEqual(after['wall_seconds'],before['wall_seconds'])
                    if not cancelled:self.assertGreaterEqual(after['wall_seconds'],5.05)
                    ledger=RunBudget.open_existing(case.root/after['native_execution']['ledger_path'],'0',
                        root_run_id=after['context']['root_run_id'])
                    self.assertEqual(ledger.summary()['requests'],1)
                    self.assertEqual(ledger.inspect_root()['stop_reason'],'cancelled' if cancelled else 'wall_time')

    def test_recovery_host_exit_needs_its_own_observation_at_three_commit_boundaries(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ('host_recovery_started','runtime_session_terminal','native_outcome_committed'):
            with self.subTest(phase=phase):
                case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
                def exit_at(point, *, recover=False):
                    with (case.root/(point+'.log')).open('w') as log:
                        command=[sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                            str(case.root),case.context,str(ROOT/'config/data_platform'),point]
                        if recover:command.append('resume')
                        worker=ObservedWorker(command,cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                        observation=worker.wait(timeout=30)
                    self.assertEqual(observation['returncode'],79,(case.root/(point+'.log')).read_text())
                    return worker,observation
                original_worker,original_observation=exit_at('clarification_object_written')
                recovery_worker,recovery_observation=exit_at(phase,recover=True)
                with Catalog.open(case.root) as catalog:
                    service=DataService(catalog);unused=F['ScriptedModel']()
                    original_worker.record(catalog,case.context)
                    before=Session(catalog,case.context)
                    attempts=before.data['native_execution']['recovery_attempts']
                    self.assertEqual(len(attempts),1);self.assertEqual(attempts[0]['status'],'active')
                    self.assertEqual(attempts[0]['owner_pid'],recovery_worker.child.pid)
                    with self.assertRaises(CatalogError) as caught:
                        asyncio.run(run_offline(service,case.context,profile,model=unused,
                            limits=F['runtime_limits'](),recover=True))
                    self.assertIn('recovery host',str(caught.exception))
                    self.assertEqual(Session(catalog,case.context).head_ref,before.head_ref)
                    observation_ref=recovery_worker.record(catalog,case.context)
                    result=asyncio.run(run_offline(service,case.context,profile,model=unused,
                        limits=F['runtime_limits'](),recover=True))
                    self.assertEqual(result['kind'],'needs_clarification');self.assertEqual(unused.inputs,[])
                    after=Session(catalog,case.context).data
                    self.assertFalse(after['native_execution']['execution_time_uncertain'])
                    records=after['native_execution']['recovery_attempts']
                    self.assertEqual([r['status'] for r in records],['reconciled','completed'])
                    self.assertEqual(records[0]['reconciliation']['observation_ref'],observation_ref)
                    self.assertEqual(records[0]['charged_seconds'],recovery_observation['exited_monotonic']-attempts[0]['execution_clock']['started_monotonic'])
                    clock=after['native_execution']['execution_clock']
                    original_upper=clock['initial_wall_seconds']+original_observation['exited_monotonic']-clock['started_monotonic']
                    self.assertAlmostEqual(after['wall_seconds'],original_upper+sum(r['charged_seconds'] for r in records),places=6)
                    if before.data['native_execution'].get('outcome_object'):
                        self.assertEqual(result,before.data['native_execution']['outcome'])
                        self.assertEqual(after['native_execution']['outcome_object'],before.data['native_execution']['outcome_object'])
                    replay=asyncio.run(run_offline(service,case.context,profile,model=unused,
                        limits=F['runtime_limits'](),recover=True))
                    self.assertEqual(replay,result)
                    self.assertEqual(Session(catalog,case.context).data['wall_seconds'],after['wall_seconds'])

    def test_slow_recovery_before_late_observation_keeps_both_execution_intervals(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
        with (case.root/'slow-recovery-worker.log').open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                str(case.root),case.context,str(ROOT/'config/data_platform'),'clarification_object_written'],
                cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=30)
        if observed['returncode']!=79:
            with Catalog.open(case.root) as catalog:failed=Session(catalog,case.context).data
            self.fail(json.dumps(dict(observation=observed,session=failed,
                log=(case.root/'slow-recovery-worker.log').read_text()),ensure_ascii=False))
        with Catalog.open(case.root) as catalog:
            original=Session(catalog,case.context).data
            clock=original['native_execution']['execution_clock']
            upper=clock['initial_wall_seconds']+observed['exited_monotonic']-clock['started_monotonic']
            service=DataService(catalog);unused=F['ScriptedModel']()
            clarify=service.clarify
            delay=upper+.25
            def slow_clarify(*args,**kwargs):
                result=clarify(*args,**kwargs)
                time.sleep(delay)
                return result
            with patch.object(service,'clarify',side_effect=slow_clarify):
                first=asyncio.run(run_offline(service,case.context,profile,model=unused,
                    limits=F['runtime_limits'](),recover=True))
            self.assertEqual(first['kind'],'needs_clarification')
            self.assertTrue(first['runtime']['execution_time_uncertain'])
            before=deepcopy(Session(catalog,case.context).data)
            self.assertGreaterEqual(before['wall_seconds'],original['wall_seconds']+delay)
            worker.record(catalog,case.context)
            second=asyncio.run(run_offline(service,case.context,profile,model=unused,
                limits=F['runtime_limits'](),recover=True))
            after=Session(catalog,case.context).data
            self.assertEqual(first,second)
            self.assertEqual(unused.inputs,[])
            self.assertFalse(after['native_execution']['execution_time_uncertain'])
            self.assertGreaterEqual(after['wall_seconds'],before['wall_seconds'])
            self.assertGreaterEqual(after['wall_seconds'],upper+delay)
            self.assertEqual(after['native_execution']['outcome_object'],before['native_execution']['outcome_object'])
            question=first['clarification']['clarification']
            request=deepcopy(case.request)|dict(revises_context_ref=case.context,
                clarification_response=dict(clarification_id=question['clarification_id'],answer='Same scope.'))
            child=service.create_context(request,request_key='slow-recovery-answer')
            self.assertEqual(Session(catalog,child['context_ref']).data['wall_seconds'],after['wall_seconds'])


if __name__=='__main__':unittest.main()
