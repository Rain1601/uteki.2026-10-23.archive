from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uteki.domain.business_map import BusinessMap, business_map_from_dict
from uteki.domain.research_data import (
    DocumentContext,
    EvidenceBundle,
    EvidenceLink,
    MetricPoint,
    PeriodComparison,
    ResearchClaim,
    ResearchDataRequest,
    evidence_bundle_from_dict,
)


class ResearchDataIntegrityError(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


class LocalResearchDataPort:
    """Read published Research Data and submit missing-data requests locally."""

    def __init__(self, release_dir: Path, *, request_dir: Path | None = None) -> None:
        self.release_dir = release_dir
        self.request_dir = request_dir or release_dir.parent / "requests"
        self.manifest = self._read_json("manifest.json")
        self._validate_artifacts()
        self.bundle = evidence_bundle_from_dict(self._read_json("evidence_bundle.json"))
        self.business_map = business_map_from_dict(self._read_json("business_map.json"))
        self._validate_release()

    def _read_json(self, filename: str) -> dict[str, Any]:
        path = self.release_dir / filename
        if not path.is_file():
            raise ResearchDataIntegrityError(f"research-data artifact is missing: {filename}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate_artifacts(self) -> None:
        for filename, expected in self.manifest.get("artifacts", {}).items():
            path = self.release_dir / filename
            if not path.is_file():
                raise ResearchDataIntegrityError(f"research-data artifact is missing: {filename}")
            raw = path.read_bytes()
            if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise ResearchDataIntegrityError(f"research-data artifact failed integrity check: {filename}")

    def _validate_release(self) -> None:
        if self.manifest["bundle_id"] != self.bundle.bundle_id:
            raise ResearchDataIntegrityError("manifest and EvidenceBundle bundle_id differ")
        if self.manifest["data_snapshot_id"] != self.bundle.data_snapshot_id:
            raise ResearchDataIntegrityError("manifest and EvidenceBundle data_snapshot_id differ")
        if self.manifest["source_policy_id"] != self.bundle.source_policy_id:
            raise ResearchDataIntegrityError("manifest and EvidenceBundle source_policy_id differ")
        if self.business_map.company_id != self.bundle.company_id:
            raise ResearchDataIntegrityError("Business Map and EvidenceBundle company_id differ")
        if self.business_map.metadata.get("benchmark_version") != self.bundle.business_map_version:
            raise ResearchDataIntegrityError("Business Map and EvidenceBundle versions differ")

    def get_business_map(self, company_id: str, version: str | None = None) -> BusinessMap:
        self._require_company(company_id)
        if version is not None and version != self.bundle.business_map_version:
            raise KeyError(f"Business Map version is unavailable: {version}")
        return self.business_map

    def search_research_data(
        self, company_id: str, query: str, source_policy_id: str
    ) -> tuple[ResearchClaim, ...]:
        self._require_company(company_id)
        if source_policy_id != self.bundle.source_policy_id:
            raise PermissionError(f"source policy is unavailable: {source_policy_id}")
        terms = tuple(item for item in query.casefold().split() if item)
        if not terms:
            raise ValueError("query must not be empty")

        matches: list[tuple[int, ResearchClaim]] = []
        for claim in self.bundle.claims:
            haystack = " ".join(
                (
                    claim.id,
                    claim.business_id,
                    claim.field,
                    claim.label_en,
                    claim.label_zh,
                    claim.value_en,
                    claim.value_zh,
                )
            ).casefold()
            if all(term in haystack for term in terms):
                score = sum(haystack.count(term) for term in terms)
                matches.append((score, claim))
        return tuple(item for _, item in sorted(matches, key=lambda pair: (-pair[0], pair[1].id)))

    def get_claim_evidence(self, claim_id: str) -> tuple[EvidenceLink, ...]:
        if claim_id not in {item.id for item in self.bundle.claims}:
            raise KeyError(f"claim is unavailable: {claim_id}")
        return tuple(item for item in self.bundle.evidence_links if item.claim_id == claim_id)

    def get_metric_series(self, metric_id: str, periods: tuple[str, ...]) -> tuple[MetricPoint, ...]:
        known_ids = {item.metric_id for item in self.bundle.metrics}
        if metric_id not in known_ids:
            raise KeyError(f"metric is unavailable: {metric_id}")
        allowed_periods = set(periods)
        return tuple(
            item
            for item in self.bundle.metrics
            if item.metric_id == metric_id and (not periods or item.period in allowed_periods)
        )

    def get_document_context(self, evidence_ids: tuple[str, ...]) -> tuple[DocumentContext, ...]:
        by_id = {item.evidence_id: item for item in self.bundle.document_context}
        missing = sorted(set(evidence_ids) - set(by_id))
        if missing:
            raise KeyError(f"evidence context is unavailable: {', '.join(missing)}")
        return tuple(by_id[item] for item in evidence_ids)

    def compare_periods(
        self, company_id: str, periods: tuple[str, ...], data_types: tuple[str, ...]
    ) -> PeriodComparison:
        self._require_company(company_id)
        requested_types = set(data_types)
        requested_periods = set(periods)
        metrics = tuple(
            item
            for item in self.bundle.metrics
            if (not requested_types or item.metric in requested_types)
            and (not requested_periods or item.period in requested_periods)
        )
        present_periods = {item.period for item in metrics}
        return PeriodComparison(
            company_id=company_id,
            requested_periods=periods,
            data_types=data_types,
            metrics=metrics,
            missing_periods=tuple(item for item in periods if item not in present_periods),
        )

    def request_missing_data(self, request: ResearchDataRequest) -> ResearchDataRequest:
        self._require_company(request.company_id)
        if request.status != "requested":
            raise ValueError("a new ResearchDataRequest must have status=requested")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", request.request_id):
            raise ValueError("request_id must be a safe identifier, not a file path")
        self.request_dir.mkdir(parents=True, exist_ok=True)
        target = self.request_dir / f"{request.request_id}.json"
        content = _json_bytes(asdict(request))
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != content:
                raise FileExistsError(f"request id already exists with different content: {request.request_id}")
        return request

    def _require_company(self, company_id: str) -> None:
        if company_id != self.bundle.company_id:
            raise KeyError(f"company is unavailable: {company_id}")
