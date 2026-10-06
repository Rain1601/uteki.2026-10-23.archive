# Review workbench

Run from the repository root with `PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app`.

## Company-first data workspace (2026-10-05)

Open [the data workspace](http://127.0.0.1:8765/data-workspace). Select a company,
then a material. The same window offers original reading, financial data,
sections/tables, filing-brief status and saved processing records. The material
list supports reporting-year ordering, type grouping and filters. Selecting a
number opens its evidence beside the original source.

In **Financial data → Display versions & history**, explicitly choose the saved
version for each task. The initial view selects none; new runs never silently
replace an existing selection. Registered base database rows are a separate,
explicit view. Version selection and recoverable archive are UI-only operations,
not adoption, and never change the MCP catalog. Task grouping is explicitly
pinned in `data/evaluation_views/workspace-tasks-v1.json`; mutable display state
lives in ignored `data/review_workbench/ui-state-v1.json`.

Original previews remain scriptless and source-bound. HTML highlights are added
only to response copies after checking recorded DOM locators and source text.
AMD/TSMC operating-cash-flow evidence currently locates whole tables, not cells.
PDF page navigation requires an actual PDF-page mapping. Missing locators and
missing outputs remain visible; no model is called when browsing this UI.

The current filing brief is not generated, and the complete acquisition/parent
Agent trace is not integrated. Existing saved extraction prompts, input packets,
normalization results and independent reviews remain inspectable. Arbitrary SQL
editing, new human scoring, reruns and adoption are outside this view.

`/evaluation` and `/extractions` remain available. The static workbench on port
8769 links to the real workspace, while its own tasks remain sample data.

## Company materials and outputs (2026-10-05)

Open [the real data workspace](http://127.0.0.1:8765/evaluation), choose a
company, then choose a report. The material page groups the saved original,
section contents, passages and HTML tables, separate financial extraction
versions, filing brief status, and the recorded extraction process. Each
version lists the actual extracted metrics and links its numbers to evidence
and saved review. Technical IDs, diagnostics and storage paths are expandable.

The actual formats remain distinct: original HTML; `index.json` plus
`blocks.jsonl` for retrieval; JSON model candidates and normalized
`research.duckdb` rows; saved task, input packet, effective System Prompt / Skill,
and review artifacts. A filing brief has not been produced. Different
extraction attempts are not summed into a unique-fact total.

`/extractions?run=<registered-id>#processing-record` presents readable saved
inputs, extraction method, outputs and open issues. Missing checks are not
reported as zero issues. This covers registered extraction artifacts; it is
not a complete acquisition, parsing and parent-Agent trace. Human annotations,
rerun controls and adoption are not implemented in this read-only view.

The static Agent Workbench demo on port 8769 now links to these real pages;
its task workspace still contains explicitly labeled sample data. No sample
company or run is passed to the real service.

Validation: 48 focused Python checks, 27 existing demo interaction checks,
live HTTP checks for both companies and the original AMD short link; a foreign
company/run selection is rejected. No browser visual acceptance was performed.

## Data evaluation (2026-10-01)

Open `http://127.0.0.1:8765/evaluation` after starting the server with
`--host 127.0.0.1 --port 8765`. This is a read-only inspection workspace for
registered frozen artifacts. It belongs to the internal engineering workspace,
not the public report product. The current app still mixes reading and engineering
routes; production authorization and publication isolation are not implemented.
See [the frontend/backend capability map](../../docs/design/UTEKI_WORKSPACES_v1.zh-CN.md)
for the proposed complete backend and remaining review/evaluation/control scope.

Choose a company dataset explicitly, then inspect:

- **Materials & coverage:** source versions, parsed-block/candidate-row counts,
  parsing diagnostics, processing gaps grouped by source and reason, and limits.
- **Source & parsing:** sandboxed original HTML, text/table blocks, source
  positions, adjacent blocks, full block JSON and asset references.
- **Records & review:** database schema, filtered exact decimal records, source
  tables and numeric metadata, and task-scoped saved model verdicts where present.
- **Run replay:** the original question/scope, submitted facts, content review,
  main-role tool decisions, results and feedback. Viewing does not execute tools.

`data/evaluation_views/data-agent-v1.json` registers GOOGL FY2025 10-K / Q3 10-Q
(253 candidate rows), MSFT FY2025 10-K (102 rows), and the saved GOOGL Data query
plus successful content-review retry (7 facts, 25 main-role steps). MSFT has no
registered replay. These counts do not establish extraction completeness or
cross-company model quality.

`data/evaluation_artifacts.py` verifies pinned manifests, listed-file hashes,
company/source identities, JSON–DuckDB payload agreement, and query/review
bindings before display. The browser accepts registered IDs, never filesystem
paths or SQL. Raw source HTML has a restrictive CSP and sandbox; external scripts
and images do not load. Records keep candidate status and adoption is unchanged.

Example: select GOOGL → Records & review → `operating_cash_flow` → the annual
2024 row `obs-1ee7bb58b50f03e0f72b12e6`. Inspect the saved value `125299000000 USD`,
raw value `125,299`, scale `6`, original cash-flow table, and saved review.
Following its block link and “Previous source block” exposes adjacent unit/title
text. Model support applies to the saved question/version; human acceptance has
not been recorded.

Not implemented here: human issue annotations/verdict persistence, a Gold set,
cross-run/model comparison, standalone Worker step replay, new extraction runs,
or shared adoption. The older `review_excerpt.json` paragraph 90 integrity gap
remains reported by `--check`; this viewer uses independently pinned datasets.

## Module layout

- `app.py`: HTTP routes, request handling and the existing result/source entry points.
- `pages/`: page renderers for company research, source documents, datasets and query acceptance.
- `components/`: shared navigation, visual shell, report text and citation presentation.
- `data/`: document lookup and research archive import helpers.
- `static/css/`, `static/js/`: stylesheet and browser script sources. Python supplies escaped data and HTML; CSS and JavaScript are edited here.
- `assets.py`: fixed local asset lookup. Renderers still embed assets in returned HTML, preserving standalone pages and source-bridge behavior. This is not a public arbitrary-file endpoint.
- `workspace_check.py`: local workspace readiness checks.

Use canonical imports such as `apps.review_workbench.pages.query_runs`. The package retains old module aliases for existing consumers and monkeypatches; aliases refer to the same module object, not duplicated implementations.

Source bridge scripts use explicit JSON placeholders replaced by their Python callers. Preserve JSON escaping, source scope, and snapshot semantics when changing these inputs. Historical generated HTML and experiment snapshots are not rewritten by an asset edit.

This organization does not change layout, company lists, research states, model calls or adoption. Python still builds dynamic HTML; introducing a template engine or splitting the route handler is separate work.

### Data workspace verification

The implementation was checked with 100 focused Python tests, 10 new controller
checks and 27 existing demo checks. Live local HTTP checks covered AMD and TSMC
financial candidates, their same-source whole-table highlights, scriptless source
headers, old short links and rejected cross-company requests. Real UI choices
were not changed by the checks. No new model run or browser visual review was
performed. The existing paragraph-90 warning in the older Alphabet excerpt
remains separate from these source-bound previews.
