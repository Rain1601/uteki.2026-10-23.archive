"""Independent synthetic acceptance of the experimental parsing package."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("build_examples.py")
spec = importlib.util.spec_from_file_location("parser_package_examples", MODULE_PATH)
package = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = package
spec.loader.exec_module(package)


class ParserPackageAcceptance(unittest.TestCase):
    def fixture(self, root, *, company="synthetic-orion", period="2031-06-30", form="10-K"):
        dataset = root / "dataset"
        (dataset / "raw").mkdir(parents=True)
        raw = '''<html><body><ix:hidden><p>HIDDEN 98765</p></ix:hidden>
        <h1>PART I</h1><h2>ITEM 1. PRODUCTS</h2><p>甲\u00a0\u00a0乙\n  丙 &lt;script&gt;literal&lt;/script&gt; &amp; “quoted”</p>
        <table><tr><td>Outer intro <table><tr><th rowspan="2">Group</th><th colspan="2">Amount</th></tr>
        <tr><td>17</td><td>19 &amp; 21</td></tr></table>Outer end</td></tr></table>
        <img src="chart.jpg" alt="&lt;img onerror=bad&gt;">
        <h2>ITEM 2. LOCATIONS</h2><p>Other section.</p></body></html>'''.encode()
        selection = {"company_id": company, "document_id": "synthetic-document-" + company,
            "source_snapshot_id": "synthetic-snapshot-" + company,
            "source_url": "https://example.invalid/" + company + "/filing.html", "raw_sha256": package.sha(raw),
            "form_type": form, "report_period_end": period, "parser_version": package.PARSER,
            "export_version": package.EXPORT}
        source = {"company_id": company, "document_id": selection["document_id"],
            "source_snapshot_id": selection["source_snapshot_id"], "source_url": selection["source_url"],
            "source_sha256": selection["raw_sha256"], "raw_file_sha256": selection["raw_sha256"],
            "raw_file": "raw/source.html", "form": form, "period_end": period, "available_at": "2031-08-10",
            "parsed_mime_type": "text/html"}
        (dataset / "raw/source.html").write_bytes(raw)
        (dataset / "sources.json").write_bytes(package.canonical([source]))
        (dataset / "manifest.json").write_bytes(package.canonical({"files": {
            name: package.sha((dataset / name).read_bytes()) for name in ("sources.json", "raw/source.html")}}))
        return dataset, selection

    def test_same_input_different_output_paths_are_identical_and_human_view_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, selection = self.fixture(root)
            first, second = root / "one", root / "deep" / "two"
            package.build_package(dataset, selection, first)
            package.build_package(dataset, selection, second)
            a = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
            b = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(a, b)
            blocks = [json.loads(line) for line in (first / "blocks.jsonl").read_text().splitlines()]
            text = " ".join(b["text"] for b in blocks)
            self.assertIn('甲 乙 丙 <script>literal</script> & “quoted”', text)
            self.assertNotIn("HIDDEN", text)
            tables = [b["table"] for b in blocks if b["type"] == "table"]
            self.assertEqual([len(t["cells"]) for t in tables], [1, 4])
            self.assertEqual(tables[1]["cells"][0]["rowspan"], 2)
            self.assertEqual(tables[1]["cells"][1]["colspan"], 2)
            html = (first / "document.html").read_text()
            self.assertIn("&lt;script&gt;literal&lt;/script&gt;", html)
            self.assertNotIn("<script>", html)
            self.assertNotIn("<img ", html)
            assets = json.loads((first / "assets.json").read_text())
            self.assertEqual(assets["bytes_status"], "not_included")
            self.assertEqual(assets["ocr_status"], "not_run")
            self.assertEqual(package.verify_package(first)["cells_verified"], 5)

    def test_other_issuer_period_and_20f_are_explicit_not_sample_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, selection = self.fixture(root, company="synthetic-lyra", period="2030-09-30", form="20-F")
            package.build_package(dataset, selection, root / "out")
            source = json.loads((root / "out/source.json").read_text())
            self.assertEqual((source["company_id"], source["report_period_end"], source["form_type"]),
                             ("synthetic-lyra", "2030-09-30", "20-F"))

    def test_invalid_or_conflicting_scope_rejected_before_output(self):
        mutations = {"missing_company": lambda s: s.pop("company_id"),
            "blank_document": lambda s: s.update(document_id=" "),
            "other_company": lambda s: s.update(company_id="wrong-issuer"),
            "other_period": lambda s: s.update(report_period_end="2029-01-01"),
            "wrong_hash": lambda s: s.update(raw_sha256="0" * 64),
            "unknown_parser": lambda s: s.update(parser_version="future-unknown"),
            "unknown_export": lambda s: s.update(export_version="future-unknown"),
            "missing_source": lambda s: s.pop("source_snapshot_id"),
            "wrong_source": lambda s: s.update(source_snapshot_id="no-such-snapshot"),
            "credential_url": lambda s: s.update(source_url="https://user:secret@example.invalid/doc")}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, original = self.fixture(root)
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    selection = deepcopy(original)
                    mutate(selection)
                    output = root / label
                    with self.assertRaises(ValueError):
                        package.build_package(dataset, selection, output)
                    self.assertFalse(output.exists())

    def test_tampered_frozen_input_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, selection = self.fixture(root)
            package.build_package(dataset, selection, root / "out")
            before = (root / "out/manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                package.build_package(dataset, selection, root / "out")
            self.assertEqual((root / "out/manifest.json").read_bytes(), before)
            (dataset / "raw/source.html").write_bytes(b"changed source")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                package.build_package(dataset, selection, root / "changed")
            self.assertFalse((root / "changed").exists())

    def test_package_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, selection = self.fixture(root)
            package.build_package(dataset, selection, root / "out")
            with (root / "out/blocks.jsonl").open("ab") as stream:
                stream.write(b"{}\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                package.verify_package(root / "out")


if __name__ == "__main__":
    unittest.main()
