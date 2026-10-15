"""Business plans and delivery requests, independent of any agent SDK."""
from __future__ import annotations

from typing import Annotated, Awaitable, Literal, Protocol
from pydantic import Field, model_validator
from .common import Contract, Text, id_type


class QueryRuntime(Protocol):
    """Injected application binding; business contracts import no SDK types."""
    def __call__(self, service, context_ref: str, *, recover: bool,
                 started: float) -> Awaitable[dict]: ...


class ResultRef(Contract):
    run_id: id_type('run')
    operation_id: id_type('op')
    kind: Literal['evidence', 'record', 'calculation']
    item_id: Text


class Need(Contract):
    need_id: Text
    description: Text
    required: bool


class PlanUpdate(Contract):
    base_version: Annotated[int, Field(ge=0)]
    needs: Annotated[tuple[Need, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode='after')
    def unique(self):
        if len({n.need_id for n in self.needs}) != len(self.needs):
            raise ValueError('duplicate needs')
        return self


class Satisfied(Contract):
    need_id: Text
    result_refs: Annotated[tuple[ResultRef, ...], Field(min_length=1)]


class Gap(Contract):
    need_id: Text
    missing: Text
    result_refs: tuple[ResultRef, ...] = ()


class TaskState(Contract):
    plan_update: PlanUpdate | None = None
    satisfied: tuple[Satisfied, ...]
    gaps: tuple[Gap, ...]
    next_action: Text
    reason: Text


class DeliveryNeed(Contract):
    need_id: Text
    status: Literal['supported', 'partial', 'unresolved']
    result_refs: tuple[ResultRef, ...]
    gaps: tuple[Text, ...]
    note: str | None = None


class Conflict(Contract):
    need_id: Text
    result_refs: Annotated[tuple[ResultRef, ...], Field(min_length=2)]
    description: Text


class DeliveryRequest(Contract):
    needs: tuple[DeliveryNeed, ...]
    conflicts: tuple[Conflict, ...] = ()
    stop_reason: Literal['delivered'] = 'delivered'


class ClarifyRequest(Contract):
    question: Text
    blocking_need_ids: Annotated[tuple[Text, ...], Field(min_length=1)]

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.blocking_need_ids)) != len(self.blocking_need_ids):
            raise ValueError('duplicate blocking need IDs')
        return self


class RuntimeLimits(Contract):
    """Explicit SDK/transport limits, distinct from business tool turn counts."""
    native_max_turns: Annotated[int, Field(ge=1, le=1000)]
    max_model_requests: Annotated[int, Field(ge=1, le=1000)]
    max_request_bytes: Annotated[int, Field(ge=1)]
    max_response_bytes: Annotated[int, Field(ge=1)]


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
    mode: Literal['offline']
    real_model_calls: Literal[0]
    gateway_cost_usd: None

    @model_validator(mode='after')
    def consistent(self):
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
        if (self.committed_delivery is not None and self.committed_delivery!=self.delivery
                or self.committed_clarification is not None and self.committed_clarification!=self.clarification):
            raise ValueError('committed aliases must retain the same accepted business payload')
        return self
