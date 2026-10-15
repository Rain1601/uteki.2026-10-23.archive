"""Persisted root cancellation survives a process exit before native cleanup."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
R=runpy.run_path(str(Path(__file__).with_name('test_openai_continuation.py')))
N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))


class RootStopRecoveryTests(unittest.TestCase):
    def test_cancelled_root_cannot_execute_saved_model_tool_after_process_exit(self):
        helper=R['OpenAIContinuationTests']();self.addCleanup(helper.doCleanups)
        case,catalog=helper.stopped('model_response_committed')
        before=deepcopy(Session(catalog,case.context).data)
        ledger=helper.ledger(catalog,case.context)
        ledger.stop_root('cancelled')
        model=F['ScriptedModel']()
        result=asyncio.run(run_offline(DataService(catalog),case.context,helper.profile(),
            model=model,limits=F['runtime_limits'](),recover=True))
        after=Session(catalog,case.context).data
        evidence=dict(result=result,before=before,after=after,ledger=ledger.inspect_root(),
            new_model_requests=len(model.inputs),real_model_calls=0)
        folder=os.environ.get('UTEKI_ROOT_STOP_EVIDENCE_DIR')
        if folder:
            path=Path(folder);path.mkdir(parents=True,exist_ok=True)
            (path/'openai-after-response.json').write_text(json.dumps(evidence,indent=2)+'\n')
        self.assertEqual(model.inputs,[])
        self.assertEqual(result['status'],'cancelled',result['error'])
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'cancelled')
        business={k:v for k,v in after['operations'].items() if v['tool']!='deliver'}
        self.assertEqual(business,before['operations'],'saved model output must not start new business work')
        self.assertEqual(after['turns'],before['turns'])
        self.assertEqual(ledger.summary()['requests'],1)
        self.assertEqual(ledger.inspect_root()['stop_reason'],'cancelled')

    def test_claude_recovery_retains_persisted_root_stop_without_reentering_native_session(self):
        report=N['run_scenario']('success',options=dict(stop_phase='native_tool_response_committed@1',
            observe_exit=True,recover_after_exit=True,stop_root_before_recovery='cancelled'))
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'])
        self.assertEqual(report['result']['status'],'cancelled',report['result']['error'])
        self.assertEqual(report['result']['delivery']['delivery']['stop_reason'],'cancelled')
        self.assertEqual(len(report['requests']),1)
        self.assertEqual(report['ledger']['stop_reason'],'cancelled')
        business={k:v for k,v in report['operations'].items() if v['tool']!='deliver'}
        self.assertEqual(business,report['before_recovery']['operations'])
        self.assertEqual(report['journal']['tool_calls'],report['before_recovery']['native_execution']['tool_calls'])

    def test_already_committed_delivery_is_not_revoked_by_later_root_stop(self):
        helper=R['OpenAIContinuationTests']();self.addCleanup(helper.doCleanups)
        case,catalog=helper.stopped('native_outcome_committed')
        service=DataService(catalog);expected=service.read_run_result(case.context)
        helper.ledger(catalog,case.context).stop_root('cancelled')
        model=F['ScriptedModel']()
        result=asyncio.run(run_offline(service,case.context,helper.profile(),
            model=model,limits=F['runtime_limits'](),recover=True))
        self.assertEqual(result,expected)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(model.inputs,[])

    def test_persisted_cancel_without_exit_observation_keeps_recovery_required(self):
        helper=R['OpenAIContinuationTests']();self.addCleanup(helper.doCleanups)
        case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
        helper.exit_worker(case,'model_response_committed')
        with Catalog.open(case.root) as catalog:
            before=deepcopy(Session(catalog,case.context).data)
            helper.ledger(catalog,case.context).stop_root('cancelled')
            model=F['ScriptedModel']()
            result=asyncio.run(run_offline(DataService(catalog),case.context,helper.profile(),
                model=model,limits=F['runtime_limits'](),recover=True))
            self.assertEqual(result['kind'],'recovery_required',result)
            self.assertTrue(result['runtime']['execution_time_uncertain'])
            self.assertEqual(Session(catalog,case.context).data['operations'],before['operations'])
            self.assertEqual(model.inputs,[])


if __name__=='__main__':unittest.main()
