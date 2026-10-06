"""Bounded source-first financial records; no benchmark or model dependencies.

Supports explicitly supplied issuer/segment mappings and calendar fiscal periods. Unsupported
formats, contexts and source mismatches are explicit diagnostics, never guesses.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from lxml import html
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources.sec import normalize_text

VERSION = "financial-records-v0.2"
CONCEPTS = {
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "us-gaap:OperatingIncomeLoss": "operating_income",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment": "capex_cash_payments",
    "us-gaap:RevenueRemainingPerformanceObligation": "remaining_performance_obligations",
}

class FinancialMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    company_id: str = Field(min_length=1, pattern=r"\S")
    entity_identifier: str = Field(min_length=1, pattern=r"\S")
    segment_entity_id: str = Field(min_length=1, pattern=r"\S")
    segment_axis: str = Field(min_length=1)
    segment_member: str = Field(min_length=1)
    consolidation_axis: str = Field(min_length=1)
    consolidation_member: str = Field(min_length=1)
    fiscal_calendar: Literal["calendar"]


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def local_name(element):
    return str(element.tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def one_text(element, name):
    matches = [x.text_content().strip() for x in element.iter() if local_name(x) == name]
    if len(matches) != 1:
        raise ValueError("missing_or_ambiguous_" + name)
    return matches[0]


def parse_context(element, *, entity_identifier):
    identifier = one_text(element, "identifier")
    if not entity_identifier or identifier != entity_identifier:
        raise ValueError("unsupported_entity")
    dimensions = {}
    for member in element.iter():
        if local_name(member) == "typedmember":
            raise ValueError("unsupported_typed_dimension")
        if local_name(member) == "explicitmember":
            axis, value = member.get("dimension"), member.text_content().strip()
            if not axis or axis in dimensions:
                raise ValueError("ambiguous_dimensions")
            dimensions[axis] = value
    instant = [x for x in element.iter() if local_name(x) == "instant"]
    if instant:
        end = one_text(element, "instant")
        date.fromisoformat(end)
        period = {"kind": "instant", "start": None, "end": end, "instant": end, "aliases": []}
    else:
        start, end = one_text(element, "startdate"), one_text(element, "enddate")
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a > b or a.year != b.year or a.day != 1:
            raise ValueError("unsupported_fiscal_period")
        if (b + timedelta(days=1)).day != 1 or b.month not in (3, 6, 9, 12):
            raise ValueError("unsupported_period_end")
        months = b.month - a.month + 1
        if a.month == 1 and months == 12:
            kind, aliases = "year", []
        elif a.month in (1, 4, 7, 10) and months == 3:
            kind, aliases = "quarter", ["ytd"] if a.month == 1 else []
        elif a.month == 1 and months in (6, 9):
            kind, aliases = "ytd", []
        else:
            raise ValueError("unsupported_duration")
        period = {"kind": kind, "start": start, "end": end, "instant": None,
                  "months": months, "fiscal_year": a.year, "fiscal_quarter": b.month // 3,
                  "aliases": aliases}
    return {"entity_identifier": identifier, "dimensions": dict(sorted(dimensions.items())), "period": period}


def parse_number(tag, unit):
    if local_name(tag) != "nonfraction" or tag.get("continuedat"):
        raise ValueError("unsupported_inline_fact")
    if any(local_name(x) == "exclude" for x in tag.iter()):
        raise ValueError("unsupported_ix_exclude")
    if any(k.endswith("nil") and v.lower() in ("true", "1") for k, v in tag.attrib.items()):
        raise ValueError("nil_fact")
    measures = [x.text_content().strip() for x in unit.iter() if local_name(x) == "measure"]
    if measures != ["iso4217:USD"] or any(local_name(x) == "divide" for x in unit.iter()):
        raise ValueError("unsupported_unit")
    fmt = tag.get("format")
    if fmt not in (None, "ixt:num-dot-decimal", "ixt:numdotdecimal"):
        raise ValueError("unsupported_number_transform")
    text = normalize_text(tag.text_content())
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text):
        raise ValueError("unsupported_number_text")
    scale = int(tag.get("scale", "0"))
    if not -12 <= scale <= 12 or tag.get("sign", "+") not in ("+", "-"):
        raise ValueError("invalid_scale_or_sign")
    value = Decimal(text.replace(",", "")) * (Decimal(10) ** scale)
    if tag.get("sign") == "-":
        value = -value
    return {"value_decimal": format(value, "f"), "unit": "USD", "raw_value": text,
            "scale": scale, "sign": tag.get("sign", "+"), "decimals": tag.get("decimals"), "format": fmt}


def dom_path_query(path):
    return re.sub(r"([\w-]+:[\w-]+)", r"*[name()='\1']", path)


def cell_grid(table):
    """Preserve rowspan/colspan, including empty layout cells."""
    occupied, grid = set(), {}
    rows = table.xpath(".//tr[not(ancestor::table[2])]")
    for row, tr in enumerate(rows):
        column = 0
        for td in tr.xpath("./th|./td"):
            while (row, column) in occupied:
                column += 1
            rs, cs = int(td.get("rowspan", "1")), int(td.get("colspan", "1"))
            if rs < 1 or cs < 1:
                raise ValueError("invalid_cell_span")
            grid[td] = {"row": row, "column": column, "rowspan": rs, "colspan": cs,
                        "text": normalize_text(td.text_content())}
            occupied.update((r, c) for r in range(row, row + rs) for c in range(column, column + cs))
            column += cs
    return grid


def logical_key(record):
    return (record["entity_id"], record["metric"], record["period"]["start"], record["period"]["end"],
            record["unit"], record["accounting_basis"], json.dumps(record["dimensions"], sort_keys=True))


def validate_table_headers(block, cell, period):
    headers = [c for c in block["table"]["cells"] if c["row"] < cell["row"]
               and c["column"] <= cell["column"] < c["column"] + c["colspan"]]
    years = [c for c in headers if re.fullmatch(r"20\d{2}", c["text"])]
    if not years or max(years, key=lambda c: c["row"])["text"] != period["end"][:4]:
        raise ValueError("year_header_context_mismatch")
    durations = [(c, months) for c in headers for pattern, months in
                 [(r"Three Months Ended", 3), (r"Six Months Ended", 6),
                  (r"Nine Months Ended", 9), (r"Year Ended", 12)]
                 if re.search(pattern, c["text"], re.I)]
    if not durations or max(durations, key=lambda pair: pair[0]["row"])[1] != period.get("months"):
        raise ValueError("duration_header_context_mismatch")
    return [max(years, key=lambda c: c["row"]), max(durations, key=lambda pair: pair[0]["row"])[0]]


def extract_financial_records(source_dir, index_dir, *, mapping: FinancialMapping, metrics=None, period_kinds=None):
    source_dir, index_dir = Path(source_dir), Path(index_dir)
    manifest = json.loads((source_dir / "manifest.json").read_text())
    raw = gzip.decompress((source_dir / "source.html.gz").read_bytes())
    if digest(raw) != manifest["content_sha256"]:
        raise ValueError("source_hash_mismatch")
    if manifest.get("company_id", mapping.company_id) != mapping.company_id:
        raise ValueError("source_company_mapping_mismatch")
    reader = DocumentReader(index_dir)
    if reader.manifest["source_sha256"] != digest(raw):
        raise ValueError("source_index_mismatch")
    tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding="utf-8"))
    by_id = {}
    for element in tree.iter():
        if element.get("id"):
            by_id.setdefault(element.get("id"), []).append(element)
    block_elements, grids = {}, {}
    for block in reader.blocks:
        if not block.get("dom_path"):
            continue
        found = tree.xpath(dom_path_query(block["dom_path"]))
        if len(found) == 1:
            block_elements[found[0]] = block
    records, evidence, diagnostics, coverage = [], {}, [], []
    selected_metrics = set(CONCEPTS.values() if metrics is None else metrics)
    if selected_metrics - set(CONCEPTS.values()):
        raise ValueError("unsupported_metric_mapping")
    for tag in tree.iter():
        concept = tag.get("name")
        if concept not in CONCEPTS or CONCEPTS[concept] not in selected_metrics:
            continue
        metric = CONCEPTS[concept]
        try:
            contexts, units = by_id.get(tag.get("contextref"), []), by_id.get(tag.get("unitref"), [])
            if len(contexts) != 1 or len(units) != 1:
                raise ValueError("ambiguous_context_or_unit")
            context = parse_context(contexts[0], entity_identifier=mapping.entity_identifier)
            dims = context["dimensions"]
            if metric == "capex_cash_payments":
                if dims:
                    continue
                entity = mapping.company_id
            else:
                if dims.get(mapping.segment_axis) != mapping.segment_member:
                    continue
                if set(dims) - {mapping.segment_axis, mapping.consolidation_axis}:
                    raise ValueError("unsupported_additional_dimensions")
                if mapping.consolidation_axis in dims and dims[mapping.consolidation_axis] != mapping.consolidation_member:
                    raise ValueError("unsupported_consolidation_member")
                entity = mapping.segment_entity_id
            period = context["period"]
            if period_kinds and period["kind"] not in period_kinds:
                continue
            number = parse_number(tag, units[0])
            ancestors = [tag, *tag.iterancestors()]
            block = next((block_elements[a] for a in ancestors if a in block_elements), None)
            if block is None or number["raw_value"] not in block["text"]:
                raise ValueError("unlocated_fact")
            eid = "ev-" + digest([manifest["source_snapshot_id"], tag.get("id"), concept, tag.get("contextref")])[:20]
            td = next((a for a in ancestors if local_name(a) in ("td", "th")), None)
            cell, headers = None, []
            if td is not None and block.get("table"):
                table = next(a for a in td.iterancestors() if local_name(a) == "table")
                if table not in grids:
                    grids[table] = cell_grid(table)
                cell = grids[table].get(td)
                if cell is None or not any(all(c[k] == cell[k] for k in ("row", "column", "text"))
                                           for c in block["table"]["cells"]):
                    raise ValueError("indexed_cell_mismatch")
                headers = validate_table_headers(block, cell, period)
            context_ids = {block["block_id"]}
            for group in reader.groups:
                if block["block_id"] in group["block_ids"]:
                    context_ids.update(group["block_ids"])
            ev = {"evidence_id": eid, "source_snapshot_id": manifest["source_snapshot_id"],
                  "source_sha256": digest(raw), "document_id": manifest["document_id"],
                  "index_id": reader.index["index_id"], "block_id": block["block_id"],
                  "text_hash": block["text_hash"], "quote": number["raw_value"], "cell": cell,
                  "verified_header_cells": headers,
                  "reported_page": block.get("reported_page"), "dom_path": block["dom_path"],
                  "fact_id": tag.get("id"), "context_ref": tag.get("contextref"), "unit_ref": tag.get("unitref"),
                  "concept": concept, "context_xml": html.tostring(contexts[0], encoding="unicode"),
                  "unit_xml": html.tostring(units[0], encoding="unicode"),
                  "context_block_ids": sorted(context_ids),
                  "source_url": manifest["source_url"], "number_metadata": number}
            evidence[eid] = ev
            basis = "reported_consolidated" if metric == "capex_cash_payments" else "reported_segment"
            record = {"record_type": "MetricObservation", "schema_version": VERSION,
                      "entity_id": entity, "metric": metric, "period": period,
                      "value_decimal": number["value_decimal"], "unit": "USD", "value_kind": "actual",
                      "dimensions": dims, "accounting_basis": basis, "concept": concept,
                      "available_at": manifest["filed_at"], "source_snapshot_id": manifest["source_snapshot_id"],
                      "evidence_ids": [eid], "quality": {"locator_match": True, "xbrl_context_parsed": True,
                      "table_header_match": True if headers else "not_applicable_to_narrative_fact",
                      "human_review": "pending", "semantic_scope": "declared_concepts_and_dimensions_only"}}
            if metric == "capex_cash_payments":
                record["definition"] = "Positive cash payments to acquire property, plant and equipment; displayed cash-flow outflow may be parenthesized. Not total investment or Cloud-only CapEx."
            record["series_key"] = "series-" + digest([entity, metric, dims, basis, "USD", "actual", period["kind"]])[:20]
            record["record_id"] = "obs-" + digest([VERSION, manifest["source_snapshot_id"], logical_key(record), record["value_decimal"]])[:20]
            records.append(record)
            coverage.append({"fact_id": tag.get("id"), "status": "extracted", "record_id": record["record_id"]})
        except (ValueError, KeyError, StopIteration) as exc:
            diagnostics.append({"fact_id": tag.get("id"), "concept": concept, "status": "unsupported",
                                "reason": str(exc) or type(exc).__name__})
    grouped = {}
    for record in records:
        key = record["record_id"]
        if key not in grouped:
            grouped[key] = record
        else:
            grouped[key]["evidence_ids"] = sorted(set(grouped[key]["evidence_ids"] + record["evidence_ids"]))
    conflicts = []
    keys = {}
    for record in grouped.values():
        keys.setdefault(logical_key(record), []).append(record)
    for members in keys.values():
        if len({r["value_decimal"] for r in members}) > 1:
            conflicts.append({"record_ids": [r["record_id"] for r in members], "status": "unresolved"})
    return {"schema_version": VERSION, "source_snapshot_id": manifest["source_snapshot_id"],
            "source_sha256": digest(raw), "index_id": reader.index["index_id"],
            "records": sorted(grouped.values(), key=lambda r: r["record_id"]), "evidence": evidence,
            "coverage": coverage, "diagnostics": diagnostics, "conflicts": conflicts,
            "mapping": mapping.model_dump(),
            "limits": ["Explicit issuer/segment mapping; calendar fiscal periods only", "Four explicitly mapped monetary concepts",
                       "No general taxonomy mapping, OCR, restatement resolution or exhaustive filing coverage"]}


class FinancialRecordPort:
    """Read-only records with explicit per-request missing/ambiguous status."""
    def __init__(self, records):
        self.records = copy.deepcopy(records)

    def query(self, *, entity_id, metric, start, end, as_of):
        cutoff = date.fromisoformat(as_of)
        end_date = date.fromisoformat(end)
        start_date = date.fromisoformat(start) if start is not None else None
        if start_date is not None and start_date > end_date:
            raise ValueError("invalid_query_period")
        hits = [r for r in self.records if r["entity_id"] == entity_id and r["metric"] == metric
                and r["period"]["start"] == (start_date.isoformat() if start_date else None)
                and r["period"]["end"] == end_date.isoformat()
                and date.fromisoformat(r["available_at"]) <= cutoff]
        # Multiple source versions are not silently preferred or overwritten.
        return {"status": "matched" if len(hits) == 1 else "missing" if not hits else "ambiguous",
                "records": copy.deepcopy(hits), "query": {"entity_id": entity_id, "metric": metric,
                "start": start, "end": end, "as_of": as_of}}


def compute_ytd_difference(current, previous):
    a, b = current["period"], previous["period"]
    if any(current[k] != previous[k] for k in ("entity_id", "metric", "unit", "dimensions", "accounting_basis", "value_kind", "concept")):
        raise ValueError("incompatible_operands")
    if (a["kind"] != "ytd" or b["kind"] not in ("quarter", "ytd") or not a["start"]
            or a["start"] != b["start"] or not a["start"].endswith("-01-01")
            or a.get("months", 0) - b.get("months", 0) != 3):
        raise ValueError("not_adjacent_ytd_periods")
    start = (date.fromisoformat(b["end"]) + timedelta(days=1)).isoformat()
    difference = Decimal(current["value_decimal"]) - Decimal(previous["value_decimal"])
    if current["metric"] == "capex_cash_payments" and difference < 0:
        raise ValueError("negative_payment_difference_requires_review")
    record = {"record_type": "ComputedFact", "formula_id": "ytd_difference-v1",
              "entity_id": current["entity_id"], "metric": current["metric"], "unit": current["unit"],
              "period": {"kind": "quarter", "start": start, "end": a["end"]},
              "value_decimal": format(difference, "f"),
              "operand_record_ids": [current["record_id"], previous["record_id"]],
              "available_at": max(current["available_at"], previous["available_at"]),
              "comparability": "same definition/dimensions and adjacent calendar YTD; restatements require separate review"}
    record["record_id"] = "calc-" + digest(record)[:20]
    return record
