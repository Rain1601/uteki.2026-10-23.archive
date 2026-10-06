"""Explicit frozen dataset registry for the read-only MCP boundary.

Hash checks establish identity, not financial correctness. External review labels
are kept separate from candidate/adoption state; held-out answers stay private.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
import json
from pathlib import Path, PurePosixPath
import re

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FIELDS = (
    "source_snapshot_id", "company_id", "source_url", "source_sha256", "document_id",
    "index_id", "form", "period_end", "available_at", "available_at_precision",
    "publication_note", "status", "fiscal_periods", "capabilities", "stage_coverage",
    "block_count", "image_block_count",
)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _path(root, relative):
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("A nonempty relative registered path is required")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative:
        raise ValueError("Registered artifact path must stay under catalog root")
    path = root / relative
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Registered artifact must not traverse a symlink")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Registered artifact escaped catalog root")
    return path


def _pin(path, expected):
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError("Every registered artifact requires SHA256")
    if digest(path.read_bytes()) != expected:
        raise ValueError("Registered artifact integrity mismatch")


def _manifest(folder, expected):
    _pin(folder / "manifest.json", expected)
    manifest = _read(folder / "manifest.json")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Frozen manifest must enumerate files")
    for relative, sha in files.items():
        _pin(_path(folder, relative), sha)
    return manifest


class CatalogEntry:
    def __init__(self, root, config):
        required = {"id", "label", "dataset_path", "manifest_sha256", "company_id", "aliases"}
        if not isinstance(config, dict) or not required <= config.keys() or set(config) - required - {"extraction"}:
            raise ValueError("Unsupported or missing dataset registration fields")
        if not isinstance(config["aliases"], list):
            raise ValueError("Explicit company aliases must be a list")
        self.id, self.label = config["id"], config["label"]
        self.company_id, self.aliases = config["company_id"], tuple(config["aliases"])
        if (not isinstance(self.id, str) or not _ID.fullmatch(self.id)
                or not isinstance(self.company_id, str) or not _ID.fullmatch(self.company_id)
                or not isinstance(self.label, str) or not self.label.strip()
                or not isinstance(config["aliases"], list) or not self.aliases
                or any(not isinstance(a, str) or not a.strip() for a in self.aliases)
                or len({a.casefold().strip() for a in self.aliases}) != len(self.aliases)):
            raise ValueError("Explicit dataset identity, company and distinct aliases are required")
        self.dataset_path = _path(root, config["dataset_path"])
        self.manifest_sha256 = config["manifest_sha256"]
        manifest = _manifest(self.dataset_path, self.manifest_sha256)
        if not {"research.duckdb", "sources.json", "metrics.json"} <= manifest["files"].keys():
            raise ValueError("Dataset manifest does not bind core query artifacts")
        self.port = QueryDataPort(self.dataset_path)
        try:
            self._validate_dataset()
            self._review = None
            self._reviews = {}
            self._extraction = None
            self._implementation_gaps = []
            if "extraction" in config:
                self._load_extraction(root, config["extraction"])
        except Exception:
            self.port.close()
            raise

    def _validate_dataset(self):
        sources = self.port.sources
        self._sources = {s["source_snapshot_id"]: s for s in sources}
        if not sources or len(sources) != len(self._sources):
            raise ValueError("Dataset requires unique source identities")
        if any(s["company_id"] != self.company_id for s in sources):
            raise ValueError("Dataset source company differs from registration")
        for source in sources:
            date.fromisoformat(source["available_at"])
            if not _SHA.fullmatch(source.get("source_sha256", "")):
                raise ValueError("Source content hash required")
            index = _path(self.dataset_path, source["index_folder"])
            for name in ("manifest.json", "index.json", "blocks.jsonl"):
                if str((index / name).relative_to(self.dataset_path)) not in self.port.manifest["files"]:
                    raise ValueError("Source index is not bound by dataset manifest")
            if source.get("raw_file"):
                _path(self.dataset_path, source["raw_file"])
                if source["raw_file"] not in self.port.manifest["files"]:
                    raise ValueError("Source bytes are not bound by dataset manifest")
        db_source_rows = self.port._db.execute("SELECT source_snapshot_id, company_id, payload FROM sources").fetchall()
        if any(company != self.company_id for _, company, _ in db_source_rows):
            raise ValueError("Database contains a source outside registered company")
        db_sources = {sid: json.loads(payload) for sid, _, payload in db_source_rows}
        if db_sources != self._sources:
            raise ValueError("Database source identity differs from frozen source metadata")
        self._records = {}
        for rid, entity, sid, status, payload in self.port._db.execute(
                "SELECT record_id, entity_id, source_snapshot_id, status, payload FROM observations").fetchall():
            row = json.loads(payload)
            if (rid, entity, sid, status) != (row.get("record_id"), row.get("entity_id"),
                    row.get("source_snapshot_id"), row.get("status")) or sid not in self._sources or status != "candidate":
                raise ValueError("Database record payload, source or candidate state mismatch")
            self._records[rid] = row

    def _load_extraction(self, root, registration):
        if not isinstance(registration, dict) or set(registration) - {"path", "manifest_sha256", "review"}:
            raise ValueError("Unsupported extraction registration")
        folder = _path(root, registration["path"])
        manifest = _manifest(folder, registration["manifest_sha256"])
        needed = {"packet.json", "job.json", "result.json", "extraction.json", "normalized.json", "dataset/manifest.json"}
        if not needed <= manifest["files"].keys() or folder / "dataset" != self.dataset_path:
            raise ValueError("Extraction must bind its own complete frozen dataset")
        if manifest["files"]["dataset/manifest.json"] != self.manifest_sha256:
            raise ValueError("Extraction/dataset manifest binding mismatch")
        packet, job, result, extraction, normalized = [_read(folder / n) for n in
            ("packet.json", "job.json", "result.json", "extraction.json", "normalized.json")]
        source = packet["source"]
        sid = source["source_snapshot_id"]
        if (len(self._sources) != 1 or self._sources.get(sid) != source
                or packet["company_id"] != self.company_id or job["company_id"] != self.company_id
                or job["source_snapshot_id"] != sid or result["projection_snapshot_id"] != self.port.snapshot_id):
            raise ValueError("Extraction packet, job or result scope mismatch")
        raw = extraction["records"]
        drafts = {row["draft_id"]: row for row in raw}
        if len(drafts) != len(raw) or normalized["raw_candidates"] != raw:
            raise ValueError("Extraction draft identity mismatch")
        if {r["record_id"]: r for r in normalized["records"]} != self._records:
            raise ValueError("Normalized records differ from candidate database")
        blocks = {b["block_id"]: b for b in packet["blocks"]}
        if len(blocks) != len(packet["blocks"]):
            raise ValueError("Extraction packet contains duplicate block IDs")
        original = {b["block_id"]: b for b in self.port._reader(source).blocks}
        for bid, block in blocks.items():
            if (digest(block["text"].encode()) != block["text_hash"] or bid not in original
                    or original[bid]["text_hash"] != block["text_hash"]):
                raise ValueError("Extraction block differs from frozen source")
        db_evidence = {eid: json.loads(payload) for eid, payload in self.port._db.execute(
            "SELECT evidence_id, payload FROM evidence").fetchall()}
        if db_evidence != normalized["evidence"]:
            raise ValueError("Normalized evidence differs from database")
        for evidence in db_evidence.values():
            block = blocks.get(evidence.get("block_id"))
            start, end = evidence.get("source_start"), evidence.get("source_end")
            if (not block or evidence.get("source_snapshot_id") != sid
                    or evidence.get("source_sha256") != source["source_sha256"]
                    or evidence.get("text_hash") != block["text_hash"]
                    or not isinstance(start, int) or not isinstance(end, int)
                    or not 0 <= start < end <= len(block["text"])
                    or block["text"][start:end] != evidence["quote"]):
                raise ValueError("Normalized evidence is outside its source quote")
        for row in self._records.values():
            if row["origin"].get("raw") != drafts.get(row["origin"].get("draft_id")):
                raise ValueError("Normalized record does not bind its original draft")
            for field in ("evidence_ids", "qualifier_evidence_ids", "question_evidence_ids"):
                if not set(row.get(field, [])) <= db_evidence.keys():
                    raise ValueError("Normalized record references unknown evidence")
        mismatches = sum(manifest["files"].get(name) != sha for name, sha in result.get("implementation", {}).items())
        if mismatches:
            self._implementation_gaps.append({"reason": "implementation_archive_metadata_mismatch",
                "count": mismatches, "scope": "historical run reproducibility", "source_snapshot_id": sid,
                "explanation": "Frozen files are hash-valid, but declared implementation hashes do not all match the archived files."})
        self._extraction = {"source_snapshot_id": sid, "raw": raw, "normalized": normalized, "gaps": extraction["gaps"]}
        if registration.get("review"):
            self._load_review(root, registration, packet, manifest, drafts)

    def _load_review(self, root, registration, packet, manifest, drafts):
        ref = registration["review"]
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError("Review requires path and SHA256")
        path = _path(root, ref["path"])
        _pin(path, ref["sha256"])
        review = _read(path)
        source = packet["source"]
        for field, expected in (("company_id", self.company_id), ("source_snapshot_id", source["source_snapshot_id"]),
                                ("source_sha256", source["source_sha256"]), ("run_id", self.id)):
            if review.get(field) != expected:
                raise ValueError("External review scope mismatch: " + field)
        inputs = review.get("inputs", {})
        for field, expected in (("run_manifest_sha256", registration["manifest_sha256"]),
                                ("packet_sha256", manifest["files"]["packet.json"]),
                                ("extraction_sha256", manifest["files"]["extraction.json"])):
            if inputs.get(field) != expected:
                raise ValueError("External review input binding mismatch")
        if review.get("adoption") != "unchanged_candidate":
            raise ValueError("This catalog supports unchanged candidates only")
        self._review = {"status": "external_review_available", "review_sha256": ref["sha256"],
                        "reviewer": review.get("reviewer"), "overall": review.get("overall"),
                        "source_snapshot_id": source["source_snapshot_id"], "adoption": "unchanged_candidate"}
        for fact in review.get("facts", []):
            did, rid = fact.get("draft_id"), fact.get("record_id")
            if did not in drafts:
                raise ValueError("External review references an unknown draft")
            if not rid:
                continue
            row = self._records.get(rid)
            if row is None or row["origin"]["draft_id"] != did or rid in self._reviews:
                raise ValueError("External review record binding mismatch")
            content = fact.get("source_review", {})
            if content.get("record_id") not in (None, rid) or content.get("draft_id") not in (None, did):
                raise ValueError("External source review record binding mismatch")
            for field, actual in (("normalized_value_decimal", row.get("value_decimal")),
                                  ("normalized_unit", row.get("unit")), ("metric_id", row.get("metric_id"))):
                if field in content and content[field] != actual:
                    raise ValueError("External review content differs from candidate record")
            self._reviews[rid] = {**self._review, "record_id": rid, "verdict": fact.get("verdict"),
                "scope": fact.get("reviewer_scope"), "source_verdict": content.get("verdict"),
                "source_scope": content.get("verdict_scope"), "remaining_limits": content.get("remaining_limits", []),
                "engineering_issues": fact.get("engineering_issues", [])}

    def record_review(self, record_id):
        if record_id not in self._records:
            raise ValueError("Record is outside registered dataset")
        return deepcopy(self._reviews.get(record_id, {"status": "not_reviewed", "record_id": record_id,
                        "adoption": "unchanged_candidate"}))

    def public(self):
        return {"dataset_id": self.id, "label": self.label, "company_id": self.company_id,
            "aliases": list(self.aliases), "snapshot_id": self.port.snapshot_id, "manifest_sha256": self.manifest_sha256,
            "status": "candidate", "source_policy_id": self.port.manifest["source_policy_id"],
            "sources": [{k: deepcopy(s[k]) for k in _SOURCE_FIELDS if k in s} for s in self.port.sources],
            "record_count": len(self._records), "review": deepcopy(self._review) or {"status": "not_reviewed"},
            "gaps": deepcopy(self._implementation_gaps)}

    def status_for_sources(self, source_ids, cutoff, include_candidates):
        selected = set(source_ids)
        if not selected or not selected <= self._sources.keys():
            raise ValueError("Explicit sources in registered dataset required")
        cutoff = date.fromisoformat(cutoff)
        if any(date.fromisoformat(self._sources[s]["available_at"]) > cutoff for s in selected):
            raise ValueError("Source unavailable at requested cutoff")
        if not include_candidates:
            return {"status": "quality_filtered", "reason": "dataset_contains_candidates_only", "adoption": "unchanged_candidate"}
        rows = [r for r in self._records.values() if r["source_snapshot_id"] in selected and date.fromisoformat(r["available_at"]) <= cutoff]
        result = {"status": "candidate", "source_snapshot_ids": sorted(selected), "normalized_record_count": len(rows),
            "adoption": "unchanged_candidate", "review": deepcopy(self._review) or {"status": "not_reviewed"},
            "gaps": deepcopy(self._implementation_gaps), "completeness": "not_evaluated"}
        if not rows:
            result["gaps"].append({"reason": "no_structured_records", "explanation": "Source reading may be available; missing rows do not prove absent disclosure."})
        ext = self._extraction
        if ext and ext["source_snapshot_id"] in selected:
            normalized = ext["normalized"]
            mapped = {r["origin"]["draft_id"] for r in rows}
            diagnostics = normalized["unresolved"]
            result.update(raw_draft_count=len(ext["raw"]), normalization_diagnostic_count=len(diagnostics),
                normalization_diagnostic_counts=dict(Counter(d["reason"] for d in diagnostics)),
                model_reported_gaps=deepcopy(ext["gaps"]),
                unresolved_drafts=[{"draft_id": r["draft_id"], "metric_id": r.get("metric_id"),
                    "source_label": r.get("metric"), "period_id": r.get("period_id"),
                    "reasons": sorted({d["reason"] for d in diagnostics if d.get("draft_id") == r["draft_id"]}),
                    "status": "not_normalized", "adoption": "unchanged_candidate"}
                    for r in ext["raw"] if r["draft_id"] not in mapped])
        return result


class Catalog:
    def __init__(self, config_path: Path):
        config_path = Path(config_path).resolve()
        config = _read(config_path)
        if (not isinstance(config, dict) or set(config) != {"schema_version", "root_path", "datasets"}
                or config["schema_version"] != "data-mcp-catalog-v1"
                or not isinstance(config["root_path"], str) or not config["root_path"].strip()
                or not isinstance(config["datasets"], list) or not config["datasets"]):
            raise ValueError("Explicit root_path and datasets in data-mcp-catalog-v1 required")
        root = (config_path.parent / config["root_path"]).resolve()
        self.entries = {}
        self._aliases = {}
        try:
            for registration in config["datasets"]:
                entry = CatalogEntry(root, registration)
                if entry.id in self.entries:
                    entry.port.close()
                    raise ValueError("Duplicate registered dataset ID")
                self.entries[entry.id] = entry
                for alias in (*entry.aliases, entry.company_id):
                    key = alias.strip().casefold()
                    if key in self._aliases and self._aliases[key] != entry.company_id:
                        raise ValueError("Ambiguous company alias in catalog")
                    self._aliases[key] = entry.company_id
        except Exception:
            self.close()
            raise

    def resolve_company(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Explicit company name, symbol or ID required")
        company = self._aliases.get(query.strip().casefold())
        if company is None:
            raise ValueError("Unknown company in selected catalog")
        return company

    def close(self):
        for entry in self.entries.values():
            entry.port.close()
