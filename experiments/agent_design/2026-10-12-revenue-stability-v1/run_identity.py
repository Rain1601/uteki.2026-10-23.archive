"""Three authorized fresh runs, preserving the original USD 3 cumulative task guard."""
import argparse
import asyncio
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from run_fresh import BASE, ROOT, LEDGER, read, ledger, implementation, config_for
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.retrieval_cycle import run_retrieval_cycle, validate
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


@contextmanager
def guarded_task():
    original = read(BASE/'budget-baseline.v1.json')
    amendment = read(BASE/'request-cap-amendment.v4.json')
    reserve = RunBudget.reserve
    def checked(budget, amount):
        state = ledger()
        if (budget.path.resolve() != LEDGER or state['limit'] != original['limit']
                or state['request_cap'] != amendment['request_cap_after']
                or state['unknown'] != original['unknown']
                or any(state['rows'].get(k) != v for k, v in original['rows'].items())):
            raise BudgetExceeded('Original ledger, USD limit or historical charges changed')
        if Decimal(state['occupied']) - Decimal(original['occupied']) + Decimal(str(amount)) > Decimal('3'):
            raise BudgetExceeded('Original cumulative task USD 3 boundary reached')
        return reserve(budget, amount)
    with patch.object(RunBudget, 'reserve', checked):
        yield


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', required=True, choices=['R1', 'R2', 'R3'])
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    folder = BASE/'v4'/args.slot
    config = config_for(args.slot, 'v4')
    # Mechanical call-count guard, not a new dollar allowance. Original charges remain.
    for role in ('planner', 'worker', 'reviewer', 'question_reviewer'):
        config[role]['max_requests_total'] = 600
    validate(config, folder/'run')
    if args.check_only:
        print('validated; no dispatch')
        return
    with (BASE/'execution.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = implementation()
        current[str(Path(__file__).resolve().relative_to(ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        freeze = BASE/'v4/implementation-freeze.json'
        if freeze.exists():
            if read(freeze) != current:
                raise ValueError('Implementation changed during independent repetitions')
        else:
            write_new(freeze, current)
        write_new(folder/'runtime-config.json', config)
        write_new(folder/'ledger-before.json', ledger())
        try:
            with guarded_task():
                result = asyncio.run(run_retrieval_cycle(config, folder/'run'))
            print(json.dumps({'slot': args.slot, 'version': 'v4', 'status': result['status'],
                              'failures': result['failures']}, ensure_ascii=False))
        finally:
            write_new(folder/'ledger-after.json', ledger())


if __name__ == '__main__':
    main()
