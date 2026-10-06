"""Build an immutable DuckDB projection from the explicitly scoped experiment."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
import tempfile

import duckdb

from uteki.agents.reading.document_reader import DocumentReader
from uteki.domain.research_data.query_contract import (
    DataQuery, ResearchRecord, QueryResult, VERSION, SOURCE_PERIOD_VERSION, export_query_schema, validate_period_version,
)
from .financial_records import digest
from .adapters.alphabet_query import from_financial, from_prompt, metric_catalog
from .query_inputs import DatasetBuildSpec

DDL = """
CREATE TABLE observations (
    record_id VARCHAR PRIMARY KEY, entity_id VARCHAR NOT NULL, metric_id VARCHAR NOT NULL,
    period_kind VARCHAR, period_start DATE, period_end DATE, value_kind VARCHAR NOT NULL,
    value_decimal DECIMAL(38,12), upper_decimal DECIMAL(38,12), value_relation VARCHAR NOT NULL,
    unit VARCHAR, accounting_basis VARCHAR NOT NULL, available_at DATE NOT NULL,
    source_snapshot_id VARCHAR NOT NULL, status VARCHAR NOT NULL, payload JSON NOT NULL
);
CREATE TABLE sources (source_snapshot_id VARCHAR PRIMARY KEY, company_id VARCHAR, form VARCHAR,
    period_end DATE, available_at DATE, payload JSON);
CREATE TABLE evidence (evidence_id VARCHAR PRIMARY KEY, source_snapshot_id VARCHAR, payload JSON);
CREATE TABLE metric_definitions (metric_id VARCHAR PRIMARY KEY, payload JSON);
"""


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load(path):
    return json.loads(path.read_text())


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path outside dataset root")
    return path


def build_dataset(repo: Path, destination: Path, *, spec: Path):
    repo, destination = repo.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError("dataset exists; never overwrite an immutable snapshot")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".query-build-", dir=destination.parent) as temp:
        work = Path(temp) / "dataset"
        work.mkdir()
        input_hashes, sources, readers = {}, [], {}

        def verified_input(relative, expected=None):
            path = contained(repo, relative)
            data = path.read_bytes()
            actual = digest(data)
            if expected and actual != expected:
                raise ValueError("frozen input hash mismatch: " + relative)
            input_hashes[relative] = actual
            return data

        spec_path = contained(repo, spec)
        config = DatasetBuildSpec.model_validate_json(verified_input(str(spec_path.relative_to(repo))))
        dataset_version = (SOURCE_PERIOD_VERSION if any(entry.adapter == "us-gaap-inline-v1" for entry in config.inputs)
                           else VERSION)
        inventory = json.loads(verified_input(config.source_inventory.path, config.source_inventory.sha256))
        bindings = {s.source_snapshot_id: s for s in config.sources}
        inventory_ids = [s["source_snapshot_id"] for s in inventory["sources"]]
        if len(set(inventory_ids)) != len(inventory_ids) or not bindings.keys() <= set(inventory_ids):
            raise ValueError("missing or ambiguous source inventory binding")
        for item in inventory["sources"]:
            if item["source_snapshot_id"] not in bindings:
                continue
            binding = bindings[item["source_snapshot_id"]]
            if not item["eligible_for_new_comparison"] or binding.content_sha256 != item["declared_content_sha256"]:
                raise ValueError("source is ineligible or differs from explicit binding")
            source_manifest = json.loads(verified_input(item["source_manifest"]["path"], item["source_manifest"]["sha256"]))
            if (source_manifest["source_snapshot_id"] != binding.source_snapshot_id
                    or source_manifest.get("company_id", binding.company_id) != binding.company_id
                    or source_manifest["document_id"] != item["document_id"]):
                raise ValueError("source manifest identity mismatch")
            if (source_manifest["content_sha256"] != binding.content_sha256
                    or source_manifest.get("published_at", source_manifest.get("filed_at")) != item["published_or_filed_at"]):
                raise ValueError("source hash or availability metadata mismatch")
            raw = verified_input(item["raw_file"]["path"], item["raw_file"]["sha256"])
            content = gzip.decompress(raw) if item["raw_file"]["path"].endswith(".gz") else raw
            if digest(content) != item["declared_content_sha256"]:
                raise ValueError("source bytes mismatch")
            sid = item["source_snapshot_id"]
            folder = contained(work, "sources/" + sid)
            folder.mkdir(parents=True)
            for file in item["index_files"]:
                data = verified_input(file["path"], file["sha256"])
                (folder / Path(file["path"]).name).write_bytes(data)
            raw_name = Path(item["raw_file"]["path"]).name
            (folder / raw_name).write_bytes(raw)
            reader = DocumentReader(folder)
            if (reader.manifest["source_sha256"] != digest(content)
                    or source_manifest["form"] != reader.index["form_type"]
                    or source_manifest["period_end"] != item["period_end"]):
                raise ValueError("source/index mismatch")
            source = {"source_snapshot_id": sid, "source_sha256": digest(content), "document_id": item["document_id"],
                      "index_id": reader.index["index_id"], "source_url": item["source_url"], "company_id": binding.company_id,
                      "form": reader.index["form_type"], "period_end": item["period_end"],
                      "available_at": item["published_or_filed_at"], "status": "candidate",
                      "available_at_precision": "date", "publication_note": source_manifest.get("publication_note"),
                      "index_folder": str(folder.relative_to(work)), "raw_file": str((folder / raw_name).relative_to(work)),
                      "raw_file_sha256": digest(raw), "capabilities": ["literal_search", "read_context", "source_bytes"],
                      "block_count": len(reader.blocks), "image_block_count": sum(b.get("type") == "image" for b in reader.blocks)}
            sources.append(source)
            readers[sid] = reader
        catalog = metric_catalog()
        if any(entry.adapter == "us-gaap-inline-v1" for entry in config.inputs):
            from .company_materialization import metric_catalog as generic_metric_catalog
            catalog.update(generic_metric_catalog())
        records, evidence, normalization_gaps = [], {}, []
        by_source = {s["source_snapshot_id"]: s for s in sources}
        for entry in config.inputs:
            relative = entry.path
            input_bytes = verified_input(relative, entry.sha256)
            data = None if entry.adapter == "us-gaap-inline-v1" else json.loads(input_bytes)
            source, binding = by_source[entry.source_snapshot_id], bindings[entry.source_snapshot_id]
            blocks = {b["block_id"]: b for b in readers[entry.source_snapshot_id].blocks}
            if entry.adapter == "alphabet-financial-v1":
                if source["form"] not in ("10-K", "10-Q") or data["source_snapshot_id"] != entry.source_snapshot_id:
                    raise ValueError("financial adapter source mismatch")
                batches = [([from_financial(row, relative, company_id=binding.company_id)], data["evidence"]) for row in data["records"]]
            elif entry.adapter == "us-gaap-inline-v1":
                from .company_materialization import extract_inline_records
                if digest(input_bytes) != source["source_sha256"] or not re.fullmatch(r"sec-\d+", binding.company_id):
                    raise ValueError("generic inline adapter requires original HTML bytes and explicit SEC issuer")
                reader = readers[entry.source_snapshot_id]
                rows, refs, diagnostics, fiscal = extract_inline_records(input_bytes,
                    {"source_id": entry.source_snapshot_id, "source_url": source["source_url"],
                     "filed_at": source["available_at"], "period_end": source["period_end"], "mime_type": "text/html"},
                    {"company_id": binding.company_id, "cik": binding.company_id[4:]}, reader.index, reader.blocks, relative)
                source["fiscal_periods"] = fiscal
                normalization_gaps.extend(diagnostics)
                batches = [([ResearchRecord.model_validate(row) for row in rows], refs)]
            else:
                if source["form"] != "EARNINGS_CALL":
                    raise ValueError("call adapter requires an earnings call")
                batches = [from_prompt(row, artifact=relative, ordinal=i, source=source, blocks=blocks)
                           for i, row in enumerate(data["records"])]
            for normalized, refs in batches:
                if any(r.source_snapshot_id != entry.source_snapshot_id or r.entity_id not in binding.entity_ids for r in normalized):
                    raise ValueError("record outside explicit source/entity binding")
                records.extend(normalized)
                for eid, ev in refs.items():
                    if eid in evidence and evidence[eid] != ev:
                        raise ValueError("evidence ID collision")
                    evidence[eid] = ev
        for ev in evidence.values():
            reader = readers[ev["source_snapshot_id"]]
            block = reader.blocks[reader.positions[ev["block_id"]]]
            if (ev["text_hash"] != block["text_hash"] or ev["quote"] not in block["text"]
                    or ev["source_sha256"] != reader.manifest["source_sha256"] or ev["index_id"] != reader.index["index_id"]):
                raise ValueError("invalid evidence/source binding")
        for record in records:
            validate_period_version(record.period, dataset_version)
            if str(record.available_at) != by_source[record.source_snapshot_id]["available_at"]:
                raise ValueError("record availability differs from its bound source")
            if any(eid not in evidence or evidence[eid]["source_snapshot_id"] != record.source_snapshot_id
                   for eid in record.evidence_ids + record.qualifier_evidence_ids + record.question_evidence_ids):
                raise ValueError("record evidence is unbound")
        rows = [ResearchRecord.model_validate({**r.model_dump(mode="json"), "schema_version": dataset_version})
                .model_dump(mode="json") for r in records]
        normalization = {"adapter_version": dataset_version, "rows": rows}
        save(work / "records.json", normalization)
        save(work / "evidence.json", evidence)
        save(work / "sources.json", sources)
        save(work / "metrics.json", catalog)
        save(work / "schemas/record.schema.json", export_query_schema(ResearchRecord, version=dataset_version))
        save(work / "schemas/query.schema.json", export_query_schema(DataQuery, version=dataset_version))
        save(work / "schemas/result.schema.json", export_query_schema(QueryResult, version=dataset_version))
        (work / "schema.sql").write_text(DDL)
        code_files = [Path(__file__), Path(__file__).with_name("query_inputs.py"),
                      Path(__file__).parent / "adapters/alphabet_query.py",
                      Path(__file__).parent / "adapters/alphabet_financial.py",
                      Path(__file__).with_name("financial_records.py"),
                      repo / "src/uteki/agents/reading/document_reader.py", repo / "src/uteki/agents/reading/reading_groups.py",
                      repo / "src/uteki/domain/research_data/query_contract.py"]
        if any(entry.adapter == "us-gaap-inline-v1" for entry in config.inputs):
            code_files.append(Path(__file__).with_name("company_materialization.py"))
        # Module paths can retain a repository symlink (for example /tmp on
        # macOS); use the same physical root as repo for stable adapter identity.
        code_files = [path.resolve() for path in code_files]
        code_hashes = {str(p.relative_to(repo)): digest(p.read_bytes()) for p in code_files}
        identity = {"schema_version": dataset_version, "input_hashes": input_hashes, "adapter_hashes": code_hashes,
                    "records_sha256": digest(rows), "metric_definitions_sha256": digest(catalog)}
        snapshot_id = "query-" + digest(identity)[:24]
        db = duckdb.connect(str(work / "research.duckdb"))
        try:
            db.execute(DDL)
            for r in rows:
                p = r["period"] or {}
                db.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           [r["record_id"], r["entity_id"], r["metric_id"], p.get("kind"), p.get("start"), p.get("end"),
                            r["value_kind"], r["value_decimal"], r["upper_decimal"], r["value_relation"], r["unit"],
                            r["accounting_basis"], r["available_at"], r["source_snapshot_id"], r["status"], json.dumps(r)])
            for s in sources:
                db.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)", [s["source_snapshot_id"], s["company_id"],
                           s["form"], s["period_end"], s["available_at"], json.dumps(s)])
            for eid, ev in evidence.items():
                db.execute("INSERT INTO evidence VALUES (?, ?, ?)", [eid, ev["source_snapshot_id"], json.dumps(ev)])
            for key, metric in catalog.items():
                db.execute("INSERT INTO metric_definitions VALUES (?, ?)", [key, json.dumps(metric)])
            db.execute("CHECKPOINT")
        finally:
            db.close()
        files = {str(f.relative_to(work)): digest(f.read_bytes()) for f in sorted(work.rglob("*")) if f.is_file()}
        result = {**identity, "snapshot_id": snapshot_id, "source_policy_id": "local-frozen-v1", "status": "candidate",
                  "database_engine": "duckdb", "database_version": duckdb.__version__, "files": files,
                  "record_count": len(rows), "source_count": len(sources), "evidence_count": len(evidence),
                  "model_calls": 0, "normalization_gaps": normalization_gaps, "excluded_sources": [s["source_snapshot_id"] for s in inventory["sources"] if not s["eligible_for_new_comparison"]],
                  "build_spec": config.model_dump(mode="json"),
                  "limits": ["Explicitly selected sources and adapters; not a full company database", "Date-level cutoff; not intraday point-in-time",
                             "Semantic records from adapted repeat 1 only; not independently approved", "No OCR/web/model planner or automatic adoption"]}
        save(work / "manifest.json", result)
        work.rename(destination)
        return result
