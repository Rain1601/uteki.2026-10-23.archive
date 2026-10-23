"""Official Model extension for bounded, durable scripted model calls only."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from enum import Enum
import time

from agents import Model

from ..contracts.common import CatalogError, canonical


# 将 SDK 对象递归转为可持久化 JSON，保留字段别名及未设置字段与显式 null 的区别。
def json_value(value):
    if hasattr(value, 'model_dump'):
        # SDK models have wire aliases (e.g. async/async_) and distinguish
        # omitted fields from explicitly supplied null. Both must survive.
        return value.model_dump(mode='json',by_alias=True,exclude_unset=True)
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k:json_value(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [json_value(v) for v in value]
    if value is None or type(value) in {str,int,float,bool}:
        return value
    raise ValueError('Unsupported value at the durable model boundary: '+type(value).__name__)


# 包装明确标记的离线脚本模型，复用请求账本、截止时间及恢复能力，不发真实模型请求。
class OfflineMeteredModel(Model):
    offline_fixture = True

    def __init__(self, inner, journal, *, state=None):
        if getattr(inner, 'offline_fixture', False) is not True:
            raise ValueError('offline metering requires an explicitly scripted model')
        self.inner, self.journal = inner, journal
        self.state = state

    # 先冻结请求意图并尝试精确重放，再登记调用；完整响应落盘后才推进 SDK 恢复游标。
    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):
        self.journal.guard_action()
        if handoffs:
            raise CatalogError('CAPABILITY_UNSUPPORTED', 'handoff metering requires a separately bound task profile')
        request = dict(boundary='scripted_sdk_model', system_instructions=system_instructions,
            input=json_value(input), model_settings=json_value(model_settings),
            tools=[dict(name=t.name, description=t.description, schema=t.params_json_schema) for t in tools],
            output_schema=output_schema.json_schema() if output_schema else None, options=json_value(kwargs))
        key = None
        if self.state is not None:
            key, replay = self.state.request(request)
            if replay is not None:
                return replay
        key = self.journal.prepare_model(request,request_key=key)
        try:
            async with asyncio.timeout(max(0, self.journal.deadline-time.monotonic())):
                response = await self.inner.get_response(system_instructions, input, model_settings,
                    tools, output_schema, handoffs, tracing, **kwargs)
            body = json_value(response)
            if len(canonical(body)) > self.journal.limits.max_response_bytes:
                raise CatalogError('RESPONSE_TOO_LARGE', 'model response exceeds the explicit response bound')
            self.journal.record_model(key, dict(complete=True, response=body), complete=True)
            if self.state is not None:
                self.state.responded()
            self.journal.guard_transport()
            return response
        # 已登记发送却没有完整结果时保存失败记录；取消和超时同时停止后续业务动作。
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                self.journal.stop('cancelled')
            elif isinstance(error, TimeoutError):
                self.journal.stop('wall_time')
            saved = self.journal.budget.inspect_request(key)
            if saved['stage'] == 'dispatched':
                self.journal.record_model(key, dict(complete=False, error_type=type(error).__name__), complete=False)
            raise

    # 当前离线适配器未定义流式持久化契约，显式报不支持，不能静默转成另一种调用。
    async def stream_response(self, *args, **kwargs):
        raise CatalogError('CAPABILITY_UNSUPPORTED', 'scripted streaming needs an explicit verified adapter')
        yield
