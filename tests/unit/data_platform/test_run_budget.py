"""Durable request behavior over the existing single reservation ledger."""
from decimal import Decimal
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from uteki.data_platform.application.run_budget import (
    BudgetExceeded, RequestIdentityConflict, RequestRecoveryRequired, RunBudget,
)


class DurableBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uteki-root-budget-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'budget.sqlite'
        self.budget = RunBudget(self.path, '1')
        self.policy = dict(model_calls=3, clock='frozen-fixture-clock', kernel='fixture')
        self.budget.bind_root('synthetic-root', mode='remote', max_requests=3, policy=self.policy)

    def receipt(self, key='first'):
        return dict(request_id='synthetic-provider-'+key, source='synthetic-ledger-test', evidence_sha256='a'*64)

    def prepare(self, key='first', amount='.4', **metadata):
        return self.budget.prepare_request(key, dict(model='fixture/model', role='query', **metadata), reserve_usd=amount)

    def test_ledger_without_root_binding_keeps_reserve_and_settle_semantics(self):
        legacy = RunBudget(self.path.with_name('legacy.sqlite'), '1')
        token = legacy.reserve('.3'); legacy.settle(token, '.2')
        self.assertEqual(Decimal(legacy.summary()['estimated_spent_usd']), Decimal('.2'))
        with self.assertRaises(ValueError):
            legacy.bind_root('root', mode='remote', max_requests=2, policy=self.policy)
        self.assertEqual(legacy.summary()['requests'], 1)

    def test_preparation_reopen_replay_and_identity_do_not_double_reserve(self):
        original = self.prepare()
        self.budget = RunBudget(self.path, '1')
        self.budget.bind_root('synthetic-root', mode='remote', max_requests=3, policy=self.policy)
        self.assertEqual(self.prepare(), original)
        self.assertEqual(self.budget.summary()['requests'], 1)

        for changes in ({'model_id':'different'}, {'prompt_hash':'changed'}):
            with self.assertRaises(RequestIdentityConflict):
                self.prepare(**changes)
        with self.assertRaises(RequestIdentityConflict):
            self.prepare(amount='.5')
        with self.assertRaises(RequestIdentityConflict):
            self.budget.bind_root('new-root', mode='remote', max_requests=3, policy=self.policy)
        with self.assertRaises(RequestIdentityConflict):
            self.budget.bind_root('synthetic-root', mode='remote', max_requests=4, policy=self.policy)
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_concurrent_same_key_gets_one_reservation_and_only_one_dispatch_permission(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = list(pool.map(lambda _: self.prepare(), range(2)))
            self.assertEqual(prepared[0]['reservation_id'], prepared[1]['reservation_id'])
            def begin(_):
                try:
                    return self.budget.begin_request('first')['stage']
                except RequestRecoveryRequired:
                    return 'already_dispatched'
            self.assertCountEqual(list(pool.map(begin, range(2))), ['dispatched','already_dispatched'])
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_prepared_request_release_is_safe_but_dispatch_cannot_be_repeated(self):
        self.prepare()
        released = self.budget.abandon_prepared('first', reason='cancelled before dispatch')
        self.assertEqual(released['stage'], 'abandoned')
        self.assertEqual(self.budget.summary()['held_usd'], '0')
        self.assertEqual(self.budget.abandon_prepared('first', reason='cancelled before dispatch'), released)
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('first')
        self.prepare('next'); self.budget.begin_request('next')
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('next')
        with self.assertRaises(RequestRecoveryRequired): self.budget.abandon_prepared('next', reason='not safe')
        self.assertEqual(self.budget.summary()['in_flight_requests'], 1)

    def test_accepted_response_and_bill_are_idempotent_and_cannot_be_replaced(self):
        self.prepare(); self.budget.begin_request('first')
        kwargs = dict(response={'output':'synthetic original'}, billed_usd='.2', receipt=self.receipt())
        stored = self.budget.record_response('first', **kwargs)
        self.assertEqual(self.budget.record_response('first', **kwargs), stored)
        self.assertEqual(stored['stage'], 'responded')
        for changes in ({'response':{'output':'replacement'}}, {'billed_usd':'.1'}):
            with self.assertRaises(RequestIdentityConflict):
                self.budget.record_response('first', **(kwargs | changes))
        self.assertEqual(self.budget.inspect_request('first')['response_event']['response'], kwargs['response'])
        self.assertEqual(Decimal(self.budget.summary()['estimated_spent_usd']), Decimal('.2'))
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('first')

    def test_unknown_dispatch_preserves_hold_and_blocks_new_or_changed_keys(self):
        self.prepare(); self.budget.begin_request('first')
        self.assertEqual(len(self.budget.recover_requests()), 1)
        self.assertEqual(self.budget.recover_requests(), [])
        recovered = self.prepare()
        self.assertEqual(recovered['stage'], 'outcome_unknown')
        self.assertEqual(recovered['cost_state'], 'unknown')
        self.assertIsNone(recovered['response_event'])
        self.assertEqual(Decimal(self.budget.summary()['held_usd']), Decimal('.4'))
        self.assertEqual(Decimal(self.budget.inspect_root()['cost']['unknown_reserved_usd']), Decimal('.4'))
        self.assertEqual(Decimal(self.budget.inspect_root()['cost']['known_billed_usd']), Decimal('0'))
        with self.assertRaises(RequestRecoveryRequired): self.budget.begin_request('first')
        with self.assertRaises(RequestRecoveryRequired): self.prepare('replacement')
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_bill_reconciliation_is_not_a_recovered_response(self):
        self.prepare(); self.budget.begin_request('first'); self.budget.recover_requests()
        fixed = self.budget.reconcile_request('first', billed_usd='.2', receipt=self.receipt())
        self.assertEqual(fixed['stage'], 'outcome_unknown')
        self.assertIsNone(fixed['response_event'])
        with self.assertRaises(RequestRecoveryRequired): self.prepare('next')
        recovered = self.budget.record_response('first', {'output':'recovered original'}, billed_usd=None)
        self.assertEqual(recovered['cost_state'], 'settled')
        self.assertEqual(Decimal(recovered['settled_usd']), Decimal('.2'))
        self.prepare('next')
        self.assertEqual(self.budget.summary()['requests'], 2)

    def test_response_without_usage_keeps_hold_until_provider_bill_is_checked(self):
        self.prepare(); self.budget.begin_request('first')
        stored = self.budget.record_response('first', {'output':'no usage'}, billed_usd=None)
        self.assertEqual(stored['stage'], 'responded')
        self.assertEqual(stored['cost_state'], 'unknown')
        with self.assertRaises(RequestRecoveryRequired): self.prepare('next')
        with self.assertRaises(ValueError):
            self.budget.reconcile_request('first', billed_usd='0', receipt={'sdk_estimate':True})
        self.budget.reconcile_request('first', billed_usd='.1', receipt=self.receipt())
        self.budget.reconcile_request('first', billed_usd='.1', receipt=self.receipt())
        with self.assertRaises(RequestIdentityConflict):
            self.budget.reconcile_request('first', billed_usd='0', receipt=self.receipt())
        self.prepare('next')
        self.assertEqual(self.budget.summary()['unknown_requests'], 0)

    def test_cancellation_blocks_prepared_and_new_dispatch_but_retains_late_response(self):
        self.prepare(); self.prepare('prepared', '.2'); self.budget.begin_request('first')
        stopped = self.budget.stop_root('cancelled')
        self.assertEqual(stopped, self.budget.stop_root('later reason'))
        with self.assertRaises(BudgetExceeded): self.budget.begin_request('prepared')
        with self.assertRaises(BudgetExceeded): self.prepare('new')
        self.budget.record_response('first', {'output':'late'}, billed_usd=None)
        self.budget.abandon_prepared('prepared', reason='root cancelled before dispatch')
        self.assertEqual(self.budget.summary()['unknown_requests'], 1)
        self.assertEqual(Decimal(self.budget.summary()['held_usd']), Decimal('.4'))

    def test_helper_requests_share_cost_and_physical_request_limit(self):
        for key in ['main','compression','auxiliary']:
            self.prepare(key, '.1', purpose=key)
        with self.assertRaises(BudgetExceeded): self.prepare('retry', '.1')
        self.assertEqual(self.budget.summary()['requests'], 3)
        self.assertEqual(self.budget.inspect_root()['request_stages'], {'prepared':3})

    def test_preparing_rollback_cannot_leave_unbound_cost(self):
        original = self.budget._reserve
        def fail_after_reserve(db, amount):
            original(db, amount)
            raise OSError('controlled failure before request association')
        self.budget._reserve = fail_after_reserve
        with self.assertRaises(OSError): self.prepare()
        self.assertEqual(self.budget.summary()['requests'], 0)
        self.assertEqual(self.budget.inspect_root()['request_stages'], {})
        self.budget._reserve = original
        self.prepare()
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_response_and_cost_rollback_together_on_write_failure(self):
        self.prepare(); self.budget.begin_request('first')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_response BEFORE UPDATE OF response_event ON metered_requests "
                       "BEGIN SELECT RAISE(ABORT,'controlled response failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.budget.record_response('first', {'output':'complete'}, billed_usd='.2', receipt=self.receipt())
        stored = self.budget.inspect_request('first')
        self.assertEqual(stored['stage'], 'dispatched')
        self.assertEqual(stored['cost_state'], 'reserved')
        self.assertIsNone(stored['response_event'])
        self.assertIsNone(stored['bill'])
        self.budget.recover_requests()
        self.assertEqual(self.budget.summary()['unknown_requests'], 1)

    def test_actual_over_estimate_is_recorded_and_blocks_already_prepared_dispatch(self):
        self.prepare(amount='.6'); self.prepare('next', '.3')
        self.budget.begin_request('first')
        self.budget.record_response('first', {'output':'cost over estimate'}, billed_usd='.8', receipt=self.receipt())
        with self.assertRaises(BudgetExceeded): self.budget.begin_request('next')
        self.assertEqual(Decimal(self.budget.summary()['estimated_spent_usd']), Decimal('.8'))
        self.assertEqual(Decimal(self.budget.summary()['held_usd']), Decimal('.3'))
        self.assertTrue(self.budget.inspect_root()['cost']['over_limit'])
        self.assertEqual(Decimal(self.budget.inspect_root()['cost']['remaining_usd']), Decimal('-.1'))

    def test_old_api_and_reopen_flags_cannot_bypass_bound_root(self):
        token = self.prepare()['reservation_id']
        with self.assertRaises(ValueError): self.budget.reserve('.1')
        with self.assertRaises(ValueError): self.budget.settle(token, '0')
        permissive = RunBudget(self.path, '1', enforce=False, allow_unknown_reservations=True)
        with self.assertRaises(ValueError): permissive.prepare_request('bypass', {'model':'fixture'}, reserve_usd='.1')
        self.assertEqual(self.budget.summary()['requests'], 1)

    def test_explicit_zero_budget_is_only_usable_for_synthetic_requests(self):
        zero = RunBudget(self.path.with_name('zero.sqlite'), '0', allow_zero_limit=True)
        zero.bind_root('offline-root', mode='offline', max_requests=1, policy=self.policy)
        zero.prepare_request('fixture', {'model':'fixture'}, reserve_usd='0')
        zero.begin_request('fixture')
        zero.record_response('fixture', {'output':'synthetic'}, billed_usd='0')
        self.assertEqual(zero.summary()['estimated_spent_usd'], '0')
        self.assertEqual(zero.inspect_request('fixture')['bill']['basis'], 'synthetic_zero')
        with self.assertRaises(ValueError): zero.prepare_request('paid', {'model':'real'}, reserve_usd='.1')
        with self.assertRaises(ValueError):
            zero.bind_root('offline-root', mode='remote', max_requests=1, policy=self.policy)


if __name__ == '__main__':
    unittest.main()
