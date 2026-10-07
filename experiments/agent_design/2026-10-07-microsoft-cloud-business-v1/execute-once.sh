#!/usr/bin/env bash
set -euo pipefail
cd /Users/rain/Documents/ChatGPT/uteki.beta
PYTHONPATH=src:. .venv/bin/python scripts/run_business_revenue_agent.py \
  --root /Users/rain/Documents/ChatGPT/uteki.beta \
  --packet experiments/agent_design/2026-10-07-microsoft-cloud-business-v1/input/source_packet.json \
  --skill experiments/agent_design/2026-10-07-microsoft-cloud-business-v1/input/skill-v0.5.md \
  --company-id sec-0000789019 --document-id msft-2025-10k --period-end 2025-06-30 \
  --model claude-sonnet-5-5 --effort high --max-tokens 16000 --timeout-seconds 600 --stream \
  --contract-version business-draft-v1 --wire-mode full \
  --preflight-output experiments/agent_design/2026-10-07-microsoft-cloud-business-v1/preflight-v1.json \
  --execute --output experiments/agent_design/2026-10-07-microsoft-cloud-business-v1/run-01 \
  --observation-root data/agent_observability/local --budget-limit-usd 0.60
