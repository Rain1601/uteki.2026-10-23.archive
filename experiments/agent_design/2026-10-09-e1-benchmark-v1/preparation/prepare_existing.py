"""Prepare a frozen annual and check duplicate-source rejection without model calls."""
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parents[1]


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    selected = ROOT / 'experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/selected-local-originals.json'
    source = json.loads(selected.read_text())
    workspace = ROOT / 'data/company_workspace/extraction_ab_v1/corpus/msft'
    for document in source['documents']:
        raw = (workspace / document['path']).read_bytes()
        assert digest(raw) == document['content_sha256']
        validate_sec_filing(raw, source['company']['cik'], document['form'], document['period_end'])
    destination = HERE / 'datasets/msft-fy2025'
    materialize_sources(source, workspace, destination)
    manifest = _verify_manifest(destination)
    duplicate = deepcopy(source)
    duplicate['documents'].append(deepcopy(duplicate['documents'][0]))
    rejected_path = HERE / 'datasets/duplicate-input-must-not-publish'
    try:
        materialize_sources(duplicate, workspace, rejected_path)
    except ValueError as error:
        assert str(error) == 'missing or duplicate source identity'
        assert not rejected_path.exists()
    else:
        raise AssertionError('duplicate source must not publish a doubled dataset')
    write(HERE / 'preparation/existing-fy2025-verification.json', {
        'schema_version': 'e1-existing-original-preparation-v1',
        'operation': 'system_materializer_local_original_reuse',
        'network_requests': 0, 'model_calls': 0,
        'selected_acquisition': str(selected.relative_to(ROOT)),
        'selected_acquisition_sha256': digest(selected.read_bytes()),
        'dataset': str(destination.relative_to(ROOT)),
        'manifest_sha256': digest((destination/'manifest.json').read_bytes()),
        'snapshot_id': manifest['snapshot_id'],
        'source_count': manifest['source_count'],
        'stage_coverage': manifest['stage_coverage'],
        'duplicate_source_identity_check': 'rejected_before_publish',
        'cross_report_deduplication': 'not_tested_missing_fy2024_original',
        'acquisition_discovery_coverage': 'historical_frozen_source_not_refreshed',
        'scope': 'FY2025 10-K only; comparison-year facts are not separate FY2024 materials',
    })
    print(json.dumps({'status': 'existing_fy2025_prepared', 'dataset': str(destination.relative_to(ROOT))}))


if __name__ == '__main__':
    main()
