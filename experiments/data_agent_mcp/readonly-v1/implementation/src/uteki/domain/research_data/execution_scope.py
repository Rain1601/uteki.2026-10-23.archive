"""Explicit execution scope and navigation; independent of frozen v0.3 storage."""
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .query_contract import Contract

EXECUTION_VERSION = "research-execution-v1"


class ExecutionScope(Contract):
    execution_schema_version: Literal["research-execution-v1"] = EXECUTION_VERSION
    snapshot_id: str = Field(min_length=1, max_length=200, pattern=r"\S")
    company_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    source_policy_id: Literal["local-frozen-v1"]
    knowledge_cutoff: date
    include_candidates: bool = False

    @model_validator(mode="after")
    def unique_scope(self):
        for name in ("company_ids", "source_snapshot_ids"):
            values = getattr(self, name)
            if any(not value.strip() or value != value.strip() or len(value) > 200 for value in values):
                raise ValueError(f"{name} requires nonblank, unpadded identifiers")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} requires unique identifiers")
        return self


class SourceOutlineRequest(Contract):
    source_snapshot_id: str = Field(min_length=1, max_length=200, pattern=r"\S")


class NavigationCursor(Contract):
    cursor_version: Literal["document-cursor-v1"] = "document-cursor-v1"
    scope_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    source_snapshot_id: str = Field(min_length=1)
    index_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)


class ReadCursor(NavigationCursor):
    kind: Literal["read"] = "read"
    start_block_id: str = Field(min_length=1)


class SearchCursor(NavigationCursor):
    kind: Literal["search"] = "search"
    phrase: str = Field(min_length=1, max_length=200, pattern=r"\S")
    offset: int = Field(ge=0)


class SourceReadRequest(SourceOutlineRequest):
    node_id: str = Field(min_length=1, max_length=300, pattern=r"\S")
    start_block_id: str | None = Field(default=None, min_length=1, max_length=300, pattern=r"\S")
    count: int = Field(default=8, ge=1, le=12)
    cursor: ReadCursor | None = None


class SourceSearchRequest(SourceOutlineRequest):
    node_id: str = Field(min_length=1, max_length=300, pattern=r"\S")
    phrase: str = Field(min_length=1, max_length=200, pattern=r"\S")
    offset: int | None = Field(default=None, ge=0,
                              description="Null starts at zero, or resumes from the supplied cursor.")
    limit: int = Field(default=8, ge=1, le=20)
    cursor: SearchCursor | None = None
