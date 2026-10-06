"""Typed retrieval evidence, separate from storage and analytical conclusions."""
from collections import deque
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from typing import Literal

from pydantic import Field, model_validator

from .execution_scope import ExecutionScope
from .query_contract import Contract, ResearchRecord

PACKAGE_VERSION = "retrieval-evidence-v1"
SHA_PATTERN = r"^[0-9a-fA-F]{64}$"


def _unique_ids(values, name):
    if any(not value.strip() or value != value.strip() for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{name} requires unique, nonblank, unpadded IDs")


class SourceLocator(Contract):
    source_snapshot_id: str = Field(min_length=1, pattern=r"\S")
    source_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    source_url: str | None = Field(default=None, min_length=1, pattern=r"\S")
    available_at: date | None = None
    index_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    block_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    reported_page: str | int | None = None
    pdf_page: int | None = Field(default=None, ge=1)
    dom_path: str | None = Field(default=None, min_length=1)
    text_hash: str | None = Field(default=None, pattern=SHA_PATTERN)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    cell: dict[str, int] | None = None
    bbox: tuple[float, float, float, float] | None = None
    region_coordinate_system: str | None = Field(default=None, min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def explicit_coordinates(self):
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("character bounds must both be supplied or both remain unknown")
        if self.char_start is not None and self.char_end <= self.char_start:
            raise ValueError("character bounds require a positive ordered range")
        if self.cell is not None and (set(self.cell) != {"row", "column"} or any(v < 0 for v in self.cell.values())):
            raise ValueError("cell requires explicit zero-based row and column")
        if (self.bbox is None) != (self.region_coordinate_system is None):
            raise ValueError("region bounds and their coordinate system must be declared together")
        if self.bbox is not None and (not all(math.isfinite(v) for v in self.bbox)
                                     or self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]):
            raise ValueError("region bounds require finite positive ordered dimensions")
        if isinstance(self.reported_page, str) and not self.reported_page.strip():
            raise ValueError("unknown reported page must remain null")
        return self


class Provenance(Contract):
    method: Literal["source_read", "source_quote", "normalization", "registered_calculation", "model", "unknown"]
    method_id: str = Field(min_length=1, pattern=r"\S")
    input_artifact_id: str | None = Field(default=None, min_length=1)
    input_path: str | None = Field(default=None, min_length=1)
    input_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    prompt_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    verification: Literal["source_verified", "snapshot_verified", "declared_unverified"]
    notes: tuple[str, ...] = ()


class SourceText(Contract):
    text: str
    block: dict

    @model_validator(mode="after")
    def original_text(self):
        if self.block.get("text") != self.text or self.block.get("type") in (None, "image", "table"):
            raise ValueError("source text must preserve original non-image, non-table block text")
        return self


class SourceTable(Contract):
    text: str
    table: dict
    block: dict

    @model_validator(mode="after")
    def original_table(self):
        if self.block.get("type") != "table" or self.block.get("text") != self.text or self.block.get("table") != self.table:
            raise ValueError("source table must preserve the original table block, text and cells")
        return self


class SourceQuote(Contract):
    text: str = Field(min_length=1, pattern=r"\S")
    evidence: dict

    @model_validator(mode="after")
    def original_quote(self):
        if self.evidence.get("quote") != self.text:
            raise ValueError("source quote text must match the retained evidence quote")
        return self


class ImageReference(Contract):
    alt_text: str = ""
    image_asset_id: str | None = Field(default=None, min_length=1)
    asset_metadata: dict | None = None
    bytes_status: Literal["verified_local", "metadata_only", "unresolved"]
    bytes_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    ocr_status: Literal["not_run"] = "not_run"
    vision_status: Literal["not_run"] = "not_run"

    @model_validator(mode="after")
    def bytes_evidence(self):
        if (self.bytes_status == "verified_local") != (self.bytes_sha256 is not None):
            raise ValueError("only verified local image bytes may carry a verified byte hash")
        if self.bytes_status == "verified_local" and self.image_asset_id is None:
            raise ValueError("verified image bytes require an explicit asset identity")
        return self


class NormalizedRecord(Contract):
    record: ResearchRecord
    origin_kind: Literal["deterministic", "model_assisted", "unknown"]


class ComputedScalar(Contract):
    fact: dict

    @model_validator(mode="after")
    def exact_finite_value(self):
        for key in ("value_decimal", "display_decimal"):
            value = self.fact.get(key)
            if not isinstance(value, str):
                raise ValueError(f"{key} requires a decimal string")
            try:
                number = Decimal(value)
            except InvalidOperation as error:
                raise ValueError("computed value must be a decimal string") from error
            if not number.is_finite():
                raise ValueError("computed value must be finite")
        operands = self.fact.get("operand_record_ids")
        if not isinstance(operands, (list, tuple)) or not operands or any(not isinstance(x, str) for x in operands):
            raise ValueError("computed fact requires operand record IDs")
        _unique_ids(operands, "operand_record_ids")
        return self


class ModelExtract(Contract):
    extraction: dict


class ModelSummary(Contract):
    text: str = Field(min_length=1, pattern=r"\S")


Payload = SourceText | SourceTable | SourceQuote | ImageReference | NormalizedRecord | ComputedScalar | ModelExtract | ModelSummary
PAYLOAD_TYPES = {"source_text": SourceText, "source_table": SourceTable, "source_quote": SourceQuote,
                 "image_reference": ImageReference, "normalized_record": NormalizedRecord,
                 "computed_scalar": ComputedScalar, "model_extract": ModelExtract, "model_summary": ModelSummary}


class EvidenceArtifact(Contract):
    artifact_id: str = Field(min_length=1, pattern=r"\S")
    kind: Literal["source_text", "source_table", "source_quote", "image_reference", "normalized_record",
                  "computed_scalar", "model_extract", "model_summary"]
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    locators: tuple[SourceLocator, ...] = ()
    derived_from: tuple[str, ...] = ()
    provenance: Provenance
    payload: Payload

    @model_validator(mode="after")
    def typed_provenance(self):
        _unique_ids((self.artifact_id,), "artifact_id")
        _unique_ids(self.source_snapshot_ids, "source_snapshot_ids")
        _unique_ids(self.derived_from, "derived_from")
        if not isinstance(self.payload, PAYLOAD_TYPES[self.kind]):
            raise ValueError("artifact kind and payload type disagree")
        if any(loc.source_snapshot_id not in self.source_snapshot_ids for loc in self.locators):
            raise ValueError("locator source is outside artifact sources")
        if self.kind in ("source_text", "source_table", "image_reference"):
            if self.derived_from or self.provenance.method != "source_read" or not self.locators:
                raise ValueError("source roots require source_read locators and cannot masquerade as derived artifacts")
        elif self.kind == "source_quote":
            if self.provenance.method != "source_quote" or not self.locators:
                raise ValueError("source quote requires quote provenance and a source locator")
        elif self.kind in ("model_extract", "model_summary"):
            if self.provenance.method != "model" or not self.derived_from:
                raise ValueError("model artifacts require declared model provenance and source parents")
        elif self.kind == "normalized_record":
            if not self.derived_from or self.provenance.method != "normalization":
                raise ValueError("normalized records require normalization provenance and parents")
            if self.payload.record.source_snapshot_id not in self.source_snapshot_ids:
                raise ValueError("normalized record source is outside artifact sources")
        elif self.kind == "computed_scalar":
            if not self.derived_from or self.provenance.method != "registered_calculation":
                raise ValueError("computed scalars require registered calculation provenance and parents")
        return self


class EvidenceGap(Contract):
    gap_id: str = Field(min_length=1, pattern=r"\S")
    reason: str = Field(min_length=1, pattern=r"\S")
    artifact_ids: tuple[str, ...] = ()
    source_snapshot_ids: tuple[str, ...] = ()
    detail: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def unique_references(self):
        _unique_ids((self.gap_id,), "gap_id")
        _unique_ids(self.artifact_ids, "gap artifact_ids")
        _unique_ids(self.source_snapshot_ids, "gap source_snapshot_ids")
        return self


class CoverageEntry(Contract):
    source_snapshot_id: str = Field(min_length=1, pattern=r"\S")
    node_id: str | None = Field(default=None, min_length=1)
    block_ids: tuple[str, ...] = ()
    mode: Literal["body_returned", "provenance_only", "navigation_only", "image_reference_only"]
    semantic_completeness: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def unique_blocks(self):
        _unique_ids(self.block_ids, "coverage block_ids")
        if self.mode == "body_returned" and not self.block_ids:
            raise ValueError("body-returned coverage requires actual block IDs")
        return self


class EvidencePackage(Contract):
    schema_version: Literal["retrieval-evidence-v1"] = PACKAGE_VERSION
    bundle_id: str = Field(min_length=1, pattern=r"\S")
    scope: ExecutionScope
    source_companies: dict[str, str]
    artifacts: tuple[EvidenceArtifact, ...] = ()
    bindings: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    coverage: tuple[CoverageEntry, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    semantic_completeness: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def closed_scoped_graph(self):
        selected = set(self.scope.source_snapshot_ids)
        if set(self.source_companies) != selected or set(self.source_companies.values()) != set(self.scope.company_ids):
            raise ValueError("source_companies must exactly cover the selected source and company scope")
        if self.artifacts and not self.scope.include_candidates:
            raise ValueError("candidate evidence artifacts require explicit candidate access")
        by_id = {artifact.artifact_id: artifact for artifact in self.artifacts}
        if len(by_id) != len(self.artifacts):
            raise ValueError("artifact IDs must be unique")
        if len({gap.gap_id for gap in self.gaps}) != len(self.gaps):
            raise ValueError("gap IDs must be unique")
        for gap in self.gaps:
            if set(gap.artifact_ids) - by_id.keys() or set(gap.source_snapshot_ids) - selected:
                raise ValueError("gap references an unknown artifact or out-of-scope source")
        for legacy_id, ids in self.bindings.items():
            if not legacy_id.strip() or not ids or set(ids) - by_id.keys():
                raise ValueError("bindings require an explicit ID and existing artifact references")
            _unique_ids(ids, "binding artifact IDs")

        def has_gap(reason, artifact, source=None):
            return any(g.reason == reason and (artifact.artifact_id in g.artifact_ids
                       or (source is not None and source in g.source_snapshot_ids)) for g in self.gaps)

        indegrees, children = {}, {key: [] for key in by_id}
        for artifact in self.artifacts:
            if set(artifact.source_snapshot_ids) - selected:
                raise ValueError("artifact source is outside execution scope")
            parents = [by_id[parent] for parent in artifact.derived_from if parent in by_id]
            if len(parents) != len(artifact.derived_from):
                raise ValueError("derived artifact references a missing parent")
            if parents and set(artifact.source_snapshot_ids) != {sid for parent in parents for sid in parent.source_snapshot_ids}:
                raise ValueError("derived artifact source set must match its parents")
            indegrees[artifact.artifact_id] = len(parents)
            for parent in parents:
                children[parent.artifact_id].append(artifact.artifact_id)
            for locator in artifact.locators:
                if locator.available_at is not None and locator.available_at > self.scope.knowledge_cutoff:
                    raise ValueError("locator source is after the knowledge cutoff")
                if any(getattr(locator, name) is None for name in ("source_sha256", "source_url", "available_at")):
                    if not has_gap("source_metadata_incomplete", artifact, locator.source_snapshot_id):
                        raise ValueError("missing source metadata requires an explicit source_metadata_incomplete gap")
            if artifact.kind == "source_quote":
                if not parents and (artifact.provenance.verification != "snapshot_verified"
                                    or not has_gap("quote_without_read_parent", artifact)):
                    raise ValueError("quote without a read parent requires snapshot verification and a quote_without_read_parent gap")
                if any(parent.kind not in ("source_text", "source_table") for parent in parents):
                    raise ValueError("quote parents must be original text or tables")
                evidence = artifact.payload.evidence
                evidence_source = evidence.get("source_snapshot_id")
                if evidence_source is not None and evidence_source not in artifact.source_snapshot_ids:
                    raise ValueError("retained quote evidence source conflicts with artifact sources")
                evidence_block = evidence.get("block_id")
                if evidence_block is not None and not any(
                        loc.block_id == evidence_block and (evidence_source is None or loc.source_snapshot_id == evidence_source)
                        for loc in artifact.locators):
                    raise ValueError("retained quote evidence block conflicts with its locators")
                if parents:
                    for locator in artifact.locators:
                        matches = []
                        for parent in parents:
                            if locator.block_id is None or parent.payload.block.get("block_id") != locator.block_id:
                                continue
                            for parent_locator in parent.locators:
                                if (parent_locator.source_snapshot_id != locator.source_snapshot_id
                                        or parent_locator.block_id != locator.block_id):
                                    continue
                                # Unknown metadata stays unknown; declared metadata
                                # cannot point at a different source/index/block.
                                metadata = ("index_id", "source_sha256", "source_url", "available_at",
                                            "text_hash", "dom_path", "reported_page", "pdf_page")
                                if any(getattr(locator, key) is not None and getattr(parent_locator, key) is not None
                                       and getattr(locator, key) != getattr(parent_locator, key) for key in metadata):
                                    continue
                                if artifact.payload.text not in parent.payload.text:
                                    continue
                                if locator.char_start is not None and parent.payload.text[locator.char_start:locator.char_end] != artifact.payload.text:
                                    continue
                                matches.append(parent)
                        if not matches:
                            raise ValueError("quote locator and text must match a corresponding original parent block")
            if artifact.kind == "normalized_record" and artifact.payload.record.available_at > self.scope.knowledge_cutoff:
                raise ValueError("normalized record is after the knowledge cutoff")
            if artifact.kind == "computed_scalar":
                if any(parent.kind != "normalized_record" for parent in parents):
                    raise ValueError("computed scalar parents must be normalized records")
                if {parent.payload.record.record_id for parent in parents} != set(artifact.payload.fact["operand_record_ids"]):
                    raise ValueError("computed operand IDs must exactly match normalized parent records")
        pending = deque(key for key, degree in indegrees.items() if degree == 0)
        visited = 0
        while pending:
            visited += 1
            for child in children[pending.popleft()]:
                indegrees[child] -= 1
                if indegrees[child] == 0:
                    pending.append(child)
        if visited != len(by_id):
            raise ValueError("artifact derivation graph must be acyclic")
        body_blocks = {(loc.source_snapshot_id, loc.block_id) for artifact in self.artifacts
                       if artifact.kind in ("source_text", "source_table") for loc in artifact.locators if loc.block_id}
        image_blocks = {(loc.source_snapshot_id, loc.block_id) for artifact in self.artifacts
                        if artifact.kind == "image_reference" for loc in artifact.locators if loc.block_id}
        for entry in self.coverage:
            if entry.source_snapshot_id not in selected:
                raise ValueError("coverage source is outside execution scope")
            if entry.mode in ("body_returned", "image_reference_only"):
                present = body_blocks if entry.mode == "body_returned" else image_blocks
                if any((entry.source_snapshot_id, bid) not in present for bid in entry.block_ids):
                    raise ValueError("coverage must be backed by returned artifacts of the declared kind")
        return self
