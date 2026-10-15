"""Exercise the real local HTTP boundary independently of CLI happy-path behavior."""
import asyncio
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import threading
import unittest

from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.agent.providers.claude_transport import OfflineClaudeTransport
from uteki.data_platform.application.runtime import RuntimeJournal

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class TransportBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.case=F['case']();self.addCleanup(self.case.doCleanups)
        profile=load_profile(ROOT/'config/data_platform/model-profiles/claude/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='claude',model_id='fixture/claude-query-v1',role='query')
        self.journal=RuntimeJournal(self.case.service,self.case.context,profile.metadata(),F['runtime_limits']())
        self.requests=[];self.entered=threading.Event();self.release=threading.Event();self.release.set()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                owner.requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                owner.entered.set()
                owner.release.wait(5)
                payload=b'{"fixture_response":true}'
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        def close():
            self.release.set();self.server.shutdown();self.server.server_close();self.thread.join()
        self.addAsyncCleanup(asyncio.to_thread,close)
        self.observed=[]
        self.bridge=OfflineClaudeTransport(self.journal,'http://127.0.0.1:'+str(self.server.server_port),
            before_request=self.journal.guard_action,observed_request=self.observed.append)
        await self.bridge.__aenter__()
        self.addAsyncCleanup(self.bridge.__aexit__,None,None,None)

    async def exchange(self, *, body=None, headers=None, path='/v1/messages'):
        if body is None:body=json.dumps(dict(model='fixture/claude-query-v1',max_tokens=4096,messages=[])).encode()
        actual_headers={'Authorization':'Bearer '+self.bridge.token,'Content-Type':'application/json',**(headers or {})}
        def send():
            connection=http.client.HTTPConnection('127.0.0.1',self.bridge.server.server_port,timeout=6)
            try:
                connection.request('POST',path,body,actual_headers)
                response=connection.getresponse();return response.status,response.read()
            finally:connection.close()
        return await asyncio.to_thread(send)

    async def test_retry_model_and_auxiliary_endpoint_cannot_bypass_frozen_transport(self):
        cases=[dict(headers={'x-stainless-retry-count':'1'}),
            dict(headers={'Authorization':'Bearer unrelated'}),
            dict(path='/v1/messages/count_tokens'),dict(path='http://127.0.0.1:1/v1/messages'),
            dict(body=b'{"model":"unbound","max_tokens":4096}'),
            dict(body=b'{"model":"fixture/claude-query-v1","max_tokens":8192}'),
            dict(body=b'{"model":"fixture/claude-query-v1","model":"fixture/claude-query-v1","max_tokens":4096}')]
        for case in cases:
            with self.subTest(case=case):self.assertEqual((await self.exchange(**case))[0],400)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.journal.budget.inspect_requests(),[])
        self.assertEqual((await self.exchange())[0],200)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(len(self.observed),1)
        self.assertEqual(self.journal.budget.inspect_root()['request_stages'],{'responded':1})

    async def test_cancel_during_upstream_wait_records_late_response_but_does_not_deliver_it(self):
        self.release.clear()
        task=asyncio.create_task(self.exchange())
        try:
            self.assertTrue(await asyncio.to_thread(self.entered.wait,5))
            self.journal.stop('cancelled')
        finally:self.release.set()
        status,_=await task
        self.assertEqual(status,400)
        self.assertEqual(self.observed,[])
        saved=self.journal.budget.inspect_requests()
        self.assertEqual(len(saved),1)
        self.assertEqual(saved[0]['stage'],'responded')
        self.assertEqual(base64.b64decode(saved[0]['response_event']['response']['body_base64']),b'{"fixture_response":true}')
        self.assertEqual((await self.exchange())[0],400)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(self.journal.budget.inspect_root()['stop_reason'],'cancelled')


if __name__=='__main__':unittest.main()
