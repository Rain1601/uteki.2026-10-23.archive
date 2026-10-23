"""Actual SDK workers must stop even when their resolver/HTTP headers block."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_supervisor import GatewaySupervisor
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class HeaderPeer:
    def __init__(self):
        self.received=threading.Event();self.release=threading.Event();self.requests=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                owner.requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                owner.received.set()
                try:
                    # Each byte arrives inside the socket timeout; only a
                    # total host deadline can bound this header indefinitely.
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Synthetic: ');self.wfile.flush()
                    while not owner.release.wait(.05):
                        self.wfile.write(b'x');self.wfile.flush()
                except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_port)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*errors):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join()


class GatewaySupervisionTests(unittest.TestCase):
    def scenario(self,kernel,fault,*,cancel=False,stop_write_failure=False):
        case,args,bindings=F['fixture'](request_timeout_seconds=.6);self.addCleanup(case.doCleanups)
        scope=next(s for s in args['scopes'] if s['profile']['kernel']==kernel)
        with HeaderPeer() as peer,tempfile.TemporaryDirectory(prefix='uteki-supervised-') as temporary:
            work=Path(temporary)
            supervisor=GatewaySupervisor(case.catalog,scope['context_ref'],bindings[scope['scope_id']],
                scope['profile'],scope['limits'],batch_deadline=time.monotonic()+(5 if fault=='run' else 15))
            case.catalog.close()
            spec=dict(root=str(case.root),kernel=kernel,context_ref=scope['context_ref'],binding=bindings[scope['scope_id']],
                limits=scope['limits'],endpoint=peer.endpoint,output=str(work/'result.json'))
            if fault=='dns':spec['block_dns']=True
            if fault=='run':spec['hold_phase']='native_initialization_saved'
            path=work/'spec.json';path.write_text(json.dumps(spec))
            env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=peer.endpoint,
                ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-gateway-worker',
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',
                HTTP_PROXY=peer.endpoint,HTTPS_PROXY=peer.endpoint,ALL_PROXY=peer.endpoint,NO_PROXY='127.0.0.1,localhost')
            cancelled=(lambda:(case.root/'blocked.json').exists()) if fault in {'dns','run'} else peer.received.is_set
            with (work/'stdout').open('w') as stdout,(work/'stderr').open('w') as stderr:
                worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_supervised_worker.py'),str(path)],
                    cwd=work,env=env,stdout=stdout,stderr=stderr)
                if stop_write_failure:
                    with patch.object(supervisor.budget,'stop_scope',side_effect=OSError('controlled stop persistence failure')):
                        with self.assertRaises(OSError):supervisor.wait(worker,cancelled=cancelled)
                    report=dict(observation=worker.observation,events=supervisor.events)
                else:report=supervisor.wait(worker,cancelled=cancelled if cancel else None)
            marker=json.loads((case.root/'blocked.json').read_text()) if (case.root/'blocked.json').exists() else None
            evidence=dict(supervision=report,cleanup=worker.cleanup,marker=marker,
                peer_requests=[json.loads(r) for r in peer.requests],stderr=(work/'stderr').read_text())
            with Catalog.open(case.root) as catalog:
                evidence['record']=supervisor.record(catalog)
                # Recovery is deterministic; no SDK assembly or inference.
                journal=RuntimeJournal(DataService(catalog),scope['context_ref'],scope['profile'],scope['limits'],
                    gateway_binding=bindings[scope['scope_id']],recover=True)
                result=journal.cached
                if result is None:
                    result=journal.finish(journal.failure_outcome('supervised worker stopped before native start'))
                evidence.update(result=result,native=Session(catalog,scope['context_ref']).data['native_execution'],
                    requests=supervisor.budget.inspect_requests(),budget=supervisor.budget.inspect_root(),
                    scope=supervisor.budget.inspect_scope(scope['scope_id']),
                    other_scope=supervisor.budget.inspect_scope(next(s['scope_id'] for s in args['scopes'] if s!=scope)))
            if os.environ.get('UTEKI_GATEWAY_SUPERVISION_EVIDENCE'):
                output=Path(os.environ['UTEKI_GATEWAY_SUPERVISION_EVIDENCE']);output.mkdir(parents=True,exist_ok=True)
                (output/(kernel+'-'+fault+('-cancel' if cancel else '')+('-disk-failure' if stop_write_failure else '')+'.json')).write_text(json.dumps(evidence,indent=2)+'\n')
            self.assertTrue(cancelled(),evidence)
            self.assertEqual(worker.cleanup['after'],[]);self.assertIsNotNone(worker.child.returncode)
            self.assertIsNone(evidence['other_scope']['stop_reason'])
            self.assertIsNone(evidence['budget']['stop_reason'])
            if not stop_write_failure:
                self.assertEqual(evidence['scope']['stop_reason'],'cancelled' if cancel else 'wall_time')
                self.assertEqual(result['status'],'cancelled' if cancel else 'partial',result)
            if fault!='run':
                self.assertEqual(len(evidence['requests']),1)
                self.assertEqual(evidence['requests'][0]['stage'],'outcome_unknown')
                self.assertEqual(evidence['requests'][0]['cost_state'],'unknown')
                self.assertTrue(result['reconciliation_required'])
                self.assertEqual(len(peer.requests),0 if fault=='dns' else 1)
            return evidence

    def test_both_resolvers_are_stopped_by_host_transport_deadline(self):
        for kernel in ('openai','claude'):
            with self.subTest(kernel=kernel):
                evidence=self.scenario(kernel,'dns')
                self.assertEqual(evidence['supervision']['events'][0]['trigger'],'transport_deadline')

    def test_dripping_headers_cannot_extend_either_native_request_forever(self):
        for kernel in ('openai','claude'):
            with self.subTest(kernel=kernel):
                evidence=self.scenario(kernel,'headers')
                self.assertEqual(evidence['supervision']['events'][0]['trigger'],'transport_deadline')

    def test_cancellation_stops_both_blocked_resolvers(self):
        for kernel in ('openai','claude'):
            with self.subTest(kernel=kernel):self.scenario(kernel,'dns',cancel=True)

    def test_whole_run_deadline_covers_initialization_without_a_model_request(self):
        for kernel in ('openai','claude'):
            with self.subTest(kernel=kernel):
                evidence=self.scenario(kernel,'run')
                self.assertEqual(evidence['requests'],[])

    def test_stop_persistence_failure_still_terminates_owned_group_and_never_reports_success(self):
        evidence=self.scenario('openai','dns',cancel=True,stop_write_failure=True)
        self.assertEqual(evidence['result']['kind'],'recovery_required')
        self.assertIsNone(evidence['scope']['stop_reason'])
