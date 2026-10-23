"""Independent execution scopes share one physical-request and cost authority."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest

from uteki.data_platform.application.run_budget import (BudgetExceeded, RequestIdentityConflict,
    RequestInFlight, RequestRecoveryRequired, RunBudget)


class BudgetScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uteki-budget-scopes-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'batch.sqlite'
        self.budget = self.make(self.path)

    def make(self, path, *, maximum=8, concurrency=1):
        value = RunBudget(path, '1')
        value.bind_root('synthetic-batch', mode='remote', max_requests=maximum,
            max_in_flight_requests=concurrency, scope_ids=['openai-case', 'claude-case'],
            policy={'kind':'synthetic budget boundary; no network'})
        for scope in ('openai-case', 'claude-case'):
            value.bind_scope(scope, max_requests=min(4, maximum), policy={'context':scope, 'prompt_hash':scope})
        return value

    def prepare(self, key, scope='openai-case', amount='.1', budget=None):
        return (budget or self.budget).prepare_request(key, {'request':'synthetic '+key},
            reserve_usd=amount, scope_id=scope)

    def record(self, key, amount='.1', budget=None):
        return (budget or self.budget).record_response(key, {'body':'original '+key},
            billed_usd=amount, receipt={'request_id':'synthetic-'+key,
                'source':'synthetic-unit-test', 'evidence_sha256':'a'*64})

    def test_cost_is_shared_across_kernels_and_reopen_without_a_second_balance(self):
        self.prepare('a', amount='.6'); self.budget.begin_request('a'); self.record('a', '.4')
        self.budget = RunBudget.open_existing(self.path, '1', root_run_id='synthetic-batch')
        self.prepare('b', 'claude-case', '.5'); self.budget.begin_request('b'); self.record('b', '.4')
        with self.assertRaises(BudgetExceeded): self.prepare('c', 'claude-case', '.21')
        self.assertEqual(Decimal(self.budget.summary()['estimated_spent_usd']), Decimal('.8'))
        self.assertEqual(self.budget.inspect_scope('openai-case')['request_stages'], {'responded':1})
        self.assertEqual(self.budget.inspect_scope('claude-case')['request_stages'], {'responded':1})
        self.assertEqual(list(self.path.parent.glob('*.sqlite')), [self.path])

    def test_scope_cancellation_keeps_late_charge_and_other_scope_can_continue(self):
        self.prepare('a'); self.prepare('unused'); self.budget.begin_request('a')
        stopped = self.budget.stop_scope('openai-case', 'caller_cancelled')
        self.assertEqual(self.budget.stop_scope('openai-case', 'late_timeout'), stopped)
        self.assertIsNone(self.budget.inspect_root()['stop_reason'])
        with self.assertRaises(BudgetExceeded): self.budget.begin_request('unused')
        with self.assertRaises(BudgetExceeded): self.prepare('a-new-key')
        self.record('a', '.07')
        self.budget.abandon_prepared('unused', reason='never dispatched')
        self.prepare('b', 'claude-case'); self.budget.begin_request('b'); self.record('b', '.03')
        self.assertEqual(Decimal(self.budget.inspect_root()['cost']['known_billed_usd']), Decimal('.1'))
        self.assertEqual(self.budget.inspect_scope('openai-case')['stop_reason'], 'caller_cancelled')

    def test_root_cancellation_still_blocks_all_scopes_and_cannot_be_rebound(self):
        self.prepare('a'); self.prepare('b', 'claude-case')
        self.budget.stop_root('user_cancelled_batch')
        self.budget.stop_scope('openai-case', 'later_scenario_timeout')
        for key in ('a', 'b'):
            with self.assertRaisesRegex(BudgetExceeded, 'user_cancelled_batch'):
                self.budget.begin_request(key)
        with self.assertRaises(BudgetExceeded): self.prepare('fresh', 'claude-case')
        self.assertEqual(self.budget.inspect_scope('claude-case')['root_stop_reason'], 'user_cancelled_batch')

    def test_missing_cost_blocks_other_scope_even_after_local_cancellation(self):
        self.prepare('a'); self.prepare('b', 'claude-case'); self.budget.begin_request('a')
        self.budget.stop_scope('openai-case', 'cancelled')
        self.budget.record_response('a', {'body':'received without bill'}, billed_usd=None)
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('b')
        with self.assertRaises(RequestRecoveryRequired): self.prepare('c', 'claude-case')
        self.budget.reconcile_request('a', billed_usd='.02', receipt={'request_id':'synthetic-a',
            'source':'synthetic-bill-reconciliation', 'evidence_sha256':'b'*64})
        self.budget.begin_request('b')
        self.assertEqual(self.budget.summary()['unknown_requests'], 0)

    def test_recovery_does_not_reclassify_another_scopes_known_active_request(self):
        budget = self.make(self.path.with_name('concurrent.sqlite'), concurrency=2)
        self.prepare('a', budget=budget); self.prepare('b', 'claude-case', budget=budget)
        budget.begin_request('a'); budget.begin_request('b')
        self.assertEqual([r['request_key'] for r in budget.recover_requests(scope_id='openai-case')], ['a'])
        self.assertEqual(budget.inspect_request('b')['stage'], 'dispatched')
        self.assertEqual(budget.recover_requests(scope_id='openai-case'), [])
        budget.reconcile_request('a', billed_usd='.03', receipt={'request_id':'synthetic-a',
            'source':'synthetic-bill-only', 'evidence_sha256':'c'*64})
        with self.assertRaises(RequestRecoveryRequired): self.prepare('new', 'claude-case', budget=budget)
        budget.record_response('a', {'body':'recovered original'}, billed_usd=None)
        self.record('b', '.02', budget=budget)
        self.prepare('new', 'claude-case', budget=budget)
        self.assertEqual(Decimal(budget.summary()['estimated_spent_usd']), Decimal('.05'))

    def test_request_and_scope_identity_cannot_be_rebound_or_omitted(self):
        original = self.prepare('same')
        self.assertEqual(original, self.prepare('same'))
        with self.assertRaises(RequestIdentityConflict): self.prepare('same', 'claude-case')
        with self.assertRaises(RequestIdentityConflict): self.prepare('same', None)
        with self.assertRaises(RequestIdentityConflict): self.prepare('new', None)
        with self.assertRaises(RequestIdentityConflict):
            self.budget.bind_scope('invented-case', max_requests=1, policy={'context':'unapproved'})
        with self.assertRaises(RequestIdentityConflict):
            self.budget.bind_scope('openai-case', max_requests=4, policy={'context':'different'})
        with self.assertRaises(RequestIdentityConflict):
            self.budget.bind_scope('openai-case', max_requests=5, policy={'context':'openai-case', 'prompt_hash':'openai-case'})
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_reopening_cannot_remove_scope_registry_or_weaken_serial_dispatch(self):
        self.budget = RunBudget.open_existing(self.path, '1', root_run_id='synthetic-batch')
        options = dict(mode='remote', max_requests=8, max_in_flight_requests=1,
            scope_ids=['claude-case','openai-case'], policy={'kind':'synthetic budget boundary; no network'})
        original = self.budget.bind_root('synthetic-batch', **options)
        for change in ({'scope_ids':None}, {'scope_ids':['openai-case']},
                {'scope_ids':['openai-case','claude-case','new-case']},
                {'max_in_flight_requests':None}, {'max_in_flight_requests':2}):
            with self.subTest(change=change), self.assertRaises(RequestIdentityConflict):
                self.budget.bind_root('synthetic-batch', **(options | change))
        self.assertEqual(self.budget.bind_root('synthetic-batch', **options), original)
        self.assertEqual(self.budget.summary()['requests'], 0)

    def test_scope_limit_and_total_limit_are_enforced_together(self):
        budget = RunBudget(self.path.with_name('limits.sqlite'), '1')
        budget.bind_root('synthetic-batch', mode='remote', max_requests=3,
            scope_ids=['openai-case','claude-case'], policy={'kind':'synthetic'})
        for scope in ('openai-case','claude-case'):
            budget.bind_scope(scope, max_requests=2, policy={'context':scope})
        self.prepare('a1', budget=budget); self.prepare('a2', budget=budget)
        with self.assertRaisesRegex(BudgetExceeded, 'Control scope'): self.prepare('a3', budget=budget)
        self.prepare('b1', 'claude-case', budget=budget)
        with self.assertRaisesRegex(BudgetExceeded, 'Physical request'): self.prepare('b2', 'claude-case', budget=budget)
        self.assertEqual(budget.summary()['requests'], 3)

    def test_concurrent_dispatch_obtains_only_one_slot_and_does_not_resend(self):
        self.prepare('a'); self.prepare('b', 'claude-case')
        def start(key):
            try:
                self.budget.begin_request(key)
                return key, 'started'
            except RequestInFlight:
                return key, 'waiting'
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = dict(pool.map(start, ('a','b')))
        self.assertCountEqual(values.values(), ['started','waiting'])
        first = next(k for k,v in values.items() if v=='started')
        other = next(k for k,v in values.items() if v=='waiting')
        self.assertEqual(self.budget.inspect_request(other)['stage'], 'prepared')
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request(first)
        self.record(first)
        self.budget.begin_request(other)
        self.assertEqual(self.budget.summary()['requests'], 2)

    def test_scope_association_failure_rolls_back_request_and_reservation(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER synthetic_scope_failure BEFORE INSERT ON metered_request_scopes "
                       "BEGIN SELECT RAISE(ABORT,'synthetic association failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.prepare('failed')
        self.assertEqual(self.budget.inspect_requests(), [])
        self.assertEqual(self.budget.summary()['requests'], 0)
        self.assertEqual(Decimal(self.budget.summary()['held_usd']), 0)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TRIGGER synthetic_scope_failure'); db.commit()
        self.prepare('failed')
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_missing_scope_records_fail_closed_instead_of_bypassing_a_stop(self):
        for damage in ('association', 'scope_table'):
            for action in ('dispatch', 'prepare_other'):
                with self.subTest(damage=damage, action=action):
                    budget = self.make(self.path.with_name(f'{damage}-{action}.sqlite'))
                    self.prepare('a', budget=budget)
                    budget.stop_scope('openai-case', 'cancelled')
                    with closing(sqlite3.connect(budget.path)) as db:
                        if damage=='association': db.execute("DELETE FROM metered_request_scopes WHERE request_key='a'")
                        else: db.execute('DROP TABLE metered_scopes')
                        db.commit()
                    before = budget.summary()
                    with self.assertRaises(RequestRecoveryRequired):
                        if action=='dispatch': budget.begin_request('a')
                        else: self.prepare('b', 'claude-case', budget=budget)
                    self.assertEqual(budget.summary(), before)
                    self.assertEqual(budget.inspect_request('a')['stage'], 'prepared')
                    self.assertEqual(len(budget.inspect_requests()), 1)

    def test_legacy_unscoped_shape_and_contract_survive_optional_scope_registration(self):
        budget = RunBudget(self.path.with_name('legacy.sqlite'), '1')
        contract = budget.bind_root('legacy-root', mode='remote', max_requests=4, policy={'legacy':True})
        original = budget.prepare_request('old', {'original':True}, reserve_usd='.1')
        budget.bind_scope('new-scope', max_requests=1, policy={'new':True})
        self.assertNotIn('scope_ids', contract)
        self.assertNotIn('max_in_flight_requests', contract)
        self.assertNotIn('control_scope_id', original)
        self.assertEqual(budget.inspect_request('old'), original)
        self.assertEqual(budget.bind_root('legacy-root', mode='remote', max_requests=4, policy={'legacy':True}), contract)
        with self.assertRaises(RequestIdentityConflict):
            budget.prepare_request('old', {'original':True}, reserve_usd='.1', scope_id='new-scope')
        budget.begin_request('old')
        self.assertEqual(budget.inspect_request('old')['stage'], 'dispatched')


if __name__ == '__main__':
    unittest.main()
