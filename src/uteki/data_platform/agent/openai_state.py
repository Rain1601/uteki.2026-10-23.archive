"""Persist public SDK checkpoints and replay only exact, durably answered requests."""
from copy import deepcopy
from importlib.metadata import version
import json
import uuid

from agents import ModelResponse, RunContextWrapper, RunState
from pydantic import TypeAdapter

from ..contracts.common import CatalogError, canonical, digest
from ..contracts.content import ObjectRef


# 管理公开 RunState 检查点及按序请求凭据；恢复依赖原始绑定，不能重建猜测的对话。
class OpenAIState:
    # cursor 指向当前 SDK 已消费的请求前缀，独立于账本中可能更长的物理请求历史。
    def __init__(self, journal, binding):
        self.journal, self.binding = journal, binding
        self.cursor = 0

    # 从内容寻址存储读取规范 JSON；无法验证的状态统一要求恢复处置。
    def read(self, reference):
        try:
            raw = self.journal.catalog.content.read_object(ObjectRef.model_validate(reference))
            value = json.loads(raw)
            if canonical(value) != raw:
                raise ValueError('noncanonical SDK state object')
            return value
        except (ValueError, OSError) as error:
            raise CatalogError('RECOVERY_REQUIRED','saved OpenAI state/request cannot be verified') from error

    # 新运行创建 RunState；恢复时核验 SDK 版本、会话身份、请求前缀及已确认响应。
    async def load(self, agent):
        native = self.journal.state()
        if native.get('openai_checkpoint') is None:
            if self.journal.resuming:
                raise CatalogError('RECOVERY_REQUIRED','original OpenAI checkpoint is missing')
            state = RunState(RunContextWrapper(None),canonical(self.binding.context).decode(),agent,
                             self.journal.limits.native_max_turns)
            self.save(state)
            return state
        saved = self.read(native['openai_checkpoint'])
        requests = native.get('openai_requests',[])
        try:
            if (saved['format']!='uteki-openai-run-state-v1' or saved['sdk_version']!=version('openai-agents')
                    or saved['context_ref']!=self.journal.context_ref or saved['binding']!=native['binding']
                    or saved['native_session_id']!=native['native_session_id']
                    or requests[:len(saved['requests'])]!=saved['requests']):
                raise ValueError('checkpoint binding or request prefix differs')
            self.cursor = len(saved['requests'])
            keys = [r['request_key'] for r in requests]
            if len(keys)!=len(set(keys)):
                raise ValueError('duplicate physical request identity')
            records = [r for r in self.journal.budget.inspect_requests()
                       if r['request']['context_ref']==self.journal.context_ref]
            if not {r['request_key'] for r in records} <= set(keys):
                raise ValueError('a physical request is absent from the SDK request order')
            for item in requests[:self.cursor]:
                record = self.journal.budget.inspect_request(item['request_key'])
                if (record['stage']!='responded' or not self.record_matches(record,self.read(item['request_ref']))
                        or record['response_event']['response'].get('complete') is not True):
                    raise ValueError('checkpoint consumes a request without a complete bound response')
                if self.journal.gateway_binding is not None:
                    if record['cost_state'] not in {'settled','bounded'} or item.get('response_ref') is None:
                        raise ValueError('gateway checkpoint lacks a confirmed SDK response or bill')
                    TypeAdapter(ModelResponse).validate_python(self.read(item['response_ref']))
            # 只能恢复检查点已经观察到的引用；稍后的工具返回需再次越过模型输入边界。
            visible = {canonical(r) for r in saved['visible_results']}
            if not visible <= {canonical(r) for r in native['observed_results']}:
                raise ValueError('checkpoint claims results not observed in this native run')
            state = await RunState.from_json(agent,saved['state'])
        except Exception as error:
            raise CatalogError('RECOVERY_REQUIRED','OpenAI checkpoint binding or public SDK restore failed') from error
        # Eligibility is not visibility: only the saved observed prefix is
        # visible now. Later replayed outputs must cross a model-input hook.
        self.binding.returned = [deepcopy(c['output']) for c in native['tool_calls'].values()
                                 if c['output'] is not None]
        self.binding.visible = visible
        return state

    # 同时保存 SDK 原生状态、已消费请求前缀和可见证据，形成一致的恢复检查点。
    def save(self, state):
        session = self.journal.session()
        native = session.data['native_execution']
        value = dict(format='uteki-openai-run-state-v1',sdk_version=version('openai-agents'),
            context_ref=self.journal.context_ref,native_session_id=native['native_session_id'],
            binding=native['binding'],requests=deepcopy(native.get('openai_requests',[])[:self.cursor]),
            visible_results=[json.loads(r) for r in sorted(self.binding.visible)],state=state.to_json())
        native['openai_checkpoint'] = self.journal.catalog.content.put_object(canonical(value)).model_dump(mode='json')
        session.save()
        self.journal.checkpoint('openai_state_committed')

    # 为当前位置先落盘请求意图；恢复必须逐项精确匹配，不能把变化后的请求当重试。
    def request(self, request):
        session = self.journal.session()
        requests = session.data['native_execution'].setdefault('openai_requests',[])
        if self.cursor > len(requests):
            raise CatalogError('RECOVERY_REQUIRED','OpenAI request position is outside its durable history')
        if self.cursor == len(requests):
            item = dict(request_key='model:'+uuid.uuid4().hex,
                request_ref=self.journal.catalog.content.put_object(canonical(request)).model_dump(mode='json'))
            requests.append(item)
            session.save()
            self.journal.checkpoint('openai_request_intent')
        else:
            item = requests[self.cursor]
            if self.read(item['request_ref'])!=request:
                raise CatalogError('RECOVERY_REQUIRED','resumed SDK request differs from the original; no replay or resend')
        record = next((r for r in self.journal.budget.inspect_requests() if r['request_key']==item['request_key']),None)
        if record is not None:
            if not self.record_matches(record,request):
                raise CatalogError('RECOVERY_REQUIRED','physical request and SDK intent bindings differ')
            if record['stage']=='responded':
                response = record['response_event']['response']
                if response.get('complete') is not True or record['cost_state'] not in {'settled','bounded'}:
                    raise CatalogError('RECOVERY_REQUIRED','saved response or fee is incomplete')
                # 网关恢复交给官方客户端解析原始 HTTP 收据，避免单独的响应缓存替代线缆证据。
                if self.journal.gateway_binding is not None:
                    # The official client parses the exact saved wire bytes
                    # again. Never trust a separate cache as a model response.
                    return item['request_key'],None
                try:
                    value = TypeAdapter(ModelResponse).validate_python(response['response'])
                except (ValueError,KeyError) as error:
                    raise CatalogError('RECOVERY_REQUIRED','saved ModelResponse cannot be restored') from error
                self.cursor += 1
                self.journal.checkpoint('openai_response_replayed')
                return item['request_key'],value
            # 已发出但未确认的请求可能产生费用，保持未知状态，禁止自动再次发送。
            if record['stage']!='prepared':
                raise CatalogError('RECOVERY_REQUIRED','physical request outcome is unknown; never resend')
        return item['request_key'],None

    # 对齐 SDK 意图与账本归属；网关额外绑定根任务、控制范围、来源及原生请求摘要。
    def record_matches(self, record, request):
        if self.journal.gateway_binding is None:
            return record['request']==dict(run_id=self.journal.context['run_id'],context_ref=self.journal.context_ref,
                profile=self.journal.profile,request=request)
        metadata=record['request']
        expected=dict(boundary='gateway_http',context_ref=self.journal.context_ref,
            business_root_run_id=self.journal.context['root_run_id'],profile=self.journal.profile,
            origin=self.journal.gateway['plan']['origin'],native_request_sha256=digest(canonical(request)))
        return (record.get('control_scope_id')==self.journal.gateway_binding['scope_id']
            and all(metadata.get(key)==value for key,value in expected.items()))

    # 网关先持久化官方 SDK 解析结果再推进游标；同一物理请求不能对应变化后的响应。
    def responded(self, response=None):
        if self.journal.gateway_binding is not None:
            if response is None:raise ValueError('gateway SDK response required')
            session=self.journal.session()
            item=session.data['native_execution']['openai_requests'][self.cursor]
            reference=self.journal.catalog.content.put_object(canonical(response)).model_dump(mode='json')
            if item.get('response_ref') is not None and item['response_ref']!=reference:
                raise CatalogError('RECOVERY_REQUIRED','SDK response changed for the same physical request')
            item['response_ref']=reference
            session.save()
            self.journal.checkpoint('openai_gateway_response_committed')
        self.cursor += 1
