"""Explicit two-company acceptance run through the public CLI; no model calls.

The case scope and expected counts are evaluation assertions, never inputs to
source discovery or extraction. Use new output/store paths for another run.
"""
import json
from pathlib import Path
import subprocess
import sys

from uteki.agents.data_query.coordinator import inspect_run
from uteki.agents.reading.document_reader import DocumentReader

ROOT = Path(__file__).resolve().parents[3]
REPORT = Path(__file__).resolve().parent
STORE = ROOT / 'data/company_workspace/official-filings-e2e-v2'
PREPARED = ROOT / 'data/company_workspace/official-filing-preparations'
CATALOG = ROOT / 'config/company_sources/annual-pilot-catalog-v1.json'
# Explicit user-approved pilot. Expected values are used only after execution.
CASES = [('amd', 'AMD', 'sec-0000002488', 4), ('tsmc', '台积电', 'sec-0001046179', 3)]


def execute(action, slug, company):
    output = PREPARED / (slug + ('-v2' if action == 'prepare' else '-refresh-v2'))
    command = [sys.executable, '-m', 'uteki.infrastructure.research_data.query_cli', 'agent', action,
        '--company', company, '--company-catalog', str(CATALOG), '--workspace', str(STORE),
        '--output', str(output), '--settings-root', str(ROOT)]
    if action == 'refresh':
        command += ['--previous', str(PREPARED / (slug + '-v2'))]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (REPORT / (slug + '-' + action + '-v2.json')).write_text(completed.stdout)
    (REPORT / (slug + '-' + action + '-v2.stderr.txt')).write_text(completed.stderr)
    (REPORT / (slug + '-' + action + '-v2.command.json')).write_text(json.dumps(
        {'command': command, 'returncode': completed.returncode}, ensure_ascii=False, indent=2) + '\n')
    if completed.returncode:
        raise RuntimeError(f'{slug} {action} exited {completed.returncode}; inspect retained artifacts')
    inspected = inspect_run(output)
    assert inspected['status'] == 'verified'
    result = inspected['result']
    assert result['status'] in ('prepared', 'prepared_with_gaps') and result['model_calls'] == 0
    source_run = json.loads((output / 'acquisition.json').read_text())
    return output, result, source_run


def main():
    if STORE.exists():
        raise ValueError('fresh source store required for this acceptance run')
    summary = {'scope': 'registered company -> live SEC discovery/download -> parsing -> verified reuse',
               'model_calls': 0, 'cases': [], 'boundary': 'Parsing and byte integrity, not financial semantic acceptance'}
    for slug, company, company_id, count in CASES:
        output, result, source_run = execute('prepare', slug, company)
        assert source_run['status'] == 'completed' and len(source_run['documents']) == count
        assert all(d['status'] == 'downloaded' for d in source_run['selected_filings'])
        assert source_run['company']['company_id'] == company_id
        dataset = Path(result['dataset']['path'])
        sources = json.loads((dataset / 'sources.json').read_text())
        records = json.loads((dataset / 'records.json').read_text())['rows']
        evidence = json.loads((dataset / 'evidence.json').read_text())
        assert len(sources) == count and all(s['company_id'] == company_id for s in sources)
        used = {eid for r in records for key in ('evidence_ids', 'qualifier_evidence_ids', 'question_evidence_ids') for eid in r[key]}
        assert used == set(evidence), 'orphan or missing evidence'
        cases = []
        for source in sources:
            reader = DocumentReader(dataset / source['index_folder'])
            document = next(n for n in reader.outline()['nodes'] if n['kind'] == 'document')
            found = reader.search(document['node_id'], 'cash flows')
            if not source['form'].endswith('/A'):
                assert found['total'] > 0
            # An amendment need not repeat financial statements; read its own
            # document start when the literal is absent, without inventing a hit.
            block_id = found['hits'][0]['block_id'] if found['hits'] else document['start_block_id']
            read = reader.read(document['node_id'], block_id, count=3)
            assert read['blocks'] and all(b['block_id'] in reader.positions for b in read['blocks'])
            assert reader.index['parser_version'] == 'sec-source-blocks-v0.1.7'
            cases.append({'source_id': source['source_snapshot_id'], 'form': source['form'],
                'period_end': source['period_end'], 'source_url': source['source_url'],
                'stage_coverage': source['stage_coverage'], 'literal_cash_flows_hits': found['total'],
                'read_sample': {'block_id': block_id, 'selection': 'search_hit' if found['hits'] else 'amendment_document_start',
                                'returned_block_count': len(read['blocks'])}})
        _, repeat, refreshed = execute('refresh', slug, company)
        assert refreshed['status'] == 'completed' and refreshed['requests'] == 1
        assert all(d['status'] == 'reused_verified' for d in refreshed['selected_filings'])
        assert repeat['materialization'] == 'reused' and repeat['dataset'] == result['dataset']
        assert repeat['gaps'] == result['gaps'] and repeat['stage_coverage'] == result['stage_coverage']
        row = {'company': company, 'company_id': company_id, 'run': str(output.relative_to(ROOT)),
            'dataset': result['dataset'], 'download_requests': source_run['requests'],
            'refresh_requests': refreshed['requests'], 'acquisition_status': source_run['status'],
            'preparation_status': result['status'], 'stage_coverage': result['stage_coverage'], 'sources': cases}
        summary['cases'].append(row)
        (REPORT / 'verification-v2.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'company': company, 'source_count': count, 'acquisition': source_run['status'],
            'preparation': result['status'], 'stage_coverage': result['stage_coverage'],
            'refresh': repeat['materialization']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
