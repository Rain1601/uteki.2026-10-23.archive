"""Observed real exits followed by public SDK state restore, never a scripted loop."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.execution_clock import ObservedWorker, reconcile_time
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import canonical
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.service import DataService
from uteki.infrastructure.run_budget import RunBudget

ROOT = Path(__file__).resolve().parents[3]
F = runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class OpenAIContinuationTests(unittest.TestCase):
    def profile(self):
        root=ROOT/'config/data_platform'
        return load_profile(root/'model-profiles/openai/fixture-query/query.json',config_root=root,
            kernel='openai',model_id='fixture/openai-query-v1',role='query')

    def stopped(self, phase, *, limits=None):
        case=F['case']();self.addCleanup(case.doCleanups);case.catalog.close()
        worker=self.exit_worker(case,phase,limits=limits)
        catalog=Catalog.open(case.root);self.addCleanup(catalog.close)
        worker.record(catalog,case.context)
        return case,catalog

    def exit_worker(self, case, phase, *, mode='initial', limits=None):
        with (case.root/(mode+'.out')).open('w') as out,(case.root/(mode+'.err')).open('w') as err:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                str(case.root),case.context,str(ROOT/'config/data_platform'),phase,mode,
                json.dumps(limits or F['runtime_limits']())],cwd=case.root,
                env={'PATH':'/usr/bin:/bin'},stdout=out,stderr=err)
            observation=worker.wait(timeout=40)
        self.assertEqual(observation['returncode'],79,(case.root/(mode+'.err')).read_text())
        return worker

    def ledger(self, catalog, context):
        data=Session(catalog,context).data
        return RunBudget.open_existing(catalog.root/data['native_execution']['ledger_path'],'0',
            root_run_id=data['context']['root_run_id'])

    def resume(self, case, catalog, *, limits=None):
        ledger=self.ledger(catalog,case.context)
        model=F['ScriptedModel']()
        # This is the synthetic peer's continuation, not application state.
        # A fresh model transport emits only the next not-yet-answered response.
        model.script.count=sum(r['stage']=='responded' for r in ledger.inspect_requests())
        self.clock_failure=None
        def reconcile(session, **kwargs):
            try:return reconcile_time(session, **kwargs)
            except Exception as error:
                self.clock_failure=dict(cause=repr(error.__cause__),session=deepcopy(session.data),
                    observation=json.loads(catalog.content.read_object(ObjectRef.model_validate(
                        session.data['native_execution']['exit_observation']))))
                raise
        with patch('uteki.data_platform.application.runtime.reconcile_time',side_effect=reconcile):
            result=asyncio.run(run_offline(DataService(catalog),case.context,self.profile(),model=model,
                limits=limits or F['runtime_limits'](),recover=True))
        return result,model

    def evidence(self, label, value):
        folder=os.environ.get('UTEKI_OPENAI_RESUME_EVIDENCE_DIR')
        if folder:
            path=Path(folder);path.mkdir(parents=True,exist_ok=True)
            (path/(label.replace('@','-')+'.json')).write_text(json.dumps(value,indent=2)+'\n')

    def test_nonterminal_checkpoints_continue_without_reissuing_answered_requests(self):
        for phase in ('openai_state_committed','openai_request_intent','model_prepared',
                      'model_response_committed','openai_state_committed@3','native_tool_prepared',
                      'response_committed','index_after_head','native_tool_response_committed@5',
                      'openai_state_committed@9'):
            with self.subTest(phase=phase):
                case,catalog=self.stopped(phase)
                before=deepcopy(Session(catalog,case.context).data)
                ledger=self.ledger(catalog,case.context)
                originals=ledger.inspect_requests()
                answered=sum(r['stage']=='responded' for r in originals)
                result,model=self.resume(case,catalog)
                self.evidence(phase,dict(result=result,answered_before=answered,new_model_requests=len(model.inputs),
                    total_physical_requests=ledger.summary()['requests'],clock_failure=self.clock_failure,real_model_calls=0))
                self.assertEqual(result['status'],'completed',result)
                self.assertTrue(result['native_success'])
                self.assertFalse(result['runtime']['execution_time_uncertain'])
                self.assertEqual(len(model.inputs),8-answered)
                self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':8})
                self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],8)
                self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
                after=Session(catalog,case.context).data
                self.assertEqual(after['native_execution']['native_session_id'],before['native_execution']['native_session_id'])
                self.assertEqual(len(after['native_execution']['execution_segments']),1)
                self.assertEqual(len(after['time_reconciliations']),1)
                self.assertGreaterEqual(after['wall_seconds'],after['time_reconciliations'][0]['charged_wall_seconds'])
                self.assertNotIn('exit_observation',after['native_execution'])
                for old in originals:
                    new=ledger.inspect_request(old['request_key'])
                    self.assertEqual(new['request'],old['request'])
                    if old['stage']=='responded':self.assertEqual(new,old)
                for key,old in before['operations'].items():
                    new=after['operations'][key]
                    if old['status']=='completed':self.assertEqual(new,old)
                self.evidence(phase,dict(result=result,answered_before=answered,new_model_requests=len(model.inputs),
                    total_physical_requests=ledger.summary()['requests'],native_identity_preserved=True,
                    original_operations_preserved=True,real_model_calls=0))
                # A completed run is exact replay, with no extra SDK or model work.
                again,unused=self.resume(case,catalog)
                self.assertEqual(again,result);self.assertEqual(unused.inputs,[])
                catalog.close()

    def test_two_observed_interruptions_keep_two_time_segments_and_one_root(self):
        case,catalog=self.stopped('openai_state_committed@3')
        original=deepcopy(Session(catalog,case.context).data['native_execution'])
        catalog.close()
        worker=self.exit_worker(case,'native_tool_response_committed@3',mode='resume')
        catalog=Catalog.open(case.root);self.addCleanup(catalog.close)
        worker.record(catalog,case.context)
        result,model=self.resume(case,catalog)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(model.inputs),4)
        native=Session(catalog,case.context).data['native_execution']
        self.assertEqual(native['native_session_id'],original['native_session_id'])
        self.assertEqual(len(native['execution_segments']),2)
        times=Session(catalog,case.context).data['time_reconciliations']
        self.assertEqual(len(times),2)
        self.assertGreater(times[1]['charged_wall_seconds'],times[0]['charged_wall_seconds'])
        self.assertEqual(native['execution_segments'][1]['prior_elapsed_seconds'],
                         native['execution_segments'][0]['time_reconciliation']['charged_wall_seconds'])
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],8)
        self.evidence('two-interruptions',dict(result=result,segments=native['execution_segments'],real_model_calls=0))

    def test_final_tool_can_finish_at_the_exact_physical_request_limit(self):
        limits=F['runtime_limits'](max_model_requests=8)
        case,catalog=self.stopped('openai_state_committed@9',limits=limits)
        result,model=self.resume(case,catalog,limits=limits)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(model.inputs,[])
        self.assertEqual(self.ledger(catalog,case.context).summary()['requests'],8)

    def test_unknown_response_stays_blocked_even_with_observed_exit_time(self):
        case,catalog=self.stopped('model_response_received')
        result,model=self.resume(case,catalog)
        self.assertEqual(result['kind'],'recovery_required')
        self.assertEqual(model.inputs,[])
        self.assertEqual(self.ledger(catalog,case.context).inspect_root()['request_stages'],{'outcome_unknown':1})
        self.evidence('unknown-response',dict(result=result,new_model_requests=0,real_model_calls=0))

    def test_altered_saved_request_does_not_replay_or_send_a_new_request(self):
        case,catalog=self.stopped('model_response_committed')
        session=Session(catalog,case.context)
        item=session.data['native_execution']['openai_requests'][0]
        value=json.loads(catalog.content.read_object(ObjectRef.model_validate(item['request_ref'])))
        value['system_instructions']+=' synthetic conflicting prompt'
        item['request_ref']=catalog.content.put_object(canonical(value)).model_dump(mode='json')
        session.save()
        result,model=self.resume(case,catalog)
        self.assertEqual(result['kind'],'recovery_required')
        self.assertEqual(model.inputs,[])
        self.assertEqual(self.ledger(catalog,case.context).summary()['requests'],1)

    def test_wrong_sdk_version_or_missing_checkpoint_object_cannot_continue(self):
        for kind in ('sdk_version','missing'):
            with self.subTest(kind=kind):
                case,catalog=self.stopped('openai_state_committed@3')
                session=Session(catalog,case.context)
                native=session.data['native_execution']
                if kind=='sdk_version':
                    value=json.loads(catalog.content.read_object(ObjectRef.model_validate(native['openai_checkpoint'])))
                    value['sdk_version']='different'
                    native['openai_checkpoint']=catalog.content.put_object(canonical(value)).model_dump(mode='json')
                else:
                    native['openai_checkpoint']=dict(native['openai_checkpoint'],sha256='0'*64)
                session.save()
                result,model=self.resume(case,catalog)
                self.assertEqual(result['kind'],'recovery_required')
                self.assertEqual(model.inputs,[])
                self.assertEqual(self.ledger(catalog,case.context).summary()['requests'],2)
                catalog.close()
