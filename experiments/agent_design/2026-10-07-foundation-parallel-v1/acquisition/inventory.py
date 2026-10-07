"""Read-only audit of explicitly selected existing pilot materials; no downloads."""
import hashlib
import json
from pathlib import Path

from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).parent


def check(path, expected=None):
    path = ROOT / path
    result = {'path': str(path.relative_to(ROOT)), 'exists': path.is_file()}
    if path.is_file():
        raw = path.read_bytes()
        result.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if expected:
            result['expected_sha256'] = expected
            result['hash_matches'] = result['sha256'] == expected
    return result


companies = []
for symbol, folder in [
    ('MSFT', 'data/company_workspace/extraction_ab_v1/corpus/msft/dataset'),
    ('GOOGL', 'data/company_workspace/extraction_ab_v1/corpus/googl/dataset'),
    ('AMD', 'data/company_workspace/official-filing-preparations/amd-v2/dataset'),
    ('TSM', 'data/company_workspace/official-filing-preparations/tsmc-v2/dataset'),
]:
    folder = Path(folder)
    manifest = json.loads((ROOT/folder/'manifest.json').read_text())
    documents = []
    for source in json.loads((ROOT/folder/'sources.json').read_text()):
        original = check(folder/source['raw_file'], source['raw_file_sha256'])
        item = {k: source[k] for k in ('company_id', 'source_url', 'form', 'period_end', 'source_snapshot_id')}
        item.update(original=original, index_manifest=check(folder/source['index_folder']/'manifest.json'),
                    blocks=check(folder/source['index_folder']/'blocks.jsonl'))
        try:
            identity = validate_sec_filing((ROOT/original['path']).read_bytes(),
                expected_cik=source['company_id'].removeprefix('sec-'),
                expected_form=source['form'], expected_period_end=source['period_end'])
            item['identity_validation'] = {'status': identity['status'], 'version': identity['validation_version']}
        except ValueError as error:
            item['identity_validation'] = {'status': 'not_validated', 'reason': str(error)}
        documents.append(item)
    companies.append({'symbol': symbol, 'dataset_manifest': check(folder/'manifest.json'),
                      'sources_manifest': check(folder/'sources.json'), 'documents': documents})

receipt_path = Path('experiments/agent_design/2026-10-07-business-map-mermaid-v1/nvidia/source_acquisition.json')
receipt = json.loads((ROOT/receipt_path).read_text())
companies.append({'symbol': 'NVDA', 'acquisition_receipt': check(receipt_path),
    'documents': [{'source_url': receipt['source_url'], 'discovery_source_url': receipt['discovery_source_url'],
        'form': 'annual-report-with-10-K', 'period_end': receipt['report_period_end'],
        'original': check(receipt['original_source_path'], receipt['original_source_sha256']),
        'derived_html': check(receipt['derived_html_path'], receipt['derived_html_sha256']),
        'identity_validation': {'status': 'unsupported_pdf_by_sec_inline_validator'},
        'company_acquisition_manifest': None, 'index_manifest': None,
        'scope_note': 'Official IR-linked PDF and derived HTML receipt; no claim of SEC inline identity verification.'}]})

acquisition_runs = []
for path in sorted((ROOT/'data/company_workspace/official-filings-e2e-v2/source-runs').glob('*/manifest.json')):
    report = json.loads(path.read_text())
    acquisition_runs.append({'manifest': check(path), 'symbol': report['company']['symbol'],
        'status': report['status'], 'selection': report['scope']['filing_selection'],
        'catalog_discovery_complete': report['filing_catalog']['discovery_complete'],
        'selection_discovery_complete': report['filing_catalog']['selection_discovery_complete'],
        'documents': [{'form': doc['form'], 'period_end': doc['period_end'],
            'source_url': doc['source_url'], 'original': check(path.parents[2]/doc['path'], doc['content_sha256'])}
            for doc in report['documents']]})

result = {'schema_version': 'foundation-acquisition-inventory-v1', 'checked_on': '2026-10-07',
    'mode': 'local_frozen_material_audit', 'network_requests': 0, 'model_calls': 0,
    'companies': companies, 'acquisition_runs': acquisition_runs,
    'coverage_warning': 'Selected annual materials are available. This is not complete official filing/release/transcript coverage.'}
(OUT/'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'companies': len(companies), 'documents': sum(len(c['documents']) for c in companies),
    'acquisition_runs': len(acquisition_runs), 'missing_or_mismatched_originals':
    [d['original']['path'] for c in companies for d in c['documents']
     if not d['original']['exists'] or not d['original'].get('hash_matches', True)]}))
