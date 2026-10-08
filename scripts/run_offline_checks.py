#!/usr/bin/env python3
"""Run the explicit portable regression set, or opt in to all local-data tests."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

# Keep this allowlist explicit: a missing fixture is an error, not a reason to
# silently remove a test. Whole modules/classes also include future test methods.
CORE_TESTS = (
    "tests.test_evaluator",
    "tests.test_m0_preparation",
    "tests.test_offline_checks",
    "tests.test_transfer_local_state",
    "tests.test_research_archive_ui",
    "tests.test_research_workflow_smoke",
    "tests.test_visual_system",
    "tests.test_workbench_structure",
    "tests.test_workspace_check",
    "tests.unit.test_annual_context",
    "tests.unit.test_annual_narrative_runner",
    "tests.unit.test_archive_rerun",
    "tests.unit.test_agent_runs_history.HistoricalRunsTests",
    "tests.unit.test_agent_runs_live",
    "tests.unit.test_agent_runs_page",
    "tests.unit.test_agent_run_results.AgentResultTests",
    "tests.unit.test_agent_run_results.LiveResultIntegrationTests",
    "tests.unit.test_agent_results_page",
    "tests.unit.test_agent_result_routes",
    "tests.unit.test_run_scores",
    "tests.unit.test_run_observation",
    "tests.unit.test_observation_relocation",
    "tests.unit.test_workspace_routes.WorkspaceRoutesTests.test_root_redirects_to_unselected_data_workspace",
    "tests.unit.test_business_map_agent",
    "tests.unit.test_business_runtime_materials",
    "tests.unit.test_business_system_task",
    "tests.unit.test_business_coverage_contract",
    "tests.unit.test_business_coverage_contract_v2",
    "tests.unit.test_business_coverage_diagnostics",
    "tests.unit.test_business_coverage_run",
    "tests.unit.test_business_coverage_recovery",
    "tests.unit.test_business_coverage_continuation",
    "tests.unit.test_business_evidence_projection",
    "tests.unit.test_business_granularity_run",
    "tests.unit.test_business_semantic_critic",
    "tests.unit.test_business_critic_revision",
    "tests.unit.test_bounded_retry",
    "tests.unit.test_coverage_audit",
    "tests.unit.test_acquisition_catalog_coverage",
    "tests.unit.test_business_map_models.BusinessMapModelTests.test_rejects_unknown_evidence_reference",
    "tests.unit.test_business_map_models.BusinessMapModelTests.test_accepts_consistent_map",
    "tests.unit.test_business_map_models.BusinessMapModelTests.test_pilot_matches_domain_contract",
    "tests.unit.test_business_map_models.BusinessMapModelTests.test_benchmark_candidate_matches_domain_contract",
    "tests.unit.test_call_costs",
    "tests.unit.test_model_configuration",
    "tests.unit.test_model_trial_registration",
    "tests.unit.test_context_regression.ContextRegressionTests.test_compound_not_list",
    "tests.unit.test_evidence_math.EvidenceMathTests.test_numeric_cells_not_permissive_text",
    "tests.unit.test_hypothesis_contract",
    "tests.unit.test_index_artifact_publication",
    "tests.unit.test_narrative_reliability",
    "tests.unit.test_nested_source_blocks.NestedBlocksTests.test_container_text_before_and_after_table_is_retained",
    "tests.unit.test_numeric_review.PercentageReviewTests.test_numbers_are_scoped_to_citations_not_global_ledger",
    "tests.unit.test_numeric_review.PercentageReviewTests.test_failed_calculation_does_not_cover_number",
    "tests.unit.test_reading_annotations.ReadingAnnotationTests",
    "tests.unit.test_reading_groups.ReadingGroupsTests.test_boundary_and_cross_page",
    "tests.unit.test_reading_groups.ReadingGroupsTests.test_no_merge_unrelated_prose",
    "tests.unit.test_report_revisions",
    "tests.unit.test_research_archive",
    "tests.unit.test_research_archive_context",
    "tests.unit.test_research_archive_routes.ArchiveRoutesTests.test_redundant_pages_redirect_to_company_children",
    "tests.unit.test_researcher_streams",
    "tests.unit.test_sec_document_index.SecDocumentIndexUnitTests",
    "tests.unit.test_sec_source",
    "tests.unit.test_source_snapshots",
    "tests.unit.test_toc_link_roles",
)

# Documentation for the deliberate boundary; --integration uses unchanged
# unittest discovery, so these tests keep their original assertions and skips.
LOCAL_DATA_TESTS = {
    "test_reproducibility_pilot": "explicit frozen AMD source blocks and pre-registered pilot references",
    "test_agent_run_results.FrozenResultIntegrationTests": "explicit frozen AMD model trials and historical runs",
    "test_agent_runs_history.FrozenAMDIntegrationTests": "explicitly registered AMD parent/query/batch/direct manifests and source dataset",
    "test_analysis_comparison": "document-reader experiment manifest and pinned source indexes",
    "test_annual_report_view": "frozen hypothesis experiment, answers and evidence",
    "test_cloud_analysis": "approved Google Cloud research release and analysis runs",
    "test_cloud_llm": "Alphabet source snapshot and reviewed Google Cloud releases",
    "test_cloud_recovery": "approved Cloud release, source snapshot and recovery runs",
    "test_cloud_spike": "Alphabet source snapshot and Google Cloud benchmark",
    "test_codex_hypothesis_mvp": "frozen annual/quarterly hypothesis experiment",
    "test_company_data": "Alphabet document catalog and source indexes",
    "test_company_universe": "original 50-company universe",
    "test_context_regression (remaining methods)": "source indexes and multi-query experiment records",
    "test_document_library": "acquired filing catalog, originals and indexes",
    "test_document_reader": "quarterly source index and document-reader experiment",
    "test_earnings_materials": "earnings catalog, originals, indexes and routes",
    "test_reading_groups (remaining method)": "Alphabet source index and reading groups",
    "test_research_archive_routes (remaining methods)": "local archive imports, company universe and material routes",
    "test_research_data": "v0.2/v0.3 business-map benchmarks, sources and research releases",
    "test_review_workbench": "research releases, company universe and frozen sources",
    "test_business_map_models (remaining methods)": "v0.2/v0.3 benchmark candidates",
    "test_evidence_math (remaining method)": "actual Alphabet revenue table",
    "test_nested_source_blocks (remaining method)": "actual quarterly filing and indexed blocks",
    "test_numeric_review (remaining method)": "immutable annual-narrative experiment",
    "test_reading_annotations.AnnotationRoutesTests": "inherits all local archive route tests",
    "test_sec_document_index.AlphabetDocumentIndexIntegrationTests": "frozen Alphabet source and index",
}

JAVASCRIPT_TESTS = ("tests/revision_demo.test.cjs", "tests/agent_runs.test.cjs", "tests/agent_results.test.cjs")


def run_check(label: str, command: list[str]) -> int:
    print(f"\n{label}", flush=True)
    env = os.environ.copy()
    # Use this checkout even when invoked outside its root or without an
    # editable install. Third-party dependencies must still be installed.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "src")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    except OSError as error:
        print(f"{label} could not start: {error}", file=sys.stderr, flush=True)
        return 1
    return result.returncode


def show_scope(integration: bool) -> None:
    if integration:
        print("Python: full unittest discovery in tests/ (core + local-data regressions).")
        print("Missing data, import errors and failed assertions retain their original failure status.")
    else:
        print("Python: explicit portable core selectors:")
        for name in CORE_TESTS:
            print(f"  {name}")
        print("\nExcluded from the portable core; included by --integration:")
        for name, reason in LOCAL_DATA_TESTS.items():
            print(f"  {name}: {reason}")
    print("\nJavaScript: " + ", ".join(JAVASCRIPT_TESTS))
    print("No dependency installation, document download or model execution is requested.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--integration", action="store_true",
        help="run all original Python regressions, including tests requiring local data/experiments",
    )
    parser.add_argument("--list", action="store_true", help="show the selected scope without running tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="show each Python test name")
    args = parser.parse_args(argv)
    if args.list:
        show_scope(args.integration)
        return 0

    if args.integration:
        python_args = ["discover", "-s", "tests", "-t", "."]
        label = "Full local regression: Python core + integration"
        print("Local data and experiment records are required; missing inputs will fail.", flush=True)
    else:
        python_args = list(CORE_TESTS)
        label = "Portable core: Python"
        print("Running the explicit offline core. See --list for included and excluded tests.", flush=True)
    if args.verbose:
        python_args.append("-v")

    python_status = run_check(label, [sys.executable, "-m", "unittest", *python_args])
    javascript_status = run_check("Portable core: JavaScript", ["node", "--test", *JAVASCRIPT_TESTS])
    print(f"\nExit statuses: Python={python_status}; JavaScript={javascript_status}", flush=True)
    return 0 if python_status == javascript_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
