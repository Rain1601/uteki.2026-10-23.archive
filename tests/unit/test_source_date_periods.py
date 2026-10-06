"""Protocol boundaries for independent, source-declared week-based periods."""
from datetime import date, timedelta
import unittest

from uteki.domain.research_data.query_contract import (
    DataQuery, EXACT_SOURCE_PERIOD_VERSION, Period, QueryResult, ResearchRecord,
    SOURCE_PERIOD_VERSION, SUPPORTED_VERSIONS, VERSION, export_query_schema,
    validate_period_version,
)


class SourceDatePeriodTests(unittest.TestCase):
    def source_period(self, kind="year", weeks=52):
        start = date(2031, 1, 5)
        return {"kind": kind, "start": start.isoformat(),
                "end": (start + timedelta(weeks=weeks) - timedelta(days=1)).isoformat(),
                "basis": "source"}

    def record(self, period, version):
        return dict(schema_version=version, record_id="synthetic-week-year",
                    record_type="metric", entity_id="synthetic-issuer", metric_id="revenue",
                    period=period, value_kind="actual", value_decimal="123.45",
                    value_relation="eq", unit="USD", accounting_basis="reported_consolidated",
                    available_at="2033-02-01", source_snapshot_id="synthetic-filing",
                    evidence_ids=["synthetic-original-row"], summary="Independent synthetic amount",
                    origin={"adapter": "synthetic-exact-date-fixture"})

    def test_exact_source_year_quarter_ytd_are_preserved(self):
        for kind, weeks in (("year", 52), ("year", 53), ("quarter", 13),
                            ("quarter", 14), ("ytd", 26), ("ytd", 39)):
            with self.subTest(kind=kind, weeks=weeks):
                supplied = self.source_period(kind, weeks)
                period = Period.model_validate(supplied)
                validate_period_version(period, EXACT_SOURCE_PERIOD_VERSION)
                self.assertEqual(period.model_dump(mode="json"), supplied)
                self.assertEqual((period.end - period.start).days + 1, weeks * 7)
                record = ResearchRecord.model_validate(self.record(supplied, EXACT_SOURCE_PERIOD_VERSION))
                self.assertEqual(record.period, period)

    def test_old_versions_reject_the_same_week_based_periods(self):
        for version in (VERSION, SOURCE_PERIOD_VERSION):
            for kind, weeks in (("year", 52), ("year", 53), ("quarter", 13), ("ytd", 26)):
                with self.subTest(version=version, kind=kind, weeks=weeks):
                    supplied = self.source_period(kind, weeks)
                    with self.assertRaises(ValueError):
                        validate_period_version(supplied, version)
                    with self.assertRaises(ValueError):
                        ResearchRecord.model_validate(self.record(supplied, version))

    def test_old_complete_month_periods_keep_their_boundaries(self):
        for supplied in (
            {"kind": "year", "start": "2030-07-01", "end": "2031-06-30", "basis": "source"},
            {"kind": "quarter", "start": "2030-11-01", "end": "2031-01-31", "basis": "source"},
            {"kind": "ytd", "start": "2030-07-01", "end": "2031-03-31", "basis": "source"},
        ):
            validate_period_version(supplied, SOURCE_PERIOD_VERSION)
            validate_period_version(supplied, EXACT_SOURCE_PERIOD_VERSION)
            with self.assertRaises(ValueError):
                validate_period_version(supplied, VERSION)
        with self.assertRaises(ValueError):
            validate_period_version({"kind": "year", "start": "2030-07-01",
                                     "end": "2031-05-31", "basis": "source"}, SOURCE_PERIOD_VERSION)

    def test_source_dates_require_start_and_order_no_inference(self):
        supplied = self.source_period()
        missing = {k: v for k, v in supplied.items() if k != "start"}
        for invalid in (missing, {**supplied, "start": None},
                        {**supplied, "start": supplied["end"], "end": supplied["start"]}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Period.model_validate(invalid)
                with self.assertRaises(ValueError):
                    validate_period_version(invalid, EXACT_SOURCE_PERIOD_VERSION)

    def test_calendar_basis_remains_strict_in_every_version(self):
        calendar = {"kind": "year", "start": "2031-01-01", "end": "2031-12-31"}
        for version in SUPPORTED_VERSIONS:
            validate_period_version(calendar, version)
            for invalid in (
                {k: v for k, v in self.source_period().items() if k != "basis"},
                {"kind": "quarter", "start": "2031-02-01", "end": "2031-04-30"},
                {"kind": "year", "start": "2030-07-01", "end": "2031-06-30"},
            ):
                with self.subTest(version=version, invalid=invalid), self.assertRaises(ValueError):
                    validate_period_version(invalid, version)

    def test_instants_and_unknown_versions(self):
        for version in SUPPORTED_VERSIONS:
            validate_period_version({"kind": "instant", "start": None, "end": "2031-01-04"}, version)
            with self.assertRaises(ValueError):
                validate_period_version({"kind": "instant", "start": "2031-01-04", "end": "2031-01-04"}, version)
        with self.assertRaises(ValueError):
            validate_period_version(None, "research-query-v999")

    def test_result_versions_do_not_silently_upgrade_records(self):
        record = ResearchRecord.model_validate(self.record(self.source_period(), EXACT_SOURCE_PERIOD_VERSION))
        result = dict(result_schema_version=EXACT_SOURCE_PERIOD_VERSION, query_id="test",
                      snapshot_id="synthetic-snapshot", source_policy_id="local-frozen-v1",
                      knowledge_cutoff="2033-02-01", candidate_data=True, status="complete",
                      completion_scope="synthetic week-year fact only", records=[record])
        QueryResult.model_validate(result)
        with self.assertRaises(ValueError):
            QueryResult.model_validate({**result, "result_schema_version": SOURCE_PERIOD_VERSION})

    def test_exports_identify_each_protocol_and_period_semantics(self):
        for version in SUPPORTED_VERSIONS:
            for model in (DataQuery, ResearchRecord, QueryResult, Period):
                with self.subTest(version=version, model=model):
                    schema = export_query_schema(model, version=version)
                    period = schema if model is Period else schema["$defs"]["Period"]
                    if version == VERSION:
                        self.assertNotIn("x-query-contract-version", schema)
                        self.assertNotIn("x-period-validation", period)
                        self.assertNotIn("$comment", period)
                    else:
                        self.assertEqual(schema["x-query-contract-version"], version)
                        rules = period["x-period-validation"]
                        self.assertEqual(rules["protocol"], version)
                        self.assertEqual(rules["source"], {
                            SOURCE_PERIOD_VERSION: "complete_month_boundaries",
                            EXACT_SOURCE_PERIOD_VERSION: "ordered_exact_dates"}[version])
                    self.assertEqual("basis" in period["properties"], version != VERSION)
                    self.assertIn("start", period["required"])
                    self.assertIn("end", period["required"])
                    markers = []
                    if model is ResearchRecord:
                        markers.append(schema["properties"]["schema_version"])
                    elif model is QueryResult:
                        markers.extend((schema["properties"]["result_schema_version"],
                            schema["$defs"]["ResearchRecord"]["properties"]["schema_version"]))
                    for marker in markers:
                        self.assertEqual(marker["default"], version)
                        if version == VERSION:
                            self.assertNotIn("const", marker)
                        else:
                            self.assertEqual(marker["const"], version)


if __name__ == "__main__":
    unittest.main()
