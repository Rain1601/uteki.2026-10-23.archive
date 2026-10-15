"""A held child handle proves exit; old PIDs or caller durations cannot do so."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.application.execution_clock import ObservedWorker, reconcile_time
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)


class ExecutionClockProcessTests(unittest.TestCase):
    def worker(self, *, timeout=30, delay=.03):
        f=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        f.setUp();self.addCleanup(f.doCleanups);f.catalog.close()
        with (f.root/'clock.stdout').open('w') as stdout,(f.root/'clock.stderr').open('w') as stderr:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_clock_worker.py'),str(f.root),f.context,str(delay)],
                cwd=f.root,env={'PATH':'/usr/bin:/bin'},stdout=stdout,stderr=stderr)
            observation=worker.wait(timeout=timeout)
        if observation['timed_out']:
            self.assertLess(observation['returncode'],0)
        else:
            self.assertEqual(observation['returncode'],79,(f.root/'clock.stderr').read_text())
        self.assertEqual(worker.cleanup['after'],[])
        return f,worker,observation

    def test_supervisor_timeout_reaps_owned_group_and_forces_partial_stop(self):
        f,worker,observation=self.worker(timeout=2.5,delay=10)
        self.assertTrue(observation['timed_out'])
        with Catalog.open(f.root) as catalog:
            worker.record(catalog,f.context)
            journal=RuntimeJournal(DataService(catalog),f.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertEqual(journal.cached['kind'],'delivery',journal.cached)
            self.assertEqual(journal.cached['status'],'partial')
            self.assertEqual(journal.cached['delivery']['delivery']['stop_reason'],'wall_time')
            self.assertFalse(journal.cached['runtime']['execution_time_uncertain'])
            self.assertEqual(journal.budget.summary()['requests'],0)

    def test_exit_bound_is_idempotent_and_excludes_wait_after_exit(self):
        f,worker,observation=self.worker()
        time.sleep(.15)  # A caller waits after observed process death, not execution.
        with Catalog.open(f.root) as catalog:
            before=Session(catalog,f.context)
            reference=worker.record(catalog,f.context)
            self.assertEqual(worker.record(catalog,f.context),reference)
            journal=RuntimeJournal(DataService(catalog),f.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            result=journal.cached
            self.assertEqual(result['kind'],'recovery_required') # Native continuation remains separate.
            self.assertFalse(result['runtime']['execution_time_uncertain'])
            after=Session(catalog,f.context)
            accounting=after.data['native_execution']['time_reconciliation']
            clock=before.data['native_execution']['execution_clock']
            expected=clock['initial_wall_seconds']+observation['exited_monotonic']-clock['started_monotonic']
            self.assertEqual(accounting['charged_wall_seconds'],expected)
            self.assertGreaterEqual(expected,accounting['known_wall_seconds'])
            self.assertEqual(accounting['observation_ref'],reference)
            self.assertEqual(journal.budget.summary()['requests'],0)
            wall=after.data['wall_seconds']
            reconcile_time(after)
            self.assertEqual(after.data['wall_seconds'],wall)
            self.assertEqual(len(after.data['time_reconciliations']),1)

    def test_unobserved_exit_does_not_reset_uncertain_time(self):
        f,worker,observation=self.worker()
        with Catalog.open(f.root) as catalog:
            journal=RuntimeJournal(DataService(catalog),f.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertTrue(journal.cached['runtime']['execution_time_uncertain'])
            self.assertNotIn('time_reconciliation',journal.cached['runtime'])

    def test_other_owner_and_other_clock_domain_are_refused(self):
        f,worker,observation=self.worker()
        with Catalog.open(f.root) as catalog:
            session=Session(catalog,f.context)
            original=deepcopy(session.data['native_execution'])
            session.data['native_execution']['owner_pid']+=1;session.save()
            with self.assertRaises(CatalogError):worker.record(catalog,f.context)
            session.data['native_execution']=original;session.save()
            worker.record(catalog,f.context)
            before=Session(catalog,f.context)
            with patch('uteki.data_platform.application.execution_clock.clock_domain',return_value='other-boot'):
                with self.assertRaises(CatalogError) as caught:reconcile_time(before)
            self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
            self.assertEqual(caught.exception.diagnostic['reason'],'clock_domain_changed')
            self.assertEqual(caught.exception.diagnostic['current_clock_domain'],'other-boot')
            self.assertEqual(Session(catalog,f.context).head_ref,before.head_ref)

    def test_corrupt_observation_cannot_reduce_budget(self):
        f,worker,observation=self.worker()
        with Catalog.open(f.root) as catalog:
            reference=worker.record(catalog,f.context)
            session=Session(catalog,f.context)
            # A different immutable observation, inconsistent with its original
            # owner clock, cannot substitute a convenient elapsed value.
            from uteki.data_platform.contracts.content import ObjectRef
            receipt=json.loads(catalog.content.read_object(ObjectRef.model_validate(reference)))
            receipt['exited_monotonic']=receipt['clock']['started_monotonic']-1
            changed=catalog.content.put_object(canonical(receipt)).model_dump(mode='json')
            session.data['native_execution']['exit_observation']=changed;session.save()
            before=session.head_ref
            with self.assertRaises(CatalogError):reconcile_time(session)
            self.assertEqual(Session(catalog,f.context).head_ref,before)

    def test_rejected_upper_bound_preserves_diagnosis_and_never_resets_budget(self):
        from uteki.data_platform.contracts.content import ObjectRef
        f,worker,observation=self.worker()
        with Catalog.open(f.root) as catalog:
            reference=worker.record(catalog,f.context)
            session=Session(catalog,f.context)
            clock=session.data['native_execution']['execution_clock']
            upper=clock['initial_wall_seconds']+observation['exited_monotonic']-clock['started_monotonic']
            session.data['wall_seconds']=upper+1;session.save()
            before=session.head_ref
            with self.assertRaises(CatalogError) as caught:reconcile_time(session)
            self.assertEqual(caught.exception.diagnostic['reason'],'upper_below_recorded_execution')
            self.assertEqual(Session(catalog,f.context).head_ref,before)
            journal=RuntimeJournal(DataService(catalog),f.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            result=journal.cached
            self.assertEqual(result['kind'],'recovery_required')
            self.assertTrue(result['runtime']['execution_time_uncertain'])
            proof=result['runtime']['time_reconciliation_failures'][0]
            diagnostic=json.loads(catalog.content.read_object(ObjectRef.model_validate(proof)))
            self.assertEqual(diagnostic['observation_ref'],reference)
            self.assertEqual(diagnostic['reason'],'upper_below_recorded_execution')
            self.assertEqual(diagnostic['observed_wall_upper'],upper)
            self.assertEqual(diagnostic['known_wall_seconds'],upper+1)
            self.assertGreaterEqual(Session(catalog,f.context).data['wall_seconds'],upper+1)
            self.assertEqual(journal.budget.summary()['requests'],0)


if __name__=='__main__':unittest.main()
