"""Read-only accounting from call receipts; never dispatches a model request."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from datetime import datetime, timezone
import json
import math
from pathlib import Path


def money(value):
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid nonnegative receipt amount')
    return amount


def token_fields(value, prefix=''):
    """Keep reported token counters in their own field; never synthesize totals."""
    if not isinstance(value, dict):
        return {}
    fields = {}
    for key, item in value.items():
        path = prefix + key
        if isinstance(item, dict):
            fields.update(token_fields(item, path + '.'))
        elif key.endswith('tokens') and type(item) is int and item >= 0:
            fields[path] = item
    return fields


def request_timing(calls, pending_count=0):
    """Only receipt measurements; missing/invalid data never becomes zero or mtime."""
    def timestamp(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
        except ValueError:
            return None
    elapsed, intervals = [], []
    for call in calls:
        seconds = call.get('elapsed_seconds')
        if type(seconds) in (float, int) and math.isfinite(seconds) and seconds >= 0:
            elapsed.append(seconds)
        start, end = timestamp(call.get('started_at')), timestamp(call.get('ended_at'))
        if start is not None and end is not None and end >= start:
            intervals.append((start, end))
    durations_complete = bool(calls) and len(elapsed) == len(calls) and pending_count == 0
    intervals_complete = bool(calls) and len(intervals) == len(calls) and pending_count == 0
    first = min((p[0] for p in intervals), default=None) if intervals_complete else None
    last = max((p[1] for p in intervals), default=None) if intervals_complete else None
    return {'completed_calls': len(calls), 'unmatched_started_calls': pending_count,
            'measured_elapsed_calls': len(elapsed), 'timestamped_interval_calls': len(intervals),
            'known_cumulative_request_seconds': math.fsum(elapsed) if elapsed else None,
            'cumulative_request_seconds': math.fsum(elapsed) if durations_complete else None,
            'first_request_at': first.isoformat() if first else None,
            'last_request_ended_at': last.isoformat() if last else None,
            'request_window_seconds': (last-first).total_seconds() if intervals_complete else None}


def summarize(root):
    rows = []
    seen_calls = set()
    for run in sorted(root.iterdir()):
        if not run.is_dir():
            continue
        costs = defaultdict(lambda: Decimal('0'))
        usage = Counter()
        statuses = Counter()
        calls = 0
        unknown = Decimal('0')
        groups = {}
        ended = set()
        timed_calls = []
        for receipt in sorted(run.glob('**/calls/*-end.json')):
            call = json.loads(receipt.read_text())
            identity = call['call_id']
            if identity in seen_calls:
                raise ValueError('duplicate call receipt: ' + identity)
            seen_calls.add(identity)
            ended.add(identity)
            timed_calls.append(call)
            calls += 1
            statuses[call['status']] += 1
            amount = call.get('estimated_usd')
            if amount is None:
                unknown += money(call['reserved_usd'])
            else:
                costs[call['stage']] += money(amount)
            raw = call.get('raw_usage') or call.get('usage') or {}
            key = tuple(call.get(field) for field in ('provider', 'requested_model', 'stage', 'cost_basis'))
            if key not in groups:
                groups[key] = {'provider': key[0], 'requested_model': key[1], 'stage': key[2],
                    'cost_basis': key[3], 'calls': 0, 'known_estimated_usd': Decimal('0'),
                    'unknown_reserved_usd': Decimal('0'), 'usage_by_provider_field': Counter(),
                    'usage_sources': Counter(), 'call_statuses': Counter()}
            group = groups[key]
            group['calls'] += 1
            group['call_statuses'][call['status']] += 1
            group['known_estimated_usd' if amount is not None else 'unknown_reserved_usd'] += money(
                amount if amount is not None else call['reserved_usd'])
            group['usage_by_provider_field'].update(token_fields(raw))
            group['usage_sources']['raw_usage' if call.get('raw_usage') else 'usage' if call.get('usage') else 'absent'] += 1
            # Preserve provider field names. Input is not assumed to include cache reads.
            for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                        'cache_creation_input_tokens', 'prompt_tokens', 'completion_tokens'):
                if type(raw.get(key)) is int and raw[key] >= 0:
                    usage[key] += raw[key]
        pending = []
        for receipt in sorted(run.glob('**/calls/*-start.json')):
            call = json.loads(receipt.read_text())
            if call['call_id'] in ended:
                continue
            if call['call_id'] in seen_calls:
                raise ValueError('duplicate call receipt: ' + call['call_id'])
            seen_calls.add(call['call_id'])
            pending.append({'call_id': call['call_id'], 'stage': call.get('stage'),
                            'provider': call.get('provider'), 'requested_model': call.get('requested_model'),
                            'reserved_usd': str(money(call['reserved_usd'])),
                            'status': 'start_without_end_not_assumed_free'})
        pending_reserved = sum((money(c['reserved_usd']) for c in pending), Decimal('0'))
        result_path = run / 'result.json'
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        grouped = []
        for group in groups.values():
            grouped.append({**group,
                'known_estimated_usd': str(group['known_estimated_usd']),
                'unknown_reserved_usd': str(group['unknown_reserved_usd']),
                'usage_by_provider_field': dict(group['usage_by_provider_field']),
                'usage_sources': dict(group['usage_sources']), 'call_statuses': dict(group['call_statuses'])})
        rows.append({'run': run.name, 'status': result.get('status', 'unfinished'),
                     'calls': calls, 'call_statuses': dict(statuses),
                     'known_estimated_usd': str(sum(costs.values(), Decimal('0'))),
                     'unknown_reserved_usd': str(unknown),
                     'unmatched_started_calls': pending,
                     'unmatched_started_reserved_usd': str(pending_reserved),
                     'receipt_upper_bound_usd': str(sum(costs.values(), Decimal('0')) + unknown + pending_reserved),
                     'by_stage_usd': {key: str(value) for key, value in costs.items()},
                     'usage_by_provider_field': dict(usage),
                     'by_provider_model_stage_cost_basis': grouped,
                     'request_timing': request_timing(timed_calls, len(pending)),
                     'actual_billed_usd': None})
    return {'schema_version': 'e1-receipt-summary-v2',
            'basis': 'All completed call receipts including failed requests, plus unmatched start reservations. Receipt upper bound is not actual billing; reconcile it with the shared ledger.',
            'usage_basis': 'Counters preserve provider field paths and may overlap: cache reads are included in chat prompt_tokens, reasoning in completion_tokens. Never add these fields into a token total. Legacy run-level fields aggregate names across providers; use provider/model/stage/cost_basis groups for comparisons.',
            'cost_basis': 'Estimated costs copied unchanged from each receipt, not recalculated. Different cost_basis values can include different cache discount assumptions and are not identical billing measures.',
            'timing_basis': 'Includes successful and failed end receipts. Cumulative request seconds sums elapsed_seconds (overlap is counted); request window spans the first started_at to the last ended_at (gaps are counted). Neither is complete end-to-end task time. Missing/invalid measurements or unmatched starts leave the corresponding full-run statistic null; known cumulative seconds is only the measured subtotal. No filesystem times, time-to-first-token or inferred zero values are used.',
            'runs': rows,
            'known_estimated_usd': str(sum((Decimal(r['known_estimated_usd']) for r in rows), Decimal('0'))),
            'unknown_reserved_usd': str(sum((Decimal(r['unknown_reserved_usd']) for r in rows), Decimal('0'))),
            'unmatched_started_reserved_usd': str(sum((Decimal(r['unmatched_started_reserved_usd']) for r in rows), Decimal('0'))),
            'receipt_upper_bound_usd': str(sum((Decimal(r['receipt_upper_bound_usd']) for r in rows), Decimal('0'))),
            'actual_billed_usd': None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.runs), ensure_ascii=False, indent=2))
