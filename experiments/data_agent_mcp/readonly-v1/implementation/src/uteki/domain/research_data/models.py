from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _nonempty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class ResearchDataQuery:
    query_id: str
    company_id: str
    question: str
    requested_data_types: tuple[str, ...]
    periods: tuple[str, ...]
    source_policy_id: str
    related_research_ids: tuple[str, ...] = ()
    minimum_evidence_level: str = "source_located"
    created_at: str = ""

    def __post_init__(self) -> None:
        _nonempty(self.query_id, "query.query_id")
        _nonempty(self.company_id, "query.company_id")
        _nonempty(self.question, "query.question")
        _nonempty(self.source_policy_id, "query.source_policy_id")


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    id: str
    business_id: str
    field: str
    label_en: str
    label_zh: str
    value_en: str
    value_zh: str
    basis: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonempty(self.id, "claim.id")
        _nonempty(self.business_id, "claim.business_id")
        _nonempty(self.field, "claim.field")
        if not self.evidence_ids:
            raise ValueError(f"claim {self.id} must cite evidence")


@dataclass(frozen=True, slots=True)
class MetricPoint:
    metric_id: str
    claim_id: str
    business_id: str
    metric: str
    period: str
    value: int
    unit: str
    reported_value_en: str
    reported_value_zh: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    link_id: str
    claim_id: str
    evidence_id: str
    source_snapshot_id: str
    document_id: str
    section_path: tuple[str, ...]
    paragraph_ordinal: int
    text_hash: str
    source_url: str
    support: str
    quote_en: str
    quote_zh: str

    def __post_init__(self) -> None:
        if self.paragraph_ordinal < 1:
            raise ValueError(f"evidence link {self.link_id} paragraph_ordinal must be >= 1")


@dataclass(frozen=True, slots=True)
class DocumentContext:
    evidence_id: str
    source_snapshot_id: str
    document_id: str
    section_path: tuple[str, ...]
    paragraph_ordinal: int
    text_hash: str
    source_url: str
    support: str
    quotes_en: tuple[str, ...]
    quotes_zh: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchUnknown:
    id: str
    question: str
    materiality: str
    related_business_ids: tuple[str, ...]
    reason_unanswered: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityDiagnostic:
    code: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    schema_version: str
    bundle_id: str
    query_id: str
    company_id: str
    status: str
    source_policy_id: str
    data_snapshot_id: str
    source_snapshot_ids: tuple[str, ...]
    document_index_ids: tuple[str, ...]
    business_map_version: str
    business_map_ref: str
    source_as_of: str
    generated_at: str
    claims: tuple[ResearchClaim, ...]
    metrics: tuple[MetricPoint, ...]
    changes: tuple[dict[str, Any], ...]
    evidence_links: tuple[EvidenceLink, ...]
    document_context: tuple[DocumentContext, ...]
    unknowns: tuple[ResearchUnknown, ...]
    quality_diagnostics: tuple[QualityDiagnostic, ...]

    def __post_init__(self) -> None:
        _nonempty(self.bundle_id, "bundle.bundle_id")
        _nonempty(self.data_snapshot_id, "bundle.data_snapshot_id")
        _nonempty(self.source_policy_id, "bundle.source_policy_id")
        if not self.source_snapshot_ids:
            raise ValueError("bundle.source_snapshot_ids must not be empty")
        self._require_unique((item.id for item in self.claims), "claim")
        self._require_unique((item.metric_id for item in self.metrics), "metric")
        self._require_unique((item.link_id for item in self.evidence_links), "evidence link")
        self._require_unique((item.evidence_id for item in self.document_context), "document context")

        link_pairs = {(item.claim_id, item.evidence_id) for item in self.evidence_links}
        claim_ids = {item.id for item in self.claims}
        context_ids = {item.evidence_id for item in self.document_context}
        for claim in self.claims:
            missing = [item for item in claim.evidence_ids if (claim.id, item) not in link_pairs]
            if missing:
                raise ValueError(f"claim {claim.id} has unlinked evidence: {', '.join(missing)}")
        for link in self.evidence_links:
            if link.claim_id not in claim_ids:
                raise ValueError(f"evidence link references unknown claim: {link.claim_id}")
            if link.evidence_id not in context_ids:
                raise ValueError(f"evidence link references unknown context: {link.evidence_id}")
            if link.source_snapshot_id not in self.source_snapshot_ids:
                raise ValueError(f"evidence link references unknown source snapshot: {link.source_snapshot_id}")
        for metric in self.metrics:
            if metric.claim_id not in claim_ids:
                raise ValueError(f"metric references unknown claim: {metric.claim_id}")

    @staticmethod
    def _require_unique(values: Any, label: str) -> None:
        materialized = list(values)
        if len(materialized) != len(set(materialized)):
            raise ValueError(f"{label} ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResearchDataRequest:
    request_id: str
    research_question: str
    missing_information: str
    why_material: str
    suggested_source_types: tuple[str, ...]
    company_id: str
    periods: tuple[str, ...]
    related_driver_or_risk_ids: tuple[str, ...]
    priority: str
    status: str = "requested"


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    company_id: str
    requested_periods: tuple[str, ...]
    data_types: tuple[str, ...]
    metrics: tuple[MetricPoint, ...]
    missing_periods: tuple[str, ...]


def evidence_bundle_from_dict(value: dict[str, Any]) -> EvidenceBundle:
    return EvidenceBundle(
        schema_version=value["schema_version"],
        bundle_id=value["bundle_id"],
        query_id=value["query_id"],
        company_id=value["company_id"],
        status=value["status"],
        source_policy_id=value["source_policy_id"],
        data_snapshot_id=value["data_snapshot_id"],
        source_snapshot_ids=tuple(value["source_snapshot_ids"]),
        document_index_ids=tuple(value["document_index_ids"]),
        business_map_version=value["business_map_version"],
        business_map_ref=value["business_map_ref"],
        source_as_of=value["source_as_of"],
        generated_at=value["generated_at"],
        claims=tuple(
            ResearchClaim(**{**item, "evidence_ids": tuple(item.get("evidence_ids", []))})
            for item in value.get("claims", [])
        ),
        metrics=tuple(
            MetricPoint(**{**item, "evidence_ids": tuple(item.get("evidence_ids", []))})
            for item in value.get("metrics", [])
        ),
        changes=tuple(value.get("changes", [])),
        evidence_links=tuple(
            EvidenceLink(**{**item, "section_path": tuple(item.get("section_path", []))})
            for item in value.get("evidence_links", [])
        ),
        document_context=tuple(
            DocumentContext(
                **{
                    **item,
                    "section_path": tuple(item.get("section_path", [])),
                    "quotes_en": tuple(item.get("quotes_en", [])),
                    "quotes_zh": tuple(item.get("quotes_zh", [])),
                }
            )
            for item in value.get("document_context", [])
        ),
        unknowns=tuple(
            ResearchUnknown(
                **{
                    **item,
                    "related_business_ids": tuple(item.get("related_business_ids", [])),
                    "evidence_ids": tuple(item.get("evidence_ids", [])),
                }
            )
            for item in value.get("unknowns", [])
        ),
        quality_diagnostics=tuple(QualityDiagnostic(**item) for item in value.get("quality_diagnostics", [])),
    )
