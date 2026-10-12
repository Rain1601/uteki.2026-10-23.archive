"""Explicit fresh revenue experiment; system runtime chooses all evidence. No gold input."""
import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.retrieval_cycle import run_retrieval_cycle, validate
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'output/revenue-stability-20261012'
LEDGER = ROOT / 'experiments/agent_design/2026-10-09-e1-benchmark-v1/costs.sqlite'
QUESTION = ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1/question.v1.json'


def read(path):
    return json.loads(path.read_bytes())


def ledger():
    with sqlite3.connect(LEDGER.as_uri() + '?mode=ro', uri=True) as db:
        rows = {rid: {'reserved': r, 'actual': a, 'state': s}
                for rid, r, a, s in db.execute('SELECT id,reserved,actual,state FROM reservations')}
        limit = db.execute('SELECT usd FROM config').fetchone()[0]
        cap = db.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0]
    return {'rows': rows, 'limit': limit, 'request_cap': cap,
        'occupied': str(sum((Decimal(v['actual'] if v['state'] == 'settled' else v['reserved'])
                            for v in rows.values()), Decimal(0))),
        'unknown': sorted(k for k,v in rows.items() if v['state'] == 'unknown')}


def implementation():
    files = [p for base in (ROOT/'src/uteki', ROOT/'skills/data-agent') for p in base.rglob('*')
             if p.is_file() and p.suffix in {'.py', '.md', '.json'}]
    files.append(Path(__file__))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def config_for(slot, version):
    model = {'provider': 'deepseek', 'model': 'deepseek-flash', 'reasoning_effort': 'low',
             'max_tokens': 8192, 'request_timeout': 180, 'max_retries': 1,
             'budget_ledger': str(LEDGER), 'budget_usd': '40', 'budget_policy': 'enforced',
             'max_requests_total': 500, 'allow_unknown_reservations': True}
    reviewers = {**model, 'max_tokens': 16384, 'reasoning_effort': 'none'}
    return {'request': {'question': read(QUESTION)['question'], 'purpose': 'analysis_evidence',
        'dataset': str(BASE/'preparation-v1/dataset'), 'scope': read(BASE/'preparation-v1/scope.json'),
        'limits': {'max_steps': 32, 'max_packet_bytes': 160000, 'observation_bytes': 24000,
                   'page_items': 12, 'turn_timeout': 240}},
        'planner': deepcopy(model), 'worker': deepcopy(model),
        'reviewer': deepcopy(reviewers), 'question_reviewer': deepcopy(reviewers),
        'question_review_policy': 'independent-question-v2',
        'credential_root': str(ROOT), 'workspace': str(BASE/version/slot/'workspace'),
        'max_review_packet_bytes': 400000, 'reviewer_max_request_bytes': 600000, 'max_attempts': 2}


@contextmanager
def bounded_task():
    baseline = read(BASE/'budget-baseline.v1.json')
    reserve = RunBudget.reserve
    def guarded(budget, amount):
        if budget.path.resolve() != LEDGER:
            raise BudgetExceeded('Unexpected ledger; do not fork task allowance')
        state = ledger()
        if state['limit'] != baseline['limit'] or state['request_cap'] != baseline['request_cap']:
            raise BudgetExceeded('Shared budget changed; inspect before dispatch')
        if any(state['rows'].get(k) != v for k,v in baseline['rows'].items()):
            raise BudgetExceeded('Historical reservation changed')
        if state['unknown'] != baseline['unknown']:
            raise BudgetExceeded('New unknown cost; reconcile before more calls')
        if Decimal(state['occupied']) - Decimal(baseline['occupied']) + Decimal(str(amount)) > Decimal('3'):
            raise BudgetExceeded('This task reached its USD 3 boundary')
        return reserve(budget, amount)
    with patch.object(RunBudget, 'reserve', guarded):
        yield


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', choices=['R1','R2','R3'], required=True)
    parser.add_argument('--version', choices=['v1','v2','v3'], default='v1')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    folder = BASE/args.version/args.slot
    config = config_for(args.slot, args.version)
    validate(config, folder/'run')
    if args.check_only:
        print('validated; no dispatch')
        return
    # Serialize this experiment; keep the existing ledger and all prior charges.
    with (BASE/'execution.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        baseline_path = BASE/'budget-baseline.v1.json'
        if not baseline_path.exists():
            write_new(baseline_path, ledger())
        freeze_path = BASE/args.version/'implementation-freeze.json'
        current = implementation()
        if freeze_path.exists():
            if read(freeze_path) != current:
                raise ValueError('Implementation changed: freeze a new version, keep old failures')
        else:
            write_new(freeze_path, current)
        write_new(folder/'runtime-config.json', config)
        write_new(folder/'ledger-before.json', ledger())
        try:
            with bounded_task():
                result = asyncio.run(run_retrieval_cycle(config, folder/'run'))
            print(json.dumps({'slot': args.slot, 'version': args.version,
                              'status': result['status'], 'failures': result['failures']}, ensure_ascii=False))
        finally:
            write_new(folder/'ledger-after.json', ledger())


if __name__ == '__main__':
    main()
