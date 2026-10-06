"""Source preview isolation, exact locators and registered real-source checks."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from lxml import html

from apps.review_workbench.pages import source_preview as preview


ROOT = Path(__file__).resolve().parents[2]


class WorkspaceSourcePreviewTests(unittest.TestCase):
    def fixture(self, raw, *, mime="text/html", blocks=None, parser="sec-source-blocks-v0.1.7"):
        self.raw = raw.encode() if isinstance(raw, str) else raw
        self.source = {"source_snapshot_id": "cedar-source", "company_id": "cedar",
                       "source_sha256": hashlib.sha256(self.raw).hexdigest()}
        self.dataset = {"id": "cedar", "sources": [self.source],
                        "blocks": {"cedar-source": blocks or []},
                        "indexes": {"cedar-source": {"parser_version": parser}}}
        self.mime = mime
        return {"dataset": ["cedar"], "source": ["cedar-source"]}

    def load(self, selection, **raw_changes):
        raw = {"content": self.raw, "mime_type": self.mime,
               "sha256": hashlib.sha256(self.raw).hexdigest(), **raw_changes}
        with patch.object(preview, "load_dataset", return_value=deepcopy(self.dataset)) as dataset_loader, \
             patch.object(preview, "load_raw_source", return_value=raw) as raw_loader:
            result = preview.load_source_preview(ROOT, selection)
            dataset_loader.assert_called_once_with(ROOT, selection["dataset"][0])
            raw_loader.assert_called_once_with(ROOT, selection["dataset"][0], selection["source"][0])
            return result

    def test_scope_must_be_single_explicit_dataset_and_source(self):
        with patch.object(preview, "load_dataset") as loader:
            for selection in ({}, {"dataset": ["cedar"]},
                              {"dataset": ["cedar"], "source": [""]},
                              {"dataset": ["cedar", "birch"], "source": ["cedar-source"]},
                              {"dataset": "cedar", "source": ["cedar-source"]},
                              {"dataset": ["cedar"], "source": ["cedar-source"], "path": ["/tmp/x"]}):
                with self.subTest(selection=selection), self.assertRaises(ValueError):
                    preview.load_source_preview(ROOT, selection)
            loader.assert_not_called()

    def test_foreign_source_or_block_rejected_before_source_read(self):
        selection = self.fixture("<html><body><p>Cedar</p></body></html>")
        with patch.object(preview, "load_dataset", return_value=self.dataset), \
             patch.object(preview, "load_raw_source") as raw_loader:
            for change in ({"source": ["birch-source"]}, {"block": ["birch-block"]}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    preview.load_source_preview(ROOT, selection | change)
            raw_loader.assert_not_called()

    def test_duplicate_source_or_block_identity_is_rejected(self):
        selection = self.fixture("<p>Cedar</p>", blocks=[{"block_id": "same"}, {"block_id": "same"}])
        with patch.object(preview, "load_dataset", return_value=self.dataset), self.assertRaisesRegex(ValueError, "ambiguous"):
            preview.load_source_preview(ROOT, selection | {"block": ["same"]})
        self.dataset["sources"].append(dict(self.source))
        with patch.object(preview, "load_dataset", return_value=self.dataset), self.assertRaisesRegex(ValueError, "ambiguous"):
            preview.load_source_preview(ROOT, selection)

    def test_source_bytes_and_declared_hash_must_match_selected_snapshot(self):
        selection = self.fixture("<p>Cedar</p>")
        for changes in ({"sha256": "0" * 64}, {"content": b"<p>Birch</p>"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "Preview bytes differ"):
                self.load(selection, **changes)

    def test_response_copy_highlights_exact_table_and_keeps_original_bytes(self):
        selection = self.fixture(
            '<html><head></head><body><a href="#cash">Cash flow</a>'
            '<table id="cash"><tr><td>Operating cash</td><td>123</td></tr></table>'
            '<p>Other content</p></body></html>',
            blocks=[{"block_id": "cash-block", "type": "table", "text": "Operating cash123",
                     "dom_path": "/html/body/table", "source_anchor": "cash"}])
        before = self.raw
        result = self.load(selection | {"block": ["cash-block"]})
        doc = html.fromstring(result["content"])
        self.assertEqual(result["locator_status"], "located")
        self.assertEqual(result["locator_precision"], "block")
        self.assertEqual(result["fragment"], "workspace-evidence")
        self.assertEqual(doc.get_element_by_id("workspace-evidence").tag, "table")
        self.assertIn("Other content", doc.text_content())
        self.assertEqual(doc.xpath("//a")[0].get("href"), "#workspace-evidence")
        self.assertEqual(self.raw, before)
        self.assertEqual(result["source_sha256"], hashlib.sha256(before).hexdigest())
        self.assertNotEqual(result["content"], before)

    def test_dom_path_requires_exact_text_and_does_not_fuzzy_search_elsewhere(self):
        selection = self.fixture('<html><body><p>Wrong number 42</p><p>Right number 24</p></body></html>',
            blocks=[{"block_id": "number", "type": "paragraph", "text": "Right number 24",
                     "dom_path": "/html/body/p[1]"}])
        result = self.load(selection | {"block": ["number"]})
        self.assertEqual(result["locator_status"], "unavailable")
        self.assertEqual(result["fragment"], "")
        self.assertNotIn('id="workspace-evidence"', result["content"].decode())
        self.assertIn("Right number 24", result["content"].decode())

    def test_duplicate_anchor_never_selects_first_match(self):
        selection = self.fixture('<html><body><p id="cash">Cash 42</p><p id="cash">Cash 42</p></body></html>',
            blocks=[{"block_id": "cash", "type": "paragraph", "text": "Cash 42", "source_anchor": "cash"}])
        self.assertEqual(self.load(selection | {"block": ["cash"]})["locator_status"], "unavailable")

    def test_unique_recorded_dom_path_disambiguates_repeated_text(self):
        selection = self.fixture('<html><body><p>Cash 42</p><p>Cash 42</p></body></html>',
            blocks=[{"block_id": "cash", "type": "paragraph", "text": "Cash 42", "dom_path": "/html/body/p[2]"}])
        doc = html.fromstring(self.load(selection | {"block": ["cash"]})["content"])
        paragraphs = doc.xpath("//p")
        self.assertIsNone(paragraphs[0].get("id"))
        self.assertEqual(paragraphs[1].get("id"), "workspace-evidence")

    def test_hidden_legacy_block_is_not_reported_as_visible_evidence(self):
        selection = self.fixture('<html><body><p hidden>Hidden 42</p></body></html>',
            blocks=[{"block_id": "hidden", "type": "paragraph", "text": "Hidden 42", "dom_path": "/html/body/p"}],
            parser="sec-source-blocks-v0.1.3")
        self.assertEqual(self.load(selection | {"block": ["hidden"]})["locator_status"], "unavailable")

    def test_source_scripts_navigation_and_remote_resources_are_isolated(self):
        selection = self.fixture('''<html><head><base href="https://example.test/"><meta http-equiv="refresh" content="0;url=https://example.test/">
            <link rel="stylesheet" href="https://example.test/style.css"></head><body onload="bad()">
            <script>bad()</script><iframe srcdoc="bad"></iframe><object data="https://example.test/x"></object>
            <form action="https://example.test/submit"><input autofocus><button formaction="https://example.test/other">Submit</button></form>
            <a href="javascript:bad()" target="_top" ping="https://example.test/">Unsafe</a>
            <img src="https://example.test/x.png" onerror="bad()" srcset="https://example.test/y.png 2x">
            <p id="workspace-evidence">Content</p></body></html>''')
        result = self.load(selection)
        doc = html.fromstring(result["content"])
        self.assertEqual(result["locator_status"], "not_requested")
        self.assertEqual(result["headers"]["Content-Security-Policy"], preview.PREVIEW_CSP)
        self.assertTrue(preview.PREVIEW_CSP.startswith("sandbox;"))
        self.assertIn("script-src 'none'", preview.PREVIEW_CSP)
        self.assertNotIn("allow-scripts", preview.PREVIEW_CSP)
        self.assertFalse(doc.xpath("//script|//iframe|//object|//base|//link"))
        self.assertFalse(doc.xpath("//*[@onload or @onerror or @action or @formaction or @srcset or @autofocus or @target or @ping]"))
        self.assertFalse(doc.xpath("//a[@href]|//img[@src]|//*[@id='workspace-evidence']"))
        self.assertFalse(doc.xpath("//meta[translate(@http-equiv,'REFSH','refsh')='refresh']"))
        self.assertIn("Content", doc.text_content())

    def test_text_highlight_requires_unique_exact_occurrence_and_escapes_markup(self):
        for raw, expected in (("Alpha <script>42</script> Omega", "located"),
                              ("<script>42</script> twice <script>42</script>", "unavailable")):
            selection = self.fixture(raw, mime="text/plain", blocks=[{
                "block_id": "text", "text": "<script>42</script>", "type": "paragraph"}])
            result = self.load(selection | {"block": ["text"]})
            doc = html.fromstring(result["content"])
            self.assertEqual(result["locator_status"], expected)
            self.assertEqual(result["mime_type"], "text/html")
            self.assertFalse(doc.xpath("//script"))
            self.assertIn(raw, doc.text_content())

    def test_pdf_uses_only_explicit_pdf_page_and_retains_original_bytes(self):
        for mapping, expected in (({"reported_page": 99}, "unavailable"),
                                  ({"pdf_page": 3, "reported_page": 99}, "located"),
                                  ({"pdf_page": True}, "unavailable"),
                                  ({"pdf_page": "3"}, "unavailable"),
                                  ({"pdf_page": 0}, "unavailable")):
            selection = self.fixture(b"%PDF-synthetic-fixture", mime="application/pdf", blocks=[{
                "block_id": "pdf-block", "type": "paragraph", "text": "Cash", **mapping}])
            result = self.load(selection | {"block": ["pdf-block"]})
            self.assertEqual(result["locator_status"], expected)
            self.assertEqual(result["content"], self.raw)
            self.assertEqual(result["fragment"], "page=3" if expected == "located" else "")
            self.assertEqual(result["locator_precision"], "page" if expected == "located" else "none")


class RegisteredSourcePreviewAcceptanceTests(unittest.TestCase):
    def test_real_amd_and_tsmc_operating_cash_flow_tables_locate_without_mutation(self):
        # Explicit pilot fixtures are test-only; the reusable viewer has no issuer defaults.
        cases = (("amd-annual-v2", "source-291485b98a75d8cfabe47571", "block-000686-a6e8806b"),
                 ("tsmc-annual-v2", "source-6719837a8d24b2b7df359f29", "block-001166-04f27bf6"))
        if not (ROOT / "data/evaluation_views/data-agent-v1.json").is_file():
            self.skipTest("Local registered real-source fixtures are not present")
        for dataset_id, source_id, block_id in cases:
            with self.subTest(dataset=dataset_id):
                dataset = preview.load_dataset(ROOT, dataset_id)
                source = next(item for item in dataset["sources"] if item["source_snapshot_id"] == source_id)
                path = ROOT / dataset["storage"]["dataset_path"] / source["raw_file"]
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                result = preview.load_source_preview(ROOT, {"dataset": [dataset_id], "source": [source_id], "block": [block_id]})
                after = hashlib.sha256(path.read_bytes()).hexdigest()
                doc = html.fromstring(result["content"])
                self.assertEqual(result["locator_status"], "located")
                self.assertEqual(result["locator_precision"], "block")
                self.assertEqual(doc.get_element_by_id("workspace-evidence").tag, "table")
                self.assertEqual(before, after)
                self.assertEqual(result["source_sha256"], before)
                self.assertEqual(result["source_snapshot_id"], source_id)
        with self.assertRaises(ValueError):
            preview.load_source_preview(ROOT, {"dataset": ["amd-annual-v2"], "source": [cases[1][1]]})


if __name__ == "__main__":
    unittest.main()
