from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


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

    def __post_init__(self) -> None:
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

    @staticmethod
    def _require_known(values: tuple[str, ...], known: set[str], owner: str) -> None:
        missing = sorted(set(values) - known)
        if missing:
            raise ValueError(f"{owner} references unknown ids: {', '.join(missing)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    )
