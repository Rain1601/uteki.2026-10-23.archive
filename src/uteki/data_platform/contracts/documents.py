"""Versioned document input contracts, independent of extraction engines/SDKs.

These describe observed parser output, not an LLM's inferred answer. Publication
validates reference closure; it does not certify OCR or business classification.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator, model_serializer

from .common import Contract, FiscalPeriod, SourceTime, Text
from .content import ObjectRef

Status = Literal['complete', 'partial', 'not_processed', 'failed', 'not_applicable']


class EntityRelation(Contract):
    entity_id: Text
    name: Text
    role: Literal['issuer', 'subject', 'mentioned', 'publisher']


class Material(Contract):
    material_id: Text
    name: Text
    material_type: Text
    language: Text | None = None
    publisher_name: Text | None = None
    related_entities: tuple[EntityRelation, ...] = ()
    reporting_period: FiscalPeriod | None = None
    published_at: SourceTime
    created_at: AwareDatetime

    @model_validator(mode='after')
    def entities(self):
        if len({(e.entity_id,e.role) for e in self.related_entities}) != len(self.related_entities):
            raise ValueError('duplicate material entity role')
        return self


class SourceVersion(Contract):
    source_version_id: Text
    material_id: Text
    format: Literal['pdf', 'html', 'text', 'image']
    object_ref: ObjectRef                 # ContentStore reference; no arbitrary file reads.
    source_url: Text | None = None
    acquisition_method: Literal['system', 'manual_upload']
    acquired_at: AwareDatetime
    ingested_at: AwareDatetime
    revision_of: Text | None = None

    @model_validator(mode='after')
    def chronology(self):
        if self.ingested_at < self.acquired_at:
            raise ValueError('ingestion precedes acquisition')
        if self.revision_of == self.source_version_id:
            raise ValueError('a source cannot revise itself')
        return self


class ModelIdentity(Contract):
    provider: Text
    model_id: Text
    model_version: Text | None = None


class Processor(Contract):
    processor_id: Text
    step: Text
    tool_name: Text
    tool_version: Text
    model: ModelIdentity | None = None    # Program-only extraction is not a model call.


class PdfLocation(Contract):
    kind: Literal['pdf_region'] = 'pdf_region'
    page_number: Annotated[int, Field(ge=1)]
    page_label: Text | None = None
    bbox: tuple[float, float, float, float]
    coordinate_system: Literal['pdf_pt_top_left'] = 'pdf_pt_top_left'

    @model_validator(mode='after')
    def rectangle(self):
        import math
        x0, y0, x1, y1 = self.bbox
        if not all(math.isfinite(v) for v in self.bbox) or not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError('invalid PDF rectangle')
        return self


class HtmlLocation(Contract):
    kind: Literal['html_node'] = 'html_node'
    dom_path: Annotated[Text, Field(pattern=r'^/')]
    char_range: tuple[int, int] | None = None

    @model_validator(mode='after')
    def interval(self):
        if self.char_range is not None and not 0 <= self.char_range[0] < self.char_range[1]:
            raise ValueError('invalid character range')
        return self


class PdfDestination(Contract):
    """Native bookmark destination; absent coordinates are not invented."""
    kind: Literal['pdf_destination'] = 'pdf_destination'
    page_number: Annotated[int, Field(ge=1)]
    x: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    y: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    coordinate_system: Literal['pdf_pt_top_left'] = 'pdf_pt_top_left'


class ImageLocation(Contract):
    kind: Literal['image_region'] = 'image_region'
    resource_id: Text                    # Source image or explicitly stored crop.
    bbox: tuple[float, float, float, float]
    coordinate_system: Literal['image_px_top_left'] = 'image_px_top_left'

    @model_validator(mode='after')
    def rectangle(self):
        PdfLocation(page_number=1,bbox=self.bbox)  # Same finite positive rectangle rule.
        return self


class TextLocation(Contract):
    kind: Literal['text_range'] = 'text_range'
    char_range: tuple[int, int]
    encoding: Literal['utf-8'] = 'utf-8'

    @model_validator(mode='after')
    def interval(self):
        HtmlLocation(dom_path='/',char_range=self.char_range)
        return self


Location = Annotated[PdfLocation | PdfDestination | HtmlLocation | ImageLocation | TextLocation, Field(discriminator='kind')]


class Resource(Contract):
    resource_id: Text
    role: Literal['original_image', 'source_crop', 'preview']
    mime_type: Text
    object_ref: ObjectRef


class TextExtraction(Contract):
    status: Status
    text: str | None = None
    processor_ref: Text | None = None
    issues: tuple[Text, ...] = ()

    @model_validator(mode='after')
    def explained(self):
        if self.text is not None and self.processor_ref is None:
            raise ValueError('extracted text requires processor provenance')
        if self.status == 'complete' and (self.text is None or self.processor_ref is None):
            raise ValueError('completed extraction requires text and processor')
        if self.status in ('partial', 'failed') and not self.issues:
            raise ValueError('partial/failed extraction requires issues')
        if self.status in ('not_processed', 'not_applicable') and (self.text is not None or self.processor_ref is not None):
            raise ValueError('unprocessed extraction cannot contain generated text')
        return self


class Cell(Contract):
    row: Annotated[int, Field(ge=0)]
    column: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1)] = 1
    column_span: Annotated[int, Field(ge=1)] = 1
    text: str
    is_header: bool = False
    locations: tuple[Location, ...] = ()


class TableContent(Contract):
    status: Status
    processor_ref: Text | None = None
    row_count: Annotated[int, Field(ge=0, le=10000)]
    column_count: Annotated[int, Field(ge=0, le=1000)]
    cells: tuple[Cell, ...] = ()
    issues: tuple[Text, ...] = ()

    @model_validator(mode='after')
    def grid(self):
        if self.cells and not self.processor_ref:
            raise ValueError('extracted cells require processor provenance')
        if self.status == 'complete' and (not self.cells or not self.processor_ref):
            raise ValueError('completed table requires cells and processor')
        if self.status in ('partial', 'failed') and not self.issues:
            raise ValueError('incomplete table requires issues')
        if self.status in ('not_processed', 'not_applicable') and self.cells:
            raise ValueError('unprocessed table cannot contain cells')
        if sum(c.row_span * c.column_span for c in self.cells) > 1_000_000:
            raise ValueError('table grid exceeds supported limit')
        occupied = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.row_count or cell.column + cell.column_span > self.column_count:
                raise ValueError('cell outside table grid')
            for r in range(cell.row, cell.row + cell.row_span):
                for c in range(cell.column, cell.column + cell.column_span):
                    if (r, c) in occupied:
                        raise ValueError('overlapping cells')
                    occupied.add((r, c))
        return self


class TagDefinition(Contract):
    tag_id: Text
    name: Text
    parent_id: Text | None = None
    description: Text
    include_rules: tuple[Text, ...] = ()
    exclude_rules: tuple[Text, ...] = ()
    applicable_material_types: tuple[Text, ...] = ()


def validate_tree(items, id_field):
    nodes = {getattr(n, id_field): n for n in items}
    if len(nodes) != len(items):
        raise ValueError('duplicate tree node ID')
    for identity, node in nodes.items():
        visited = {identity}
        parent = node.parent_id
        while parent is not None:
            if parent not in nodes or parent in visited:
                raise ValueError('missing parent or cycle in tree')
            visited.add(parent)
            if len(visited)>128:
                raise ValueError('directory/taxonomy nesting exceeds supported depth 128')
            parent = nodes[parent].parent_id


class Taxonomy(Contract):
    taxonomy_id: Text
    version: Text
    tags: tuple[TagDefinition, ...]

    @model_validator(mode='after')
    def tree(self):
        validate_tree(self.tags, 'tag_id')
        return self


class Tagging(Contract):
    status: Status
    tag_ids: tuple[Text, ...] = ()
    processor_ref: Text | None = None
    issues: tuple[Text, ...] = ()

    @model_validator(mode='after')
    def explained(self):
        if self.tag_ids and not self.processor_ref:
            raise ValueError('assigned tags require processor provenance')
        if self.status == 'complete' and not self.processor_ref:
            raise ValueError('completed tagging requires provenance, even with zero matches')
        if self.status in ('partial', 'failed') and not self.issues:
            raise ValueError('incomplete tagging requires issues')
        if self.status in ('not_processed', 'not_applicable') and (self.tag_ids or self.processor_ref):
            raise ValueError('unprocessed tagging cannot contain labels')
        if len(set(self.tag_ids)) != len(self.tag_ids):
            raise ValueError('duplicate tag ID')
        return self


class DirectoryNode(Contract):
    node_id: Text
    parent_id: Text | None
    title: Text
    order: Annotated[int, Field(ge=0)]
    basis: Literal['source_directory', 'source_heading', 'inferred']
    locations: tuple[Location, ...] = ()
    code: Text | None = None
    heading_block_id: Text | None = None
    hierarchy_basis: Text | None = None

    @model_validator(mode='after')
    def code_segment(self):
        if self.code is not None and ('.' in self.code or any(c.isspace() for c in self.code)):
            raise ValueError('code must be one path segment without dots or whitespace')
        return self

    @model_serializer(mode='wrap')
    def omit_extensions_on_legacy_nodes(self, handler):
        value = handler(self)
        for key in ('code', 'heading_block_id', 'hierarchy_basis'):
            if value.get(key) is None:
                value.pop(key, None)
        return value


class Directory(Contract):
    has_source_directory: bool | None
    status: Status
    nodes: tuple[DirectoryNode, ...] = ()
    issues: tuple[Text, ...] = ()

    @model_validator(mode='after')
    def tree(self):
        validate_tree(self.nodes, 'node_id')
        codes = [(n.parent_id, n.code) for n in self.nodes if n.code is not None]
        if len(codes) != len(set(codes)):
            raise ValueError('duplicate directory code among siblings')
        if self.has_source_directory is True and self.status == 'not_applicable':
            raise ValueError('an existing source directory cannot be not applicable')
        if self.has_source_directory is True and self.status == 'complete' and not self.nodes:
            raise ValueError('source directory cannot be reported complete and empty')
        if self.status in ('not_processed', 'not_applicable') and self.nodes:
            raise ValueError('unprocessed directory cannot contain nodes')
        if self.status in ('partial', 'failed') and not self.issues:
            raise ValueError('incomplete directory requires issues')
        if self.has_source_directory is not True and any(n.basis == 'source_directory' for n in self.nodes):
            raise ValueError('cannot invent a source directory')
        return self


class RelatedBlock(Contract):
    block_id: Text
    relation: Literal['caption', 'footnote', 'continuation', 'context']


class Hyperlink(Contract):
    text: str
    target_url: Text                     # Retained as data; never fetched by storage.
    locations: tuple[Location, ...] = ()


class BodySelection(Contract):
    decision: Literal['keep', 'exclude', 'uncertain']
    reason: Text
    policy_version: Text


class SourceLine(Contract):
    """A source text-line observation; character offsets use block.text codepoints."""
    line_id: Text
    text: str
    location: PdfLocation
    char_range: tuple[int, int] | None = None  # None means alignment was not established.


class ContentBlock(Contract):
    block_id: Text
    order: Annotated[int, Field(ge=0)]
    type: Literal['text', 'image', 'table']
    role: Literal['heading', 'body', 'caption', 'footnote', 'header', 'footer'] = 'body'
    processor_ref: Text
    text: str | None = None
    text_origin: Literal['source','ocr','mixed','unknown'] = 'source'
    resources: tuple[Resource, ...] = ()
    table: TableContent | None = None
    ocr: TextExtraction
    description: TextExtraction
    locations: Annotated[tuple[Location, ...], Field(min_length=1)]
    directory_node_ids: tuple[Text, ...] = ()
    directory_assignment: Literal['assigned', 'outside_directory', 'no_source_directory', 'unresolved']
    tagging: Tagging
    related_blocks: tuple[RelatedBlock, ...] = ()
    links: tuple[Hyperlink, ...] = ()
    status: Literal['complete', 'partial', 'failed']
    issues: tuple[Text, ...] = ()
    body_selection: BodySelection | None = None
    text_lines: tuple[SourceLine, ...] | None = None

    @model_serializer(mode='wrap')
    def omit_extension_on_legacy_blocks(self, handler):
        value = handler(self)
        if value.get('body_selection') is None:
            value.pop('body_selection', None)
        if value.get('text_lines') is None:
            value.pop('text_lines', None)
        return value

    @model_validator(mode='after')
    def content(self):
        if self.text_lines is not None:
            if self.type != 'text' or len({line.line_id for line in self.text_lines}) != len(self.text_lines):
                raise ValueError('text lines require a text block and unique line IDs')
            for line in self.text_lines:
                if line.char_range is not None and not 0 <= line.char_range[0] < line.char_range[1] <= len(self.text or ''):
                    raise ValueError('line character range outside block text')
        if self.type == 'text' and (self.text is None or self.table is not None):
            raise ValueError('text block requires text and cannot contain a table')
        if self.type != 'text' and self.text is not None:
            raise ValueError('image/table text belongs in OCR or table cells')
        if self.type != 'table' and self.table is not None:
            raise ValueError('non-table block contains table structure')
        if self.type == 'image' and not self.resources:
            raise ValueError('image block requires a stored resource')
        if self.type == 'table' and self.table is None and not self.resources:
            raise ValueError('table requires structure or a stored image')
        if (self.directory_assignment == 'assigned') != bool(self.directory_node_ids):
            raise ValueError('directory assignment and node references disagree')
        if len(set(self.directory_node_ids)) != len(self.directory_node_ids):
            raise ValueError('duplicate directory link')
        if self.status != 'complete' and not self.issues:
            raise ValueError('incomplete block requires issues')
        return self


class Passage(Contract):
    """A flat content group within one native section, never a directory node."""
    passage_id: Text
    directory_node_id: Text
    index: Annotated[int, Field(ge=0)]
    block_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    lead_block_id: Text | None = None
    grouping_basis: Literal['section_content', 'typographic_lead', 'parser_heading']


class ParseVersion(Contract):
    parse_id: Text
    material_id: Text
    source_version_id: Text
    schema_version: Literal['document-v1', 'document-v2', 'document-v3'] = 'document-v1'
    config_hash: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    parser_output_ref: ObjectRef | None = None
    processors: Annotated[tuple[Processor, ...], Field(min_length=1)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: Literal['complete', 'partial']   # Only publish finished, usable versions.
    directory_schema: Directory
    taxonomy: Taxonomy | None = None
    issues: tuple[Text, ...] = ()
    passages: tuple[Passage, ...] | None = None

    @model_serializer(mode='wrap')
    def preserve_legacy_bytes(self, handler):
        value = handler(self)
        if value.get('passages') is None:
            value.pop('passages', None)
        return value

    @model_validator(mode='after')
    def chronology(self):
        if self.passages is not None and self.schema_version != 'document-v3':
            raise ValueError('frozen passages require document-v3')
        if self.completed_at < self.started_at:
            raise ValueError('parse completion precedes start')
        if self.status == 'partial' and not self.issues:
            raise ValueError('partial parse requires issues')
        if len({p.processor_id for p in self.processors}) != len(self.processors):
            raise ValueError('duplicate processor ID')
        return self


class DocumentPackage(Contract):
    """Immutable publication input; all block IDs are local to this parse."""
    schema_version: Literal['document-package-v1'] = 'document-package-v1'
    material: Material
    source: SourceVersion
    parse: ParseVersion
    blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1)]

    @model_validator(mode='after')
    def closure(self):
        if not self.material.material_id == self.source.material_id == self.parse.material_id:
            raise ValueError('material identities differ')
        if self.parse.source_version_id != self.source.source_version_id:
            raise ValueError('parse uses another source version')
        ids = {b.block_id for b in self.blocks}
        if len(ids) != len(self.blocks) or len({b.order for b in self.blocks}) != len(self.blocks):
            raise ValueError('duplicate block ID or reading order')
        nodes = {n.node_id for n in self.parse.directory_schema.nodes}
        if any(n.heading_block_id is not None and n.heading_block_id not in ids
               for n in self.parse.directory_schema.nodes):
            raise ValueError('directory heading refers to missing block')
        if self.parse.schema_version in ('document-v2', 'document-v3') and (
            any(b.body_selection is None for b in self.blocks) or
            any(n.code is None for n in self.parse.directory_schema.nodes)
        ):
            raise ValueError('document-v2 requires directory codes and explicit body selection')
        if self.parse.schema_version == 'document-v3':
            if self.parse.passages is None or any(n.basis != 'source_directory' for n in self.parse.directory_schema.nodes):
                raise ValueError('document-v3 requires passages and native directory nodes')
            by_id = {b.block_id:b for b in self.blocks}
            headings = {n.heading_block_id for n in self.parse.directory_schema.nodes}
            seen, passage_ids, indices, last_orders = set(), set(), {}, {}
            for passage in self.parse.passages:
                if passage.passage_id in passage_ids or passage.directory_node_id not in nodes:
                    raise ValueError('duplicate passage or missing directory node')
                passage_ids.add(passage.passage_id)
                expected = indices.get(passage.directory_node_id, 0)
                if passage.index != expected:
                    raise ValueError('passage indices must be contiguous within a section')
                indices[passage.directory_node_id] = expected + 1
                previous = last_orders.get(passage.directory_node_id, -1)
                for bid in passage.block_ids:
                    block = by_id.get(bid)
                    if (block is None or bid in seen or bid in headings or
                        block.body_selection.decision == 'exclude' or
                        block.directory_node_ids != (passage.directory_node_id,) or block.order <= previous):
                        raise ValueError('invalid passage block membership or reading order')
                    seen.add(bid); previous = block.order
                last_orders[passage.directory_node_id] = previous
                if passage.lead_block_id is not None and passage.lead_block_id != passage.block_ids[0]:
                    raise ValueError('passage lead must be its first block')
            expected = {b.block_id for b in self.blocks if b.directory_node_ids and
                        b.body_selection.decision != 'exclude' and b.block_id not in headings}
            if seen != expected:
                raise ValueError('passages must cover section content exactly once')
        processors = {p.processor_id for p in self.parse.processors}
        tags = {t.tag_id: t for t in self.parse.taxonomy.tags} if self.parse.taxonomy else {}
        resource_ids = {}
        incomplete = self.parse.directory_schema.status not in ('complete', 'not_applicable')
        for block in self.blocks:
            if not set(block.directory_node_ids) <= nodes or any(r.block_id not in ids or r.block_id == block.block_id for r in block.related_blocks):
                raise ValueError('dangling directory/context reference')
            if block.directory_assignment == 'no_source_directory' and self.parse.directory_schema.has_source_directory is not False:
                raise ValueError('absence of source directory has not been confirmed')
            if block.tagging.status == 'complete' and self.parse.taxonomy is None:
                raise ValueError('completed tagging requires a fixed taxonomy')
            for tag_id in block.tagging.tag_ids:
                if tag_id not in tags:
                    raise ValueError('unknown tag')
                applicable = tags[tag_id].applicable_material_types
                if applicable and self.material.material_type not in applicable:
                    raise ValueError('tag not applicable to material type')
            refs = [block.processor_ref, block.ocr.processor_ref, block.description.processor_ref, block.tagging.processor_ref]
            if block.table is not None:
                refs.append(block.table.processor_ref)
                incomplete |= block.table.status not in ('complete', 'not_applicable')
            if any(r is not None and r not in processors for r in refs):
                raise ValueError('unknown processor reference')
            for resource in block.resources:
                if resource.resource_id in resource_ids and resource_ids[resource.resource_id] != resource.object_ref:
                    raise ValueError('resource ID refers to different bytes')
                resource_ids[resource.resource_id] = resource.object_ref
            incomplete |= block.status != 'complete' or block.directory_assignment == 'unresolved'
            incomplete |= any(v.status not in ('complete', 'not_applicable') for v in (block.ocr, block.description, block.tagging))
        all_locations=[loc for node in self.parse.directory_schema.nodes for loc in node.locations]
        for block in self.blocks:
            all_locations.extend(block.locations)
            all_locations.extend(line.location for line in block.text_lines or ())
            all_locations.extend(loc for link in block.links for loc in link.locations)
            if block.table:all_locations.extend(loc for cell in block.table.cells for loc in cell.locations)
        for loc in all_locations:
            if isinstance(loc,ImageLocation) and loc.resource_id not in resource_ids:
                raise ValueError('image locator refers to an unknown stored resource')
            supported={'pdf_region':'pdf','pdf_destination':'pdf','html_node':'html','text_range':'text'}
            if loc.kind in supported and self.source.format!=supported[loc.kind]:
                raise ValueError('location kind does not match original format')
        if incomplete and self.parse.status != 'partial':
            raise ValueError('incomplete processing cannot be published as complete')
        return self


class BlockRef(Contract):
    material_id: Text
    parse_id: Text
    block_id: Text


class BlockQuery(Contract):
    """Selectors combine with AND; tags choose any/all. Pagination pins this query."""
    parse_id: Text
    content_view: Literal['all', 'body'] = 'all'
    directory_node_id: Text | None = None
    directory_path: tuple[Text, ...] | None = None
    include_descendants: bool = False
    tags: tuple[Text, ...] = ()
    tag_match: Literal['any', 'all'] = 'any'
    types: tuple[Literal['text', 'image', 'table'], ...] = ()
    text: Text | None = None
    text_match: Literal['phrase', 'substring'] = 'phrase'
    text_origins: tuple[Literal['source', 'ocr', 'mixed', 'unknown', 'description'], ...] = ('source', 'ocr', 'mixed', 'unknown')
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    max_bytes: Annotated[int, Field(ge=256, le=1_000_000)] = 24000

    @model_validator(mode='after')
    def selectors(self):
        if self.directory_node_id is not None and self.directory_path is not None:
            raise ValueError('choose node ID or path')
        if self.directory_path == () or not self.text_origins:
            raise ValueError('empty directory path or text origins')
        if len(set(self.tags)) != len(self.tags):
            raise ValueError('duplicate tag filter')
        return self
