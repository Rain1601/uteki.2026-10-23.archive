# Data retrieval foundation: catalog, scope and typed queries

2026-10-09. Read-only code/data review. No model calls or network requests. No production code changes in this review. Probes are recorded in `catalog-probes.json`; reproduce from repository root with `PYTHONPATH=src:. .venv/bin/python experiments/agent_design/2026-10-09-data-foundation-review-v1/catalog_probe.py`.

## Conclusion

Company/source/cutoff gates worked in the exercised cases. The concrete blocker is that available financial observations and the fiscal-period catalog disagree. AMD also has an explicitly unsupported numeric-period adapter. Model evaluation must not assume these datasets already provide complete structured query capability.

## Dataset scope

| Case | Frozen dataset | Observations | Actual observed periods |
|---|---|---:|---|
| Selected Microsoft | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset` | 102 | FY2023, FY2024, FY2025, July–June dates |
| Selected Google | `data/company_workspace/extraction_ab_v1/corpus/googl/dataset` | 253 | 2023–2025 annual, 2024/2025 Q3 and YTD |
| Selected AMD | `experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset` | 0 | No normalized records; FY2023 original/index exists |
| Additional Google comparison | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/googl/dataset` | 111 | 2023–2025 annual |
| Additional AMD comparison | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/amd/preparation/dataset` | 0 | Four indexed originals, including 10-K/A |

Counts are candidate occurrences, not unique reviewed financial facts or full-report extraction acceptance.

## F1 — Available historical records cannot pass fiscal Query grounding

**Classification: reproducible integration defect / incomplete materialization contract. Priority: high.**

Microsoft and Google contain FY2024 observations, but their annual source metadata maps only FY2025. Calling `explicit_periods('FY2024 revenue', fiscal_periods=port.get_schema()['fiscal_periods'], require_fiscal_mapping=True)` returns an empty tuple. The autonomous numeric-query gate consequently rejects the request before SQL. Google quarterly metadata similarly maps only the current FY2025 Q3, despite FY2024 Q3 observations.

Relevant code:

- `src/uteki/infrastructure/research_data/company_materialization.py:230`: fiscal mappings are emitted only after successful record creation, for non-dimensional contexts whose end equals the report end. Comparative periods are omitted.
- `src/uteki/domain/research_data/period_scope.py:32`: FY syntax requires a unique explicit mapping.
- `src/uteki/agents/data_query/autonomous.py:814`: numeric Query requires this mapping. The same guard applies to document Query at line 821.

The conservative gate is useful; do not repair it by silently substituting calendar dates. The producer needs evidence-backed comparative fiscal mappings, and discovery needs to expose periods that are genuinely queryable. Narrative source reading remains possible; this finding concerns typed Query.

Acceptance proposal: a source with current and comparative annual/quarterly facts publishes supported fiscal labels and exact dates; a query for a genuinely absent or ambiguous fiscal period remains an explicit gap. Cover a non-calendar issuer and an independent synthetic dataset.

## F2 — AMD originals are readable, but normalized financial tables are unavailable

**Classification: declared adapter limitation, reproduced on both AMD datasets. Priority: high for structured extraction.**

Selected AMD exposes one original source and indexed text but zero observations, zero metric catalog rows and zero fiscal mappings. The additional four-report AMD dataset has the same numeric outcome. The frozen acquisition verification reports unsupported duration and complete-month validation failures.

- `src/uteki/infrastructure/research_data/company_materialization.py:73`: duration kind uses a month-count mapping.
- Same file, line 217: records use `SOURCE_PERIOD_VERSION`, requiring complete month boundaries.
- Same file, line 248: the limitation is explicitly published as `complete_month_boundaries_only`.
- `src/uteki/domain/research_data/query_contract.py:52`: complete-month validation; a separate exact-source protocol already exists but is not selected by this materializer.

AMD's week-based fiscal boundaries are therefore not a model failure. Do not label zero metric rows as no financial disclosure. The query can use raw text/tables within bounded retrieval, while numeric operations should report the structured-data gap. Supporting exact source periods requires an explicit adapter/protocol change and new frozen materialization, not editing historical snapshots.

## F3 — Calendar-year syntax remains ambiguous for non-calendar companies

**Classification: known syntax limitation and demonstrated semantic risk; not a proven cross-company leak.**

For Microsoft, `FY2025 revenue` resolves to 2024-07-01 through 2025-06-30. `2025年度收入` and `for 2025 revenue` resolve to calendar 2025, even with `require_fiscal_mapping=True`. This can under-retrieve when a user intended the company's fiscal year.

- `src/uteki/domain/research_data/period_scope.py:52`: bare-year expressions become calendar periods.
- `src/uteki/domain/research_data/execution_scope.py:12`: execution scope contains a knowledge cutoff, not a separately typed reporting period.

These meanings should be made explicit in Query normalization/feedback. No inferred fiscal fallback is justified. Relative dates, YTD wording, year ranges and half-years are also intentionally rejected by this parser; their failure is a declared subset limitation.

## F4 — Small catalog exists, but financial meaning is weakly described

**Classification: concrete usability limitation; effect on model accuracy unmeasured.**

The metric catalog provides unit, version, aggregation rule and source scope. However, four of the five exposed metric definitions merely repeat their identifier (`revenue`, `operating_income`, `net_income`, `operating_cash_flow`); aliases also repeat that identifier. Only capex has a meaningful explanatory definition. Dimensional entities use hashed IDs and raw XBRL axis/member names; they have no verified business label or hierarchy.

- `src/uteki/infrastructure/research_data/company_materialization.py:66`: metric description generator.
- Same file, line 226: dimensions are intentionally opaque, not interpreted as named segments.
- `src/uteki/infrastructure/research_data/query_catalog.py:61`: entity projection retains raw dimensions.

For example, Microsoft's entity catalog exposes `msft:IntelligentCloudMember` in `reported_dimensions`, not a source-reviewed business taxonomy. Google exposes combined product and segment axes on the same entity. A model must not turn those into parent-child business relationships without source evidence. This is a data-semantics prerequisite, not permission to encode company-specific answers into shared rules.

Catalog pagination worked: selected Microsoft exposes 20 entities and 81 coverage items, but the 4 KB initial page returns eight entities. Source/metric pages are only a few KB. `probe_schema({})` may spend its first page on source/metric/entity metadata; examples occur later. Cursors are present, so this is not silent truncation. A bounded targeted probe is preferable to loading the full schema (roughly 68 KB for Microsoft).

## Other explicit limits

- `src/uteki/domain/research_data/query_contract.py:196`: typed document Query accepts 10-K, 10-Q and EARNINGS_CALL only. Indexed 10-K/A and 20-F cannot use this typed route, although direct source tools can read them. The additional AMD dataset contains a 10-K/A. This is route inconsistency / unsupported scope, not proof the document is absent.
- `src/uteki/infrastructure/research_data/query_service.py:263`: document matching is literal, in source order, not semantic recall/ranking. Four contexts at most per typed document request. Missing literal matches are not non-disclosure.
- `src/uteki/infrastructure/research_data/query_catalog.py:54`: each small catalog probe scans all scoped observation payloads before projecting/paginating. Output is bounded, but database work is not similarly bounded. No problematic latency was observed in these small datasets; scaling remains unverified.

## Scope checks that passed

All five dataset probes rejected unknown source IDs and company/source mismatch. A scoped child could not widen the cutoff. A cutoff before publication exposed no source catalog entries and returned `not_available_at_cutoff` for source outline. In Google and additional AMD multi-source cases, narrowing the source list removed excluded sources from discovery and blocked their body access.

The implementation checks these boundaries in `query_service.py:434`; typed query headers are pinned at line 505, entity/document company checks at line 567, direct source lookup at line 582, and publication/candidate checks at line 594. SQL uses parameterized source/company restrictions at line 190.

This review did not identify a concrete company/source body-isolation bypass. It did not merge separate real-company datasets or audit every public route, adversarial metadata mutation, or adoption transition; do not describe this as a comprehensive security certification.

## Immediate priority

Fix and test fiscal-period discoverability and the explicit supported-data matrix first. Keep AMD's numeric limitation visible until an exact-date adapter is validated. Then enrich general metric/data descriptions with precise meaning and evidence rules. Do not spend model comparisons diagnosing data that the host currently makes unqueryable.
