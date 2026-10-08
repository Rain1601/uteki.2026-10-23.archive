"""Materialize all system-selected original annuals; no semantic selection."""
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parents[1]


def main():
    workspace = HERE/'acquisition/workspace'
    manifest_path = workspace/'source-runs/20261008T205046-a663c12323dd/manifest.json'
    source = json.loads(manifest_path.read_text())
    assert source['status'] == 'completed' and not source['gaps']
    assert {d['period_end'] for d in source['documents']} == {'2024-06-30', '2025-06-30'}
    products = []
    groups = [('msft-two-annuals', source['documents'])]
    groups += [('msft-acquired-fy'+d['period_end'][:4], [d]) for d in source['documents']]
    for name, documents in groups:
        selected = deepcopy(source)
        selected['documents'] = documents
        output = HERE/'datasets'/name
        materialize_sources(selected, workspace, output)
        manifest = _verify_manifest(output)
        products.append({'name': name, 'dataset': str(output.relative_to(ROOT)),
            'snapshot_id': manifest['snapshot_id'],
            'manifest_sha256': digest((output/'manifest.json').read_bytes()),
            'source_count': manifest['source_count'], 'record_count': manifest['record_count'],
            'stage_coverage': manifest['stage_coverage'],
            'source_ids': [d['source_id'] for d in documents]})
    result = {'schema_version': 'e1-two-annual-preparation-v1', 'model_calls': 0,
        'network_acquisition': True, 'source_acquisition': str(manifest_path.relative_to(ROOT)),
        'source_acquisition_sha256': digest(manifest_path.read_bytes()),
        'originals': [{**{k: d[k] for k in ('source_id','source_url','content_sha256','period_end','filed_at','form','validation')},
                       'raw_path': str((workspace/d['path']).relative_to(ROOT))} for d in source['documents']],
        'datasets': products, 'semantic_chapter_selection': False,
        'limitations': ['Preparation and identity validation are not semantic completeness acceptance',
                       'Generalized multi-year deduplication and query behavior need independent benchmark review']}
    with (HERE/'preparation/acquired-datasets.json').open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({'status': 'prepared', 'datasets': [x['dataset'] for x in products]}))


if __name__ == '__main__':
    main()
