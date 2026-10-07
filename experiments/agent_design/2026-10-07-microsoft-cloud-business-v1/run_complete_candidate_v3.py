"""Explicit complete-candidate run; no automatic retries, budget includes all known runs."""
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from uteki.agents.business_map import product_run as run
from uteki.agents.runtime.local_credentials import load_provider_key
from scripts.run_business_revenue_agent import save_preflight

async def main():
    output=HERE/'complete-candidate-v3'
    if output.exists():raise ValueError('existing_run_no_resubmission')
    spent=Decimal('0');records=[]
    for name in ['run-01','run-02','repair-run-01','repair-run-03-contract-v2-connected','complete-candidate-v1','complete-candidate-v2']:
        raw=json.loads((HERE/name/'result.json').read_text());b=raw['budget']
        if b['unknown_requests'] or b['in_flight_requests']:raise ValueError('unsettled_cost')
        spent+=Decimal(b['estimated_spent_usd']);records.append({'run':name,'usd':b['estimated_spent_usd']})
    prepared=run.prepare(root=ROOT,packet_path=HERE/'input/source_packet.json',skill_path=HERE/'input/skill-complete-candidate-v3.md',
        company_id='sec-0000789019',document_id='msft-2025-10k',period_end='2025-06-30',
        model='claude-sonnet-5-5',effort='high',max_tokens=24000,timeout_seconds=600,stream=True,
        contract_version='business-draft-v2',thinking_type='between_tools')
    if Decimal(prepared['manifest']['reserved_estimated_usd'])>Decimal('3')-spent:raise ValueError('authorized_total_exceeded')
    save_preflight(prepared,HERE/'complete-candidate-v3-preflight.json')
    budget_note={'authorized_total_usd':'3.00','prior_known_estimated_usd':str(spent),'prior_runs':records,
        'connection_failure_reconciliation':'repair-run-03-contract-v2-connected/manifest.json',
        'remaining_usd':str(Decimal('3')-spent),'reason':'User authorized autonomous iteration within $3 cumulative on this task.'}
    note=HERE/'complete-candidate-v3-budget.json'
    if not note.exists():note.write_text(json.dumps(budget_note,indent=2)+'\n')
    if '--execute' not in sys.argv:return
    load_provider_key(ROOT,'aihubmix')
    result=await run.execute(prepared,root=ROOT,output=output,observation_root=ROOT/'data/agent_observability/local',budget_limit_usd=str(Decimal('3')-spent))
    print(json.dumps({k:result.get(k) for k in ['status','trace_id','budget','validation']},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
