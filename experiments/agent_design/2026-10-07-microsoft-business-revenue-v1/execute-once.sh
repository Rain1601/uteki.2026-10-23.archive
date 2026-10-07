#!/usr/bin/env bash
# Explicitly scoped one-call command. Preparation alone never runs this file.
# A failed or uncertain result must be reconciled; do not rerun automatically.
set -euo pipefail
cd /Users/rain/Documents/ChatGPT/uteki.beta
PYTHONPATH=src:. .venv/bin/python scripts/run_business_revenue_agent.py \
  --root /Users/rain/Documents/ChatGPT/uteki.beta \
  --packet experiments/agent_design/2026-10-07-microsoft-business-revenue-v1/input/source_packet.json \
  --skill experiments/agent_design/2026-10-07-microsoft-business-revenue-v1/input/skill-v0.5.md \
  --company-id sec-0000789019 --document-id msft-2025-10k --period-end 2025-06-30 \
  --model claude-sonnet-5-5 --effort high --max-tokens 16000 --timeout-seconds 600 --stream \
  --contract-version business-revenue-draft-v2 --wire-mode compact-v1 \
  --preflight-output experiments/agent_design/2026-10-07-microsoft-business-revenue-v1/preflight-compact-v1.json \
  --execute --output experiments/agent_design/2026-10-07-microsoft-business-revenue-v1/run-01 \
  --observation-root data/agent_observability/local --budget-limit-usd 0.60
