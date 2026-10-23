"""Recover the actual installed ledger after an abrupt child process exit."""
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from uteki.data_platform.application.run_budget import RequestRecoveryRequired, RunBudget


WORKER = Path(__file__).resolve().parents[2]/'fixtures/data_platform/runtime_budget_worker.py'


class RuntimeBudgetProcessTests(unittest.TestCase):
    def test_reopen_after_each_durable_dispatch_boundary_never_resends(self):
        for phase in ['preparing','prepared','dispatched','responding','responded']:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix='uteki-meter-exit-') as temp:
                path = Path(temp)/'ledger.sqlite'
                child = subprocess.run([sys.executable, '-I', str(WORKER), str(path), phase],
                                       capture_output=True, text=True, timeout=20, cwd=temp)
                self.assertEqual(child.returncode, 73, child.stderr)
                budget = RunBudget(path, '1')
                self.assertEqual(budget.inspect_root()['root_run_id'], 'synthetic-process-root')
                recovered = budget.recover_requests()
                if phase == 'preparing':
                    self.assertEqual(recovered, [])
                    self.assertEqual(budget.summary()['requests'], 0)
                    self.assertEqual(budget.inspect_root()['request_stages'], {})
                    continue
                stored = budget.inspect_request('physical-request')
                self.assertEqual(budget.summary()['requests'], 1)
                if phase == 'prepared':
                    self.assertEqual(recovered, [])
                    self.assertEqual(stored['stage'], 'prepared')
                    budget.abandon_prepared('physical-request', reason='confirmed never dispatched')
                    self.assertEqual(budget.summary()['held_usd'], '0')
                elif phase in {'dispatched','responding'}:
                    self.assertEqual(len(recovered), 1)
                    self.assertEqual(stored['stage'], 'outcome_unknown')
                    self.assertEqual(budget.summary()['unknown_requests'], 1)
                    self.assertEqual(Decimal(budget.summary()['held_usd']), Decimal('.4'))
                    self.assertIsNone(stored['response_event'])
                    with self.assertRaises(RequestRecoveryRequired):
                        budget.begin_request('physical-request')
                else:
                    self.assertEqual(recovered, [])
                    self.assertEqual(stored['stage'], 'responded')
                    self.assertEqual(stored['response_event']['response']['output'], 'original synthetic response')
                    self.assertEqual(Decimal(budget.summary()['estimated_spent_usd']), Decimal('.2'))
                    with self.assertRaises(RequestRecoveryRequired):
                        budget.begin_request('physical-request')


if __name__ == '__main__':
    unittest.main()
