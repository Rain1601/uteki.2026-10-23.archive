"""Business result persistence must not disappear from current execution time."""
from pathlib import Path
import runpy
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError

F=runpy.run_path(str(Path(__file__).with_name('test_run_completion.py')))

class RuntimeFinalizationTests(unittest.TestCase):
    def test_current_execution_time_includes_result_commit_without_rewriting_result(self):
        case=F['make_case']();case.setUp();self.addCleanup(case.doCleanups)
        def checkpoint(phase):
            if phase=='native_outcome_committed':time.sleep(.25)
        journal=RuntimeJournal(case.service,case.context,F['PROFILE'],F['LIMITS'],checkpoint=checkpoint)
        before=Session(case.catalog,case.context).data['wall_seconds']
        result=journal.finish(F['failure']())
        after=Session(case.catalog,case.context).data
        self.assertGreaterEqual(after['wall_seconds']-before,.25)
        self.assertEqual(after['native_execution']['completion_clock']['status'],'recorded')
        self.assertEqual(result['runtime']['timing_scope'],'through_result_preparation')
        self.assertEqual(case.service.read_run_result(case.context),result)

    def test_final_timing_write_failure_keeps_original_result_and_requires_reconciliation(self):
        case=F['make_case']();case.setUp();self.addCleanup(case.doCleanups)
        journal=RuntimeJournal(case.service,case.context,F['PROFILE'],F['LIMITS'])
        tick=journal.tick
        def fail(**kwargs):
            if kwargs.get('completion'):raise OSError('synthetic final timing failure')
            return tick(**kwargs)
        with patch.object(journal,'tick',fail),self.assertRaises(OSError):journal.finish(F['failure']())
        result=case.service.read_run_result(case.context)
        self.assertEqual(case.service.inspect_context(case.context)['completion_clock']['status'],'pending')
        with self.assertRaises(CatalogError):RuntimeJournal(case.service,case.context,F['PROFILE'],F['LIMITS'])
        recovered=RuntimeJournal(case.service,case.context,F['PROFILE'],F['LIMITS'],recover=True)
        self.assertEqual(recovered.cached,result)
        self.assertTrue(recovered.state()['execution_time_uncertain'])
        self.assertEqual(recovered.state()['completion_clock']['status'],'pending')

    def test_invalid_host_start_cannot_extend_deadline_or_create_native_state(self):
        case=F['make_case']();case.setUp();self.addCleanup(case.doCleanups)
        for started in (float('nan'),float('inf'),-1,time.monotonic()+60,True):
            with self.subTest(started=started),self.assertRaises(CatalogError):
                RuntimeJournal(case.service,case.context,F['PROFILE'],F['LIMITS'],started=started)
        self.assertNotIn('native_execution',Session(case.catalog,case.context).data)

if __name__=='__main__':unittest.main()
