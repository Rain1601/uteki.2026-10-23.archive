"""Finish startup under the original identity, then enter the real SDK loop."""
import asyncio
from copy import deepcopy
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
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService
from uteki.infrastructure.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))

def profile():
    return load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
        config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')

class NativeInitializationTests(unittest.TestCase):
    def test_openai_initialization_exit_enters_original_run_once(self):
        for phase in ('native_initialization_saved','runtime_ledger_linked','root_initialization_ready'):
            with self.subTest(phase=phase):
                case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
                path=case.root/(phase+'.log')
                with path.open('w') as log:
                    worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                        str(case.root),case.context,str(ROOT/'config/data_platform'),phase],
                        cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                    observation=worker.wait(timeout=30)
                self.assertEqual(observation['returncode'],79,path.read_text())
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    try:worker.record(catalog,case.context)
                    except Exception as error:
                        self.fail(json.dumps(dict(error=str(error),observation=observation,
                            native=before['native_execution']),ensure_ascii=False))
                    model=F['ScriptedModel']()
                    result=asyncio.run(run_offline(DataService(catalog),case.context,profile(),model=model,
                        limits=F['runtime_limits'](),recover=True))
                    self.assertEqual(result['status'],'completed',result)
                    after=Session(catalog,case.context).data
                    self.assertEqual(after['native_execution']['native_session_id'],before['native_execution']['native_session_id'])
                    ledger=RunBudget.open_existing(case.root/after['native_execution']['ledger_path'],'0',
                        root_run_id=before['context']['root_run_id'])
                    self.assertEqual(ledger.summary()['requests'],8)
                    self.assertEqual(len(model.inputs),8)
                    folder=os.environ.get('UTEKI_INITIALIZATION_EVIDENCE_DIR')
                    if folder:
                        target=Path(folder);target.mkdir(parents=True,exist_ok=True)
                        (target/(phase+'.json')).write_text(json.dumps(dict(before=before,after=after,
                            result=result,observation=observation,requests=ledger.inspect_requests(),
                            real_model_calls=0),ensure_ascii=False,indent=2)+'\n')

    def test_claude_initialization_exit_starts_original_native_session_once(self):
        for phase in ('native_initialization_saved','runtime_ledger_linked','root_initialization_ready'):
            with self.subTest(phase=phase):
                evidence=N['run_scenario']('success',options=dict(stop_phase=phase,observe_exit=True,recover_after_exit=True))
                self.assertEqual(evidence['exit_code'],79,evidence)
                self.assertEqual(evidence['recovery']['exit_code'],0,evidence['recovery'])
                self.assertEqual(evidence['result']['status'],'completed',evidence['result'])
                self.assertEqual(len(evidence['requests']),8)
                self.assertEqual(evidence['journal']['native_session_id'],evidence['before_recovery']['native_execution']['native_session_id'])

    def test_initialization_time_exhaustion_stops_before_first_model_request(self):
        case=F['case']();self.addCleanup(case.doCleanups)
        request=deepcopy(case.request);request['run_policy']['max_wall_seconds']=1
        context=case.service.create_context(request,request_key='slow-start')['context_ref']
        def checkpoint(phase):
            if phase=='root_initialization_ready':time.sleep(1.05)
        model=F['ScriptedModel']()
        result=asyncio.run(run_offline(case.service,context,profile(),model=model,
            limits=F['runtime_limits'](),checkpoint=checkpoint))
        self.assertEqual(result['status'],'partial',result)
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'wall_time')
        self.assertEqual(model.inputs,[])
        data=Session(case.catalog,context).data
        ledger=RunBudget.open_existing(case.root/data['native_execution']['ledger_path'],'0',
            root_run_id=data['context']['root_run_id'])
        self.assertEqual(ledger.summary()['requests'],0)
        self.assertEqual(ledger.inspect_root()['stop_reason'],'wall_time')

    def test_recovered_initialization_keeps_root_cancellation_before_first_request(self):
        case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
        path=case.root/'cancelled-start.log'
        with path.open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                str(case.root),case.context,str(ROOT/'config/data_platform'),'root_initialization_ready'],
                cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=30)
        self.assertEqual(observed['returncode'],79,path.read_text())
        with Catalog.open(case.root) as catalog:
            before=Session(catalog,case.context).data
            ledger=RunBudget.open_existing(case.root/before['native_execution']['ledger_path'],'0',
                root_run_id=before['context']['root_run_id'])
            ledger.stop_root('cancelled');worker.record(catalog,case.context)
            model=F['ScriptedModel']()
            result=asyncio.run(run_offline(DataService(catalog),case.context,profile(),model=model,
                limits=F['runtime_limits'](),recover=True))
            self.assertEqual(result['status'],'cancelled',result)
            self.assertEqual(result['delivery']['delivery']['stop_reason'],'cancelled')
            self.assertEqual(model.inputs,[])
            self.assertEqual(ledger.summary()['requests'],0)
            self.assertEqual(ledger.inspect_root()['stop_reason'],'cancelled')

if __name__=='__main__':unittest.main()
