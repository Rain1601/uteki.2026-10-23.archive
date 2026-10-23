"""Fresh SDK sessions keep the old lane's money, stops and request count."""
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest

from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response
from uteki.data_platform.application.gateway_batch import load_gateway_binding, prepare_gateway_attempt
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.run_completion import read_result
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.application.run_budget import BudgetExceeded, RequestRecoveryRequired

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))
FAILURE=dict(kind='failed',status='failed',error='synthetic prior failure',native_success=False,
    delivery=None,committed_delivery=None,clarification=None,committed_clarification=None,
    native_events=[],tool_events=[],mode='offline',real_model_calls=0,gateway_cost_usd=None)


class GatewayAttemptTests(unittest.TestCase):
    def setup_case(self,kernel='openai'):
        case,args,bindings=F['fixture'](profile_overrides={
            'openai':{'sdk_version':'0.22.2'},'claude':{'sdk_version':'0.2.166'}})
        self.addCleanup(case.doCleanups)
        scope=next(s for s in args['scopes'] if s['profile']['kernel']==kernel)
        binding=bindings[scope['scope_id']]
        old=Session(case.catalog,scope['context_ref'])
        budget=load_gateway_binding(old,binding,scope['profile'],scope['limits'])['budget']
        return case,scope,binding,budget

    def record(self,budget,scope,key,*,known=True,dispatch_only=False):
        budget.prepare_request(key,dict(context_ref=scope['context_ref'],profile=scope['profile']),
            reserve_usd='.8',scope_id=scope['scope_id'])
        budget.begin_request(key)
        if dispatch_only:return
        payload=dict(id='gen-synthetic-'+key,object='chat.completion',choices=[dict(finish_reason='stop')],
            usage={'cost':.01} if known else {})
        record_response(budget,key,capture_response('chat_completions',200,[('Content-Type','application/json')],
            [json.dumps(payload).encode()],max_bytes=10000),origin='synthetic')
        self.assertTrue(budget.inspect_request(key)['response_event']['response']['complete'])

    def native(self,kernel,*,retain_unknown_bill=False):
        case,scope,binding,budget=self.setup_case(kernel)
        journal=RuntimeJournal(case.service,scope['context_ref'],scope['profile'],scope['limits'],gateway_binding=binding)
        self.record(budget,scope,'prior',known=not retain_unknown_bill)
        if retain_unknown_bill:
            budget.retain_response_reservation('prior',confirmation='Synthetic approval to retain full reservation.')
        original_result=journal.finish(FAILURE | {'profile':scope['profile']})
        prior=Session(case.catalog,scope['context_ref']);old_head=prior.head_ref
        old_ledger=budget.inspect_root();original_request=budget.inspect_request('prior')
        profile=F['profile'](kernel).metadata()
        attempt=prepare_gateway_attempt(case.catalog,binding,profile,request_key=kernel+'-current-sdk')
        self.assertEqual(attempt,prepare_gateway_attempt(case.catalog,binding,profile,request_key=kernel+'-current-sdk'))
        self.assertEqual(budget.inspect_root(),old_ledger)
        case.catalog.close()
        peer_type=F['ChatPeer'] if kernel=='openai' else F['MessagesPeer']
        with tempfile.TemporaryDirectory(prefix='uteki-new-sdk-') as temporary,peer_type() as peer:
            work=Path(temporary)
            env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=peer.endpoint,
                ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-gateway-worker',
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',
                HTTP_PROXY=peer.endpoint,HTTPS_PROXY=peer.endpoint,ALL_PROXY=peer.endpoint,NO_PROXY='127.0.0.1,localhost')
            spec=dict(root=str(case.root),kernel=kernel,**attempt,limits=scope['limits'],
                      endpoint=peer.endpoint,output=str(work/'result.json'))
            path=work/'spec.json';path.write_text(json.dumps(spec))
            process=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_batch_sdk_worker.py'),
                str(path)],cwd=work,env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads((work/'result.json').read_text())
            self.assertEqual(result['status'],'completed',result)
            self.assertEqual(len(peer.requests),8,peer.errors)
            self.assertEqual(peer.errors,[])
            self.assertTrue(result['delivery']['delivery']['evidence'])
            self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
            with Catalog.open(case.root) as catalog:
                old=Session(catalog,scope['context_ref']);new=Session(catalog,attempt['context_ref'])
                self.assertEqual(old.head_ref,old_head)
                self.assertEqual(read_result(old),original_result)
                self.assertNotEqual(old.data['native_execution']['native_session_id'],new.data['native_execution']['native_session_id'])
                loaded=load_gateway_binding(new,attempt['binding'],profile,scope['limits'])
                self.assertEqual(loaded['budget'].path,budget.path)
                self.assertEqual(loaded['budget'].inspect_request('prior'),original_request)
                self.assertEqual(loaded['budget'].inspect_scope(scope['scope_id'])['request_stages'],{'responded':9})
                self.assertEqual(Decimal(loaded['budget'].inspect_root()['cost']['known_billed_usd']),
                    Decimal('.08') if retain_unknown_bill else Decimal('.09'))
                self.assertEqual(Decimal(loaded['budget'].summary()['held_usd']),
                    Decimal('.8') if retain_unknown_bill else Decimal('0'))
                self.assertEqual(read_result(new),result)
                self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)
                records=loaded['budget'].inspect_requests()
                self.assertEqual(len([r for r in records if r['request'].get('context_ref')==attempt['context_ref']]),8)
                if os.environ.get('UTEKI_ATTEMPT_EVIDENCE'):
                    output=Path(os.environ['UTEKI_ATTEMPT_EVIDENCE']);output.mkdir(parents=True,exist_ok=True)
                    with (output/(kernel+'.json')).open('x') as stream:
                        json.dump(dict(result=result,prior_request=original_request,requests=records,
                            old_result_unchanged=True,shared_ledger=True,real_model_calls=0),stream,indent=2)

    def test_openai_current_sdk_fresh_session_keeps_prior_cost_and_result(self):self.native('openai')

    def test_claude_current_sdk_fresh_session_keeps_prior_cost_and_result(self):self.native('claude')

    def test_acknowledged_bill_allows_new_native_chain_without_releasing_reservation(self):
        self.native('openai',retain_unknown_bill=True)

    def test_unknown_bill_and_unknown_dispatch_are_not_bypassed(self):
        case,scope,binding,budget=self.setup_case()
        self.record(budget,scope,'unknown',known=False)
        before=budget.inspect_root()
        attempt=prepare_gateway_attempt(case.catalog,binding,F['profile']('openai').metadata(),request_key='new')
        self.assertEqual(budget.inspect_root(),before)
        with self.assertRaises(RequestRecoveryRequired):
            budget.prepare_request('blocked',dict(context_ref=attempt['context_ref']),reserve_usd='.1',scope_id=scope['scope_id'])
        self.assertEqual(budget.inspect_root(),before)
        second,scope2,binding2,budget2=self.setup_case()
        self.record(budget2,scope2,'dispatched',dispatch_only=True)
        with self.assertRaisesRegex(CatalogError,'pending or uncertain'):
            prepare_gateway_attempt(second.catalog,binding2,F['profile']('openai').metadata(),request_key='blocked')

    def test_original_stop_and_remaining_request_cap_are_enforced(self):
        case,scope,binding,budget=self.setup_case()
        for index in range(9):self.record(budget,scope,str(index))
        attempt=prepare_gateway_attempt(case.catalog,binding,F['profile']('openai').metadata(),request_key='last')
        self.record(budget,scope | {'context_ref':attempt['context_ref']},'last')
        with self.assertRaises(BudgetExceeded):
            budget.prepare_request('eleventh',{'synthetic':True},reserve_usd='.1',scope_id=scope['scope_id'])
        with self.assertRaisesRegex(CatalogError,'exhausted'):
            prepare_gateway_attempt(case.catalog,binding,F['profile']('openai').metadata(),request_key='no-reset')
        budget.stop_scope(scope['scope_id'],'cancelled')
        with self.assertRaisesRegex(CatalogError,'stopped'):
            prepare_gateway_attempt(case.catalog,binding,F['profile']('openai').metadata(),request_key='no-reopen')

    def test_changed_input_route_limits_or_missing_attempt_fail_closed(self):
        case,scope,binding,budget=self.setup_case()
        profile=F['profile']('openai').metadata()
        with self.assertRaisesRegex(ValueError,'model, route, prompt'):
            prepare_gateway_attempt(case.catalog,binding,profile | {'model_id':'other-model'},request_key='wrong-model')
        attempt=prepare_gateway_attempt(case.catalog,binding,profile,request_key='current')
        new=Session(case.catalog,attempt['context_ref'])
        with self.assertRaises(CatalogError):load_gateway_binding(new,binding,profile,scope['limits'])
        with self.assertRaises(CatalogError):
            load_gateway_binding(new,attempt['binding'],profile,scope['limits'] | {'max_model_requests':11})
        invalid=deepcopy(attempt['binding']);invalid['scope_id']='claude-G01-normal'
        with self.assertRaises(CatalogError):load_gateway_binding(new,invalid,profile,scope['limits'])
        # An unregistered object with valid content addressing is not an accepted attempt.
        from uteki.data_platform.contracts.content import ObjectRef
        value=json.loads(case.catalog.content.read_object(ObjectRef.model_validate(attempt['binding']['attempt_ref'])))
        value['policy']['context_sha256']='0'*64
        invalid=attempt['binding'] | {'attempt_ref':case.catalog.content.put_object(canonical(value)).model_dump(mode='json')}
        with self.assertRaises(CatalogError):load_gateway_binding(new,invalid,profile,scope['limits'])

    def test_larger_request_bound_keeps_original_money_count_and_history(self):
        case,scope,binding,budget=self.setup_case()
        self.record(budget,scope,'prior-size')
        before=budget.inspect_root();original_request=budget.inspect_request('prior-size')
        profile=F['profile']('openai').metadata();size=scope['limits']['max_request_bytes']+100000
        attempt=prepare_gateway_attempt(case.catalog,binding,profile,request_key='larger',max_request_bytes=size)
        self.assertEqual(attempt,prepare_gateway_attempt(case.catalog,binding,profile,request_key='larger',max_request_bytes=size))
        limits=scope['limits'] | {'max_request_bytes':size}
        loaded=load_gateway_binding(Session(case.catalog,attempt['context_ref']),attempt['binding'],profile,limits)
        kwargs=dict(endpoint='http://127.0.0.1:9999',origin='synthetic',credential='uteki-synthetic-gateway',
                    deadline=time.monotonic()+30,before_request=lambda request:None)
        old=GatewayHTTP(budget,scope['scope_id'],**kwargs)
        new=GatewayHTTP(budget,scope['scope_id'],execution_policy=loaded['execution_policy'],**kwargs)
        self.addCleanup(old.close);self.addCleanup(new.close)
        request=dict(model=profile['model_id'],max_tokens=profile['max_output_tokens'],
            provider=dict(only=profile['route']['upstream'],order=profile['route']['upstream'],allow_fallbacks=False,require_parameters=True),
            reasoning={'enabled':False},messages=[{'role':'user','content':'x'*(size-50000)}])
        raw=canonical(request)
        with self.assertRaisesRegex(ValueError,'gateway_request_exceeds_bound'):
            old.validate_request('/v1/chat/completions',raw,{})
        self.assertEqual(new.validate_request('/v1/chat/completions',raw,{}),request)
        with self.assertRaisesRegex(ValueError,'gateway_request_exceeds_bound'):
            new.validate_request('/v1/chat/completions',b'x'*(size+1),{})
        with self.assertRaises(CatalogError):
            load_gateway_binding(Session(case.catalog,attempt['context_ref']),attempt['binding'],profile,
                limits | {'max_model_requests':limits['max_model_requests']+1})
        self.assertEqual(budget.inspect_root(),before)
        self.assertEqual(budget.inspect_request('prior-size'),original_request)


if __name__=='__main__':unittest.main()
