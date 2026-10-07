"""Explicit independent graph run; reference candidate is not loaded here."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from uteki.agents.business_map import product_run as run
from uteki.agents.business_map import independent_run
from scripts.run_business_revenue_agent import save_preflight
from uteki.agents.runtime.local_credentials import load_provider_key

async def main():
    output = HERE / 'run-01'
    if output.exists():
        raise ValueError('frozen_run_exists_no_resubmission')
    prepared = run.prepare(
        root=ROOT,
        packet_path=ROOT / 'experiments/agent_design/2026-10-07-microsoft-input-audit-v1/clean-source-packet.json',
        skill_path=HERE / 'input/graph-stage.md',
        company_id='sec-0000789019', document_id='msft-2025-10k', period_end='2025-06-30',
        model='claude-sonnet-5-5', effort='high', max_tokens=48000,
        timeout_seconds=600, stream=True, contract_version='business-draft-v2',
        thinking_type='between_tools')
    run.verify_prepared(prepared)
    save_preflight(prepared, HERE / 'preflight-48k.json')
    # Latest explicit authorization replaces the previous cumulative ceiling.
    # This one task includes the initial request and its bounded revision.
    task_limit = Decimal('3')
    note = dict(policy='per_task_warning_boundary', authorized_task_limit_usd=str(task_limit),
                historical_estimated_usd='2.510078', historical_cost_is_separate=True,
                reserved_usd=prepared['manifest']['reserved_estimated_usd'], actual_billed_usd=None,
                authorization='User confirmed necessary calls; warn before one task exceeds USD 3.')
    (HERE / 'budget-authorization-v2.json').write_text(json.dumps(note, indent=2)+'\n')
    print(json.dumps(note), flush=True)
    if '--execute' not in sys.argv:
        await prepared['native'].aclose()
        return
    if Decimal(note['reserved_usd']) > task_limit:
        await prepared['native'].aclose()
        raise ValueError('per_task_budget_warning_requires_review')
    load_provider_key(ROOT, 'aihubmix')
    result = await independent_run.execute(prepared, root=ROOT, output=output,
        observation_root=ROOT/'data/agent_observability/local', budget_limit_usd=str(task_limit), max_revisions=1)
    print(json.dumps({k:result.get(k) for k in ('status','candidate_path','estimated_spent_usd','attempts','stop_reason')}, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(main())
