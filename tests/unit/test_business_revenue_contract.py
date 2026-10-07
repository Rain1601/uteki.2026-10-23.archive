"""Source-selected product contract boundaries; independent synthetic issuers."""
import copy
import hashlib
from decimal import Decimal
import unittest

from pydantic import ValidationError

from uteki.agents.business_map.product_contract import ProductDraft, parse_amount_cell, validate_draft


def fixture(company="orion", period="2025-06-30", label="2025", *, adjusted=False):
    def block(bid, text):
        return {"id": bid, "section_path": ["Synthetic source"], "source_dom_path": f"//*[@id='{bid}']",
                "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    def cell(cid, text, row, col=4, rowspan=1, colspan=1):
        return {"id": cid, "text": text, "source_dom_path": f"//*[@id='{cid}']",
                "row_index": row, "column_index": col, "rowspan": rowspan, "colspan": colspan}
    packet = {
        "company_id": company, "document_id": company + "-report", "period_end": period,
        "requested_period_label": label, "financial_currency": "USD", "financial_unit": "million",
        "source_sha256": hashlib.sha256((company + period).encode()).hexdigest(),
        "source_local_path": f"synthetic/{company}.html", "source_url": f"https://example.invalid/{company}",
        "blocks": [block("business-source", company + " supplies tools and support services."),
                   block("unit", "The revenue table is presented in millions."),
                   block("currency", "Financial amounts are denominated in US dollars."),
                   block("table-block", "Revenue by type for explicitly labeled periods.")],
        "tables": [{"id": "table", "block_id": "table-block", "source_dom_path": "//*[@id='table']",
                    "cells": [cell("prior-header", "prior period", 0, 0, colspan=3),
                              cell("header", label, 0, 3, colspan=3),
                              cell("a", "80" if adjusted else "60", 1),
                              cell("b", "30" if adjusted else "40", 2),
                              cell("adjustment", "(10)", 3), cell("total", "100", 4),
                              cell("subtotal", "110" if adjusted else "100", 5)]}],
    }
    row = lambda rid, cid: {"id": rid, "label": rid, "amount_cell_id": cid}
    data = {
        "company_id": company, "document_id": packet["document_id"], "period_end": period,
        "summary": "Synthetic business and separately selected revenue.",
        "businesses": [{"id": "root", "name": company, "kind": "company", "description": "Company",
                        "evidence_block_ids": ["business-source"]},
                       {"id": "tools", "name": "Tools", "kind": "business", "description": "Tools business",
                        "monetization": [{"description": "No reviewed pricing information.", "basis": "unknown",
                                          "evidence_block_ids": []}], "evidence_block_ids": ["business-source"]}],
        "relationships": [{"source_id": "tools", "target_id": "root", "kind": "part_of",
                           "description": "Business belongs to company", "evidence_block_ids": ["business-source"]}],
        "unknowns": [{"id": "pricing", "question": "What is the price?", "reason_unanswered": "Not in supplied material.",
                      "related_business_ids": ["tools"]}],
        "revenue_charts": [{"id": "revenue", "title": "Revenue by type", "denominator_label": "Total revenue",
                            "chart_type": "bar" if adjusted else "donut", "total_cell_id": "total",
                            "unit_block_id": "unit", "currency_block_id": "currency", "period_header_cell_id": "header",
                            "parts": [row("tools-revenue", "a"), row("services-revenue", "b")],
                            "adjustments": [row("revenue-adjustment", "adjustment")] if adjusted else [],
                            "reported_subtotals": [{**row("gross-subtotal", "subtotal"),
                                                   "component_ids": ["tools-revenue", "services-revenue"]}]}],
    }
    return data, packet


class BusinessRevenueContractTests(unittest.TestCase):
    def test_other_company_period_and_spanned_period_header_work(self):
        for company, period, label in (("orion", "2025-06-30", "2025"), ("lyra", "2022-09-30", "FY2022")):
            data, packet = fixture(company, period, label)
            actual = validate_draft(data, packet)
            self.assertIsInstance(actual, ProductDraft)
            self.assertEqual(actual.company_id, company)
            self.assertEqual(actual.period_end, period)
            self.assertEqual(actual.revenue_charts[0].chart_type, "donut")
            self.assertNotIn("value", actual.revenue_charts[0].parts[0].model_dump())

    def test_extra_fields_amounts_and_revenue_graph_edges_are_rejected(self):
        data, packet = fixture()
        for field in ("value", "amount", "evidence_ids"):
            bad = copy.deepcopy(data)
            bad["revenue_charts"][0]["parts"][0][field] = 50
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_draft(bad, packet)
        bad = copy.deepcopy(data)
        bad["relationships"][0]["kind"] = "revenue_component_of"
        with self.assertRaises(ValidationError):
            validate_draft(bad, packet)
        bad = copy.deepcopy(data)
        bad["businesses"][1]["kind"] = "revenue_line"
        with self.assertRaises(ValidationError):
            validate_draft(bad, packet)

    def test_scope_ids_and_evidence_cannot_fall_back(self):
        data, packet = fixture()
        for field, value in (("company_id", "other"), ("document_id", "other-report"), ("period_end", "2024-06-30")):
            bad = copy.deepcopy(data)
            bad[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "scope_mismatch"):
                validate_draft(bad, packet)
        for action, error in ((lambda d: d["businesses"].append(copy.deepcopy(d["businesses"][1])), "duplicate_business_id"),
                              (lambda d: d["businesses"][1].update(evidence_block_ids=["outside"]), "business_evidence_outside"),
                              (lambda d: d["relationships"][0].update(target_id="outside"), "relationship_endpoints_outside"),
                              (lambda d: d["unknowns"][0].update(related_business_ids=["outside"]), "unknown_businesses_outside")):
            bad = copy.deepcopy(data)
            action(bad)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                validate_draft(bad, packet)

    def test_packet_source_text_hash_and_missing_scope_fail(self):
        data, packet = fixture()
        bad = copy.deepcopy(packet)
        bad["blocks"][0]["text"] += " Changed."
        with self.assertRaisesRegex(ValueError, "block_hash_mismatch"):
            validate_draft(data, bad)
        for field in ("source_sha256", "source_url", "source_local_path", "financial_unit", "financial_currency"):
            bad = copy.deepcopy(packet)
            bad.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_draft(data, bad)

    def test_amount_parser_is_strict_and_preserves_signed_decimal(self):
        for text, expected in ((" 1,234.50 ", "1234.50"), ("( 1,234.50 )", "-1234.50"),
                               ("1\u202f234.50", "1234.50"), ("- 10", "-10"), ("0", "0")):
            self.assertEqual(parse_amount_cell(text), Decimal(expected))
        for text in ("", "—", "–", "-", "N/A", "NaN", "60*", "$60", "1,23", "(-10)", "1 2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount_cell(text)

    def test_negative_adjustment_stays_in_bar_and_subtotal_is_not_added_twice(self):
        data, packet = fixture(adjusted=True)
        result = validate_draft(data, packet)
        self.assertEqual(result.revenue_charts[0].reported_subtotals[0].component_ids,
                         ["tools-revenue", "services-revenue"])
        bad = copy.deepcopy(data)
        bad["revenue_charts"][0]["chart_type"] = "donut"
        with self.assertRaisesRegex(ValueError, "donut_cannot_include_adjustments"):
            validate_draft(bad, packet)
        bad = copy.deepcopy(data)
        chart = bad["revenue_charts"][0]
        chart["parts"].append(chart["adjustments"].pop())
        with self.assertRaisesRegex(ValueError, "negative_amount_belongs_in_adjustments"):
            validate_draft(bad, packet)

    def test_duplicate_selected_cells_and_subtotal_components_are_rejected(self):
        data, packet = fixture()
        bad = copy.deepcopy(data)
        bad["revenue_charts"][0]["parts"][0]["amount_cell_id"] = "total"
        with self.assertRaisesRegex(ValueError, "duplicate_revenue_amount_cell"):
            validate_draft(bad, packet)
        for component_ids in (["tools-revenue", "tools-revenue"], ["gross-subtotal"], ["outside"]):
            bad = copy.deepcopy(data)
            bad["revenue_charts"][0]["reported_subtotals"][0]["component_ids"] = component_ids
            with self.subTest(components=component_ids), self.assertRaises(ValueError):
                validate_draft(bad, packet)

    def test_unknown_cells_missing_period_and_wrong_header_are_rejected(self):
        data, packet = fixture()
        bad = copy.deepcopy(data)
        bad["revenue_charts"][0]["parts"][0]["amount_cell_id"] = "invented"
        with self.assertRaisesRegex(ValueError, "cell_outside_packet"):
            validate_draft(bad, packet)
        for label in (None, "2024", "202"):
            bad_packet = copy.deepcopy(packet)
            if label is None:
                bad_packet.pop("requested_period_label")
            else:
                bad_packet["requested_period_label"] = label
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_draft(data, bad_packet)

    def test_other_table_column_and_header_rowspan_do_not_establish_coverage(self):
        data, packet = fixture()
        for field, value in (("column_index", 1), ("colspan", 3)):
            bad = copy.deepcopy(packet)
            bad["tables"][0]["cells"][2][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "outside_period_header"):
                validate_draft(data, bad)
        bad = copy.deepcopy(packet)
        bad["tables"][0]["cells"][1]["rowspan"] = 2
        with self.assertRaisesRegex(ValueError, "outside_period_header"):
            validate_draft(data, bad)
        bad = copy.deepcopy(packet)
        other = {"id": "other-table", "block_id": "table-block", "source_dom_path": "//*[@id='other-table']",
                 "cells": [bad["tables"][0]["cells"].pop(2)]}
        bad["tables"].append(other)
        with self.assertRaisesRegex(ValueError, "must_share_table"):
            validate_draft(data, bad)

    def test_original_amounts_must_reconcile_and_unknown_or_zero_is_not_imputed(self):
        data, packet = fixture()
        for cid, text, error in (("b", "39", "does_not_reconcile"), ("total", "0", "positive_revenue"),
                                 ("total", "—", "amount_cell_number"), ("subtotal", "99", "subtotal_does_not_reconcile")):
            bad = copy.deepcopy(packet)
            next(c for c in bad["tables"][0]["cells"] if c["id"] == cid)["text"] = text
            before = copy.deepcopy(bad)
            with self.subTest(cell=cid, text=text), self.assertRaisesRegex(ValueError, error):
                validate_draft(data, bad)
            self.assertEqual(bad, before)


if __name__ == "__main__":
    unittest.main()
