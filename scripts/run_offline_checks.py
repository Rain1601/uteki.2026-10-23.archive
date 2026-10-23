#!/usr/bin/env python3
"""Run the offline regression set for the Data core and the kept local tools.

No dependency installation, document download or model execution is requested.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]

# New-core suites are discovered per directory (they have no __init__.py).
CORE_SUITES = ("tests/unit/data_platform", "tests/integration/data_platform")
AGENT_SUITES = ("tests/unit/data_platform_agent", "tests/integration/data_platform_agent")
# Kept tools outside the Data core, run by module name from the checkout root.
CORE_MODULES = (
    "tests.test_offline_checks",
    "tests.unit.test_claude_dialogue",
    "tests.unit.test_claude_dialogue_http",
    "tests.unit.test_claude_dialogue_integration",
    "tests.unit.test_claude_dialogue_service",
)

# A test that depends on the installed environment is excluded by module name,
# never silently: --list shows each one with the command that does run it.
ENVIRONMENT_TESTS = {
    "test_gateway_sdk_wire": "needs the agent extra (Claude SDK); runs under --integration in the SDK env",
    "test_content_processes": "asserts no agent SDK is installed; run it alone in the data-only env (LOCAL_DEVELOPMENT §2)",
}
INTEGRATION_EXCLUDED = ("test_content_processes",)

JAVASCRIPT_TESTS = ("tests/claude_dialogue.test.cjs", *sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "apps/uteki_zero").glob("*.test.mjs")))


def run_check(label: str, command: list[str]) -> int:
    print(f"\n{label}", flush=True)
    env = os.environ.copy()
    # The checkout root makes tests/apps/scripts importable; uteki itself comes
    # from the interpreter's installed (editable or regular) package.
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    except OSError as error:
        print(f"{label} could not start: {error}", file=sys.stderr, flush=True)
        return 1
    return result.returncode


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


# 子进程内执行：逐目录 discover，按模块名排除环境相关测试，并保留导入失败等原始结果。
def _run_python(integration: bool, verbose: bool) -> int:
    loader = unittest.TestLoader()
    excluded = set(INTEGRATION_EXCLUDED if integration else ENVIRONMENT_TESTS)
    suite = unittest.TestSuite()
    for folder in CORE_SUITES + (AGENT_SUITES if integration else ()):
        found = loader.discover(str(ROOT / folder), pattern="test_*.py", top_level_dir=str(ROOT / folder))
        suite.addTests(test for test in _iter_tests(found) if test.id().split(".")[0] not in excluded)
    suite.addTests(loader.loadTestsFromNames(CORE_MODULES))
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


def show_scope(integration: bool) -> None:
    suites = CORE_SUITES + (AGENT_SUITES if integration else ())
    print("Python (discovered per directory):")
    for folder in suites:
        print(f"  {folder}")
    print("Python modules:")
    for name in CORE_MODULES:
        print(f"  {name}")
    print("\nExcluded environment-dependent tests:")
    for name, reason in ENVIRONMENT_TESTS.items():
        if integration and name not in INTEGRATION_EXCLUDED:
            continue
        print(f"  {name}: {reason}")
    if not integration:
        print("\n--integration adds the agent suites; run it with the non-editable SDK env python.")
    print("\nJavaScript: " + ", ".join(JAVASCRIPT_TESTS))
    print("No dependency installation, document download or model execution is requested.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--integration", action="store_true",
        help="also run the agent suites (needs the agent extra, local loopback and subprocess permissions)",
    )
    parser.add_argument("--list", action="store_true", help="show the selected scope without running tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="show each Python test name")
    parser.add_argument("--python-only-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.python_only_child:
        return _run_python(args.integration, args.verbose)
    if args.list:
        show_scope(args.integration)
        return 0

    child = [sys.executable, str(Path(__file__).resolve()), "--python-only-child"]
    child += ["--integration"] if args.integration else []
    child += ["--verbose"] if args.verbose else []
    label = "Data core + agent suites: Python" if args.integration else "Offline core: Python"
    python_status = run_check(label, child)
    javascript_status = run_check("Offline core: JavaScript", ["node", "--test", *JAVASCRIPT_TESTS])
    print(f"\nExit statuses: Python={python_status}; JavaScript={javascript_status}", flush=True)
    return 0 if python_status == javascript_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
