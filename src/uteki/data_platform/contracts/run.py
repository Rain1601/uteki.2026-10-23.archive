"""Business plans and delivery requests, independent of any agent SDK."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import Field, model_validator
from .common import Contract, Text, id_type


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
