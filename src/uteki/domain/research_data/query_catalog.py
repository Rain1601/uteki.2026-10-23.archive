"""Bounded, source-scoped catalog views; separate from frozen query protocols."""
from typing import Literal

from pydantic import Field

from .query_contract import Contract


class CatalogCursor(Contract):
    version: Literal['query-catalog-cursor-v1'] = 'query-catalog-cursor-v1'
    snapshot_id: str
    scope_id: str
    filter_hash: str
    content_hash: str
    offset: int = Field(ge=0)
    checksum: str


class CatalogRequest(Contract):
    kind: Literal['sources', 'entities', 'metrics', 'fiscal_periods', 'coverage']
    ids: tuple[str, ...] = Field(default=(), max_length=100)
    cursor: CatalogCursor | None = None
    limit: int = Field(default=20, ge=1, le=100)
    max_bytes: int = Field(default=12000, ge=256, le=8000000)


class SchemaProbeRequest(Contract):
    metric_ids: tuple[str, ...] = Field(default=(), max_length=100)
    entity_ids: tuple[str, ...] = Field(default=(), max_length=100)
    source_snapshot_ids: tuple[str, ...] = Field(default=(), max_length=64)
    cursor: CatalogCursor | None = None
    limit: int = Field(default=20, ge=1, le=100)
    max_bytes: int = Field(default=12000, ge=256, le=8000000)
