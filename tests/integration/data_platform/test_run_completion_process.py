"""Real process exits around terminal commits and explicit abandoned-run closure."""
import json
from pathlib import Path
import runpy
import sys
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
WORKER=ROOT/'tests/fixtures/data_platform/run_completion_worker.py'
PROFILE=dict(kernel='completion_fixture')
LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)


class RunCompletionProcessTests(unittest.TestCase):
    def fixture(self):
        case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        case.setUp();self.addCleanup(case.doCleanups)
        (case.root/'completion-fixture.json').write_text(json.dumps(dict(context=case.context,profile=PROFILE,
            limits=LIMITS,state=case.state('find_assets'))))
        case.catalog.close()
        return case

    def run_worker(self, case, mode, phase='none', *, expected=0, observe=True):
        with (case.root/'completion-worker.log').open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(WORKER),str(case.root),mode,phase],
                cwd=str(case.root),env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            result=worker.wait(timeout=30)
        self.assertEqual(result['returncode'],expected,(case.root/'completion-worker.log').read_text())
        if observe:
            with Catalog.open(case.root) as catalog:
                if Session(catalog,case.context).data['native_execution']['owner_pid']==worker.child.pid:
                    worker.record(catalog,case.context)
        return json.loads((case.root/'completion-result.json').read_text()) if expected==0 else None

    def test_terminal_commit_recovers_identical_intent_at_four_real_exit_positions(self):
        for phase in ('native_outcome_prepared','runtime_session_terminal','runtime_catalog_terminal','native_outcome_committed'):
            with self.subTest(phase=phase):
                case=self.fixture();self.run_worker(case,'start',phase,expected=74)
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    reference=before['native_execution']['outcome_intent']['object_ref']
                report=self.run_worker(case,'recover')
                self.assertIn('result',report,report)
                result=report['result']
                self.assertEqual(result['kind'],'failed');self.assertEqual(result['error'],'original synthetic failure')
                with Catalog.open(case.root) as catalog:
                    data=Session(catalog,case.context).data
                    self.assertEqual(data['native_execution']['outcome_object'],reference)
                    self.assertEqual(data['status'],'failed')
                    self.assertEqual(catalog._get('runs','run_id',data['context']['run_id'])['status'],'failed')
                    self.assertEqual(DataService(catalog).read_run_result(case.context),result)
                self.assertEqual(self.run_worker(case,'recover')['result'],result)

    def test_abandoned_native_execution_closes_without_response_or_history_fabrication(self):
        for phase,stages in [('model_prepared',{'abandoned':1}),('model_dispatched',{'outcome_unknown':1}),
                             ('native_tool_prepared',{}),('readonly_accepted',{})]:
            with self.subTest(phase=phase):
                case=self.fixture();self.run_worker(case,'start',phase,expected=74)
                with Catalog.open(case.root) as catalog:before=Session(catalog,case.context).data
                result=self.run_worker(case,'close')['result']
                self.assertTrue(result['terminal']);self.assertEqual(result['error'],'RUN_CLOSED')
                self.assertEqual(result['reconciliation_required'],phase=='model_dispatched')
                self.assertEqual(result['runtime']['budget']['request_stages'],stages)
                self.assertEqual(result['runtime']['budget']['stop_reason'],'run_closed')
                with Catalog.open(case.root) as catalog:
                    data=Session(catalog,case.context).data
                    self.assertEqual(data['native_execution']['tool_calls'],before['native_execution']['tool_calls'])
                    self.assertEqual(data['turns'],before['turns'])
                    for op in data['operations'].values():
                        self.assertEqual(op['status'],'closed');self.assertIsNone(op['response'])
                        recovered=DataService(catalog).call(case.context,op['tool'],op['request'],state=op['state'],
                            request_key=op['request_key'],recover=True)
                        self.assertEqual(recovered['error']['code'],'INVALID_STATE')
                    saved=RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
                    self.assertEqual(saved.cached,result)
                    self.assertEqual(saved.budget.inspect_root()['request_stages'],stages)
                self.assertEqual(self.run_worker(case,'close')['result'],result)

    def test_close_interrupted_again_confirms_original_identity_and_unknown_request(self):
        for phase in ('run_close_prepared','run_close_root_stopped','run_close_operations_closed',
                      'native_outcome_prepared','runtime_session_terminal','runtime_catalog_terminal'):
            with self.subTest(phase=phase):
                case=self.fixture();self.run_worker(case,'start','model_dispatched',expected=74)
                self.run_worker(case,'close',phase,expected=74)
                with Catalog.open(case.root) as catalog:
                    old=Session(catalog,case.context).data
                    intent=old['native_execution']['close_intent']
                    with self.assertRaises(CatalogError):RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
                result=self.run_worker(case,'close')['result']
                self.assertEqual(result['runtime']['close_intent'],intent)
                self.assertEqual(result['runtime']['budget']['request_stages'],{'outcome_unknown':1})
                self.assertTrue(result['reconciliation_required'])
                with Catalog.open(case.root) as catalog:
                    self.assertGreaterEqual(Session(catalog,case.context).data['wall_seconds'],old['wall_seconds'])
                    with self.assertRaises(CatalogError) as caught:
                        DataService(catalog).close_run(case.context,request_key='different',reason=intent['reason'])
                    self.assertEqual(caught.exception.code,'IDEMPOTENCY_CONFLICT')

    def test_missing_exit_observation_cannot_be_replaced_by_catalog_ownership(self):
        case=self.fixture();self.run_worker(case,'start','model_dispatched',expected=74,observe=False)
        report=self.run_worker(case,'close')
        self.assertEqual(report['error']['code'],'RECOVERY_REQUIRED')
        with Catalog.open(case.root) as catalog:
            data=Session(catalog,case.context).data
            self.assertNotIn('close_intent',data['native_execution'])
            ledger=RunBudget.open_existing(case.root/data['native_execution']['ledger_path'],'0',root_run_id=data['context']['root_run_id'])
            self.assertEqual(ledger.inspect_root()['request_stages'],{'dispatched':1})

    def test_existing_response_must_be_confirmed_before_closing_no_response_is_discarded(self):
        case=self.fixture();self.run_worker(case,'start','tool_response_prepared',expected=74)
        report=self.run_worker(case,'close')
        self.assertEqual(report['error']['code'],'RECOVERY_REQUIRED')
        with Catalog.open(case.root) as catalog:
            service=DataService(catalog);before=Session(catalog,case.context).data
            original=next(iter(before['operations'].values()))
            self.assertNotIn('close_intent',before['native_execution'])
            result=service.call(case.context,original['tool'],original['request'],state=original['state'],
                request_key=original['request_key'],recover=True)
            self.assertEqual(result,original['response_intent']['response'])
            closed=service.close_run(case.context,request_key='host-close',reason='original native history unavailable')
            self.assertEqual(closed['error'],'RUN_CLOSED')
            self.assertEqual(next(iter(Session(catalog,case.context).data['operations'].values()))['response'],result)

    def test_acquisition_must_be_resolved_first_and_transport_uncertainty_survives_run_closure(self):
        cls=runpy.run_path(str(Path(__file__).with_name('test_acquisition_resolution_process.py')))['AcquisitionResolutionProcessTests']
        helper=cls();self.addCleanup(helper.doCleanups)
        case=helper.fixture('transport_inflight')
        with Catalog.open(case.root) as catalog:
            before=Session(catalog,case.context)
            with self.assertRaises(CatalogError) as caught:
                DataService(catalog).close_run(case.context,request_key='host-close',reason='unknown transport')
            self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
            self.assertEqual(Session(catalog,case.context).head_ref,before.head_ref)
        resolved=helper.run_worker(case,'close')['result']
        self.assertTrue(resolved['error']['details']['transport_outcome_unknown'])
        with Catalog.open(case.root) as catalog:
            closed=DataService(catalog).close_run(case.context,request_key='host-close',reason='unknown transport')
            self.assertEqual(closed['error'],'RUN_CLOSED')
            self.assertTrue(closed['reconciliation_required'])
            self.assertEqual(closed['runtime']['budget']['request_stages'],{})
            self.assertEqual(closed['runtime']['unknown_transports'],[dict(operation_id=resolved['operation_id'],
                retained_ref=resolved['error']['details']['retained_ref'])])


if __name__=='__main__':unittest.main()
