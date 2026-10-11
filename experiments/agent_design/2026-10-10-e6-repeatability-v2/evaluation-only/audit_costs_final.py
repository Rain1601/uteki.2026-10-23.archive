"""Independent read-only E6-V2 call/ledger reconciliation. No API or writes to runs.

Run while the experiment is paused between slots, or after its terminal result.
Partial reports preserve the fixed nine-slot denominator and unexecuted slots.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/e6-repeatability-20261010-r2'
read = lambda path: json.loads(Path(path).read_bytes())


def ledger(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        rows = {rid: {'reserved': reserved, 'actual': actual, 'state': state}
                for rid, reserved, actual, state in db.execute('SELECT id,reserved,actual,state FROM reservations')}
        limit = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
        cap = db.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0]
    return rows, limit, cap


def audit(partial=False):
    baseline = read(OUTPUT / 'ledger-before.v1.json')
    matrix = read(EXP / 'execution-matrix.v1.json')
    first = read(ROOT / matrix['runs'][0]['config'])
    rows, limit, cap = ledger(first['planner']['budget_ledger'])
    issues, all_calls, cases = [], [], []
    seen_calls, seen_reservations = set(), set()

    def check(condition, message):
        if not condition:
            issues.append(message)

    check(limit == baseline['usd_limit'] == '13', 'Shared USD13 authorization changed')
    check(cap == baseline['request_cap'] == 1000, 'Shared request1000 guard changed')
    check(all(rows.get(rid) == value for rid, value in baseline['rows'].items()), 'Historical ledger row changed or disappeared')
    new_ids = set(rows) - set(baseline['ids'])
    unsettled = sorted(rid for rid, value in rows.items() if value['state'] != 'settled')
    check(unsettled == baseline['unsettled_ids'], 'New unknown/inflight reservation needs investigation')

    for item in matrix['runs']:
        run = ROOT / item['run']
        config = read(ROOT / item['config'])
        for role in ('planner', 'worker', 'reviewer', 'question_reviewer'):
            value = config[role]
            check(value['budget_ledger'] == first['planner']['budget_ledger']
                  and value['budget_usd'] == '13' and value['max_requests_total'] == 1000
                  and value['budget_policy'] == 'enforced', item['slot_id'] + ': role budget/config drift')
            check(value['provider'] == 'deepseek' and value['model'] == 'deepseek-flash', item['slot_id'] + ': provider/model drift')
        if not run.exists():
            cases.append({'slot_id': item['slot_id'], 'execution': 'unexecuted', 'calls': 0, 'known_estimated_usd': None})
            check(partial, item['slot_id'] + ': fixed sample unexecuted')
            continue
        manifest = None
        if (run / 'manifest.json').exists():
            try:
                manifest = cycle._verify_manifest(run)
            except Exception as error:
                issues.append(item['slot_id'] + ': sealed manifest invalid: ' + str(error))
        else:
            issues.append(item['slot_id'] + ': existing run is unsealed; audit while paused')
        own = []
        start_paths = list(run.rglob('calls/*-start.json'))
        end_paths = list(run.rglob('calls/*-end.json'))
        starts = {p.name[:-11]: p for p in start_paths}
        ends = {p.name[:-9]: p for p in end_paths}
        check(len(starts) == len(start_paths) and len(ends) == len(end_paths),
              item['slot_id'] + ': duplicate call artifact across folders')
        check(starts.keys() == ends.keys(), item['slot_id'] + ': unmatched call-start/end')
        # Bind every cost artifact to its SDK attempt metadata as well as its seal.
        bound = {}
        for pattern in ('decision-*-attempt-*.json', 'review-*-attempt-*.json'):
            for path in run.rglob(pattern):
                for reference in read(path).get('calls', []):
                    target = path.parent / reference['path']
                    check(target.exists() and digest(target.read_bytes()) == reference['sha256'],
                          item['slot_id'] + ': SDK attempt call-reference mismatch')
                    bound.setdefault(target, []).append(path)
        for call_key, start_path in sorted(starts.items()):
            start = read(start_path)
            call_id, reservation = start['call_id'], start['budget_reservation_id']
            check(call_key == call_id and call_id not in seen_calls, item['slot_id'] + ': duplicate/misnamed call')
            check(reservation not in seen_reservations and reservation in new_ids, item['slot_id'] + ': duplicate/non-task reservation')
            seen_calls.add(call_id)
            seen_reservations.add(reservation)
            for path in (start_path, ends.get(call_key)):
                if path is None:
                    continue
                check(path in bound, item['slot_id'] + ': unbound SDK cost record ' + path.name)
                if manifest:
                    check(manifest['files'].get(str(path.relative_to(run))) == digest(path.read_bytes()),
                          item['slot_id'] + ': call missing from run manifest')
            if call_key not in ends:
                continue
            end_path = ends[call_key]
            end = read(end_path)
            row = rows.get(reservation)
            for key in ('call_id', 'stage', 'provider', 'requested_model', 'reasoning_effort',
                        'started_at', 'pricing_snapshot', 'configuration_snapshot', 'budget_reservation_id', 'reserved_usd'):
                check(start.get(key) == end.get(key), item['slot_id'] + ': start/end drift: ' + key)
            check(row is not None and Decimal(row['reserved']) == Decimal(end['reserved_usd']),
                  item['slot_id'] + ': ledger reserved amount mismatch')
            price, usage = end['pricing_snapshot'], end.get('usage')
            check(price['input_per_million'] == '0.30' and price['output_per_million'] == '1.20'
                  and price['currency'] == 'USD', item['slot_id'] + ': frozen price drift')
            amount = None
            if usage is not None and all(usage.get(k) is not None for k in ('input_tokens', 'output_tokens')):
                amount = (Decimal(usage['input_tokens']) * Decimal(price['input_per_million'])
                          + Decimal(usage['output_tokens']) * Decimal(price['output_per_million'])) / Decimal(1000000)
                check(end.get('estimated_usd') is not None and amount == Decimal(end['estimated_usd']),
                      item['slot_id'] + ': usage x frozen price differs from recorded estimate')
                raw = end.get('raw_usage')
                if raw:
                    check(raw.get('prompt_tokens') == usage['input_tokens']
                          and raw.get('completion_tokens') == usage['output_tokens'], item['slot_id'] + ': normalized/raw usage differ')
            elif end.get('usage_source') == 'host_not_sent' and end.get('estimated_usd') == '0':
                amount = Decimal(0)
            else:
                issues.append(item['slot_id'] + ': unknown billable usage; never substitute zero')
            if amount is not None:
                check(row is not None and row['state'] == 'settled' and row['actual'] is not None
                      and Decimal(row['actual']) == amount, item['slot_id'] + ': settled ledger/call amount mismatch')
            entry = {'call_id': call_id, 'reservation_id': reservation, 'status': end['status'],
                     'stage': end['stage'], 'role_path': str(end_path.parent.parent.relative_to(run)),
                     'start_sha256': digest(start_path.read_bytes()), 'end_sha256': digest(end_path.read_bytes()),
                     'known_estimated_usd': str(amount) if amount is not None else None,
                     'reserved_usd': end['reserved_usd'], 'recorded_actual_upstream_model': end.get('actual_upstream_model'),
                     'cached_tokens_recorded': ((usage or {}).get('input_tokens_details') or {}).get('cached_tokens')}
            own.append(entry)
        result = read(run / 'result.json') if (run / 'result.json').exists() else {}
        cases.append({'slot_id': item['slot_id'], 'execution': 'sealed' if manifest else 'unsealed',
                      'runtime_status': result.get('status'), 'calls': len(own),
                      'known_estimated_usd': str(sum((Decimal(c['known_estimated_usd']) for c in own
                                                   if c['known_estimated_usd'] is not None), Decimal(0))),
                      'failed_provider_call_ids': [c['call_id'] for c in own if c['status'] != 'succeeded'],
                      'retrieval_attempt_count': len(result.get('attempts', [])),
                      'run_manifest_sha256': digest((run / 'manifest.json').read_bytes()) if manifest else None})
        all_calls.extend(own)
    check(new_ids == seen_reservations, 'Task ledger reservations are not bound exactly once to recorded calls')
    known = sum((Decimal(value['actual']) for value in rows.values() if value['state'] == 'settled'), Decimal(0))
    held = sum((Decimal(value['reserved']) for value in rows.values() if value['state'] != 'settled'), Decimal(0))
    task_known, task_held = known - Decimal(baseline['known_usd']), held - Decimal(baseline['held_usd'])
    recorded = sum((Decimal(c['known_estimated_usd']) for c in all_calls if c['known_estimated_usd'] is not None), Decimal(0))
    check(recorded == task_known, 'All succeeded/failed call costs do not sum to task ledger increment')
    check(task_known + task_held <= Decimal('3'), 'Task occupied increment exceeds USD3 warning boundary')
    check(ledger(first['planner']['budget_ledger']) == (rows, limit, cap), 'Ledger changed during read-only audit; rerun while paused')
    return {'schema_version': 'e6-v2-independent-cost-integrity-audit-v1',
            'audit_api_calls': 0, 'status': 'pass' if not issues else 'fail', 'partial_snapshot': partial,
            'created_at': datetime.now(timezone.utc).isoformat(), 'planned_denominator': 9,
            'sealed_runs': sum(c['execution'] == 'sealed' for c in cases),
            'baseline_rows_immutable': all(rows.get(k) == v for k, v in baseline['rows'].items()),
            'new_reservations_bound_once': new_ids == seen_reservations,
            'same_ledger_limit_usd': limit, 'same_request_guard': cap,
            'old_unsettled_ids_retained': unsettled, 'all_success_and_failure_calls_included': True,
            'cases': cases, 'calls': all_calls, 'call_status_counts': dict(Counter(c['status'] for c in all_calls)),
            'task_new_known_estimated_usd': str(task_known), 'task_new_held_usd': str(task_held),
            'task_new_occupied_usd': str(task_known + task_held),
            'shared_ledger': {'requests': len(rows), 'known_usd': str(known), 'held_usd': str(held), 'occupied_usd': str(known + held)},
            'issues': issues, 'cost_is_provider_bill': False,
            'basis': 'Frozen peak list price times total prompt/completion usage; cache discounts excluded, no duplicate cache/reasoning tokens.',
            'auditor_sha256': digest(Path(__file__).read_bytes())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.partial)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({k: report[k] for k in ('status', 'sealed_runs', 'task_new_known_estimated_usd', 'issues')}))
    raise SystemExit(0 if report['status'] == 'pass' else 1)
