"""Zero-API experiment checks, metrics and task guard on the original ledger."""
from contextlib import contextmanager
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sqlite3
import threading
from unittest.mock import patch

from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'output/e6-repeatability-20261010-r3'
read = lambda p: json.loads(Path(p).read_bytes())


def ledger(config):
    path = Path(config['planner']['budget_ledger'])
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    rows = {rid: {'reserved': reserved, 'actual': actual, 'state': state}
            for rid, reserved, actual, state in db.execute('SELECT id,reserved,actual,state FROM reservations')}
    limit = db.execute('SELECT usd FROM config').fetchone()[0]
    cap = db.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0]
    db.close()
    known = sum((Decimal(r['actual']) for r in rows.values() if r['state'] == 'settled'), Decimal(0))
    held = sum((Decimal(r['reserved']) for r in rows.values() if r['state'] != 'settled'), Decimal(0))
    return {'rows': rows, 'ids': list(rows), 'requests': len(rows), 'request_cap': cap,
            'known_usd': str(known), 'held_usd': str(held), 'occupied_usd': str(known + held),
            'unsettled_ids': sorted(k for k, v in rows.items() if v['state'] != 'settled'), 'usd_limit': limit}


def check_ledger(config):
    current = ledger(config)
    base = read(OUTPUT / 'ledger-before.v1.json')
    assert current['usd_limit'] == base['usd_limit'] and current['request_cap'] == base['request_cap']
    assert all(current['rows'].get(k) == v for k, v in base['rows'].items()), 'historical ledger changed'
    assert current['unsettled_ids'] == base['unsettled_ids'], 'new unknown/inflight; stop and investigate'
    return current


def verify_freeze():
    freeze = read(EXP / 'evaluation-only/freeze.v1.json')
    for relative, expected in freeze['files'].items():
        assert digest((ROOT / relative).read_bytes()) == expected, relative
    for relative, expected in freeze['sealed_refs'].items():
        cycle._verify_manifest(ROOT / relative, expected)


@contextmanager
def task_guard(config):
    """Local serial-run guard; no new ledger or change to shared authorization."""
    base = read(OUTPUT / 'ledger-before.v1.json')
    original = RunBudget.reserve
    lock = threading.RLock()
    expected = Path(config['planner']['budget_ledger']).resolve()

    def reserve(budget, amount):
        assert budget.path.resolve() == expected, 'unexpected ledger'
        with lock:
            now = ledger(config)
            increment = Decimal(now['occupied_usd']) - Decimal(base['occupied_usd'])
            if increment + Decimal(str(amount)) > Decimal('3'):
                raise BudgetExceeded('E6-V3 task warning boundary reached before dispatch; original ledger retained')
            return original(budget, amount)

    with patch.object(RunBudget, 'reserve', reserve):
        yield


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metrics(item):
    legacy = load_module('frozen_v1_metrics', ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v1/evaluation-only/collect_metrics.py')
    run = ROOT / item['run']
    try:
        value = legacy.collect(item)
    except Exception as error:
        # A zero-dispatch/partial failure must still get a receipt and retain its
        # terminal reason. This is a disclosed metric gap, never a successful run.
        calls = [read(p) for p in run.rglob('calls/*-end.json')]
        value = {'slot_id': item['slot_id'], 'calls': len(calls),
                 'known_estimated_usd': str(sum((Decimal(c['estimated_usd']) for c in calls
                     if c.get('estimated_usd') is not None), Decimal(0))),
                 'metric_collection_error': {'type': type(error).__name__, 'error': str(error)},
                 'mechanical_no_recovery': False, 'strict_load_gate': {'status': 'not_available'},
                 'recovery_events': {}}
    # R1 adds an explicit source repair inside one review execution; preserve it.
    source_repairs = [str(p.relative_to(ROOT)) for p in run.rglob('source-repair-input.json')]
    for p in run.rglob('result.json'):
        row = read(p)
        if row.get('source_protocol_repair_attempted') or row.get('source_review_protocol_repair_attempted'):
            source_repairs.append(str(p.relative_to(ROOT)))
    # The second source logical review is distinct from a wire retry of attempt 1.
    source_logical = [str(p.relative_to(ROOT)) for p in run.rglob('review-0002-input.json')
                      if p.parent.name == 'model']
    value['recovery_events']['source_protocol_repair_artifacts'] = sorted(set(source_repairs + source_logical))
    value['mechanical_no_recovery'] = value['mechanical_no_recovery'] and not (source_repairs or source_logical)
    return value


def terminal_reason(result, run, current):
    if result['status'] == 'cancelled':
        return 'cancelled'
    if any(row.get('error_type') == 'BudgetExceeded' for row in result.get('failures', []) + result.get('attempts', [])):
        return 'task_or_shared_budget_boundary'
    if current['requests'] >= current['request_cap'] or Decimal(current['occupied_usd']) >= Decimal(current['usd_limit']):
        return 'shared_budget_or_request_guard'
    records = [read(p) for p in run.rglob('calls/*-end.json')]
    if any(r.get('error_type') == 'BudgetExceeded' for r in records):
        return 'task_or_shared_budget_boundary'
    if any(r.get('http_status') in {401, 403} or r.get('error_type') in {'AuthenticationError', 'PermissionDeniedError'} for r in records):
        return 'authentication_or_permission_failure'
    policy = load_module('frozen_transport_policy', ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v1/evaluation-only/stop_policy_v3.py')
    # Only final bounded role outcomes are terminal; earlier recovered errors stay costs.
    roles = {}
    for pattern in ('decision-*-attempt-*.json', 'review-*-attempt-*.json'):
        for path in run.rglob(pattern):
            row = read(path)
            if row.get('error_type') == 'BudgetExceeded':
                return 'task_or_shared_budget_boundary'
            role = row.get('role') or ('question_reviewer' if path.parent.name == 'question-model' else 'source_reviewer')
            key = row.get('ended_at', ''), str(path)
            if role not in roles or key > roles[role][0]:
                roles[role] = key, row
    if any(row.get('status') not in {'decision_returned', 'json_returned'} and not row.get('retry_scheduled')
           and policy.transport_failure(row) for _, row in roles.values()):
        return 'bounded_infrastructure_failure_unrecovered'
    return None
