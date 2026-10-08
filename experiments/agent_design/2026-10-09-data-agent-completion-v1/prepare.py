"""Rebuild explicitly selected existing annuals through the system materializer."""
import json
from pathlib import Path
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.agents.data_query.coordinator import _verify_manifest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
rows=[]
for symbol in ('msft', 'googl'):
    selected=ROOT/f'experiments/agent_design/2026-10-08-acquisition-reuse-v1/{symbol}/selected-local-originals.json'
    source=json.loads(selected.read_text())
    workspace=ROOT/f'data/company_workspace/extraction_ab_v1/corpus/{symbol}'
    hashes={str(workspace/doc['path']):digest((workspace/doc['path']).read_bytes()) for doc in source['documents']}
    if any(hashes[str(workspace/doc['path'])] != doc['content_sha256'] for doc in source['documents']):
        raise ValueError('selected original differs from pinned acquisition')
    output=HERE/'datasets'/symbol
    materialize_sources(source, workspace, output)
    manifest=_verify_manifest(output)
    assert all(digest(Path(p).read_bytes())==h for p,h in hashes.items())
    rows.append({'symbol':symbol,'dataset':str(output.relative_to(ROOT)),
        'manifest_sha256':digest((output/'manifest.json').read_bytes()),
        'selected_acquisition':str(selected.relative_to(ROOT)), 'selected_acquisition_sha256':digest(selected.read_bytes()),
        'original_sha256':hashes,'originals_unchanged':True,'network_acquisition':False,
        'stage_coverage':manifest['stage_coverage']})
    print(json.dumps({'symbol':symbol,'status':'new_dataset_verified'},ensure_ascii=False),flush=True)
with (HERE/'preparation.json').open('x') as f: json.dump(rows,f,ensure_ascii=False,indent=2)
