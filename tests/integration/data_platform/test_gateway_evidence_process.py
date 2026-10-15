"""Real process exits and a local HTTP peer exercise durable wire observations."""
from contextlib import closing
from decimal import Decimal
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response, response_bytes
from uteki.infrastructure.run_budget import RunBudget, RequestRecoveryRequired


WORKER=Path(__file__).resolve().parents[2]/'fixtures/data_platform/gateway_evidence_worker.py'


class GatewayEvidenceProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uteki-gateway-evidence-process-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'batch.sqlite'
        self.budget=RunBudget(self.path,'2')
        self.budget.bind_root('synthetic-evidence-process',mode='remote',max_requests=3,
            scope_ids=['first-case','other-case'],max_in_flight_requests=1,policy={'synthetic':True})
        for scope in ('first-case','other-case'):
            self.budget.bind_scope(scope,max_requests=2,policy={'context':scope})

    def crash(self, phase):
        result=subprocess.run([sys.executable,'-I',str(WORKER),str(self.path),phase],
            cwd=self.path.parent,env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,79,result.stderr)
        self.budget=RunBudget.open_existing(self.path,'2',root_run_id='synthetic-evidence-process')

    def other(self):
        return self.budget.prepare_request('other',{'synthetic':'other SDK'},reserve_usd='.8',scope_id='other-case')

    def test_exit_after_receive_but_before_record_preserves_unknown_request_and_hold(self):
        self.crash('received');self.budget.recover_requests(scope_id='first-case')
        request=self.budget.inspect_request('first')
        self.assertEqual(request['stage'],'outcome_unknown');self.assertIsNone(request['response_event'])
        self.assertEqual(Decimal(self.budget.summary()['held_usd']),Decimal('.8'))
        with self.assertRaises(RequestRecoveryRequired):self.other()

    def test_exit_inside_raw_response_transaction_rolls_back_charge_and_body_together(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TRIGGER synthetic_failure BEFORE UPDATE OF response_event ON metered_requests '
                       'BEGIN SELECT synthetic_exit(); END');db.commit()
        self.crash('transaction')
        request=self.budget.inspect_request('first')
        self.assertIsNone(request['response_event']);self.assertIsNone(request['bill'])
        self.assertEqual(request['stage'],'dispatched')
        self.assertEqual(Decimal(self.budget.summary()['held_usd']),Decimal('.8'))
        self.budget.recover_requests(scope_id='first-case')
        with self.assertRaises(RequestRecoveryRequired):self.other()

    def test_exit_after_complete_response_retains_exact_bytes_and_one_charge(self):
        self.crash('complete')
        saved=self.budget.inspect_request('first')
        raw=response_bytes(saved['response_event']['response']['http'])
        self.assertIn(b'"cost":0.04',raw)
        self.assertEqual(saved['stage'],'responded');self.assertEqual(saved['settled_usd'],'0.04')
        record_response(self.budget,'first',saved['response_event']['response']['http'],origin='synthetic')
        self.assertEqual(self.budget.summary()['requests'],1)
        with self.assertRaises(RequestRecoveryRequired):self.budget.begin_request('first')
        self.other()

    def test_exit_after_partial_bill_keeps_original_response_unknown(self):
        self.crash('bill')
        saved=self.budget.inspect_request('first')
        self.assertEqual(saved['stage'],'outcome_unknown');self.assertEqual(saved['settled_usd'],'0.04')
        self.assertEqual(len(response_bytes(saved['response_event']['response']['http'])),32)
        self.assertEqual(self.budget.recover_requests(scope_id='first-case'),[])
        with self.assertRaises(RequestRecoveryRequired):self.other()

    def test_real_loopback_http_short_body_retains_incomplete_bytes_not_success(self):
        raw=b'{"id":"gen-synthetic-a","model":"synthetic/model","object":"chat.completion","choices":[{"finish_reason":"stop"}],"usage":{"cost":0.04}}'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('X-Generation-Id','gen-synthetic-a')
                self.send_header('Content-Length',str(len(raw)+50))
                self.end_headers();self.wfile.write(raw)
                self.close_connection=True
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            self.budget.prepare_request('wire',{'synthetic':'local HTTP'},reserve_usd='.8',scope_id='first-case')
            self.budget.begin_request('wire')
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            try:
                connection.request('POST','/synthetic',body=b'{}')
                response=connection.getresponse()
                def chunks():
                    while chunk:=response.read(8):
                        yield chunk
                captured=capture_response('chat_completions',response.status,response.getheaders(),chunks(),max_bytes=1000)
            finally:connection.close()
            saved=record_response(self.budget,'wire',captured,origin='synthetic')
            self.assertEqual(response_bytes(captured),raw)
            self.assertEqual(captured['error'],'content_length_mismatch')
            self.assertEqual(saved['stage'],'outcome_unknown')
            self.assertEqual(saved['cost_state'],'unknown')
            with self.assertRaises(RequestRecoveryRequired):self.other()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
            self.assertFalse(worker.is_alive())


if __name__=='__main__':unittest.main()
