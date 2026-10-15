"""Actual official Runner/Chat client, synthetic HTTP, shared durable business tools."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.openai_runtime import run_gateway
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_batch import load_gateway_binding
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.service import DataService
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, reconcile_response, record_response, response_bytes
from uteki.infrastructure.run_budget import RequestRecoveryRequired

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayOpenAITests(unittest.IsolatedAsyncioTestCase):
    def setup_case(self,case_id='G01-normal',**options):
        case,args,bindings=F['fixture'](case_id,**options);self.addCleanup(case.doCleanups)
        return case,args,bindings

    async def run_case(self,service,scope,binding,endpoint,**options):
        return await run_gateway(service,scope['context_ref'],F['profile']('openai'),gateway_binding=binding,
            endpoint=endpoint,credential='uteki-synthetic-gateway',limits=scope['limits'],**options)

    def evidence(self,name,case,args,result,peer):
        folder=os.environ.get('UTEKI_GATEWAY_OPENAI_EVIDENCE')
        if folder:
            path=Path(folder);path.mkdir(parents=True,exist_ok=True)
            native=Session(case.catalog,args['scopes'][0]['context_ref']).data['native_execution']
            budget=load_gateway_binding(Session(case.catalog,args['scopes'][0]['context_ref']),
                native['binding']['gateway'],args['scopes'][0]['profile'],args['scopes'][0]['limits'])['budget']
            (path/(name+'.json')).write_text(json.dumps(dict(result=result,native=native,
                requests=budget.inspect_requests(),peer_requests=[json.loads(r) for r in peer.requests],
                peer_responses=[json.loads(r) for r in peer.responses],peer_errors=peer.errors),indent=2)+'\n')

    async def test_actual_chat_client_and_runner_deliver_from_eight_shared_tool_requests(self):
        case,args,bindings=self.setup_case();scope=args['scopes'][0]
        with F['ChatPeer']() as peer:
            result=await self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint)
            self.evidence('normal',case,args,result,peer)
            self.assertEqual(result['status'],'completed',result)
            self.assertTrue(result['native_success']);self.assertEqual(len(peer.requests),8,peer.errors)
            self.assertEqual(result['mode'],'gateway_synthetic');self.assertEqual(result['real_model_calls'],0)
            self.assertEqual(result['runtime']['control_scope']['request_stages'],{'responded':8})
            self.assertEqual(Decimal(result['delivery']['delivery']['usage']['synthetic_cost_usd']),Decimal('.08'))
            self.assertFalse(result['reconciliation_required'])
            self.assertTrue(result['delivery']['delivery']['evidence'])
            self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
            for request in map(json.loads,peer.requests):
                self.assertEqual(request['messages'][0]['content'],F['profile']('openai').text)
                self.assertEqual(request['model'],scope['profile']['model_id'])
                self.assertEqual(len(request['tools']),8)
            self.assertEqual(await self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint),result)
            self.assertEqual(len(peer.requests),8)

    async def test_missing_usage_keeps_raw_response_and_stops_before_business_tools(self):
        case,args,bindings=self.setup_case('G05-missing-usage');scope=args['scopes'][0]
        with F['ChatPeer'](missing_usage=True) as peer:
            result=await self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint)
            self.evidence('missing-usage',case,args,result,peer)
            self.assertEqual(len(peer.requests),1)
            self.assertEqual(result['kind'],'recovery_required',result)
            self.assertEqual(result['runtime']['budget']['cost']['unknown_reserved_usd'],'0.8')
            self.assertEqual(Session(case.catalog,scope['context_ref']).data['operations'],{})

    async def test_withheld_billing_blocks_other_scope_and_reconciles_without_resending(self):
        case,args,bindings=self.setup_case('G05-missing-usage');scope=args['scopes'][0]
        def withhold(*values,**options):return record_response(*values,**options,withhold_billing=True)
        with F['ChatPeer']() as peer,patch('uteki.data_platform.agent.providers.gateway_http.record_response',side_effect=withhold):
            result=await self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint)
            budget=load_gateway_binding(Session(case.catalog,scope['context_ref']),bindings[scope['scope_id']],scope['profile'],scope['limits'])['budget']
            record=budget.inspect_requests()[0]
            self.assertEqual(result['kind'],'recovery_required')
            self.assertTrue(record['response_event']['response']['billing_observation_withheld'])
            self.assertEqual(response_bytes(record['response_event']['response']['http']),peer.responses[0])
            self.assertEqual(json.loads(peer.responses[0])['usage']['cost'],.01)
            with self.assertRaises(RequestRecoveryRequired):
                budget.prepare_request('other-kernel-attempt',{'synthetic':'probe'},reserve_usd='.8',scope_id=args['scopes'][1]['scope_id'])
            bill=capture_response('generation',200,[('Content-Type','application/json')],
                [json.dumps(dict(data=dict(id=json.loads(peer.responses[0])['id'],total_cost=.01))).encode()],max_bytes=1000)
            reconcile_response(budget,record['request_key'],bill,origin='synthetic')
            self.assertEqual(budget.summary()['unknown_requests'],0)
            self.assertEqual(budget.summary()['held_usd'],'0')
            self.assertEqual(Decimal(budget.inspect_root()['cost']['known_billed_usd']),Decimal('.01'))
            self.assertEqual(len(peer.requests),1);self.assertEqual(budget.summary()['requests'],1)
            self.evidence('withheld-billing',case,args,result,peer)

    async def test_cancel_after_dispatch_retains_unknown_cost_and_no_business_action(self):
        case,args,bindings=self.setup_case('G04-cancel');scope=args['scopes'][0]
        with F['ChatPeer'](hold_response=True) as peer:
            task=asyncio.create_task(self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint))
            self.assertTrue(await asyncio.to_thread(peer.received.wait,10),'dispatch boundary was not reached')
            task.cancel()
            result=await asyncio.wait_for(task,5)
            peer.release.set()
            self.evidence('cancel',case,args,result,peer)
            self.assertEqual(result['status'],'cancelled',result)
            self.assertEqual(len(peer.requests),1)
            self.assertEqual(result['runtime']['control_scope']['stop_reason'],'cancelled')
            self.assertIsNone(result['runtime']['budget']['stop_reason'])
            self.assertEqual(result['runtime']['budget']['cost']['unknown_reserved_usd'],'0.8')
            self.assertTrue(result['reconciliation_required'])
            self.assertEqual({o['tool'] for o in Session(case.catalog,scope['context_ref']).data['operations'].values()},{'deliver'})

    async def test_schema_valid_tool_error_crosses_next_native_input_without_false_delivery(self):
        from uteki.data_platform.application.tools import ToolExecution
        case,args,bindings=self.setup_case('G03-tool-error');scope=args['scopes'][0]
        original=ToolExecution.execute;injected=[]
        def fail_first(executor,operation_id):
            if executor.tool=='find_assets' and not injected:
                injected.append(operation_id)
                raise CatalogError('CAPABILITY_UNSUPPORTED','Controlled synthetic source tool error')
            return original(executor,operation_id)
        with F['ChatPeer'](stop_after_error=True) as peer,patch.object(ToolExecution,'execute',fail_first):
            result=await self.run_case(case.service,scope,bindings[scope['scope_id']],peer.endpoint)
            self.evidence('tool-error',case,args,result,peer)
            self.assertEqual(len(injected),1)
            self.assertEqual(len(peer.requests),2)
            self.assertEqual(result['kind'],'failed',result)
            self.assertIsNone(result['delivery'])
            outputs=[json.loads(m['content']) for m in json.loads(peer.requests[-1])['messages'] if m['role']=='tool']
            self.assertEqual(outputs[0]['error']['code'],'CAPABILITY_UNSUPPORTED')
            self.assertIn('Controlled synthetic',outputs[0]['error']['message'])

    async def test_synthetic_binding_cannot_be_used_to_reach_an_external_endpoint(self):
        case,args,bindings=self.setup_case();scope=args['scopes'][0]
        result=await self.run_case(case.service,scope,bindings[scope['scope_id']],'https://openrouter.ai/api')
        self.assertEqual(result['kind'],'failed')
        self.assertIn('synthetic_wire_requires_loopback',result['error'])
        self.assertEqual(result['runtime']['budget']['request_stages'],{})

    async def test_real_origin_rejects_current_unapproved_contract_before_network(self):
        case,args,bindings=self.setup_case(origin='openrouter');scope=args['scopes'][0]
        with patch('uteki.data_platform.agent.providers.gateway_http.http.client.HTTPSConnection',
                   side_effect=AssertionError('unapproved execution must not open a connection')) as connection:
            result=await self.run_case(case.service,scope,bindings[scope['scope_id']],'https://openrouter.ai/api',
                execution_contract=F['CONTRACT'])
        connection.assert_not_called()
        self.assertEqual(result['kind'],'failed')
        self.assertIn('gateway_execution_contract_not_authorized_or_not_admitted',result['error'])
        self.assertEqual(result['runtime']['budget']['request_stages'],{})
        self.assertEqual(result['real_model_calls'],0)

    async def test_observed_exit_resumes_original_sdk_state_without_repeating_http_or_tools(self):
        for phase in ('gateway_request_prepared','gateway_response_committed','native_tool_response_committed'):
            with self.subTest(phase=phase),F['ChatPeer']() as peer:
                case,args,bindings=self.setup_case('G02-resume');scope=args['scopes'][0]
                spec=case.root/'gateway-worker.json'
                spec.write_text(json.dumps(dict(context_ref=scope['context_ref'],binding=bindings[scope['scope_id']],
                    limits=scope['limits'],endpoint=peer.endpoint)))
                case.catalog.close()
                with (case.root/'gateway-worker.log').open('w') as log:
                    worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_openai_worker.py'),
                        str(case.root),str(spec),phase],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                    observed=worker.wait(timeout=30)
                self.assertEqual(observed['returncode'],89,(case.root/'gateway-worker.log').read_text())
                self.assertTrue(observed['process_group_empty'])
                with Catalog.open(case.root) as catalog:
                    before=deepcopy(Session(catalog,scope['context_ref']).data)
                    worker.record(catalog,scope['context_ref'])
                    result=await self.run_case(DataService(catalog),scope,bindings[scope['scope_id']],peer.endpoint,recover=True)
                    original_catalog=case.catalog;case.catalog=catalog
                    try:self.evidence(phase,case,args,result,peer)
                    finally:case.catalog=original_catalog
                    self.assertEqual(result['status'],'completed',result)
                    self.assertEqual(result['runtime']['native_session_id'],before['native_execution']['native_session_id'])
                    self.assertEqual(len(peer.requests),8,peer.errors)
                    self.assertEqual(result['runtime']['control_scope']['request_stages'],{'responded':8})
                    after=Session(catalog,scope['context_ref']).data
                    for key,value in before['operations'].items():self.assertEqual(after['operations'][key],value)

    async def test_unknown_dispatch_and_missing_sdk_response_do_not_restart_requests(self):
        for phase,damage in [('gateway_request_dispatched',False),('native_tool_response_committed',True)]:
            with self.subTest(phase=phase),F['ChatPeer']() as peer:
                case,args,bindings=self.setup_case('G02-resume');scope=args['scopes'][0]
                spec=case.root/'gateway-worker.json'
                spec.write_text(json.dumps(dict(context_ref=scope['context_ref'],binding=bindings[scope['scope_id']],
                    limits=scope['limits'],endpoint=peer.endpoint)))
                case.catalog.close()
                with (case.root/'gateway-worker.log').open('w') as log:
                    worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_openai_worker.py'),
                        str(case.root),str(spec),phase],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                    observation=worker.wait(timeout=30)
                self.assertEqual(observation['returncode'],89,(case.root/'gateway-worker.log').read_text())
                sent=len(peer.requests)
                with Catalog.open(case.root) as catalog:
                    before=deepcopy(Session(catalog,scope['context_ref']).data)
                    worker.record(catalog,scope['context_ref'])
                    if damage:
                        reference=ObjectRef.model_validate(before['native_execution']['openai_requests'][0]['response_ref'])
                        catalog.content._path(reference).unlink()
                    result=await self.run_case(DataService(catalog),scope,bindings[scope['scope_id']],peer.endpoint,recover=True)
                    original_catalog=case.catalog;case.catalog=catalog
                    try:self.evidence('missing-sdk-response' if damage else 'unknown-dispatch',case,args,result,peer)
                    finally:case.catalog=original_catalog
                    self.assertEqual(result['kind'],'recovery_required',result)
                    self.assertEqual(len(peer.requests),sent)
                    self.assertEqual(Session(catalog,scope['context_ref']).data['operations'],before['operations'])
                    if not damage:
                        self.assertEqual(result['runtime']['budget']['cost']['unknown_reserved_usd'],'0.8')
                        self.assertEqual(sent,0)

    async def test_changed_wire_reconstruction_is_recovery_required_without_resending(self):
        import httpx2
        from uteki.data_platform.agent.providers.gateway_openai import _Transport
        case,args,bindings=self.setup_case('G02-resume');scope=args['scopes'][0]
        with F['ChatPeer']() as peer:
            spec=case.root/'gateway-worker.json'
            spec.write_text(json.dumps(dict(context_ref=scope['context_ref'],binding=bindings[scope['scope_id']],
                limits=scope['limits'],endpoint=peer.endpoint)))
            case.catalog.close()
            with (case.root/'gateway-worker.log').open('w') as log:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_openai_worker.py'),
                    str(case.root),str(spec),'gateway_response_committed'],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                observation=worker.wait(timeout=30)
            self.assertEqual(observation['returncode'],89,(case.root/'gateway-worker.log').read_text())
            original=_Transport.handle_async_request
            async def changed(transport,request):
                altered=httpx2.Request(request.method,request.url,headers=request.headers,content=request.content+b' ')
                return await original(transport,altered)
            with Catalog.open(case.root) as catalog,patch.object(_Transport,'handle_async_request',changed):
                worker.record(catalog,scope['context_ref'])
                result=await self.run_case(DataService(catalog),scope,bindings[scope['scope_id']],peer.endpoint,recover=True)
                original_catalog=case.catalog;case.catalog=catalog
                try:self.evidence('changed-wire',case,args,result,peer)
                finally:case.catalog=original_catalog
                self.assertEqual(len(peer.requests),1)
                self.assertEqual(result['kind'],'recovery_required',result)


if __name__=='__main__':unittest.main()
