"""Generate and self-review a brief from a frozen source packet and explicit task."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


async def main():
    from uteki.agents.filing_brief.run import prepare, execute
    from uteki.agents.runtime.local_credentials import load_provider_key
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packet','task','skill','output','observation-root','model','budget-usd'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-tokens',type=int,default=16000)
    parser.add_argument('--repair-run',help='Explicit failed generation to repair once, sharing its original task budget.')
    parser.add_argument('--audit-run',help='Explicit candidate for one model audit/revision/fresh-audit loop on its existing budget.')
    parser.add_argument('--review-model')
    parser.add_argument('--resume-audit-run',help='One known-cost initial audit recovery after max_tokens; original ledger retained.')
    parser.add_argument('--review-max-tokens',type=int,default=12000)
    args=parser.parse_args()
    load_provider_key(ROOT,'aihubmix')
    prepared=prepare(root=ROOT,packet_path=args.packet,task_path=args.task,skill_path=args.skill,
                     model=args.model,max_tokens=args.max_tokens)
    result=await execute(prepared,output=ROOT/args.output,observation_root=ROOT/args.observation_root,budget_usd=args.budget_usd,
                         repair_run=args.repair_run,audit_run=args.audit_run,review_model=args.review_model,
                         review_max_tokens=args.review_max_tokens,resume_audit_run=args.resume_audit_run)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['status']=='candidate' else 1


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
