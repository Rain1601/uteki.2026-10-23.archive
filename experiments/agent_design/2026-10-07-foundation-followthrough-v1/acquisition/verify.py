"""Validate five explicit acquisition profiles against selected frozen inventory.

No network: presence and verified identity are separate from a new acquisition run.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'src'))
from uteki.infrastructure.document_sources.company_registry import resolve_company_profile
from uteki.infrastructure.document_sources.company_acquisition import _configuration
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing

catalog = ROOT/'config/company_sources/annual-pilot-catalog-v2.json'
inventory = json.loads((ROOT/'experiments/agent_design/2026-10-07-foundation-parallel-v1/acquisition/inventory.json').read_text())
cases = []
for symbol in ('MSFT', 'GOOGL', 'NVDA', 'TSM', 'AMD'):
    config = resolve_company_profile(catalog, symbol)
    # Validate shape locally; this synthetic contact is never used for a request.
    _configuration({**config, 'sec_user_agent': 'Offline profile validation offline@example.invalid'})
    selected = config['filing_selection']
    inventory_entry = next(c for c in inventory['companies'] if c['symbol'] == symbol)
    documents = []
    for doc in inventory_entry['documents']:
        end = doc['period_end']
        if selected['mode'] == 'annual_filing_period' and end != selected['report_period_end']:
            continue
        if selected['mode'] == 'annual_filings_range' and not selected['report_period_end_from'] <= end <= selected['report_period_end_to']:
            continue
        if doc['form'] not in (selected['annual_form'], selected['annual_form']+'/A', 'annual-report-with-10-K'):
            continue
        original = doc['original']
        raw = (ROOT/original['path']).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        assert sha == original['sha256']
        result = {'path': original['path'], 'sha256': sha, 'period_end': end, 'form': doc['form']}
        if raw.startswith(b'%PDF'):
            result.update(identity_status='unsupported_by_selected_sec_inline_adapter',
                requirement_status='missing_verified_sec_html',
                existing_alternative='Official IR PDF retained; not silently substituted for the SEC HTML profile.')
        else:
            validation = validate_sec_filing(raw, expected_cik=config['cik'],
                expected_form=doc['form'], expected_period_end=end)
            result.update(identity_status=validation['status'], requirement_status='frozen_original_verified')
        documents.append(result)
    assert documents, 'selected pilot must have an inventory entry, including explicit gaps'
    cases.append({'symbol': symbol, 'company_id': 'sec-'+config['cik'],
        'profile': config, 'configuration_status': 'valid', 'documents': documents,
        'new_acquisition_run': False, 'complete_official_material_coverage': False})
try:
    resolve_company_profile(catalog, 'Unregistered Company')
except ValueError:
    unknown_rejected = True
else:
    raise AssertionError('unknown company must not fall back')
result = {'schema_version': 'five-company-profile-check-v1', 'catalog': str(catalog.relative_to(ROOT)),
    'catalog_sha256': hashlib.sha256(catalog.read_bytes()).hexdigest(), 'network_requests': 0,
    'model_calls': 0, 'unknown_company_rejected': unknown_rejected, 'cases': cases,
    'unverified_requirements': ['Unified acquisition execution/reuse receipts for all five profiles',
        'NVIDIA SEC HTML or separately verified PDF identity adapter',
        'Quarterly/6-K, earnings releases, attachments and official transcript coverage']}
(Path(__file__).parent/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({c['symbol']: {'configuration': c['configuration_status'],
    'documents': len(c['documents']), 'identity': [d['identity_status'] for d in c['documents']]} for c in cases}, indent=2))
