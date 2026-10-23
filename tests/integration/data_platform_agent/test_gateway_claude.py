"""Official Claude SDK/CLI business loop against a synthetic Messages gateway."""
from decimal import Decimal
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_batch import load_gateway_binding
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayClaudeTests(unittest.TestCase):
    def scenario(self,name,*,case_id='G01-normal',peer_options=None,options=None,recover=False,reconcile=False,max_request_bytes=None,profile_overrides=None):
        case,args,bindings=F['fixture'](case_id,max_request_bytes=max_request_bytes,
            profile_overrides={'claude':profile_overrides or {}});self.addCleanup(case.doCleanups)
        scope=args['scopes'][1];case.catalog.close()
        with tempfile.TemporaryDirectory(prefix='uteki-gateway-claude-') as temp,F['MessagesPeer'](**(peer_options or {})) as peer:
            work=Path(temp)
            env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=peer.endpoint,
                ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-gateway-worker',
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(scope['profile']['max_output_tokens']),
                HTTP_PROXY=peer.endpoint,HTTPS_PROXY=peer.endpoint,ALL_PROXY=peer.endpoint,NO_PROXY='127.0.0.1,localhost')
            spec=dict(root=str(case.root),context_ref=scope['context_ref'],binding=bindings[scope['scope_id']],
                endpoint=peer.endpoint,limits=scope['limits'],output=str(work/'result.json'),
                profile_overrides=profile_overrides,**(options or {}))
            attempts=[]
            def execute(spec):
                path=work/'spec.json';path.write_text(json.dumps(spec))
                stdout_path=work/f'stdout-{len(attempts)}';stderr_path=work/f'stderr-{len(attempts)}'
                with stdout_path.open('w') as stdout,stderr_path.open('w') as stderr:
                    watcher=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_claude_worker.py'),str(path)],
                        env=env,cwd=work,stdout=stdout,stderr=stderr)
                    observed=watcher.wait(timeout=45)
                with Catalog.open(case.root) as catalog:
                    native=Session(catalog,scope['context_ref']).data['native_execution']
                    owned=[a for a in native.get('recovery_attempts',[]) if a['owner_pid']==watcher.child.pid]
                    if native['owner_pid']==watcher.child.pid or any(a['status']=='active' for a in owned):
                        watcher.record(catalog,scope['context_ref'])
                    else:
                        # A recovery-only worker can finish its own clock while
                        # leaving the original native owner unchanged. It must
                        # not attach an exit receipt to that original owner.
                        self.assertEqual(watcher.child.returncode,0)
                        self.assertTrue(owned,native)
                        self.assertTrue(all(a['status']=='completed' for a in owned),owned)
                attempts.append(dict(exit_code=watcher.child.returncode,observation=observed,
                    cleanup=watcher.cleanup,stdout=stdout_path.read_text(),stderr=stderr_path.read_text()))
                return watcher.child.returncode
            first=execute(spec)
            if recover:
                self.assertEqual(first,89,attempts)
                with Catalog.open(case.root) as catalog:
                    session=Session(catalog,scope['context_ref']);before=session.data
                    if reconcile:
                        budget=load_gateway_binding(session,bindings[scope['scope_id']],scope['profile'],scope['limits'])['budget']
                        wire=GatewayHTTP(budget,scope['scope_id'],endpoint=peer.endpoint,origin='synthetic',
                            credential='uteki-synthetic-gateway',deadline=time.monotonic()+10,before_request=lambda req:None)
                        try:wire.observe_bill(budget.inspect_requests()[0]['request_key'])
                        finally:wire.close()
                spec.pop('stop_phase',None);spec['recover']=True
                last=execute(spec)
            else:before=None;last=first
            result=json.loads((work/'result.json').read_text()) if (work/'result.json').exists() else None
            with Catalog.open(case.root) as catalog:
                session=Session(catalog,scope['context_ref'])
                budget=load_gateway_binding(session,bindings[scope['scope_id']],scope['profile'],scope['limits'])['budget']
                records=budget.inspect_requests()
                evidence=dict(result=result,native=session.data.get('native_execution'),before=before,
                    operations=session.data['operations'],requests=records,
                    billing_observations={r['request_key']:budget.inspect_billing_observations(r['request_key']) for r in records},
                    peer_requests=[json.loads(r) for r in peer.requests],peer_responses=[r.decode() for r in peer.responses],
                    lookups=peer.lookups,peer_errors=peer.errors,attempts=attempts)
            if os.environ.get('UTEKI_GATEWAY_CLAUDE_EVIDENCE'):
                output=Path(os.environ['UTEKI_GATEWAY_CLAUDE_EVIDENCE']);output.mkdir(parents=True,exist_ok=True)
                (output/(name+'.json')).write_text(json.dumps(evidence,indent=2)+'\n')
            self.assertEqual(last,0,attempts)
            return evidence

    def test_native_size_rejection_is_retained_as_api_error_not_session_corruption(self):
        evidence=self.scenario('request-size-error',max_request_bytes=100)
        result=evidence['result']
        self.assertEqual(result['kind'],'failed')
        self.assertIn('request_too_large',result['error'])
        self.assertNotIn('assistant audit failed',result['error'])
        self.assertEqual(evidence['requests'],[])
        self.assertEqual(evidence['peer_requests'],[])
        errors=[e for e in result['native_events'] if e['type']=='AssistantMessage' and e['data'].get('error')]
        self.assertTrue(errors)
        blocked=[e for e in result['native_events'] if e['type']=='native_transport'][0]['requests']
        self.assertTrue(all(e['request_bytes']>100 and e['error_code']=='request_too_large' for e in blocked))

    def test_native_non_anthropic_model_has_frozen_routing_and_original_receipt(self):
        import base64
        overrides=dict(model_id='openai/gpt-5.6-luna',max_output_tokens=8192,
            route=dict(provider='openrouter',protocol='anthropic_messages',upstream=['openai'],
                       allow_fallbacks=False,require_parameters=True),
            reasoning_effort='low',request_controls={'output_config':{'effort':'low'}})
        evidence=self.scenario('non-anthropic-route',profile_overrides=overrides)
        self.assertEqual(evidence['result']['status'],'completed',evidence['result'])
        self.assertEqual(len(evidence['peer_requests']),8)
        for request in evidence['peer_requests']:
            self.assertEqual(request['model'],overrides['model_id'])
            self.assertEqual(request['max_tokens'],8192)
            self.assertEqual(request['provider'],dict(only=['openai'],order=['openai'],
                allow_fallbacks=False,require_parameters=True))
            self.assertEqual(request['output_config'],{'effort':'low'})
            self.assertNotIn('root-cause-first',json.dumps(request))
        for receipt in evidence['requests']:
            metadata=receipt['request']
            native=json.loads(base64.b64decode(metadata['native_http_body_base64']))
            wire=json.loads(base64.b64decode(metadata['body_base64']))
            self.assertNotIn('provider',native)
            self.assertEqual(native,{k:v for k,v in wire.items() if k!='provider'})

    def test_native_business_loop_bills_each_original_response_and_replays_delivery(self):
        evidence=self.scenario('normal',options={'replay':True});result=evidence['result']
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['native_success']);self.assertEqual(len(evidence['peer_requests']),8)
        self.assertEqual(len(evidence['lookups']),8);self.assertEqual(len(evidence['requests']),8)
        self.assertEqual(result['mode'],'gateway_synthetic');self.assertEqual(result['real_model_calls'],0)
        self.assertEqual(Decimal(result['runtime']['budget']['cost']['known_billed_usd']),Decimal('.08'))
        self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
        self.assertFalse(result['reconciliation_required']);self.assertEqual(evidence['peer_errors'],[])
        for request in evidence['peer_requests']:
            self.assertEqual(request['model'],F['profile']('claude').profile.model_id)
            self.assertTrue(any(p.get('text')==F['profile']('claude').text for p in request['system']))
            self.assertEqual(len(request['tools']),8)
        exposed = json.dumps(evidence['peer_requests'][0]['tools'])
        self.assertIn('Exact name of the tool being called now',exposed)
        self.assertIn('Never copy context.clock/created_at',exposed)
        self.assertIn('UTF-8 budget for the complete response',exposed)

    def test_observed_process_exit_resumes_same_native_history_without_repeating_first_tool(self):
        evidence=self.scenario('resume',case_id='G02-resume',options={'stop_phase':'claude_post_tool'},recover=True)
        result=evidence['result'];self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(evidence['peer_requests']),8);self.assertEqual(len(evidence['lookups']),8)
        self.assertEqual(evidence['native']['native_session_id'],evidence['before']['native_execution']['native_session_id'])
        for key,value in evidence['before']['operations'].items():self.assertEqual(evidence['operations'][key],value)

    def test_missing_generation_or_bill_prevents_business_actions_and_preserves_reservation(self):
        for mode in ('missing_identity','missing_bill'):
            with self.subTest(mode=mode):
                evidence=self.scenario(mode,case_id='G05-missing-usage',peer_options={mode:True})
                result=evidence['result'];self.assertEqual(result['kind'],'recovery_required',result)
                self.assertEqual(len(evidence['peer_requests']),1)
                self.assertEqual(len(evidence['lookups']),0 if mode=='missing_identity' else 1)
                self.assertEqual(result['runtime']['budget']['cost']['unknown_reserved_usd'],'0.8')
                self.assertEqual(evidence['operations'],{})

    def test_schema_valid_tool_error_reaches_next_native_request_without_false_delivery(self):
        evidence=self.scenario('tool-error',case_id='G03-tool-error',peer_options={'stop_after_error':True},options={'tool_error':True})
        self.assertEqual(evidence['result']['status'],'failed',evidence['result'])
        self.assertEqual(len(evidence['peer_requests']),2)
        returned=[b for m in evidence['peer_requests'][1]['messages'] if isinstance(m.get('content'),list)
            for b in m['content'] if b.get('type')=='tool_result']
        self.assertEqual(len(returned),1);self.assertTrue(returned[0]['is_error'])
        self.assertIn('CAPABILITY_UNSUPPORTED',json.dumps(returned[0]))

    def test_cancel_after_durable_bill_never_executes_the_received_tool(self):
        evidence=self.scenario('cancel',case_id='G04-cancel',options={'cancel_phase':'gateway_bill_reconciled'})
        result=evidence['result'];self.assertEqual(result['status'],'cancelled',result)
        self.assertEqual(len(evidence['peer_requests']),1);self.assertEqual(len(evidence['lookups']),1)
        self.assertFalse(result['reconciliation_required'])
        self.assertEqual({o['tool'] for o in evidence['operations'].values()},{'deliver'})

    def test_process_exit_after_billing_receipt_reconciles_without_get_or_model_replay(self):
        evidence=self.scenario('billing-receipt-exit',case_id='G02-resume',
            options={'stop_phase':'gateway_billing_observation_committed'},recover=True,reconcile=True)
        self.assertEqual(evidence['result']['kind'],'recovery_required',evidence['result'])
        self.assertEqual(len(evidence['peer_requests']),1);self.assertEqual(len(evidence['lookups']),1)
        self.assertEqual(evidence['requests'][0]['cost_state'],'settled')
        self.assertEqual(evidence['operations'],{})

    def test_process_exit_after_dispatch_does_not_resend_unknown_native_request(self):
        evidence=self.scenario('dispatch-exit',case_id='G02-resume',
            options={'stop_phase':'gateway_request_dispatched'},recover=True)
        self.assertEqual(evidence['result']['kind'],'recovery_required',evidence['result'])
        self.assertEqual(evidence['peer_requests'],[]);self.assertEqual(evidence['lookups'],[])
        self.assertEqual(evidence['requests'][0]['stage'],'outcome_unknown')
        self.assertEqual(evidence['requests'][0]['cost_state'],'unknown')
