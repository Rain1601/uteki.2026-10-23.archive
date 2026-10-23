"""The check entry point must not turn missing tools or failed checks into green runs."""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_offline_checks as checks


class OfflineChecksTests(unittest.TestCase):
    def test_either_language_failure_makes_the_whole_run_fail(self):
        for statuses in ((1, 0), (0, 1), (1, 1), (-15, 0)):
            with self.subTest(statuses=statuses), patch.object(checks, "run_check", side_effect=statuses) as run:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(checks.main([]), 1)
                self.assertEqual(run.call_count, 2)

    def test_missing_runtime_fails_with_an_actionable_error(self):
        with patch.object(checks.subprocess, "run", side_effect=FileNotFoundError("node not found")):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertNotEqual(checks.run_check("JavaScript", ["node", "--test"]), 0)
        self.assertIn("node not found", error.getvalue())

    def test_subprocess_uses_checkout_root_and_returns_failure_unchanged(self):
        # Real child process: exercises cwd/env handling and failure propagation.
        command = [sys.executable, "-c", (
            "import os, pathlib, sys; "
            "assert pathlib.Path.cwd() == pathlib.Path(sys.argv[1]); "
            "assert os.environ['OPENAI_AGENTS_DISABLE_TRACING'] == '1'; "
            "raise SystemExit(7)"
        ), str(checks.ROOT)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checks.run_check("intentional failure", command), 7)

    def test_cli_scope_can_be_read_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, str(checks.ROOT / "scripts/run_offline_checks.py"), "--list"],
                cwd=folder, text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests/unit/data_platform", result.stdout)
        self.assertIn("test_content_processes", result.stdout)
        self.assertIn("tests/claude_dialogue.test.cjs", result.stdout)


if __name__ == "__main__":
    unittest.main()
