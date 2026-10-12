"""Final persisted artifacts and exact consumer locators; no model calls."""
import json
from pathlib import Path
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.document_sources.parsed_package import verify_parsed_package
from uteki.infrastructure.research_data.record_locator import resolve_record_locator
from uteki.infrastructure.research_data.financial_records import digest
BASE=Path('output/preparation-acceptance-20261012')
rows={}
for company in ('msft','googl'):
    dataset=BASE/'v5'/company/'dataset'
    other=BASE/'v6'/company/'dataset'
    manifest=_verify_manifest(dataset)
    _verify_manifest(other)
    source=json.loads((dataset/'sources.json').read_text())[0]
    package=dataset/source['index_folder']; replay=other/source['index_folder']
    checked=verify_parsed_package(package)
    files={str(p.relative_to(package)):digest(p.read_bytes()) for p in package.rglob('*') if p.is_file()}
    replay_files={str(p.relative_to(replay)):digest(p.read_bytes()) for p in replay.rglob('*') if p.is_file()}
    evidence=json.loads((dataset/'evidence.json').read_text())
    failures=[]
    for eid,item in evidence.items():
        try:resolve_record_locator(dataset,item)
        except Exception as e:failures.append({'evidence_id':eid,'error':type(e).__name__+': '+str(e)})
    rows[company]={'package_verification':checked,'canonical_replay_equal':files==replay_files,
      'file_count':len(files),'record_locators_checked':len(evidence),'locator_errors':failures,
      'dataset_sha256':digest((dataset/'manifest.json').read_bytes()),
      'unchanged_after_read':manifest==_verify_manifest(dataset)}
    print(company,rows[company],flush=True)
(BASE/'evaluation-only/delivery-verification.v1.json').write_text(json.dumps(rows,indent=2)+'\n')
assert all(r['canonical_replay_equal'] and not r['locator_errors'] and r['unchanged_after_read'] for r in rows.values())
