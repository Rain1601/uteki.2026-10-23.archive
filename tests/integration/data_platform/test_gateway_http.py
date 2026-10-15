"""Real loopback HTTP through the same metered boundary used by native SDKs."""
import base64
from copy import deepcopy
from decimal import Decimal
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP, GatewayProxy
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, reconcile_response, response_bytes
from uteki.infrastructure.run_budget import BudgetExceeded, RequestInFlight, RequestRecoveryRequired
from uteki.infrastructure.run_budget import RunBudget


def profile(kernel='openai'):
    return dict(kernel=kernel,model_id='synthetic/model',max_output_tokens=32,
        route=dict(provider='openrouter',protocol='chat_completions' if kernel=='openai' else 'anthropic_messages',
                   upstream=['synthetic'],allow_fallbacks=False,require_parameters=True))


def request(kernel='openai'):
    value=dict(model='synthetic/model',max_tokens=32,messages=[dict(role='user',content='Synthetic input')])
    if kernel=='openai':value.update(provider=dict(only=['synthetic'],order=['synthetic'],
        allow_fallbacks=False,require_parameters=True),reasoning={'enabled':False})
    else:value.update(stream=True,thinking={'type':'disabled'})
    return json.dumps(value).encode()


class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uteki-wire-boundary-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'batch.sqlite';self.received=[];self.behavior={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                owner.received.append(dict(path=self.path,headers=dict(self.headers),body=body))
                number=len(owner.received)
                raw=json.dumps(dict(id=f'gen-synthetic-{number}',model='synthetic/model',provider='Synthetic',
                    object='chat.completion',choices=[dict(finish_reason='stop',message=dict(role='assistant',content='Synthetic output'))],
                    usage=dict(prompt_tokens=2,completion_tokens=2,total_tokens=4,cost=.04))).encode()
                raw=owner.behavior.get('body',raw)
                self.send_response(owner.behavior.get('status',200))
                self.send_header('Content-Type',owner.behavior.get('media','application/json'))
                self.send_header('Content-Length',str(len(raw)+owner.behavior.get('extra_length',0)))
                self.send_header('X-Generation-Id',f'gen-synthetic-{number}')
                self.end_headers()
                if owner.behavior.get('hold_body'):
                    self.wfile.write(raw[:12]);self.wfile.flush()
                    owner.behavior['body_started'].set()
                    owner.behavior['release_body'].wait(timeout=3)
                    raw=raw[12:]
                if owner.behavior.get('delay'):time.sleep(owner.behavior['delay'])
                try:self.wfile.write(raw)
                except OSError:pass
                self.close_connection=True
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_port)
        self.budget=RunBudget(self.path,'2')
        self.budget.bind_root('synthetic-batch',mode='remote',max_requests=4,max_in_flight_requests=1,
                             scope_ids=['openai','claude'],policy={'synthetic':True})
        for kernel in ('openai','claude'):
            self.budget.bind_scope(kernel,max_requests=2,policy=dict(profile=profile(kernel),
                context_ref='synthetic-context-'+kernel,business_root_run_id='synthetic-business-'+kernel,
                transport=dict(max_request_bytes=10000,max_response_bytes=10000,request_timeout_seconds=1,reserve_usd='.8')))

    def stop_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def wire(self,kernel='openai',**kwargs):
        value=GatewayHTTP(self.budget,kernel,endpoint=self.endpoint,origin='synthetic',
            credential='uteki-synthetic-gateway',deadline=time.monotonic()+10,before_request=lambda req:None,**kwargs)
        self.addCleanup(value.close)
        return value

    def test_same_body_forwarded_with_private_credential_and_durable_actual_bill(self):
        wire=self.wire();raw=request()
        key,captured=wire.exchange('/v1/chat/completions',raw,{},request_key='first')
        self.assertEqual(key,'first');self.assertEqual(self.received[0]['body'],raw)
        self.assertEqual(self.received[0]['headers']['Authorization'],'Bearer uteki-synthetic-gateway')
        self.assertEqual(self.received[0]['headers']['Accept-Encoding'],'identity')
        saved=self.budget.inspect_request(key)
        self.assertEqual(base64.b64decode(saved['request']['body_base64']),raw)
        self.assertEqual(saved['settled_usd'],'0.04')
        self.assertEqual(response_bytes(captured),response_bytes(saved['response_event']['response']['http']))
        self.assertNotIn('uteki-synthetic-gateway',json.dumps(saved))
        with self.assertRaises(RequestRecoveryRequired):wire.exchange('/v1/chat/completions',raw,{},request_key='first')
        self.assertEqual(len(self.received),1)

    def test_bad_model_route_output_stream_retry_and_path_never_reserve_or_send(self):
        wire=self.wire()
        for change in ({'model':'other/model'},{'max_tokens':33},{'stream':True},
                {'provider':{'order':['different']}},{'reasoning':{'enabled':True}}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                wire.exchange(wire.path,json.dumps(json.loads(request())|change).encode(),{})
        for path,headers in [('/v1/messages',{}),(wire.path,{'x-stainless-retry-count':'1'}),
                ('https://other.invalid/v1/chat/completions',{}),(wire.path+'?beta=true',{})]:
            with self.subTest(path=path),self.assertRaises(ValueError):wire.exchange(path,request(),headers)
        for query in ('?beta=false','?beta=true&model=other','?beta=true&beta=false','?other=1'):
            with self.subTest(query=query),self.assertRaises(ValueError):
                self.wire('claude').exchange('/v1/messages'+query,request('claude'),{})
        self.assertEqual(self.received,[]);self.assertEqual(self.budget.summary()['requests'],0)

    def test_unknown_fee_blocks_the_other_kernel_without_a_second_ledger(self):
        value=dict(id='gen-synthetic-1',model='synthetic/model',object='chat.completion',
            choices=[dict(finish_reason='stop',message=dict(role='assistant',content='synthetic'))],usage={'prompt_tokens':2})
        self.behavior['body']=json.dumps(value).encode()
        self.wire().exchange('/v1/chat/completions',request(),{},request_key='first')
        with self.assertRaises(RequestRecoveryRequired):self.wire('claude').exchange('/v1/messages',request('claude'),{})
        self.assertEqual(len(self.received),1);self.assertEqual(Decimal(self.budget.summary()['held_usd']),Decimal('.8'))
        bill=capture_response('generation',200,[('content-type','application/json')],
            [b'{"data":{"id":"gen-synthetic-1","total_cost":0.04}}'],max_bytes=1000)
        reconcile_response(self.budget,'first',bill,origin='synthetic')
        self.assertEqual(self.budget.inspect_request('first')['settled_usd'],'0.04')

    def test_cancel_after_receive_keeps_late_bill_but_does_not_return_body(self):
        def checkpoint(phase):
            if phase=='gateway_response_received':self.budget.stop_scope('openai','cancelled')
        with self.assertRaises(BudgetExceeded):
            self.wire(checkpoint=checkpoint).exchange('/v1/chat/completions',request(),{},request_key='first')
        saved=self.budget.inspect_request('first')
        self.assertEqual(saved['stage'],'responded');self.assertEqual(saved['settled_usd'],'0.04')
        self.assertIsNone(self.budget.inspect_root()['stop_reason'])
        self.assertEqual(len(self.received),1)

    def test_short_body_never_returns_success(self):
        self.behavior['extra_length']=20
        with self.assertRaises(ValueError):self.wire().exchange('/v1/chat/completions',request(),{},request_key='short')
        saved=self.budget.inspect_request('short')
        self.assertEqual(saved['stage'],'outcome_unknown')
        self.assertEqual(saved['response_event']['response']['http']['error'],'content_length_mismatch')
        self.assertEqual(saved['cost_state'],'unknown')

    def test_response_timeout_preserves_unknown_cost_without_retry(self):
        self.behavior['delay']=1.3
        with self.assertRaises(ValueError):self.wire().exchange('/v1/chat/completions',request(),{},request_key='timeout')
        saved=self.budget.inspect_request('timeout')
        self.assertEqual(saved['stage'],'outcome_unknown');self.assertEqual(saved['cost_state'],'unknown')
        self.assertFalse(saved['response_event']['response']['http']['transport_complete'])
        self.assertEqual(len(self.received),1)

    def test_response_size_bound_preserves_received_prefix(self):
        self.behavior['body']=b'x'*20000
        with self.assertRaises(ValueError):self.wire().exchange('/v1/chat/completions',request(),{},request_key='large')
        saved=self.budget.inspect_request('large')
        self.assertEqual(saved['stage'],'outcome_unknown')
        self.assertEqual(response_bytes(saved['response_event']['response']['http']),b'x'*10000)
        self.assertEqual(len(self.received),1)

    def test_receipt_write_failure_is_not_silently_retried(self):
        with patch('uteki.data_platform.agent.providers.gateway_http.record_response',side_effect=OSError('synthetic disk failure')) as record:
            with self.assertRaises(OSError):self.wire().exchange('/v1/chat/completions',request(),{},request_key='disk')
        self.assertEqual(record.call_count,1)
        self.assertEqual(self.budget.inspect_request('disk')['stage'],'dispatched')
        self.assertEqual(self.budget.inspect_request('disk')['cost_state'],'reserved')
        self.assertEqual(Decimal(self.budget.summary()['held_usd']),Decimal('.8'))
        with self.assertRaises(RequestInFlight):
            self.wire('claude').exchange('/v1/messages',request('claude'),{})
        self.assertEqual(len(self.received),1)

    def test_close_interrupts_detached_http10_response_socket(self):
        started=threading.Event();release=threading.Event();errors=[]
        self.behavior.update(hold_body=True,body_started=started,release_body=release)
        wire=self.wire()
        def send():
            try:wire.exchange('/v1/chat/completions',request(),{},request_key='interrupted-body')
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=send);worker.start()
        try:
            self.assertTrue(started.wait(timeout=2))
            wire.close();worker.join(timeout=.8)
            self.assertFalse(worker.is_alive());self.assertEqual(len(errors),1)
            saved=self.budget.inspect_request('interrupted-body')
            self.assertEqual(saved['stage'],'outcome_unknown')
            self.assertEqual(saved['cost_state'],'unknown')
        finally:release.set();worker.join(timeout=3)

    def test_proxy_exit_interrupts_incomplete_request_without_dispatch(self):
        with GatewayProxy(self.wire()) as proxy:
            client=socket.create_connection(('127.0.0.1',proxy.server.server_port),timeout=3)
            self.addCleanup(client.close)
            client.sendall(('POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer '+proxy.token+
                '\r\nContent-Length: 1000\r\n\r\n{').encode())
            until=time.monotonic()+1
            while not proxy.incoming and time.monotonic()<until:time.sleep(.005)
            self.assertTrue(proxy.incoming)
        self.assertFalse(proxy.incoming);self.assertFalse(proxy.thread.is_alive())
        self.assertEqual(self.received,[]);self.assertEqual(self.budget.summary()['requests'],0)

    def test_slow_request_body_cannot_extend_its_total_deadline(self):
        with GatewayProxy(self.wire()) as proxy:
            client=socket.create_connection(('127.0.0.1',proxy.server.server_port),timeout=3)
            self.addCleanup(client.close)
            client.sendall(('POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer '+proxy.token+
                '\r\nContent-Length: 1000\r\n\r\n').encode())
            start=time.monotonic()
            while time.monotonic()-start<1.5 and not proxy.events:
                try:client.sendall(b' ')
                except OSError:break
                time.sleep(.03)
            self.assertTrue(proxy.events)
            self.assertEqual(proxy.events[0]['error_type'],'TimeoutError')
        self.assertEqual(self.received,[]);self.assertEqual(self.budget.summary()['requests'],0)

    def test_http_error_is_returned_once_and_not_assumed_free(self):
        self.behavior.update(status=429,body=b'{"error":{"message":"synthetic limit"}}')
        key,response=self.wire().exchange('/v1/chat/completions',request(),{},request_key='limited')
        self.assertEqual(response['status'],429);self.assertEqual(len(self.received),1)
        self.assertEqual(self.budget.inspect_request(key)['cost_state'],'unknown')

    def test_private_proxy_rejects_token_external_target_and_retries(self):
        with GatewayProxy(self.wire()) as proxy:
            conn=http.client.HTTPConnection('127.0.0.1',proxy.server.server_port,timeout=3)
            try:
                for token,path in [('bad',proxy.exchange.path),(proxy.token,'http://other.invalid/')]:
                    conn.request('POST',path,body=request(),headers={'Authorization':'Bearer '+token})
                    response=conn.getresponse();response.read();self.assertEqual(response.status,400)
            finally:conn.close()
            self.assertEqual(self.received,[]);self.assertEqual(self.budget.summary()['requests'],0)

    def test_draft_contract_cannot_enable_an_external_transport(self):
        with self.assertRaises(ValueError):
            GatewayHTTP(self.budget,'openai',endpoint='https://openrouter.ai/api',origin='openrouter',
                credential='not-a-real-key',deadline=time.monotonic()+1,before_request=lambda req:None,
                execution_contract={'execution_enabled':False,'authorization':{'inference_authorized':False}})
        with self.assertRaises(ValueError):
            GatewayHTTP(self.budget,'openai',endpoint='http://example.com',origin='synthetic',
                credential='uteki-synthetic-gateway',deadline=time.monotonic()+1,before_request=lambda req:None)
        self.assertEqual(self.received,[])

    def test_closing_transport_before_send_cannot_reopen_a_connection(self):
        wire=self.wire();original=http.client.HTTPConnection.request
        def cancelled(connection,*args,**kwargs):
            wire.close()
            return original(connection,*args,**kwargs)
        with patch.object(http.client.HTTPConnection,'request',cancelled),self.assertRaises(Exception):
            wire.exchange('/v1/chat/completions',request(),{},request_key='cancel-before-send')
        self.assertEqual(self.received,[])
        self.assertEqual(self.budget.inspect_request('cancel-before-send')['stage'],'outcome_unknown')


if __name__=='__main__':unittest.main()
