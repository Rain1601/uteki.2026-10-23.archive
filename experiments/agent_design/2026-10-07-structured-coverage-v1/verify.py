"""Retrospective coverage audit of frozen real extraction results; no model call."""
from copy import deepcopy
import json
from pathlib import Path
from collections import Counter

from uteki.domain.research_data.query_contract import ResearchRecord
from uteki.infrastructure.research_data.direct_normalization import evaluate_required_facts
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / 'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1'
CASES = {
    'amd': ('amd-fy2023-cash-flow-main-agent-v2/query/turn-003/financial_extract/extraction-01',
            'sec-0000002488', 'USD'),
    'tsmc': ('tsmc-fy2023-operating-cash-flow-batch-v2/extraction-01', 'sec-0001046179', 'TWD'),
}
COMPLETED = {
    'amd': ['amd-fy2023-cash-flow-batch-v3/extraction-01'],
    'tsmc': ['tsmc-fy2023-operating-cash-flow-batch-v2/extraction-01',
             'tsmc-fy2023-investing-cash-flow-batch-v2/extraction-01'],
}


def verified_rows(folder, selected):
    """Inspect existing successful runs without generating or modifying their records."""
    packet = json.loads((folder / 'packet.json').read_text())
    normalized = json.loads((folder / 'normalized.json').read_text())
    receipt = json.loads((folder / 'result.json').read_text())
    assert receipt['plan_origin'] == 'model' and receipt['status'] == 'candidate'
    for field in ('company_id', 'source_snapshot_id', 'source_sha256'):
        assert packet['source'][field] == selected['source'][field]
    periods = {p['period_id']: p['period'] for p in packet['period_catalog']}
    for requirement in selected['required_facts']:
        assert packet['metric_catalog'][requirement['metric_id']]['unit'] == requirement['unit']
        expected = next(p['period'] for p in selected['period_catalog'] if p['period_id'] == requirement['period_id'])
        assert periods[requirement['period_id']] == expected
    blocks = {b['block_id']: b for b in packet['blocks']}
    rows = [ResearchRecord.model_validate(r).model_dump(mode='json') for r in normalized['records']]
    assert not normalized['unresolved']
    for row in rows:
        assert row['source_snapshot_id'] == selected['source']['source_snapshot_id']
        for eid in (*row['evidence_ids'], *row['qualifier_evidence_ids']):
            ref = normalized['evidence'][eid]
            block = blocks[ref['block_id']]
            assert digest(block['text'].encode()) == block['text_hash'] == ref['text_hash']
            assert block['text'][ref['source_start']:ref['source_end']] == ref['quote']
            assert ref['source_sha256'] == packet['source']['source_sha256']
    # The historical SQL projection must contain the same candidates, not an
    # unrelated new JSON-only report. Read DuckDB in read-only mode.
    import duckdb
    connection = duckdb.connect(str(folder / 'dataset/research.duckdb'), read_only=True)
    try:
        saved = dict(connection.execute('SELECT record_id, value_decimal FROM observations').fetchall())
        from decimal import Decimal
        assert saved == {r['record_id']: Decimal(r['value_decimal']) for r in rows}
    finally:
        connection.close()
    return rows, normalized['raw_candidates'], normalized['validation']['model_gaps'], {
        'folder': str(folder.relative_to(ROOT)), 'record_count': len(rows),
        'plan_origin': receipt['plan_origin'], 'evidence_offsets_checked': True, 'sql_values_checked': True,
        'files': {p: digest((folder / p).read_bytes()) for p in ('packet.json', 'normalized.json', 'result.json')},
    }


def main():
    reports = []
    for name, (relative, company, unit) in CASES.items():
        folder = BASE / relative
        packet = json.loads((folder / 'packet.json').read_text())
        normalized = json.loads((folder / 'normalized.json').read_text())
        assert packet['company_id'] == company
        requirements = [{'requirement_id': f'{metric}-{period}', 'entity_id': company,
            'metric_id': metric, 'period_id': period, 'unit': unit,
            'accounting_basis': 'reported_consolidated', 'value_kind': 'actual'}
            for metric in ('operating_cash_flow', 'capex_cash_payments')
            for period in ('fy2021', 'fy2022', 'fy2023')]
        selected = deepcopy(packet)
        selected['required_facts'] = requirements
        rows = [ResearchRecord.model_validate(r).model_dump(mode='json') for r in normalized['records']]
        coverage = evaluate_required_facts(selected, rows, normalized['raw_candidates'],
            normalized['unresolved'], normalized['validation']['model_gaps'])
        counts = dict(Counter(i['status'] for i in coverage['requirements']))
        assert counts == {'candidate_present': 3, 'unresolved' if name == 'amd' else 'not_extracted': 3}
        report = {'company': name, 'kind': 'retrospective_frozen_output_coverage_check',
            'model_calls': 0, 'independent_model_run': False,
            'input': {'folder': str(folder.relative_to(ROOT)),
                      'files': {p: digest((folder / p).read_bytes()) for p in ('packet.json', 'normalized.json', 'extraction.json')}},
            'requirement_selection': 'Review-selected OCF and PPE cash payments for FY2021–FY2023; no expected values supplied.',
            'requirement_sha256': digest(requirements), 'counts': counts,
            'coverage': coverage, 'implementation_sha256': digest(
                (ROOT / 'src/uteki/infrastructure/research_data/direct_normalization.py').read_bytes())}
        (OUT / f'{name}-coverage.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        completed_rows, completed_raw, completed_gaps, receipts = [], [], [], []
        for relative in COMPLETED[name]:
            rows, raw_candidates, model_gaps, receipt = verified_rows(BASE / relative, selected)
            completed_rows.extend(rows); completed_raw.extend(raw_candidates)
            completed_gaps.extend(model_gaps); receipts.append(receipt)
        completed_coverage = evaluate_required_facts(selected, completed_rows, completed_raw, [], completed_gaps)
        completed_counts = dict(Counter(i['status'] for i in completed_coverage['requirements']))
        assert completed_counts == {'candidate_present': 6}
        (OUT / f'{name}-completed-coverage.json').write_text(json.dumps({
            'kind': 'retrospective_multi_batch_candidate_coverage', 'model_calls': 0,
            'new_extraction': False, 'inputs': receipts, 'coverage': completed_coverage,
            'counts': completed_counts,
            'boundary': 'All six selected fact cells have real historical candidates. Original batch gaps remain; this does not establish whole-filing completeness or a general automatic merge.'},
            ensure_ascii=False, indent=2) + '\n')
        reports.append({'company': name, 'counts': counts, 'status': coverage['status'],
                        'model_gap_count': len(coverage['model_gaps']),
                        'existing_completed_batches': completed_counts,
                        'exact_evidence_and_sql_projection': 'checked'})
    (OUT / 'verification.json').write_text(json.dumps({'model_calls': 0,
        'semantic_acceptance': 'not_evaluated', 'todo07': 'partial', 'cases': reports}, indent=2) + '\n')
    print(json.dumps(reports, ensure_ascii=False))


if __name__ == '__main__':
    main()
