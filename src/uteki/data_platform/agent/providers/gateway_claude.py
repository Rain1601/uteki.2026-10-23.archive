"""Private HTTP bridge for the official Claude CLI, with no replacement loop."""
from __future__ import annotations

import asyncio
import json
import time

from ...contracts.common import CatalogError, canonical
from .gateway_http import GatewayHTTP, GatewayProxy, _pairs, _constant


def routed_request(raw, profile):
    """Add only the host-frozen OpenRouter route; leave native content intact.

    Claude's Messages client has no provider-selection option. This transport
    adaptation does not choose a model, change instructions or repair tool calls.
    Conflicting controls are errors, never silently overwritten.
    """
    if profile['route']['provider'] != 'openrouter' or profile.get('request_controls') is None:
        return raw
    request = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(request, dict):
        raise ValueError('gateway_request_object_required')
    expected = dict(only=profile['route']['upstream'], order=profile['route']['upstream'],
                    allow_fallbacks=False, require_parameters=True)
    if 'provider' in request:
        if request['provider'] != expected:
            raise ValueError('gateway_provider_controls_differ')
        return raw
    return canonical(request | {'provider': expected})


# 将官方 Claude CLI 接到共享计量网关，CLI 仍负责解析响应与调度业务工具。
class GatewayClaudeTransport:
    # 绑定既有账本 scope，并用私有回环代理隔离 CLI 与实际上游凭据。
    def __init__(self, journal, *, endpoint, credential, observed_request, validate_request,
                 execution_contract=None):
        if journal.gateway_binding is None:
            raise ValueError('persistent gateway binding required')
        self.journal=journal
        self.loop=asyncio.get_running_loop()
        self.observed_request,self.validate_request=observed_request,validate_request
        self.wire=GatewayHTTP(journal.budget,journal.gateway_binding['scope_id'],endpoint=endpoint,
            origin=journal.gateway['plan']['origin'],credential=credential,deadline=journal.deadline,
            before_request=self.before_request,checkpoint=lambda phase:self.callback(journal.checkpoint,phase),
            execution_contract=execution_contract,execution_policy=journal.gateway['execution_policy'])
        self.deadline,self.transport=self.wire.deadline,self.wire.transport
        self.proxy=GatewayProxy(self)
        self.base_url,self.token,self.events=self.proxy.base_url,self.proxy.token,self.proxy.events

    # 请求线程通过原事件循环更新 RuntimeJournal，回调等待也遵守全局截止时间。
    def callback(self, function, *args):
        async def invoke():return function(*args)
        future=asyncio.run_coroutine_threadsafe(invoke(),self.loop)
        try:return future.result(timeout=max(.01,self.deadline-time.monotonic()))
        except BaseException:
            future.cancel()
            raise

    # 请求发送前同时检查业务可继续状态和恢复历史，防止未核验上下文进入上游。
    def before_request(self, request):
        self.callback(self.journal.guard_action)
        self.callback(self.validate_request,request)

    # 代理入口与物理传输复用同一预算、停止状态和截止时间检查。
    def guard(self):self.wire.guard()

    # 原始响应落盘后确认费用，再把请求中的工具结果标记为可见，最后返回给 CLI。
    def exchange(self, path, raw, headers):
        try:
            native_raw=raw
            raw=routed_request(raw,self.wire.profile)
            key,captured=self.wire.exchange(path,raw,headers,
                native_http_body=native_raw if raw!=native_raw else None)
            # Messages usage is not a bill. Keep the raw SSE unchanged and
            # settle its observed generation before the CLI can run tools.
            if self.journal.budget.inspect_request(key)['cost_state'] not in {'settled','bounded'}:
                # 响应已落盘但身份或账单无法核实时，费用仍为未知预留，须走恢复而非普通模型失败。
                try:
                    self.wire.observe_bill(key)
                except CatalogError:
                    raise
                except Exception as error:
                    # Only the type: exception text may carry private request data.
                    raise CatalogError('RECOVERY_REQUIRED','received response has no verifiable generation '
                        'identity or bill: '+type(error).__name__) from error
            self.callback(self.journal.guard_action)
            request=self.wire.validate_request(path,raw,{k.lower():v for k,v in headers.items()})
            self.callback(self.observed_request,request)
            return key,captured
        except Exception as error:
            if isinstance(error,CatalogError):
                self.callback(setattr,self.journal,'failure_code',error.code)
            raise

    # 关闭物理连接可打断进行中的网络读写，禁止取消后继续打开连接。
    def close(self):self.wire.close()

    # 启动私有回环代理；其地址和随机令牌仅供本次隔离 CLI 使用。
    async def __aenter__(self):
        self.proxy.__enter__()
        return self

    # 工作线程可能等待本事件循环回调，因此清理和线程 join 必须移到循环之外。
    async def __aexit__(self,*errors):
        # Request threads may be awaiting a journal callback on this loop.
        # Join them off-loop so cleanup cannot deadlock that callback.
        await asyncio.to_thread(self.proxy.__exit__,*errors)
