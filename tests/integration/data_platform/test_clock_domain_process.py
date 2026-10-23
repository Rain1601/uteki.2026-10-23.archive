"""Boot identity survives timezone differences without reinterpreting old clocks."""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch

from uteki.data_platform.application.execution_clock import ObservedWorker, reconcile_time
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)


@unittest.skipUnless(sys.platform=='darwin','macOS formatted boot metadata regression')
class ClockDomainProcessTests(unittest.TestCase):
    def fixture(self):
        case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        case.setUp();self.addCleanup(case.doCleanups);case.catalog.close()
        return case

    def worker(self,case,*,timezone,python=None,recovery=False):
        name='recovery_clock_worker.py' if recovery else 'runtime_clock_worker.py'
        with (case.root/(name+'.log')).open('w') as log,patch.dict(os.environ,TZ='UTC'):
            worker=ObservedWorker([python or sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform'/name),
                str(case.root),case.context,'exit' if recovery else '.03'],cwd=case.root,
                env={'PATH':'/usr/bin:/bin','TZ':timezone},stdout=log,stderr=log)
            observed=worker.wait(timeout=20)
        self.assertEqual(observed['returncode'],79,(case.root/(name+'.log')).read_text())
        return worker

    def test_different_timezones_keep_native_and_recovery_clocks_comparable(self):
        case=self.fixture()
        native=self.worker(case,timezone='Asia/Shanghai')
        with Catalog.open(case.root) as catalog,patch.dict(os.environ,TZ='UTC'):
            native.record(catalog,case.context)
        recovery=self.worker(case,timezone='America/New_York',recovery=True)
        with Catalog.open(case.root) as catalog,patch.dict(os.environ,TZ='Europe/Paris'):
            recovery.record(catalog,case.context)
            before=Session(catalog,case.context).data['wall_seconds']
            journal=RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertEqual(journal.cached['kind'],'recovery_required',journal.cached)
            self.assertFalse(journal.cached['runtime']['execution_time_uncertain'])
            after=Session(catalog,case.context).data
            self.assertGreaterEqual(after['wall_seconds'],before)
            native_state=after['native_execution']
            self.assertEqual(native_state['execution_clock']['domain_version'],3)
            self.assertEqual(native_state['recovery_attempts'][0]['status'],'reconciled')
            self.assertGreater(native_state['recovery_attempts'][0]['charged_seconds'],0)
            self.assertEqual(journal.budget.summary()['requests'],0)

    def legacy_python(self):
        path=os.environ.get('UTEKI_LEGACY_CLOCK_PYTHON')
        if not path:self.skipTest('explicit old ordinary-installed package is required')
        self.assertTrue(Path(path).is_absolute() and Path(path).is_file())
        return path

    def test_unrecognized_persisted_clock_version_does_not_publish_an_observation(self):
        case=self.fixture();worker=self.worker(case,timezone='UTC')
        with Catalog.open(case.root) as catalog:
            session=Session(catalog,case.context)
            session.data['native_execution']['execution_clock']['domain_version']=999
            session.save();before=session.head_ref
            with self.assertRaises(CatalogError) as raised:worker.record(catalog,case.context)
            self.assertEqual(raised.exception.code,'RECOVERY_REQUIRED')
            self.assertEqual(Session(catalog,case.context).head_ref,before)
            self.assertNotIn('exit_observation',Session(catalog,case.context).data['native_execution'])

    def test_legacy_worker_keeps_original_clock_and_observation_when_same_timezone(self):
        python=self.legacy_python();case=self.fixture()
        worker=self.worker(case,timezone='UTC',python=python)
        with Catalog.open(case.root) as catalog,patch.dict(os.environ,TZ='UTC'):
            clock=Session(catalog,case.context).data['native_execution']['execution_clock'].copy()
            self.assertNotIn('domain_version',clock)
            reference=worker.record(catalog,case.context)
            self.assertEqual(worker.record(catalog,case.context),reference)
            journal=RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertFalse(journal.cached['runtime']['execution_time_uncertain'])
            after=Session(catalog,case.context)
            self.assertEqual(after.data['native_execution']['execution_clock'],clock)
            before=after.head_ref
            with patch.dict(os.environ,TZ='Asia/Shanghai'),self.assertRaises(CatalogError):
                reconcile_time(after)
            self.assertEqual(Session(catalog,case.context).head_ref,before)

    def test_legacy_worker_from_different_timezone_cannot_be_relabelled(self):
        python=self.legacy_python();case=self.fixture()
        worker=self.worker(case,timezone='Asia/Shanghai',python=python)
        with Catalog.open(case.root) as catalog,patch.dict(os.environ,TZ='UTC'):
            before=Session(catalog,case.context).head_ref
            with self.assertRaises(CatalogError):worker.record(catalog,case.context)
            self.assertEqual(Session(catalog,case.context).head_ref,before)

    def test_observation_written_by_old_installed_supervisor_remains_readable(self):
        python=self.legacy_python();case=self.fixture()
        code='''
import subprocess,sys
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.catalog import Catalog
worker=ObservedWorker([sys.executable,'-I',sys.argv[1],sys.argv[2],sys.argv[3],'.03'],
    cwd=sys.argv[2],env={'PATH':'/usr/bin:/bin','TZ':'UTC'},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
assert worker.wait(timeout=20)['returncode']==79
worker.child.communicate()
with Catalog.open(sys.argv[2]) as catalog:worker.record(catalog,sys.argv[3])
'''
        old=subprocess.run([python,'-I','-c',code,str(ROOT/'tests/fixtures/data_platform/runtime_clock_worker.py'),
            str(case.root),case.context],cwd=case.root,env={'PATH':'/usr/bin:/bin','TZ':'UTC'},
            capture_output=True,text=True,timeout=30)
        self.assertEqual(old.returncode,0,old.stderr)
        with Catalog.open(case.root) as catalog,patch.dict(os.environ,TZ='UTC'):
            before=Session(catalog,case.context).data['native_execution']
            journal=RuntimeJournal(DataService(catalog),case.context,dict(kernel='clock_fixture'),LIMITS,recover=True)
            self.assertFalse(journal.cached['runtime']['execution_time_uncertain'])
            after=Session(catalog,case.context).data['native_execution']
            self.assertEqual(after['execution_clock'],before['execution_clock'])
            self.assertEqual(after['exit_observation'],before['exit_observation'])
            self.assertEqual(journal.budget.summary()['requests'],0)


if __name__=='__main__':unittest.main()
