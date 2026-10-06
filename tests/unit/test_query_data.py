import copy
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from pydantic import ValidationError

from uteki.domain.research_data.query_contract import DataQuery, Period, ResearchRecord
from uteki.infrastructure.research_data.query_dataset import build_dataset
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.adapters.alphabet_query import from_financial, from_prompt

ROOT = Path(__file__).resolve().parents[2]


def period(year, kind="quarter"):
    return {"kind": kind, "start": f"{year}-04-01" if kind == "quarter" else f"{year}-01-01",
            "end": f"{year}-12-31" if kind == "year" else f"{year}-06-30"}


class QueryDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.dataset = Path(cls.temp.name) / "dataset"
        cls.manifest = build_dataset(ROOT, cls.dataset, spec=ROOT / "experiments/data_agent_query/specs/alphabet-reviewed-v1.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)

    def query(self, **kwargs):
        return {"query_id": "test", "snapshot_id": self.port.snapshot_id, "knowledge_cutoff": "2026-09-22",
                "include_candidates": True, **kwargs}

    def record(self, metric="revenue", year=2026, **kwargs):
        return {"entity_id": "google-cloud", "metric_id": metric, "period": period(year), **kwargs}

    def test_schema_and_source_discovery_are_explicit(self):
        schema = self.port.get_schema(["cloud_ml_compute_share"])
        self.assertEqual(set(schema["metrics"]), {"cloud_ml_compute_share"})
        self.assertEqual(schema["metrics"]["cloud_ml_compute_share"]["denominator"], "total_ml_compute")
        value = next(c for c in schema["physical_tables"]["observations"] if c["name"] == "value_decimal")
        self.assertEqual(value["type"], "DECIMAL(38,12)")
        self.assertEqual(schema["query"], json.loads((self.dataset / "schemas/query.schema.json").read_text()))
        discovery = self.port.discover_data(knowledge_cutoff="2026-02-04", include_candidates=True)
        self.assertEqual([s["form"] for s in discovery["sources"]], ["EARNINGS_CALL"])
        self.assertFalse(any(c["metric_id"] == "revenue" for c in discovery["coverage"]))

    def test_quarter_and_half_year_are_not_interchangeable(self):
        q = self.query(records=[self.record(), self.record(period=period(2026, "ytd"))])
        result = self.port.query_data(q)
        self.assertEqual(result["status"], "complete")
        self.assertEqual({r["period"]["kind"]: r["value_decimal"] for r in result["records"]},
                         {"quarter": "24768000000", "ytd": "44796000000"})
        self.assertTrue(all(t["parameters"] for t in result["trace"] if t["tool"] == "sql"))

    def test_document_schema_requires_explicit_company(self):
        document = self.port.get_schema()["query"]["$defs"]["DocumentRequest"]
        self.assertIn("company_id", document["required"])
        self.assertNotIn("default", document["properties"]["company_id"])
        from uteki.domain.research_data.query_contract import VERSION, export_query_schema
        self.assertEqual(self.port.get_schema()["query"], export_query_schema(DataQuery, version=VERSION))

    def test_document_company_missing_or_blank_rejected_before_retrieval(self):
        document = {"form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": "just over half"}
        invalid = [document, *[{**document, "company_id": company} for company in (None, "", " \t\n")]]
        with patch.object(self.port, "_reader") as reader:
            for request in invalid:
                with self.subTest(request=request), self.assertRaises(ValidationError) as error:
                    self.port.query_data(self.query(documents=[request]))
                self.assertEqual(error.exception.errors()[0]["loc"], ("documents", 0, "company_id"))
            reader.assert_not_called()

    def test_document_other_company_never_falls_back_to_alphabet(self):
        document = {"company_id": "microsoft", "form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": "just over half"}
        with patch.object(self.port, "_reader") as reader:
            result = self.port.query_data(self.query(documents=[document]))
            reader.assert_not_called()
        self.assertEqual(result["status"], "unanswerable")
        self.assertEqual(result["documents"][0]["status"], "source_missing")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["evidence"], {})
        document["company_id"] = "alphabet"
        self.assertEqual(self.port.query_data(self.query(documents=[document]))["status"], "complete")

    def test_older_contract_snapshot_requires_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp)
            manifest = {**self.manifest, "schema_version": "research-query-v0.1"}
            (old / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "expected research-query-v0.3.*Build a new dataset"):
                QueryDataPort(old)

    def test_exact_financial_calculations_and_dependency_evidence(self):
        calculations = [{"formula_id": "operating_margin", "entity_id": "google-cloud", "periods": [period(y)]} for y in (2025, 2026)]
        calculations += [{"formula_id": f, "entity_id": "google-cloud", "periods": [period(2025), period(2026)]}
                         for f in ("revenue_yoy", "operating_income_yoy", "operating_margin_delta_pp")]
        result = self.port.query_data(self.query(calculations=calculations))
        self.assertEqual(result["status"], "complete")
        self.assertEqual([r["display_decimal"] for r in result["computed_facts"]], ["20.74", "35.59", "81.80", "211.89", "14.84"])
        self.assertEqual(result["computed_facts"][0]["value_decimal"], "20.742807")
        self.assertEqual(result["computed_facts"][-1]["value_decimal"], "14.843433")
        ids = {r["record_id"] for r in result["records"]}
        for c in result["computed_facts"]:
            self.assertTrue(set(c["operand_record_ids"]) <= ids)
        self.assertEqual(len(ids), 4)

    def test_cutoff_does_not_leak_values_or_evidence(self):
        result = self.port.query_data(self.query(records=[self.record()], knowledge_cutoff="2026-07-22"))
        self.assertEqual(result["status"], "unanswerable")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["evidence"], {})
        self.assertEqual(result["gaps"][0]["reason"], "not_available_at_cutoff")

    def test_candidate_access_and_snapshot_binding(self):
        result = self.port.query_data(self.query(records=[self.record()], include_candidates=False))
        self.assertEqual(result["gaps"][0]["reason"], "quality_filtered")
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            self.port.query_data(self.query(records=[self.record()], snapshot_id="other"))

    def test_missing_metric_is_not_not_disclosed(self):
        result = self.port.query_data(self.query(records=[self.record("gross_profit")]))
        self.assertEqual(result["selections"][0]["status"], "source_present_unprocessed")
        result = self.port.query_data(self.query(records=[self.record("made_up_metric")]))
        self.assertEqual(result["selections"][0]["status"], "unsupported")

    def test_ambiguous_values_block_calculation(self):
        original = self.port._sql

        def conflict(sql, params, trace):
            rows = original(sql, params, trace)
            if params[1] == "revenue":
                row = json.loads(rows[0][0])
                other = {**row, "record_id": row["record_id"] + "-conflict", "value_decimal": "1"}
                return rows + [(json.dumps(other),)]
            return rows

        with patch.object(self.port, "_sql", side_effect=conflict):
            result = self.port.query_data(self.query(calculations=[{"formula_id": "operating_margin", "entity_id": "google-cloud", "periods": [period(2026)]}]))
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["computed_facts"], [])
        self.assertIn("operand_missing_or_ambiguous", [g["reason"] for g in result["gaps"]])

    def test_repeated_guidance_is_not_added(self):
        result = self.port.query_data(self.query(records=[self.record("capex_guidance", entity_id="alphabet", period=period(2026, "year"), value_kind="management_guidance")]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["selections"][0]["occurrence_count"], 2)
        self.assertEqual({r["value_decimal"] for r in result["records"]}, {"175000000000"})
        self.assertEqual({r["upper_decimal"] for r in result["records"]}, {"185000000000"})
        self.assertEqual(len({r["speaker"] for r in result["records"]}), 2)

    def test_ml_allocation_retains_comparison_and_denominator(self):
        result = self.port.query_data(self.query(records=[self.record("cloud_ml_compute_share", period=period(2026, "year"), value_kind="management_guidance")]))
        r = result["records"][0]
        self.assertEqual((r["value_decimal"], r["value_relation"], r["denominator"]), ("50", "gt", "total_ml_compute"))
        self.assertEqual(r["origin"]["raw_record"]["value"], "50")
        self.assertTrue(any("just over half" in ev["quote"] for ev in result["evidence"].values()))

    def test_future_similarity_is_independently_queryable_without_numbers(self):
        result = self.port.query_data(self.query(records=[self.record("investment_mix_outlook", entity_id="alphabet", period=period(2026, "year"), value_kind="management_guidance")]))
        self.assertEqual(result["status"], "complete")
        r = result["records"][0]
        self.assertEqual(r["value_relation"], "qualitative")
        self.assertIsNone(r["value_decimal"])
        self.assertEqual(r["summary"], "it's going to be fairly similar in 2026")

    def test_modal_life_and_unresolved_future_date_are_not_overstated(self):
        result = self.port.query_data(self.query(records=[self.record("building_useful_life", entity_id="alphabet", period=None, value_kind="attributed_statement")]))
        self.assertEqual(result["records"][0]["modality"], "could")
        self.assertEqual(result["records"][0]["value_relation"], "gte")
        self.assertEqual(result["records"][0]["period_resolution"], "not_applicable")
        self.assertEqual(result["status"], "complete")
        result = self.port.query_data(self.query(records=[self.record("cloud_growth_outlook", period=None, value_kind="management_guidance")]))
        self.assertEqual(result["status"], "partial")
        self.assertIn("target_period_unresolved", [g["reason"] for g in result["gaps"]])

    def test_mixed_guidance_query_reads_conditions(self):
        q = self.query(records=[self.record("capex_guidance", entity_id="alphabet", period=period(2026, "year"), value_kind="management_guidance")],
                       documents=[{"company_id": "alphabet", "form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": "timing of cash payments"}])
        result = self.port.query_data(q)
        self.assertEqual(result["status"], "complete")
        text = " ".join(b["text"] for c in result["documents"][0]["contexts"] for b in c["blocks"])
        self.assertIn("$175 billion to $185 billion", text)
        self.assertIn("availability of supply", text)
        self.assertIn("pricing of components", text)
        self.assertIn("timing of cash payments", text)

    def test_document_read_preserves_whole_qa(self):
        result = self.port.query_data(self.query(documents=[{"company_id": "alphabet", "form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": "just over half"}]))
        context = result["documents"][0]["contexts"][0]
        source = next(s for s in self.port.sources if s["form"] == "EARNINGS_CALL")
        reader = self.port._reader(source)
        expected = [b["block_id"] for b in reader.blocks if b.get("exchange_id") == "qa-06"]
        self.assertEqual(context["block_ids"], expected)
        self.assertTrue(any(b.get("speaker_role") == "analyst" for b in context["blocks"]))

    def test_absent_call_and_no_keyword_match_are_different(self):
        q = self.query(documents=[{"company_id": "alphabet", "form": "EARNINGS_CALL", "period_end": "2026-06-30", "phrase": "Cloud"}])
        result = self.port.query_data(q)
        self.assertEqual(result["documents"][0]["status"], "source_missing")
        q["documents"][0].update(period_end="2025-12-31", phrase="not-a-real-disclosure")
        result = self.port.query_data(q)
        self.assertEqual(result["documents"][0]["status"], "no_literal_match")
        self.assertFalse(result["documents"][0]["not_disclosed"])

    def test_search_limit_is_partial_and_empty_phrase_rejected(self):
        result = self.port.query_data(self.query(documents=[{"company_id": "alphabet", "form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": "Cloud", "limit": 1}]))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["documents"][0]["status"], "limited")
        with self.assertRaises(ValidationError):
            self.port.query_data(self.query(documents=[{"company_id": "alphabet", "form": "EARNINGS_CALL", "period_end": "2025-12-31", "phrase": " "}]))

    def test_unresolved_natural_language_and_arbitrary_sql_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.port.query_data(self.query(question="what was revenue?"))
        with self.assertRaises(ValidationError):
            self.port.query_data(self.query(records=[self.record()], sql="DROP TABLE observations"))
        result = self.port.query_data(self.query(records=[self.record(entity_id="google-cloud' OR 1=1 --")]))
        self.assertEqual(result["selections"][0]["status"], "unsupported")
        self.assertEqual(result["records"], [])
        with self.assertRaises(duckdb.Error):
            self.port._db.execute("DELETE FROM observations")
        with self.assertRaises(duckdb.Error):
            self.port._db.execute("SELECT * FROM read_csv_auto('/etc/passwd')")

    def test_evidence_is_pinned_and_obeys_cutoff(self):
        result = self.port.query_data(self.query(records=[self.record()]))
        eid = next(iter(result["evidence"]))
        got = self.port.get_evidence([eid], snapshot_id=self.port.snapshot_id, knowledge_cutoff="2026-09-22", include_candidates=True)
        self.assertEqual(got["evidence"][eid], result["evidence"][eid])
        with self.assertRaises(KeyError):
            self.port.get_evidence([eid], snapshot_id=self.port.snapshot_id, knowledge_cutoff="2026-07-22", include_candidates=True)
        with self.assertRaises(PermissionError):
            self.port.get_evidence([eid], snapshot_id=self.port.snapshot_id, knowledge_cutoff="2026-09-22")

    def test_valid_plan_with_many_evidence_ids_uses_bounded_batches(self):
        row = self.port.query_data(self.query(records=[self.record()]))["records"][0]
        row["evidence_ids"] = [f"e-{i}" for i in range(300)]
        selection = {"status": "matched", "record_ids": [row["record_id"]]}
        def evidence(ids, **kwargs):
            self.assertLessEqual(len(ids), 256)
            return {"evidence": {eid: {"evidence_id": eid} for eid in ids}}
        with patch.object(self.port, "_lookup", return_value=(selection, [row])), \
             patch.object(self.port, "get_evidence", side_effect=evidence) as reader:
            result = self.port.query_data(self.query(records=[self.record()]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["evidence"]), 300)
        self.assertEqual(reader.call_count, 2)

    def test_period_comparability_and_decimal_contract(self):
        result = self.port.query_data(self.query(calculations=[{"formula_id": "revenue_yoy", "entity_id": "google-cloud", "periods": [period(2025), period(2026, "ytd")]}]))
        self.assertEqual(result["computed_facts"], [])
        self.assertIn("incomparable_periods", [g["reason"] for g in result["gaps"]])
        with self.assertRaises(ValidationError):
            Period.model_validate({"kind": "quarter", "start": "2026-01-01", "end": "2026-06-30"})
        row = self.port.query_data(self.query(records=[self.record()]))["records"][0]
        for value in ("NaN", "Infinity", "1e26", "0.0000000000001", "not-a-decimal"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ResearchRecord.model_validate({**row, "value_decimal": value})

    def test_semantic_dimensions_map_only_declared_scope(self):
        result = self.port.query_data(self.query(records=[self.record(), self.record("operating_income")]))
        self.assertEqual([r["dimensions"] for r in result["records"]], [{"reporting_segment": "google-cloud"}] * 2)
        raw = copy.deepcopy(result["records"][0]["origin"]["raw_record"])
        raw["dimensions"]["new:GeographyAxis"] = "new:Europe"
        with self.assertRaisesRegex(ValueError, "unsupported Cloud financial dimensions"):
            from_financial(raw, "fault-injection", company_id="alphabet")

    def test_same_plan_via_python_and_cli_returns_same_result(self):
        q = self.query(calculations=[{"formula_id": "operating_margin", "entity_id": "google-cloud", "periods": [period(2025)]}])
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(json.dumps(q))
            process = subprocess.run([sys.executable, "scripts/query_research_data.py", "query", "--dataset", str(self.dataset), "--request", str(request)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), self.port.query_data(q))

    def test_build_refuses_to_overwrite_snapshot(self):
        with self.assertRaises(FileExistsError):
            build_dataset(ROOT, self.dataset, spec=ROOT / "experiments/data_agent_query/specs/alphabet-reviewed-v1.json")

    def test_new_input_build_is_explicit_and_preserves_old_snapshot(self):
        """Replay old-only -> old+new inputs; this is not automatic ingestion."""
        config = json.loads((ROOT / "experiments/data_agent_query/specs/alphabet-reviewed-v1.json").read_text())
        old_inputs = config['inputs'][:-1]
        old_sources = {entry['source_snapshot_id'] for entry in old_inputs}
        with tempfile.TemporaryDirectory(dir=ROOT / 'experiments/data_agent_query') as temp:
            root = Path(temp)
            old_spec = root / 'old.json'
            old_spec.write_text(json.dumps({**config, 'inputs': old_inputs,
                'sources': [source for source in config['sources'] if source['source_snapshot_id'] in old_sources]}))
            old = build_dataset(ROOT, root / 'old', spec=old_spec)
            old_bytes = {name: (root / 'old' / name).read_bytes() for name in old['files']}
            new_spec = root / 'new.json'
            new_spec.write_text(json.dumps(config))
            new = build_dataset(ROOT, root / 'new', spec=new_spec)
            old_rows = json.loads((root / 'old/records.json').read_text())['rows']
            new_rows = json.loads((root / 'new/records.json').read_text())['rows']
            self.assertLess(old['record_count'], new['record_count'])
            self.assertNotEqual(old['snapshot_id'], new['snapshot_id'])
            self.assertTrue({r['record_id'] for r in old_rows} < {r['record_id'] for r in new_rows})
            self.assertTrue(all((root / 'old' / name).read_bytes() == raw for name, raw in old_bytes.items()))
            with QueryDataPort(root / 'old') as old_port:
                self.assertEqual(old_port.snapshot_id, old['snapshot_id'])
                self.assertEqual(len(old_port.sources), len(old_sources))

    def test_build_requires_explicit_spec_and_checks_pinned_input(self):
        with self.assertRaises(TypeError):
            build_dataset(ROOT, self.dataset)
        config = json.loads((ROOT / "experiments/data_agent_query/specs/alphabet-reviewed-v1.json").read_text())
        with tempfile.TemporaryDirectory(dir=ROOT / "experiments/data_agent_query") as tmp:
            spec = Path(tmp) / "spec.json"
            config["inputs"][0]["sha256"] = "0" * 64
            spec.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "frozen input hash mismatch"):
                build_dataset(ROOT, Path(tmp) / "output", spec=spec)
            self.assertFalse((Path(tmp) / "output").exists())

    def test_reviewed_call_repairs_reject_other_source_or_inconsistent_value(self):
        config = json.loads((ROOT / "experiments/data_agent_query/specs/alphabet-reviewed-v1.json").read_text())
        entry = config["inputs"][-1]
        record = next(r for r in json.loads((ROOT / entry["path"]).read_text())["records"] if r["metric"] == "capex_machine_share")
        source = next(s for s in self.port.sources if s["source_snapshot_id"] == entry["source_snapshot_id"])
        blocks = {b["block_id"]: b for b in self.port._reader(source).blocks}
        for change in ({"source_sha256": "0" * 64}, {"company_id": "other"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "source/entity mismatch"):
                from_prompt(record, artifact=entry["path"], ordinal=0, source={**source, **change}, blocks=blocks)
        with self.assertRaisesRegex(ValueError, "value disagrees"):
            from_prompt({**record, "value": "99"}, artifact=entry["path"], ordinal=0, source=source, blocks=blocks)

    def test_mutated_snapshot_is_rejected_before_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            damaged = Path(tmp)/"damaged"
            shutil.copytree(self.dataset, damaged)
            (damaged/"records.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "dataset integrity failure"):
                QueryDataPort(damaged)

    def test_equivalent_disclosure_does_not_double_operand(self):
        original = self.port._sql

        def duplicate(sql, params, trace):
            rows = original(sql, params, trace)
            if params[1] == "revenue":
                row = json.loads(rows[0][0])
                return rows + [(json.dumps({**row, "record_id": row["record_id"] + "-repeat"}),)]
            return rows

        with patch.object(self.port, "_sql", side_effect=duplicate):
            result = self.port.query_data(self.query(calculations=[{"formula_id": "operating_margin", "entity_id": "google-cloud", "periods": [period(2025)]}]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["computed_facts"][0]["display_decimal"], "20.74")

    def test_zero_denominator_is_a_calculation_gap(self):
        original = self.port._sql

        def zero(sql, params, trace):
            rows = original(sql, params, trace)
            if params[1] == "revenue":
                rows = [(json.dumps({**json.loads(r[0]), "value_decimal": "0"}),) for r in rows]
            return rows

        with patch.object(self.port, "_sql", side_effect=zero):
            result = self.port.query_data(self.query(calculations=[{"formula_id": "operating_margin", "entity_id": "google-cloud", "periods": [period(2025)]}]))
        self.assertEqual(result["computed_facts"], [])
        self.assertIn("nonpositive_revenue_denominator", [g["reason"] for g in result["gaps"]])


if __name__ == "__main__":
    unittest.main()
