"""Explicit one-request diagnostics retain prior unknown charges and all limits."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.run_budget import RunBudget, RequestRecoveryRequired, RequestIdentityConflict, BudgetExceeded
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, observe_response


class DiagnosticRequestTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'budget.sqlite'
        self.budget = RunBudget(self.path, '1')
        self.budget.bind_root('root', mode='remote', max_requests=3, policy={'fixture': True})
        self.budget.prepare_request('old', {'fixture': 'old'}, reserve_usd='.4')
        self.budget.begin_request('old')
        self.budget.record_response('old', {'complete': True, 'http': {'status': 404}}, billed_usd=None)

    def authorization(self, request, cap='.1'):
        event = self.budget.inspect_request('old')['response_event']
        return dict(id='user-instruction-1', authorized_by='user', user_message='Make one minimal diagnostic request.',
            root_run_id='root', scope_id=None, max_requests=1, max_reserve_usd=cap,
            request_sha256=hashlib.sha256(RunBudget._json(request).encode()).hexdigest(),
            retained_unknown_requests={'old': hashlib.sha256(RunBudget._json(event).encode()).hexdigest()})

    def test_one_request_survives_reopen_and_retains_unknown_charge_without_general_bypass(self):
        request={'fixture': 'diagnostic'}; auth=self.authorization(request)
        original=self.budget.inspect_request('old')
        self.budget.prepare_request('probe', request, reserve_usd='.1', diagnostic_authorization=auth)
        self.budget=RunBudget.open_existing(self.path,'1',root_run_id='root')
        self.budget.begin_request('probe')
        self.budget.record_response('probe', {'complete': True}, billed_usd='0',
            receipt={'request_id':'probe','source':'synthetic fixture','evidence_sha256':'0'*64})
        self.assertEqual(self.budget.inspect_request('old'),original)
        self.assertEqual(self.budget.summary()['held_usd'],'0.4')
        with self.assertRaises(RequestRecoveryRequired):
            self.budget.prepare_request('ordinary',request,reserve_usd='.1')
        with self.assertRaises(RequestIdentityConflict):
            self.budget.prepare_request('probe-again',request,reserve_usd='.1',diagnostic_authorization=auth)
        self.assertEqual(self.budget.summary()['requests'],2)

    def test_changed_request_or_unknown_evidence_cannot_use_authorization(self):
        request={'fixture':'diagnostic'}; auth=self.authorization(request)
        with self.assertRaises(RequestIdentityConflict):
            self.budget.prepare_request('changed',{'fixture':'different'},reserve_usd='.1',diagnostic_authorization=auth)
        auth['retained_unknown_requests']={}
        with self.assertRaises(RequestIdentityConflict):
            self.budget.prepare_request('missing-evidence',request,reserve_usd='.1',diagnostic_authorization=auth)

    def test_budget_and_diagnostic_reservation_cap_still_apply(self):
        request={'fixture':'diagnostic'}
        with self.assertRaises(BudgetExceeded):
            self.budget.prepare_request('cap',request,reserve_usd='.2',diagnostic_authorization=self.authorization(request))
        with self.assertRaises(BudgetExceeded):
            self.budget.prepare_request('root-cap',request,reserve_usd='.7',diagnostic_authorization=self.authorization(request,'.7'))
        self.assertEqual(self.budget.summary()['requests'],1)

    def test_unknown_dispatch_cannot_be_bypassed(self):
        request={'fixture':'diagnostic'}
        # An independent fixture models a dispatch whose response was never observed.
        path=self.path.with_name('partial.sqlite');self.budget=RunBudget(path,'1')
        self.budget.bind_root('root',mode='remote',max_requests=3,policy={'fixture':True})
        self.budget.prepare_request('old',{'fixture':'old'},reserve_usd='.4');self.budget.begin_request('old')
        self.budget.record_response('old',{'complete':False},billed_usd=None,outcome_known=False)
        with self.assertRaises(RequestRecoveryRequired):
            self.budget.prepare_request('probe',request,reserve_usd='.1',diagnostic_authorization=self.authorization(request))

    def test_sdk_decoded_json_is_explicit_while_raw_encoded_body_remains_rejected(self):
        import gzip
        raw=b'{"id":"gen-fixture","object":"chat.completion","model":"fixture","choices":[{"finish_reason":"stop"}],"usage":{"cost":0.000008}}'
        headers=[('Content-Type','application/json'),('Content-Encoding','gzip')]
        decoded=capture_response('chat_completions',200,headers,[raw],max_bytes=1000)
        self.assertIn('unsupported_content_encoding',observe_response(decoded)['issues'])
        decoded['body_representation']='decoded_by_httpx2'
        self.assertEqual(observe_response(decoded)['billed_usd'],'0.000008')
        encoded=capture_response('chat_completions',200,headers,[gzip.compress(raw)],max_bytes=1000)
        self.assertFalse(observe_response(encoded)['protocol_complete'])

    def test_acknowledged_complete_response_keeps_money_and_caps_after_reopen(self):
        original=self.budget.inspect_request('old')
        before=self.budget.inspect_root()
        row=self.budget.retain_response_reservation('old',confirmation='Continue within the original limit.')
        self.assertEqual(row['cost_state'],'bounded')
        self.assertIsNone(row['bill']);self.assertIsNone(row['settled_usd'])
        self.assertEqual(row['response_event']['response'],original['response_event']['response'])
        self.assertEqual(self.budget.inspect_root()['cost']['remaining_usd'],before['cost']['remaining_usd'])
        self.budget=RunBudget.open_existing(self.path,'1',root_run_id='root')
        self.assertEqual(self.budget.retain_response_reservation('old',
            confirmation='Continue within the original limit.'),row)
        with self.assertRaises(RequestIdentityConflict):
            self.budget.retain_response_reservation('old',confirmation='Changed approval')
        with self.assertRaises(RequestRecoveryRequired):self.budget.begin_request('old')
        with self.assertRaises(BudgetExceeded):self.budget.prepare_request('too-much',{'test':1},reserve_usd='.7')
        for key in ('next','last'):
            self.budget.prepare_request(key,{'test':key},reserve_usd='.1')
            self.budget.begin_request(key)
            self.budget.record_response(key,{'complete':True},billed_usd='.01',
                receipt=dict(request_id=key,source='synthetic',evidence_sha256='0'*64))
        with self.assertRaises(BudgetExceeded):self.budget.prepare_request('fourth',{'test':4},reserve_usd='.1')
        self.assertEqual(self.budget.summary()['held_usd'],'0.4')
        self.budget.reconcile_request('old',billed_usd='.02',
            receipt=dict(request_id='old',source='synthetic',evidence_sha256='0'*64))
        self.assertEqual(self.budget.summary()['held_usd'],'0')
        self.assertEqual(self.budget.inspect_request('old')['response_event'],row['response_event'])

    def test_acknowledgement_does_not_cover_future_missing_bills_or_stops(self):
        self.budget.retain_response_reservation('old',confirmation='Continue this batch.')
        self.budget.prepare_request('new',{'test':'new'},reserve_usd='.1')
        self.budget.begin_request('new')
        self.budget.record_response('new',{'complete':True},billed_usd=None)
        with self.assertRaises(RequestRecoveryRequired):
            self.budget.prepare_request('blocked',{'test':3},reserve_usd='.1')
        self.budget.retain_response_reservation('new',confirmation='Synthetic follow-up approval.')
        self.budget.stop_root('cancelled')
        with self.assertRaises(BudgetExceeded):self.budget.prepare_request('stopped',{'test':3},reserve_usd='.1')

    def test_acknowledgement_cannot_cover_dispatch_or_partial_response(self):
        self.budget.retain_response_reservation('old',confirmation='Continue this batch.')
        self.budget.prepare_request('partial',{'test':'partial'},reserve_usd='.1')
        self.budget.begin_request('partial')
        with self.assertRaises(RequestRecoveryRequired):
            self.budget.retain_response_reservation('partial',confirmation='Continue.')
        self.budget.record_response('partial',{'complete':False},billed_usd=None,outcome_known=False)
        with self.assertRaises(RequestRecoveryRequired):
            self.budget.retain_response_reservation('partial',confirmation='Continue.')
        self.assertEqual(self.budget.summary()['held_usd'],'0.5')


if __name__ == '__main__': unittest.main()
