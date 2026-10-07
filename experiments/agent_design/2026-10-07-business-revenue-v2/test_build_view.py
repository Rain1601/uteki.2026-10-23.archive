"""Independent revenue boundary fixtures; no model or browser execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "business_revenue_view", Path(__file__).with_name("build_view.py")
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class RevenueBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = patch.object(builder.view, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fixture(self, company="orion", period="2022-06-30", adjusted=False, services_value=None):
        """All expected amounts come from this explicit synthetic disclosure."""
        a, b = (80, 30) if adjusted else (60, 40)
        if services_value is not None:
            b = services_value
        labels = {
            "total": f"{company}: year ended {period}; total revenue",
            "a": "Subscriptions revenue",
            "b": "Services revenue",
        }
        tokens = {"total": "100", "a": str(a), "b": str(b)}
        if adjusted:
            labels["adjustment"] = "Revenue adjustment"
            tokens["adjustment"] = "(10)"
        quotes = {eid: f"{label} {tokens[eid]} USD million" for eid, label in labels.items()}
        path = self.root / f"{company}-{period}.html"
        path.write_text(
            '<html><head><meta charset="utf-8"></head><body>'
            + "".join(
                f'<p id="{eid}">{label} <span id="{eid}-value">{tokens[eid]}</span> USD million</p>'
                for eid, label in labels.items()
            )
            + "</body></html>"
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document_id = f"{company}-{period}"
        scope = {
            "company_id": company,
            "document_id": document_id,
            "metadata": {"period_end": period, "source_sha256": digest},
        }
        row = lambda eid, value, label: {
            "id": eid, "label": label, "value": value, "evidence_ids": [eid],
            "amount_evidence_id": eid,
        }
        data = {
            "company_id": company,
            "document_id": document_id,
            "period_end": period,
            "currency": "USD",
            "unit": "million",
            "source_local_path": path.name,
            "source_sha256": digest,
            "source_url": f"https://example.invalid/{document_id}",
            "evidence": [
                {"id": eid, "local_path": path.name, "fragment": eid, "exact_quote": quote,
                 "source_cell_dom_path": f"//*[@id='{eid}-value']", "source_cell_text": tokens[eid]}
                for eid, quote in quotes.items()
            ],
            "charts": [{
                "id": "revenue", "title": "Disclosed revenue",
                "denominator_label": "Total revenue", "total": 100,
                "total_evidence_ids": ["total"],
                "total_amount_evidence_id": "total",
                "chart_type": "bar" if adjusted else "donut",
                "parts": [row("a", a, "Subscriptions"), row("b", b, "Services")],
                "adjustments": [row("adjustment", -10, "Revenue adjustment")] if adjusted else [],
            }],
        }
        return data, scope

    def validate(self, data, scopes):
        path = self.root / "revenue.json"
        path.write_text(json.dumps(data))
        return builder.validate_revenue(path, scopes)

    def test_explicit_other_company_and_period_support_complete_donut(self):
        first, first_scope = self.fixture()
        second, second_scope = self.fixture("lyra", "2021-09-30")
        for data in (first, second):
            with self.subTest(company=data["company_id"]):
                actual = self.validate(data, [first_scope, second_scope])
                self.assertEqual(actual["company_id"], data["company_id"])
                self.assertEqual(actual["period_end"], data["period_end"])
                self.assertEqual(actual["charts"][0]["chart_type"], "donut")
                self.assertEqual(actual["charts"][0]["total"], 100)
                self.assertEqual([p["value"] for p in actual["charts"][0]["parts"]], [60, 40])

    def test_wrong_company_document_or_period_never_falls_back(self):
        data, scope = self.fixture()
        _, other_scope = self.fixture("lyra", "2021-09-30")
        for field, value in (
            ("company_id", "unknown-issuer"),
            ("company_id", "lyra"),
            ("document_id", "other-report"),
            ("period_end", "2023-06-30"),
        ):
            bad = copy.deepcopy(data)
            bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "scope_mismatch"):
                self.validate(bad, [scope, other_scope])

    def test_declared_and_actual_source_hash_must_both_match(self):
        data, scope = self.fixture()
        bad = copy.deepcopy(data)
        bad["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "revenue_source_mismatch"):
            self.validate(bad, [scope])
        source = self.root / data["source_local_path"]
        source.write_text(source.read_text().replace(">100</span>", ">101</span>"))
        with self.assertRaisesRegex(ValueError, "revenue_source_hash_mismatch"):
            self.validate(data, [scope])

    def test_missing_or_unsupported_units_are_not_assumed(self):
        data, scope = self.fixture()
        for field in ("currency", "unit"):
            for value in (None, "", "unsupported"):
                bad = copy.deepcopy(data)
                if value is None:
                    bad.pop(field)
                else:
                    bad[field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "scope|unit"):
                    self.validate(bad, [scope])

    def test_signed_adjustment_reconciles_without_becoming_donut(self):
        data, scope = self.fixture(adjusted=True)
        actual = self.validate(data, [scope])
        chart = actual["charts"][0]
        self.assertEqual(chart["chart_type"], "bar")
        self.assertEqual(chart["adjustments"][0]["value"], -10)
        self.assertEqual(sum(p["value"] for p in chart["parts"] + chart["adjustments"]), 100)
        bad = copy.deepcopy(data)
        bad["charts"][0]["chart_type"] = "donut"
        with self.assertRaisesRegex(ValueError, "donut_cannot_include_adjustments"):
            self.validate(bad, [scope])
        bad["charts"][0]["chart_type"] = "bar"
        bad["charts"][0]["parts"].append(bad["charts"][0]["adjustments"].pop())
        with self.assertRaisesRegex(ValueError, "negative_amount_belongs_in_adjustments"):
            self.validate(bad, [scope])

    def test_unknown_zero_or_nonfinite_denominator_is_not_filled(self):
        data, scope = self.fixture()
        for value in (None, 0, -1, "", True, float("nan"), float("inf")):
            bad = copy.deepcopy(data)
            bad["charts"][0]["total"] = value
            before = json.dumps(bad)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(bad, [scope])
            self.assertEqual(json.dumps(bad), before)
        bad = copy.deepcopy(data)
        bad["charts"][0]["parts"][0]["value"] = None
        with self.assertRaisesRegex(ValueError, "revenue_number_required"):
            self.validate(bad, [scope])

    def test_absent_required_chart_fields_report_validation_gap(self):
        data, scope = self.fixture()
        for field in ("total", "total_evidence_ids", "parts", "adjustments"):
            bad = copy.deepcopy(data)
            del bad["charts"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(bad, [scope])
        bad = copy.deepcopy(data)
        del bad["charts"][0]["parts"][0]["value"]
        with self.assertRaises(ValueError):
            self.validate(bad, [scope])

    def test_sum_mismatch_never_creates_other_or_changes_denominator(self):
        data, scope = self.fixture(services_value=39)
        before = copy.deepcopy(data)
        with self.assertRaisesRegex(ValueError, "revenue_does_not_reconcile"):
            self.validate(data, [scope])
        self.assertEqual(data, before)

    def test_same_total_with_changed_parts_is_rejected_against_source_cells(self):
        data, scope = self.fixture()
        data["charts"][0]["parts"][0]["value"] = 50
        data["charts"][0]["parts"][1]["value"] = 50
        self.assertEqual(sum(row["value"] for row in data["charts"][0]["parts"]), 100)
        with self.assertRaisesRegex(ValueError, "revenue_amount_differs_from_source_cell"):
            self.validate(data, [scope])

    def test_amount_binding_must_exist_and_be_cited(self):
        data, scope = self.fixture()
        for target, field in (("chart", "total_amount_evidence_id"), ("row", "amount_evidence_id")):
            for invalid in (None, "not-registered", "b"):
                bad = copy.deepcopy(data)
                owner = bad["charts"][0] if target == "chart" else bad["charts"][0]["parts"][0]
                if invalid is None:
                    owner.pop(field)
                else:
                    owner[field] = invalid
                with self.subTest(target=target, invalid=invalid), self.assertRaisesRegex(ValueError, "revenue_amount_binding_required"):
                    self.validate(bad, [scope])

    def test_missing_or_forged_source_cell_binding_is_rejected(self):
        data, scope = self.fixture()
        for field in ("source_cell_dom_path", "source_cell_text"):
            bad = copy.deepcopy(data)
            del bad["evidence"][1][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "revenue_source_cell_required"):
                self.validate(bad, [scope])
        bad = copy.deepcopy(data)
        bad["evidence"][1]["source_cell_text"] = "50"
        bad["charts"][0]["parts"][0]["value"] = 50
        with self.assertRaisesRegex(ValueError, "revenue_source_cell_text_mismatch"):
            self.validate(bad, [scope])
        bad = copy.deepcopy(data)
        bad["evidence"][1]["source_cell_dom_path"] = "//*[@id='missing-value']"
        with self.assertRaisesRegex(ValueError, "revenue_source_cell_not_unique"):
            self.validate(bad, [scope])

    def test_real_anchor_and_quote_are_required(self):
        data, scope = self.fixture()
        for field, value in (("fragment", "missing"), ("exact_quote", "Invented revenue 999.")):
            bad = copy.deepcopy(data)
            bad["evidence"][1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "revenue_anchor_quote_mismatch"):
                self.validate(bad, [scope])


if __name__ == "__main__":
    unittest.main()
