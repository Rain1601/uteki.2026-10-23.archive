"""Independent source-scoped tools; fixture is not an extraction quality claim."""
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from pydantic import ValidationError

from uteki.domain.research_data.execution_scope import ExecutionScope, SourceSearchRequest
from uteki.domain.research_data.query_contract import DataQuery, QueryResult, ResearchRecord, VERSION, export_query_schema
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import DDL, save
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort


def year(value):
    return {"kind": "year", "start": f"{value}-01-01", "end": f"{value}-12-31"}


def make_scoped_dataset(folder, *, schema_metadata=False):
    """Small public-domain synthetic fixture, including colliding local block IDs."""
    sources = []
    for sid, company, form, end, available in (
        ("acme-annual", "acme", "10-K", "2031-12-31", "2032-02-01"),
        ("acme-amended", "acme", "10-K", "2031-12-31", "2032-03-01"),
        ("acme-quarter", "acme", "10-Q", "2032-03-31", "2032-04-20"),
        ("acme-future", "acme", "10-K", "2032-12-31", "2033-02-01"),
        ("other-annual", "other", "10-K", "2031-12-31", "2032-02-02"),
    ):
        index_id = "index-" + sid
        blocks = [{"block_id": f"b{i}", "type": kind, "text": text, "reported_page": "1"}
                  for i, (kind, text) in enumerate((
                      ("heading_candidate", "Business"), ("paragraph", company + " sales from products."),
                      ("paragraph", company + " sales from services."),
                      ("heading_candidate", "Risk Factors"), ("paragraph", "Risks include:"),
                      ("list_item", "• Demand risk"), ("list_item", "• Supply risk"),
                      ("paragraph", "Numbers in millions:"), ("table", "Sales 100"),
                      ("paragraph", "(1) Sales exclude discontinued activities."),
                  ))]
        blocks[8]["table"] = {"rows": [[{"text": "Sales"}, {"text": "100"}]]}
        index = {"index_id": index_id, "form_type": form, "diagnostics": [], "nodes": [
            {"node_id": "root", "kind": "document", "start_block_id": "b0", "end_block_id": "b9"},
            {"node_id": "business", "kind": "item", "start_block_id": "b0", "end_block_id": "b2"},
            {"node_id": "risks", "kind": "item", "start_block_id": "b3", "end_block_id": "b6"},
            {"node_id": "notes", "kind": "item", "start_block_id": "b7", "end_block_id": "b9"},
        ]}
        index_folder = folder / "indexes" / sid
        save(index_folder / "index.json", index)
        (index_folder / "blocks.jsonl").write_text("".join(json.dumps(b) + "\n" for b in blocks))
        save(index_folder / "manifest.json", {"status": "candidate", "artifacts": {
            name: {"sha256": digest((index_folder / name).read_bytes())} for name in ("index.json", "blocks.jsonl")}})
        sources.append({"source_snapshot_id": sid, "company_id": company, "form": form, "period_end": end,
                        "available_at": available, "index_id": index_id, "index_folder": "indexes/" + sid,
                        "source_sha256": digest(sid), "source_url": "https://example.invalid/" + sid})
        if schema_metadata:
            sources[-1]["fiscal_periods"] = [{"fiscal_year": int(end[:4]), "period": year(end[:4])}]
    metrics = {m: {"metric_id": m, "unit": "USD"} for m in ("revenue", "operating_income", "gross_profit")}
    db = duckdb.connect(str(folder / "research.duckdb"))
    db.execute(DDL)
    for source in sources:
        db.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                   [source[k] for k in ("source_snapshot_id", "company_id", "form", "period_end", "available_at")]
                   + [json.dumps(source)])
    for sid, entity, metric, value, period_year, available in (
        ("acme-annual", "acme-services", "revenue", "100", 2031, "2032-02-01"),
        ("acme-annual", "acme-services", "operating_income", "15", 2031, "2032-02-01"),
        ("acme-annual", "acme-services", "revenue", "90", 2030, "2032-02-01"),
        ("acme-amended", "acme-services", "revenue", "900", 2031, "2032-03-01"),
        ("acme-amended", "acme-services", "operating_income", "81", 2031, "2032-03-01"),
        ("other-annual", "other-services", "revenue", "800", 2031, "2032-02-02"),
        # Earlier observation timestamp cannot make its later source available.
        ("acme-future", "acme-services", "revenue", "120", 2032, "2032-01-01"),
    ):
        rid = f"{sid}-{metric}-{period_year}"
        row = ResearchRecord(record_id=rid, record_type="metric", entity_id=entity, metric_id=metric,
            period=year(period_year), value_kind="actual", value_decimal=value, value_relation="eq", unit="USD",
            accounting_basis="reported_segment", available_at=available, source_snapshot_id=sid,
            evidence_ids=(rid,), summary="Synthetic observation", origin={}).model_dump(mode="json")
        if schema_metadata:
            row["dimensions"] = {"issuer:BusinessAxis": sid + ":ServicesMember"}
        db.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   [rid, entity, metric, "year", f"{period_year}-01-01", f"{period_year}-12-31", "actual", value,
                    None, "eq", "USD", "reported_segment", available, sid, "candidate", json.dumps(row)])
        db.execute("INSERT INTO evidence VALUES (?, ?, ?)",
                   [rid, sid, json.dumps({"evidence_id": rid, "source_snapshot_id": sid, "quote": value})])
    if schema_metadata:
        # Future extraction inside an already available source must not leak
        # through either its accounting basis or its dimension labels.
        payload = {**row, "record_id": "future-observation", "source_snapshot_id": "acme-annual",
                   "period": year(2031), "value_decimal": "999", "available_at": "2033-01-01",
                   "accounting_basis": "future-basis", "evidence_ids": ["future-observation"],
                   "dimensions": {"issuer:BusinessAxis": "FutureObservationMember"}}
        db.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   ["future-observation", "acme-services", "revenue", "year", "2031-01-01", "2031-12-31",
                    "actual", "999", None, "eq", "USD", "future-basis", "2033-01-01", "acme-annual",
                    "candidate", json.dumps(payload)])
    db.close()
    save(folder / "sources.json", sources)
    save(folder / "metrics.json", metrics)
    for name, model in (("query", DataQuery), ("record", ResearchRecord), ("result", QueryResult)):
        save(folder / f"schemas/{name}.schema.json", export_query_schema(model, version=VERSION))
    save(folder / "manifest.json", {"schema_version": VERSION, "snapshot_id": "synthetic-scoped-v1",
        "source_policy_id": "local-frozen-v1", "limits": ["Synthetic fixture; no extraction claims"],
        "files": {str(p.relative_to(folder)): digest(p.read_bytes()) for p in folder.rglob("*") if p.is_file()}})


class ScopedSchemaMetadataTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        make_scoped_dataset(self.folder, schema_metadata=True)
        self.port = QueryDataPort(self.folder)
        self.addCleanup(self.port.close)
        self.scope = {"snapshot_id": self.port.snapshot_id, "company_ids": ["acme"],
                      "source_snapshot_ids": ["acme-annual", "acme-future"],
                      "source_policy_id": "local-frozen-v1", "knowledge_cutoff": "2032-06-01",
                      "include_candidates": True}

    def test_dimensions_and_fiscal_metadata_use_selected_available_sources(self):
        schema = self.port.scoped(self.scope).get_schema()
        child = next(e for e in schema["entities"] if e["entity_id"] == "acme-services")
        self.assertEqual(child["reported_dimensions"], [{"issuer:BusinessAxis": "acme-annual:ServicesMember"}])
        self.assertEqual(child["accounting_bases"], ["reported_segment"])
        self.assertEqual(schema["fiscal_periods"], [{"fiscal_year": 2031, "period": year(2031),
                         "company_id": "acme", "source_snapshot_id": "acme-annual"}])
        self.assertEqual({e["company_id"] for e in schema["entities"]}, {"acme"})
        # Ensure the excluded same-entity labels actually exist in the parent.
        parent = next(e for e in self.port.get_schema()["entities"] if e["entity_id"] == "acme-services")
        self.assertGreater(len(parent["reported_dimensions"]), 1)

    def test_another_company_has_only_its_own_schema_metadata(self):
        schema = self.port.scoped({**self.scope, "company_ids": ["other"],
                                  "source_snapshot_ids": ["other-annual"]}).get_schema()
        child = next(e for e in schema["entities"] if e["entity_id"] == "other-services")
        self.assertEqual(child["reported_dimensions"], [{"issuer:BusinessAxis": "other-annual:ServicesMember"}])
        self.assertEqual({p["source_snapshot_id"] for p in schema["fiscal_periods"]}, {"other-annual"})

    def test_candidate_denial_preserves_source_identity_without_derived_metadata(self):
        port = self.port.scoped({**self.scope, "include_candidates": False})
        schema = port.get_schema()
        self.assertEqual(schema["entities"], [
            {"entity_id": "acme", "company_id": "acme", "accounting_bases": []},
            {"entity_id": "acme-services", "company_id": "acme", "accounting_bases": []}])
        self.assertEqual(schema["fiscal_periods"], [])
        catalog = port.discover_data()
        self.assertEqual([s["source_snapshot_id"] for s in catalog["sources"]], ["acme-annual"])
        self.assertFalse(catalog["sources"][0]["queryable"])
        self.assertNotIn("fiscal_periods", catalog["sources"][0])
        self.assertTrue(all(c["status"] == "quality_filtered" for c in catalog["coverage"]))

    def test_earlier_cutoff_and_nested_scope_cannot_restore_metadata(self):
        port = self.port.scoped(self.scope).scoped({**self.scope, "knowledge_cutoff": "2032-01-31"})
        self.assertEqual(port.get_schema()["fiscal_periods"], [])
        self.assertEqual([e["entity_id"] for e in port.get_schema()["entities"]], ["acme"])
        self.assertEqual(port.discover_data()["sources"], [])


class ScopedQueryServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        make_scoped_dataset(self.folder)
        self.port = QueryDataPort(self.folder)
        self.addCleanup(self.port.close)
        self.scope = {"snapshot_id": self.port.snapshot_id, "company_ids": ["acme"],
            "source_snapshot_ids": ["acme-annual"], "source_policy_id": "local-frozen-v1",
            "knowledge_cutoff": "2032-06-01", "include_candidates": True}
        self.scoped = self.port.scoped(self.scope)

    def query(self, **changes):
        return {"query_id": "scoped-test", **{k: self.scope[k] for k in
                ("snapshot_id", "source_policy_id", "knowledge_cutoff", "include_candidates")}, **changes}

    def record(self, metric="revenue", period_year=2031):
        return {"entity_id": "acme-services", "metric_id": metric, "period": year(period_year)}

    def test_missing_duplicate_unknown_and_conflicting_scope_rejected(self):
        for key in ("company_ids", "source_snapshot_ids", "source_policy_id", "knowledge_cutoff", "snapshot_id"):
            missing = {k: v for k, v in self.scope.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ExecutionScope.model_validate(missing)
        for key in ("company_ids", "source_snapshot_ids"):
            for value in ([], [" "], [self.scope[key][0], self.scope[key][0]]):
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                    ExecutionScope.model_validate({**self.scope, key: value})
        for changes in ({"source_snapshot_ids": ["unknown"]}, {"source_snapshot_ids": ["other-annual"]},
                        {"company_ids": ["unknown"]}, {"company_ids": ["acme", "other"]}, {"snapshot_id": "other"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.port.scoped({**self.scope, **changes})

    def test_scoped_calculation_excludes_conflicting_same_company_source(self):
        query = self.query(calculations=[{"formula_id": "operating_margin", "entity_id": "acme-services",
                                         "periods": [year(2031)]}])
        self.assertEqual(self.port.query_data(query)["status"], "ambiguous")
        result = self.scoped.query_data(query)
        self.assertEqual(result["computed_facts"][0]["display_decimal"], "15.00")
        self.assertEqual({r["source_snapshot_id"] for r in result["records"]}, {"acme-annual"})
        self.assertTrue(all(e["source_snapshot_id"] == "acme-annual" for e in result["evidence"].values()))
        self.assertTrue(all("acme-annual" in t["parameters"] for t in result["trace"] if t["tool"] == "sql"))

    def test_missing_data_diagnostics_cannot_use_excluded_sources_or_future_values(self):
        for period, expected in ((year(2031), "source_present_unprocessed"),
                                  ({"kind": "quarter", "start": "2032-01-01", "end": "2032-03-31"}, "source_missing"),
                                  (year(2032), "source_missing")):
            result = self.scoped.query_data(self.query(records=[{**self.record("gross_profit"), "period": period}]))
            self.assertEqual(result["selections"][0]["status"], expected)
        scoped = self.port.scoped({**self.scope, "source_snapshot_ids": ["acme-annual", "acme-future"]})
        result = scoped.query_data(self.query(records=[self.record(period_year=2032)]))
        self.assertEqual(result["selections"][0]["status"], "not_available_at_cutoff")
        self.assertEqual(result["records"], [])
        self.assertFalse(any(c["period_end"] == "2032-12-31" for c in scoped.discover_data()["coverage"]))

    def test_schema_and_discovery_are_scoped_without_changing_frozen_contracts(self):
        before = {str(p): digest(p.read_bytes()) for p in self.folder.rglob("*") if p.is_file()}
        schema = self.scoped.get_schema()
        self.assertEqual(schema["query"], export_query_schema(DataQuery, version=VERSION))
        self.assertEqual(schema["schema_version"], "research-query-v0.3")
        self.assertEqual(schema["execution_schema_version"], "research-execution-v1")
        self.assertEqual({e["entity_id"] for e in schema["entities"]}, {"acme", "acme-services"})
        discovery = self.scoped.discover_data()
        self.assertEqual({s["source_snapshot_id"] for s in discovery["sources"]}, {"acme-annual"})
        self.assertEqual(sum(c["occurrence_count"] for c in discovery["coverage"]), 3)
        self.assertEqual(before, {str(p): digest(p.read_bytes()) for p in self.folder.rglob("*") if p.is_file()})

    def test_legacy_dataset_rejects_source_period_for_records_and_calculations(self):
        source_period = {"kind": "year", "start": "2030-07-01", "end": "2031-06-30", "basis": "source"}
        for changes in (
            {"records": [{**self.record(), "period": source_period}]},
            {"calculations": [{"formula_id": "operating_margin", "entity_id": "acme-services",
                               "periods": [source_period]}]},
        ):
            for port in (self.port, self.scoped):
                with self.subTest(changes=changes, port=type(port).__name__), self.assertRaises(ValueError):
                    port.query_data(self.query(**changes))

    def test_query_headers_and_outside_entities_cannot_override_scope(self):
        for key, value in (("knowledge_cutoff", "2033-01-01"), ("include_candidates", False), ("snapshot_id", "wrong")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.scoped.query_data(self.query(records=[self.record()], **{key: value}))
        with self.assertRaises(ValueError):
            self.scoped.query_data(self.query(records=[{**self.record(), "entity_id": "other-services"}]))
        with self.assertRaises(ValueError):
            self.scoped.query_data(self.query(documents=[{"company_id": "other", "form": "10-K",
                "period_end": "2031-12-31", "phrase": "sales"}]))

    def test_evidence_access_is_atomic_scoped_and_candidate_aware(self):
        eid = "acme-annual-revenue-2031"
        self.assertIn(eid, self.scoped.get_evidence([eid])["evidence"])
        for other in ("acme-amended-revenue-2031", "other-annual-revenue-2031", "missing"):
            with self.subTest(other=other), self.assertRaises(KeyError):
                self.scoped.get_evidence([eid, other])
        with self.assertRaises(ValueError):
            self.scoped.get_evidence([eid], include_candidates=False)
        with self.assertRaises(PermissionError):
            self.port.scoped({**self.scope, "include_candidates": False}).get_evidence([eid])

    def test_legacy_document_queries_only_search_allowed_source(self):
        result = self.scoped.query_data(self.query(documents=[{"company_id": "acme", "form": "10-K",
            "period_end": "2031-12-31", "phrase": "sales", "limit": 4}]))
        self.assertEqual({c["source_snapshot_id"] for d in result["documents"] for c in d["contexts"]}, {"acme-annual"})
        result = self.scoped.query_data(self.query(documents=[{"company_id": "acme", "form": "10-Q",
            "period_end": "2032-03-31", "phrase": "sales"}]))
        self.assertEqual(result["documents"][0]["status"], "source_missing")

    def test_outline_read_continuation_boundaries_and_complete_groups(self):
        source = {"source_snapshot_id": "acme-annual"}
        self.assertEqual(self.scoped.outline_source(source)["status"], "available")
        first = self.scoped.read_source({**source, "node_id": "business", "count": 1})
        self.assertEqual(first["block_ids"], ["b0"])
        rest = self.scoped.read_source({**source, "node_id": "business", "cursor": first["next_cursor"]})
        self.assertEqual(rest["block_ids"], ["b1", "b2"])
        self.assertIsNone(rest["next_cursor"])
        self.assertTrue(rest["node_complete"])
        risks = self.scoped.read_source({**source, "node_id": "risks", "start_block_id": "b5", "count": 1})
        self.assertEqual(risks["block_ids"], ["b3", "b4", "b5", "b6"])
        table = self.scoped.read_source({**source, "node_id": "notes", "start_block_id": "b8", "count": 1})
        self.assertEqual(table["block_ids"], ["b7", "b8", "b9"])
        self.assertIn("table", table["blocks"][1])
        with self.assertRaises(ValueError):
            self.scoped.read_source({**source, "node_id": "business", "start_block_id": "b5"})
        with self.assertRaises(ValueError):
            self.scoped.read_context(source_snapshot_id="other-annual", block_id="b0")
        missing = self.scoped.read_source({**source, "node_id": "absent"})
        self.assertEqual(missing["status"], "node_missing")
        self.assertEqual(missing["blocks"], [])

    def test_search_pagination_and_cursor_replay_rejected(self):
        request = {"source_snapshot_id": "acme-annual", "node_id": "business", "phrase": "sales", "limit": 1}
        first = self.scoped.search_source(request)
        self.assertEqual(first["status"], "limited")
        second = self.scoped.search_source({**request, "cursor": first["next_cursor"]})
        self.assertEqual(second["status"], "matched")
        self.assertNotEqual(first["hits"][0]["block_id"], second["hits"][0]["block_id"])
        for changes in ({"phrase": "risk"}, {"node_id": "root"}, {"offset": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.scoped.search_source({**request, "cursor": first["next_cursor"], **changes})
        amended = self.port.scoped({**self.scope, "source_snapshot_ids": ["acme-amended"]})
        with self.assertRaises(ValueError):
            amended.search_source({**request, "source_snapshot_id": "acme-amended", "cursor": first["next_cursor"]})
        changed_cutoff = self.port.scoped({**self.scope, "knowledge_cutoff": "2032-07-01"})
        with self.assertRaises(ValueError):
            changed_cutoff.search_source({**request, "cursor": first["next_cursor"]})
        zero = self.scoped.search_source({**request, "phrase": "no such disclosure"})
        self.assertEqual(zero["status"], "no_literal_match")
        self.assertFalse(zero["not_disclosed"])

    def test_candidate_and_cutoff_block_body_tools(self):
        for scoped, sid, expected in (
            (self.port.scoped({**self.scope, "include_candidates": False}), "acme-annual", "quality_filtered"),
            (self.port.scoped({**self.scope, "source_snapshot_ids": ["acme-future"]}), "acme-future", "not_available_at_cutoff"),
        ):
            for method, args in (("outline_source", {}), ("read_source", {"node_id": "business"}),
                                 ("search_source", {"node_id": "business", "phrase": "sales"})):
                with self.subTest(method=method, expected=expected):
                    result = getattr(scoped, method)({"source_snapshot_id": sid, **args})
                    self.assertEqual(result["status"], expected)
                    self.assertFalse(result["blocks"] or result["nodes"] or result["hits"])

    def test_oversized_atomic_context_is_not_truncated_or_advanced(self):
        source = self.scoped.sources[0]
        reader = self.scoped._reader(source)
        # Modify only this cached test reader, never the frozen input artifact.
        reader.blocks[1] = {**reader.blocks[1], "text": "x" * 90000}
        result = self.scoped.read_source({"source_snapshot_id": "acme-annual", "node_id": "business", "start_block_id": "b1"})
        self.assertEqual(result["status"], "context_too_large")
        self.assertEqual(result["blocks"], [])
        self.assertIsNone(result["next_cursor"])
        self.assertIsNone(result["next_block_id"])
        self.assertFalse(result["node_complete"])

    def test_prior_period_facts_remain_readable_from_explicit_annual_source(self):
        result = self.scoped.query_data(self.query(records=[self.record(period_year=2030)]))
        self.assertEqual(result["records"][0]["value_decimal"], "90")
        self.assertEqual(result["records"][0]["source_snapshot_id"], "acme-annual")

    def test_another_company_uses_the_same_scope_contract(self):
        scoped = self.port.scoped({**self.scope, "company_ids": ["other"], "source_snapshot_ids": ["other-annual"]})
        result = scoped.query_data(self.query(records=[{**self.record(), "entity_id": "other-services"}]))
        self.assertEqual(result["records"][0]["value_decimal"], "800")
        self.assertEqual({e["source_snapshot_id"] for e in result["evidence"].values()}, {"other-annual"})
        text = scoped.read_source({"source_snapshot_id": "other-annual", "node_id": "business"})
        self.assertIn("other sales", text["blocks"][1]["text"])

    def test_read_cursor_is_bound_and_cannot_conflict_with_explicit_start(self):
        request = {"source_snapshot_id": "acme-annual", "node_id": "business", "count": 1}
        cursor = self.scoped.read_source(request)["next_cursor"]
        for changes in ({"node_id": "root"}, {"start_block_id": "b2"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.scoped.read_source({**request, "cursor": cursor, **changes})
        with self.assertRaises(ValueError):
            self.scoped.read_source({**request, "cursor": {**cursor, "index_id": "wrong-index"}})

    def test_cross_node_context_is_a_gap_instead_of_an_incomplete_quote(self):
        reader = self.scoped._reader(self.scoped.sources[0])
        reader.groups.append({"group_id": "synthetic-crossing-group", "kind": "test",
                              "block_ids": ["b2", "b3"], "rule": "Test boundary conflict"})
        result = self.scoped.read_source({"source_snapshot_id": "acme-annual", "node_id": "business", "start_block_id": "b2"})
        self.assertEqual(result["status"], "context_crosses_node")
        self.assertEqual(result["blocks"], [])
        self.assertIsNone(result["next_cursor"])
        self.assertIn("synthetic-crossing-group", result["context_group_ids"])

    def test_evidence_cutoff_cannot_follow_earlier_observation_timestamp(self):
        scoped = self.port.scoped({**self.scope, "source_snapshot_ids": ["acme-future"]})
        with self.assertRaises(KeyError):
            scoped.get_evidence(["acme-future-revenue-2032"])

    def test_derived_scopes_can_only_retain_or_narrow_access(self):
        broader_scope = {**self.scope, "company_ids": ["acme", "other"],
                         "source_snapshot_ids": ["acme-annual", "acme-amended", "other-annual"]}
        broad = self.port.scoped(broader_scope)
        self.assertEqual(broad.scoped(broader_scope).scope_id, broad.scope_id)
        narrow_scope = {**self.scope, "knowledge_cutoff": "2032-02-02", "include_candidates": False}
        narrow = broad.scoped(narrow_scope)
        self.assertEqual(narrow.scope.company_ids, ("acme",))
        self.assertEqual(narrow.scope.source_snapshot_ids, ("acme-annual",))
        self.assertEqual(narrow.outline_source({"source_snapshot_id": "acme-annual"})["status"], "quality_filtered")
        attempts = [
            {"include_candidates": True}, {"knowledge_cutoff": "2032-02-03"},
            {"source_snapshot_ids": ["acme-annual", "acme-amended"]},
            {"company_ids": ["acme", "other"], "source_snapshot_ids": ["acme-annual", "other-annual"]},
        ]
        for changes in attempts:
            for constructor in (narrow.scoped, lambda s: ScopedQueryDataPort(narrow, s)):
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "cannot widen"):
                    constructor({**narrow_scope, **changes})
        # The original owner retains its authority to explicitly establish a new scope.
        self.assertTrue(self.port.scoped({**narrow_scope, "include_candidates": True}).scope.include_candidates)

    def test_search_cursor_survives_model_dump_roundtrip_with_default_fields(self):
        request = {"source_snapshot_id": "acme-annual", "node_id": "business", "phrase": "sales", "limit": 1}
        first = self.scoped.search_source(request)
        typed = SourceSearchRequest(**request, cursor=first["next_cursor"])
        serialized = typed.model_dump(mode="json")
        self.assertIsNone(serialized["offset"])
        following = self.scoped.search_source(serialized)
        self.assertEqual(following["offset"], 1)
        self.assertEqual(following["hits"][0]["block_id"], "b2")
        with self.assertRaisesRegex(ValueError, "offset conflicts"):
            self.scoped.search_source({**serialized, "offset": 0})


if __name__ == "__main__":
    unittest.main()
