"""Review-only comparison with a held-out source audit; never an extraction input.

The label correspondence below belongs to this explicit annual-core evaluation.
This compares selected source facts, not complete financial semantics or recall.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

LABELS = {
    'revenue': 'revenue', 'operating_income': 'operating_income',
    'net_income': 'net_income', 'operating_cash_flow': 'operating_cash_flow',
    'capex_cash_payments': 'capex_cash_payments',
    'cash_and_equivalents': 'cash_and_cash_equivalents',
    'short_term_debt': 'current_portion_long_term_debt_net',
    'long_term_debt': 'long_term_debt_net_of_current_portion',
    'share_capital': 'common_stock_carrying_value',
    'shares_outstanding': 'common_shares_outstanding',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def numeric(value):
    value = value.replace(',', '').strip()
    return Decimal('-' + value[1:-1] if value.startswith('(') else value)


def review(folder, run_id, gold_path):
    packet, extraction, normalized = [read(folder / name) for name in
        ('packet.json', 'extraction.json', 'normalized.json')]
    gold = read(gold_path)
    manifest = read(folder / 'manifest.json')
    for name in ('packet.json', 'extraction.json', 'normalized.json'):
        if manifest['files'][name] != sha(folder / name):
            raise ValueError('Frozen run changed: ' + name)
    source = packet['source']
    if source['source_sha256'] != gold['source']['source_sha256'] or source['source_snapshot_id'] != gold['source']['source_snapshot_id']:
        raise ValueError('Held-out comparison belongs to another source')
    if source['company_id'] != packet['company_id']:
        raise ValueError('Company/source mismatch')
    raw = folder / 'dataset' / source['raw_file']
    if sha(raw) != source['source_sha256']:
        raise ValueError('Raw source mismatch')
    periods = {x['period_id']: x['period'] for x in packet['period_catalog']}
    blocks = {x['block_id']: x for x in packet['blocks']}
    records = {x['origin']['draft_id']: x for x in normalized['records']}
    facts, covered = [], set()
    for draft in extraction['records']:
        period = periods.get(draft['period_id'])
        peers = [x for x in gold['reviewed_facts'] if x['metric'] == LABELS.get(draft['metric_id'])
                 and period and x['period']['end'] == period['end']
                 and x['period'].get('start') == period.get('start')
                 and (x['period']['type'] == 'instant') == (period['kind'] == 'instant')]
        row = {'draft_id': draft['draft_id'], 'verdict': 'not_reviewed',
               'rationale': 'Outside this held-out set, or no exact period mapping; independent source review is still required.',
               'engineering_issues': [x['reason'] for x in normalized['unresolved'] if x['draft_id'] == draft['draft_id']]}
        if draft['draft_id'] in records:
            row['record_id'] = records[draft['draft_id']]['record_id']
        if len(peers) == 1:
            peer = peers[0]
            covered.add(peer['review_fact_id'])
            row['held_out_fact_id'] = peer['review_fact_id']
            expected = Decimal(str(peer.get('signed_display_value_in_millions', peer['value_in_millions'])))
            unit = 'shares_millions' if peer['normalized_unit'] == 'shares' else 'USD_millions'
            try:
                matches = numeric(draft['value']) == expected and draft['unit'] == unit
            except (TypeError, ValueError, ArithmeticError, AttributeError):
                matches = False
            evidence = draft['evidence'] + draft['qualifiers']
            same_table = any(x['block_id'] == peer['evidence']['block_id'] for x in evidence)
            exact_quotes = all(x['block_id'] in blocks and x['quote'] and
                               x['quote'] in blocks[x['block_id']]['text'] for x in evidence)
            row.update(value_matches=matches, same_statement_table=same_table, exact_quotes=exact_quotes,
                       source_block_id=peer['evidence']['block_id'], actual_period=period,
                       reviewer_scope='Selected amount, unit, source table and exact period; does not approve the full mapping or completeness.')
            if matches and same_table and exact_quotes:
                row['verdict'] = 'value_scope_matched'
                row['rationale'] = ('Amount, statement sign, unit and exact period match the independent source audit. '
                    'Mapping/protocol issues remain separate; candidate is not adopted.')
            else:
                row['verdict'] = 'needs_review'
                row['rationale'] = 'Value, unit, same-table evidence or exact quote did not match this held-out comparison.'
            if peer['source_display'] == '—':
                row['verdict'] = 'needs_evidence'
                row['rationale'] = ('The source audit establishes zero through inline XBRL fixed-zero metadata, '
                    'but the supplied text evidence is a dash. The draft must not treat a dash as zero without that support.')
        facts.append(row)
    core = {x['review_fact_id'] for x in gold['reviewed_facts'] if x['metric'] in LABELS.values()}
    supplied = {x['review_fact_id'] for x in gold['reviewed_facts'] if x['review_fact_id'] in core
                and x['evidence']['block_id'] in blocks}
    return {'schema_version': 'canary-held-out-review-v1', 'run_id': run_id,
        'company_id': packet['company_id'], 'source_snapshot_id': source['source_snapshot_id'],
        'source_sha256': source['source_sha256'], 'reviewer': 'Codex source review with held-out comparison',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'inputs': {'run_manifest_sha256': sha(folder/'manifest.json'),
                   'packet_sha256': sha(folder/'packet.json'), 'extraction_sha256': sha(folder/'extraction.json'),
                   'held_out_path': str(gold_path), 'held_out_sha256': sha(gold_path),
                   'comparison_script_sha256': sha(Path(__file__))},
        'summary': {'raw_drafts': len(facts), 'database_records': len(records),
                    'verdict_counts': dict(Counter(x['verdict'] for x in facts)),
                    'held_out_core_facts': len(core), 'matched_period_core_facts': len(core & covered),
                    'held_out_core_facts_in_packet': len(supplied),
                    'unmatched_supplied_core_fact_ids': sorted(supplied-covered),
                    'core_fact_ids_outside_supplied_packet': sorted(core-supplied)},
        'facts': facts, 'adoption': 'unchanged_candidate', 'overall': 'partial',
        'limits': ['Selected core rows only; not full-report recall, debt-note acceptance, or investment research.',
                   'Equal amount is insufficient for semantic acceptance; source signs, scope, mapping and qualifications remain review dimensions.',
                   'Drafts outside the held-out set stay not_reviewed, not incorrect. Evidence presence is not a financial quality score.',
                   'This review and its held-out values must never be supplied to extraction or normalization as answers.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--gold', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = review(args.run, args.run_id, args.gold)
    with args.output.open('x') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
