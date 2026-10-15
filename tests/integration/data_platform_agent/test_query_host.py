"""Real SDKs retain their request and process boundaries behind DataService."""
import asyncio
from functools import partial
import json
import os
from pathlib import Path
import runpy
import sys
import time
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))


class QueryHostTests(unittest.TestCase):
    def test_supervisor_timeout_preserves_unknown_request_and_forces_partial_in_both_hosts(self):
        report=N['run_scenario']('success',options=dict(service_entry=True,observe_exit=True,
            supervisor_at_phase='model_dispatched',recover_after_exit=True))
        self.assertTrue(report['exit_observation']['timed_out'])
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-2000:])
        self.assertEqual(report['result']['status'],'partial',report['result']['error'])
        self.assertEqual(report['ledger']['stop_reason'],'wall_time')
        self.assertEqual(report['ledger']['request_stages'],{'outcome_unknown':1})
        self.assertEqual(report['requests'],[],'fixture was blocked after dispatch registration but before HTTP transmission')
        self.assertTrue(report['result']['reconciliation_required'])

        case=F['case']();case.catalog.close()
        try:
            config=ROOT/'config/data_platform'
            profile=load_profile(config/'model-profiles/openai/fixture-query/query.json',config_root=config,
                kernel='openai',model_id='fixture/openai-query-v1',role='query')
            with (case.root/'host-timeout.log').open('w') as log:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                    str(case.root),case.context,str(config),'model_dispatched','supervisor',json.dumps(F['runtime_limits']()),'service'],
                    cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                marker=case.root/'fixture-host-blocked';deadline=time.monotonic()+15
                while not marker.exists() and worker.child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
                observed=worker.wait(timeout=.05)
                self.assertTrue(marker.exists(),(case.root/'host-timeout.log').read_text())
            self.assertTrue(observed['timed_out'])
            with Catalog.open(case.root) as catalog:
                worker.record(catalog,case.context)
                model=F['ScriptedModel']()
                service=DataService(catalog,query_runtime=partial(run_offline,
                    profile=profile,model=model,limits=F['runtime_limits']()))
                result=asyncio.run(service.run_query(case.context,recover=True))
                self.assertEqual(result['status'],'partial',result['error'])
                self.assertEqual(result['runtime']['budget']['stop_reason'],'wall_time')
                self.assertEqual(result['runtime']['budget']['request_stages'],{'outcome_unknown':1})
                self.assertTrue(result['reconciliation_required'])
                self.assertEqual(model.inputs,[])
            directory=os.environ.get('UTEKI_QUERY_HOST_EVIDENCE_DIR')
            if directory:
                folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
                (folder/'supervised-timeout.json').write_text(json.dumps(dict(result=result,observation=observed,
                    new_model_requests=0,real_model_calls=0),indent=2)+'\n')
        finally:case.doCleanups()

    def test_native_claude_service_entry_delivery_and_cancellation(self):
        for options,status,count in [({'replay':True},'completed',8),
            ({'cancel_phase':'model_response_received','repeat_cancel':True},'cancelled',1)]:
            with self.subTest(status=status):
                report=N['run_scenario']('success',options=dict(options,service_entry=True))
                self.assertEqual(report['exit_code'],0,report['stderr'][-2000:])
                self.assertEqual(report['result']['status'],status,report['result']['error'])
                self.assertEqual(len(report['requests']),count)
                self.assertEqual(report['process_cleanup']['before'],[])
                if status=='completed':self.assertTrue(report['result']['fixture_replay_equal'])
                else:self.assertEqual(report['ledger']['stop_reason'],'cancelled')

    def test_native_claude_service_entry_recovers_original_terminal_after_observed_exit(self):
        report=N['run_scenario']('success',options=dict(service_entry=True,
            stop_phase='delivery_object_written',observe_exit=True,recover_after_exit=True))
        self.assertEqual(report['exit_code'],79)
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-2000:])
        self.assertEqual(report['result']['status'],'completed',report['result']['error'])
        self.assertEqual(len(report['requests']),8)
        self.assertFalse(report['result']['runtime']['execution_time_uncertain'])
        self.assertEqual(report['exit_observation']['owner_pid'],report['journal']['owner_pid'])

    def test_openai_service_entry_preserves_unknown_response_or_original_delivery_after_exit(self):
        config=ROOT/'config/data_platform'
        profile=load_profile(config/'model-profiles/openai/fixture-query/query.json',config_root=config,
            kernel='openai',model_id='fixture/openai-query-v1',role='query')
        for phase,kind,count in [('model_response_received','recovery_required',1),
                                 ('native_outcome_committed','delivery',8)]:
            with self.subTest(phase=phase):
                case=F['case']();case.catalog.close()
                try:
                    with (case.root/'query-host.log').open('w') as log:
                        worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                            str(case.root),case.context,str(config),phase,'success',json.dumps(F['runtime_limits']()),'service'],
                            cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                        observation=worker.wait(timeout=40)
                    self.assertEqual(observation['returncode'],79,(case.root/'query-host.log').read_text())
                    with Catalog.open(case.root) as catalog:
                        worker.record(catalog,case.context)
                        model=F['ScriptedModel']()
                        service=DataService(catalog,query_runtime=partial(run_offline,
                            profile=profile,model=model,limits=F['runtime_limits']()))
                        result=asyncio.run(service.run_query(case.context,recover=True))
                        self.assertEqual(result['kind'],kind,result['error'])
                        self.assertEqual(model.inputs,[])
                        self.assertEqual(sum(result['runtime']['budget']['request_stages'].values()),count)
                    directory=os.environ.get('UTEKI_QUERY_HOST_EVIDENCE_DIR')
                    if directory:
                        folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
                        (folder/(phase+'.json')).write_text(json.dumps(dict(result=result,observation=observation,
                            new_model_requests=0,real_model_calls=0),indent=2)+'\n')
                finally:case.doCleanups()


if __name__=='__main__':unittest.main()
