"""The frozen ten scenarios run sequentially with one shared cost ledger."""
from decimal import Decimal
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest

from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_batch import load_gateway_binding
from uteki.data_platform.application.gateway_supervisor import GatewaySupervisor
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService
from uteki.infrastructure.run_budget import RequestRecoveryRequired

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayBatchNativeTests(unittest.TestCase):
    def test_both_native_kernels_execute_frozen_five_cases_in_one_batch(self):
        case,args,bindings=F['fixture'](all_cases=True);self.addCleanup(case.doCleanups)
        self.assertEqual(len(args['scopes']),10)
        self.assertEqual(args['max_requests'],F['CONTRACT']['execution']['max_physical_requests_total'])
        self.assertEqual(len({s['context_ref'] for s in args['scopes']}),10)
        output=Path(os.environ['UTEKI_GATEWAY_BATCH_EVIDENCE']) if os.environ.get('UTEKI_GATEWAY_BATCH_EVIDENCE') else None
        if output:output.mkdir(parents=True,exist_ok=True)
        frozen=dict(args=args,bindings=bindings,contexts={s['scope_id']:Session(case.catalog,s['context_ref']).data['context'] for s in args['scopes']})
        if output:(output/'frozen-before-dispatch.json').write_text(json.dumps(frozen,indent=2)+'\n')
        case.catalog.close();reports=[];deadline=time.monotonic()+F['CONTRACT']['execution']['batch_execution_seconds']
        try:
            for scope in args['scopes']:
                kernel=scope['profile']['kernel'];name=scope['scope_id'];case_id=name.removeprefix(kernel+'-')
                peer_class=F['ChatPeer'] if kernel=='openai' else F['MessagesPeer']
                with tempfile.TemporaryDirectory(prefix='uteki-shared-native-') as temporary,peer_class(stop_after_error=case_id=='G03-tool-error') as peer:
                    work=Path(temporary)
                    env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                        CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=peer.endpoint,
                        ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-gateway-worker',
                        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',
                        HTTP_PROXY=peer.endpoint,HTTPS_PROXY=peer.endpoint,ALL_PROXY=peer.endpoint,NO_PROXY='127.0.0.1,localhost')
                    spec=dict(root=str(case.root),kernel=kernel,context_ref=scope['context_ref'],binding=bindings[name],
                        limits=scope['limits'],endpoint=peer.endpoint,output=str(work/'result.json'),held=str(work/'held.json'))
                    if case_id=='G02-resume':spec['stop_phase']='native_tool_response_committed' if kernel=='openai' else 'claude_post_tool'
                    if case_id=='G03-tool-error':spec['tool_error']=True
                    if case_id=='G04-cancel':spec['hold_phase']='gateway_response_committed' if kernel=='openai' else 'gateway_bill_reconciled'
                    if case_id=='G05-missing-usage':spec['withhold_billing']=True
                    attempts=[]
                    def execute():
                        with Catalog.open(case.root) as catalog:
                            supervisor=GatewaySupervisor(catalog,scope['context_ref'],bindings[name],scope['profile'],scope['limits'],batch_deadline=deadline)
                        path=work/'spec.json';path.write_text(json.dumps(spec))
                        stdout_path=work/f'stdout-{len(attempts)}';stderr_path=work/f'stderr-{len(attempts)}'
                        with stdout_path.open('w') as stdout,stderr_path.open('w') as stderr:
                            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_batch_sdk_worker.py'),str(path)],
                                cwd=work,env=env,stdout=stdout,stderr=stderr)
                            observed=supervisor.wait(worker,cancelled=(lambda:(work/'held.json').exists()) if case_id=='G04-cancel' else None)
                        with Catalog.open(case.root) as catalog:record=supervisor.record(catalog)
                        attempts.append(dict(supervision=observed,record=record,cleanup=worker.cleanup,
                            stdout=stdout_path.read_text(),stderr=stderr_path.read_text()))
                        return worker.child.returncode
                    first=execute();before=None
                    if case_id=='G02-resume':
                        self.assertEqual(first,89,attempts)
                        with Catalog.open(case.root) as catalog:before=Session(catalog,scope['context_ref']).data
                        spec.pop('stop_phase');spec['recover']=True
                        self.assertEqual(execute(),0,attempts)
                    elif case_id=='G04-cancel':
                        self.assertTrue((work/'held.json').exists(),attempts)
                        self.assertLess(first,0,attempts)
                    else:self.assertEqual(first,0,attempts)
                    with Catalog.open(case.root) as catalog:
                        session=Session(catalog,scope['context_ref'])
                        budget=load_gateway_binding(session,bindings[name],scope['profile'],scope['limits'])['budget']
                        if case_id=='G04-cancel':
                            journal=RuntimeJournal(DataService(catalog),scope['context_ref'],scope['profile'],scope['limits'],gateway_binding=bindings[name],recover=True)
                            result=journal.cached
                        else:result=json.loads((work/'result.json').read_text())
                        session=Session(catalog,scope['context_ref']);records=[r for r in budget.inspect_requests() if r.get('control_scope_id')==name]
                        bill_check=None
                        if case_id=='G05-missing-usage':
                            self.assertEqual(result['kind'],'recovery_required',result)
                            self.assertEqual(len(records),1);self.assertEqual(records[0]['cost_state'],'unknown')
                            self.assertTrue(records[0]['response_event']['response']['complete'])
                            before_bill=budget.inspect_root();count=budget.summary()['requests']
                            for target_kernel in ('openai','claude'):
                                target=next(s for s in args['scopes'] if s['profile']['kernel']==target_kernel and s['scope_id'].endswith('G05-missing-usage'))
                                with self.assertRaises(RequestRecoveryRequired):
                                    budget.prepare_request('must-not-dispatch-'+name+'-'+target_kernel,{'synthetic':'unknown-bill-probe'},reserve_usd='.8',scope_id=target['scope_id'])
                            wire=GatewayHTTP(budget,name,endpoint=peer.endpoint,origin='synthetic',credential='uteki-synthetic-gateway',
                                deadline=min(deadline,time.monotonic()+45),before_request=lambda req:None)
                            try:wire.observe_bill(records[0]['request_key'])
                            finally:wire.close()
                            self.assertEqual(budget.summary()['requests'],count)
                            bill_check=dict(before=before_bill,after=budget.inspect_root(),model_count_before=count,model_count_after=budget.summary()['requests'])
                            records=[budget.inspect_request(r['request_key']) for r in records]
                        report=dict(scope=scope,result=result,before=before,native=session.data['native_execution'],operations=session.data['operations'],
                            requests=records,ledger=budget.inspect_root(),billing_check=bill_check,attempts=attempts,
                            peer_requests=[json.loads(r) for r in peer.requests],peer_responses=[r.decode() for r in peer.responses],
                            lookups=peer.lookups,peer_errors=peer.errors)
                    reports.append(report)
                    if output:(output/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
                    expected_count=8 if case_id in {'G01-normal','G02-resume'} else 2 if case_id=='G03-tool-error' else 1
                    self.assertEqual(len(peer.requests),expected_count,report)
                    self.assertEqual(len(records),expected_count)
                    self.assertEqual(peer.errors,[])
                    if case_id in {'G01-normal','G02-resume'}:
                        self.assertEqual(result['status'],'completed',result);self.assertTrue(result['native_success'])
                        self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
                    if before is not None:
                        self.assertEqual(report['native']['native_session_id'],before['native_execution']['native_session_id'])
                        for key,value in before['operations'].items():self.assertEqual(report['operations'][key],value)
                    if case_id=='G03-tool-error':
                        self.assertEqual(result['status'],'failed');self.assertIsNone(result['delivery'])
                        self.assertIn('CAPABILITY_UNSUPPORTED',json.dumps(report['peer_requests'][1]))
                    if case_id=='G04-cancel':
                        self.assertEqual(result['status'],'cancelled',result)
                        self.assertEqual({o['tool'] for o in report['operations'].values()},{'deliver'})
                        self.assertFalse(result['reconciliation_required'])
                    self.assertTrue(all(r['cost_state']=='settled' for r in records))
                    self.assertLessEqual(Decimal(report['ledger']['cost']['known_billed_usd']),Decimal(args['limit_usd']))
                    print(name,'accepted',len(peer.requests),'model requests',flush=True)
            with Catalog.open(case.root) as catalog:
                scope=args['scopes'][0]
                budget=load_gateway_binding(Session(catalog,scope['context_ref']),bindings[scope['scope_id']],scope['profile'],scope['limits'])['budget']
                records=budget.inspect_requests();ledger=budget.inspect_root()
                self.assertEqual(len(records),40);self.assertEqual(Decimal(ledger['cost']['known_billed_usd']),Decimal('.40'))
                self.assertEqual(ledger['cost']['unknown_reserved_usd'],'0');self.assertIsNone(ledger['stop_reason'])
                self.assertEqual(len({r['bill']['receipt']['request_id'] for r in records}),40)
                self.assertEqual(len({r['native']['native_session_id'] for r in reports}),10)
                self.assertEqual(len(list((case.root/'gateway-batches').rglob('budget.sqlite'))),1)
                self.assertEqual(len(list((case.root/'runs').rglob('budget.sqlite'))),0)
                if output:(output/'batch-result.json').write_text(json.dumps(dict(status='synthetic_ten_cases_passed',batch_id=args['batch_id'],
                    execution_order=[r['scope']['scope_id'] for r in reports],ledger=ledger,request_count=len(records),
                    scopes=[budget.inspect_scope(s['scope_id']) for s in args['scopes']],real_model_calls=0,actual_cost_usd='0'),indent=2)+'\n')
        finally:
            if output:(output/'completed-scopes.json').write_text(json.dumps([r['scope']['scope_id'] for r in reports],indent=2)+'\n')
