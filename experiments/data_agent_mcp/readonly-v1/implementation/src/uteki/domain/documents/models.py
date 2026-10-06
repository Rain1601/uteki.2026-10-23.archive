from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Paragraph:
    ordinal: int
    text: str
    text_hash: str


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    source_url: str
    content_hash: str
    paragraphs: tuple[Paragraph, ...]


BlockKind = Literal[
    "heading_candidate",
    "paragraph",
    "list_item",
    "table",
    "image",
    "page_marker",
    "other",
]
NodeKind = Literal["document", "part", "item"]


@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    row: int
    column: int
    rowspan: int
    colspan: int
    is_header: bool


@dataclass(frozen=True, slots=True)
class TableStructure:
    row_count: int
    column_count: int
    cells: tuple[TableCell, ...]


@dataclass(frozen=True, slots=True)
class AssetReference:
    asset_id: str
    source_url: str
    source_path: str
    alt: str | None
    dom_path: str


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    anchor: str
    dom_path: str
    target_block_id: str | None


@dataclass(frozen=True, slots=True)
class TocEntry:
    kind: Literal["part", "item"]
    number: str
    title: str
    source_anchor: str | None
    reported_page: int | None
    ordinal: int


@dataclass(frozen=True, slots=True)
class SourceBlock:
    block_id: str
    ordinal: int
    type: BlockKind
    text: str
    text_hash: str
    source_anchor: str | None
    dom_path: str
    reported_page: int | None
    style_signature: tuple[tuple[str, str], ...]
    table: TableStructure | None = None
    image_asset_id: str | None = None
    layout_role: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    document_id: str
    source_url: str
    content_hash: str
    source_snapshot_id: str
    form_type: str
    parser_version: str
    blocks: tuple[SourceBlock, ...]
    anchors: tuple[SourceAnchor, ...]
    toc_entries: tuple[TocEntry, ...]
    assets: tuple[AssetReference, ...]
    parser_diagnostics: tuple["IndexDiagnostic", ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentNode:
    node_id: str
    parent_id: str | None
    kind: NodeKind
    title: str
    part_number: str | None
    item_number: str | None
    start_block_id: str
    end_block_id: str
    source_anchor: str | None
    reported_page: int | None


@dataclass(frozen=True, slots=True)
class IndexDiagnostic:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentIndex:
    index_id: str
    schema_version: str
    parser_version: str
    source_snapshot_id: str
    form_type: str
    nodes: tuple[DocumentNode, ...]
    diagnostics: tuple[IndexDiagnostic, ...]
