#!/usr/bin/env python3
"""Prepare one separately authorized between-tools repair recovery; default is offline."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import repair_once as repair


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--confirmed-total-budget-usd',choices=['0.70'])
    parser.add_argument('--target-contract-version',choices=[repair.BUSINESS_DRAFT_VERSION,repair.BUSINESS_DRAFT_V2_VERSION],default=repair.BUSINESS_DRAFT_VERSION)
    parser.add_argument('--connection-recovery',action='store_true')
    args=parser.parse_args()
    if args.execute and args.confirmed_total_budget_usd!='0.70':
        parser.error('--execute requires the user-confirmed total budget: --confirmed-total-budget-usd 0.70')
    prepared=repair.prepare(HERE/'repair-input.json',max_tokens=6000,
        recovery_profile=repair.RECOVERY_PROFILE,target_contract_version=args.target_contract_version,connection_recovery=args.connection_recovery)
    repair.preflight(prepared)
    if args.execute:
        from uteki.agents.runtime.local_credentials import load_provider_key
        if prepared['manifest']['budget_gate']!='ready':
            raise repair.BudgetExceeded('repair_recovery_preflight_budget_blocked')
        load_provider_key(repair.ROOT,'aihubmix')
        result=asyncio.run(repair.execute(prepared,
            observation_root=repair.ROOT/'data/agent_observability/local',
            confirmed_total_budget_usd=args.confirmed_total_budget_usd))
        print(json.dumps({k:result[k] for k in ('status','trace_id','execution_mode','budget')},ensure_ascii=False))


if __name__=='__main__':main()
