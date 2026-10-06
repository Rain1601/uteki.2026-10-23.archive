"""Natural-language Data Agent boundary, separate from immutable dataset schemas."""
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .query_contract import Contract, RecordRequest, DocumentRequest, CalculationRequest

AGENT_VERSION = "data-agent-query-v0.2"


class AgentQuery(Contract):
    question: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    company_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    snapshot_id: str = Field(min_length=1)
    source_policy_id: Literal["local-frozen-v1"]
    knowledge_cutoff: date
    include_candidates: bool = False

    @model_validator(mode="after")
    def explicit_companies(self):
        if any(not c.strip() for c in self.company_ids) or len(set(self.company_ids)) != len(self.company_ids):
            raise ValueError("company scope must contain unique, nonblank IDs")
        return self


class QueryPlan(Contract):
    records: tuple[RecordRequest, ...] = Field(default=(), max_length=16)
    documents: tuple[DocumentRequest, ...] = Field(default=(), max_length=4)
    calculations: tuple[CalculationRequest, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def nonempty(self):
        if not (self.records or self.documents or self.calculations):
            raise ValueError("empty query plan")
        return self


class ContextRequest(Contract):
    source_snapshot_id: str
    block_id: str


class AnswerPart(Contract):
    # This labels the requested subquestion. Financial values are rendered from
    # referenced tool results, never copied or recomputed by the planner.
    requested_information: str = Field(min_length=1, max_length=500)
    record_ids: tuple[str, ...] = Field(default=(), max_length=256)
    computed_ids: tuple[str, ...] = Field(default=(), max_length=32)
    context_ids: tuple[str, ...] = Field(default=(), max_length=16)
    gap_ids: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def referenced(self):
        if not (self.record_ids or self.computed_ids or self.context_ids or self.gap_ids):
            raise ValueError("each answer part must reference retrieved data or an observed gap")
        return self


class PlannerDecision(Contract):
    action: Literal["query", "read_context", "finish", "clarify"]
    plan: QueryPlan | None = None
    context: ContextRequest | None = None
    answer_parts: tuple[AnswerPart, ...] = Field(default=(), max_length=16)
    clarification: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def exclusive_payload(self):
        present = {"query": self.plan is not None, "read_context": self.context is not None,
                   "finish": bool(self.answer_parts), "clarify": bool(self.clarification and self.clarification.strip())}
        if not present[self.action] or sum(present.values()) != 1:
            raise ValueError("provide only the payload required by the selected action")
        return self
