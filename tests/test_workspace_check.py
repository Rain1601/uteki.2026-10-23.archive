import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from apps.review_workbench import app
from apps.review_workbench.workspace_check import COMPANIES, RELEASE, SOURCE, inspect_workspace
from uteki.infrastructure.document_sources.sec import text_hash


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "workspace"

    def write_json(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def check_named(self, name):
        return next(c for c in inspect_workspace(self.root)["checks"] if c["name"] == name)

    def test_missing_workspace_reports_paths_without_creating_state(self):
        result = inspect_workspace(self.root)
        self.assertFalse(result["ready"])
        missing = [c for c in result["checks"] if c["required"] and c["status"] == "missing"]
        self.assertIn(str(self.root / COMPANIES), [c["path"] for c in missing])
        self.assertIn(str(self.root / RELEASE / "evidence_bundle.json"), [c["path"] for c in missing])
        self.assertFalse(self.root.exists())

    def test_invalid_company_json_is_distinguished_from_missing_data(self):
        path = self.write_json(COMPANIES, {})
        path.write_text("{invalid", encoding="utf-8")
        check = self.check_named("Company list / 公司名单")
        self.assertEqual(check["status"], "invalid")
        self.assertIn("JSONDecodeError", check["detail"])
        self.assertFalse((self.root / "data/research_archive").exists())

    def test_excerpt_hashes_are_recomputed_without_repairing_the_input(self):
        path = self.write_json(SOURCE + "/review_excerpt.json", {
            "paragraphs": [{"ordinal": 1, "text": "changed", "text_hash": text_hash("original")}]
        })
        before = path.read_bytes()
        check = self.check_named("Excerpt integrity / 摘录完整性")
        self.assertEqual(check["status"], "invalid")
        self.assertFalse(check["required"])
        self.assertIn("1", check["detail"])
        self.assertEqual(path.read_bytes(), before)

    def test_source_bytes_are_checked_against_manifest_and_corruption_is_reported(self):
        raw = b"original filing"
        self.write_json(SOURCE + "/manifest.json", {"content_sha256": hashlib.sha256(raw).hexdigest()})
        source = self.root / SOURCE / "source.html.gz"
        source.write_bytes(gzip.compress(raw))
        self.assertEqual(self.check_named("Full SEC source / 完整 SEC 原文")["status"], "ok")
        source.write_bytes(gzip.compress(b"different filing"))
        self.assertEqual(self.check_named("Full SEC source / 完整 SEC 原文")["status"], "invalid")
        source.write_bytes(b"not gzip")
        self.assertEqual(self.check_named("Full SEC source / 完整 SEC 原文")["status"], "invalid")
        source.write_bytes(bytes.fromhex("1f8b0800000000000003070000000000000000"))
        self.assertEqual(self.check_named("Full SEC source / 完整 SEC 原文")["status"], "invalid")

    def test_malformed_excerpt_is_a_required_error(self):
        for paragraphs in ([], [None]):
            self.write_json(SOURCE + "/review_excerpt.json", {
                "paragraphs": paragraphs, "translation": {"notice_zh": "Candidate"}
            })
            check = self.check_named("Source excerpt / 证据摘录")
            self.assertEqual(check["status"], "invalid")
            self.assertTrue(check["required"])

    def test_incomplete_archive_fails_without_writing_lock_or_state(self):
        path = self.write_json("data/research_archive/state.json", {"snapshots": {}})
        before = path.read_bytes()
        check = self.check_named("Existing review state / 已有审核状态")
        self.assertEqual(check["status"], "invalid")
        self.assertTrue(check["required"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(path.with_suffix(".json.lock").exists())

    def test_valid_empty_archive_remains_unchanged(self):
        path = self.write_json("data/research_archive/state.json", {
            "schema_version": "1.1", "snapshots": {}, "comments": {}, "audit_events": []
        })
        before = path.read_bytes()
        self.assertEqual(self.check_named("Existing review state / 已有审核状态")["status"], "ok")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(path.with_suffix(".json.lock").exists())

    def test_tampered_release_cannot_be_reported_as_ready(self):
        self.write_json(RELEASE + "/business_map.json", {})
        self.write_json(RELEASE + "/evidence_bundle.json", {})
        self.write_json(RELEASE + "/manifest.json", {
            "artifacts": {"business_map.json": {"bytes": 2, "sha256": "incorrect"}}
        })
        check = self.check_named("Research release integrity / 研究数据发布完整性")
        self.assertEqual(check["status"], "invalid")
        self.assertTrue(check["required"])
        self.assertIn("integrity check", check["detail"])

    def test_cli_works_from_another_directory_and_returns_nonzero_for_missing_inputs(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_workspace.py"),
                                 "--root", str(self.root), "--json"], cwd=self.temp.name,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(json.loads(result.stdout)["ready"])
        self.assertFalse(self.root.exists())

    def test_startup_stops_before_server_or_archive_initialization(self):
        with patch.object(app, "ROOT", self.root), patch.object(sys, "argv", ["workbench"]), \
                patch.object(app, "make_handler") as handler, \
                patch.object(app, "ThreadingHTTPServer") as server, redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as error:
                app.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("Workspace data is incomplete", output.getvalue())
        handler.assert_not_called()
        server.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_check_only_does_not_start_server_even_when_inputs_are_ready(self):
        with patch.object(sys, "argv", ["workbench", "--check"]), \
                patch("apps.review_workbench.workspace_check.inspect_workspace", return_value={"ready": True, "checks": []}), \
                patch.object(app, "make_handler") as handler, \
                patch.object(app, "ThreadingHTTPServer") as server, redirect_stdout(io.StringIO()):
            app.main()
        handler.assert_not_called()
        server.assert_not_called()
