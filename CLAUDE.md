# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Uteki is an evidence-based investment research system (基于原件证据的投资研究系统). Most docs are in Chinese.

## Working agreements (authoritative)

@AGENTS.md

AGENTS.md is the binding collaboration contract (root-cause-first, one small task at a time, real-component acceptance, cost/authorization limits, no MiniMax, SEC acquisition only via `uteki-data acquire` / `prepare_sources`). Read order for any task: AGENTS.md → `TODO.md` (the single current action) → `docs/DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md` (the only top-level design, rewritten 2026-10-23: code map §8, status §10, roadmap §11; old section numbers like "14.x" refer to `docs/DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md`, the frozen v1.30 record). Do not read historical plans/reports/archives by default, and do not resume work because an old doc says "next step". Write design refinements back into the core design doc and status into TODO.md — no parallel plans or progress reports.

## Commands

Python 3.11+ (environment reproduced on 3.13), managed by `uv` with the root `uv.lock`. Tests use stdlib `unittest`; always invoke with `-I`.

```bash
# Main dev environment (editable; no Claude SDK)
uv sync --locked --python 3.13 --extra analysis --extra data

# Offline core regression (Python + JS via node; no model calls, no downloads)
.venv/bin/python scripts/run_offline_checks.py            # --list shows scope and exclusions, --verbose

# Single test file / single test (test dirs have no __init__.py, so use discover -s)
.venv/bin/python -I -m unittest discover -s tests/unit/data_platform -p test_catalog.py
"$SDK_ENV/bin/python" -I -m unittest discover -s tests/integration/data_platform_agent \
  -p test_gateway_openai.py -k <test_name_substring> -v

# OpenSpec helpers (Node)
npm run spec:check
```

Agent tests (`*/data_platform_agent`, `test_gateway_sdk_wire`) need a separate **non-editable** env with `--extra data --extra agent`; run `scripts/run_offline_checks.py --integration` with that env's python. `test_content_processes` must run alone in a data-only non-editable env. After any source change, reinstall (`uv pip install --reinstall-package uteki-eval --no-deps .`) and verify the actual import path. Exact commands: `docs/LOCAL_DEVELOPMENT.md`.

Console entry point (pyproject): `uteki-data acquire` (`uteki.data_platform.cli`, official SEC filings; no parsing or model calls). Real model runs go through `examples/data_platform/live_function.py` (`inspect` first; every batch needs explicit user authorization).

## Architecture

- `src/uteki/data_platform/` — the **Data core**, the only Python package under `src/uteki/` since S4 (2026-10-23; legacy agents/infrastructure/domain/interfaces, the review workbench, experiments, benchmarks and tracked `data/` were archived, see `docs/REPOSITORY_RETENTION.zh-CN.md`). Layering:
  - `contracts/` pydantic v2 models (`extra=forbid`); tool JSON Schema, MCP schema and doc examples are all exported from these — change the contract, not three copies.
  - `catalog/` SQLite metadata (versioned, hashed SQL migrations shipped as package data) · `content/` object store, staging, manifests, hash checks, publication/recovery · `connectors/` official sources (SEC acquisition `prepare_sources`, official discovery, filing integrity, SEC contact settings) · `build/` HTML/iXBRL/DOM parsing (incl. `sec_index`) → validated publishable assets · `retrieval/` asset discovery + in-asset content index · `structured/` DuckDB records and deterministic (Decimal) calculations · `documents/` PDF document library (Docling, native directory, passages).
  - `application/` SDK-agnostic business tools, requirement state, evidence, delivery/exports, the `run_budget` root ledger, limits, recovery clocks. Read/build layers never depend back on agent code.
  - `agent/` thin, independent adapters for **two official SDKs** (OpenAI Agents SDK and Claude Agent SDK) sharing the one `application/` core: model profiles, gateway transport (`providers/`), metering, session state, skill runtime. The SDK owns the agent loop; don't reimplement it.
- `config/data_platform/` — model profiles (`model-profiles/<kernel>/<model_key>/<role>.json`), prompts, skills, gateway contract. `config/company_sources/` — company source configs for `uteki-data acquire`. Shared code must not default to sample companies, paths, dates, or answers.
- `apps/` — `claude_dialogue` (shared Claude window; read its README and use `scripts/claude_chat.py --conversation-root <private dir>`), `uteki_zero` (brand/catalog modules used by the Swiss C front end), `logo_studio` (logo source assets). The Swiss C front end lives in `docs/design/company-workspace-swiss-c/` (static ES modules).
- `tests/unit|integration/data_platform[_agent]/` — Data core tests; SDK integration tests use local loopback mock gateways (synthetic responses, `real_model_calls=0`) — these validate wiring, not real model behavior. `tests/fixtures/data_platform/` holds synthetic workers.
- `scripts/data_agent/` and `examples/data_platform/` — acceptance/verification entry points (e.g. `verify_tool_delivery.py`, `verify_html_material.py`, `live_function.py`).
- `output/` holds frozen run evidence (reviews, call traces, deliveries, ledgers). Never modify or "fix" these; they are evidence.
- `skills/` — dev-collaboration skills. For UI work read `skills/uteki-interface/SKILL.md` + style guide first; for business diagrams read `skills/uteki-business-diagrams/SKILL.md`. Front-end design decisions go in `docs/FRONTEND_DESIGN.md`.

## Key constraints to remember

- Real model calls cost money against a shared ledger with frozen per-task limits ($3 default warning); check TODO.md for current spend/authorization before any real run. Mock/synthetic runs never count as functional acceptance.
- Report separately: wiring/storage tests, real runs, and business (original-document) acceptance.
- Credentials, ledgers, contacts, private sessions and machine paths stay out of commits (`.env` is local).
