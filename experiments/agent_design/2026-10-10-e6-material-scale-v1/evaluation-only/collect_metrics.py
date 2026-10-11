"""Collect actual E6 artifacts; does not score semantic correctness or call models."""
from collections import Counter
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/e6-material-scale-20261010-r1'


def read(path):
    return json.loads(path.read_bytes())


def collect(tier_id):
    run = OUTPUT / tier_id / 'run-r1'
    records = [read(p) for p in run.rglob('*-end.json')]
    if len({r['call_id'] for r in records}) != len(records):
        raise ValueError('duplicate cost records')
    starts = [read(p) for p in run.rglob('*-start.json')]
    if {r['call_id'] for r in starts} != {r['call_id'] for r in records}:
        raise ValueError('incomplete API calls; costs cannot be finalized')
    totals = Counter()
    unknown_fields = set()
    cost = Decimal(0)
    for record in records:
        cost += Decimal(record['estimated_usd'] or '0')
        usage = record.get('usage') or {}
        fields = {'input_tokens': usage.get('input_tokens'),
                  'output_tokens': usage.get('output_tokens'),
                  'cached_input_tokens': (usage.get('input_tokens_details') or {}).get('cached_tokens'),
                  'reasoning_tokens': (usage.get('output_tokens_details') or {}).get('reasoning_tokens')}
        for key, value in fields.items():
            if value is None:
                unknown_fields.add(key)
            else:
                totals[key] += value
    result = read(run / 'result.json')
    attempts = []
    for attempt in result.get('attempts', []):
        query = run / attempt['path'] / 'data-query/query'
        outcome = read(query / 'result.json') if (query / 'result.json').exists() else {}
        selections = outcome.get('delivery_selection', {})
        selected = {(s['context_id'], s['block_id']) for entries in selections.values() for s in entries}
        actions = Counter(t.get('action') for t in outcome.get('trace', []))
        review_summaries = []
        for r in attempt.get('reviews', []):
            review = Path(r['review_ref']['path'])
            inp, rv = read(review / 'input.json'), read(review / 'result.json')
            docs = inp.get('source_documents', [])
            blocks = [b for d in docs for b in d.get('blocks', [])]
            review_summaries.append({'status': rv['status'], 'analysis_eligible': rv['analysis_eligible'],
                'selected_fact_count': len(inp.get('facts', [])),
                'selected_numeric_records': sum(f.get('kind') == 'record' for f in inp.get('facts', [])),
                'selected_source_block_checks': sum(f.get('kind') == 'source_block' for f in inp.get('facts', [])),
                'selected_blocks': len(blocks),
                'selected_tables': sum(b.get('type') == 'table' for b in blocks),
                'selected_navigation_tables': sum(b.get('type') == 'table' and
                    b.get('layout_role') in {'running_header', 'table_of_contents', 'repeated_navigation'}
                    for b in blocks),
                'selected_source_ids': [d.get('source_snapshot_id') for d in docs],
                'question_protocol_repair_attempted': rv.get('question_protocol_repair_attempted',
                    (review / 'question-repair-input.json').exists()),
                'failures': rv.get('failures', []), 'review_ref': r['review_ref']})
        attempts.append({'attempt': attempt['attempt'], 'status': attempt['status'],
            'execution': attempt.get('execution'), 'steps': outcome.get('decision_budget', {}).get('used'),
            'actions': dict(actions), 'selected_body_blocks': len(selected),
            'sum_planner_packet_bytes': sum(t.get('packet_bytes', 0) for t in outcome.get('trace', [])),
            'retrieved_evidence_bytes': outcome.get('evidence_budget', {}).get('used_bytes'),
            'pending_body_reads': outcome.get('pending_body_reads'), 'reviews': review_summaries})
    stages = {}
    for stage in {r['stage'] for r in records}:
        rs = [r for r in records if r['stage'] == stage]
        stages[stage] = {'calls': len(rs), 'estimated_usd': str(sum((Decimal(r['estimated_usd'] or '0') for r in rs), Decimal(0)))}
    return {'tier_id': tier_id, 'runtime_status': result['status'], 'calls': len(records),
        'known_estimated_usd': str(cost), 'unknown_cost_requests': sum(r['estimated_usd'] is None for r in records),
        'actual_billed_usd': None, 'cost_basis': 'frozen uncached peak list-price estimate, not supplier bill',
        'reported_tokens': dict(totals), 'partially_or_fully_missing_token_fields': sorted(unknown_fields),
        'api_span_seconds': (max(datetime.fromisoformat(r['ended_at']) for r in records) -
                             min(datetime.fromisoformat(r['started_at']) for r in records)).total_seconds(),
        'api_elapsed_sum_seconds': sum(r['elapsed_seconds'] for r in records),
        'call_statuses': dict(Counter(r['status'] for r in records)), 'by_stage': stages,
        'attempts': attempts, 'failures': result.get('failures', []),
        'final_review_ref': result.get('final_review_ref'), 'independent_content_acceptance': 'separate'}


if __name__ == '__main__':
    import sys
    print(json.dumps([collect(t) for t in sys.argv[1:] or ('S1', 'S2', 'S3')], ensure_ascii=False, indent=2))
