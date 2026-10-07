"""Loopback HTTP behavior with an injected fake service; no provider requests."""
import asyncio
from copy import deepcopy
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from apps.claude_dialogue.app import ChatServer
from scripts.claude_dialogue import DialogueError
from scripts.claude_chat import connection


class FakeService:
    def __init__(self):
        self.revision='rev-0';self.turns=[];self.cost='0';self.cap='1.5';self.busy=False
        self.calls=0;self.actors=[];self.release=threading.Event();self.started=threading.Event()
    def history(self):
        if self.busy:raise DialogueError('session_locked')
        return {'revision':self.revision,'model':'claude-opus-5-5','configuration':{'max_tokens':4096},
            'summary':{'budget_usd':self.cap,'estimated_spent_usd':self.cost,'held_usd':'0','remaining_usd':str(float(self.cap)-float(self.cost))},
            'turns':deepcopy(self.turns),'system':'private-system-do-not-expose','api_key':'never-expose','path':'/private/path'}
    def preflight(self,message,revision):
        if revision!=self.revision:raise DialogueError('revision_conflict')
        return {'allowed':self.cap!='0.01','reason':'budget_insufficient','reserve_usd':'0.2'}
    def set_budget(self,value,revision,actor='user'):
        if revision!=self.revision:raise DialogueError('revision_conflict')
        if actor!='user':raise AssertionError('actor spoof')
        self.cap=str(value);self.revision='budget-'+self.revision;return self.history()
    async def send(self,message,revision,actor='user'):
        self.calls+=1;self.actors.append(actor);self.busy=True;self.started.set()
        while not self.release.is_set():await asyncio.sleep(.005)
        self.busy=False;self.revision='rev-'+str(self.calls);self.cost='0.01'
        self.turns.append({'number':self.calls,'actor':actor,'status':'completed','user':message,'answer':'<script>visible as text</script>','model':'claude-opus-5-5','estimated_usd':'0.01'})
        return self.history()


class ChatHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.window=self.base/'window';self.window.mkdir(mode=0o700)
        self.service=FakeService();self.server=ChatServer(('127.0.0.1',0),self.service,self.window)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie=None;self.csrf=None
    def tearDown(self):
        self.service.release.set();self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,body=None,*,browser=False,codex=False,headers=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        h={}
        if browser:
            h['Cookie']=self.cookie or '';h['X-CSRF-Token']=self.csrf or '';h['Origin']=self.server.origin
        if codex:h['Authorization']='Bearer '+self.server.cli_token
        if headers:h.update(headers)
        raw=None
        if body is not None:raw=json.dumps(body).encode();h['Content-Type']='application/json'
        c.request('POST' if body is not None else 'GET',path,body=raw,headers=h)
        r=c.getresponse();data=r.read();status=r.status;rh=dict(r.getheaders());c.close()
        return status,json.loads(data),rh
    def login(self):
        status,r,headers=self.request('/api/session');self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0];self.csrf=r['csrf_token']
    def payload(self,rid='submission-01',message='Hello <img src=x onerror=alert(1)>'):
        return {'message':message,'expected_revision':self.service.revision,'client_request_id':rid}
    def wait_finished(self):
        deadline=time.monotonic()+3
        while self.server.pending and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(self.server.pending)

    def test_private_history_requires_session_and_never_exposes_system_or_key(self):
        self.assertEqual(self.request('/api/conversation')[0],401)
        self.login();status,data,headers=self.request('/api/conversation',browser=True)
        self.assertEqual(status,200)
        self.assertNotIn('private-system',json.dumps(data));self.assertNotIn('never-expose',json.dumps(data))
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(headers['X-Frame-Options'],'DENY')
        self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertEqual(self.request('/api/conversation',codex=True)[0],200)
        self.assertEqual(self.request('/session/system.txt',browser=True)[0],404)
        self.assertEqual(self.request('/../../.env',browser=True)[0],404)

    def test_origin_host_and_csrf_checks_prevent_mutation(self):
        self.login()
        for headers in ({'Origin':'https://outside.invalid'},{'Host':'rebind.invalid'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('/api/messages',self.payload(),browser=True,headers=headers)[0],403)
        self.assertEqual(self.request('/api/messages',self.payload(),browser=True,headers={'X-CSRF-Token':'wrong'})[0],401)
        self.assertEqual(self.request('/api/messages',{**self.payload(),'actor':'codex'},browser=True)[0],409)
        self.assertEqual(self.service.calls,0)

    def test_send_is_single_dispatch_pending_is_readable_and_history_shared(self):
        self.login();payload=self.payload()
        self.assertEqual(self.request('/api/messages',payload,browser=True)[0],202)
        self.assertTrue(self.service.started.wait(2))
        status,state,_=self.request('/api/conversation',browser=True)
        self.assertEqual(status,200);self.assertEqual(state['pending']['message'],payload['message'])
        status,replay,_=self.request('/api/messages',payload,browser=True)
        self.assertEqual(status,202);self.assertTrue(replay['replayed'])
        self.assertEqual(self.request('/api/codex/messages',self.payload('submission-02'),codex=True)[0],409)
        recovery={**self.payload('submission-03'),'continue_after_failed_turn':1,'max_tokens':8192}
        self.assertEqual(self.request('/api/codex/messages',recovery,codex=True)[1]['error']['code'],'request_in_progress')
        self.service.release.set();self.wait_finished()
        state=self.request('/api/conversation',codex=True)[1]
        self.assertEqual(state['turns'][0]['user'],payload['message'])
        self.assertEqual(state['turns'][0]['answer'],'<script>visible as text</script>')
        self.assertEqual(self.service.calls,1);self.assertEqual(self.service.actors,['user'])
        self.assertEqual(self.request('/api/messages',payload,browser=True)[1]['submission']['status'],'completed')
        self.assertEqual(self.service.calls,1)
        self.assertEqual(self.request('/api/messages',self.payload(message='different'),browser=True)[0],409)

    def test_codex_uses_same_revision_history_and_recorded_actor(self):
        payload=self.payload();self.service.release.set()
        self.assertEqual(self.request('/api/codex/messages',payload,codex=True)[0],202)
        self.wait_finished();self.login()
        state=self.request('/api/conversation',browser=True)[1]
        self.assertEqual(state['turns'][0]['actor'],'codex')
        stale={**self.payload('submission-02'),'expected_revision':'rev-0'}
        self.assertEqual(self.request('/api/messages',stale,browser=True)[0],409)
        self.assertEqual(self.service.calls,1)

    def test_budget_is_explicit_and_insufficient_budget_creates_no_job(self):
        self.login()
        status,state,_=self.request('/api/budget',{'limit_usd':'0.01','expected_revision':self.service.revision},browser=True)
        self.assertEqual(status,200);self.assertEqual(state['budget']['limit_usd'],'0.01')
        result=self.request('/api/messages',self.payload(),browser=True)
        self.assertEqual(result[0],409);self.assertEqual(result[1]['error']['code'],'budget_insufficient')
        self.assertEqual(list(self.server.submissions.iterdir()),[]);self.assertEqual(self.service.calls,0)
        self.assertEqual(self.request('/api/budget',{'limit_usd':'4','expected_revision':self.service.revision},codex=True)[0],401)

    def test_private_connection_and_cli_projection(self):
        conn=connection(self.base)
        self.assertEqual(conn['url'],self.server.origin)
        self.assertEqual((self.window/'connection.json').stat().st_mode&0o777,0o600)
        from scripts.claude_chat import call
        state=call(conn,'/api/conversation')
        self.assertEqual(state['revision'],'rev-0')
        self.assertNotIn('token',state)
        (self.window/'connection.json').chmod(0o644)
        with self.assertRaisesRegex(ValueError,'private_connection'):connection(self.base)

    def test_worker_failure_is_visible_and_does_not_leave_pending(self):
        async def fail(*args,**kwargs):raise DialogueError('previous_turn_failed_or_interrupted')
        self.service.send=fail
        self.assertEqual(self.request('/api/codex/messages',self.payload(),codex=True)[0],202)
        self.wait_finished()
        state=self.request('/api/conversation',codex=True)[1]
        self.assertEqual(state['last_submission']['status'],'failed')
        self.assertEqual(state['last_submission']['error_code'],'previous_turn_failed_or_interrupted')
        self.assertEqual(self.request('/api/codex/messages',self.payload(),codex=True)[1]['replayed'],True)

if __name__=='__main__':unittest.main()
