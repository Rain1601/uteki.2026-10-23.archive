"""Official OpenAI client over the shared metered HTTP boundary.

Runner and the official Chat adapter own the model/tool protocol. This adapter
only binds a native request intent to one durable physical HTTP request.
"""
from __future__ import annotations

import asyncio
import base64
import time

import httpx2
from openai import AsyncOpenAI, APIConnectionError
from agents import Model, OpenAIChatCompletionsModel

from ...contracts.common import CatalogError, canonical, digest
from ..metering import json_value
from .gateway_http import GatewayHTTP
from .openrouter_evidence import response_bytes
from .openrouter_reasoning import restore_reasoning


# 官方 OpenAI 客户端的底层传输扩展，将一次原生请求映射到既有计量边界。
class _Transport(httpx2.AsyncBaseTransport):
    def __init__(self, owner):
        self.owner=owner

    # 仅允许已绑定意图的一次 Chat 请求；额外请求、改变后的恢复字节和隐式重发均拒绝。
    async def handle_async_request(self, request):
        owner=self.owner
        if (request.method!='POST' or str(request.url)!='http://uteki-gateway.invalid/v1/chat/completions'
                or owner.intent is None or owner.http_used):
            raise CatalogError('CAPABILITY_UNSUPPORTED','unbound or additional native HTTP request')
        owner.http_used=True
        key,native_request=owner.intent
        # 请求准入及摘要计算前，从已绑定原始响应恢复不透明 reasoning_details 字段。
        raw=restore_reasoning(await request.aread(),owner.state)
        headers=dict(request.headers)
        headers['content-length']=str(len(raw))
        try:
            owner.wire.validate_request('/v1/chat/completions',raw,headers)
        except CatalogError:
            raise
        except ValueError as error:
            # The official client wraps custom transport ValueErrors as a
            # connection failure. Keep local admission failures distinguishable
            # from an uncertain network dispatch (and never retry either here).
            raise CatalogError('INVALID_REQUEST',
                'native request rejected before dispatch: '+str(error)) from error
        record=next((r for r in owner.journal.budget.inspect_requests() if r['request_key']==key),None)
        if record is not None:
            metadata=record['request']
            if (not owner.state.record_matches(record,native_request)
                    or metadata.get('method')!='POST' or metadata.get('path')!='/v1/chat/completions'
                    or metadata.get('body_sha256')!=digest(raw)
                    or base64.b64decode(metadata.get('body_base64',''),validate=True)!=raw):
                raise CatalogError('RECOVERY_REQUIRED','native HTTP request differs; no replay or resend')
            # 精确重放已确认的 HTTP 收据，让官方客户端重新解析，不能重新发送已完成请求。
            if record['stage']=='responded':
                saved=record['response_event']['response']
                if not saved.get('complete') or record['cost_state'] not in {'settled','bounded'}:
                    raise CatalogError('RECOVERY_REQUIRED','saved HTTP response or bill is incomplete')
                captured=saved['http']
                owner.journal.checkpoint('openai_gateway_wire_replayed')
                return httpx2.Response(captured['status'],headers=captured['headers'],content=response_bytes(captured))
            if record['stage']!='prepared':
                raise CatalogError('RECOVERY_REQUIRED','unknown HTTP request cannot be resent')
        # 同步网络操作移出事件循环；shield 让取消处理有机会关闭套接字并收齐最终账本状态。
        task=asyncio.create_task(asyncio.to_thread(owner.wire.exchange,'/v1/chat/completions',raw,headers,
            request_key=key,native_request_sha256=digest(canonical(native_request))))
        try:
            _,captured=await asyncio.shield(task)
        except asyncio.CancelledError:
            # Stop the owned socket and observe its final durable receipt before
            # RuntimeJournal recovery can mark this scope's request unknown.
            owner.wire.close()
            try:await task
            except Exception:pass
            raise
        return httpx2.Response(captured['status'],headers=captured['headers'],content=response_bytes(captured))


# 装配官方 Chat 模型适配器，新增的职责仅是持久化意图、计量传输和错误归属。
class GatewayOpenAIModel(Model):
    gateway_metered=True

    # 客户端使用虚拟地址和自定义传输，关闭环境代理与自动重试；真实凭据仅交给网关。
    def __init__(self, journal, state, *, endpoint, credential, execution_contract=None):
        if journal.gateway_binding is None:raise ValueError('persistent gateway binding required')
        self.journal,self.state=journal,state
        self.intent=None;self.http_used=False
        self.wire=GatewayHTTP(journal.budget,journal.gateway_binding['scope_id'],endpoint=endpoint,
            origin=journal.gateway['plan']['origin'],credential=credential,deadline=journal.deadline,
            before_request=lambda request:journal.guard_transport(),checkpoint=journal.checkpoint,
            execution_contract=execution_contract,execution_policy=journal.gateway['execution_policy'])
        self.client=AsyncOpenAI(base_url='http://uteki-gateway.invalid/v1',api_key='uteki-sdk-gateway',
            max_retries=0,http_client=httpx2.AsyncClient(transport=_Transport(self),trust_env=False))
        self.inner=OpenAIChatCompletionsModel(model=journal.profile['model_id'],openai_client=self.client)

    # 固定 SDK 原生请求意图后调用官方适配器，响应确认落盘后再推进恢复游标。
    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):
        self.journal.guard_action()
        if handoffs:raise CatalogError('CAPABILITY_UNSUPPORTED','handoff requires an independently bound profile')
        request=dict(boundary='gateway_sdk_model',system_instructions=system_instructions,
            input=json_value(input),model_settings=json_value(model_settings),
            tools=[dict(name=t.name,description=t.description,schema=t.params_json_schema) for t in tools],
            output_schema=output_schema.json_schema() if output_schema else None,options=json_value(kwargs))
        key,replay=self.state.request(request)
        if replay is not None:raise CatalogError('RECOVERY_REQUIRED','gateway replay must use the original wire receipt')
        self.intent=(key,request);self.http_used=False
        try:
            async with asyncio.timeout(max(0,self.journal.deadline-time.monotonic())):
                response=await self.inner.get_response(system_instructions,input,model_settings,tools,
                    output_schema,handoffs,tracing,**kwargs)
            self.state.responded(json_value(response))
            self.journal.guard_transport()
            return response
        except asyncio.CancelledError:
            self.journal.stop('cancelled');raise
        except TimeoutError:
            self.journal.stop('wall_time');raise
        except APIConnectionError as error:
            # The locked openai 3.13.0 client wraps custom-transport application
            # errors. Keep our existing recovery contract through its public
            # cause chain; ordinary network errors retain the SDK error type.
            cause=error.__cause__
            if isinstance(cause,CatalogError):
                raise CatalogError(cause.code,str(cause).removeprefix(cause.code+': ')) from error
            raise
        finally:
            self.intent=None

    # 同时关闭物理网关连接和官方异步客户端，结束本次运行拥有的传输资源。
    async def close(self):
        self.wire.close()
        await self.client.close()

    # 此冻结 OpenAI 路由只接受非流式响应；不能沿未核验路径启用流式调用。
    async def stream_response(self,*args,**kwargs):
        raise CatalogError('CAPABILITY_UNSUPPORTED','this frozen OpenAI gateway profile is nonstreaming')
        yield
