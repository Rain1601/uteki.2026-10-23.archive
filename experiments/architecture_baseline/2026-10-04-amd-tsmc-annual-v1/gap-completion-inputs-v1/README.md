# FY2023 missing financial cells: actual DeepSeek completion, 2026-10-05

This increment generated new candidate datasets for seven previously missing FY2023 cells: AMD operating cash flow and cash PP&E purchases; TSMC revenue, operating income, operating cash flow, cash PP&E purchases and ending cash. Comparative columns in the original FY2023 reports were retained. The selected successful child snapshots contain **20 database candidates across five runs**, covering all seven requested FY2023 cells. This is extraction/projection evidence, not baseline adoption or product acceptance. Independent review and backend registration are separate work.

## Input, models and method

- Source cutoff: 2026-10-04. Existing frozen official FY2023 annual sources only; no download or FY2024/25 extraction in this increment.
- AMD: `source-291485b98a75d8cfabe47571`, official 10-K, source SHA `47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808`, dataset `data/company_workspace/official-filing-preparations/amd-v2/dataset`.
- TSMC: `source-6719837a8d24b2b7df359f29`, official 20-F, source SHA `8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1`, dataset `data/company_workspace/official-filing-preparations/tsmc-v2/dataset`.
- Planning/source discovery: real `deepseek-v4-pro`, reasoning `high`. Financial extraction: real `deepseek-flash`, reasoning `low`. Exact local configurations are [planner-model-config.json](planner-model-config.json) and [extractor-model-config.json](extractor-model-config.json).
- Existing shared SQLite cost ledger retained, `record_only`, no amount or total-request ceiling. Operational per-request/per-task bounds remain explicit. [Call accounting](call-accounting.json) records 32 request endings, known list-price estimates totalling USD 1.16886162, and 2 unknown-cost connection failures. These are estimates, not provider invoices.
- Registered execution method: `annual-financial-v2@2`, task default from `config/data_tasks/annual-financial-v1.json`. Each child run freezes `method-snapshot.json`, the actual Skill and System Prompt, model input/output and implementation files.
- No consumer answer or reviewer gold was supplied to discovery, selection, extraction or normalization. Financial values came from the frozen source material and actual model responses. Review feedback supplied issue descriptions, not corrected amounts.

AMD reused the prior source-bound model discovery, and Pro independently selected the cash-flow batch. TSMC used [run_discovery_for_task.py](../run_discovery_for_task.py), which reuses the existing source-hash/date-context/short-reference discovery implementation, freezes its code and calls Pro on the complete original block catalog. It emits a new registered task input; extraction remains owned by the normal Uteki `agent query` / `extract-batch` entry points. This discovery wrapper is still an experiment entry point, not a claim of a fully generalized production job builder.

## Actual attempts and recovery

Paths below are relative to the enclosing annual experiment directory. Original unsuccessful runs remain intact.

| Run | Actual outcome | Limitation or recovery |
| --- | --- | --- |
| `amd-fy2023-cash-flow-main-agent-v1` | Connection failure before a plan; no candidates | Default sandbox network unavailable; retried with network permission into a new run |
| `tsmc-fy2023-discovery-v1` | Connection failure; no discovery | Original failed call retained |
| `amd-fy2023-cash-flow-main-agent-v2` | Pro chose batch 4; Flash generated 6 raw / 3 DB / 4 diagnostics | PP&E source alias absent. Root ended `limited / no_progress_limit` after repeatedly rereading the delivered extraction receipt. Child candidate success is not root-loop success |
| `tsmc-fy2023-discovery-v2` | Pro selected 44 refs; schema validation rejected its period catalog | Complete JSON, but three instant periods wrongly carried a start date; no manual repair |
| `tsmc-fy2023-discovery-v3` | New Pro response passed source/date/schema checks: 80 delivered source blocks, five mapped periods | Added generic receiving-contract clarification that instant start must be null. Original dates still verified against source XBRL |
| `amd-fy2023-cash-flow-batch-v3` | New Flash response: 6 raw / 6 DB / 0 diagnostics | Explicit source label `Purchases of property and equipment` added to a new configuration; no amount edits |
| `tsmc-fy2023-three-statements-main-agent-v1`, turn 003 | Pro selected income table; Flash: 12 raw / 6 DB / 9 diagnostics | Three-year TWD revenue and operating income entered DB. Extra convenience USD translations / net income remain unresolved under the requested TWD metric catalog |
| Same root, turn 004 | Pro selected assets table; Flash: 3 raw / 2 DB / 4 diagnostics | Two-year TWD ending cash entered DB; extra convenience translation remains unresolved |
| Same root, turn 005 | Pro selected operating cash-flow page; Flash: 4 raw / 0 DB / 18 diagnostics | Exact source row alias and short year-header aliases absent; investing continuation not delivered. Root correctly ended `partial`, explicitly reporting the missing continuation and exhausted three-batch allowance |
| `tsmc-fy2023-operating-cash-flow-batch-v2` | New Flash response: 3 raw / 3 DB / 0 diagnostics | New explicit source label/year-header mappings; original fiscal dates unchanged |
| `tsmc-fy2023-investing-continuation-main-agent-v1` | New Pro independently chose investing batch 10; Flash: 3 raw / 0 DB / 8 diagnostics | Ambiguous child row label, omitted accounting-parenthesis spaces, one fabricated qualifier quote. Root ended `candidate_ready`, meaning a candidate artifact existed, not that any record passed projection |
| `tsmc-fy2023-investing-cash-flow-batch-v2` | New Flash response: 3 raw / 3 DB / 0 diagnostics | Source-pinned hierarchical acquisitions label, exact source context, and original spaced negative literals. The fabricated qualifier was removed by model re-extraction; relation now identifies cash-flow context |

## Selected candidate outputs

| Candidate child run | Raw / DB / program diagnostics | Requested coverage |
| --- | --- | --- |
| `amd-fy2023-cash-flow-batch-v3/extraction-01` | 6 / 6 / 0 | OCF + cash PP&E, FY2023/22/21 |
| `tsmc-fy2023-three-statements-main-agent-v1/query/turn-003/financial_extract/extraction-01` | 12 / 6 / 9 | TWD revenue + operating income, FY2023/22/21 |
| `tsmc-fy2023-three-statements-main-agent-v1/query/turn-004/financial_extract/extraction-01` | 3 / 2 / 4 | TWD ending cash, FY2023/22 |
| `tsmc-fy2023-operating-cash-flow-batch-v2/extraction-01` | 3 / 3 / 0 | TWD OCF, FY2023/22/21 |
| `tsmc-fy2023-investing-cash-flow-batch-v2/extraction-01` | 3 / 3 / 0 | TWD cash PP&E, FY2023/22/21 |

[program-checks.json](program-checks.json) contains each run and dataset manifest SHA, immutable snapshot ID and verified file-manifest result. Each child provides `packet.json` (actual original source blocks), `extraction.json` (raw model candidates), `normalized.json` (projection and unresolved reasons), `dataset/research.duckdb`, `system-prompt-effective.json` and `model/` call artifacts. A zero program-diagnostic count does not establish full financial-statement coverage or semantic approval.

## Changes retained in the system and explicit inputs

1. AMD source-label mapping: [amd-source-label-change.json](amd-source-label-change.json), [new job](amd-cash-flow-job-v2.json). Added the exact investing cash-purchase wording; source numbers were not provided as fixes.
2. TSMC OCF mapping: [tsmc-source-label-change.json](tsmc-source-label-change.json), [new job](tsmc-operating-cash-flow-job-v2.json). `Net cash generated by operating activities` and printed year-header aliases were bound to this source. Dates remain the independently verified source period catalog; short years are not a general fiscal-calendar rule.
3. TSMC acquisitions mapping: [tsmc-investing-source-binding-v1.json](tsmc-investing-source-binding-v1.json), [new job and feedback](tsmc-investing-job-v2.json). The alias is the hierarchical `Acquisitions of: Property, plant and equipment`; no global bare `Property, plant and equipment` alias was added. The same table also has a disposal/proceeds row with that bare label.
4. Generic normalizer version `direct-normalization-v2` now accepts horizontal padding inside accounting parentheses while preserving the raw literal and requiring exact original evidence. It still rejects joined digits, malformed signs, reformatted literals absent from evidence and invented quotes.
5. Optional source-bound contextual mapping is now checked in packet construction and again at normalization. It pins company, source ID, raw SHA, dataset manifest and the exact delivered block hashes. Every mapped candidate must actually cite the required acquisition heading, investing scope, year/currency header and unit caption. Exact quote binding still applies; a valid packet alone does not satisfy per-record context.

Changed shared code: `src/uteki/infrastructure/research_data/direct_normalization.py` and `direct_extraction.py`; focused tests in `tests/unit/test_direct_normalization.py`. **35 focused offline tests passed**, including the existing provenance, batch and autonomous-financial boundaries plus new independent-company/currency/period and contextual-source isolation tests. An earlier test command included a nonexistent module name and failed discovery; the corrected command passed. These are engineering checks separate from the actual model runs above.

## Independent review and backend registration

Codex source review has now checked the selected candidates against the original
frozen report cells, exact quotes, dates, units and acquisition-versus-disposal
context. The five selected runs are registered in the real company/material
viewer; the original TSMC mapping failures and inaccurate-quote attempt remain
separately visible. Canonical review references are recorded in
`../review-mcp-compatible-v2-registration-refs.json`; the final investing review
is `../review-tsmc-fy2023-investing-cash-flow-batch-v2-combined.json`.

[registered-target-facts-acceptance.json](registered-target-facts-acceptance.json)
verifies each of the seven requested FY2023 facts from its actual DuckDB payload
and linked per-fact review. All remain unadopted candidates. The readonly-v1 MCP
catalog and historical consumer run have not been overwritten.

## Remaining work

1. Extend the readable extraction-artifact view to the complete acquisition, parsing and parent-Agent trace, including failed/partial root-loop statuses and persistent human annotations.
2. Re-run read-only MCP consumer questions against an explicitly selected new catalog after review. No candidate is automatically adopted into a baseline.
3. Address AMD planner receipt rereading and productionize source-discovery / reviewed mapping configuration reuse. The source-pinned contextual adapter is a bounded supported case, not proof of general table-semantic interpretation.
