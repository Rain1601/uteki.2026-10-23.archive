"""Business plans and delivery requests, independent of any agent SDK."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Awaitable, Literal, Protocol
from pydantic import Field, model_validator
from .common import Contract, Text, id_type, canonical, digest


# 运行时注入协议：业务层只依赖可等待的调用结果，不把某个 Agent SDK 类型写入契约。
class QueryRuntime(Protocol):
    """Injected application binding; business contracts import no SDK types."""
    # 接收服务、上下文引用、恢复标记和起始时间，返回异步运行结果字典。
    def __call__(self, service, context_ref: str, *, recover: bool,
                 started: float) -> Awaitable[dict]: ...


# 用运行、操作、结果类型和项目 ID 定位已经产生的结果，避免把未来结果当作现有依据。
class ResultRef(Contract):
    """Copy a returned result reference. Metadata describes registered assets or parser output, not source facts. Never construct a ResultRef from an AssetRef."""
    run_id: id_type('run')
    operation_id: id_type('op')
    kind: Literal['evidence', 'record', 'calculation', 'metadata']
    item_id: Text


class SourceQuote(Contract):
    result_ref: ResultRef
    quote: Text = Field(description='Exact nonempty quote from a previously returned source evidence item.')


class SourceClaim(Contract):
    statement: Text = Field(description='Source-based interpretation. Each claim needs exact quoted source support; code verifies quote presence, not semantic entailment. Do not claim independent verification.')
    support: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=8)]


def result_handle(reference):
    """A deterministic display handle; authorization still uses the full reference."""
    value = ResultRef.model_validate(reference).model_dump(mode='json')
    return 'rr_' + digest(canonical(value))[:16]


# 计划中的独立业务需求，required 标记其是否为必需交付项。
class Need(Contract):
    need_id: Text
    description: Text
    required: bool


# 携带基准版本的完整计划提案；这里验证结构，提交、保留旧需求等规则由应用层检查。
class PlanUpdate(Contract):
    base_version: Annotated[int, Field(ge=0, description='Current committed plan.version, initially 0. A rejected preflight does not commit this update.')]
    needs: Annotated[tuple[Need, ...], Field(min_length=1, max_length=100,
        description='Complete plan. Preserve every existing need unchanged; additions are allowed. Account for every need in satisfied or gaps in this same call.')]

    # 同一计划内 need_id 不能重复，否则后续满足状态无法唯一归属。
    @model_validator(mode='after')
    def unique(self):
        if len({n.need_id for n in self.needs}) != len(self.needs):
            raise ValueError('duplicate needs')
        return self


# 声明需求由已返回引用支撑；应用层核对引用及状态一致性，不证明业务内容充分。
class Satisfied(Contract):
    need_id: Text
    result_refs: Annotated[tuple[ResultRef, ...], Field(min_length=1)]


# 保留未满足需求及缺失内容，可附已获得但尚不足以支撑交付的结果。
class Gap(Contract):
    need_id: Text
    missing: Text
    result_refs: tuple[ResultRef, ...] = ()


# 每次业务调用提交的任务状态：完整覆盖需求状态，并说明当前工具和调用原因。
class TaskState(Contract):
    plan_update: PlanUpdate | None = Field(default=None, description='Required until a nonempty plan is committed. An accepted call commits its update even when it returns zero items. Omit plan_update after that unless adding needs. After an error use current_task_state.plan; do not resend a committed base_version.')
    satisfied: tuple[Satisfied, ...] = Field(description='Needs supported by result_refs already returned to this run. Together with gaps, cover every need in the effective plan exactly once, including newly proposed needs.')
    gaps: tuple[Gap, ...] = Field(description='Every need not yet supported, with the missing evidence. On the first call all new needs belong here; no future result_refs. Do not omit unresolved needs.')
    next_action: Text = Field(description='Exact name of the tool being called now, e.g. find_assets. Not a sentence, future step, or SDK MCP prefix.')
    reason: Text = Field(description='Brief reason for the current action, not private reasoning.')


# 面向模型的任务状态增量：宿主保留未变化需求、计划版本和当前工具名，不推断满足与否。
class TaskProgress(Contract):
    add_needs: Annotated[tuple[Need, ...], Field(max_length=100)] = Field(default=(),
        description='Initial needs on the first call, or NEW needs only later. Never repeat or rewrite existing needs.')
    satisfied: tuple[Satisfied, ...] = Field(default=(),
        description='Only changed needs now supported by previously observed references. Omitted needs retain committed status.')
    gaps: tuple[Gap, ...] = Field(default=(),
        description='Only changed unresolved needs. Omitted needs retain committed status; new needs start unresolved.')
    reason: Text


# 交付中逐项声明支持程度、结果引用和缺口，避免把部分证据表述为完全解决。
class DeliveryNeed(Contract):
    need_id: Text
    status: Literal['supported', 'partial', 'unresolved'] = Field(description='Whether this requested task is fulfilled. Disclosing known source limitations can fulfill a disclosure task; proving source quality requires evidence. Never label missing requested content as a mere limitation.')
    result_refs: tuple[ResultRef, ...]
    gaps: tuple[Text, ...] = Field(description='Unfulfilled parts of this requested task. Nonempty gaps require partial/unresolved; do not use this field merely because disclosed source quality is partial.')
    limitations: tuple[Text, ...] = Field(default=(), description='Disclosed qualifications of the delivered result, distinct from missing requested work. They do not automatically change task status. Keep actual missing requested evidence in gaps.')
    note: str | None = None
    source_claims: Annotated[tuple[SourceClaim, ...], Field(max_length=20)] = Field(default=(), description='Only include source claims needed by the question, with quotes from evidence in this need. Metadata cannot support a source claim. Pagination/coverage is generated by code; do not restate it here.')


# 保留同一需求下至少两个互相冲突的结果引用及冲突说明。
class Conflict(Contract):
    need_id: Text
    result_refs: Annotated[tuple[ResultRef, ...], Field(min_length=2)]
    description: Text


# 业务交付提案包含需求结果和冲突；是否可以接受由交付组装与核验层决定。
class DeliveryRequest(Contract):
    needs: tuple[DeliveryNeed, ...]
    conflicts: tuple[Conflict, ...] = ()
    stop_reason: Literal['delivered'] = 'delivered'


# 将一个澄清问题绑定到被阻塞的需求，便于后续回答修订正确上下文。
class ClarifyRequest(Contract):
    question: Text
    blocking_need_ids: Annotated[tuple[Text, ...], Field(min_length=1)]

    # 阻塞需求 ID 不允许重复，避免同一需求被重复计入澄清范围。
    @model_validator(mode='after')
    def unique(self):
        if len(set(self.blocking_need_ids)) != len(self.blocking_need_ids):
            raise ValueError('duplicate blocking need IDs')
        return self


# SDK/传输层限制与业务工具轮次分开计数，覆盖模型请求数和单次请求/响应大小。
class RuntimeLimits(Contract):
    """Explicit SDK/transport limits, distinct from business tool turn counts."""
    native_max_turns: Annotated[int, Field(ge=1, le=1000)]
    max_model_requests: Annotated[int, Field(ge=1, le=1000)]
    max_request_bytes: Annotated[int, Field(ge=1)]
    max_response_bytes: Annotated[int, Field(ge=1)]


# 统一运行结果同时保留业务交付、SDK 成功状态和对账需求，三者不能相互替代。
class RunQueryResult(Contract):
    """Versioned business result; SDK success and reconciliation are separate."""
    schema_version: Literal['uteki-run-query-result-v1']
    kind: Literal['delivery','needs_clarification','failed','recovery_required']
    status: Literal['completed','partial','cancelled','needs_clarification','failed']
    terminal: bool
    reconciliation_required: bool
    native_success: bool
    error: str | None
    native_error: str | None = None
    delivery: dict | None = None
    clarification: dict | None = None
    committed_delivery: dict | None = None
    committed_clarification: dict | None = None
    profile: dict
    native_events: list[dict]
    tool_events: list[dict]
    runtime: dict
    mode: Literal['offline','gateway_synthetic','remote']
    real_model_calls: Annotated[int, Field(ge=0)]
    gateway_cost_usd: str | None

    # 检查模式、费用、终止状态和业务载荷的一致性；恢复状态必须保留未完成对账。
    @model_validator(mode='after')
    def consistent(self):
        # 离线/合成运行不得声明真实模型请求或费用；远端已知费用必须是有限非负十进制金额。
        if self.mode!='remote' and (self.real_model_calls!=0 or self.gateway_cost_usd is not None):
            raise ValueError('nonremote execution cannot claim real requests or costs')
        if self.gateway_cost_usd is not None:
            try:amount=Decimal(self.gateway_cost_usd)
            except InvalidOperation:raise ValueError('invalid gateway charge') from None
            if not amount.is_finite() or amount<0:raise ValueError('invalid gateway charge')
        # 需要恢复意味着上下文尚未终止；业务交付、澄清和失败必须各自匹配规定的载荷形状。
        if self.terminal != (self.kind!='recovery_required'):
            raise ValueError('recovery is nonterminal; other results end this context')
        if self.kind=='delivery':
            if (self.delivery is None or self.clarification is not None or self.error is not None
                    or self.status not in {'completed','partial','cancelled'}
                    or self.delivery.get('kind')!='delivery'
                    or self.delivery.get('delivery',{}).get('business_status','completed')!=self.status):
                raise ValueError('delivery kind, status and payload differ')
        elif self.kind=='needs_clarification':
            if (self.clarification is None or self.delivery is not None or self.error is not None
                    or self.status!='needs_clarification' or self.clarification.get('kind')!='needs_clarification'):
                raise ValueError('clarification kind, status and payload differ')
        elif (self.delivery is not None or self.clarification is not None or self.status!='failed' or not self.error):
            raise ValueError('failure/recovery cannot claim a business delivery')
        if self.kind=='recovery_required' and not self.reconciliation_required:
            raise ValueError('recovery must retain its reconciliation requirement')
        # 兼容字段必须保留同一份已接受业务载荷，防止别名与主字段表达不同交付。
        if (self.committed_delivery is not None and self.committed_delivery!=self.delivery
                or self.committed_clarification is not None and self.committed_clarification!=self.clarification):
            raise ValueError('committed aliases must retain the same accepted business payload')
        return self
