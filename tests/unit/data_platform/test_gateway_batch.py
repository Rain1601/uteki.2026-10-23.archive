"""Business identities remain distinct while physical requests share one ledger."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import runpy
import unittest
import uuid

from uteki.data_platform.application.gateway_batch import create_gateway_batch, load_gateway_binding
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response
from uteki.infrastructure.run_budget import RequestRecoveryRequired

LIMITS=dict(native_max_turns=12,max_model_requests=2,max_request_bytes=10000,max_response_bytes=10000)


def fixture():
    case=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
    case.setUp()
    request=deepcopy(case.request);request['run_policy']['max_usd']='3'
    scopes=[]
    for kernel in ('openai','claude'):
        context=case.service.create_context(request,request_key='gateway-'+kernel)['context_ref']
        scopes.append(dict(scope_id=kernel,context_ref=context,profile=dict(kernel=kernel,model_id='synthetic/model'),
            limits=LIMITS,transport=dict(max_request_bytes=10000,max_response_bytes=10000,
                request_timeout_seconds=10,reserve_usd='.8')))
    args=dict(batch_id=str(uuid.uuid4()),scopes=scopes,limit_usd='3',max_requests=4,origin='synthetic',contract_sha256='a'*64)
    return case,args


def failure(profile):
    return dict(kind='failed',status='failed',error='synthetic failure',native_success=False,
        delivery=None,committed_delivery=None,clarification=None,committed_clarification=None,
        profile=profile,native_events=[],tool_events=[],mode='offline',real_model_calls=0,gateway_cost_usd=None)


class GatewayBatchTests(unittest.TestCase):
    def setUp(self):
        self.case,self.args=fixture();self.addCleanup(self.case.doCleanups)
        self.bindings=create_gateway_batch(self.case.catalog,**self.args)

    def journal(self,kernel,**kwargs):
        scope=next(s for s in self.args['scopes'] if s['scope_id']==kernel)
        return RuntimeJournal(self.case.service,scope['context_ref'],scope['profile'],scope['limits'],
            gateway_binding=self.bindings[kernel],**kwargs)

    def request(self,journal,key,*,finish=True,cost=True):
        budget=journal.budget;scope=journal.gateway_binding['scope_id']
        budget.prepare_request(key,dict(context_ref=journal.context_ref),reserve_usd='.8',scope_id=scope)
        budget.begin_request(key)
        if finish:
            raw=json.dumps(dict(id='gen-synthetic-'+key,object='chat.completion',choices=[dict(finish_reason='stop')],
                usage={'cost':.04} if cost else {})).encode()
            record_response(budget,key,capture_response('chat_completions',200,[('Content-Type','application/json')],
                [raw],max_bytes=10000),origin='synthetic')

    def test_distinct_business_roots_share_one_existing_ledger(self):
        first=self.journal('openai');second=self.journal('claude')
        self.assertNotEqual(first.context['root_run_id'],second.context['root_run_id'])
        self.assertNotEqual(first.state()['native_session_id'],second.state()['native_session_id'])
        self.assertEqual(first.budget.path,second.budget.path)
        self.assertEqual(first.budget.inspect_root()['root_run_id'],self.args['batch_id'])
        self.request(first,'one');self.request(second,'two')
        self.assertEqual(Decimal(first.budget.inspect_root()['cost']['known_billed_usd']),Decimal('.08'))
        self.assertEqual(len(list(self.case.root.rglob('budget.sqlite'))),1)
        self.assertEqual(create_gateway_batch(self.case.catalog,**self.args),self.bindings)
        self.assertEqual(second.budget.summary()['requests'],2)

    def test_cancel_stops_only_own_scope_and_root_stop_still_stops_all(self):
        first=self.journal('openai');second=self.journal('claude')
        first.stop('cancelled')
        with self.assertRaises(CatalogError):first.guard_transport()
        second.guard_action();self.request(second,'second')
        self.assertIsNone(second.budget.inspect_root()['stop_reason'])
        second.budget.stop_root('cancelled')
        with self.assertRaises(CatalogError):second.guard_transport()

    def test_unknown_fee_blocks_business_actions_in_other_scope(self):
        first=self.journal('openai');second=self.journal('claude')
        self.request(first,'unknown',cost=False)
        with self.assertRaises(CatalogError) as caught:second.guard_action()
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(Decimal(second.budget.summary()['held_usd']),Decimal('.8'))

    def test_finish_does_not_recover_another_active_scope(self):
        first=self.journal('openai');second=self.journal('claude')
        self.request(second,'active',finish=False)
        result=first.finish(failure(first.profile))
        self.assertEqual(second.budget.inspect_request('active')['stage'],'dispatched')
        self.assertEqual(second.budget.inspect_request('active')['cost_state'],'reserved')
        self.assertEqual(result['runtime']['root_run_id'],first.context['root_run_id'])
        self.assertEqual(result['runtime']['budget']['root_run_id'],self.args['batch_id'])
        self.assertEqual(result['runtime']['control_scope']['scope_id'],'openai')
        self.assertEqual(result['mode'],'gateway_synthetic');self.assertEqual(result['real_model_calls'],0)
        self.assertTrue(result['reconciliation_required'])
        self.assertEqual(self.journal('openai',recover=True).cached,result)

    def test_cancelled_delivery_reads_shared_usage_without_claiming_real_charges(self):
        first=self.journal('openai');second=self.journal('claude')
        self.request(first,'first');self.request(second,'second')
        first.stop('cancelled')
        result=first.finish(failure(first.profile))
        self.assertEqual(result['kind'],'delivery',result)
        self.assertEqual(result['status'],'cancelled')
        usage=result['delivery']['delivery']['usage']
        self.assertEqual(usage['mode'],'gateway_synthetic')
        self.assertEqual(usage['root_run_id'],first.context['root_run_id'])
        self.assertEqual(usage['budget_root_run_id'],self.args['batch_id'])
        self.assertEqual(usage['control_scope_id'],'openai')
        self.assertEqual(usage['model_calls'],2)
        self.assertEqual(usage['scope_model_calls'],1)
        self.assertEqual(usage['real_model_calls'],0)
        self.assertIsNone(usage['cost_usd'])
        self.assertEqual(Decimal(usage['synthetic_cost_usd']),Decimal('.08'))
        second.guard_action()
        self.assertEqual(self.case.service.read_run_result(first.context_ref),result)

    def test_explicit_gap_delivery_keeps_unknown_batch_reservation(self):
        first=self.journal('openai');second=self.journal('claude')
        self.request(second,'unknown',cost=False)
        response=self.case.service.deliver(first.context_ref,
            dict(needs=[dict(need_id='need-1',status='unresolved',result_refs=[],gaps=['More source evidence needed'])]),
            state=self.case.state('deliver',context=first.context_ref),request_key='explicit-gap')
        result=first.finish(failure(first.profile)|dict(delivery=response))
        self.assertEqual(result['kind'],'delivery');self.assertEqual(result['status'],'partial')
        self.assertTrue(result['reconciliation_required'])
        usage=response['delivery']['usage']
        self.assertEqual(Decimal(usage['unknown_cost_reserved_usd']),Decimal('.8'))
        self.assertEqual(usage['scope_model_calls'],0)
        self.assertEqual(usage['unknown_requests'],1)
        self.assertIsNone(usage['cost_usd'])
        self.assertEqual(self.case.service.read_run_result(first.context_ref),result)

    def test_explicit_recovery_is_scoped_and_preserves_original_native_identity(self):
        first=self.journal('openai');second=self.journal('claude')
        identity=first.state()['native_session_id']
        self.request(second,'active',finish=False)
        recovered=self.journal('openai',recover=True)
        self.assertEqual(recovered.state()['native_session_id'],identity)
        self.assertEqual(recovered.cached['kind'],'recovery_required')
        self.assertEqual(second.budget.inspect_request('active')['stage'],'dispatched')

    def test_gateway_cannot_use_zero_cost_offline_metering(self):
        journal=self.journal('openai')
        with self.assertRaises(CatalogError):journal.prepare_model({'synthetic':'request'})
        with self.assertRaises(CatalogError):journal.record_model('unknown',{},complete=True)
        self.assertEqual(journal.budget.summary()['requests'],0)

    def test_changed_context_profile_scope_and_limits_do_not_create_native_state(self):
        scope=self.args['scopes'][0]
        for binding,profile,limits in [
                (self.bindings['claude'],scope['profile'],LIMITS),
                (self.bindings['openai'],scope['profile']|{'model_id':'other'},LIMITS),
                (self.bindings['openai'],scope['profile'],LIMITS|{'max_model_requests':3})]:
            with self.subTest(binding=binding['scope_id']),self.assertRaises(CatalogError):
                RuntimeJournal(self.case.service,scope['context_ref'],profile,limits,gateway_binding=binding)
        self.assertNotIn('native_execution',Session(self.case.catalog,scope['context_ref']).data)

    def test_missing_enabled_ledger_and_ready_marker_are_never_recreated(self):
        journal=self.journal('openai');self.request(journal,'paid')
        ledger=journal.budget.path;ready=ledger.parent/'ready.json'
        original=ledger.read_bytes();ledger.unlink();ready.unlink()
        with self.assertRaises(CatalogError):create_gateway_batch(self.case.catalog,**self.args,recover=True)
        self.assertFalse(ledger.exists());self.assertFalse(ready.exists())
        self.assertTrue(original)

    def test_corrupt_ledger_is_not_replaced_by_its_initial_image(self):
        journal=self.journal('openai');journal.budget.path.write_bytes(b'corrupt retained ledger')
        with self.assertRaises(CatalogError):create_gateway_batch(self.case.catalog,**self.args,recover=True)
        self.assertEqual(journal.budget.path.read_bytes(),b'corrupt retained ledger')

    def test_missing_business_root_claim_cannot_be_silently_adopted(self):
        journal=self.journal('openai');journal.finish(failure(journal.profile))
        session=journal.session();del session.data['root_budget'];session.save()
        with self.assertRaises(CatalogError):self.journal('openai',recover=True)

    def test_changed_ready_claim_cannot_rebind_a_completed_native_session(self):
        journal=self.journal('openai');journal.finish(failure(journal.profile))
        session=journal.session();original=deepcopy(session.data['root_budget'])
        for change in ({'status':'pending'},{'native_session_id':str(uuid.uuid4())},{'context_ref':'different-context'}):
            with self.subTest(change=change):
                session=journal.session();session.data['root_budget']=deepcopy(original)
                session.data['root_budget']['initialization'].update(change);session.save()
                with self.assertRaises(CatalogError):self.journal('openai',recover=True)

    def test_changed_frozen_batch_limit_rejected_without_mutation(self):
        journal=self.journal('openai');self.request(journal,'paid')
        before=journal.budget.path.read_bytes()
        with self.assertRaises(CatalogError):create_gateway_batch(self.case.catalog,**(self.args|{'max_requests':5}))
        self.assertEqual(journal.budget.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
