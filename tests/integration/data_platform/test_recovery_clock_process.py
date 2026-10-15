"""Independent observations are required for the original and recovery workers."""
import json
from pathlib import Path
import runpy
import sys
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError,canonical
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)


class RecoveryClockProcessTests(unittest.TestCase):
    def test_terminal_intent_and_result_keep_bytes_but_account_observed_worker_tail(self):
        for phase in ('native_outcome_prepared','native_outcome_committed','runtime_completion_clock_recorded'):
            with self.subTest(phase=phase):
                case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
                case.setUp();self.addCleanup(case.doCleanups);case.catalog.close()
                with (case.root/'terminal-tail.log').open('w') as log:
                    worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/recovery_clock_worker.py'),
                        str(case.root),case.context,'terminal',phase],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                    observed=worker.wait(timeout=20)
                self.assertEqual(observed['returncode'],79,(case.root/'terminal-tail.log').read_text())
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    reference=before['native_execution']['outcome_intent']['object_ref']
                    expected=json.loads(catalog.content.read_object(ObjectRef.model_validate(reference)))
                    worker.record(catalog,case.context)
                    recovered=RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
                    self.assertEqual(recovered.cached,expected)
                    after=Session(catalog,case.context).data
                    self.assertEqual(after['native_execution']['outcome_object'],reference)
                    self.assertIn('time_reconciliation',after['native_execution'])
                    clock=after['native_execution']['execution_clock']
                    upper=clock['initial_wall_seconds']+observed['exited_monotonic']-clock['started_monotonic']
                    self.assertGreaterEqual(after['wall_seconds'],upper)
                    self.assertGreater(after['wall_seconds'],before['wall_seconds']+.2)
                    self.assertEqual(after['native_execution']['time_reconciliation']['charged_wall_seconds'],upper)
                    expected_status='recorded' if phase=='runtime_completion_clock_recorded' else 'observed'
                    self.assertEqual(after['native_execution']['completion_clock']['status'],expected_status)
                    self.assertEqual(recovered.budget.summary()['requests'],0)

    def test_exit_before_result_preparation_does_not_invent_the_original_failure(self):
        case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        case.setUp();self.addCleanup(case.doCleanups);case.catalog.close()
        with (case.root/'pending-tail.log').open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/recovery_clock_worker.py'),
                str(case.root),case.context,'terminal','runtime_completion_clock_pending'],
                cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=20)
        self.assertEqual(observed['returncode'],79,(case.root/'pending-tail.log').read_text())
        with Catalog.open(case.root) as catalog:
            before=Session(catalog,case.context).data
            self.assertNotIn('outcome_intent',before['native_execution'])
            worker.record(catalog,case.context)
            service=DataService(catalog)
            recovered=RuntimeJournal(service,case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertEqual(recovered.cached['kind'],'recovery_required')
            self.assertNotEqual(recovered.cached['error'],'original failure')
            self.assertEqual(recovered.budget.summary()['requests'],0)
            self.assertEqual(Session(catalog,case.context).data['native_execution']['completion_clock']['status'],'observed')
            closed=service.close_run(case.context,request_key='close-pending-tail',reason='Original error was not persisted.')
            self.assertEqual(closed['kind'],'failed')

    def fixture(self, *, timeout=False):
        case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        case.setUp();self.addCleanup(case.doCleanups);case.catalog.close()
        workers=[]
        for name,argument in [('runtime_clock_worker.py','.03'),
                              ('recovery_clock_worker.py','timeout' if timeout else 'exit')]:
            with (case.root/(name+'.log')).open('w') as log:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform'/name),
                    str(case.root),case.context,argument],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                observed=worker.wait(timeout=2.5 if argument=='timeout' else 20)
            self.assertEqual(observed['timed_out'],argument=='timeout')
            if argument!='timeout':self.assertEqual(observed['returncode'],79,(case.root/(name+'.log')).read_text())
            workers.append(worker)
        return case,workers

    def test_supervisor_timeout_of_recovery_stops_original_root_without_model_call(self):
        case,workers=self.fixture(timeout=True)
        with Catalog.open(case.root) as catalog:
            for worker in workers:worker.record(catalog,case.context)
            journal=RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertEqual(journal.cached['kind'],'delivery',journal.cached)
            self.assertEqual(journal.cached['status'],'partial')
            self.assertEqual(journal.cached['delivery']['delivery']['stop_reason'],'wall_time')
            self.assertEqual(journal.budget.inspect_root()['stop_reason'],'wall_time')
            self.assertEqual(journal.budget.summary()['requests'],0)

    def test_wrong_recovery_observation_does_not_change_time_or_head(self):
        case,workers=self.fixture()
        with Catalog.open(case.root) as catalog:
            workers[0].record(catalog,case.context)
            reference=workers[1].record(catalog,case.context)
            receipt=json.loads(catalog.content.read_object(ObjectRef.model_validate(reference)))
            receipt['recovery_attempt_id']='unrelated-attempt'
            bad=catalog.content.put_object(canonical(receipt)).model_dump(mode='json')
            session=Session(catalog,case.context)
            session.data['native_execution']['recovery_attempts'][0]['exit_observation']=bad
            session.save()
            with self.assertRaises(CatalogError) as caught:
                RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertIn('recovery host observation',str(caught.exception))
            self.assertEqual(Session(catalog,case.context).head_ref,session.head_ref)
            self.assertEqual(Session(catalog,case.context).data['wall_seconds'],session.data['wall_seconds'])


if __name__=='__main__':unittest.main()
