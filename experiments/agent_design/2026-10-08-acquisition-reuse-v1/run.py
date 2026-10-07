"""Explicit, offline reuse of frozen originals through existing system entry points.

This does not impersonate an online acquisition or synthesize its receipts.
Run once: immutable per-company outputs are deliberately not overwritten.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.infrastructure.document_sources.company_registry import resolve_company_profile
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact
from uteki.infrastructure.research_data.company_materialization import materialize_sources

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def selected(doc, profile):
    selection = profile['filing_selection']
    if doc['form'] not in (selection['annual_form'], selection['annual_form'] + '/A'):
        return False
    period = doc['period_end']
    if selection['mode'] == 'annual_filing_period':
        return period == selection['report_period_end']
    return selection['report_period_end_from'] <= period <= selection['report_period_end_to']


def main():
    inputs = json.loads((HERE / 'inputs.json').read_text())
    catalog = ROOT / inputs['catalog']
    assert sha(catalog) == inputs['catalog_sha256']
    contact, origin = resolve_sec_contact(settings_root=ROOT)
    # Do not persist or print a contact value. Offline replay needs no contact.
    write(HERE / 'live-preflight.json', {
        'sec_contact_configured': bool(contact), 'sec_contact_origin': origin,
        'status': 'available_not_invoked_by_offline_runner' if contact else 'blocked_missing_sec_contact',
        'network_requests': 0,
        'required_setting': 'UTEKI_SEC_USER_AGENT',
        'settings_file': '.env',
    })
    results = []
    for case in inputs['cases']:
        symbol = case['symbol']
        profile = resolve_company_profile(catalog, symbol)
        path, workspace = ROOT / case['manifest'], ROOT / case['workspace']
        assert sha(path) == case['manifest_sha256']
        prior = json.loads(path.read_text())
        assert prior['company']['cik'] == profile['cik']
        by_id = {doc['source_id']: doc for doc in prior['documents']}
        docs = [by_id[sid] for sid in case['source_ids']]
        assert all(selected(doc, profile) for doc in docs)
        verified, old_hashes = [], {path: sha(path)}
        for doc in docs:
            original = workspace / doc['path']
            assert sha(original) == doc['content_sha256']
            old_hashes[original] = sha(original)
            identity = validate_sec_filing(original.read_bytes(), profile['cik'], doc['form'], doc['period_end'])
            verified.append({'source_id': doc['source_id'], 'identity': identity,
                             'original_path': str(original.relative_to(ROOT)),
                             'source_url': doc['source_url'], 'form': doc['form'], 'period_end': doc['period_end']})
        destination = HERE / symbol.lower()
        write(destination / 'selection.json', {
            'profile': profile, 'origin': case, 'verified_originals': verified,
            'scope': 'Explicit selected annuals only; no new discovery or availability claim.'})
        if prior['schema_version'] == 'company-source-run-v1':
            result = CompanyDataCoordinator(workspace).prepare_acquisition(
                path, acquisition_sha256=case['manifest_sha256'],
                source_ids=case['source_ids'], output=destination / 'preparation')
            checked = inspect_run(destination / 'preparation')
            assert checked['status'] == 'verified'
            dataset = Path(result['dataset']['path'])
            mode = 'system_frozen_acquisition_replay'
        else:
            assert prior['schema_version'] == 'local-original-reuse-v1'
            # Preserve the original declared cutoff. Selection only removes the
            # quarter outside this annual-only profile, never changes raw data.
            source = deepcopy(prior)
            source['documents'] = deepcopy(docs)
            write(destination / 'selected-local-originals.json', source)
            dataset = destination / 'dataset'
            materialize_sources(source, workspace, dataset)
            mode = 'system_local_original_materialization'
        manifest = json.loads((dataset / 'manifest.json').read_text())
        for relative, expected in manifest['files'].items():
            assert sha(dataset / relative) == expected
        assert all(sha(p) == expected for p, expected in old_hashes.items())
        row = {'symbol': symbol, 'mode': mode, 'status': 'reused_and_frozen',
               'new_network_acquisition': False, 'identity_verified_count': len(verified),
               'source_count': manifest['source_count'],
               'dataset': str(dataset.relative_to(ROOT)),
               'manifest_sha256': sha(dataset / 'manifest.json'),
               'originals_unchanged': True, 'all_published_files_hash_verified': True,
               'stage_coverage': manifest['stage_coverage'],
               'downstream_gap_counts': dict(Counter(g['reason'] for g in manifest['gaps'])),
               'acquisition_discovery_coverage': 'not_refreshed'}
        results.append(row)
        write(destination / 'verification.json', row)
        print(json.dumps({'symbol': symbol, 'status': row['status'], 'sources': row['source_count']}, ensure_ascii=False), flush=True)
    for symbol in inputs['unavailable']:
        profile = resolve_company_profile(catalog, symbol)
        results.append({'symbol': symbol, 'status': 'missing_selected_original',
                        'profile': profile, 'reason': 'SEC HTML absent; official IR PDF is outside selected inline identity adapter',
                        'network_attempt': 'blocked_missing_sec_contact' if not contact else 'not_performed_by_offline_runner'})
    write(HERE / 'verification.json', {
        'schema_version': 'selected-annual-system-reuse-v1',
        'inputs_sha256': sha(HERE / 'inputs.json'), 'network_requests': 0, 'model_calls': 0,
        'results': results,
        'remaining': ['Online acquisition requires a configured SEC contact',
                      'NVIDIA selected SEC HTML unavailable',
                      'Quarterly filings, 6-K/8-K, releases and transcripts outside these selected profiles',
                      'Parsed identity/hash validation is separate from extraction semantic quality']})


if __name__ == '__main__':
    main()
