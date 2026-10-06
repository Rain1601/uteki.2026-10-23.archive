"""Read-only views of explicitly registered, hash-pinned Data evaluation artifacts.

This adapter displays historical evidence and review judgments. It does not run
an agent, repair records, adopt candidates, or accept filesystem paths from a UI.
"""
from __future__ import annotations

from functools import wraps
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import duckdb

from uteki.agents.data_query.answer_handoff import validate_assessment
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest

REGISTRATION = "data/evaluation_views/data-agent-v1.json"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,95}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _public(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, KeyError, TypeError, IndexError, duckdb.Error) as error:
            raise ValueError(f"Evaluation artifact unavailable or invalid ({type(error).__name__})") from error
    return checked


def _path(root, relative):
    """Reject traversal and symlinks before reading any registered artifact."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Artifact path must be an explicit relative path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(p in {".", ".."} for p in parts.parts) or str(parts) != relative:
        raise ValueError("Artifact path outside registered root")
    root = Path(root).resolve()
    current = root
    for part in parts.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Artifact symlinks are unsupported")
    if not current.resolve().is_relative_to(root):
        raise ValueError("Artifact path outside registered root")
    return current


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _manifest(folder, expected):
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError("Explicit manifest SHA256 is required")
    path = _path(folder, "manifest.json")
    if _hash(path) != expected:
        raise ValueError("Manifest integrity mismatch")
    manifest = _json(path)
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("Frozen manifest has no files")
    for relative, sha in files.items():
        if not isinstance(sha, str) or not _SHA.fullmatch(sha) or _hash(_path(folder, relative)) != sha:
            raise ValueError("Frozen file integrity mismatch: " + relative)
    return manifest


def _read(folder, manifest, relative):
    if relative not in manifest["files"]:
        raise ValueError("Artifact is not listed in frozen manifest: " + relative)
    return _json(_path(folder, relative))


def _registration(root):
    config = _json(_path(root, REGISTRATION))
    if config.get("schema_version") != "data-evaluation-view-v1":
        raise ValueError("Unsupported evaluation registration version")
    for kind in ("datasets", "runs"):
        entries = config[kind]
        ids = [e["id"] for e in entries]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not _ID.fullmatch(i) for i in ids):
            raise ValueError("Missing, invalid or duplicate registration ID")
    for entry in config["datasets"]:
        if PurePosixPath(entry["path"]).parts[0] != "data":
            raise ValueError("Dataset must be registered under data/")
        _path(root, entry["path"])
    for entry in config["runs"]:
        if entry["dataset_id"] not in {d["id"] for d in config["datasets"]}:
            raise ValueError("Run references an unregistered dataset")
        for key in ("query", "review"):
            if entry.get(key) is not None:
                if PurePosixPath(entry[key]["path"]).parts[0] != "experiments":
                    raise ValueError("Run must be registered under experiments/")
                _path(root, entry[key]["path"])
    return config


def _select(config, kind, identity):
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError("Explicit valid " + kind + " selection required")
    matches = [entry for entry in config[kind] if entry["id"] == identity]
    if len(matches) != 1:
        raise ValueError("Unknown " + kind + " selection")
    return matches[0]


def _dataset_manifest(root, entry):
    folder = _path(root, entry["path"])
    manifest = _manifest(folder, entry["manifest_sha256"])
    company = manifest["company"]
    if (not all(company.get(k) for k in ("company_id", "name", "symbol"))
            or company["company_id"] != entry["company_id"]
            or company["symbol"] != entry["symbol"]
            or manifest["snapshot_id"] != entry["snapshot_id"]):
        raise ValueError("Dataset company or snapshot registration mismatch")
    if manifest.get("materialization", {}).get("company", company) != company:
        raise ValueError("Materialization company mismatch")
    return folder, manifest


@_public
def load_catalog(root):
    """Return registered choices only; there is deliberately no default choice."""
    config = _registration(root)
    datasets = []
    for entry in config["datasets"]:
        _, manifest = _dataset_manifest(root, entry)
        company = manifest["company"]
        datasets.append({"id": entry["id"], "company_id": company["company_id"],
            "company_name": company["name"], "symbol": company["symbol"],
            **{k: manifest[k] for k in ("snapshot_id", "status", "source_count", "record_count")},
            "manifest_sha256": entry["manifest_sha256"]})
    return {"datasets": datasets, "runs": [{k: r[k] for k in ("id", "label", "dataset_id")}
                                           for r in config["runs"]]}


def _unique(rows, key):
    values = {row[key]: row for row in rows}
    if len(values) != len(rows):
        raise ValueError("Duplicate artifact identity: " + key)
    return values


def _database(folder, records, sources, evidence, metrics):
    connection = duckdb.connect(str(_path(folder, "research.duckdb")), read_only=True, config={
        "enable_external_access": "false", "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false", "threads": "1", "memory_limit": "128MB"})
    try:
        # Table names are adapter constants; callers cannot supply SQL.
        for table, key, expected in (("observations", "record_id", records),
                ("sources", "source_snapshot_id", sources), ("evidence", "evidence_id", evidence),
                ("metric_definitions", "metric_id", metrics)):
            rows = connection.execute(f"SELECT {key}, payload FROM {table}").fetchall()
            actual = {identity: json.loads(payload) for identity, payload in rows}
            if len(actual) != len(rows) or actual != expected:
                raise ValueError("DuckDB payload differs from frozen JSON: " + table)
        for identity, entity, sid in connection.execute(
                "SELECT record_id, entity_id, source_snapshot_id FROM observations").fetchall():
            if records[identity]["entity_id"] != entity or records[identity]["source_snapshot_id"] != sid:
                raise ValueError("DuckDB observation identity mismatch")
        for sid, company in connection.execute("SELECT source_snapshot_id, company_id FROM sources").fetchall():
            if sources[sid]["company_id"] != company:
                raise ValueError("DuckDB source company mismatch")
        rows = connection.execute("SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'main' "
            "ORDER BY table_name, ordinal_position").fetchall()
        return [dict(zip(("table_name", "column_name", "data_type", "is_nullable"), row)) for row in rows]
    finally:
        connection.close()


@_public
def load_dataset(root, dataset_id):
    entry = _select(_registration(root), "datasets", dataset_id)
    folder, manifest = _dataset_manifest(root, entry)
    sources = _read(folder, manifest, "sources.json")
    records = _read(folder, manifest, "records.json")["rows"]
    evidence = _read(folder, manifest, "evidence.json")
    metrics = _read(folder, manifest, "metrics.json")
    by_source = _unique(sources, "source_snapshot_id")
    by_record = _unique(records, "record_id")
    company = manifest["company"]
    if any(gap.get("source_snapshot_id") is not None and gap["source_snapshot_id"] not in by_source
           for gap in manifest["gaps"]):
        raise ValueError("Processing gap refers to a source outside selected dataset")
    blocks, indexes, assets, raw_sizes, block_maps = {}, {}, {}, {}, {}
    if (len(sources), len(records), len(evidence)) != (
            manifest["source_count"], manifest["record_count"], manifest["evidence_count"]):
        raise ValueError("Dataset counts differ from manifest")
    for sid, source in by_source.items():
        if source["company_id"] != company["company_id"]:
            raise ValueError("Source belongs to another company")
        raw = source["raw_file"]
        if (manifest["files"].get(raw) != source["raw_file_sha256"]
                or source["raw_file_sha256"] != source["source_sha256"]):
            raise ValueError("Source/raw hash association mismatch or unsupported compressed source")
        raw_sizes[sid] = _path(folder, raw).stat().st_size
        prefix = source["index_folder"] + "/"
        index_manifest = _read(folder, manifest, prefix + "manifest.json")
        index = _read(folder, manifest, prefix + "index.json")
        if (index_manifest["source_snapshot_id"] != sid or index["source_snapshot_id"] != sid
                or index_manifest["source_sha256"] != source["source_sha256"]
                or index["index_id"] != source["index_id"] or index["form_type"] != source["form"]):
            raise ValueError("Source/index association mismatch")
        for name in ("blocks.jsonl", "index.json", "assets.json"):
            if manifest["files"].get(prefix + name) != index_manifest["artifacts"][name]["sha256"]:
                raise ValueError("Index artifact hash association mismatch")
        parsed = [json.loads(line) for line in _path(folder, prefix + "blocks.jsonl").read_text().splitlines()]
        block_maps[sid] = _unique(parsed, "block_id")
        for block in parsed:
            if digest(block["text"].encode()) != block["text_hash"]:
                raise ValueError("Block text hash mismatch")
        for node in index["nodes"]:
            if any(node[k] not in block_maps[sid] for k in ("start_block_id", "end_block_id")):
                raise ValueError("Index node references a missing source block")
        blocks[sid], indexes[sid] = parsed, index
        assets[sid] = _read(folder, manifest, prefix + "assets.json")
    for eid, item in evidence.items():
        sid = item["source_snapshot_id"]
        if sid not in by_source or item["evidence_id"] != eid:
            raise ValueError("Foreign or mismatched evidence identity")
        source, block = by_source[sid], block_maps[sid].get(item["block_id"])
        if (block is None or item["source_sha256"] != source["source_sha256"]
                or item["index_id"] != source["index_id"] or item["text_hash"] != block["text_hash"]
                or item["quote"] not in block["text"]
                or any(b not in block_maps[sid] for b in item.get("context_block_ids", []))):
            raise ValueError("Evidence does not match its selected original source")
    for row in records:
        sid, entity = row["source_snapshot_id"], row["entity_id"]
        expected_entity = company["company_id"]
        if row["dimensions"]:
            expected_entity += "-dimensions-" + digest(row["dimensions"])[:16]
        if sid not in by_source or entity != expected_entity or row["metric_id"] not in metrics:
            raise ValueError("Record company, source, entity adapter or metric mismatch")
        for key in ("evidence_ids", "qualifier_evidence_ids", "question_evidence_ids"):
            for eid in row[key]:
                if eid not in evidence or evidence[eid]["source_snapshot_id"] != sid:
                    raise ValueError("Record has foreign evidence")
    columns = _database(folder, by_record, by_source, evidence, metrics)
    return {"id": dataset_id, "company": company, "manifest_sha256": entry["manifest_sha256"],
        "storage": {"dataset_path": entry["path"], "records_path": entry["path"] + "/records.json",
                    "database_path": entry["path"] + "/research.duckdb"},
        **{k: manifest[k] for k in ("snapshot_id", "source_policy_id", "status", "gaps", "limits")},
        "sources": sources, "records": records, "evidence": evidence, "metrics": metrics,
        "columns": columns, "blocks": blocks, "indexes": indexes, "assets": assets, "raw_sizes": raw_sizes}


@_public
def load_raw_source(root, dataset_id, source_id):
    """Return verified source bytes only for a source in the selected dataset."""
    dataset = load_dataset(root, dataset_id)
    matches = [source for source in dataset["sources"] if source["source_snapshot_id"] == source_id]
    if len(matches) != 1:
        raise ValueError("Unknown source in selected dataset")
    source = matches[0]
    entry = _select(_registration(root), "datasets", dataset_id)
    content = _path(_path(root, entry["path"]), source["raw_file"]).read_bytes()
    if digest(content) != source["raw_file_sha256"]:
        raise ValueError("Source bytes changed during read")
    return {"content": content, "mime_type": source["parsed_mime_type"], "sha256": source["raw_file_sha256"]}


def _scope(value, dataset):
    scope = ExecutionScope.model_validate(value).model_dump(mode="json")
    sources = {s["source_snapshot_id"]: s for s in dataset["sources"]}
    if (scope["snapshot_id"] != dataset["snapshot_id"]
            or scope["company_ids"] != [dataset["company"]["company_id"]]
            or scope["source_policy_id"] != dataset["source_policy_id"]
            or not set(scope["source_snapshot_ids"]) <= sources.keys()
            or any(sources[s]["available_at"] > scope["knowledge_cutoff"] for s in scope["source_snapshot_ids"])):
        raise ValueError("Run scope is outside selected dataset")
    return scope


def _bound_reference(reference, registration):
    # Historical absolute paths are metadata only. Never follow them. A relocated
    # checkout resolves the explicit registration relative to its own root.
    parts = PurePosixPath(reference["path"]).parts
    expected = PurePosixPath(registration["path"]).parts
    if (parts[-len(expected):] != expected
            or reference["manifest_sha256"] != registration["manifest_sha256"]):
        raise ValueError("Historical reference differs from registered artifact")


def _citation(citation, dataset, scope):
    sid = citation["source_snapshot_id"]
    if sid not in scope["source_snapshot_ids"]:
        raise ValueError("Citation source is outside run scope")
    source = next(s for s in dataset["sources"] if s["source_snapshot_id"] == sid)
    matches = [b for b in dataset["blocks"][sid] if b["block_id"] == citation["block_id"]]
    if len(matches) != 1 or not citation["quote"] or citation["quote"] not in matches[0]["text"]:
        raise ValueError("Citation quote does not match original source")
    for key in ("index_id", "source_sha256", "source_url"):
        if key in citation and citation[key] != source[key]:
            raise ValueError("Citation source metadata mismatch")
    if "original_block" in citation:
        if any(matches[0].get(k) != v for k, v in citation["original_block"].items()):
            raise ValueError("Citation original block differs from dataset")


def _steps(folder, manifest, result):
    steps = []
    for event in result["trace"]:
        number = event["step"]
        if type(number) is not int or number < 1:
            raise ValueError("Invalid trace step")
        prefix = f"turn-{number:03d}/"
        decision = _read(folder, manifest, prefix + "decision.json")
        feedback = _read(folder, manifest, prefix + "feedback.json")
        receipt = _read(folder, manifest, prefix + "receipt.json")
        if decision["action"] != event["action"] or receipt["step"] != number or receipt["action"] != event["action"]:
            raise ValueError("Trace/decision/receipt mismatch")
        # Only task decisions and public tool feedback; no provider requests,
        # raw responses, hidden reasoning, prompts or credential configuration.
        safe_feedback = {k: feedback[k] for k in ("status", "reason", "error_type", "evidence_ids", "plan",
            "model_claimed_coverage", "semantic_completeness", "preview_truncated", "receipt") if k in feedback}
        steps.append({"step": number, "action": event["action"], "status": event["status"],
            "decision": decision, "result": feedback.get("result"), "feedback": safe_feedback})
    return steps


@_public
def load_run(root, run_id):
    config = _registration(root)
    entry = _select(config, "runs", run_id)
    dataset_entry = _select(config, "datasets", entry["dataset_id"])
    dataset = load_dataset(root, entry["dataset_id"])
    query = entry["query"]
    folder = _path(root, query["path"])
    manifest = _manifest(folder, query["manifest_sha256"])
    result = _read(folder, manifest, "result.json")
    request = _read(folder, manifest, "request.json")
    scope = _scope(result["active_scope"], dataset)
    if result["request"] != request or request["scope"] != scope:
        raise ValueError("Query request/result scope mismatch")
    bundle = _read(folder, manifest, "evidence-bundle.json")
    if (bundle["schema_version"] != "autonomous-evidence-manifest-v2"
            or bundle["bundle_id"] != result["evidence_bundle"]["bundle_id"]
            or bundle["bundle_id"] != "bundle-" + digest({k: v for k, v in bundle.items() if k != "bundle_id"})[:24]):
        raise ValueError("Query evidence bundle mismatch")
    items = _unique(bundle["items"], "evidence_id")
    dataset_records = {r["record_id"]: r for r in dataset["records"]}
    for item in items.values():
        if item["scope"] != scope or item["artifact"]["scope"] != scope:
            raise ValueError("Evidence bundle contains a foreign scope")
        ref = item["artifact"]
        if manifest["files"].get(ref["path"]) != ref["sha256"]:
            raise ValueError("Evidence artifact reference mismatch")
        item["value"] = _read(folder, manifest, ref["path"])
        identity_hash = digest({k: item[k] for k in ("kind", "value", "scope")})
        if item["sha256"] != identity_hash or item["evidence_id"] != "ev-" + identity_hash[:24]:
            raise ValueError("Evidence item identity hash mismatch")
        value = item["value"]
        if "source_snapshot_id" in value and value["source_snapshot_id"] not in scope["source_snapshot_ids"]:
            raise ValueError("Evidence item references a source outside run scope")
        if item["kind"] == "record" and dataset_records.get(value["record_id"]) != value:
            raise ValueError("Query record differs from selected dataset")
        if item["kind"] == "citation":
            _citation(value, dataset, scope)
    for requirement in result["coverage"]:
        if not set(requirement["evidence_ids"]) <= items.keys():
            raise ValueError("Requirement has missing evidence references")
        for key in ("query_scope", "source_scope"):
            if requirement.get(key) is not None and requirement[key] != scope:
                raise ValueError("Requirement contains a foreign scope")
    facts, assessment, review_result = [], None, None
    limitations = list(entry["limitations"])
    if entry.get("review") is not None:
        review = entry["review"]
        review_folder = _path(root, review["path"])
        review_manifest = _manifest(review_folder, review["manifest_sha256"])
        packet = _read(review_folder, review_manifest, "input.json")
        review_result = _read(review_folder, review_manifest, "result.json")
        _bound_reference(packet["query_ref"], query)
        _bound_reference(packet["dataset_ref"], dataset_entry)
        if (packet["scope"] != scope or review_result["scope"] != scope or packet["question"] != request["question"]
                or packet["requirements"] != result["coverage"] or packet["query_status"] != result["status"]
                or packet["query_gaps"] != result["gaps"]
                or review_result["input_sha256"] != digest(packet) or review_result["packet_id"] != packet["packet_id"]):
            raise ValueError("Review packet is not bound to the selected query")
        if packet["packet_id"] != "data-review-" + digest({k: v for k, v in packet.items() if k != "packet_id"})[:24]:
            raise ValueError("Review packet identity mismatch")
        documents = _unique(packet["source_documents"], "source_snapshot_id")
        if documents.keys() != set(scope["source_snapshot_ids"]):
            raise ValueError("Review originals do not cover selected sources")
        for sid, document in documents.items():
            source = next(s for s in dataset["sources"] if s["source_snapshot_id"] == sid)
            if any(document[k] != source[k] for k in ("company_id", "source_sha256", "index_id")):
                raise ValueError("Review original source identity mismatch")
            expected_blocks = [{k: b[k] for k in ("block_id", "type", "text", "table", "reported_page") if k in b}
                               for b in dataset["blocks"][sid]]
            if document["blocks"] != expected_blocks:
                raise ValueError("Review original blocks differ from selected dataset")
        facts = packet["facts"]
        _unique(facts, "fact_id")
        records = {r["record_id"]: r for r in dataset["records"]}
        requirements = {r["requirement_id"]: r for r in result["coverage"]}
        for fact in facts:
            if not fact["requirement_ids"] or not set(fact["requirement_ids"]) <= requirements.keys():
                raise ValueError("Review fact references a foreign requirement")
            if fact["kind"] == "record":
                value = fact["value"]
                item = items.get(fact["fact_id"])
                if (item is None or item["kind"] != "record" or item["value"] != value
                        or records.get(value["record_id"]) != value
                        or value["source_snapshot_id"] not in scope["source_snapshot_ids"]):
                    raise ValueError("Reviewed record differs from query or selected dataset")
            elif fact["kind"] == "source_claim":
                item = items.get(fact["answer_id"])
                if item is None or item["kind"] != "candidate_source_answer" or digest(item["value"]) != fact["answer_sha256"]:
                    raise ValueError("Reviewed claim answer binding mismatch")
                number = int(fact["fact_id"].removeprefix(fact["answer_id"] + ":claim:"))
                if item["value"]["claims"][number] != fact["value"]:
                    raise ValueError("Reviewed claim differs from frozen answer")
            else:
                raise ValueError("Unsupported review fact kind")
            for citation in fact["citations"]:
                _citation(citation, dataset, scope)
        if "response.json" in review_manifest["files"]:
            response = _read(review_folder, review_manifest, "response.json")
            assessment, eligible = validate_assessment(packet, response)
            if (review_result["assessment"] != assessment or review_result["analysis_eligible"] != eligible
                    or (review_result["status"] == "reviewed" and (not eligible or review_result["failures"]))):
                raise ValueError("Review result disagrees with validated assessment")
            limitations.extend(assessment["limitations"])
        elif review_result["assessment"] is not None or review_result["analysis_eligible"]:
            raise ValueError("Review result has no saved assessment response")
        review_result = {k: v for k, v in review_result.items() if k != "usage"}
    return {"id": run_id, "label": entry["label"], "dataset_id": entry["dataset_id"],
        "question": request["question"], "scope": scope, "result": result, "facts": facts,
        "assessment": assessment, "review_result": review_result,
        "steps": _steps(folder, manifest, result), "limitations": limitations}
