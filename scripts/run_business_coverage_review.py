"""Run a bounded source-only business-graph coverage audit over an explicit candidate."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


async def main():
    from uteki.agents.business_map import coverage_run
    from uteki.agents.runtime.local_credentials import load_provider_key

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observation-root', type=Path, required=True)
    parser.add_argument('--budget-usd', required=True)
    parser.add_argument('--inventory-max-tokens', type=int, default=18000)
    parser.add_argument('--audit-max-tokens', type=int, default=24000)
    parser.add_argument('--max-attempts', type=int, default=2)
    parser.add_argument('--prior-failed-run', type=Path)
    args = parser.parse_args()
    load_provider_key(ROOT, 'aihubmix')
    result = await coverage_run.execute(root=ROOT, input_run=args.input_run,
        output=ROOT/args.output, observation_root=ROOT/args.observation_root,
        budget_limit_usd=args.budget_usd, inventory_max_tokens=args.inventory_max_tokens,
        audit_max_tokens=args.audit_max_tokens, max_attempts=args.max_attempts,
        prior_failed_run=args.prior_failed_run)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
