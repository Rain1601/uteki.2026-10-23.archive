"""Real Runner process exits preserve request and operation identities."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.session import Session
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService
from uteki.infrastructure.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class RuntimeProcessTests(unittest.TestCase):
    def test_late_exit_observation_keeps_frozen_question_and_allows_same_root_child(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        case=F['case']();case.catalog.close()
        try:
            with (case.root/'late-observation.log').open('w') as log:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                    str(case.root),case.context,str(ROOT/'config/data_platform'),'clarification_object_written'],
                    cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                observed=worker.wait(timeout=30)
            self.assertEqual(observed['returncode'],79,(case.root/'late-observation.log').read_text())
            with Catalog.open(case.root) as catalog:
                service=DataService(catalog)
                unused=F['ScriptedModel']()
                first=asyncio.run(run_offline(service,case.context,profile,model=unused,limits=F['runtime_limits'](),recover=True))
                self.assertEqual(first['kind'],'needs_clarification')
                self.assertTrue(first['runtime']['execution_time_uncertain'])
                frozen=Session(catalog,case.context).data['native_execution']['outcome_object']
                request=deepcopy(case.request)|dict(revises_context_ref=case.context,
                    clarification_response=dict(clarification_id=first['clarification']['clarification']['clarification_id'],answer='Same scope.'))
                with self.assertRaises(CatalogError):service.create_context(request,request_key='late-observation-answer')
                worker.record(catalog,case.context)
                second=asyncio.run(run_offline(service,case.context,profile,model=unused,limits=F['runtime_limits'](),recover=True))
                self.assertEqual(first,second);self.assertEqual(unused.inputs,[])
                data=Session(catalog,case.context).data
                self.assertEqual(data['native_execution']['outcome_object'],frozen)
                self.assertFalse(data['native_execution']['execution_time_uncertain'])
                self.assertEqual(len(data['time_reconciliations']),1)
                child=service.create_context(request,request_key='late-observation-answer')
                model=F['ScriptedModel']('after_clarification')
                delivered=asyncio.run(run_offline(service,child['context_ref'],profile,model=model,limits=F['runtime_limits']()))
                self.assertEqual(delivered['status'],'completed')
                self.assertEqual(delivered['delivery']['delivery']['usage']['model_calls'],9)
                self.assertEqual(delivered['runtime']['root_run_id'],first['runtime']['root_run_id'])
        finally:case.doCleanups()

    def test_observed_clarification_exit_allows_child_without_resetting_root_budget(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        case=F['case']();case.catalog.close()
        try:
            with (case.root/'observed.stdout').open('w') as stdout,(case.root/'observed.stderr').open('w') as stderr:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                    str(case.root),case.context,str(ROOT/'config/data_platform'),'clarification_object_written'],
                    cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=stdout,stderr=stderr)
                observation=worker.wait(timeout=40)
            self.assertEqual(observation['returncode'],79,(case.root/'observed.stderr').read_text())
            with Catalog.open(case.root) as catalog:
                worker.record(catalog,case.context)
                service=DataService(catalog)
                saved=Session(catalog,case.context)
                package=next(o['terminal_intent']['package'] for o in saved.data['operations'].values() if o['tool']=='clarify')
                unused=F['ScriptedModel']()
                parent=asyncio.run(run_offline(service,case.context,profile,model=unused,limits=F['runtime_limits'](),recover=True))
                self.assertEqual(parent['clarification']['clarification'],package)
                self.assertEqual(unused.inputs,[])
                self.assertFalse(parent['runtime']['execution_time_uncertain'])
                self.assertEqual(parent['runtime']['time_reconciliation']['kind'],'supervised_upper_bound')
                request=deepcopy(case.request)|dict(revises_context_ref=case.context,
                    clarification_response=dict(clarification_id=package['clarification_id'],answer='Use the same scope.'))
                child=service.create_context(request,request_key='observed-answer')
                before=Session(catalog,child['context_ref'])
                self.assertEqual(before.data['wall_seconds'],Session(catalog,case.context).data['wall_seconds'])
                self.assertEqual(len(before.data['time_reconciliations']),1)
                result=asyncio.run(run_offline(service,child['context_ref'],profile,model=F['ScriptedModel']('after_clarification'),limits=F['runtime_limits']()))
                self.assertEqual(result['status'],'completed',result['error'])
                self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],9)
                self.assertEqual(result['delivery']['delivery']['usage']['time_reconciliations'],before.data['time_reconciliations'])
                self.assertEqual(service.create_context(request,request_key='observed-answer'),child)
        finally:case.doCleanups()

    def test_acquisition_publication_recovers_same_effect_without_new_requests(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ('before_build_commit','after_build_commit'):
            with self.subTest(phase=phase):
                case=F['acquisition_case']();case.catalog.close()
                try:
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                        str(case.root),case.context,str(ROOT/'config/data_platform'),phase,'acquisition'],cwd=case.root,
                        capture_output=True,text=True,timeout=40)
                    self.assertEqual(child.returncode,79,child.stderr[-3000:])
                    with Catalog.open(case.root) as catalog, F['acquisition_host'](catalog) as service:
                        before=Session(catalog,case.context)
                        expected=next(iter(before.data['operations'].values()))['effect_intent']['target']
                        model=F['ScriptedModel']()
                        result=asyncio.run(run_offline(service,case.context,profile,model=model,limits=F['runtime_limits'](),recover=True))
                        self.assertEqual(result['kind'],'recovery_required')
                        self.assertEqual(model.inputs,[])
                        after=Session(catalog,case.context)
                        operation=next(iter(after.data['operations'].values()))
                        self.assertEqual(operation['status'],'completed')
                        self.assertEqual(operation['response']['items'][0]['new_asset_refs'][0]['snapshot_id'],expected['snapshot_id'])
                        self.assertEqual(operation['response']['recovery']['kind'],'verified_existing_acquisition')
                        self.assertEqual(len(json.loads((case.root/'fixture-native-acquisition-requests.json').read_text())),2)
                        native=after.data['native_execution']
                        ledger=RunBudget.open_existing(case.root/native['ledger_path'],'0',root_run_id=after.data['context']['root_run_id'])
                        self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':1})
                        self.assertTrue(all(t['output'] is not None for t in native['tool_calls'].values()))
                finally:case.doCleanups()

    def test_clarification_exit_recovers_same_question_and_preserves_unknown_time(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ('clarification_accepted','clarification_object_written','clarification_response_committed'):
            with self.subTest(phase=phase):
                case=F['case']();case.catalog.close()
                try:
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                        str(case.root),case.context,str(ROOT/'config/data_platform'),phase],cwd=case.root,
                        capture_output=True,text=True,timeout=40)
                    self.assertEqual(child.returncode,79,child.stderr[-3000:])
                    with Catalog.open(case.root) as catalog:
                        service=DataService(catalog);session=Session(catalog,case.context)
                        expected=next(o['terminal_intent']['package'] for o in session.data['operations'].values() if o['tool']=='clarify')
                        model=F['ScriptedModel']('clarify')
                        result=asyncio.run(run_offline(service,case.context,profile,model=model,limits=F['runtime_limits'](),recover=True))
                        self.assertEqual(result['kind'],'needs_clarification')
                        self.assertEqual(result['clarification']['clarification'],expected)
                        self.assertEqual(result['runtime']['budget']['request_stages'],{'responded':1})
                        self.assertTrue(result['runtime']['execution_time_uncertain'])
                        self.assertEqual(model.inputs,[])
                        answer=dict(case.request,revises_context_ref=case.context,
                            clarification_response=dict(clarification_id=expected['clarification_id'],answer='Same scope.'))
                        with self.assertRaises(CatalogError) as caught:service.create_context(answer,request_key='answer')
                        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                finally:case.doCleanups()

    def test_model_tool_and_delivery_crashes_do_not_restart_or_forget_records(self):
        profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ['model_response_received','model_response_committed','index_after_head','tool_response_prepared',
                      'response_committed','delivery_accepted','delivery_object_written',
                      'delivery_response_committed','native_outcome_committed']:
            with self.subTest(phase=phase):
                case=F['case']();case.catalog.close()
                try:
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                        str(case.root),case.context,str(ROOT/'config/data_platform'),phase],
                        cwd=case.root,capture_output=True,text=True,timeout=40)
                    self.assertEqual(child.returncode,79,child.stderr[-3000:])
                    with Catalog.open(case.root) as catalog:
                        session=Session(catalog,case.context)
                        native=session.data['native_execution']
                        ledger=RunBudget.open_existing(case.root/native['ledger_path'],'0',
                                                      root_run_id=session.data['context']['root_run_id'])
                        count=ledger.summary()['requests']
                        unused=F['ScriptedModel']()
                        async def replay(*,recover=False):
                            return await run_offline(DataService(catalog),case.context,profile,
                                                     model=unused,limits=F['runtime_limits'](),recover=recover)
                        with self.assertRaises(CatalogError) as caught:asyncio.run(replay())
                        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                        if phase=='native_outcome_committed':
                            # The result is immutable and readable; starting an
                            # SDK is distinct from reading it while the final
                            # timing confirmation remains interrupted.
                            saved=DataService(catalog).read_run_result(case.context)
                            self.assertEqual(saved,native['outcome'])
                            self.assertEqual(saved['status'],'completed')
                            self.assertEqual(native['completion_clock']['status'],'pending')
                        self.assertEqual(unused.inputs,[])
                        self.assertEqual(ledger.summary()['requests'],count)
                        if phase=='model_response_received':
                            self.assertEqual(ledger.inspect_root()['request_stages'],{'dispatched':1})
                            ledger.recover_requests()
                            self.assertEqual(ledger.summary()['unknown_requests'],1)
                            self.assertFalse(session.data['operations'])
                        elif phase=='model_response_committed':
                            self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':1})
                            self.assertFalse(session.data['operations'])
                        elif phase=='index_after_head':
                            self.assertTrue(any(o['tool']=='request_asset_update' and o['status']=='accepted'
                                                for o in session.data['operations'].values()))
                            self.assertTrue(list((case.root/'derived').rglob('head.json')))
                        elif phase=='delivery_object_written':
                            self.assertTrue(any(o['tool']=='deliver' and o['status']=='accepted'
                                                for o in session.data['operations'].values()))
                            self.assertIsNone(session.data['delivery'])
                        if phase in {'index_after_head','tool_response_prepared','response_committed'}:
                            recovered=asyncio.run(replay(recover=True))
                            self.assertEqual(recovered['kind'],'recovery_required')
                            self.assertFalse(recovered['native_success'])
                            after=Session(catalog,case.context)
                            self.assertTrue(all(o['status']=='completed' for o in after.data['operations'].values()))
                            self.assertEqual(ledger.summary()['requests'],count)
                            self.assertEqual(unused.inputs,[])
                            self.assertTrue(all(t['output'] is not None for t in after.data['native_execution']['tool_calls'].values()))
                            if phase=='tool_response_prepared':
                                original=next(iter(session.data['operations'].values()))
                                self.assertEqual(after.data['operations'][original['operation_id']]['response'],original['response_intent']['response'])
                        if phase in {'delivery_accepted','delivery_object_written','delivery_response_committed'}:
                            intent=next(o['terminal_intent']['package'] for o in session.data['operations'].values() if o['tool']=='deliver')
                            recovered=asyncio.run(replay(recover=True))
                            self.assertEqual(recovered['delivery']['delivery'],intent)
                            self.assertFalse(recovered['native_success'])
                            self.assertEqual(recovered['native_error'],'UNCONFIRMED_AFTER_PROCESS_EXIT')
                            self.assertTrue(recovered['runtime']['execution_time_uncertain'])
                            self.assertEqual(asyncio.run(replay()),recovered)
                            self.assertEqual(unused.inputs,[])
                            self.assertEqual(ledger.summary()['requests'],count)
                finally:case.doCleanups()


if __name__=='__main__':unittest.main()
