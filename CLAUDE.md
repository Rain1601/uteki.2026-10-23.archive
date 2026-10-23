# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Uteki is an evidence-based investment research system (基于原件证据的投资研究系统). Most docs are in Chinese.

## Working agreements (authoritative)

@AGENTS.md

AGENTS.md is the binding collaboration contract (root-cause-first, one small task at a time, real-component acceptance, cost/authorization limits, no MiniMax, SEC acquisition only via `query_cli agent acquire` / `prepare_sources`). Read order for any task: AGENTS.md → `TODO.md` (the single current action) → `docs/DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md` (the only top-level design, rewritten 2026-10-23: code map §8, status §10, roadmap §11; old section numbers like "14.x" refer to `docs/DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md`, the frozen v1.30 record). Do not read historical plans/reports/archives by default, and do not resume work because an old doc says "next step". Write design refinements back into the core design doc and status into TODO.md — no parallel plans or progress reports.

## Commands

Python 3.11+ (environment reproduced on 3.13), managed by `uv` with the root `uv.lock`. Tests use stdlib `unittest`; always invoke with `-I`.

```bash
# Main dev environment (add --extra agent for the OpenAI + Claude SDK paths)
uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp

# Offline core regression (Python + JS via node; no model calls, no downloads)
.venv/bin/python scripts/run_offline_checks.py            # --list shows selectors, --verbose, --integration
.venv/bin/python scripts/check_workspace.py               # returns 2 when local data is missing
.venv/bin/python scripts/smoke_research_workflow.py

# Single test file / single test (test dirs have no __init__.py, so use discover -s)
.venv/bin/python -I -m unittest discover -s tests/unit/data_platform -p test_catalog.py
.venv/bin/python -I -m unittest discover -s tests/integration/data_platform_agent \
  -p test_gateway_openai.py -k <test_name_substring> -v

# OpenSpec helpers (Node)
npm run spec:check
```

The M0 SDK validation env is separate: base deps + `requirements/m0.txt` (do not merge into the main lock). Some integration tests and reviews run against an installed (non-editable) env — when source changes, reinstall and verify the actual import path; see `docs/LOCAL_DEVELOPMENT.md` for the exact reusable review commands and `docs/OFFLINE_TESTS.md` for test-scope tables (which mixed files are core vs. `--integration`).

Console entry points (pyproject): `uteki-data` (`uteki.infrastructure.research_data.query_cli`, includes `agent acquire`), `uteki-data-mcp` (MCP stdio server), `uteki-reports`, `uteki-eval`.

Review workbench: `PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check` (then `--host 127.0.0.1 --port 8765`).

## Architecture

- `src/uteki/data_platform/` — the **new Data core**; active development happens here. It must not depend on the legacy `research_data` / `data_query` business orchestration (legacy code is kept for comparison/compat only, no new features). Layering:
  - `contracts/` pydantic v2 models (`extra=forbid`); tool JSON Schema, MCP schema and doc examples are all exported from these — change the contract, not three copies.
  - `catalog/` SQLite metadata (versioned, hashed SQL migrations shipped as package data) · `content/` object store, staging, manifests, hash checks, publication/recovery · `connectors/` official sources (SEC EDGAR/XBRL, company sites, explicit local originals) · `build/` HTML/iXBRL/DOM parsing → validated publishable assets · `retrieval/` asset discovery + in-asset content index · `structured/` DuckDB records and deterministic (Decimal) calculations · `documents/` PDF/document directory & passages.
  - `application/` SDK-agnostic business tools, requirement state, evidence, delivery/exports, budget/limits, recovery clocks. Read/build layers never depend back on agent code.
  - `agent/` thin, independent adapters for **two official SDKs** (OpenAI Agents SDK and Claude Agent SDK) sharing the one `application/` core: model profiles, gateway transport (`providers/`), metering, session state, skill runtime. The SDK owns the agent loop; don't reimplement it.
- `config/data_platform/` — model profiles (`model-profiles/<kernel>/<model_key>/<role>.json`), prompts, source/runtime policies, gateway contract. Shared code must not default to sample companies, paths, dates, or answers.
- `src/uteki/interfaces/` — `data_mcp` (MCP server/client) and investment-report CLI. `src/uteki/agents/`, `domain/`, `infrastructure/`, `presentation/` are earlier generations (analysis agents, research data, reading/report pipeline).
- `apps/` — `review_workbench` (Python web workbench), `claude_dialogue` (shared Claude window; read its README and use `scripts/claude_chat.py --conversation-root <private dir>`), `uteki_zero` (JS).
- `tests/unit|integration/data_platform[_agent]/` — new-core tests; SDK integration tests use local loopback mock gateways (synthetic responses, `real_model_calls=0`) — these validate wiring, not real model behavior. `tests/fixtures/data_platform/` holds synthetic workers.
- `scripts/data_agent/` and `examples/data_platform/` — acceptance/verification entry points (e.g. `verify_tool_delivery.py`, `verify_html_material.py`).
- `output/` holds frozen run evidence (reviews, call traces, deliveries, ledgers). Never modify or "fix" these; they are evidence.
- `skills/` — dev-collaboration skills. For UI work read `skills/uteki-interface/SKILL.md` + style guide first; for business diagrams read `skills/uteki-business-diagrams/SKILL.md`. Front-end design decisions go in `docs/FRONTEND_DESIGN.md`.

## Key constraints to remember

- Real model calls cost money against a shared ledger with frozen per-task limits ($3 default warning); check TODO.md for current spend/authorization before any real run. Mock/synthetic runs never count as functional acceptance.
- Report separately: wiring/storage tests, real runs, and business (original-document) acceptance.
- Credentials, ledgers, contacts, private sessions and machine paths stay out of commits (`.env` is local).
