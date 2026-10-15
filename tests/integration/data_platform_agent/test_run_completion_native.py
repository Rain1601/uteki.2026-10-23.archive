"""Both real SDKs preserve original failure results and allow observed host closure."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))


class NativeRunCompletionTests(unittest.TestCase):
    def evidence(self,name,value):
        folder=os.environ.get('UTEKI_RUN_COMPLETION_EVIDENCE_DIR')
        if folder:
            target=Path(folder);target.mkdir(parents=True,exist_ok=True)
            (target/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')

    def test_openai_native_failure_commit_recovers_without_new_model_request(self):
        config=ROOT/'config/data_platform'
        profile=load_profile(config/'model-profiles/openai/fixture-query/query.json',config_root=config,
            kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ('native_outcome_prepared','runtime_session_terminal','runtime_catalog_terminal',
                      'native_outcome_committed','runtime_completion_clock_recorded'):
            with self.subTest(phase=phase):
                case=F['case']();case.catalog.close()
                try:
                    with (case.root/'sdk.log').open('w') as log:
                        worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                            str(case.root),case.context,str(config),phase,'failure'],cwd=case.root,
                            env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                        observed=worker.wait(timeout=30)
                    self.assertEqual(observed['returncode'],79,(case.root/'sdk.log').read_text())
                    with Catalog.open(case.root) as catalog:
                        worker.record(catalog,case.context)
                        original=Session(catalog,case.context).data['native_execution']['outcome_intent']
                        model=F['ScriptedModel']()
                        result=asyncio.run(run_offline(DataService(catalog),case.context,profile,model=model,
                            limits=F['runtime_limits'](),recover=True))
                        self.assertEqual(model.inputs,[])
                        self.assertEqual(result['kind'],'failed');self.assertEqual(result['error'],'NO_VALIDATED_DELIVERY')
                        self.assertEqual(result['runtime']['budget']['request_stages'],{'responded':1})
                        self.assertEqual(Session(catalog,case.context).data['native_execution']['outcome_object'],original['object_ref'])
                        self.assertEqual(catalog._get('runs','run_id',result['runtime']['run_id'])['status'],'failed')
                    self.evidence('openai-'+phase,dict(result=result,observation=observed,new_model_requests=0,real_model_calls=0))
                finally:case.doCleanups()

    def test_openai_unknown_or_pending_native_tool_closes_without_restarting_runner(self):
        config=ROOT/'config/data_platform'
        profile=load_profile(config/'model-profiles/openai/fixture-query/query.json',config_root=config,
            kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase in ('model_response_received','native_tool_prepared'):
            with self.subTest(phase=phase):
                case=F['case']();case.catalog.close()
                try:
                    with (case.root/'sdk.log').open('w') as log:
                        worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                            str(case.root),case.context,str(config),phase],cwd=case.root,
                            env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                        observed=worker.wait(timeout=30)
                    self.assertEqual(observed['returncode'],79,(case.root/'sdk.log').read_text())
                    with Catalog.open(case.root) as catalog:
                        worker.record(catalog,case.context)
                        before=Session(catalog,case.context).data
                        service=DataService(catalog)
                        result=service.close_run(case.context,request_key='close-original',reason='abandon interrupted run')
                        self.assertEqual(result['error'],'RUN_CLOSED')
                        self.assertEqual(result['reconciliation_required'],phase=='model_response_received')
                        model=F['ScriptedModel']()
                        replay=asyncio.run(run_offline(service,case.context,profile,model=model,limits=F['runtime_limits'](),recover=True))
                        self.assertEqual(replay,result);self.assertEqual(model.inputs,[])
                        self.assertEqual(Session(catalog,case.context).data['native_execution']['tool_calls'],before['native_execution']['tool_calls'])
                        self.assertEqual(result['runtime']['budget']['request_stages'],
                            {'outcome_unknown':1} if phase=='model_response_received' else {'responded':1})
                    self.evidence('openai-close-'+phase,dict(result=result,observation=observed,new_model_requests=0,real_model_calls=0))
                finally:case.doCleanups()

    def test_claude_failure_commit_preserves_result_and_does_not_restart_cli_requests(self):
        for phase in ('native_outcome_prepared','runtime_session_terminal','runtime_catalog_terminal',
                      'native_outcome_committed','runtime_completion_clock_recorded'):
            with self.subTest(phase=phase):
                report=N['run_scenario']('free_text',options=dict(stop_phase=phase,observe_exit=True,recover_after_exit=True))
                self.evidence('claude-'+phase,report)
                self.assertEqual(report['exit_code'],79,report['stderr'])
                self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'])
                self.assertEqual(len(report['requests']),1)
                self.assertEqual(report['result']['kind'],'failed')
                self.assertEqual(report['result']['error'],'NO_VALIDATED_DELIVERY')
                self.assertEqual(report['journal']['outcome_object'],report['before_recovery']['native_execution']['outcome_intent']['object_ref'])

    def test_claude_missing_native_history_and_unknown_response_can_close_without_new_requests(self):
        for name,options in [('missing',dict(stop_phase='claude_post_tool@1',history_fault='missing',recover_after_exit=True)),
                             ('unknown',dict(stop_phase='model_response_received'))]:
            with self.subTest(name=name):
                report=N['run_scenario']('success',options=options|dict(observe_exit=True,host_close_run=True))
                self.evidence('claude-close-'+name,report)
                self.assertEqual(report['exit_code'],79,report['stderr'])
                self.assertEqual(len(report['requests']),1)
                result=report['closed_run']
                self.assertEqual(result['kind'],'failed');self.assertEqual(result['error'],'RUN_CLOSED')
                self.assertTrue(result['terminal']);self.assertFalse(result['native_success'])
                self.assertEqual(result['reconciliation_required'],name=='unknown')
                self.assertEqual(report['ledger']['stop_reason'],'run_closed')
                self.assertEqual(report['process_cleanup']['after'],[])


if __name__=='__main__':unittest.main()
