"""Versioned, source-bound HTML artifacts. No query planner or model protocol."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assets import AssetRef, ContentReadiness, Readiness
from .common import Contract, Text


# 定位某个 DOM 节点在指定文本投影中的字符区间，并用文本摘要约束其内容。
class HtmlLocator(Contract):
    kind: Literal["html_node"]
    projection: Literal["visible_text_v1", "raw_text_v1"]
    dom_path: Text
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(ge=0)]
    text_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    # 允许空字符区间，但禁止反向区间；具体节点和摘要一致性由读取器核对。
    @model_validator(mode="after")
    def interval(self):
        if self.char_end < self.char_start:
            raise ValueError("reversed HTML text range")
        return self


# 保留章节所属标题块及识别依据，区分原生 heading 元素与样式推断。
class HtmlSection(Contract):
    id: Text
    title: Text
    parent_id: Text | None
    block_id: Text
    basis: Literal["heading_element", "inferred_style"]


# HTML 文本块携带来源定位和上下文依赖；表格块可进一步关联结构化表格。
class HtmlBlock(Contract):
    id: Text
    kind: Literal["paragraph", "heading", "list_item", "table", "other"]
    text: str
    locator: HtmlLocator
    section_id: Text | None
    dependency_ids: tuple[Text, ...]
    table_id: Text | None
    layout_role: Text | None


# 表格单元格保留合并范围、原文定位、显式/候选表头以及脚注来源。
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


# 完整表格结构及相邻上下文，嵌套表格通过 ID 关联而非混入父表行列。
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


# Inline XBRL 原始事实与解析结果并存，保留实体、期间、维度、单位和出处。
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

    # 只有 parsed 可携带数值；不支持或无效的事实必须说明问题，避免静默丢失。
    @model_validator(mode="after")
    def value_status(self):
        if (self.status == "parsed") != (self.value_decimal is not None):
            raise ValueError("only parsed facts may have a numeric value")
        if self.status in {"unsupported", "invalid"} and not self.issues:
            raise ValueError("unparsed fact needs explicit issues")
        return self


# 图片发现结果，区分已保存、缺失和被排除；alt 文本不代表图片内容已经解析。
class HtmlImage(Contract):
    id: Text
    dom_path: Text
    source_url: str | None
    resource_key: str | None
    alt: str
    status: Literal["present", "missing", "excluded"]
    reason: str | None


# HTML 在基础就绪声明上补充表格与内联事实状态；列出事实不等于结构化查询已就绪。
class HtmlReadiness(ContentReadiness):
    tables: Readiness
    # Enumerating parsed facts is distinct from structured query readiness.
    inline_facts: Readiness


# 绑定 HTML 构建和处理器版本，分别公布内容能力、已发布能力及仍存在的缺口。
class HtmlSchema(Contract):
    schema_version: Literal["uteki-asset-schema-html-v1"]
    asset_ref: AssetRef
    processor_version: Text
    content_readiness: HtmlReadiness
    published_readiness: HtmlReadiness
    gaps: tuple[Text, ...]
    description: Text


# HTML 处理质量记录，保留数量、问题与排除项，覆盖率只在声明范围内成立。
class HtmlQuality(Contract):
    schema_version: Literal["uteki-html-quality-v1"]
    issues: tuple[Text, ...]
    counts: dict[str, int]
    exclusions: tuple[dict[str, str], ...]
    coverage: Literal["complete", "partial"]


# 绑定具体构建、项目与字段的证据读取请求，不能仅凭一个块 ID 跨版本读取。
class HtmlEvidenceRef(Contract):
    asset_ref: AssetRef
    kind: Literal["block", "table_cell", "record_field"]
    item_id: Text
    field: Literal["text", "value_decimal", "raw_value"]
