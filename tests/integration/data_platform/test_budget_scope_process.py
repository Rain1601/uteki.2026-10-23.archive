"""Actual worker exit preserves scope ownership, charges and immutable results."""
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from uteki.infrastructure.run_budget import BudgetExceeded, RequestRecoveryRequired, RunBudget

WORKER = Path(__file__).resolve().parents[2]/'fixtures/data_platform/budget_scope_worker.py'


class BudgetScopeProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uteki-budget-scope-process-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'batch.sqlite'
        self.budget = RunBudget(self.path, '1')
        self.budget.bind_root('synthetic-scope-process', mode='remote', max_requests=4,
            max_in_flight_requests=1, scope_ids=['openai-case','claude-case'], policy={'synthetic':True})
        for scope in ('openai-case','claude-case'):
            self.budget.bind_scope(scope, max_requests=2, policy={'context':scope})

    def crash(self, phase):
        result = subprocess.run([sys.executable, '-I', str(WORKER), str(self.path), phase],
            cwd=self.path.parent, env={'PATH':'/usr/bin:/bin'}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 79, result.stderr)
        self.budget = RunBudget.open_existing(self.path, '1', root_run_id='synthetic-scope-process')

    def prepare_other(self):
        return self.budget.prepare_request('other', {'synthetic':'other SDK'}, reserve_usd='.4', scope_id='claude-case')

    def test_exit_during_association_commits_neither_orphan_cost_nor_request(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TRIGGER synthetic_exit BEFORE INSERT ON metered_request_scopes '
                       'BEGIN SELECT synthetic_process_exit(); END'); db.commit()
        self.crash('association')
        self.assertEqual(self.budget.inspect_requests(), [])
        self.assertEqual(self.budget.summary()['requests'], 0)
        self.assertEqual(Decimal(self.budget.summary()['held_usd']), 0)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TRIGGER synthetic_exit'); db.commit()
        self.prepare_other(); self.budget.begin_request('other')

    def test_exit_after_dispatch_blocks_both_kernels_until_original_response_and_bill(self):
        self.prepare_other(); self.crash('dispatch')
        self.budget.recover_requests(scope_id='openai-case')
        self.assertEqual(self.budget.inspect_request('other')['stage'], 'prepared')
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('other')
        self.budget.reconcile_request('first', billed_usd='.2', receipt={
            'request_id':'synthetic-first','source':'synthetic-reconciliation','evidence_sha256':'b'*64})
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('other')
        self.budget.record_response('first', {'synthetic':'recovered original response'}, billed_usd=None)
        self.budget.begin_request('other')
        self.assertEqual(self.budget.summary()['requests'], 2)

    def test_exit_after_response_retains_charge_and_never_dispatches_original_again(self):
        self.crash('response')
        before = self.budget.inspect_request('first')
        repeated = self.budget.prepare_request('first', {'synthetic':'original input'}, reserve_usd='.4', scope_id='openai-case')
        self.assertEqual(before, repeated)
        self.assertEqual(self.budget.recover_requests(scope_id='openai-case'), [])
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('first')
        self.prepare_other(); self.budget.begin_request('other')
        self.assertEqual(Decimal(self.budget.summary()['estimated_spent_usd']), Decimal('.2'))

    def test_scope_stop_survives_exit_and_late_bill_does_not_cancel_other_scope(self):
        self.crash('cancel')
        self.assertEqual(self.budget.inspect_scope('openai-case')['stop_reason'], 'caller_cancelled')
        with self.assertRaises(BudgetExceeded):
            self.budget.prepare_request('replacement', {'synthetic':'new key'}, reserve_usd='.1', scope_id='openai-case')
        self.budget.record_response('first', {'synthetic':'late original response'}, billed_usd='.2',
            receipt={'request_id':'synthetic-first','source':'synthetic-late-peer','evidence_sha256':'c'*64})
        self.prepare_other(); self.budget.begin_request('other')
        self.assertIsNone(self.budget.inspect_root()['stop_reason'])


if __name__ == '__main__':
    unittest.main()
