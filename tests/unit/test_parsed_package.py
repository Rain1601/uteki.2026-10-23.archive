"""Independent source and negative-boundary acceptance for production packages."""
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources import parsed_package as package


def synthetic_filing():
    return '''<html><body><ix:hidden><p>HIDDEN 98765</p></ix:hidden>
    <h1>PART I</h1><h2 id="business">ITEM 1. PRODUCTS</h2>
    <p>甲\u00a0\u00a0乙\n  丙 &lt;script&gt;literal&lt;/script&gt; &amp; “quoted”</p>
    <table><tr><td>Outer intro <table><tr><th rowspan="2">Group</th><th colspan="2">Amount</th></tr>
    <tr><td>17</td><td>19 &amp; 21</td></tr></table>Outer end</td></tr></table>
    <img src="chart.jpg" alt="&lt;img onerror=bad&gt;">
    <h2>ITEM 2. LOCATIONS</h2><p>Other section.</p></body></html>'''.encode()


def identity(raw, **changes):
    return {"company_id": "synthetic-orion", "document_id": "orion-document-2031",
        "source_snapshot_id": "orion-frozen-2031", "source_url": "https://example.invalid/orion/annual.html",
        "raw_sha256": package.sha(raw), "form_type": "10-K", "report_period_end": "2031-06-30",
        "available_at": "2031-08-10", "parser_version": package.PARSER,
        "export_version": package.EXPORT, **changes}


def file_bytes(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def replace_and_repin(folder, name, value):
    """Re-pin a corruption so structural validation is tested beyond the hash check."""
    raw = (b"".join(package.canonical(item) for item in value) if name.endswith("jsonl")
           else package.canonical(value))
    (folder / name).write_bytes(raw)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    entry = {"sha256": package.sha(raw), "bytes": len(raw)}
    manifest["files"][name] = entry
    if name in manifest["artifacts"]:
        manifest["artifacts"][name] = entry
    manifest["package_id"] = "parsed-" + package.sha(package.canonical({
        "source_identity_sha256": manifest["source_identity_sha256"],
        "files": manifest["files"], "runtime": manifest["runtime"]}))[:24]
    (folder / "manifest.json").write_bytes(package.canonical(manifest))


class ParsedPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = synthetic_filing()

    def build(self, name="package", **scope):
        output = self.root / name
        package.build_parsed_package(self.raw, identity(self.raw, **scope), output)
        return output

    def test_replay_has_identical_files_and_readable_exact_table_cells(self):
        first, second = self.build("one"), self.build("deeper/two")
        self.assertEqual(file_bytes(first), file_bytes(second))
        result = package.verify_parsed_package(first, expected_source=identity(self.raw))
        self.assertEqual(result["files_verified"], 15)
        self.assertEqual(result["cells_verified"], 5)
        reader = DocumentReader(first)
        texts = " ".join(block["text"] for block in reader.blocks)
        self.assertIn('甲 乙 丙 <script>literal</script> & “quoted”', texts)
        self.assertNotIn("HIDDEN", texts)
        tables = [block["table"] for block in reader.blocks if block["type"] == "table"]
        self.assertEqual([len(table["cells"]) for table in tables], [1, 4])
        self.assertEqual(tables[1]["cells"][0]["rowspan"], 2)
        self.assertEqual(tables[1]["cells"][1]["colspan"], 2)
        root_node = next(node for node in reader.index["nodes"] if node["kind"] == "document")
        hit = reader.search(root_node["node_id"], "甲 乙 丙")["hits"][0]
        self.assertTrue(reader.read(root_node["node_id"], hit["block_id"])["blocks"])
        markup = (first / "document.html").read_text()
        self.assertIn("&lt;script&gt;literal&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img ", markup)
        assets = json.loads((first / "assets.json").read_bytes())
        self.assertEqual((assets["bytes_status"], assets["ocr_status"], assets["vision_status"]),
                         ("not_included", "not_run", "not_run"))

    def test_explicit_other_company_period_form_and_nullable_update_period(self):
        output = self.build(company_id="synthetic-lyra", document_id="lyra-document",
            source_snapshot_id="lyra-frozen", source_url="https://example.invalid/lyra/annual.html",
            report_period_end="2030-09-30", available_at=None, form_type="20-F")
        source = json.loads((output / "source.json").read_bytes())
        self.assertEqual((source["company_id"], source["report_period_end"], source["form_type"], source["available_at"]),
                         ("synthetic-lyra", "2030-09-30", "20-F", None))
        update = self.build("update", form_type="OFFICIAL_UPDATE", report_period_end=None)
        self.assertIsNone(json.loads((update / "source.json").read_bytes())["report_period_end"])
        for name, changes in (("company", {"company_id": "another-company"}),
                              ("period", {"report_period_end": "2030-01-01"}),
                              ("snapshot", {"source_snapshot_id": "another-snapshot"})):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "expected source identity"):
                package.verify_parsed_package(update,
                    expected_source=identity(self.raw, **{"form_type": "OFFICIAL_UPDATE", "report_period_end": None, **changes}))

    def test_missing_or_unsupported_metadata_and_non_html_are_rejected_before_output(self):
        mutations = {"missing_company": lambda s: s.pop("company_id"),
            "blank_company": lambda s: s.update(company_id=" "),
            "missing_snapshot": lambda s: s.pop("source_snapshot_id"),
            "blank_document": lambda s: s.update(document_id=" "),
            "missing_available_at": lambda s: s.pop("available_at"),
            "missing_report_period": lambda s: s.pop("report_period_end"),
            "null_annual_period": lambda s: s.update(report_period_end=None),
            "wrong_hash": lambda s: s.update(raw_sha256="0" * 64),
            "unknown_parser": lambda s: s.update(parser_version="future"),
            "unknown_export": lambda s: s.update(export_version="future"),
            "unknown_form": lambda s: s.update(form_type="unknown"),
            "credential_url": lambda s: s.update(source_url="https://user:secret@example.invalid/filing")}
        for name, mutate in mutations.items():
            selection = identity(self.raw)
            mutate(selection)
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.build_parsed_package(self.raw, selection, self.root / name)
            self.assertFalse((self.root / name).exists())
        for name, raw in (("pdf", b"%PDF-1.4 unparsed"), ("json", b'{"data":"not a document"}'),
                          ("text", b"plain source text")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "HTML"):
                package.build_parsed_package(raw, identity(raw), self.root / name)
            self.assertFalse((self.root / name).exists())

    def test_full_merged_cell_occupancy_is_checked_not_only_cell_origins(self):
        for name, table in (("overlap", '<tr><td>A</td><td rowspan="2">B</td></tr><tr><td colspan="2">C</td></tr>'),
                            ("beyond", '<tr><td rowspan="3">A</td><td>B</td></tr><tr><td>C</td></tr>')):
            raw = ("<html><body><table>" + table + "</table></body></html>").encode()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "overlap|beyond"):
                package.build_parsed_package(raw, identity(raw), self.root / name)
            self.assertFalse((self.root / name).exists())

    def test_verify_checks_anchor_target_even_when_content_hashes_are_repinned(self):
        output = self.build()
        anchors = json.loads((output / "anchors.json").read_bytes())
        self.assertTrue(anchors)
        anchors[0]["target_block_id"] = "absent-block"
        replace_and_repin(output, "anchors.json", anchors)
        with self.assertRaisesRegex(ValueError, "anchor targets absent"):
            package.verify_parsed_package(output)

    def test_verify_checks_table_bounds_after_repinned_mutation(self):
        output = self.build()
        blocks = [json.loads(line) for line in (output / "blocks.jsonl").read_bytes().splitlines()]
        table = next(block["table"] for block in blocks if block["table"])
        table["cells"][0]["rowspan"] = table["row_count"] + 1
        replace_and_repin(output, "blocks.jsonl", blocks)
        with self.assertRaisesRegex(ValueError, "beyond table dimensions"):
            package.verify_parsed_package(output)

    def test_existing_output_preserved_and_modified_package_detected(self):
        output = self.build()
        before = file_bytes(output)
        with self.assertRaises(FileExistsError):
            package.build_parsed_package(self.raw, identity(self.raw), output)
        self.assertEqual(file_bytes(output), before)
        with (output / "blocks.jsonl").open("ab") as stream:
            stream.write(b"{}\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            package.verify_parsed_package(output)

    def test_old_and_new_parser_selection_matches_manifest_and_keeps_blocks(self):
        raw = b'<html><body><p>First <span id="inside">17</span></p><p>Next</p></body></html>'
        results = []
        for version in ('sec-source-blocks-v0.1.7', 'sec-source-blocks-v0.1.8', 'sec-source-blocks-v0.1.9', 'sec-source-blocks-v0.1.10', 'sec-source-blocks-v0.1.11'):
            folder = self.root / version
            package.build_parsed_package(raw, identity(raw, parser_version=version), folder)
            package.verify_parsed_package(folder, expected_source=identity(raw, parser_version=version))
            self.assertEqual(json.loads((folder/'manifest.json').read_bytes())['parser_version'], version)
            results.append(folder)
        self.assertEqual((results[0]/'blocks.jsonl').read_bytes(), (results[1]/'blocks.jsonl').read_bytes())
        self.assertNotEqual((results[0]/'anchors.json').read_bytes(), (results[1]/'anchors.json').read_bytes())


if __name__ == "__main__":
    unittest.main()
