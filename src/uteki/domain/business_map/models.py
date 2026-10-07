from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


LEGACY_BUSINESS_MAP_VERSIONS = frozenset({
    "0.1", "0.1-pilot", "0.1-candidate", "0.2-candidate", "0.3-candidate",
    "m0-review-business-map-v1", "business-map-v0.1",
})
BUSINESS_MAP_VERSION = "business-map-v0.2"


class BusinessKind(StrEnum):
    COMPANY = "company"
    REPORTABLE_SEGMENT = "reportable_segment"
    BUSINESS = "business"
    OFFERING_GROUP = "offering_group"
    REVENUE_LINE = "revenue_line"


class RelationshipKind(StrEnum):
    REPORTED_UNDER = "reported_under"
    PART_OF = "part_of"
    REVENUE_COMPONENT_OF = "revenue_component_of"
    SUPPORTS = "supports"


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class AssertionBasis(StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    UNKNOWN = "unknown"


def _nonempty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    document_id: str
    section_path: tuple[str, ...]
    paragraph_ordinal: int
    text_hash: str
    source_url: str
    support: str
    company_id: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.id, "evidence.id")
        _nonempty(self.document_id, "evidence.document_id")
        _nonempty(self.text_hash, "evidence.text_hash")
        if not self.section_path:
            raise ValueError("evidence.section_path must not be empty")
        if self.paragraph_ordinal < 1:
            raise ValueError("evidence.paragraph_ordinal must be >= 1")


@dataclass(frozen=True, slots=True)
class Monetization:
    description: str
    basis: AssertionBasis
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    evidence_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class BusinessClaimEvidence:
    field: str
    item_index: int | None
    excerpts: tuple[EvidenceExcerpt, ...]


@dataclass(frozen=True, slots=True)
class Business:
    id: str
    name: str
    kind: BusinessKind
    description: str
    products_services: tuple[str, ...] = ()
    customers: tuple[str, ...] = ()
    monetization: tuple[Monetization, ...] = ()
    importance_signals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    claim_evidence: tuple[BusinessClaimEvidence, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.id, "business.id")
        _nonempty(self.name, "business.name")


@dataclass(frozen=True, slots=True)
class Relationship:
    source_id: str
    target_id: str
    kind: RelationshipKind
    description: str
    evidence_ids: tuple[str, ...]
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    # None preserves legacy "not assessed"; it must never become explicit.
    basis: AssertionBasis | None = None
    rationale: str | None = None
    excerpts: tuple[EvidenceExcerpt, ...] = ()


@dataclass(frozen=True, slots=True)
class Unknown:
    id: str
    question: str
    materiality: str
    related_business_ids: tuple[str, ...]
    reason_unanswered: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BusinessMap:
    schema_version: str
    company_id: str
    document_id: str
    summary: str
    businesses: tuple[Business, ...]
    relationships: tuple[Relationship, ...]
    unknowns: tuple[Unknown, ...]
    evidence: tuple[Evidence, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    relationship_absence: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in LEGACY_BUSINESS_MAP_VERSIONS | {BUSINESS_MAP_VERSION}:
            raise ValueError("unsupported_business_map_schema_version")
        _nonempty(self.company_id, "business_map.company_id")
        _nonempty(self.document_id, "business_map.document_id")
        business_ids = [item.id for item in self.businesses]
        evidence_ids = [item.id for item in self.evidence]
        if len(business_ids) != len(set(business_ids)):
            raise ValueError("business ids must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence ids must be unique")
        known_businesses = set(business_ids)
        known_evidence = set(evidence_ids)
        for item in self.businesses:
            self._require_known(item.evidence_ids, known_evidence, f"business {item.id}")
            for statement in item.monetization:
                self._require_known(statement.evidence_ids, known_evidence, f"business {item.id} monetization")
        for relation in self.relationships:
            self._require_known((relation.source_id, relation.target_id), known_businesses, "relationship")
            self._require_known(relation.evidence_ids, known_evidence, "relationship")
        for unknown in self.unknowns:
            self._require_known(unknown.related_business_ids, known_businesses, f"unknown {unknown.id}")
            self._require_known(unknown.evidence_ids, known_evidence, f"unknown {unknown.id}")
        if self.schema_version == "business-map-v0.2":
            self._validate_v2()

    def _validate_v2(self) -> None:
        """Validate declared evidence bindings, not semantic entailment."""
        if self.relationship_absence != "unknown":
            raise ValueError("unrecorded_relationship_must_remain_unknown")
        evidence = {e.id: e for e in self.evidence}
        if any(e.document_id != self.document_id or e.company_id != self.company_id for e in self.evidence):
            raise ValueError("business_map_evidence_scope_mismatch")

        def excerpts(items, owner):
            self._require_known(tuple(e.evidence_id for e in items), set(evidence), owner)
            for item in items:
                _nonempty(item.quote, owner + ".quote")
                if " ".join(item.quote.split()) not in " ".join(evidence[item.evidence_id].support.split()):
                    raise ValueError("business_map_quote_not_in_source")

        for business in self.businesses:
            expected = {("name", None), ("description", None)}
            for field_name in ("products_services", "customers", "importance_signals"):
                expected.update((field_name, i) for i in range(len(getattr(business, field_name))))
            expected.update(("monetization", i) for i, m in enumerate(business.monetization)
                            if m.basis != AssertionBasis.UNKNOWN)
            actual = [(c.field, c.item_index) for c in business.claim_evidence]
            if any(c.item_index is not None and type(c.item_index) is not int for c in business.claim_evidence):
                raise ValueError("business_claim_item_index_invalid")
            if len(actual) != len(set(actual)) or set(actual) != expected:
                raise ValueError("business_claim_coverage_mismatch")
            for claim in business.claim_evidence:
                if not claim.excerpts:
                    raise ValueError("business_claim_excerpt_required")
                excerpts(claim.excerpts, "business_claim")
                ids = {e.evidence_id for e in claim.excerpts}
                if not ids.issubset(business.evidence_ids):
                    raise ValueError("business_claim_not_in_node_evidence")
                if claim.field == "monetization" and ids != set(business.monetization[claim.item_index].evidence_ids):
                    raise ValueError("monetization_claim_evidence_mismatch")
        identities = [(r.source_id, r.kind, r.target_id) for r in self.relationships]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_relationship")
        for relation in self.relationships:
            if relation.basis not in tuple(AssertionBasis) or not relation.rationale or not relation.rationale.strip():
                raise ValueError("relationship_basis_and_rationale_required")
            if relation.source_id == relation.target_id:
                raise ValueError("self_relationship_unsupported")
            excerpts(relation.excerpts, "relationship")
            if {e.evidence_id for e in relation.excerpts} != set(relation.evidence_ids):
                raise ValueError("relationship_excerpt_evidence_mismatch")
            if relation.basis != AssertionBasis.UNKNOWN and not relation.excerpts:
                raise ValueError("asserted_relationship_excerpt_required")
            if relation.basis == AssertionBasis.UNKNOWN:
                if relation.review_status in (ReviewStatus.ACCEPTED, ReviewStatus.EDITED):
                    raise ValueError("unknown_relationship_cannot_be_accepted")
                if not any({relation.source_id, relation.target_id}.issubset(u.related_business_ids) for u in self.unknowns):
                    raise ValueError("unknown_relationship_requires_gap")

    @staticmethod
    def _require_known(values: tuple[str, ...], known: set[str], owner: str) -> None:
        missing = sorted(set(values) - known)
        if missing:
            raise ValueError(f"{owner} references unknown ids: {', '.join(missing)}")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.schema_version != "business-map-v0.2":
            # Historical products remain byte-shape compatible. Reading them
            # neither invents evidence annotations nor upgrades their basis.
            value.pop("relationship_absence")
            for business in value["businesses"]:
                business.pop("claim_evidence")
            for relation in value["relationships"]:
                for key in ("basis", "rationale", "excerpts"):
                    relation.pop(key)
            for evidence in value["evidence"]:
                evidence.pop("company_id")
        return value


def business_map_from_dict(value: dict[str, Any]) -> BusinessMap:
    evidence = tuple(
        Evidence(
            id=item["id"],
            document_id=item["document_id"],
            section_path=tuple(item["section_path"]),
            paragraph_ordinal=item["paragraph_ordinal"],
            text_hash=item["text_hash"],
            source_url=item["source_url"],
            support=item["support"],
            company_id=item.get("company_id"),
        )
        for item in value.get("evidence", [])
    )
    businesses = tuple(
        Business(
            id=item["id"],
            name=item["name"],
            kind=BusinessKind(item["kind"]),
            description=item["description"],
            products_services=tuple(item.get("products_services", [])),
            customers=tuple(item.get("customers", [])),
            monetization=tuple(
                Monetization(
                    description=statement["description"],
                    basis=AssertionBasis(statement["basis"]),
                    evidence_ids=tuple(statement.get("evidence_ids", [])),
                )
                for statement in item.get("monetization", [])
            ),
            importance_signals=tuple(item.get("importance_signals", [])),
            evidence_ids=tuple(item.get("evidence_ids", [])),
            review_status=ReviewStatus(item.get("review_status", "candidate")),
            claim_evidence=tuple(BusinessClaimEvidence(
                field=c["field"], item_index=c["item_index"],
                excerpts=tuple(EvidenceExcerpt(e["evidence_id"], e["quote"]) for e in c["excerpts"]))
                for c in item.get("claim_evidence", [])),
        )
        for item in value.get("businesses", [])
    )
    relationships = tuple(
        Relationship(
            source_id=item["source_id"],
            target_id=item["target_id"],
            kind=RelationshipKind(item["kind"]),
            description=item["description"],
            evidence_ids=tuple(item.get("evidence_ids", [])),
            review_status=ReviewStatus(item.get("review_status", "candidate")),
            basis=AssertionBasis(item["basis"]) if item.get("basis") is not None else None,
            rationale=item.get("rationale"),
            excerpts=tuple(EvidenceExcerpt(e["evidence_id"], e["quote"]) for e in item.get("excerpts", [])),
        )
        for item in value.get("relationships", [])
    )
    unknowns = tuple(
        Unknown(
            id=item["id"],
            question=item["question"],
            materiality=item["materiality"],
            related_business_ids=tuple(item.get("related_business_ids", [])),
            reason_unanswered=item["reason_unanswered"],
            evidence_ids=tuple(item.get("evidence_ids", [])),
        )
        for item in value.get("unknowns", [])
    )
    return BusinessMap(
        schema_version=value["schema_version"],
        company_id=value["company_id"],
        document_id=value["document_id"],
        summary=value["summary"],
        businesses=businesses,
        relationships=relationships,
        unknowns=unknowns,
        evidence=evidence,
        metadata=value.get("metadata", {}),
        relationship_absence=value.get("relationship_absence"),
    )
