"""Offline synthetic coverage for annual extraction; no provider calls or real issuers."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from uteki.agents.runtime.deepseek_model import json_instructions
from uteki.domain.research_data.query_contract import EXACT_SOURCE_PERIOD_VERSION, SOURCE_PERIOD_VERSION
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet, run_direct_extraction
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.financial_records import digest


class AnnualExtractionSupportTests(unittest.TestCase):
    def fixture(self, unit="TWD_millions", value="12.5", metric="revenue"):
        base_unit = unit.split("_")[0]
        company, source = "sec-0000009017", "synthetic-week-filing"
        period = {"kind": "year", "start": "2031-01-05", "end": "2032-01-03", "basis": "source"}
        label = "Revenue" if metric == "revenue" else "Common shares"
        text = f"{label} for the 52-week reporting period: {value} {unit}."
        packet = {
            "packet_id": "synthetic-packet", "company_id": company,
            "record_schema_version": EXACT_SOURCE_PERIOD_VERSION,
            "source": {"company_id": company, "source_snapshot_id": source,
                       "source_sha256": digest(text.encode()), "source_url": "https://example.invalid/annual",
                       "available_at": "2032-03-01", "index_id": "synthetic-index"},
            "blocks": [{"block_id": "annual-row", "text": text, "text_hash": digest(text.encode())}],
            "entity_catalog": [{"entity_id": company, "company_id": company,
                                "source_snapshot_id": source, "label": "Synthetic Foundry"}],
            "metric_catalog": {metric: {"metric_id": metric, "label": label, "unit": base_unit,
                                        "aliases": [], "definition_version": "synthetic-v1",
                                        "denominator": None, "aggregation": "no_implicit_sum"}},
            "period_catalog": [{"period_id": "week-year", "label": "52-week reporting period",
                                "company_id": company, "source_snapshot_id": source, "period": period}],
            "task": {"company_id": company, "source_snapshot_ids": [source],
                     "knowledge_cutoff": "2032-03-02"},
        }
        draft = {"draft_id": "row-1", "kind": "financial", "entity": "Synthetic Foundry",
                 "entity_id": company, "metric": label, "metric_id": metric,
                 "period": "52-week reporting period", "period_id": "week-year",
                 "value": value, "value_relation": "eq", "unit": unit,
                 "accounting_basis": "reported_consolidated", "summary": text,
                 "evidence": [{"block_id": "annual-row", "quote": text}]}
        return packet, {"records": [draft], "relations": [], "gaps": []}

    def test_twd_only_scales_with_no_currency_conversion(self):
        for unit, expected in (("TWD", "12.5"), ("TWD_thousands", "12500.0"),
                               ("TWD_millions", "12500000.0"), ("TWD_billions", "12500000000.0")):
            with self.subTest(unit=unit):
                packet, extraction = self.fixture(unit)
                original = deepcopy((packet, extraction))
                result = normalize_direct_candidates(extraction, packet)
                self.assertEqual(result["unresolved"], [])
                self.assertEqual((result["records"][0]["value_decimal"], result["records"][0]["unit"]),
                                 (expected, "TWD"))
                self.assertEqual(result["records"][0]["origin"]["raw"]["unit"], unit)
                self.assertEqual((packet, extraction), original)

    def test_usd_does_not_silently_join_twd_metric(self):
        packet, extraction = self.fixture("USD_millions")
        packet["metric_catalog"]["revenue"]["unit"] = "TWD"
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result["records"], [])
        self.assertIn("metric_unit_mismatch", {g["reason"] for g in result["unresolved"]})
        self.assertEqual(result["raw_candidates"][0]["unit"], "USD_millions")

    def test_usd_remains_usd_when_catalog_agrees(self):
        packet, extraction = self.fixture("USD_millions")
        row = normalize_direct_candidates(extraction, packet)["records"][0]
        self.assertEqual((row["value_decimal"], row["unit"]), ("12500000.0", "USD"))

    def test_share_scaling_preserves_share_unit(self):
        for unit, expected in (("shares", "12.5"), ("shares_thousands", "12500.0"),
                               ("shares_millions", "12500000.0")):
            with self.subTest(unit=unit):
                packet, extraction = self.fixture(unit, metric="common_shares")
                row = normalize_direct_candidates(extraction, packet)["records"][0]
                self.assertEqual((row["value_decimal"], row["unit"]), (expected, "shares"))

    def test_company_and_period_scope_are_not_inferred(self):
        for catalog in ("entity_catalog", "period_catalog"):
            packet, extraction = self.fixture()
            packet[catalog][0]["company_id"] = "sec-0000009018"
            with self.subTest(catalog=catalog), self.assertRaisesRegex(ValueError, "catalog outside"):
                normalize_direct_candidates(extraction, packet)
        for field, value, reason in (("entity_id", "sec-0000009018", "unresolved_entity"),
                                     ("period_id", "unrequested-year", "unresolved_period")):
            packet, extraction = self.fixture()
            extraction["records"][0][field] = value
            result = normalize_direct_candidates(extraction, packet)
            self.assertEqual(result["records"], [])
            self.assertIn(reason, {g["reason"] for g in result["unresolved"]})

    def test_week_period_requires_explicit_v05(self):
        packet, extraction = self.fixture()
        row = normalize_direct_candidates(extraction, packet)["records"][0]
        self.assertEqual(row["schema_version"], EXACT_SOURCE_PERIOD_VERSION)
        self.assertEqual(row["period"], packet["period_catalog"][0]["period"])
        packet["record_schema_version"] = SOURCE_PERIOD_VERSION
        with self.assertRaisesRegex(ValueError, "complete month"):
            normalize_direct_candidates(extraction, packet)
        packet.pop("record_schema_version")
        with self.assertRaisesRegex(ValueError, "complete month"):
            normalize_direct_candidates(extraction, packet)

    def prepared_source(self, root):
        packet, extraction = self.fixture()
        source = packet["source"]
        text = packet["blocks"][0]["text"]
        raw = f"<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>{text}</p></body></html>".encode()
        (root / "filing.html").write_bytes(raw)
        company = {"company_id": packet["company_id"], "cik": "0000009017",
                   "name": "Synthetic Foundry", "symbol": "SYNW"}
        materialize_sources({"company": company, "as_of": "2032-03-02", "documents": [{
            "source_id": source["source_snapshot_id"], "company_id": company["company_id"],
            "source_url": source["source_url"], "form": "10-K", "filed_at": "2032-03-01",
            "period_end": "2032-01-03", "content_sha256": digest(raw), "path": "filing.html",
            "mime_type": "text/html", "status": "frozen"}]}, root, root / "baseline")
        stored = json.loads((root / "baseline/sources.json").read_text())[0]
        blocks = [json.loads(line) for line in (root / "baseline" / stored["index_folder"] / "blocks.jsonl").read_text().splitlines()]
        block = next(b for b in blocks if b["text"] == text)
        extraction["records"][0]["evidence"][0]["block_id"] = block["block_id"]
        job = {"company_id": company["company_id"], "source_snapshot_id": source["source_snapshot_id"],
               "as_of": "2032-03-02", "task": "Extract this explicitly selected synthetic source row.",
               "block_ids": [block["block_id"]], "entity_catalog": packet["entity_catalog"],
               "period_catalog": packet["period_catalog"], "record_schema_version": EXACT_SOURCE_PERIOD_VERSION,
               "normalization_config": {"version": "synthetic-v1", "metric_catalog": packet["metric_catalog"]},
               "prompt": {"version": "synthetic-prompt-v1", "text": "Extract only provided synthetic evidence."}}
        return job, extraction, company

    def test_projection_keeps_company_week_dates_and_v05_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, extraction, company = self.prepared_source(root)
            before = (root / "baseline/manifest.json").read_bytes()
            async def scripted(packet):
                return extraction
            result = asyncio.run(run_direct_extraction(root / "baseline", job, root / "run",
                                                       strategy="direct", model_call=scripted))
            self.assertEqual(result["plan_origin"], "scripted_fixture")
            manifest = json.loads((root / "run/dataset/manifest.json").read_text())
            self.assertEqual(manifest["company"], company)
            self.assertEqual(manifest["schema_version"], EXACT_SOURCE_PERIOD_VERSION)
            self.assertEqual((root / "baseline/manifest.json").read_bytes(), before)
            connection = duckdb.connect(str(root / "run/dataset/research.duckdb"), read_only=True)
            try:
                rows = connection.execute("SELECT payload FROM observations").fetchall()
            finally:
                connection.close()
            row = json.loads(rows[0][0])
            self.assertEqual((row["schema_version"], row["unit"], row["value_decimal"]),
                             (EXACT_SOURCE_PERIOD_VERSION, "TWD", "12500000.0"))
            self.assertEqual(row["period"]["start"], "2031-01-05")
            schema = json.loads((root / "run/dataset/schemas/record.schema.json").read_text())
            self.assertEqual(schema["properties"]["schema_version"]["const"], EXACT_SOURCE_PERIOD_VERSION)
            with self.assertRaises(ValueError):
                build_extraction_packet(root / "baseline", {**job, "company_id": "sec-0000009018"})
            with self.assertRaises(ValueError):
                build_extraction_packet(root / "baseline", {**job, "record_schema_version": SOURCE_PERIOD_VERSION})

    def test_prompt_and_runtime_settings_reach_gateway_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, extraction, _ = self.prepared_source(root)
            received = {}
            class NoNetworkReviewer:
                def __init__(self, provider, model, **kwargs):
                    received.update(provider=provider, model=model, **kwargs)
                    self.frozen_config = {"prompt": kwargs["prompt"],
                        "prompt_sha256": digest(kwargs["prompt"]),
                        "output_schema": kwargs["output_schema"].model_json_schema()}
                async def review(self, packet):
                    received["packet"] = packet
                    return extraction
                async def aclose(self):
                    pass
                def snapshot_usage(self):
                    return {"test_double": True, "requests": 0}
            config = {"provider": "deepseek", "model": "synthetic-no-network",
                      "budget_ledger": str(root / "ledger.json"), "budget_usd": None,
                      "max_requests_total": None, "reasoning_effort": "high", "max_request_bytes": 1500000}
            with patch("uteki.agents.data_query.record_review_model.SdkRecordReviewer", NoNetworkReviewer):
                asyncio.run(run_direct_extraction(root / "baseline", job, root / "run", strategy="direct",
                                                   model_config=config, credentials_root=root))
            self.assertEqual(received["reasoning_effort"], "high")
            self.assertEqual(received["max_request_bytes"], 1500000)
            self.assertEqual(received["prompt"], job["prompt"]["text"])
            prompt = json.loads((root / "run/prompt.json").read_text())
            self.assertEqual(prompt["sha256"], digest(received["prompt"]))
            effective = json.loads((root / "run/system-prompt-effective.json").read_text())
            self.assertEqual(effective["text"], json_instructions(received["prompt"], received["output_schema"].model_json_schema()))


if __name__ == "__main__":
    unittest.main()
