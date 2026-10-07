from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_m0_review as review_tool
from scripts.prepare_m0_review import audit_evidence
from uteki.domain.documents import Document, Paragraph
from uteki.infrastructure.document_sources.sec import parse_sec_html, text_hash
from uteki.infrastructure.document_sources.snapshots import import_snapshot


class M0EvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.text = "Platforms , which generate fees."
        self.document = Document("filing", "https://example.test/filing.htm", "source-sha", (
            Paragraph(90, self.text, text_hash(self.text)),
        ))
        self.candidate = {"document_id": "filing", "evidence": [{
            "id": "e-platforms", "document_id": "filing", "source_url": self.document.source_url,
            "paragraph_ordinal": 90, "text_hash": text_hash(self.text),
        }]}
        self.excerpt = {"paragraphs": [{"ordinal": 90, "text": self.text, "text_hash": text_hash(self.text)}]}
        self.claims = {"claims": [{"id": "fees", "evidence_ids": ["e-platforms"]}]}
        self.spans = {"spans": [{"claim_id": "fees", "evidence_id": "e-platforms", "quote_en": "which generate fees."}]}

    def audit(self):
        return audit_evidence(self.document, self.candidate, self.excerpt, self.claims, self.spans)

    def test_excerpt_corruption_is_identified_without_rewriting_legacy(self):
        self.excerpt["paragraphs"][0]["text"] = "Platforms, which generate fees."
        original = deepcopy(self.excerpt)
        result = self.audit()
        self.assertTrue(result["can_rebind_source"])
        self.assertEqual(result["counts"]["matching_legacy_excerpts"], 0)
        issue = result["issues"][0]
        self.assertEqual(issue["kind"], "legacy_excerpt_difference")
        self.assertTrue(issue["stored_hash_matches_source"])
        self.assertEqual(issue["affected_claim_ids"], ["fees"])
        self.assertEqual(self.excerpt, original)
        self.assertEqual(result["semantic_review"], "pending_human_review")

    def test_changed_source_hash_prevents_mechanical_rebinding(self):
        self.candidate["evidence"][0]["text_hash"] = "different"
        result = self.audit()
        self.assertFalse(result["can_rebind_source"])
        self.assertEqual(result["counts"]["verified_evidence"], 0)

    def test_quote_must_match_source_and_the_named_claim(self):
        for edit in ({"quote_en": "unseen words"}, {"claim_id": "unknown"}, {"quote_en": ""}):
            with self.subTest(edit=edit):
                old = deepcopy(self.spans)
                self.spans["spans"][0].update(edit)
                result = self.audit()
                self.assertFalse(result["can_rebind_source"])
                self.assertEqual(result["counts"]["verified_spans"], 0)
                self.spans = old

    def test_wrong_document_or_url_is_not_accepted_on_hash_alone(self):
        for field in ("document_id", "source_url"):
            with self.subTest(field=field):
                old = deepcopy(self.candidate)
                self.candidate["evidence"][0][field] = "different"
                self.assertFalse(self.audit()["can_rebind_source"])
                self.candidate = old

    def test_duplicate_evidence_identity_is_rejected(self):
        self.candidate["evidence"].append(deepcopy(self.candidate["evidence"][0]))
        self.assertFalse(self.audit()["can_rebind_source"])

    def test_missing_claim_evidence_is_not_a_success(self):
        self.claims["claims"][0]["evidence_ids"].append("missing")
        self.assertFalse(self.audit()["can_rebind_source"])

    def test_missing_or_duplicate_span_is_not_a_complete_evidence_chain(self):
        original = deepcopy(self.spans)
        for rows in ([], original["spans"] * 2):
            with self.subTest(rows=rows):
                self.spans["spans"] = rows
                self.assertFalse(self.audit()["can_rebind_source"])


class M0ReviewPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "external-source"
        self.legacy = self.root / "external-legacy"
        self.legacy.mkdir()
        self.output = self.root / "review"
        self.when = "2026-09-18T12:00:00+00:00"
        paragraphs = [f"Paragraph {ordinal}." for ordinal in range(1, 92)]
        paragraphs[89] = "Platforms , which generate fees."
        raw = ("<html><body>" + "".join(f"<div>{text}</div>" for text in paragraphs) + "</body></html>").encode()
        source = {**review_tool.M0_IDENTITY, "source_snapshot_id": "legacy-source",
                  "content_sha256": hashlib.sha256(raw).hexdigest(), "paragraph_count": 91}
        import_snapshot(raw, source_manifest=source, assets={}, output_dir=self.snapshot,
                        retrieved_at=self.when, retrieval={"method": "synthetic_unit_fixture"})
        document = parse_sec_html(source["document_id"], source["source_url"], raw)
        paragraph = document.paragraphs[89]
        candidate = {
            "schema_version": "business-map-v0.1", "company_id": "alphabet",
            "document_id": document.id, "summary": "Synthetic evidence-review fixture.",
            "businesses": [{"id": "alphabet", "name": "Alphabet", "kind": "company",
                            "description": "Synthetic fixture", "evidence_ids": ["e-platforms"],
                            "review_status": "accepted", "approved_by": "historical reviewer"}],
            "relationships": [], "unknowns": [],
            "evidence": [{"id": "e-platforms", "document_id": document.id,
                          "source_url": document.source_url, "section_path": ["ITEM 1"],
                          "paragraph_ordinal": 90, "text_hash": paragraph.text_hash,
                          "support": "Fixture support", "approved_at": "historical"}],
            "metadata": {"source_snapshot_id": "legacy-source", "gold_status": "frozen",
                         "benchmark_version": "old-benchmark", "approved_by": "historical reviewer"},
            "approval": {"status": "approved"},
        }
        claims = {"schema_version": "old-claims", "source_snapshot_id": "legacy-source",
                  "benchmark_id": "old-benchmark", "status": "approved", "approved_by": "historical reviewer",
                  "claims": [{"id": "fees", "business_id": "alphabet", "field": "description",
                              "label_en": "Fees", "label_zh": "收费", "value_en": "Generate fees",
                              "value_zh": "产生费用", "basis": "explicit", "evidence_ids": ["e-platforms"],
                              "review_status": "accepted", "adopted_at": "historical"}]}
        spans = {"schema_version": "old-spans", "source_snapshot_id": "legacy-source", "status": "approved",
                 "approved_by": "historical reviewer",
                 "spans": [{"claim_id": "fees", "evidence_id": "e-platforms",
                            "quote_en": "which generate fees.", "quote_zh": "产生费用",
                            "approved_by": "historical reviewer"}]}
        excerpt = {"source_snapshot_id": "legacy-source", "paragraphs": [
            {"ordinal": 90, "text": "Platforms, which generate fees.", "text_hash": paragraph.text_hash}
        ]}
        for name, value in zip(review_tool.LEGACY_FILES, (candidate, claims, spans, excerpt)):
            (self.legacy / name).write_bytes(review_tool.encoded(value))

    def prepare(self, output=None):
        return review_tool.prepare_review(self.snapshot, self.legacy, self.legacy / "review_excerpt.json",
                                          output or self.output, prepared_at=self.when)

    def read(self, name, root=None):
        return json.loads(((root or self.output) / name).read_bytes())

    def reseal_artifact(self, name, value, root=None):
        root = root or self.output
        raw = review_tool.encoded(value)
        (root / name).write_bytes(raw)
        manifest = self.read("manifest.json", root)
        manifest["artifacts"][name] = review_tool.fingerprint(name, raw)
        (root / "manifest.json").write_bytes(review_tool.encoded(manifest))

    def test_package_can_move_and_replay_after_all_external_inputs_are_removed(self):
        manifest = self.prepare()
        moved = self.root / "independent-copy"
        shutil.copytree(self.output, moved)
        shutil.rmtree(self.snapshot)
        shutil.rmtree(self.legacy)
        before = {str(path.relative_to(moved)): path.read_bytes() for path in moved.rglob("*") if path.is_file()}
        self.assertEqual(review_tool.verify_review(moved), manifest)
        after = {str(path.relative_to(moved)): path.read_bytes() for path in moved.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        replay = self.root / "replayed"
        repeated = review_tool.prepare_review(moved / "source_snapshot", moved / "legacy_inputs",
                                              moved / "legacy_inputs/review_excerpt.json", replay,
                                              prepared_at=self.when)
        self.assertEqual(repeated, manifest)
        for name, record in manifest["artifacts"].items():
            self.assertEqual(record["path"], name)
            self.assertFalse(Path(record["path"]).is_absolute())
            self.assertEqual((moved / name).read_bytes(), (replay / name).read_bytes())

    def test_fresh_candidates_do_not_inherit_old_approvals_or_version_identity(self):
        originals = {name: (self.legacy / name).read_bytes() for name in review_tool.LEGACY_FILES}
        manifest = self.prepare()
        for name in review_tool.LEGACY_FILES:
            self.assertEqual((self.legacy / name).read_bytes(), originals[name])
            self.assertEqual((self.output / "legacy_inputs" / name).read_bytes(), originals[name])
        business = self.read("business_map.json")
        self.assertEqual(business["schema_version"], "m0-review-business-map-v1")
        self.assertNotEqual(business["schema_version"], json.loads(originals["business_map.json"])["schema_version"])
        self.assertEqual(business["businesses"][0]["review_status"], "candidate")
        self.assertEqual(business["metadata"]["benchmark_version"], manifest["package_id"])
        self.assertEqual(business["metadata"]["gold_status"], "not_frozen")
        self.assertNotIn("approval", business)
        for name in ("business_map.json", "claims.json", "evidence_spans.json"):
            text = (self.output / name).read_text()
            self.assertNotIn("historical reviewer", text)
            self.assertNotIn("old-benchmark", text)
            self.assertNotIn("old-schema-version", text)
            self.assertNotIn('"adopted_at"', text)
        questions = self.read("review_questions.json")
        self.assertIsNone(questions["reviewer"])
        self.assertIsNone(questions["reviewed_at"])
        self.assertTrue(all(item["answer"] is None for item in questions["questions"]))
        audit = self.read("legacy_audit.json")
        self.assertEqual(audit["counts"]["matching_legacy_excerpts"], 0)
        self.assertTrue(audit["can_rebind_source"])
        self.assertEqual(self.read("review_excerpt.json")["paragraphs"][0]["text"], "Platforms , which generate fees.")

    def test_resealed_answers_approvals_audit_or_old_identity_fail_replay(self):
        self.prepare()
        edits = [
            ("review_questions.json", lambda value: value["questions"][0].update(answer="approved")),
            ("business_map.json", lambda value: value["businesses"][0].update(review_status="accepted")),
            ("business_map.json", lambda value: value.update(schema_version="old-schema-version")),
            ("claims.json", lambda value: value.update(benchmark_id="old-benchmark")),
            ("legacy_audit.json", lambda value: value["counts"].update(verified_evidence=999)),
        ]
        for index, (name, edit) in enumerate(edits):
            with self.subTest(name=name, index=index):
                folder = self.root / f"tampered-{index}"
                shutil.copytree(self.output, folder)
                value = self.read(name, folder)
                edit(value)
                self.reseal_artifact(name, value, folder)
                with self.assertRaisesRegex(ValueError, "replay"):
                    review_tool.verify_review(folder)

    def test_bundled_raw_source_corruption_is_rejected(self):
        self.prepare()
        raw_path = self.output / "source_snapshot/source.html.gz"
        raw_path.write_bytes(b"corrupted-source")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            review_tool.verify_review(self.output)

    def test_manifest_metadata_and_unsafe_artifact_paths_are_rejected(self):
        original = self.prepare()
        modifications = [
            {"status": "approved"}, {"gold_status": "frozen"}, {"source_snapshot_id": "legacy-source"},
            {"automatic_adoption": True},
            {"artifacts": {"../outside": {"path": "../outside", "bytes": 0, "sha256": "0" * 64}}},
            {"artifacts": {"/tmp/outside": {"path": "/tmp/outside", "bytes": 0, "sha256": "0" * 64}}},
        ]
        for changes in modifications:
            with self.subTest(changes=changes):
                (self.output / "manifest.json").write_bytes(review_tool.encoded({**original, **changes}))
                with self.assertRaises(ValueError):
                    review_tool.verify_review(self.output)

    def test_missing_extra_and_symlink_files_are_rejected(self):
        self.prepare()
        extra = self.output / "untracked.txt"
        extra.write_text("untracked")
        with self.assertRaises(ValueError):
            review_tool.verify_review(self.output)
        extra.unlink()
        questions = self.output / "review_questions.json"
        questions.unlink()
        with self.assertRaises(ValueError):
            review_tool.verify_review(self.output)
        questions.symlink_to(self.legacy / "claims.json")
        with self.assertRaises(ValueError):
            review_tool.verify_review(self.output)

    def test_mixed_legacy_source_identities_fail_before_publication(self):
        path = self.legacy / "claims.json"
        claims = json.loads(path.read_bytes())
        claims["source_snapshot_id"] = "another-version"
        path.write_bytes(review_tool.encoded(claims))
        with self.assertRaisesRegex(ValueError, "share one identity"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_incomplete_claim_content_is_not_published_as_a_reviewable_package(self):
        path = self.legacy / "claims.json"
        claims = json.loads(path.read_bytes())
        del claims["claims"][0]["value_en"]
        path.write_bytes(review_tool.encoded(claims))
        with self.assertRaisesRegex(ValueError, "required review content"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_write_or_manifest_failures_leave_no_published_package(self):
        write = review_tool._write_new
        for fail_name in ("claims.json", ".manifest.json.tmp"):
            with self.subTest(fail_name=fail_name):
                def failed(path, raw):
                    if path.name == fail_name:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(raw[:5])
                        raise OSError("simulated write failure")
                    write(path, raw)
                with patch.object(review_tool, "_write_new", side_effect=failed):
                    with self.assertRaisesRegex(OSError, "write failure"):
                        self.prepare()
                self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "manifest.json"
        sentinel.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(sentinel.read_bytes(), b"existing")

    def test_cli_verifies_without_input_paths_or_writes_and_returns_nonzero_on_corruption(self):
        self.prepare()
        shutil.rmtree(self.snapshot)
        shutil.rmtree(self.legacy)
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(review_tool.main(["--verify", str(self.output)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "candidate_pending_human_review")
        (self.output / "claims.json").write_bytes(b"corrupt")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(review_tool.main(["--verify", str(self.output)]), 1)
        self.assertIn("integrity mismatch", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
