"""A complete usage observation may retain its hold; it must never invent a bill."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from uteki.data_platform.application.run_budget import RunBudget, BudgetExceeded, RequestRecoveryRequired, RequestIdentityConflict
from uteki.data_platform.agent.providers.deepseek_evidence import record_response
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response


PRICE = dict(currency='USD', input_per_million='0.3', output_per_million='1.2',
             source='https://api-docs.deepseek.com/quick_start/pricing/', observed_at='2026-10-15')


class LiveProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'budget.sqlite'
        self.budget = RunBudget(self.path, '1')
        self.budget.bind_root('live-test', mode='remote', max_requests=4,
            policy=dict(retain_usage_estimate_reservations=True))

    def capture(self, usage=True, complete=True, model='deepseek-flash'):
        value = dict(id='deepseek-fixture-response', object='chat.completion', model=model,
            choices=[dict(finish_reason='tool_calls', message=dict(role='assistant', content=None,
                         tool_calls=[dict(id='call-1', type='function', function=dict(name='find_assets', arguments='{}'))]))])
        if usage:
            value['usage'] = dict(prompt_tokens=1000, completion_tokens=100, prompt_cache_hit_tokens=0)
        raw = json.dumps(value).encode()
        captured = capture_response('chat_completions', 200, [('Content-Type','application/json')], [raw], max_bytes=10000)
        if not complete:
            captured.update(transport_complete=False, error='IncompleteRead')
        return captured

    def dispatch(self, key='first', reserve='.3'):
        self.budget.prepare_request(key, {'model':'deepseek-flash'}, reserve_usd=reserve)
        self.budget.begin_request(key)

    def record(self, captured):
        return record_response(self.budget, 'first', captured, profile={'model_id':'deepseek-flash'}, pricing=PRICE)

    def test_usage_keeps_full_hold_without_claiming_provider_charge_and_survives_reopen(self):
        self.dispatch()
        row = self.record(self.capture())
        self.assertEqual(row['cost_state'], 'bounded')
        self.assertIsNone(row['bill']); self.assertIsNone(row['settled_usd'])
        self.assertEqual(Decimal(row['response_event']['usage_estimate']['estimated_usd']), Decimal('.00042'))
        self.budget = RunBudget.open_existing(self.path, '1', root_run_id='live-test')
        self.assertEqual(self.budget.summary()['held_usd'], '0.3')
        self.assertEqual(self.budget.inspect_root()['cost']['known_billed_usd'], '0')
        self.assertEqual(self.budget.inspect_root()['cost']['remaining_usd'], '0.7')
        self.dispatch('second', '.7')
        with self.assertRaises(BudgetExceeded):
            self.budget.prepare_request('over', {'model':'deepseek-flash'}, reserve_usd='.01')

    def test_missing_usage_remains_unknown_and_blocks_further_dispatch(self):
        self.dispatch()
        with self.assertRaises(ValueError): self.record(self.capture(usage=False))
        self.assertEqual(self.budget.inspect_request('first')['cost_state'], 'unknown')
        with self.assertRaises(RequestRecoveryRequired): self.dispatch('second')

    def test_partial_response_cannot_be_promoted_by_valid_usage(self):
        self.dispatch()
        row = self.record(self.capture(complete=False))
        self.assertEqual(row['stage'], 'outcome_unknown')
        self.assertEqual(row['cost_state'], 'unknown')
        with self.assertRaises(RequestRecoveryRequired): self.dispatch('second')

    def test_wrong_model_and_underreserved_response_fail_without_releasing_hold(self):
        self.dispatch(reserve='.00001')
        with self.assertRaises(BudgetExceeded): self.record(self.capture())
        self.assertEqual(self.budget.summary()['held_usd'], '0.00001')
        self.assertEqual(self.budget.inspect_request('first')['cost_state'], 'unknown')

    def test_verified_later_bill_settles_same_request_and_retains_usage_evidence(self):
        self.dispatch()
        before = self.record(self.capture())
        row = self.budget.reconcile_request('first', billed_usd='.0002', receipt=dict(
            request_id='provider-receipt', source='test-provider-bill', evidence_sha256='b'*64))
        self.assertEqual(row['cost_state'], 'settled')
        self.assertEqual(row['response_event'], before['response_event'])
        self.assertEqual(self.budget.summary()['held_usd'], '0')

    def test_estimate_cannot_replace_evidence_or_be_enabled_for_legacy_roots(self):
        self.dispatch()
        row = self.record(self.capture())
        estimate = row['response_event']['usage_estimate']
        with self.assertRaises(RequestIdentityConflict):
            self.budget.retain_usage_estimate('first', estimated_usd=estimate['estimated_usd'],
                evidence=estimate['evidence'] | {'response_sha256':'b'*64})
        legacy = RunBudget(self.path.with_name('legacy.sqlite'), '1')
        legacy.bind_root('legacy', mode='remote', max_requests=2, policy={'legacy_contract': True})
        with self.assertRaises(ValueError):
            legacy.retain_usage_estimate('first', estimated_usd=estimate['estimated_usd'], evidence=estimate['evidence'])


if __name__ == '__main__': unittest.main()
