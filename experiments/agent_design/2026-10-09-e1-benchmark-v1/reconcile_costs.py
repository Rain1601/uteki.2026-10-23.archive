"""Reconcile each existing reservation with original receipts, without changing credit."""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    return hashlib.sha256(value).hexdigest()


def amount(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError('invalid receipt or ledger amount')
    return value


def ledger_snapshot(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        cap = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
        maximum = db.execute('SELECT maximum FROM autonomous_request_limit WHERE id=1').fetchone()[0]
        rows = [dict(zip(('id', 'reserved', 'actual', 'state'), row)) for row in
                db.execute('SELECT id,reserved,actual,state FROM reservations ORDER BY id')]
    return {'released_limit_usd': cap, 'request_limit': maximum, 'reservations': rows}


def reconcile(ledger, receipts_root):
    before = ledger_snapshot(ledger)
    receipts, issues = defaultdict(lambda: {'start': [], 'end': []}), []
    call_ids = defaultdict(set)
    receipt_hashes = {}
    for phase in ('start', 'end'):
        for path in sorted(receipts_root.glob('**/calls/*-' + phase + '.json')):
            raw = path.read_bytes()
            value = json.loads(raw)
            ref = str(path.relative_to(receipts_root))
            reservation = value.get('budget_reservation_id')
            receipt_hashes[ref] = digest(raw)
            if not isinstance(reservation, str) or not reservation:
                issues.append({'issue': 'missing_reservation_identity', 'receipt': ref})
                continue
            receipts[reservation][phase].append((ref, value))
            call_ids[value['call_id']].add(reservation)
    for call_id, identities in call_ids.items():
        if len(identities) != 1:
            issues.append({'issue': 'call_has_multiple_reservations', 'call_id': call_id})
    known = unknown = inflight = Decimal(0)
    rows = []
    for row in before['reservations']:
        rid, state = row['id'], row['state']
        pair = receipts.pop(rid, {'start': [], 'end': []})
        errors = []
        reserved = amount(row['reserved'])
        actual = amount(row['actual']) if row['actual'] is not None else None
        if state == 'settled' and actual is not None:
            known += actual
        elif state == 'unknown' and actual is None:
            unknown += reserved
        elif state == 'reserved' and actual is None:
            inflight += reserved
        else:
            errors.append('invalid_ledger_state_or_amount')
        if len(pair['start']) != 1:
            errors.append('expected_one_start_receipt')
        if len(pair['end']) != (0 if state == 'reserved' else 1):
            errors.append('unexpected_end_receipt_count')
        entries = pair['start'] + pair['end']
        if len({value['call_id'] for _, value in entries}) > 1:
            errors.append('reservation_has_multiple_calls')
        for field in ('provider', 'requested_model', 'stage', 'started_at'):
            if len({value.get(field) for _, value in entries}) > 1:
                errors.append('receipt_identity_differs_' + field)
        for _, value in entries:
            if amount(value['reserved_usd']) != reserved:
                errors.append('reserved_amount_differs')
        for _, value in pair['end']:
            estimated = value.get('estimated_usd')
            if state == 'settled' and (estimated is None or amount(estimated) != actual):
                errors.append('settled_amount_differs')
            if state == 'unknown' and estimated is not None:
                errors.append('unknown_reservation_has_known_receipt')
        refs = {phase: [ref for ref, _ in pair[phase]] for phase in ('start', 'end')}
        rows.append({'reservation_id': rid, 'ledger_state': state,
            'reserved_usd': str(reserved), 'known_estimated_usd': str(actual) if actual is not None else None,
            'unknown_reserved_usd': str(reserved) if state == 'unknown' else '0',
            'inflight_reserved_usd': str(reserved) if state == 'reserved' else '0',
            'call_ids': sorted({value['call_id'] for _, value in entries}), 'receipts': refs,
            'receipt_sha256': {ref: receipt_hashes[ref] for ref, _ in entries},
            'provider': entries[0][1].get('provider') if entries else None,
            'requested_model': entries[0][1].get('requested_model') if entries else None,
            'stage': entries[0][1].get('stage') if entries else None,
            'call_status': pair['end'][0][1].get('status') if len(pair['end']) == 1 else None,
            'match': not errors, 'issues': sorted(set(errors))})
    for rid, pair in receipts.items():
        issues.append({'issue': 'receipt_reservation_absent_from_ledger', 'reservation_id': rid,
                       'receipts': [ref for entries in pair.values() for ref, _ in entries]})
    after = ledger_snapshot(ledger)
    changed = before != after
    if changed:
        issues.append({'issue': 'ledger_changed_during_scan_rerun_after_calls_finish'})
    mismatches = sum(not row['match'] for row in rows)
    held = unknown + inflight
    cap = amount(before['released_limit_usd'])
    if known + held > cap:
        issues.append({'issue': 'committed_amount_exceeds_released_limit'})
    if cap > 100 or len(rows) > before['request_limit']:
        issues.append({'issue': 'authorization_or_request_limit_exceeded'})
    quiescent = not changed and inflight == 0 and all(r['ledger_state'] != 'reserved' for r in rows)
    return {'schema_version': 'e1-reservation-reconciliation-v1',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'status': 'matched_quiescent' if quiescent and not issues and not mismatches else 'provisional_or_mismatch',
        'read_only': True, 'model_calls': 0, 'quiescent': quiescent,
        'ledger_snapshot_sha256': digest(json.dumps(before, sort_keys=True).encode()),
        'released_limit_usd': str(cap), 'global_authorization_usd': '100',
        'requests': len(rows), 'settled_requests': sum(r['ledger_state'] == 'settled' for r in rows),
        'unknown_requests': sum(r['ledger_state'] == 'unknown' for r in rows),
        'inflight_requests': sum(r['ledger_state'] == 'reserved' for r in rows),
        'known_estimated_usd': str(known), 'unknown_reserved_usd': str(unknown),
        'inflight_reserved_usd': str(inflight), 'committed_upper_bound_usd': str(known + held),
        'remaining_released_usd': str(cap-known-held), 'mismatched_reservations': mismatches,
        'issues': issues, 'reservations': rows, 'actual_billed_usd': None,
        'limitations': 'Costs are original receipt estimates, not supplier billing. Unknown reservations remain held in full. A live scan is provisional; rerun after all calls stop. No account credentials, prompts or response content are exported.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--receipts-root', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--final', action='store_true', help='Refuse output unless idle and every reservation matches')
    args = parser.parse_args()
    result = reconcile(args.ledger, args.receipts_root)
    if args.final and result['status'] != 'matched_quiescent':
        raise SystemExit('Not final: calls are active, the snapshot changed, or a reservation differs')
    if args.output:
        if args.output.exists():
            raise SystemExit('Output already exists; preserve earlier reconciliation snapshots')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'reservations'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
