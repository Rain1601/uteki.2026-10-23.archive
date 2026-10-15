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


class _Transport(httpx2.AsyncBaseTransport):
    def __init__(self, owner):
        self.owner=owner

    async def handle_async_request(self, request):
        owner=self.owner
        if (request.method!='POST' or str(request.url)!='http://uteki-gateway.invalid/v1/chat/completions'
                or owner.intent is None or owner.http_used):
            raise CatalogError('CAPABILITY_UNSUPPORTED','unbound or additional native HTTP request')
        owner.http_used=True
        key,native_request=owner.intent
        raw=await request.aread()
        headers=dict(request.headers)
        owner.wire.validate_request('/v1/chat/completions',raw,headers)
        record=next((r for r in owner.journal.budget.inspect_requests() if r['request_key']==key),None)
        if record is not None:
            metadata=record['request']
            if (not owner.state.record_matches(record,native_request)
                    or metadata.get('method')!='POST' or metadata.get('path')!='/v1/chat/completions'
                    or metadata.get('body_sha256')!=digest(raw)
                    or base64.b64decode(metadata.get('body_base64',''),validate=True)!=raw):
                raise CatalogError('RECOVERY_REQUIRED','native HTTP request differs; no replay or resend')
            if record['stage']=='responded':
                saved=record['response_event']['response']
                if not saved.get('complete') or record['cost_state']!='settled':
                    raise CatalogError('RECOVERY_REQUIRED','saved HTTP response or bill is incomplete')
                captured=saved['http']
                owner.journal.checkpoint('openai_gateway_wire_replayed')
                return httpx2.Response(captured['status'],headers=captured['headers'],content=response_bytes(captured))
            if record['stage']!='prepared':
                raise CatalogError('RECOVERY_REQUIRED','unknown HTTP request cannot be resent')
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


class GatewayOpenAIModel(Model):
    gateway_metered=True

    def __init__(self, journal, state, *, endpoint, credential, execution_contract=None):
        if journal.gateway_binding is None:raise ValueError('persistent gateway binding required')
        self.journal,self.state=journal,state
        self.intent=None;self.http_used=False
        self.wire=GatewayHTTP(journal.budget,journal.gateway_binding['scope_id'],endpoint=endpoint,
            origin=journal.gateway['plan']['origin'],credential=credential,deadline=journal.deadline,
            before_request=lambda request:journal.guard_transport(),checkpoint=journal.checkpoint,
            execution_contract=execution_contract)
        self.client=AsyncOpenAI(base_url='http://uteki-gateway.invalid/v1',api_key='uteki-sdk-gateway',
            max_retries=0,http_client=httpx2.AsyncClient(transport=_Transport(self),trust_env=False))
        self.inner=OpenAIChatCompletionsModel(model=journal.profile['model_id'],openai_client=self.client)

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

    async def close(self):
        self.wire.close()
        await self.client.close()

    async def stream_response(self,*args,**kwargs):
        raise CatalogError('CAPABILITY_UNSUPPORTED','this frozen OpenAI gateway profile is nonstreaming')
        yield
