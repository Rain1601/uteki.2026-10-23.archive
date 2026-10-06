"""Independent two-company data MCP acceptance; synthetic values are test-only."""

import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from pydantic import ValidationError

from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import save
from uteki.interfaces.data_mcp.service import DataMCPService


def _company_dataset(root, company, form=None, empty_fiscal_periods=False):
    folder = root / company
    folder.mkdir()
    make_scoped_dataset(folder, schema_metadata=True)
    sources = [source for source in json.loads((folder / "sources.json").read_text())
               if source["company_id"] == company]
    db = duckdb.connect(str(folder / "research.duckdb"))
    db.execute("DELETE FROM observations WHERE source_snapshot_id IN (SELECT source_snapshot_id FROM sources WHERE company_id != ?)", [company])
    db.execute("DELETE FROM evidence WHERE source_snapshot_id IN (SELECT source_snapshot_id FROM sources WHERE company_id != ?)", [company])
    db.execute("DELETE FROM sources WHERE company_id != ?", [company])
    for source in sources:
        if empty_fiscal_periods:
            source["fiscal_periods"] = []
        if form:
            source["form"] = form
            index_folder = folder / source["index_folder"]
            index = json.loads((index_folder / "index.json").read_text())
            index["form_type"] = form
            save(index_folder / "index.json", index)
            save(index_folder / "manifest.json", {"status": "candidate", "artifacts": {
                name: {"sha256": digest((index_folder / name).read_bytes())}
                for name in ("index.json", "blocks.jsonl")}})
        db.execute("UPDATE sources SET form = ?, payload = ? WHERE source_snapshot_id = ?",
                   [source["form"], json.dumps(source), source["source_snapshot_id"]])
    db.close()
    save(folder / "sources.json", sources)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["snapshot_id"] = "synthetic-" + company
    manifest["files"] = {str(path.relative_to(folder)): digest(path.read_bytes())
                         for path in folder.rglob("*") if path.is_file() and path != folder / "manifest.json"}
    save(folder / "manifest.json", manifest)
    return {"id": company + "-v1", "label": company + " synthetic v1", "company_id": company,
            "aliases": [company.upper()], "dataset_path": company,
            "manifest_sha256": digest((folder / "manifest.json").read_bytes())}


class DataMCPServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        registrations = [_company_dataset(self.root, "acme"), _company_dataset(self.root, "other", "20-F")]
        config_path = self.root / "catalog.json"
        save(config_path, {"schema_version": "data-mcp-catalog-v1", "root_path": ".", "datasets": registrations})
        self.service = DataMCPService(config_path)
        self.addCleanup(self.service.close)

    def selection(self, company="acme", **changes):
        return {"dataset_id": company + "-v1", "company_id": company,
                "source_snapshot_ids": [company + "-annual"], "knowledge_cutoff": "2032-06-01",
                "include_candidates": True, **changes}

    def facts(self, company="acme", period_year=2031, selection=None, **changes):
        return self.service.query_facts({
            "selection": selection or self.selection(company), "question": "Read the requested financial period",
            "records": [{"entity_id": company + "-services", "metric_id": "revenue", "period": year(period_year)}],
            **changes,
        })

    def test_observed_periods_are_discoverable_without_fiscal_catalog_and_stay_scoped(self):
        root = self.root / "empty-fiscal"
        root.mkdir()
        registrations = [_company_dataset(root, "acme", empty_fiscal_periods=True),
                         _company_dataset(root, "other", "20-F", empty_fiscal_periods=True)]
        save(root / "catalog.json", {"schema_version": "data-mcp-catalog-v1", "root_path": ".", "datasets": registrations})
        service = DataMCPService(root / "catalog.json")
        self.addCleanup(service.close)
        result = service.get_data_schema({"selection": self.selection(), "view": "periods"})
        self.assertEqual({item["period"]["end"] for item in result["items"]}, {"2030-12-31", "2031-12-31"})
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(all(item["source_snapshot_id"] == "acme-annual" and item["origin"] == "stored_observation" for item in result["items"]))
        self.assertEqual(service.get_data_schema({"selection": self.selection(include_candidates=False), "view": "periods"})["items"], [])
        other = service.get_data_schema({"selection": self.selection("other"), "view": "periods"})
        self.assertEqual([item["period"]["end"] for item in other["items"]], ["2031-12-31"])

    def test_discovery_requires_scope_and_returns_version_choices_without_paths(self):
        for request in ({}, {"company_queries": ["acme"]}, {"knowledge_cutoff": "2032-06-01"},
                        {"company_queries": [" "], "knowledge_cutoff": "2032-06-01"}):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                self.service.discover_data(request)
        request = {"company_queries": ["ACME", "OTHER", "unknown"],
                   "knowledge_cutoff": "2032-06-01", "include_candidates": True}
        result = self.service.discover_data(request)
        self.assertEqual(result["status"], "partial")
        self.assertEqual({item["dataset_id"] for item in result["items"]}, {"acme-v1", "other-v1"})
        self.assertEqual(result["gaps"][0]["reason"], "company_unavailable_or_ambiguous")
        self.assertNotIn("acme-future", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn("index_folder", json.dumps(result))
        only_20f = self.service.discover_data({**request, "company_queries": ["OTHER"], "forms": ["20-F"]})
        self.assertEqual(only_20f["items"][0]["sources"][0]["form"], "20-F")

    def test_unknown_missing_and_cross_company_selection_rejected(self):
        for field in ("dataset_id", "company_id", "source_snapshot_ids", "knowledge_cutoff"):
            invalid = self.selection()
            invalid.pop(field)
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                self.facts(selection=invalid)
        for changes in ({"dataset_id": "absent"}, {"company_id": "other"},
                        {"source_snapshot_ids": ["absent"]}, {"source_snapshot_ids": ["other-annual"]},
                        {"source_snapshot_ids": []}, {"source_snapshot_ids": ["acme-annual", "acme-annual"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.facts(selection=self.selection(**changes))
        with self.assertRaises(ValueError):
            self.facts(records=[{"entity_id": "other-services", "metric_id": "revenue", "period": year(2031)}])
        with self.assertRaises(ValueError):
            self.service.read_source({"selection": self.selection(), "operation": "outline",
                                      "source_snapshot_id": "other-annual"})

    def test_explicit_periods_company_isolation_and_candidate_review_separation(self):
        for company, period_year, expected in (("acme", 2031, "100"), ("acme", 2030, "90"), ("other", 2031, "800")):
            with self.subTest(company=company, period=period_year):
                result = self.facts(company, period_year)
                self.assertEqual(result["status"], "complete")
                self.assertEqual([record["value_decimal"] for record in result["records"]], [expected])
                self.assertEqual(result["records"][0]["period"], year(period_year))
                self.assertEqual(result["records"][0]["status"], "candidate")
                self.assertEqual(result["records"][0]["external_review"]["status"], "not_reviewed")
                self.assertEqual(result["records"][0]["external_review"]["adoption"], "unchanged_candidate")
                self.assertNotIn("trace", result)
                self.assertNotIn(str(self.root), json.dumps(result))
                self.assertNotIn("index_folder", json.dumps(result))
        absent = self.facts(period_year=2029)
        self.assertEqual(absent["records"], [])
        self.assertNotEqual(absent["status"], "complete")
        self.assertTrue(absent["gaps"])

    def test_candidate_denial_gates_values_schema_examples_and_source_content(self):
        denied = self.selection(include_candidates=False)
        facts = self.facts(selection=denied)
        self.assertEqual(facts["records"], [])
        self.assertEqual(facts["evidence"], {})
        self.assertEqual(facts["data_state"]["status"], "quality_filtered")
        for view in ("metrics", "examples", "periods"):
            result = self.service.get_data_schema({"selection": denied, "view": view})
            if view == "metrics":
                self.assertTrue(all(item["status"] == "quality_filtered" for item in result["items"]))
                self.assertNotIn("value_decimal", json.dumps(result["items"]))
            else:
                self.assertEqual(result["items"], [], view)
            self.assertEqual(result["data_state"]["status"], "quality_filtered")
        for operation, fields in (("outline", {}), ("search", {"node_id": "business", "phrase": "sales"}),
                                  ("read", {"node_id": "business"}), ("context", {"block_id": "b1"}),
                                  ("evidence", {"evidence_ids": ["acme-annual-revenue-2031"]})):
            result = self.service.read_source({"selection": denied, "operation": operation,
                                               "source_snapshot_id": "acme-annual", **fields})
            self.assertNotIn("sales from", json.dumps(result))
            self.assertNotIn('"quote": "100"', json.dumps(result))
            if operation != "evidence":
                self.assertEqual(result["status"], "quality_filtered")
        for value in ("true", "false", 0, 1):
            with self.subTest(candidate=value), self.assertRaises(ValidationError):
                self.facts(selection=self.selection(include_candidates=value))
            with self.subTest(discovery_candidate=value), self.assertRaises(ValidationError):
                self.service.discover_data({"company_queries": ["acme"], "knowledge_cutoff": "2032-06-01", "include_candidates": value})

    def test_cutoff_excludes_future_sources_observations_and_no_matches_is_gap(self):
        discovered = self.service.discover_data({"company_queries": ["acme"], "knowledge_cutoff": "2032-02-15", "include_candidates": True})
        self.assertEqual([source["source_snapshot_id"] for source in discovered["items"][0]["sources"]], ["acme-annual"])
        self.assertEqual(self.facts(selection=self.selection(knowledge_cutoff="2032-02-15"))["records"][0]["value_decimal"], "100")
        schema = self.service.get_data_schema({"selection": self.selection(), "view": "entities"})
        self.assertNotIn("future-basis", json.dumps(schema))
        self.assertNotIn("FutureObservationMember", json.dumps(schema))
        with self.assertRaises(ValueError):
            self.facts(selection=self.selection(source_snapshot_ids=["acme-future"]))
        unavailable = self.service.discover_data({"company_queries": ["acme"], "knowledge_cutoff": "2032-01-01", "include_candidates": True})
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["items"], [])
        self.assertEqual(unavailable["gaps"][0]["reason"], "no_registered_source_matches_scope")

    def test_cursor_binds_company_cutoff_candidate_filters_and_source_reading(self):
        request = {"company_queries": ["acme", "other"], "knowledge_cutoff": "2032-06-01", "include_candidates": True, "limit": 1}
        first = self.service.discover_data(request)
        self.assertEqual(first["status"], "limited")
        second = self.service.discover_data({**request, "cursor": first["next_cursor"]})
        self.assertEqual(second["items"][0]["company_id"], "other")
        for change in ({"company_queries": ["other"]}, {"knowledge_cutoff": "2032-02-15"},
                       {"include_candidates": False}, {"forms": ["10-K"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.service.discover_data({**request, "cursor": first["next_cursor"], **change})
        read = {"selection": self.selection(), "operation": "read", "source_snapshot_id": "acme-annual", "node_id": "business", "count": 1}
        first_read = self.service.read_source(read)
        self.assertTrue(first_read["next_cursor"])
        continued = self.service.read_source({**read, "cursor": first_read["next_cursor"]})
        self.assertNotEqual(first_read["blocks"][0]["block_id"], continued["blocks"][0]["block_id"])
        with self.assertRaises(ValueError):
            self.service.read_source({**read, "selection": self.selection("other"), "source_snapshot_id": "other-annual", "cursor": first_read["next_cursor"]})

    def test_20f_source_and_evidence_remain_bound_to_selected_issuer_and_source(self):
        selection = self.selection("other")
        outline = self.service.read_source({"selection": selection, "operation": "outline", "source_snapshot_id": "other-annual"})
        self.assertEqual(outline["status"], "available")
        content = self.service.read_source({"selection": selection, "operation": "read", "source_snapshot_id": "other-annual", "node_id": "business"})
        self.assertIn("other sales", json.dumps(content))
        self.assertNotIn("acme sales", json.dumps(content))
        self.assertNotIn(str(self.root), json.dumps(content))
        missing = self.facts("other", records=[{"entity_id": "other-services", "metric_id": "gross_profit", "period": year(2031)}])
        self.assertEqual(missing["records"], [])
        self.assertEqual(missing["gaps"][0]["reason"], "source_present_unprocessed")
        with self.assertRaisesRegex(ValueError, "evidence unavailable"):
            self.service.read_source({"selection": self.selection(), "operation": "evidence", "source_snapshot_id": "acme-annual", "evidence_ids": ["other-annual-revenue-2031"]})
        with self.assertRaises(ValueError):
            self.service.read_source({"selection": self.selection(source_snapshot_ids=["acme-annual", "acme-amended"]), "operation": "evidence", "source_snapshot_id": "acme-annual", "evidence_ids": ["acme-amended-revenue-2031"]})


if __name__ == "__main__":
    unittest.main()
