"""Bounded query-plan compiler, SQL reader, evidence reader and Decimal formulas.

The caller supplies a resolved plan using discover_data/get_schema. Free-form
questions are trace context, never silently interpreted as executable SQL.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import json
from pathlib import Path
import threading

import duckdb

from uteki.agents.reading.document_reader import DocumentReader
from uteki.domain.research_data.query_contract import (
    DataQuery, RecordRequest, ResearchRecord, QueryResult, VERSION, SUPPORTED_VERSIONS, validate_period_version,
)
from uteki.domain.research_data.execution_scope import (
    EXECUTION_VERSION, ExecutionScope, ReadCursor, SearchCursor,
    SourceOutlineRequest, SourceReadRequest, SourceSearchRequest,
)
from uteki.domain.research_data.evidence_package import EvidencePackage
from uteki.domain.research_data.task_plan import TaskPlan, TaskStep, ProgressSnapshot
from uteki.domain.research_data.task_completion import CompletionAssessment
from .financial_records import digest
from .query_dataset import contained, load

MAX_DOCUMENT_BYTES = 80000


def compact_table_cells(result):
    """Lossless wire projection: factor repeated cell keys out of large tables.

    All cells, empty cells, text, row/column positions and spans are retained.
    Heterogeneous cell schemas retain their original representation. The frozen
    index and reader cache are never mutated.
    """
    blocks = []
    for block in result["blocks"]:
        table = block.get("table")
        cells = table.get("cells") if isinstance(table, dict) else None
        if cells and all(isinstance(cell, dict) and cell.keys() == cells[0].keys() for cell in cells):
            fields = list(cells[0])
            table = {**table, "cell_fields": fields,
                     "cells": [[cell[field] for field in fields] for cell in cells]}
            block = {**block, "table": table}
        blocks.append(block)
    return {**result, "blocks": blocks, "representation": "compact",
            "table_encoding": "Each table.cells tuple maps positionally to table.cell_fields; all cells including empty cells are retained."}


class QueryDataPort:
    def __init__(self, dataset: Path):
        self.dataset = dataset.resolve()
        self.manifest = load(self.dataset / "manifest.json")
        if self.manifest["schema_version"] not in SUPPORTED_VERSIONS:
            raise ValueError(f"unsupported dataset schema version: {self.manifest['schema_version']}; "
                             f"expected {' or '.join(SUPPORTED_VERSIONS)}. Build a new dataset; preserve the historical snapshot.")
        for relative, expected in self.manifest["files"].items():
            if digest(contained(self.dataset, relative).read_bytes()) != expected:
                raise ValueError("dataset integrity failure: " + relative)
        self.sources = load(self.dataset / "sources.json")
        self.metrics = load(self.dataset / "metrics.json")
        self._readers = {}
        self._db = duckdb.connect(str(self.dataset / "research.duckdb"), read_only=True, config={
            "enable_external_access": "false", "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false", "threads": "1", "memory_limit": "128MB",
        })
        try:
            entities = {s["company_id"]: {"entity_id": s["company_id"], "company_id": s["company_id"],
                                         "accounting_bases": set()} for s in self.sources}
            for entity, company, basis in self._db.execute(
                    "SELECT DISTINCT o.entity_id, s.company_id, o.accounting_basis "
                    "FROM observations o JOIN sources s USING (source_snapshot_id)").fetchall():
                if entity in entities and entities[entity]["company_id"] != company:
                    raise ValueError("entity belongs to multiple companies; use qualified entity IDs")
                entry = entities.setdefault(entity, {"entity_id": entity, "company_id": company, "accounting_bases": set()})
                entry["accounting_bases"].add(basis)
            self.entities = {key: {**value, "accounting_bases": sorted(value["accounting_bases"])}
                             for key, value in sorted(entities.items())}
            for entity, payload in self._db.execute("SELECT entity_id, payload FROM observations").fetchall():
                dimensions = json.loads(payload).get("dimensions", {})
                if dimensions:
                    entry = self.entities[entity].setdefault("reported_dimensions", [])
                    if dimensions not in entry:
                        entry.append(dimensions)
        except Exception:
            self._db.close()
            raise

    def close(self):
        self._db.close()

    def scoped(self, scope):
        """Borrow this read-only connection with an explicit, immutable scope."""
        return ScopedQueryDataPort(self, scope)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def snapshot_id(self):
        return self.manifest["snapshot_id"]

    def _sql(self, sql, parameters, trace):
        # Only source-controlled SQL reaches this method. Each connection is used serially.
        timer = threading.Timer(10, self._db.interrupt)
        timer.daemon = True
        timer.start()
        try:
            rows = self._db.execute(sql, parameters).fetchall()
        finally:
            timer.cancel()
            timer.join()
        trace.append({"tool": "sql", "sql": sql, "parameters": [str(x) if isinstance(x, date) else x for x in parameters],
                      "returned_rows": len(rows), "snapshot_id": self.snapshot_id})
        return rows

    def get_schema(self, metric_ids=()):
        unknown = set(metric_ids) - self.metrics.keys()
        if unknown:
            raise ValueError("unknown metric IDs: " + ", ".join(sorted(unknown)))
        return {"snapshot_id": self.snapshot_id, "schema_version": self.manifest["schema_version"], "query": load(self.dataset / "schemas/query.schema.json"),
                "record": load(self.dataset / "schemas/record.schema.json"), "result": load(self.dataset / "schemas/result.schema.json"),
                "metrics": {k:v for k,v in self.metrics.items() if not metric_ids or k in metric_ids},
                "entities": list(self.entities.values()),
                "fiscal_periods": [{**p, "company_id": s["company_id"], "source_snapshot_id": s["source_snapshot_id"]}
                                   for s in self.sources for p in s.get("fiscal_periods", [])],
                "physical_tables": {name: [{"name": row[1], "type": row[2], "not_null": row[3], "primary_key": row[5]}
                    for row in self._db.execute(f"PRAGMA table_info('{name}')").fetchall()]
                    for name in ("observations", "sources", "evidence", "metric_definitions")},
                "capabilities": ["compiled_parameterized_select", "decimal_calculations", "literal_document_search", "read_complete_context"],
                "unsupported": ["free_form_NL_planner", "arbitrary_SQL", "OCR", "web_search", "automatic_acquisition"],
                "notes": ["All rows are candidates; include_candidates must be explicitly true.",
                          "period=null requests records with no typed period; period_resolution distinguishes unresolved/not_applicable. It is not a wildcard.",
                          "question is context; only the typed plan is executed.",
                          "No implicit SUM or joins that multiply disclosure occurrences."]}

    def discover_data(self, *, knowledge_cutoff: str, include_candidates=False):
        cutoff = date.fromisoformat(knowledge_cutoff)
        visible = [s for s in self.sources if date.fromisoformat(s["available_at"]) <= cutoff]
        rows = self._db.execute("SELECT entity_id, metric_id, period_kind, period_start, period_end, value_kind, count(*) "
                                "FROM observations WHERE available_at <= ? GROUP BY ALL ORDER BY entity_id, metric_id, period_end", [cutoff]).fetchall()
        return {"snapshot_id": self.snapshot_id, "source_policy_id": self.manifest["source_policy_id"],
                "status": "candidate", "knowledge_cutoff": knowledge_cutoff,
                "sources": [{**s, "queryable": include_candidates} for s in visible],
                "coverage": [{"entity_id": r[0], "metric_id": r[1], "period_kind": r[2],
                              "period_start": str(r[3]) if r[3] else None, "period_end": str(r[4]) if r[4] else None,
                              "value_kind": r[5], "occurrence_count": r[6],
                              "status": "available_candidate" if include_candidates else "quality_filtered"} for r in rows],
                "limits": self.manifest["limits"], "not_disclosed_inference": "never inferred from a missing row"}

    def _reader(self, source):
        sid = source["source_snapshot_id"]
        if sid not in self._readers:
            self._readers[sid] = DocumentReader(contained(self.dataset, source["index_folder"]))
        return self._readers[sid]

    @staticmethod
    def _document_node(reader):
        roots = [n["node_id"] for n in reader.index["nodes"] if n["kind"] == "document"]
        if len(roots) != 1:
            raise ValueError("source index must declare exactly one document node")
        return roots[0]

    def get_evidence(self, evidence_ids, *, snapshot_id, knowledge_cutoff, include_candidates=False):
        if snapshot_id != self.snapshot_id:
            raise ValueError("snapshot mismatch")
        if not include_candidates:
            raise PermissionError("candidate evidence requires explicit candidate access")
        if not 1 <= len(evidence_ids) <= 256:
            raise ValueError("evidence request must contain 1..256 IDs")
        cutoff = date.fromisoformat(knowledge_cutoff)
        found = {}
        for eid in dict.fromkeys(evidence_ids):
            clause, args = self._source_restriction("s.")
            row = self._db.execute("SELECT e.payload FROM evidence e JOIN sources s USING(source_snapshot_id) "
                                   "WHERE e.evidence_id = ? AND s.available_at <= ?" + clause,
                                   [eid, cutoff, *args]).fetchone()
            if row is None:
                raise KeyError("evidence unavailable at requested cutoff: " + eid)
            found[eid] = json.loads(row[0])
        return {"snapshot_id": self.snapshot_id, "evidence": found}

    def _source_restriction(self, prefix=""):
        scope = getattr(self, "_execution_scope", None)
        if scope is None:
            return "", []
        sources = ", ".join("?" for _ in scope.source_snapshot_ids)
        companies = ", ".join("?" for _ in scope.company_ids)
        return (f" AND {prefix}source_snapshot_id IN ({sources}) AND {prefix}company_id IN ({companies})",
                [*scope.source_snapshot_ids, *scope.company_ids])

    def _observation_restriction(self, cutoff):
        clause, args = self._source_restriction()
        if not clause:
            return "", []
        return (" AND source_snapshot_id IN (SELECT source_snapshot_id FROM sources WHERE available_at <= ?"
                + clause + ")", [cutoff, *args])

    @staticmethod
    def _key(request):
        return digest(request.model_dump(mode="json"))[:24]

    def _lookup(self, request, query, trace):
        plan = request.model_dump(mode="json")
        base = {"request": plan, "selection_id": self._key(request), "record_ids": []}
        if request.metric_id not in self.metrics or request.entity_id not in self.entities:
            return {**base, "status": "unsupported", "reason": "unknown_entity_or_metric"}, []
        if not query.include_candidates:
            return {**base, "status": "quality_filtered", "reason": "dataset_contains_candidates_only"}, []
        sql = "SELECT payload FROM observations WHERE entity_id = ? AND metric_id = ? AND value_kind = ?"
        args = [request.entity_id, request.metric_id, request.value_kind]
        if request.period:
            sql += " AND period_kind = ? AND period_start IS NOT DISTINCT FROM ? AND period_end = ?"
            args += [request.period.kind, request.period.start, request.period.end]
        else:
            sql += " AND period_kind IS NULL"
        def select(cutoff):
            clause, scope_args = self._observation_restriction(cutoff)
            return (sql + clause + " AND available_at <= ? AND status = 'candidate' ORDER BY record_id LIMIT 257",
                    args + scope_args + [cutoff])
        rows = [json.loads(r[0]) for r in self._sql(*select(query.knowledge_cutoff), trace)]
        if len(rows) > 256:
            return {**base, "status": "limited", "reason": "narrow_query_before_consuming_records"}, []
        base["record_ids"] = [r["record_id"] for r in rows]
        if not rows:
            uncapped = self._db.execute(*select(date.max)).fetchall()
            if uncapped:
                return {**base, "status": "not_available_at_cutoff", "reason": "later_source_exists_in_snapshot"}, []
            company = self.entities[request.entity_id]["company_id"]
            eligible_sources = {s["source_snapshot_id"] for s in self.sources
                                if s["company_id"] == company and s["available_at"] <= str(query.knowledge_cutoff)
                                and (request.value_kind != "actual" or s["form"] in
                                     ("10-K", "10-Q", "20-F", "10-K/A", "10-Q/A", "20-F/A"))}
            matching_periods = {s["source_snapshot_id"] for s in self.sources if s["source_snapshot_id"] in eligible_sources
                                and request.period and s["period_end"] == str(request.period.end)}
            if request.period:
                clause, scope_args = self._observation_restriction(query.knowledge_cutoff)
                matching_periods.update(r[0] for r in self._db.execute(
                    "SELECT DISTINCT source_snapshot_id FROM observations WHERE entity_id = ? AND period_kind = ? "
                    "AND period_start IS NOT DISTINCT FROM ? AND period_end = ? AND available_at <= ?" + clause,
                    [request.entity_id, request.period.kind, request.period.start, request.period.end,
                     query.knowledge_cutoff, *scope_args]).fetchall() if r[0] in eligible_sources)
            return {**base, "status": "source_present_unprocessed" if matching_periods else "source_missing",
                    "reason": "not_structured_in_this_pilot; not a not-disclosed finding"}, []
        if all(r["value_relation"] == "qualitative" for r in rows):
            return {**base, "status": "listed", "reason": "qualitative_statements_are_not_numeric_observations"}, rows
        signatures = {json.dumps([r[k] for k in ("record_type", "value_decimal", "upper_decimal", "value_relation", "unit",
                      "accounting_basis", "dimensions", "denominator", "modality")]
                      + [r["available_at"] if r["value_kind"] == "management_guidance" else None], sort_keys=True) for r in rows}
        return {**base, "status": "matched" if len(signatures) == 1 else "ambiguous",
                "reason": "equivalent_numeric_disclosures_retained" if len(rows) > 1 and len(signatures) == 1 else "one_or_conflicting_observations",
                "occurrence_count": len(rows)}, rows

    def _documents(self, request, query, trace):
        spec = request.model_dump(mode="json")
        sources = [s for s in self.sources if s["company_id"] == request.company_id and s["form"] == request.form
                   and s["period_end"] == str(request.period_end)]
        if not query.include_candidates:
            return {"request": spec, "status": "quality_filtered", "contexts": []}
        visible = [s for s in sources if s["available_at"] <= str(query.knowledge_cutoff)]
        if not visible:
            return {"request": spec, "status": "not_available_at_cutoff" if sources else "source_missing", "contexts": []}
        contexts, hits, remaining, seen = [], 0, request.limit, set()
        for source in visible:
            reader = self._reader(source)
            node_id = self._document_node(reader)
            result = reader.search(node_id, request.phrase, limit=request.limit)
            hits += result["total"]
            trace.append({"tool": "document_search", "source_snapshot_id": source["source_snapshot_id"],
                          "phrase": request.phrase, "total_hits": result["total"], "mode": "literal_source_order",
                          **{k:v for k,v in result.items() if k.startswith('omitted_') or k == 'omission_reason'}})
            for hit in result["hits"]:
                if remaining == 0:
                    break
                anchor = reader.blocks[reader.positions[hit["block_id"]]]
                start = reader.positions[hit["block_id"]]
                if anchor.get("speaker") and not anchor.get("exchange_id"):
                    for previous in reader.blocks[max(0, start - 2):start][::-1]:
                        if previous.get("turn_id") != anchor.get("turn_id") or previous.get("speaker") != anchor.get("speaker"):
                            break
                        start -= 1
                context = reader.read(node_id, reader.blocks[start]["block_id"], count=reader.positions[hit["block_id"]] - start + 1)
                block_ids = tuple(b["block_id"] for b in context["blocks"])
                key = (source["source_snapshot_id"], block_ids)
                if key in seen:
                    continue
                seen.add(key)
                chars = sum(len(b["text"]) for b in context["blocks"])
                payload = {"source_snapshot_id": source["source_snapshot_id"], "index_id": source["index_id"],
                           "source_url": source["source_url"], "source_sha256": source["source_sha256"],
                           "anchor_block_id": hit["block_id"], "block_ids": block_ids, "context_characters": chars,
                           "source_period_end": source["period_end"], "available_at": source["available_at"],
                           **{k:v for k,v in context.items() if k.startswith('omitted_') or k == 'omission_reason'}}
                if chars > 80000 or (getattr(self, "_execution_scope", None) is not None
                                    and len(json.dumps(context, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES):
                    contexts.append({**payload, "status": "context_too_large", "blocks": [],
                                     "continuation": {"source_snapshot_id": source["source_snapshot_id"], "block_id": hit["block_id"]}})
                else:
                    contexts.append({**payload, "status": "read", "blocks": context["blocks"]})
                remaining -= 1
                trace.append({"tool": "document_read", **{k:v for k,v in payload.items() if k != "source_url"}})
        status = "no_literal_match" if not hits else "limited" if hits > request.limit or any(c["status"] != "read" for c in contexts) else "matched"
        return {"request": spec, "status": status, "total_literal_hits": hits, "contexts": contexts,
                "coverage": "bounded literal retrieval; not exhaustive semantic recall", "not_disclosed": False}

    def read_context(self, *, source_snapshot_id, block_id, snapshot_id, knowledge_cutoff, include_candidates=False,
                     representation="full"):
        if representation not in {"full", "compact"}:
            raise ValueError("unsupported source representation")
        if snapshot_id != self.snapshot_id:
            raise ValueError("snapshot mismatch")
        if not include_candidates:
            raise PermissionError("candidate access must be explicit")
        cutoff = date.fromisoformat(knowledge_cutoff)
        source = next((s for s in self.sources if s["source_snapshot_id"] == source_snapshot_id and date.fromisoformat(s["available_at"]) <= cutoff), None)
        if source is None:
            raise KeyError("source unavailable at cutoff")
        reader = self._reader(source)
        result = reader.read(self._document_node(reader), block_id, count=1)
        if representation == "compact":
            result = compact_table_cells(result)
        return {"snapshot_id": self.snapshot_id, "source_snapshot_id": source_snapshot_id, "source_sha256": source["source_sha256"],
                "source_url": source["source_url"], **result}

    @staticmethod
    def _dependencies(calculation):
        metrics = ("revenue", "operating_income") if calculation.formula_id in ("operating_margin", "operating_margin_delta_pp") else (calculation.formula_id.removesuffix("_yoy"),)
        return [RecordRequest(entity_id=calculation.entity_id, metric_id=m, period=p, value_kind="actual")
                for p in calculation.periods for m in metrics]

    def _calculate(self, calculation, selections, records):
        deps = self._dependencies(calculation)
        used, values = [], []
        for dep in deps:
            selection = selections[self._key(dep)]
            if selection["status"] != "matched":
                raise ValueError("operand_missing_or_ambiguous")
            members = [records[rid] for rid in selection["record_ids"]]
            r = members[0]
            if r["value_relation"] != "eq" or r["value_kind"] != "actual" or r["record_type"] != "metric":
                raise ValueError("operand_not_exact_actual")
            used.extend(selection["record_ids"])
            values.append(r)
        signature = lambda r: json.dumps([r[k] for k in ("entity_id", "unit", "accounting_basis", "dimensions")], sort_keys=True)
        if len({signature(r) for r in values}) != 1:
            raise ValueError("incompatible_unit_basis_or_dimensions")
        periods = calculation.periods
        if len(periods) == 2:
            a, b = periods
            months = lambda p: (p.end.year - p.start.year) * 12 + p.end.month - p.start.month + 1 if p.start else None
            if a.end >= b.end or a.kind != b.kind or months(a) != months(b):
                raise ValueError("incomparable_periods")
            if calculation.formula_id.endswith("_yoy") and (b.end.year != a.end.year + 1 or
                    (a.end.month, a.end.day) != (b.end.month, b.end.day) or a.start is None or b.start is None or
                    (a.start.month, a.start.day) != (b.start.month, b.start.day)):
                raise ValueError("not_year_over_year_periods")
        with localcontext() as context:
            context.prec = 50
            decimals = [Decimal(r["value_decimal"]) for r in values]
            if calculation.formula_id in ("operating_margin", "operating_margin_delta_pp"):
                if any(x <= 0 for x in decimals[::2]):
                    raise ValueError("nonpositive_revenue_denominator")
                margins = [decimals[i+1] / decimals[i] * 100 for i in range(0, len(decimals), 2)]
                value = margins[0] if len(margins) == 1 else margins[1] - margins[0]
            else:
                if decimals[0] <= 0:
                    raise ValueError("nonpositive_yoy_base")
                value = (decimals[1] / decimals[0] - 1) * 100
            exact = str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))
            display = str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
        result = {"formula_id": calculation.formula_id + "-v1", "entity_id": calculation.entity_id,
                  "periods": [p.model_dump(mode="json") for p in periods], "operand_record_ids": used,
                  "value_decimal": exact, "display_decimal": display,
                  "unit": "percentage_points" if calculation.formula_id.endswith("_pp") else "percent",
                  "rounding": "Decimal precision 50; HALF_EVEN 6 output decimals / 2 display decimals",
                  "snapshot_id": self.snapshot_id}
        return {"computed_id": "calc-" + digest(result)[:24], **result}

    def query_data(self, request):
        query = request if isinstance(request, DataQuery) else DataQuery.model_validate(request)
        for period in [r.period for r in query.records] + [p for c in query.calculations for p in c.periods]:
            validate_period_version(period, self.manifest["schema_version"])
        if query.snapshot_id != self.snapshot_id:
            raise ValueError("snapshot mismatch")
        if query.source_policy_id != self.manifest["source_policy_id"]:
            raise PermissionError("source policy mismatch")
        trace, selections, all_records, gaps = [], {}, {}, []
        needs = list(query.records)
        for calc in query.calculations:
            needs.extend(self._dependencies(calc))
        for need in needs:
            key = self._key(need)
            if key in selections:
                continue
            selection, rows = self._lookup(need, query, trace)
            selections[key] = selection
            all_records.update({r["record_id"]:r for r in rows})
            if selection["status"] not in ("matched", "listed"):
                gaps.append({"scope": "record", "selection_id": key, "reason": selection["status"], "request": selection["request"]})
            elif any(r["period_resolution"] == "unresolved" for r in rows):
                gaps.append({"scope": "semantics", "selection_id": key, "reason": "target_period_unresolved"})
        computed = []
        for calc in query.calculations:
            try:
                result = self._calculate(calc, selections, all_records)
                computed.append(result)
                trace.append({"tool": "registered_calculation", "computed_id": result["computed_id"], "formula_id": result["formula_id"]})
            except ValueError as error:
                gaps.append({"scope": "calculation", "formula_id": calc.formula_id, "reason": str(error)})
        documents = [self._documents(d, query, trace) for d in query.documents]
        gaps.extend({"scope": "document", "request": d["request"], "reason": d["status"]} for d in documents if d["status"] != "matched")
        evidence_ids = sorted({eid for r in all_records.values() for name in ("evidence_ids", "qualifier_evidence_ids", "question_evidence_ids") for eid in r[name]})
        evidence = {}
        for offset in range(0, len(evidence_ids), 256):
            evidence.update(self.get_evidence(evidence_ids[offset:offset + 256], snapshot_id=self.snapshot_id,
                            knowledge_cutoff=str(query.knowledge_cutoff),
                            include_candidates=query.include_candidates)["evidence"])
        has_content = bool(all_records or computed or any(d["contexts"] for d in documents))
        status = "ambiguous" if any(g["reason"] == "ambiguous" for g in gaps) else "partial" if gaps and has_content else "unanswerable" if gaps else "complete"
        return QueryResult(result_schema_version=self.manifest["schema_version"],
                           query_id=query.query_id, snapshot_id=self.snapshot_id, source_policy_id=query.source_policy_id,
                           knowledge_cutoff=query.knowledge_cutoff, candidate_data=query.include_candidates, status=status,
                           completion_scope="Resolved typed plan only; document match does not establish semantic completeness of the natural-language question.",
                           records=tuple(ResearchRecord.model_validate(r) for r in all_records.values()),
                           selections=tuple(selections.values()), computed_facts=tuple(computed), documents=tuple(documents),
                           evidence=evidence, gaps=tuple(gaps), trace=tuple(trace)).model_dump(mode="json")


class ScopedQueryDataPort(QueryDataPort):
    """One source allowlist for all read tools; owns no connection or snapshot."""

    def __init__(self, port, scope):
        self._execution_scope = ExecutionScope.model_validate(scope)
        scope = self._execution_scope
        parent_scope = getattr(port, "_execution_scope", None)
        if parent_scope is not None and (
                not set(scope.company_ids).issubset(parent_scope.company_ids)
                or not set(scope.source_snapshot_ids).issubset(parent_scope.source_snapshot_ids)
                or scope.knowledge_cutoff > parent_scope.knowledge_cutoff
                or (scope.include_candidates and not parent_scope.include_candidates)):
            raise ValueError("a scoped port cannot widen its company, source, cutoff or candidate access")
        if scope.snapshot_id != port.snapshot_id:
            raise ValueError("snapshot mismatch")
        if scope.source_policy_id != port.manifest["source_policy_id"]:
            raise ValueError("source policy mismatch")
        selected = []
        for sid in scope.source_snapshot_ids:
            matches = [s for s in port.sources if s["source_snapshot_id"] == sid]
            if len(matches) != 1:
                raise ValueError("selected source is unknown or ambiguous")
            if matches[0]["company_id"] not in scope.company_ids:
                raise ValueError("selected source is outside company scope")
            selected.append(matches[0])
        if set(scope.company_ids) != {s["company_id"] for s in selected}:
            raise ValueError("each requested company requires an explicitly selected source")
        self.dataset, self.manifest, self.metrics = port.dataset, port.manifest, port.metrics
        self._db, self._readers = port._db, port._readers
        self.sources = selected
        self.scope = scope
        self.scope_id = "scope-" + digest(scope.model_dump(mode="json"))[:24]
        # Entity roots are supplied by the selected source metadata. Child entities
        # and their accounting bases/dimensions require permitted observations
        # inside the same source and observation cutoff. Never copy the parent's
        # entity catalog: one entity may occur in both selected and excluded sources.
        entities = {s["company_id"]: {"entity_id": s["company_id"], "company_id": s["company_id"],
                                      "accounting_bases": set()} for s in selected}
        clause, args = self._source_restriction("s.")
        rows = self._db.execute(
            "SELECT o.entity_id, s.company_id, o.accounting_basis, o.payload FROM observations o "
            "JOIN sources s USING(source_snapshot_id) WHERE o.available_at <= ? AND s.available_at <= ? "
            "AND o.status = 'candidate'" + clause + " ORDER BY o.record_id",
            [scope.knowledge_cutoff, scope.knowledge_cutoff, *args]).fetchall()
        for entity, company, basis, payload in rows:
            entry = entities.setdefault(entity, {"entity_id": entity, "company_id": company, "accounting_bases": set()})
            if entry["company_id"] != company:
                raise ValueError("entity belongs to multiple scoped companies")
            if not scope.include_candidates:
                continue
            entry["accounting_bases"].add(basis)
            dimensions = json.loads(payload).get("dimensions", {})
            if dimensions:
                reported = entry.setdefault("reported_dimensions", [])
                if dimensions not in reported:
                    reported.append(dimensions)
        self.entities = {key: {**value, "accounting_bases": sorted(value["accounting_bases"])}
                         for key, value in sorted(entities.items())}

    def close(self):
        """Connection lifecycle belongs to the original QueryDataPort."""

    def scoped(self, scope):
        """Derived capabilities may retain or narrow, never widen, this scope."""
        return ScopedQueryDataPort(self, scope)

    def for_query_source(self, source_id=None):
        """Pin one model-declared numeric source without changing caller authority."""
        if source_id is None:
            return self
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("query source_id must be a nonblank scoped source ID")
        source = self._source(source_id)
        if source["available_at"] > str(self.scope.knowledge_cutoff):
            raise ValueError("query source is unavailable at cutoff")
        return self.scoped({**self.scope.model_dump(mode="json"),
            "company_ids": [source["company_id"]], "source_snapshot_ids": [source_id]})

    def _header(self):
        scope = self.scope
        return {"execution_schema_version": EXECUTION_VERSION, "scope_id": self.scope_id,
                "scope": scope.model_dump(mode="json"), "snapshot_id": self.snapshot_id,
                "source_policy_id": scope.source_policy_id, "knowledge_cutoff": str(scope.knowledge_cutoff),
                "candidate_data": scope.include_candidates}

    def _check_headers(self, values):
        fixed = {"snapshot_id": self.snapshot_id, "source_policy_id": self.scope.source_policy_id,
                 "knowledge_cutoff": str(self.scope.knowledge_cutoff), "include_candidates": self.scope.include_candidates}
        if any(key not in fixed or str(value) != str(fixed[key]) for key, value in values.items()):
            raise ValueError("query headers cannot change the execution scope")

    def discover_catalog(self, request):
        """Bounded navigation view; frozen discover_data remains unchanged."""
        from .query_catalog import discover_catalog
        return discover_catalog(self, request)

    def probe_schema(self, request):
        """Bounded data semantics/examples, without full execution protocols."""
        from .query_catalog import probe_schema
        return probe_schema(self, request)

    def get_schema(self, metric_ids=()):
        result = super().get_schema(metric_ids)
        result["fiscal_periods"] = [
            {**period, "company_id": source["company_id"], "source_snapshot_id": source["source_snapshot_id"]}
            for source in self.sources
            if self.scope.include_candidates and date.fromisoformat(source["available_at"]) <= self.scope.knowledge_cutoff
            for period in source.get("fiscal_periods", [])
        ]
        result.update(self._header())
        result["output_contracts"] = {"evidence_package": EvidencePackage.model_json_schema(),
                                      "task_progress": ProgressSnapshot.model_json_schema(),
                                      "task_completion": CompletionAssessment.model_json_schema()}
        result["execution_contracts"] = {name: model.model_json_schema() for name, model in (
            ("scope", ExecutionScope), ("outline_source", SourceOutlineRequest),
            ("read_source", SourceReadRequest), ("search_source", SourceSearchRequest))}
        # Separate discovery avoids expanding legacy planner packets before the
        # task-driven ReAct integration is implemented.
        result["task_contracts"] = {"plan": TaskPlan.model_json_schema(), "step": TaskStep.model_json_schema()}
        result["capabilities"] += ["explicit_source_scope", "source_outline", "chapter_read_with_continuation",
                                   "paginated_literal_source_search"]
        result["notes"] += ["Frozen query/record/result schemas describe v0.3 storage; execution_contracts describe current scoped tools.",
                            "Source reporting dates do not substitute for explicitly requested observation periods.",
                            "Outline and search previews are navigation, not evidence of complete chapter reading."]
        return result

    def discover_data(self):
        scope = self.scope
        clause, args = self._source_restriction("s.")
        rows = self._db.execute(
            "SELECT o.entity_id, o.metric_id, o.period_kind, o.period_start, o.period_end, o.value_kind, count(*) "
            "FROM observations o JOIN sources s USING(source_snapshot_id) "
            "WHERE o.available_at <= ? AND s.available_at <= ? AND o.status = 'candidate'" + clause
            + " GROUP BY ALL ORDER BY o.entity_id, o.metric_id, o.period_end",
            [scope.knowledge_cutoff, scope.knowledge_cutoff, *args]).fetchall()
        visible = [s for s in self.sources if s["available_at"] <= str(scope.knowledge_cutoff)]
        return {**self._header(), "status": "candidate",
                "sources": [{**{k: v for k, v in s.items() if k != "fiscal_periods" or scope.include_candidates},
                             "queryable": scope.include_candidates} for s in visible],
                "coverage": [{"entity_id": r[0], "metric_id": r[1], "period_kind": r[2],
                              "period_start": str(r[3]) if r[3] else None, "period_end": str(r[4]) if r[4] else None,
                              "value_kind": r[5], "occurrence_count": r[6],
                              "status": "available_candidate" if scope.include_candidates else "quality_filtered"} for r in rows],
                "gaps": [{"scope": "source", "source_snapshot_id": s["source_snapshot_id"],
                          "reason": "not_available_at_cutoff"} for s in self.sources if s not in visible],
                "limits": self.manifest["limits"], "not_disclosed_inference": "never inferred from a missing row"}

    def query_data(self, request):
        query = DataQuery.model_validate(request)
        self._check_headers({key: getattr(query, key) for key in
                             ("snapshot_id", "source_policy_id", "knowledge_cutoff", "include_candidates")})
        if any(r.entity_id not in self.entities for r in (*query.records, *query.calculations)):
            raise ValueError("entity is outside the visible execution scope")
        if any(d.company_id not in self.scope.company_ids for d in query.documents):
            raise ValueError("document company is outside execution scope")
        return {**super().query_data(query), **self._header()}

    def get_evidence(self, evidence_ids, **headers):
        self._check_headers(headers)
        return {**super().get_evidence(evidence_ids, snapshot_id=self.snapshot_id,
                    knowledge_cutoff=str(self.scope.knowledge_cutoff), include_candidates=self.scope.include_candidates),
                **self._header()}

    def _source(self, sid):
        matches = [s for s in self.sources if s["source_snapshot_id"] == sid]
        if len(matches) != 1:
            raise ValueError("source is outside execution scope")
        return matches[0]

    def _source_header(self, source):
        return {**self._header(), "source": source, "source_snapshot_id": source["source_snapshot_id"],
                "company_id": source["company_id"], "source_period_end": source["period_end"],
                "available_at": source["available_at"],
                **{key: source[key] for key in ("index_id", "source_sha256", "source_url") if key in source}}

    def _blocked_source(self, source):
        if not self.scope.include_candidates:
            return "quality_filtered"
        if source["available_at"] > str(self.scope.knowledge_cutoff):
            return "not_available_at_cutoff"
        return None

    def _empty(self, source, status, **details):
        return {**self._source_header(source), "status": status, "blocks": [], "nodes": [], "hits": [],
                "next_cursor": None, "next_block_id": None, "next_offset": None,
                "node_complete": False, "not_disclosed": False,
                "gaps": [{"scope": "document", "source_snapshot_id": source["source_snapshot_id"],
                          "reason": status, **details}], **details}

    def _navigation(self, source, node_id=None):
        reader = self._reader(source)
        if reader.index["index_id"] != source["index_id"]:
            raise ValueError("source index identity mismatch")
        if node_id is not None and node_id not in reader.nodes:
            return reader, self._empty(source, "node_missing", node_id=node_id)
        return reader, None

    def _cursor_header(self, source, reader, node_id):
        return {"scope_id": self.scope_id, "snapshot_id": self.snapshot_id,
                "source_snapshot_id": source["source_snapshot_id"],
                "index_id": reader.index["index_id"], "node_id": node_id}

    def _check_cursor(self, cursor, source, reader, node_id):
        if any(getattr(cursor, key) != value for key, value in self._cursor_header(source, reader, node_id).items()):
            raise ValueError("continuation cursor does not match source, node, index or execution scope")

    def outline_source(self, request):
        request = SourceOutlineRequest.model_validate(request)
        source = self._source(request.source_snapshot_id)
        blocked = self._blocked_source(source)
        if blocked:
            return self._empty(source, blocked)
        reader, _ = self._navigation(source)
        result = reader.outline()
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES:
            return self._empty(source, "outline_too_large")
        return {**result, **self._source_header(source), "index_status": result["status"], "status": "available",
                "coverage": "Document structure only; no body text has been read.", "gaps": []}

    def read_source(self, request):
        request = SourceReadRequest.model_validate(request)
        source = self._source(request.source_snapshot_id)
        blocked = self._blocked_source(source)
        if blocked:
            return self._empty(source, blocked, node_id=request.node_id)
        reader, missing = self._navigation(source, request.node_id)
        if missing:
            return missing
        start = request.start_block_id
        if request.cursor:
            self._check_cursor(request.cursor, source, reader, request.node_id)
            if start is not None and start != request.cursor.start_block_id:
                raise ValueError("read start conflicts with continuation cursor")
            start = request.cursor.start_block_id
        # Omitting a block explicitly means the start of this selected chapter,
        # never an implicit selection of another chapter or the whole document.
        if start is None:
            start = reader.nodes[request.node_id]["start_block_id"]
        if start not in reader.positions:
            raise ValueError("unknown read block")
        result = reader.read(request.node_id, start, count=request.count)
        full_bytes = len(json.dumps(result, ensure_ascii=False).encode())
        if request.representation == "compact":
            result = compact_table_cells(result)
        lo, hi = reader._range(request.node_id)
        # A requested layout-only slice may be explicitly omitted. Do not
        # silently read a different block or claim that any body was returned.
        returned_start = reader.positions[result["blocks"][0]["block_id"]] if result["blocks"] else reader.positions[start]
        returned_end = reader.positions[result["blocks"][-1]["block_id"]] + 1 if result["blocks"] else returned_start
        crossing = [g["group_id"] for g in reader.groups
                    if result["blocks"] and reader.positions[g["block_ids"][0]] < returned_end
                    and reader.positions[g["block_ids"][-1]] + 1 > returned_start
                    and not (lo <= reader.positions[g["block_ids"][0]]
                             and reader.positions[g["block_ids"][-1]] + 1 <= hi)]
        if crossing:
            return self._empty(source, "context_crosses_node", node_id=request.node_id,
                               requested_start_block_id=start, context_group_ids=crossing,
                               detail="Complete context crosses this node; explicitly select a containing node before reading.")
        required_bytes = len(json.dumps(result, ensure_ascii=False).encode())
        if required_bytes > MAX_DOCUMENT_BYTES:
            compact_bytes = (required_bytes if request.representation == "compact" else
                             len(json.dumps(compact_table_cells(result), ensure_ascii=False).encode()))
            # Encoding changes preserve this exact atomic range. A failed read
            # supplies no body and does not advance source or reading coverage.
            retry_representation = ("compact" if request.representation == "full" and compact_bytes <= MAX_DOCUMENT_BYTES
                                    else "full" if full_bytes <= MAX_DOCUMENT_BYTES else None)
            retry = ({**request.model_dump(mode="json"), "representation": retry_representation}
                     if retry_representation else None)
            return self._empty(source, "context_too_large", node_id=request.node_id,
                               requested_start_block_id=start,
                               representation=request.representation, required_bytes=required_bytes,
                               max_bytes=MAX_DOCUMENT_BYTES,
                               representation_bytes={"full": full_bytes, "compact": compact_bytes},
                               retry_request=retry,
                               detail=("Atomic context exceeds the response limit; no blocks read or continuation advanced. "
                                       f"Retry the same source range with representation={retry_representation}; all text and cells are retained."
                                       if retry else
                                       "Atomic context exceeds the response limit; no blocks read or continuation advanced. "
                                       "Neither supported representation fits. Report a capacity gap for this atomic range."))
        following = result["next_block_id"]
        cursor = ReadCursor(**self._cursor_header(source, reader, request.node_id), start_block_id=following) if following else None
        layout_only = not result['blocks'] and bool(result.get('omitted_block_count'))
        return {**result, **self._source_header(source), "status": "layout_only" if layout_only else "read", "gaps": [],
                "requested_start_block_id": start, "block_ids": [b["block_id"] for b in result["blocks"]],
                "next_cursor": cursor.model_dump(mode="json") if cursor else None,
                "node_complete": following is None,
                **({'not_disclosed': False} if layout_only else {}),
                "coverage": ("Only repeated navigation was omitted; no body blocks were read. Continuation and node_complete describe source traversal, not complete reading."
                             if layout_only else "Returned full blocks only; reaching the node end does not prove all earlier blocks were read.")}

    def search_source(self, request):
        request = SourceSearchRequest.model_validate(request)
        source = self._source(request.source_snapshot_id)
        blocked = self._blocked_source(source)
        if blocked:
            return self._empty(source, blocked, node_id=request.node_id)
        reader, missing = self._navigation(source, request.node_id)
        if missing:
            return missing
        offset = request.offset if request.offset is not None else 0
        if request.cursor:
            self._check_cursor(request.cursor, source, reader, request.node_id)
            if request.cursor.phrase != request.phrase:
                raise ValueError("search phrase conflicts with continuation cursor")
            if request.offset is not None and offset != request.cursor.offset:
                raise ValueError("search offset conflicts with continuation cursor")
            offset = request.cursor.offset
        result = reader.search(request.node_id, request.phrase, offset=offset, limit=request.limit)
        if offset and offset >= result["total"]:
            raise ValueError("search offset is outside the matching hit range")
        following = result["next_offset"]
        cursor = SearchCursor(**self._cursor_header(source, reader, request.node_id),
                              phrase=request.phrase, offset=following) if following is not None else None
        status = "no_literal_match" if not result["total"] else "limited" if following is not None else "matched"
        return {**result, **self._source_header(source), "status": status, "phrase": request.phrase, "offset": offset,
                "next_cursor": cursor.model_dump(mode="json") if cursor else None, "not_disclosed": False,
                "coverage": "Literal source-order previews only; no complete body contexts read or semantic recall established.",
                "gaps": [] if status == "matched" else [{"scope": "document_search", "reason": status,
                    "source_snapshot_id": source["source_snapshot_id"], "node_id": request.node_id}]}

    def read_context(self, *, source_snapshot_id, block_id, representation="full"):
        source = self._source(source_snapshot_id)
        blocked = self._blocked_source(source)
        if blocked:
            return self._empty(source, blocked)
        reader, _ = self._navigation(source)
        return self.read_source(SourceReadRequest(source_snapshot_id=source_snapshot_id,
                                node_id=self._document_node(reader), start_block_id=block_id, count=1,
                                representation=representation))
