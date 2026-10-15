"""One raw HTTP boundary for the two official SDKs; no model/tool loop.

The host binds the scope and authorizes an endpoint before constructing this
transport. Synthetic endpoints are restricted to loopback. OpenRouter requires
the exact, enabled execution contract; no credentials are discovered here.
"""
from __future__ import annotations

from copy import deepcopy
import base64
from decimal import Decimal, InvalidOperation
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid

from uteki.infrastructure.run_budget import BudgetExceeded, RequestIdentityConflict
from ...contracts.common import canonical, digest
from .openrouter_evidence import capture_response, record_response, response_bytes


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate_request_field')
        result[key]=value
    return result


def _constant(_):
    raise ValueError('nonfinite_request_number')


class GatewayHTTP:
    """Forward unchanged protocol bodies after a durable reservation/dispatch.

    Session mutations are deliberately absent. The owning RuntimeJournal must
    separately authorize business progress and persist its native state.
    """
    def __init__(self, budget, scope_id, *, endpoint, origin, credential, deadline,
                 before_request, checkpoint=None, execution_contract=None):
        self.budget,self.scope_id=budget,scope_id
        self.scope=deepcopy(budget.inspect_scope(scope_id))
        self.policy=deepcopy(self.scope['policy'])
        self.profile=self.policy['profile']
        self.transport=self.policy['transport']
        self.protocol=self.profile['route']['protocol']
        self.path={'chat_completions':'/v1/chat/completions','anthropic_messages':'/v1/messages'}.get(self.protocol)
        if self.path is None:raise ValueError('unsupported_gateway_protocol')
        route=self.profile['route']
        if (route.get('provider')!='openrouter' or route.get('allow_fallbacks') is not False
                or route.get('require_parameters') is not True
                or not isinstance(route.get('upstream'),list) or not route['upstream']
                or any(not isinstance(item,str) or not item for item in route['upstream'])
                or self.profile.get('kernel')!=('openai' if self.protocol=='chat_completions' else 'claude')
                or type(self.profile.get('max_output_tokens')) is not int or self.profile['max_output_tokens']<1):
            raise ValueError('explicit_frozen_gateway_profile_required')
        try:reserve=Decimal(self.transport['reserve_usd'])
        except (InvalidOperation,KeyError,TypeError,ValueError):raise ValueError('positive_gateway_reservation_required') from None
        if not reserve.is_finite() or reserve<=0:raise ValueError('positive_gateway_reservation_required')
        for key in ('max_request_bytes','max_response_bytes'):
            if type(self.transport.get(key)) is not int or self.transport[key]<1:raise ValueError('explicit_positive_byte_limits_required')
        duration=self.transport.get('request_timeout_seconds')
        if type(duration) not in {int,float} or not math.isfinite(duration) or duration<=0:
            raise ValueError('explicit_request_timeout_required')
        if type(deadline) not in {int,float} or not math.isfinite(deadline):raise ValueError('explicit_host_deadline_required')
        if not isinstance(credential,str) or not credential or '\r' in credential or '\n' in credential:
            raise ValueError('explicit_private_credential_required')
        if not callable(before_request):raise ValueError('explicit_host_guard_required')
        self.deadline,self.before_request,self.checkpoint=deadline,before_request,checkpoint or (lambda phase:None)
        self.origin,self.credential=origin,credential
        parsed=urlsplit(endpoint)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError('unexpected_endpoint_components')
        root=budget.inspect_root()
        if root['mode']!='remote':raise ValueError('gateway_wire_requires_metered_remote_semantics')
        if origin=='synthetic':
            if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port
                    or parsed.path not in {'','/'} or credential!='uteki-synthetic-gateway'):
                raise ValueError('synthetic_wire_requires_loopback_and_synthetic_credential')
            self.prefix=''
        elif origin=='openrouter':
            if endpoint!='https://openrouter.ai/api':raise ValueError('exact_openrouter_endpoint_required')
            contract=execution_contract
            if (not isinstance(contract,dict) or contract.get('execution_enabled') is not True
                    or contract.get('authorization',{}).get('inference_authorized') is not True
                    or contract['authorization'].get('approved_limit_usd')!=root['limit_usd']
                    or root['policy'].get('execution_contract_sha256')!=digest(canonical(contract))
                    or {g.get('id') for g in contract.get('launch_gates',[])}!={'L1','L2','L3','L4','L5','L6'}
                    or any(not str(g.get('status','')).startswith('passed') for g in contract.get('launch_gates',[]))):
                raise ValueError('gateway_execution_contract_not_authorized_or_not_admitted')
            if (self.profile['model_id']!=contract['model']['gateway_id']
                    or self.profile['route']['upstream']!=[contract['model']['upstream_tag']]):
                raise ValueError('profile_differs_from_authorized_route')
            self.prefix='/api'
        else:raise ValueError('explicit_gateway_origin_required')
        self.endpoint=parsed
        self.connections=set();self.sockets=set();self.lock=threading.Lock();self.closed=False

    def guard(self):
        if self.closed:raise BudgetExceeded('gateway_transport_closed')
        root=self.budget.inspect_root();scope=self.budget.inspect_scope(self.scope_id)
        if root['stop_reason'] or scope['stop_reason']:
            raise BudgetExceeded('gateway_root_or_scope_stopped')
        if time.monotonic()>=self.deadline:raise BudgetExceeded('gateway_host_deadline')
        if scope['policy']!=self.policy:raise RequestIdentityConflict('gateway_scope_binding_changed')

    def validate_request(self, path, raw, headers):
        self.guard()
        allowed={self.path}
        # The native Claude CLI uses Anthropic's beta Messages SDK route.
        # Preserve this exact official query; do not accept arbitrary queries.
        if self.protocol=='anthropic_messages':allowed.add(self.path+'?beta=true')
        if path not in allowed:raise ValueError('gateway_endpoint_not_permitted')
        if not isinstance(raw,bytes) or not 0<len(raw)<=self.transport['max_request_bytes']:
            raise ValueError('gateway_request_exceeds_bound')
        if headers.get('x-stainless-retry-count','0')!='0':raise ValueError('sdk_retry_not_authorized')
        request=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
        if (not isinstance(request,dict) or request.get('model')!=self.profile['model_id']
                or request.get('max_tokens')!=self.profile['max_output_tokens']):
            raise ValueError('gateway_request_differs_from_frozen_model_or_output_bound')
        expected_stream=self.protocol=='anthropic_messages'
        if request.get('stream',False) is not expected_stream:raise ValueError('gateway_stream_mode_differs')
        if self.protocol=='chat_completions':
            expected=dict(only=self.profile['route']['upstream'],order=self.profile['route']['upstream'],
                          allow_fallbacks=False,require_parameters=True)
            if request.get('provider')!=expected:raise ValueError('gateway_provider_controls_differ')
            if request.get('reasoning')!={'enabled':False}:raise ValueError('gateway_reasoning_controls_differ')
        elif request.get('thinking',{'type':'disabled'})!={'type':'disabled'}:
            raise ValueError('gateway_reasoning_controls_differ')
        return request

    def exchange(self, path, raw, headers, *, request_key=None):
        """Called once per physical SDK HTTP request; never retries or redirects."""
        headers={k.lower():v for k,v in headers.items()}
        request=self.validate_request(path,raw,headers)
        self.before_request(request)
        self.guard()
        key=request_key or 'http:'+uuid.uuid4().hex
        metadata=dict(boundary='gateway_http',context_ref=self.policy['context_ref'],
            business_root_run_id=self.policy['business_root_run_id'],profile=self.profile,
            method='POST',path=path,origin=self.origin,body_sha256=digest(raw),
            body_base64=base64.b64encode(raw).decode('ascii'))
        self.budget.prepare_request(key,metadata,reserve_usd=self.transport['reserve_usd'],scope_id=self.scope_id)
        self.checkpoint('gateway_request_prepared')
        self.guard()
        self.budget.begin_request(key)
        self.checkpoint('gateway_request_dispatched')
        connection=None;response=None;connected_socket=None;captured=None;record_attempted=False
        until=min(self.deadline,time.monotonic()+self.transport['request_timeout_seconds'])
        try:
            self.guard()
            cls=http.client.HTTPSConnection if self.endpoint.scheme=='https' else http.client.HTTPConnection
            connection=cls(self.endpoint.hostname,self.endpoint.port,timeout=max(.001,until-time.monotonic()))
            with self.lock:
                if self.closed:raise BudgetExceeded('gateway_transport_closed')
                self.connections.add(connection)
            # http.client normally reconnects from request()/send() after close.
            # Own one explicit connection and never let cancellation reopen it.
            connection.auto_open=0
            connection.connect()
            connected_socket=connection.sock
            with self.lock:
                if self.closed:
                    connection.close()
                    raise BudgetExceeded('gateway_transport_closed')
                self.sockets.add(connected_socket)
            self.guard()
            outgoing={'Content-Type':'application/json','Accept-Encoding':'identity',
                      'Authorization':'Bearer '+self.credential}
            if self.protocol=='anthropic_messages':
                for name in ('anthropic-version','anthropic-beta'):
                    if name in headers:outgoing[name]=headers[name]
            connection.request('POST',self.prefix+path,body=raw,headers=outgoing)
            self.checkpoint('gateway_request_sent')
            remaining=until-time.monotonic()
            if remaining<=0:raise TimeoutError('gateway_request_deadline')
            connected_socket.settimeout(remaining)
            response=connection.getresponse()
            def chunks():
                while not response.isclosed():
                    remaining=until-time.monotonic()
                    if remaining<=0:raise TimeoutError('gateway_request_deadline')
                    # HTTP/1.0 can detach the socket from the connection while
                    # its response file still owns it. Retain cancellation and
                    # deadline control over that socket until the body closes.
                    connected_socket.settimeout(remaining)
                    block=response.read1(min(65536,self.transport['max_response_bytes']+1))
                    if not block:break
                    yield block
            captured=capture_response(self.protocol,response.status,response.getheaders(),chunks(),
                                      max_bytes=self.transport['max_response_bytes'])
            self.checkpoint('gateway_response_received')
            record_attempted=True
            stored=record_response(self.budget,key,captured,origin=self.origin)
            self.checkpoint('gateway_response_committed')
            self.guard()
            if not stored['response_event']['response']['complete']:
                raise ValueError('gateway_response_incomplete')
            return key,captured
        except BaseException as error:
            current=self.budget.inspect_request(key)
            if current['stage']=='dispatched' and not record_attempted:
                # No successful/partial receipt has been committed. Preserve
                # any received bytes; a network/guard error is not zero cost.
                if captured is None:
                    captured=capture_response(self.protocol,599,[],[],max_bytes=self.transport['max_response_bytes'])
                    captured.update(transport_complete=False,error=type(error).__name__)
                record_response(self.budget,key,captured,origin=self.origin)
            raise
        finally:
            if response is not None:response.close()
            if connection is not None:
                connection.close()
                with self.lock:
                    self.connections.discard(connection)
                    self.sockets.discard(connected_socket)

    def close(self):
        with self.lock:
            self.closed=True
            for connected_socket in self.sockets:
                try:connected_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            for connection in self.connections:
                if connection.sock is not None:
                    try:connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                connection.close()


class GatewayProxy:
    """Private loopback gate; both SDKs keep their native wire protocol."""
    def __init__(self, exchange):
        self.exchange=exchange;self.token=secrets.token_urlsafe(32);self.events=[]
        self.lock=threading.Lock();self.incoming=set();self.closed=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                with owner.lock:
                    if owner.closed:raise ConnectionAbortedError('gateway_proxy_closed')
                    owner.incoming.add(self.connection)
                self.input_deadline=min(exchange.deadline,time.monotonic()+exchange.transport['request_timeout_seconds'])
                self.connection.settimeout(max(.001,self.input_deadline-time.monotonic()))
            def finish(self):
                try:super().finish()
                finally:
                    with owner.lock:owner.incoming.discard(self.connection)
            def log_message(self,*args):pass
            def do_CONNECT(self):self.send_error(403)
            def do_GET(self):self.send_error(403)
            def do_POST(self):
                try:
                    if self.headers.get('Authorization')!='Bearer '+owner.token:
                        raise ValueError('private_gateway_token_required')
                    if self.headers.get('Transfer-Encoding') is not None:
                        raise ValueError('explicit_request_content_length_required')
                    values=self.headers.get_all('Content-Length',[])
                    if len(values)!=1 or not values[0].isdigit():raise ValueError('invalid_content_length')
                    length=int(values[0])
                    if not 0<length<=exchange.transport['max_request_bytes']:raise ValueError('request_too_large')
                    exchange.guard()
                    pieces=[];remaining_length=length
                    while remaining_length:
                        remaining_time=self.input_deadline-time.monotonic()
                        if remaining_time<=0:raise TimeoutError('gateway_request_body_deadline')
                        self.connection.settimeout(remaining_time)
                        block=self.rfile.read1(min(remaining_length,65536))
                        if not block:raise ValueError('incomplete_request')
                        pieces.append(block);remaining_length-=len(block)
                    raw=b''.join(pieces)
                    if len(raw)!=length:raise ValueError('incomplete_request')
                    key,captured=exchange.exchange(self.path,raw,dict(self.headers))
                    body=response_bytes(captured)
                    self.send_response(captured['status'])
                    for name,value in captured['headers']:
                        if name!='content-length':self.send_header(name,value)
                    self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                    owner.events.append(dict(request_key=key,status='forwarded'))
                except Exception as error:
                    owner.events.append(dict(status='blocked_or_failed',error_type=type(error).__name__))
                    try:self.send_error(400,'Gateway request blocked or failed')
                    except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=False
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.base_url='http://127.0.0.1:'+str(self.server.server_port)

    def __enter__(self):
        self.thread.start();return self

    def __exit__(self,*errors):
        self.exchange.close()
        self.server.shutdown()
        with self.lock:
            self.closed=True
            for connection in self.incoming:
                try:connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        self.server.server_close();self.thread.join()
