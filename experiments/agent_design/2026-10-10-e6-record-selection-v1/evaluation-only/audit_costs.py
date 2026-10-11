"""Reconcile all new real calls to the unchanged shared ledger; no API."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'output/e6-record-selection-20261010-r1'
read = lambda p: json.loads(p.read_bytes())


def audit(report_name):
    baseline = read(OUTPUT / 'ledger-before.v1.json')
    config = read(EXP / 'config/fresh-S1.v1.json')
    db = sqlite3.connect(Path(config['planner']['budget_ledger']).as_uri() + '?mode=ro', uri=True)
    rows = {rid: {'reserved': reserved, 'actual': actual, 'state': state}
            for rid, reserved, actual, state in db.execute('SELECT id,reserved,actual,state FROM reservations')}
    db.close()
    assert set(baseline['ids']) <= rows.keys()
    new_ids = set(rows) - set(baseline['ids'])
    cost_ids, calls, cases = set(), [], []
    for case in read(EXP / 'execution-matrix.v1.json')['cases']:
        root = OUTPUT / case['id'] / 'run-r1'
        if not (root / 'manifest.json').exists():
            continue
        own = []
        for end in sorted(root.rglob('calls/*-end.json')):
            call = read(end)
            start = end.with_name(end.name.replace('-end.json', '-start.json'))
            assert read(start)['call_id'] == call['call_id']
            rid = call['budget_reservation_id']
            assert rid not in cost_ids and rid in new_ids
            cost_ids.add(rid)
            usage, price = call['usage'], call['pricing_snapshot']
            assert usage is not None and rows[rid]['state'] == 'settled'
            value = (Decimal(usage['input_tokens']) * Decimal(price['input_per_million'])
                     + Decimal(usage['output_tokens']) * Decimal(price['output_per_million'])) / Decimal(1000000)
            assert value == Decimal(call['estimated_usd']) == Decimal(rows[rid]['actual'])
            own.append({'call_id': call['call_id'], 'reservation_id': rid, 'status': call['status'],
                        'role_path': str(end.parent.parent.relative_to(root)),
                        'call_end_sha256': digest(end.read_bytes()), 'estimated_usd': str(value)})
        result = read(root / 'result.json')
        cases.append({'case_id': case['id'], 'operation': case['operation'], 'calls': len(own),
                      'known_estimated_usd': str(sum((Decimal(c['estimated_usd']) for c in own), Decimal(0))),
                      'retrieval_attempts': len(result['attempts']), 'status': result['status']})
        calls.extend(own)
    assert new_ids == cost_ids, 'New ledger reservations must all bind to a recorded call'
    unsettled = sorted(rid for rid, row in rows.items() if row['state'] != 'settled')
    assert unsettled == baseline['unsettled_ids'], 'New unknown/inflight needs investigation'
    known = sum((Decimal(row['actual']) for row in rows.values() if row['state'] == 'settled'), Decimal(0))
    held = sum((Decimal(row['reserved']) for row in rows.values() if row['state'] != 'settled'), Decimal(0))
    report = {'schema_version': 'e6-r2-shared-cost-audit-v1', 'audit_api_calls': 0,
              'historical_reservation_ids_preserved': True, 'all_new_reservations_bound_once': True,
              'old_unsettled_ids_preserved': unsettled, 'cases': cases, 'calls': calls,
              'task_new_known_estimated_usd': str(known - Decimal(baseline['known_usd'])),
              'task_new_held_usd': str(held - Decimal(baseline['held_usd'])),
              'shared_ledger': {'requests': len(rows), 'known_estimated_usd': str(known),
                                'held_usd': str(held), 'occupied_usd': str(known + held)},
              'cost_is_provider_bill': False}
    write_new(EXP / 'evaluation-only' / report_name, report)
    print(json.dumps({'cases': cases, 'shared_ledger': report['shared_ledger']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report-name', required=True)
    audit(parser.parse_args().report_name)
