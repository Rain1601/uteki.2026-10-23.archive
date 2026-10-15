"""Versioned, source-bound HTML artifacts. No query planner or model protocol."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assets import AssetRef, ContentReadiness, Readiness
from .common import Contract, Text


class HtmlLocator(Contract):
    kind: Literal["html_node"]
    projection: Literal["visible_text_v1", "raw_text_v1"]
    dom_path: Text
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(ge=0)]
    text_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def interval(self):
        if self.char_end < self.char_start:
            raise ValueError("reversed HTML text range")
        return self


class HtmlSection(Contract):
    id: Text
    title: Text
    parent_id: Text | None
    block_id: Text
    basis: Literal["heading_element", "inferred_style"]


class HtmlBlock(Contract):
    id: Text
    kind: Literal["paragraph", "heading", "list_item", "table", "other"]
    text: str
    locator: HtmlLocator
    section_id: Text | None
    dependency_ids: tuple[Text, ...]
    table_id: Text | None
    layout_role: Text | None


class HtmlCell(Contract):
    id: Text
    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1, le=1000)]
    col_span: Annotated[int, Field(ge=1, le=1000)]
    text: str
    locator: HtmlLocator
    header: bool
    scope: str | None
    explicit_headers: tuple[Text, ...]
    header_candidates: tuple[Text, ...]
    footnote_paths: tuple[Text, ...]
    footnote_links: tuple[dict[str, str], ...] = ()


class HtmlTable(Contract):
    id: Text
    block_id: Text
    locator: HtmlLocator
    row_count: Annotated[int, Field(ge=0)]
    column_count: Annotated[int, Field(ge=0)]
    cells: tuple[HtmlCell, ...]
    caption: str | None
    context_block_ids: tuple[Text, ...]
    nested_table_ids: tuple[Text, ...]


class InlineRecord(Contract):
    id: Text
    fact_id: str | None
    concept: str | None
    concept_namespace: str | None
    context_ref: str | None
    unit_ref: str | None
    raw_value: str
    value_decimal: str | None
    format: str | None
    scale: str | None
    sign: str | None
    decimals: str | None
    entity_identifier: str | None
    entity_scheme: str | None
    period: dict[str, str | None]
    dimensions: tuple[dict[str, str], ...]
    unit: dict[str, tuple[str, ...]]
    status: Literal["parsed", "nil", "unsupported", "invalid"]
    issues: tuple[Text, ...]
    locator: HtmlLocator
    context_path: str | None
    unit_path: str | None
    duplicate_group: str | None

    @model_validator(mode="after")
    def value_status(self):
        if (self.status == "parsed") != (self.value_decimal is not None):
            raise ValueError("only parsed facts may have a numeric value")
        if self.status in {"unsupported", "invalid"} and not self.issues:
            raise ValueError("unparsed fact needs explicit issues")
        return self


class HtmlImage(Contract):
    id: Text
    dom_path: Text
    source_url: str | None
    resource_key: str | None
    alt: str
    status: Literal["present", "missing", "excluded"]
    reason: str | None


class HtmlReadiness(ContentReadiness):
    tables: Readiness
    # Enumerating parsed facts is distinct from structured query readiness.
    inline_facts: Readiness


class HtmlSchema(Contract):
    schema_version: Literal["uteki-asset-schema-html-v1"]
    asset_ref: AssetRef
    processor_version: Text
    content_readiness: HtmlReadiness
    published_readiness: HtmlReadiness
    gaps: tuple[Text, ...]
    description: Text


class HtmlQuality(Contract):
    schema_version: Literal["uteki-html-quality-v1"]
    issues: tuple[Text, ...]
    counts: dict[str, int]
    exclusions: tuple[dict[str, str], ...]
    coverage: Literal["complete", "partial"]


class HtmlEvidenceRef(Contract):
    asset_ref: AssetRef
    kind: Literal["block", "table_cell", "record_field"]
    item_id: Text
    field: Literal["text", "value_decimal", "raw_value"]
