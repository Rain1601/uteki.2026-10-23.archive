"""Explicit, clean source extraction. No prior candidate or review answers loaded."""
import asyncio,json,sys
from pathlib import Path
from decimal import Decimal
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from uteki.agents.business_map import product_run as run
from scripts.run_business_revenue_agent import save_preflight
from uteki.agents.runtime.local_credentials import load_provider_key
async def main():
 out=HERE/'run-02';old=ROOT/'experiments/agent_design/2026-10-07-microsoft-cloud-business-v1'
 if out.exists():raise ValueError('existing_run_no_resubmission')
 names=['run-01','run-02','repair-run-01','repair-run-03-contract-v2-connected','complete-candidate-v1','complete-candidate-v2','complete-candidate-v3','accepted-candidate-v1']
 spent=Decimal(0)
 for name in names:
  b=json.loads((old/name/'result.json').read_text())['budget']
  if b['unknown_requests'] or b['in_flight_requests']:raise ValueError('unsettled_previous_cost')
  spent+=Decimal(b['estimated_spent_usd'])
 b=json.loads((HERE/'run-01/result.json').read_text())['budget']
 if b['unknown_requests'] or b['in_flight_requests']:raise ValueError('unsettled_clean_run_cost')
 spent+=Decimal(b['estimated_spent_usd'])
 prepared=run.prepare(root=ROOT,packet_path=ROOT/'experiments/agent_design/2026-10-07-microsoft-input-audit-v1/clean-source-packet.json',skill_path=HERE/'input/skill-v2.md',company_id='sec-0000789019',document_id='msft-2025-10k',period_end='2025-06-30',model='claude-sonnet-5-5',effort='high',max_tokens=48000,timeout_seconds=600,stream=True,contract_version='business-draft-v2',thinking_type='between_tools')
 assert '<prior_candidate_data>' not in prepared['kwargs']['system_instructions']
 assert 'Preserve all 12' not in prepared['kwargs']['system_instructions']
 if Decimal(prepared['manifest']['reserved_estimated_usd'])>Decimal('3')-spent:raise ValueError('authorized_cumulative_budget_exceeded')
 save_preflight(prepared,HERE/'preflight-v2.json')
 (HERE/'budget-note-v2.json').write_text(json.dumps({'authorized_cumulative_usd':'3','prior_estimated_usd':str(spent),'remaining_usd':str(Decimal('3')-spent),'reserved_usd':prepared['manifest']['reserved_estimated_usd'],'actual_billed_usd':None},indent=2)+'\n')
 print(json.dumps({'phase':'prepared','reserved_usd':prepared['manifest']['reserved_estimated_usd'],'blocks':len(prepared['packet']['blocks']),'remaining_usd':str(Decimal('3')-spent)}),flush=True)
 if '--execute' not in sys.argv:return
 load_provider_key(ROOT,'aihubmix')
 result=await run.execute(prepared,root=ROOT,output=out,observation_root=ROOT/'data/agent_observability/local',budget_limit_usd=str(Decimal('3')-spent))
 print(json.dumps({k:result.get(k) for k in ['status','trace_id','counts','budget','validation','validation_error','error_type']},ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
