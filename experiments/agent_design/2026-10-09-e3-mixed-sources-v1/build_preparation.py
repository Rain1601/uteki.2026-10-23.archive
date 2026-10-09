"""Explicit E3 fixture composition, not a new production acquisition capability.

No semantic selections, expected answers, networking, model calls or ledgers.
Original acquisitions stay immutable; only verified bytes are copied to this run.
"""
import argparse
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlparse

from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained, save


def build(config_path, *, repository, output):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('new immutable output required')
    raw_config = Path(config_path).read_bytes()
    config = json.loads(raw_config)
    if config['schema_version'] != 'e3-explicit-frozen-sources-v1':
        raise ValueError('unsupported experiment input')
    company_id, cik = config['company_id'], config['cik']
    if company_id != 'sec-' + cik or len(cik) != 10 or not cik.isdigit():
        raise ValueError('explicit matching company and CIK required')
    cutoff = date.fromisoformat(config['knowledge_cutoff'])
    if config['source_policy_id'] != 'local-frozen-v1' or not config['acquisitions']:
        raise ValueError('explicit supported policy and acquisitions required')
    policy = config['source_policy']
    if not isinstance(policy, dict) or any(not isinstance(policy.get(k), list) for k in ('official', 'third_party')):
        raise ValueError('explicit source policy required')
    documents, originals, provenance, gaps = [], {}, [], []
    company = None
    for selection in config['acquisitions']:
        manifest_path = contained(repository, selection['manifest'])
        raw_manifest = manifest_path.read_bytes()
        if digest(raw_manifest) != selection['manifest_sha256']:
            raise ValueError('original acquisition manifest hash mismatch')
        acquired = json.loads(raw_manifest)
        if (acquired['schema_version'] != 'company-source-run-v1'
                or acquired['status'] not in {'completed', 'completed_with_gaps'}
                or acquired['company']['company_id'] != company_id or acquired['company']['cik'] != cik):
            raise ValueError('acquisition identity/status mismatch')
        if acquired['scope']['source_policy'] != policy:
            raise ValueError('acquisition source policy mismatch')
        company = acquired['company'] if company is None else company
        by_id = {d['source_id']: d for d in acquired['documents']}
        if len(by_id) != len(acquired['documents']) or not selection['sources']:
            raise ValueError('nonempty unique original sources required')
        selected_ids = []
        for expected in selection['sources']:
            sid = expected['source_id']
            if sid in originals:
                raise ValueError('duplicate selected source; no silent de-duplication')
            doc = deepcopy(by_id[sid])
            if (doc['role'] != 'filing' or doc['form'] != expected['form']
                    or doc['period_end'] != expected['period_end']
                    or doc['status'] not in {'downloaded', 'frozen'} or doc['as_of_eligible'] is not True
                    or doc.get('company_id', company_id) != company_id):
                raise ValueError('selected filing metadata/scope mismatch')
            if date.fromisoformat(doc['filed_at']) > cutoff:
                raise ValueError('selected source unavailable at experiment cutoff')
            url = urlparse(doc['source_url'])
            if url.scheme != 'https' or url.hostname != 'www.sec.gov' or not url.path.startswith('/Archives/edgar/'):
                raise ValueError('this fixture supports explicitly selected official SEC filings only')
            workspace = contained(repository, selection['workspace'])
            original = contained(workspace, doc['path'])
            raw = original.read_bytes()
            sha = doc['content_sha256']
            if digest(raw) != sha or doc.get('sha256', sha) != sha:
                raise ValueError('original source hash mismatch')
            verified = validate_sec_filing(raw, cik, doc['form'], doc['period_end'])
            receipt = doc['validation']
            if (receipt.get('status') != 'identity_validated'
                    or any(receipt.get(k) != verified[k] for k in ('cik', 'form', 'period_end', 'content_sha256'))):
                raise ValueError('original identity receipt mismatch')
            originals[sid] = {'path': original, 'raw': raw}
            doc['path'] = 'sources/objects/' + sha + '.bin'
            documents.append(doc)
            selected_ids.append(sid)
        gaps.extend(deepcopy(g) for g in acquired['gaps']
                    if not (g.get('source_id') or g.get('source_snapshot_id'))
                    or (g.get('source_id') or g.get('source_snapshot_id')) in selected_ids)
        provenance.append({'manifest': selection['manifest'], 'manifest_sha256': digest(raw_manifest),
                           'origin_run_id': acquired['run_id'], 'origin_cutoff': acquired['scope']['as_of'],
                           'selected_source_ids': selected_ids})
    source = {'schema_version': 'company-source-run-v1', 'run_id': 'e3-fixture-' + digest(raw_config)[:24],
              'company': company, 'scope': {'as_of': cutoff.isoformat(), 'selection': 'explicit_frozen_sources',
                  'source_ids': [d['source_id'] for d in documents], 'source_policy': policy, 'automatic_adoption': False},
              'documents': documents, 'gaps': gaps, 'model_calls': 0, 'requests': 0,
              'composition': {'schema_version': 'e3-source-composition-v1', 'origins': provenance,
                              'input_sha256': digest(raw_config)},
              'status': 'completed_with_gaps' if gaps else 'completed'}
    output.mkdir(parents=True)
    (output / 'input.json').write_bytes(raw_config)
    save(output / 'source-run.json', source)
    workspace = output / 'source-store'
    for doc in documents:
        target = workspace / doc['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(originals[doc['source_id']]['raw'])
    manifest = materialize_sources(source, workspace, output / 'dataset')
    if manifest['source_count'] != len(documents):
        raise ValueError('selected source failed indexing; preserve output and inspect gaps')
    # Detect any original acquisition/blob changes over the entire preparation.
    for selection in config['acquisitions']:
        if digest(contained(repository, selection['manifest']).read_bytes()) != selection['manifest_sha256']:
            raise ValueError('original acquisition changed during preparation')
    for sid, original in originals.items():
        expected = next(d['content_sha256'] for d in documents if d['source_id'] == sid)
        if digest(original['path'].read_bytes()) != expected:
            raise ValueError('original source changed during preparation')
    result = {'schema_version': 'e3-preparation-checkpoint-v1', 'status': 'prepared_with_gaps' if manifest['gaps'] else 'prepared',
              'dataset_manifest_sha256': digest((output / 'dataset/manifest.json').read_bytes()),
              'snapshot_id': manifest['snapshot_id'], 'source_count': manifest['source_count'],
              'record_count': manifest['record_count'], 'stage_coverage': manifest['stage_coverage'],
              'gap_count': len(manifest['gaps']), 'model_calls': 0, 'http_requests': 0,
              'semantic_completeness': 'not_evaluated', 'revision_version_coverage': 'not_evaluated',
              'originals_unchanged': True, 'implementation_sha256': digest(Path(__file__).read_bytes())}
    save(output / 'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.input, repository=args.repository, output=args.output), ensure_ascii=False))
