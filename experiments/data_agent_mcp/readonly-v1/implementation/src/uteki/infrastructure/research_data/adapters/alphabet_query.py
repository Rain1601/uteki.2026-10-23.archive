"""Alphabet-only adapters for reviewed financial records and one frozen call.

No model calls. Corrections are bounded, quote-checked overlays, not a general
semantic normalizer. Original records and source evidence are always retained.
"""
from __future__ import annotations

from decimal import Decimal
import re

from uteki.domain.research_data.query_contract import Period, ResearchRecord
from ..financial_records import digest
from .alphabet_financial import ALPHABET_FINANCIAL_MAPPING

CLOUD_AXIS = ALPHABET_FINANCIAL_MAPPING.segment_axis
CLOUD_MEMBER = ALPHABET_FINANCIAL_MAPPING.segment_member
CONSOLIDATION_AXIS = ALPHABET_FINANCIAL_MAPPING.consolidation_axis

METRICS = {
    "revenue": ("收入 / Revenue", "Reported revenue; segment scope is separate from consolidated scope.", "USD", None),
    "operating_income": ("营业利润 / Operating income", "Reported operating income on the stated entity/basis.", "USD", None),
    "capex_cash_payments": ("固定资产现金支出 / PP&E cash payments", "Positive cash payments for PP&E; not automatically equivalent to management CapEx.", "USD", None),
    "remaining_performance_obligations": ("剩余履约义务 / RPO", "Reported remaining performance obligations; instant balance, not revenue.", "USD", None),
    "capex_guidance": ("资本开支指引 / CapEx guidance", "Management CapEx range; repeated speakers are disclosures, not additive forecasts.", "USD", None),
    "investment_rationale": ("投资理由 / Investment rationale", "Attributed management explanation, not established causation.", None, None),
    "cloud_growth_outlook": ("Cloud 增长展望 / Cloud outlook", "Qualitative future growth; unresolved target dates remain explicit.", None, None),
    "infrastructure_expense_pressure": ("基础设施费用压力 / Expense pressure", "Attributed depreciation and operating expense pressure.", None, None),
    "depreciation": ("折旧实际值 / Actual depreciation", "Historical reported depreciation; separate from future outlook.", "USD", None),
    "depreciation_outlook": ("折旧展望 / Depreciation outlook", "Qualitative expected depreciation growth, not a forecast amount.", None, None),
    "capex_machine_share": ("机器投资比例 / Machine share", "Management description of historical investment composition.", "percent", "total_investment"),
    "capex_long_duration_share": ("长期资产投资比例 / Long-duration share", "Data center and networking assets as a share of investment.", "percent", "total_investment"),
    "investment_mix_outlook": ("投资构成展望 / Investment mix outlook", "Qualitative future similarity, without invented exact shares.", None, "total_investment"),
    "building_useful_life": ("建筑使用寿命 / Building useful life", "Modal possible life; does not describe every component or guarantee a minimum.", "years", None),
    "cloud_ml_compute_share": ("Cloud ML 算力比例 / Cloud ML compute share", "Share of ML compute allocated to Cloud, NOT share of total CapEx.", "percent", "total_ml_compute"),
    "gross_profit": ("毛利润 / Gross profit", "Known metric definition, but not extracted by this pilot.", "USD", None),
}


def metric_catalog():
    return {key: {"metric_id": key, "label": row[0], "definition": row[1], "unit": row[2],
                  "denominator": row[3], "definition_version": "pilot-v1", "aggregation": "no_implicit_sum",
                  "aliases": [row[0].split(" / ")[0], row[0].split(" / ")[-1], key]}
            for key, row in METRICS.items()}


def from_financial(record, artifact, *, company_id):
    if company_id != "alphabet":
        raise ValueError("Alphabet financial adapter company mismatch")
    p = record["period"]
    dimensions = record["dimensions"]
    if record["entity_id"] == "google-cloud":
        if (dimensions.get(CLOUD_AXIS) != CLOUD_MEMBER or set(dimensions) - {CLOUD_AXIS, CONSOLIDATION_AXIS}
                or dimensions.get(CONSOLIDATION_AXIS, "us-gaap:OperatingSegmentsMember") != "us-gaap:OperatingSegmentsMember"
                or record["accounting_basis"] != "reported_segment"):
            raise ValueError("unsupported Cloud financial dimensions")
        # Revenue and operating income use different XBRL grouping axes for the
        # same named segment. Map only the explicitly supported segment member.
        dimensions = {"reporting_segment": "google-cloud"}
    elif record["entity_id"] != "alphabet" or dimensions or record["accounting_basis"] != "reported_consolidated":
        raise ValueError("unsupported consolidated financial dimensions")
    return ResearchRecord(
        record_id=record["record_id"], record_type="metric", entity_id=record["entity_id"],
        metric_id=record["metric"], period=Period(kind=p["kind"], start=p["start"], end=p["end"]),
        value_kind="actual", value_decimal=record["value_decimal"], value_relation="eq", unit=record["unit"],
        accounting_basis=record["accounting_basis"], dimensions=dimensions,
        available_at=record["available_at"], source_snapshot_id=record["source_snapshot_id"],
        evidence_ids=record["evidence_ids"], summary=f"{record['entity_id']} {record['metric']}",
        origin={"artifact": artifact, "record_id": record["record_id"], "raw_record": record},
        normalization_notes=("Deterministic source values retained; candidate status is not approval.",
                             "Declared XBRL segment/grouping axes mapped to reporting scope; original dimensions retained in origin."),
    )


def parse_period(label):
    if label is None:
        return None
    if re.fullmatch(r"FY\d{4}", label):
        return Period(kind="year", start=f"{label[2:]}-01-01", end=f"{label[2:]}-12-31")
    raise ValueError("unsupported prompt period; never infer dates from summary")


def from_prompt(record, *, artifact, ordinal, source, blocks):
    # These semantic repairs were reviewed only against this exact source.
    # A new call must use a separately reviewed adapter, even if wording matches.
    if (source["company_id"] != "alphabet" or source["source_sha256"] !=
            "8e3678d5138e30a0ee9065cdf54ae790937b9e27194ffae223a0c438c4928cd5"
            or record["entity"] not in ("alphabet", "google-cloud")):
        raise ValueError("reviewed Alphabet call adapter source/entity mismatch")
    evidence = {}

    def cite(ref, role):
        block = blocks[ref["block_id"]]
        if not ref["quote"] or ref["quote"] not in block["text"]:
            raise ValueError("nonexact_prompt_evidence")
        start = block["text"].index(ref["quote"])
        eid = "qev-" + digest([source["source_snapshot_id"], ref["block_id"], start, ref["quote"]])[:24]
        evidence[eid] = {"evidence_id": eid, "source_snapshot_id": source["source_snapshot_id"],
                         "source_sha256": source["source_sha256"], "index_id": source["index_id"],
                         "document_id": source["document_id"], "block_id": ref["block_id"],
                         "text_hash": block["text_hash"], "quote": ref["quote"], "start": start,
                         "end": start + len(ref["quote"]), "speaker": block.get("speaker"),
                         "speaker_role": block.get("speaker_role"), "pdf_page": block.get("pdf_page"),
                         "bbox": block.get("bbox"), "source_url": source["source_url"]}
        if role == "evidence" and (block.get("speaker_role") != "management" or block.get("speaker") != record["speaker"]):
            raise ValueError("prompt_speaker_mismatch")
        if role == "question" and block.get("speaker_role") != "analyst":
            raise ValueError("invalid_question_reference")
        return eid

    eids = tuple(cite(ref, "evidence") for ref in record["evidence"])
    qids = tuple(cite(ref, "qualifier") for ref in record["qualifiers"])
    questions = tuple(cite({"block_id": bid, "quote": blocks[bid]["text"]}, "question") for bid in record["question_refs"])
    metric = "depreciation" if record["metric"] == "depreciation_outlook" and record["kind"] == "financial" else record["metric"]
    if metric not in METRICS:
        raise ValueError("unknown prompt metric")
    kind = {"financial": "actual", "guidance": "management_guidance", "statement": "attributed_statement"}[record["kind"]]
    relation = "qualitative" if record["value"] is None else "range" if record["upper"] is not None else "unresolved"
    value, upper, unit = record["value"], record["upper"], record["unit"]
    if unit in ("USD_millions", "USD_billions"):
        scale = Decimal(10) ** (6 if unit == "USD_millions" else 9)
        value = str(Decimal(value) * scale)
        upper = str(Decimal(upper) * scale) if upper is not None else None
        unit = "USD"
        if record["kind"] == "financial":
            relation = "eq"
    text = " ".join(ref["quote"] for ref in record["evidence"])
    notes = ["Explicit quote-checked pilot normalization; original model record preserved."]
    modality = None
    if metric == "cloud_ml_compute_share":
        if "just over half of our ML compute" not in text or value != "50":
            raise ValueError("unsupported ML allocation wording")
        relation, modality = "gt", "expected"
        notes.append("Threshold 50 is not an exact forecast; near-half wording remains in evidence.")
    elif metric == "building_useful_life":
        if "could be 40 years or longer" not in text or value != "40":
            raise ValueError("unsupported building life wording")
        relation, modality = "gte", "could"
    elif metric in ("capex_machine_share", "capex_long_duration_share"):
        if record["period"] != "FY2025":
            raise ValueError("future shares cannot be promoted to exact forecasts")
        full_text = " ".join(blocks[ref["block_id"]]["text"] for ref in record["evidence"])
        if "Approximately 60%" not in full_text or "40%" not in full_text:
            raise ValueError("unsupported investment composition wording")
        expected = "60" if metric == "capex_machine_share" else "40"
        if value != expected or unit != "percent" or upper is not None:
            raise ValueError("investment composition value disagrees with reviewed quote")
        relation = "approx"
        notes.append("Approximation from the full investment-composition statement is retained.")
    elif metric == "cloud_growth_outlook":
        kind, modality = "management_guidance", "expected"
        notes.append("Future outlook typed as guidance; target dates unresolved, not guessed.")
    common = dict(record_id="qr-" + digest([artifact, ordinal, record])[:24],
                  record_type="metric" if record["kind"] == "financial" else "guidance" if kind == "management_guidance" else "statement",
                  entity_id=record["entity"], metric_id=metric, period=parse_period(record["period"]),
                  period_resolution="resolved" if record["period"] else "not_applicable" if metric in ("building_useful_life", "investment_rationale") else "unresolved",
                  value_kind=kind, value_decimal=value, upper_decimal=upper, value_relation=relation,
                  unit=unit, denominator=METRICS[metric][3], modality=modality,
                  accounting_basis="management_disclosure", available_at=source["available_at"],
                  source_snapshot_id=source["source_snapshot_id"], evidence_ids=eids,
                  qualifier_evidence_ids=qids, question_evidence_ids=questions,
                  summary=record["summary"], speaker=record["speaker"],
                  origin={"artifact": artifact, "record_index": ordinal, "raw_record": record},
                  normalization_notes=tuple(notes))
    records = [ResearchRecord(**common)]
    # A narrowly supported extra record makes the future qualitative statement queryable.
    if metric == "capex_machine_share":
        anchor = next((blocks[ref["block_id"]] for ref in record["evidence"]
                       if "it's going to be fairly similar in 2026" in blocks[ref["block_id"]]["text"]), None)
        if anchor:
            ref = {"block_id": anchor["block_id"], "quote": "it's going to be fairly similar in 2026"}
            linked = cite(ref, "evidence")
            records.append(ResearchRecord(**{**common, "record_id": "qr-" + digest([common["record_id"], "future_mix"])[:24],
                "record_type": "guidance", "metric_id": "investment_mix_outlook", "period": parse_period("FY2026"), "period_resolution": "resolved",
                "value_kind": "management_guidance", "value_decimal": None, "upper_decimal": None,
                "value_relation": "qualitative", "unit": None, "modality": "expected", "evidence_ids": (linked,),
                "qualifier_evidence_ids": eids, "summary": ref["quote"],
                "normalization_notes": ("Bounded literal normalization of explicit future year/similarity; no numeric forecast.",)}))
    return records, evidence
