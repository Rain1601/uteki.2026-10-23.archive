# Code responsibilities

The repository groups executable code by responsibility. Filenames in old import
locations remain compatibility aliases; they contain no second implementation.
Frozen datasets, experiment outputs, manifests and existing evidence are not moved.

## Agent execution

```text
src/uteki/agents/
  data_query/     Question proposal, bounded retrieval loop, SDK planner and report
    agent.py     Public DataQueryAgent: run / run_scoped / run_tasks / run_question
    loop.py      Proposal and task execution; host-owned progress and completion
    prompts.py   Planner instructions; no company, period or source fallback
    model.py     SDK decision adapter and prior-budget preflight
    artifacts.py Exclusive JSON artifact creation
    report.py    Render saved retrieval results and their evidence
  reading/       DocumentReader, reading groups, pinned material selection
    citations.py Citation / Claim / Answer contracts shared by older consumers
    tool_session.py Bounded document tool session and citation provenance checks
  analysis/      Limited reviewed-Data consumer; historical analyst/reviewer, narrative and cloud experiments
  archive/       Research archive, revision contracts, context and rerun orchestration
  runtime/       Provider adapters, credential loading, costs and budget enforcement
  business_map/  Existing BusinessMapAgent capability and contracts
  *.py           Compatibility aliases for the former flat import paths
```

`analysis/` does not mean the complete downstream research Agent is implemented.
As audited on 2026-10-06, `data_consumer.py` consumes a scope-validated, reviewed
Data handoff and has a real limited-task run from 2026-09-30. Its output remains
a candidate awaiting content review, not a published company report. Historical
analyst/reviewer, narrative and Cloud experiments retain their original scope.
The complete independent research-review, revision and publication loop remains
unfinished. See the [current Agent inventory](CODE_OVERVIEW.zh-CN.md).

The current retrieval path is:

```text
CLI -> data_query.agent -> data_query.loop
                         -> infrastructure.research_data.task_progress
                         -> query_service / evidence_packaging
                         -> domain.research_data contracts and completion rules
```

The model adapter imports `data_query.prompts` directly. Query artifact writing
lives in `data_query.artifacts`, so services need not import the agent to persist
results. Narrative contracts and readers import `reading.citations` and
`reading.tool_session`; they no longer import the analysis comparison experiment.
Provider construction lives in `runtime.model_factory` and is shared by callers.

Use the new module paths for new code. The old paths resolve to the same module
object to preserve existing imports and test/client monkeypatch behavior. No
custom import loader is installed. Compatibility modules can be removed only in
an explicit breaking-change migration after external consumers are accounted for.

## Research data boundaries

- `domain/research_data/`: validated requests, scope, evidence and task contracts.
- `infrastructure/research_data/`: concrete storage, query execution, packaging,
  progress and completion evaluation.
- `scripts/`: explicit experiment/CLI entry points, not reusable agent contracts.
- `experiments/`: versioned inputs and results; historical outputs remain frozen.

New prepared runs hash the moved implementation files, including extracted
prompts and artifact helpers. Old prepared manifests are not rewritten: changed
code must be prepared as a new run. Scope validation, source allowlists, limits,
provider budgets, candidate status and evidence semantics are unchanged by the
structural migration.

## Verification

Before migration, 26 focused query tests passed. After migration, 132 focused
query, CLI preparation/integrity, mocked SDK/provider, document reading, costs,
historical analysis, archive-rerun and narrative checks passed. These are deterministic/offline checks, not model evaluation.
The CLI integrity check also exercises changing the newly extracted planner
instructions after preparation and rejects execution before provider setup.

Question planners must declare `plan_origin` as `model` (the SDK adapter) or
`scripted_fixture` (offline deterministic proposals). Missing/unknown origin is
rejected before planner invocation or output creation; it cannot silently become
`model`. Caller-authored plans continue through `run_tasks` with their declared
plan origin. An SDK test with mocked HTTP still records the adapter origin as
`model`; test reports must separately identify that no live model call occurred.

## Workbench

The server workbench uses `pages/`, `components/`, `data/`, and separate
`static/css/` / `static/js/`; see [its structure guide](../apps/review_workbench/README.md).
Full migration regression passed 661 Python and 7 JavaScript checks.
[End-to-end results](../experiments/data_agent_query/e2e-review-v1/README.md) distinguish
real model runs, scripted tool checks, fixes, and the unimplemented Analysis Agent.
