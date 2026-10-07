"""Candidate product selection over one host-frozen source packet.

The model selects original cells, never supplies financial amounts. Validation
checks references, geometry and arithmetic, not business meaning or whether a
source table is the complete and appropriate revenue disclosure.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class MonetizationDraft(Contract):
    description: Text
    basis: Literal["explicit", "unknown"]
    evidence_block_ids: list[ID]


class BusinessDraft(Contract):
    id: ID
    name: Text
    kind: Literal["company", "reportable_segment", "business", "offering_group"]
    description: Text
    products_services: list[Text] = Field(default_factory=list)
    customers: list[Text] = Field(default_factory=list)
    monetization: list[MonetizationDraft] = Field(default_factory=list)
    evidence_block_ids: list[ID] = Field(min_length=1)
    role: Literal["market", "application_platform", "offering_group"] | None = None


class RelationshipDraft(Contract):
    source_id: ID
    target_id: ID
    kind: Literal["reported_under", "part_of", "supports"]
    description: Text
    evidence_block_ids: list[ID] = Field(min_length=1)


class UnknownDraft(Contract):
    id: ID
    question: Text
    reason_unanswered: Text
    related_business_ids: list[ID]


class RevenuePartDraft(Contract):
    id: ID
    label: Text
    amount_cell_id: ID


class RevenueSubtotalDraft(RevenuePartDraft):
    component_ids: list[ID] = Field(min_length=1)


class RevenueChartDraft(Contract):
    id: ID
    title: Text
    denominator_label: Text
    chart_type: Literal["bar", "donut"]
    total_cell_id: ID
    unit_block_id: ID
    currency_block_id: ID
    period_header_cell_id: ID
    parts: list[RevenuePartDraft] = Field(min_length=1)
    adjustments: list[RevenuePartDraft] = Field(default_factory=list)
    reported_subtotals: list[RevenueSubtotalDraft] = Field(default_factory=list)


class ProductDraft(Contract):
    company_id: ID
    document_id: ID
    period_end: Text
    summary: Text
    businesses: list[BusinessDraft] = Field(min_length=1)
    relationships: list[RelationshipDraft]
    unknowns: list[UnknownDraft]
    revenue_charts: list[RevenueChartDraft]


LEGACY_DRAFT_VERSION = "business-revenue-draft-v1"
DRAFT_VERSION = "business-revenue-draft-v2"
BUSINESS_DRAFT_VERSION = "business-draft-v1"
BUSINESS_DRAFT_V2_VERSION = "business-draft-v2"
BUSINESS_DRAFT_VERSIONS = (BUSINESS_DRAFT_VERSION, BUSINESS_DRAFT_V2_VERSION)


class EvidenceExcerptDraft(Contract):
    block_id: ID
    quote: Text


class BusinessClaimDraft(Contract):
    """A pointer to one populated field, not a duplicate editable statement."""
    field: Literal["name", "description", "products_services", "customers", "monetization"]
    item_index: Annotated[int, Field(ge=0)] | None
    excerpts: list[EvidenceExcerptDraft] = Field(min_length=1)


class BusinessDraftV2(BusinessDraft):
    claim_evidence: list[BusinessClaimDraft] = Field(min_length=1)


class RelationshipDraftV2(RelationshipDraft):
    basis: Literal["explicit", "derived", "unknown"]
    rationale: Text
    evidence_block_ids: list[ID]
    excerpts: list[EvidenceExcerptDraft]


class ProductDraftV2(ProductDraft):
    schema_version: Literal["business-revenue-draft-v2"]
    relationship_absence: Literal["unknown"]
    businesses: list[BusinessDraftV2] = Field(min_length=1)
    relationships: list[RelationshipDraftV2]


class BlockDispositionDraft(Contract):
    block_id: ID
    disposition: Literal["used", "context", "layout_noise", "not_used"]
    reason: Text


class BusinessOnlyDraft(Contract):
    """One explicitly selected subsection; revenue is outside this contract."""
    schema_version: Literal["business-draft-v1"]
    company_id: ID
    document_id: ID
    period_end: Text
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    summary: Text
    relationship_absence: Literal["unknown"]
    businesses: list[BusinessDraftV2] = Field(min_length=1)
    relationships: list[RelationshipDraftV2]
    unknowns: list[UnknownDraft]
    block_disposition: list[BlockDispositionDraft] = Field(min_length=1)



class CompanyNode(BusinessDraftV2):
    kind: Literal["company"]
    role: None = None


class SegmentNode(BusinessDraftV2):
    kind: Literal["reportable_segment"]
    role: None = None


class BusinessNode(BusinessDraftV2):
    kind: Literal["business"]
    role: Literal["market", "application_platform"] | None = None


class OfferingGroupNode(BusinessDraftV2):
    kind: Literal["offering_group"]
    role: Literal["offering_group"] | None = None


class BusinessOnlyDraftV2(BusinessOnlyDraft):
    """Expose legal kind/role pairs in both JSON Schema and runtime validation.

    These variants constrain structural classification, not source truth. A valid
    pair still needs independent semantic review; never coerce a conflicting pair.
    """
    schema_version: Literal["business-draft-v2"]
    businesses: list[CompanyNode | SegmentNode | BusinessNode | OfferingGroupNode] = Field(min_length=1)


def draft_model(version: str):
    if version == LEGACY_DRAFT_VERSION:
        return ProductDraft
    if version == DRAFT_VERSION:
        return ProductDraftV2
    if version == BUSINESS_DRAFT_VERSION:
        return BusinessOnlyDraft
    if version == BUSINESS_DRAFT_V2_VERSION:
        return BusinessOnlyDraftV2
    raise ValueError("unsupported_product_contract_version")


def has_claim_evidence(value):
    return isinstance(value, (ProductDraftV2, BusinessOnlyDraft))


def validate_business_scope(packet, blocks):
    """Check caller-selected coverage, without claiming semantic completeness.

    The caller supplies the subsection boundary. Original DOM verification and
    independent coverage review remain necessary; ordinal continuity alone is
    not proof that a caller selected the right subsection.
    """
    scope = packet.get("extraction_scope")
    if not isinstance(scope, dict) or scope.get("kind") != "complete_report_subsection":
        raise ValueError("explicit_business_subsection_required")
    _text(scope.get("title"), "business_scope_title")
    groups = []
    for field, role in (("section_block_ids", "selected_subsection"),
                        ("scope_metadata_block_ids", "scope_metadata")):
        ids = scope.get(field)
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
            raise ValueError("business_scope_block_ids_required: " + field)
        _references(ids, blocks.keys(), "business_scope_" + field)
        if any(blocks[x].get("input_role") != role for x in ids):
            raise ValueError("business_scope_block_role_mismatch")
        groups.append(set(ids))
    section, context = groups
    if section & context or section | context != set(blocks):
        raise ValueError("business_scope_partition_mismatch")
    start, end = scope.get("start_ordinal"), scope.get("end_ordinal_inclusive")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        raise ValueError("business_scope_ordinal_range_invalid")
    if [blocks[x].get("ordinal") for x in scope["section_block_ids"]] != list(range(start, end + 1)):
        raise ValueError("business_scope_section_incomplete")
    if scope.get("end_boundary_exclusive_ordinal") != end + 1:
        raise ValueError("business_scope_end_boundary_invalid")
    _text(scope.get("end_boundary_exclusive_title"), "business_scope_end_boundary_title")
    if scope.get("filtered_block_ids") != [] or scope.get("financial_analysis") is not False:
        raise ValueError("business_scope_complete_nonfinancial_required")
    identity = packet.get("scope_evidence_block_ids")
    if not isinstance(identity, dict):
        raise ValueError("business_scope_identity_evidence_required")
    for field in ("company", "period"):
        ids = identity.get(field)
        if not isinstance(ids, list):
            raise ValueError("business_scope_identity_evidence_required: " + field)
        _references(ids, context, "business_scope_" + field)
    return scope


def _validate_excerpts(excerpts, blocks, label):
    _unique(((e.block_id, " ".join(e.quote.split())) for e in excerpts), label + "_excerpt")
    for excerpt in excerpts:
        if excerpt.block_id not in blocks:
            raise ValueError(label + "_evidence_outside_packet")
        if " ".join(excerpt.quote.split()) not in " ".join(blocks[excerpt.block_id]["text"].split()):
            raise ValueError(label + "_quote_not_in_source")


def _validate_v2(value, blocks):
    for business in value.businesses:
        expected = {("name", None), ("description", None)}
        for field in ("products_services", "customers"):
            expected.update((field, i) for i in range(len(getattr(business, field))))
        expected.update(("monetization", i) for i, m in enumerate(business.monetization) if m.basis == "explicit")
        actual = _unique(((c.field, c.item_index) for c in business.claim_evidence), "business_claim_target")
        if actual != expected:
            raise ValueError("business_claim_coverage_mismatch: " + business.id)
        for claim in business.claim_evidence:
            _validate_excerpts(claim.excerpts, blocks, "business_claim")
            if set(e.block_id for e in claim.excerpts) - set(business.evidence_block_ids):
                raise ValueError("business_claim_not_in_node_evidence")
            if claim.field == "monetization" and set(e.block_id for e in claim.excerpts) != set(
                    business.monetization[claim.item_index].evidence_block_ids):
                raise ValueError("monetization_claim_evidence_mismatch")
    for relation in value.relationships:
        _validate_excerpts(relation.excerpts, blocks, "relationship")
        if set(e.block_id for e in relation.excerpts) != set(relation.evidence_block_ids):
            raise ValueError("relationship_excerpt_evidence_mismatch")
        if relation.basis != "unknown" and not relation.excerpts:
            raise ValueError("asserted_relationship_excerpt_required")
        if relation.basis == "unknown" and not any(
                {relation.source_id, relation.target_id}.issubset(u.related_business_ids) for u in value.unknowns):
            raise ValueError("unknown_relationship_requires_gap")


def parse_amount_cell(text: str) -> Decimal:
    """Parse a displayed number in millions; do not scale or impute missing cells.

    Accept commas or grouped spaces, decimal fractions, a leading minus, and
    accounting parentheses. A dash, footnote, currency sign or mixed text is a
    gap, not zero. The host separately establishes currency/unit evidence.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("amount_cell_number_required")
    token = text.strip()
    token = re.sub(r"\s*([(),.\-])\s*", r"\1", token)
    parenthesized = token.startswith("(") and token.endswith(")")
    if parenthesized:
        token = token[1:-1]
    if parenthesized and token.startswith("-"):
        raise ValueError("unsupported_amount_cell_number")
    if not re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:\s\d{3})+|\d+)(?:\.\d+)?", token):
        raise ValueError("unsupported_amount_cell_number")
    number = Decimal(re.sub(r"[,\s]", "", token))
    return -number if parenthesized else number


def _unique(values, label):
    values = list(values)
    if len(set(values)) != len(values):
        raise ValueError("duplicate_" + label)
    return set(values)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("packet_missing_" + label)
    return value


def _references(values, known, label, *, required=True):
    if required and not values:
        raise ValueError(label + "_required")
    _unique(values, label)
    if set(values) - known:
        raise ValueError(label + "_outside_packet")


def _packet_index(packet):
    if not isinstance(packet, dict):
        raise ValueError("packet_object_required")
    for key in ("company_id", "document_id", "period_end", "source_sha256", "source_local_path", "source_url"):
        _text(packet.get(key), key)
    if not re.fullmatch(r"[a-f0-9]{64}", packet["source_sha256"]):
        raise ValueError("packet_invalid_source_sha256")
    date.fromisoformat(packet["period_end"])
    blocks, tables = packet.get("blocks"), packet.get("tables")
    if not isinstance(blocks, list) or not blocks or not isinstance(tables, list):
        raise ValueError("packet_blocks_and_tables_required")
    by_block = {}
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("packet_block_object_required")
        bid = _text(block.get("id"), "block_id")
        if bid in by_block:
            raise ValueError("duplicate_packet_block_id")
        text = _text(block.get("text"), "block_text")
        normalized = " ".join(text.split())
        if block.get("text_sha256") != hashlib.sha256(normalized.encode()).hexdigest():
            raise ValueError("packet_block_hash_mismatch")
        _text(block.get("source_dom_path"), "block_source_dom_path")
        if not isinstance(block.get("section_path"), list) or not block["section_path"]:
            raise ValueError("packet_block_section_required")
        by_block[bid] = block
    by_cell, table_ids = {}, set()
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("packet_table_object_required")
        tid = _text(table.get("id"), "table_id")
        if tid in table_ids:
            raise ValueError("duplicate_packet_table_id")
        table_ids.add(tid)
        if table.get("block_id") not in by_block:
            raise ValueError("table_block_outside_packet")
        _text(table.get("source_dom_path"), "table_source_dom_path")
        if not isinstance(table.get("cells"), list):
            raise ValueError("packet_table_cells_required")
        for cell in table["cells"]:
            if not isinstance(cell, dict):
                raise ValueError("packet_cell_object_required")
            cid = _text(cell.get("id"), "cell_id")
            if cid in by_cell:
                raise ValueError("duplicate_packet_cell_id")
            if not isinstance(cell.get("text"), str):
                raise ValueError("packet_cell_text_required")
            if ("text_sha256" in cell and cell["text_sha256"]
                    != hashlib.sha256(" ".join(cell["text"].split()).encode()).hexdigest()):
                raise ValueError("packet_cell_hash_mismatch")
            _text(cell.get("source_dom_path"), "cell_source_dom_path")
            for key in ("row_index", "column_index", "rowspan", "colspan"):
                minimum = 0 if key.endswith("index") else 1
                if type(cell.get(key)) is not int or cell[key] < minimum:
                    raise ValueError("packet_invalid_cell_" + key)
            by_cell[cid] = (tid, cell)
    return by_block, by_cell


def validate_draft(draft: ProductDraft | BusinessOnlyDraft | dict[str, Any], packet: dict[str, Any], *,
                   expected_version: str | None = None) -> ProductDraft | BusinessOnlyDraft:
    """Reject unsupported output without repairing facts or substituting amounts.

    The host must freeze and verify packet bytes against the original source.
    This function validates supplied blocks/cell selections; it does not read
    arbitrary filesystem paths or infer period columns from a fiscal-year date.
    """
    raw = draft.model_dump() if isinstance(draft, (ProductDraft, BusinessOnlyDraft)) else draft
    version = raw.get("schema_version", LEGACY_DRAFT_VERSION) if isinstance(raw, dict) else None
    if expected_version is not None and version != expected_version:
        raise ValueError("product_contract_version_mismatch")
    value = draft_model(version).model_validate(raw)
    blocks, cells = _packet_index(packet)
    for field in ("company_id", "document_id", "period_end"):
        if getattr(value, field) != packet[field]:
            raise ValueError("product_scope_mismatch: " + field)
    if isinstance(value, BusinessOnlyDraft):
        validate_business_scope(packet, blocks)
        if value.source_sha256 != packet["source_sha256"]:
            raise ValueError("product_scope_mismatch: source_sha256")
    business_ids = _unique((b.id for b in value.businesses), "business_id")
    if sum(b.kind == "company" for b in value.businesses) != 1:
        raise ValueError("one_company_node_required")
    for business in value.businesses:
        if business.role in ("market", "application_platform") and business.kind != "business":
            raise ValueError("market_or_platform_role_requires_business_kind")
        if business.role == "offering_group" and business.kind != "offering_group":
            raise ValueError("offering_group_role_requires_matching_kind")
        _references(business.evidence_block_ids, blocks.keys(), "business_evidence")
        for statement in business.monetization:
            _references(statement.evidence_block_ids, blocks.keys(), "monetization_evidence",
                        required=statement.basis == "explicit")
    _unique(((r.source_id, r.kind, r.target_id) for r in value.relationships), "relationship")
    for relation in value.relationships:
        if relation.source_id == relation.target_id:
            raise ValueError("self_relationship_unsupported")
        _references([relation.source_id, relation.target_id], business_ids, "relationship_endpoints")
        _references(relation.evidence_block_ids, blocks.keys(), "relationship_evidence",
                    required=not has_claim_evidence(value) or relation.basis != "unknown")
    _unique((u.id for u in value.unknowns), "unknown_id")
    for unknown in value.unknowns:
        _references(unknown.related_business_ids, business_ids, "unknown_businesses", required=False)
    if has_claim_evidence(value):
        _validate_v2(value, blocks)
    if isinstance(value, BusinessOnlyDraft):
        disposition_ids = _unique((d.block_id for d in value.block_disposition), "block_disposition_id")
        if disposition_ids != set(blocks):
            raise ValueError("block_disposition_coverage_mismatch")
        referenced = {x for b in value.businesses for x in b.evidence_block_ids}
        referenced.update(x for b in value.businesses for m in b.monetization for x in m.evidence_block_ids)
        referenced.update(x for r in value.relationships for x in r.evidence_block_ids)
        if any(d.block_id in referenced and d.disposition in ("layout_noise", "not_used")
               for d in value.block_disposition):
            raise ValueError("referenced_block_marked_unused")
        return value
    _unique((c.id for c in value.revenue_charts), "revenue_chart_id")

    def source_cell(cid):
        if cid not in cells:
            raise ValueError("revenue_cell_outside_packet")
        return cells[cid]

    for chart in value.revenue_charts:
        if packet.get("financial_currency") != "USD" or packet.get("financial_unit") != "million":
            raise ValueError("explicit_usd_million_packet_scope_required")
        _references([chart.unit_block_id], blocks.keys(), "revenue_unit_evidence")
        _references([chart.currency_block_id], blocks.keys(), "revenue_currency_evidence")
        if not re.search(r"\bmillions?\b", blocks[chart.unit_block_id]["text"], re.I):
            raise ValueError("explicit_million_unit_required")
        if not re.search(r"\b(?:USD|US\s+dollars|U\.S\.\s*dollars|United\s+States\s+dollars)\b",
                         blocks[chart.currency_block_id]["text"], re.I):
            raise ValueError("explicit_usd_currency_required")
        label = " ".join(_text(packet.get("requested_period_label"), "requested_period_label").split())
        table_id, header = source_cell(chart.period_header_cell_id)
        if not re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", " ".join(header["text"].split())):
            raise ValueError("requested_period_header_mismatch")

        def amount(cid):
            selected_table, cell = source_cell(cid)
            if selected_table != table_id:
                raise ValueError("revenue_cells_must_share_table")
            if (cell["column_index"] < header["column_index"]
                    or cell["column_index"] + cell["colspan"] > header["column_index"] + header["colspan"]
                    or cell["row_index"] < header["row_index"] + header["rowspan"]):
                raise ValueError("revenue_cell_outside_period_header")
            return parse_amount_cell(cell["text"])

        all_rows = chart.parts + chart.adjustments + chart.reported_subtotals
        _unique((row.id for row in all_rows), "revenue_row_id")
        _unique([chart.total_cell_id, *(row.amount_cell_id for row in all_rows)], "revenue_amount_cell")
        total = amount(chart.total_cell_id)
        if total <= 0:
            raise ValueError("positive_revenue_denominator_required")
        values = {row.id: amount(row.amount_cell_id) for row in chart.parts + chart.adjustments}
        if any(values[row.id] < 0 for row in chart.parts):
            raise ValueError("negative_amount_belongs_in_adjustments")
        if chart.chart_type == "donut" and chart.adjustments:
            raise ValueError("donut_cannot_include_adjustments")
        if sum(values.values(), Decimal(0)) != total:
            raise ValueError("revenue_does_not_reconcile")
        subtotal_sets = set()
        for subtotal in chart.reported_subtotals:
            _references(subtotal.component_ids, values.keys(), "subtotal_components")
            component_set = frozenset(subtotal.component_ids)
            if component_set in subtotal_sets:
                raise ValueError("duplicate_reported_subtotal_components")
            subtotal_sets.add(component_set)
            if amount(subtotal.amount_cell_id) != sum((values[cid] for cid in subtotal.component_ids), Decimal(0)):
                raise ValueError("reported_subtotal_does_not_reconcile")
    return value
