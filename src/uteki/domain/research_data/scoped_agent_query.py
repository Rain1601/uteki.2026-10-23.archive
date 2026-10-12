"""Source-scoped Agent execution, leaving saved v0.2 requests unchanged."""
from typing import Literal

from pydantic import Field, model_validator

from .agent_query import AnswerPart, ContextRequest, QueryPlan
from .execution_scope import ExecutionScope, SourceOutlineRequest, SourceReadRequest, SourceSearchRequest
from .query_contract import Contract
from .figure_evidence import FigureBundleRef

SCOPED_AGENT_VERSION = "data-agent-query-v0.3"


class ScopedAgentQuery(Contract):
    agent_schema_version: Literal["data-agent-query-v0.3"] = SCOPED_AGENT_VERSION
    question: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    scope: ExecutionScope
    figure_bundle_ref: FigureBundleRef | None = Field(default=None, exclude_if=lambda value: value is None)


class ScopedPlannerDecision(Contract):
    action: Literal["query", "read_context", "outline_source", "read_source", "search_source", "finish", "clarify"]
    plan: QueryPlan | None = None
    context: ContextRequest | None = None
    outline: SourceOutlineRequest | None = None
    read: SourceReadRequest | None = None
    search: SourceSearchRequest | None = None
    answer_parts: tuple[AnswerPart, ...] = Field(default=(), max_length=16)
    clarification: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def exclusive_payload(self):
        present = {"query": self.plan is not None, "read_context": self.context is not None,
                   "outline_source": self.outline is not None, "read_source": self.read is not None,
                   "search_source": self.search is not None, "finish": bool(self.answer_parts),
                   "clarify": bool(self.clarification and self.clarification.strip())}
        if not present[self.action] or sum(present.values()) != 1:
            raise ValueError("provide only the payload required by the selected action")
        return self
