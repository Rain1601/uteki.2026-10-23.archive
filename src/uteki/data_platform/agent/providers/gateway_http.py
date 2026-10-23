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
from urllib.parse import urlsplit, urlencode
import uuid

from uteki.infrastructure.run_budget import BudgetExceeded, RequestIdentityConflict
from ...contracts.common import canonical, digest
from .openrouter_evidence import capture_response, record_response, response_bytes, observe_response, reconcile_response


# 严格拒绝重复请求字段，确保账本摘要对应唯一 JSON 语义。
def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate_request_field')
        result[key]=value
    return result


# 非有限数字无法形成可靠的冻结请求，禁止 NaN 和 Infinity 等 JSON 扩展。
def _constant(_):
    raise ValueError('nonfinite_request_number')


# 两种 SDK 共用的物理 HTTP 边界：管准入、预算、原始收据和连接，不接管业务循环。
class GatewayHTTP:
    """Forward unchanged protocol bodies after a durable reservation/dispatch.

    Session mutations are deliberately absent. The owning RuntimeJournal must
    separately authorize business progress and persist its native state.
    """
    # 从持久化 scope 固定协议和限制，并按合成、授权 live 或历史 OpenRouter 契约核验端点。
    def __init__(self, budget, scope_id, *, endpoint, origin, credential, deadline,
                 before_request, checkpoint=None, execution_contract=None, execution_policy=None):
        self.budget,self.scope_id=budget,scope_id
        self.scope=deepcopy(budget.inspect_scope(scope_id))
        self.ledger_policy=deepcopy(self.scope['policy'])
        self.policy=deepcopy(self.ledger_policy if execution_policy is None else execution_policy)
        if execution_policy is not None:
            from ...application.gateway_batch import validate_execution_policy
            validate_execution_policy(self.ledger_policy,self.policy)
        self.profile=self.policy['profile']
        self.transport=self.policy['transport']
        self.protocol=self.profile['route']['protocol']
        self.path={'chat_completions':'/v1/chat/completions','anthropic_messages':'/v1/messages'}.get(self.protocol)
        if self.path is None:raise ValueError('unsupported_gateway_protocol')
        route=self.profile['route']
        if (route.get('provider') not in {'openrouter','deepseek'} or route.get('allow_fallbacks') is not False
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
        self.billing_origin=origin
        self.live_policy=None
        parsed=urlsplit(endpoint)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError('unexpected_endpoint_components')
        root=budget.inspect_root()
        if root['mode']!='remote':raise ValueError('gateway_wire_requires_metered_remote_semantics')
        # 合成路径仅接受回环地址与合成凭据；真实路径须通过对应执行契约验证。
        if origin=='synthetic':
            if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port
                    or parsed.path not in {'','/'} or credential!='uteki-synthetic-gateway'):
                raise ValueError('synthetic_wire_requires_loopback_and_synthetic_credential')
            self.prefix=''
        elif origin=='live':
            from .live_policy import admit
            self.prefix,self.live_policy=admit(execution_contract,root,self.scope,endpoint)
            self.billing_origin=route['provider']
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

    # 每个阶段复核停止状态、截止时间和 scope 身份；补账可越过业务停止，但仍受截止限制。
    def guard(self, *, billing=False):
        if self.closed:raise BudgetExceeded('gateway_transport_closed')
        root=self.budget.inspect_root();scope=self.budget.inspect_scope(self.scope_id)
        if not billing and (root['stop_reason'] or scope['stop_reason']):
            raise BudgetExceeded('gateway_root_or_scope_stopped')
        if time.monotonic()>=self.deadline:raise BudgetExceeded('gateway_host_deadline')
        if scope['policy']!=self.ledger_policy:raise RequestIdentityConflict('gateway_scope_binding_changed')

    # 检查实际 HTTP 请求与冻结模型、输出上限、流式模式及供应商控制参数完全一致。
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
        controls=self.profile.get('request_controls')
        if controls is not None:
            if any(request.get(key)!=value for key,value in controls.items()):
                raise ValueError('provider_request_controls_differ')
            if self.profile['route']['provider']=='openrouter':
                if self.profile.get('parallel_tool_calls',False) is None and 'parallel_tool_calls' in request:
                    raise ValueError('gateway_parallel_tool_omission_differs')
                expected=dict(only=self.profile['route']['upstream'],order=self.profile['route']['upstream'],
                              allow_fallbacks=False,require_parameters=True)
                if request.get('provider')!=expected:raise ValueError('gateway_provider_controls_differ')
            elif 'provider' in request or 'reasoning' in request:
                raise ValueError('openrouter_controls_cannot_be_sent_to_deepseek')
            if self.protocol=='anthropic_messages' and request.get('thinking',{'type':'enabled'}).get('type') not in {'enabled','adaptive'}:
                raise ValueError('unexpected_deepseek_thinking_mode')
        elif self.protocol=='chat_completions':
            expected=dict(only=self.profile['route']['upstream'],order=self.profile['route']['upstream'],
                          allow_fallbacks=False,require_parameters=True)
            if request.get('provider')!=expected:raise ValueError('gateway_provider_controls_differ')
            if request.get('reasoning')!={'enabled':False}:raise ValueError('gateway_reasoning_controls_differ')
        elif request.get('thinking',{'type':'disabled'})!={'type':'disabled'}:
            raise ValueError('gateway_reasoning_controls_differ')
        elif self.origin=='openrouter' and request.get('thinking')!={'type':'disabled'}:
            # The pinned Claude CLI omits thinking while emitting effort=high
            # even with SDK thinking=disabled. OpenRouter maps that effort to
            # reasoning; absence is NOT proof that this contract disables it.
            # Synthetic wire capture remains diagnostic, never live admission.
            raise ValueError('gateway_reasoning_disable_not_transmitted')
        return request

    # 一次方法调用对应一次物理 POST：先持久化预留及发送状态，再 I/O，最后提交原始收据。
    def exchange(self, path, raw, headers, *, request_key=None, native_request_sha256=None,
                 native_http_body=None):
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
        if native_http_body is not None:
            if (not isinstance(native_http_body,bytes) or not native_http_body
                    or len(native_http_body)>self.transport['max_request_bytes']
                    or native_request_sha256 is not None):
                raise ValueError('invalid_native_http_body')
            native_request_sha256=digest(native_http_body)
            metadata['native_http_body_base64']=base64.b64encode(native_http_body).decode('ascii')
        if native_request_sha256 is not None:
            if (not isinstance(native_request_sha256,str) or len(native_request_sha256)!=64
                    or any(c not in '0123456789abcdef' for c in native_request_sha256)):
                raise ValueError('invalid_native_request_identity')
            metadata['native_request_sha256']=native_request_sha256
        reservation=self.transport['reserve_usd']
        if self.live_policy is not None:
            from .live_policy import reserve
            reservation=reserve(self.live_policy['pricing'],raw,self.profile['max_output_tokens'])
            if Decimal(reservation)>Decimal(self.transport['reserve_usd']):
                raise ValueError('live_request_reservation_exceeds_frozen_bound')
        # 费用预留和请求身份先于发送落盘；即使进程在后续中断，恢复也能识别未知请求。
        self.budget.prepare_request(key,metadata,reserve_usd=reservation,scope_id=self.scope_id)
        self.checkpoint('gateway_request_prepared')
        self.guard()
        self.budget.begin_request(key)
        self.checkpoint('gateway_request_dispatched')
        captured=None;record_attempted=False
        try:
            captured=self._capture('POST',path,raw,headers,self.protocol)
            self.checkpoint('gateway_response_received')
            record_attempted=True
            stored=self.record_response(key,captured)
            self.checkpoint('gateway_response_committed')
            self.guard()
            if not stored['response_event']['response']['complete']:
                raise ValueError('gateway_response_incomplete')
            return key,captured
        # 未能提交响应时保留已接收字节或明确的不完整收据，网络失败不能归为零费用。
        except BaseException as error:
            current=self.budget.inspect_request(key)
            if current['stage']=='dispatched' and not record_attempted:
                # No successful/partial receipt has been committed. Preserve
                # any received bytes; a network/guard error is not zero cost.
                if captured is None:
                    captured=capture_response(self.protocol,599,[],[],max_bytes=self.transport['max_response_bytes'])
                    captured.update(transport_complete=False,error=type(error).__name__)
                self.record_response(key,captured)
            raise

    # 按供应商证据口径记账：DeepSeek 保留 token 估算，OpenRouter 可核对实际 generation 账单。
    def record_response(self,key,captured):
        if self.billing_origin=='deepseek':
            from .deepseek_evidence import record_response as record_deepseek
            return record_deepseek(self.budget,key,captured,profile=self.profile,pricing=self.live_policy['pricing'])
        return record_response(self.budget,key,captured,origin=self.billing_origin)

    # 在请求超时与宿主截止时间的较早边界内收集原始响应，并保留受控套接字以支持取消。
    def _capture(self, method, path, raw, headers, protocol):
        connection=None;response=None;connected_socket=None
        until=min(self.deadline,time.monotonic()+self.transport['request_timeout_seconds'])
        try:
            self.guard(billing=method=='GET')
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
            self.guard(billing=method=='GET')
            if time.monotonic()>=until:raise TimeoutError('gateway_request_deadline')
            outgoing={'Content-Type':'application/json','Accept-Encoding':'identity',
                      'Authorization':'Bearer '+self.credential}
            if self.protocol=='anthropic_messages':
                if self.billing_origin=='deepseek':outgoing['x-api-key']=self.credential
                for name in ('anthropic-version','anthropic-beta'):
                    if name in headers:outgoing[name]=headers[name]
            target=self.prefix+path
            if self.billing_origin=='deepseek' and self.protocol=='chat_completions':
                target=path.removeprefix('/v1')
            connection.request(method,target,body=raw,headers=outgoing)
            if method=='POST':self.checkpoint('gateway_request_sent')
            remaining=until-time.monotonic()
            if remaining<=0:raise TimeoutError('gateway_request_deadline')
            connected_socket.settimeout(remaining)
            response=connection.getresponse()
            # 每次读块重算剩余时间；HTTP 连接对象脱离套接字后仍保留取消和读取期限控制。
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
            captured=capture_response(protocol,response.status,response.getheaders(),chunks(),
                                      max_bytes=self.transport['max_response_bytes'])
            return captured
        finally:
            if response is not None:response.close()
            if connection is not None:
                connection.close()
                with self.lock:
                    self.connections.discard(connection)
                    self.sockets.discard(connected_socket)

    # 仅为原 scope 已观察到的 generation 查询账单；每次尝试先登记，已有可用收据直接复核。
    def observe_bill(self, request_key):
        """One bounded GET; callers may explicitly request a second observation.

        The same ledger retains every attempt before I/O, including interrupted
        attempts. Previously committed bytes are reconciled without another GET.
        """
        self.guard(billing=True)
        current=self.budget.inspect_request(request_key)
        metadata=current['request']
        if (current.get('control_scope_id')!=self.scope_id
                or metadata.get('boundary')!='gateway_http'
                or metadata.get('origin')!=self.origin
                or metadata.get('context_ref')!=self.policy['context_ref']
                or current['response_event'] is None):
            raise RequestIdentityConflict('billing_request_outside_original_scope')
        if current['cost_state']=='settled':return current
        generation=observe_response(current['response_event']['response']['http'])['generation_id']
        if generation is None:raise ValueError('observed_generation_identity_required')
        for previous in self.budget.inspect_billing_observations(request_key):
            captured=previous['observation']
            if captured is not None and observe_response(captured)['billed_usd'] is not None:
                return reconcile_response(self.budget,request_key,captured,origin=self.billing_origin)
        ordinal=self.budget.begin_billing_observation(request_key,identity=generation)
        self.checkpoint('gateway_billing_observation_started')
        try:
            captured=self._capture('GET','/v1/generation?'+urlencode({'id':generation}),None,{},'generation')
        except Exception as error:
            captured=capture_response('generation',599,[],[],max_bytes=self.transport['max_response_bytes'])
            captured.update(transport_complete=False,error=type(error).__name__)
            self.budget.record_billing_observation(request_key,ordinal,captured)
            raise
        self.budget.record_billing_observation(request_key,ordinal,captured)
        self.checkpoint('gateway_billing_observation_committed')
        result=reconcile_response(self.budget,request_key,captured,origin=self.billing_origin)
        self.checkpoint('gateway_bill_reconciled')
        return result

    # 标记传输关闭并主动 shutdown 所有受控套接字，防止取消后读写或隐式重新连接。
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


# SDK 连接的私有回环入口，验证随机令牌与请求大小后才交给受控网关。
class GatewayProxy:
    """Private loopback gate; both SDKs keep their native wire protocol."""
    # 跟踪入站连接并设置独立读请求期限，避免慢请求在取消后继续占用服务线程。
    def __init__(self, exchange):
        self.exchange=exchange;self.token=secrets.token_urlsafe(32);self.events=[]
        self.lock=threading.Lock();self.incoming=set();self.closed=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            # 连接接入时就纳入取消集合，读取请求头和正文均受同一入口期限约束。
            def setup(self):
                super().setup()
                with owner.lock:
                    if owner.closed:raise ConnectionAbortedError('gateway_proxy_closed')
                    owner.incoming.add(self.connection)
                self.input_deadline=min(exchange.deadline,time.monotonic()+exchange.transport['request_timeout_seconds'])
                self.connection.settimeout(max(.001,self.input_deadline-time.monotonic()))
            # 无论处理是否成功，都从活动连接集合移除该连接。
            def finish(self):
                try:super().finish()
                finally:
                    with owner.lock:owner.incoming.discard(self.connection)
            def log_message(self,*args):pass
            def do_CONNECT(self):self.send_error(403)
            def do_GET(self):self.send_error(403)
            # 要求唯一 Content-Length 且禁止分块请求，按有界长度读完后再进行网关交换。
            def do_POST(self):
                length=None
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
                    # Retain only known local codes, never arbitrary upstream
                    # exception text (which may contain private request data).
                    codes={'private_gateway_token_required','explicit_request_content_length_required',
                        'invalid_content_length','request_too_large','incomplete_request',
                        'gateway_request_exceeds_bound','sdk_retry_not_authorized',
                        'live_request_reservation_exceeds_frozen_bound'}
                    code=str(error) if isinstance(error,ValueError) and str(error) in codes else None
                    owner.events.append(dict(status='blocked_or_failed',error_type=type(error).__name__,
                        error_code=code,request_bytes=length,max_request_bytes=exchange.transport['max_request_bytes']))
                    try:self.send_error(400,'Gateway request blocked or failed')
                    except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=False
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.base_url='http://127.0.0.1:'+str(self.server.server_port)

    # 上下文开始时启动本地监听线程，地址随机分配且只绑定回环接口。
    def __enter__(self):
        self.thread.start();return self

    # 先停止上游传输，再关闭入站连接及监听线程，确保上下文结束后无残留 I/O。
    def __exit__(self,*errors):
        self.exchange.close()
        self.server.shutdown()
        with self.lock:
            self.closed=True
            for connection in self.incoming:
                try:connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        self.server.server_close();self.thread.join()
