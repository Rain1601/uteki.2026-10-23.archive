from __future__ import annotations

from typing import Protocol

from uteki.domain.business_map import BusinessMap

from .models import (
    DocumentContext,
    EvidenceLink,
    MetricPoint,
    PeriodComparison,
    ResearchClaim,
    ResearchDataRequest,
)


class ResearchDataPort(Protocol):
    def get_business_map(self, company_id: str, version: str | None = None) -> BusinessMap: ...

    def search_research_data(
        self, company_id: str, query: str, source_policy_id: str
    ) -> tuple[ResearchClaim, ...]: ...

    def get_claim_evidence(self, claim_id: str) -> tuple[EvidenceLink, ...]: ...

    def get_metric_series(self, metric_id: str, periods: tuple[str, ...]) -> tuple[MetricPoint, ...]: ...

    def get_document_context(self, evidence_ids: tuple[str, ...]) -> tuple[DocumentContext, ...]: ...

    def compare_periods(
        self, company_id: str, periods: tuple[str, ...], data_types: tuple[str, ...]
    ) -> PeriodComparison: ...

    def request_missing_data(self, request: ResearchDataRequest) -> ResearchDataRequest: ...
