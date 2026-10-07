"""Check references against explicitly selected new packages without migration."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
checks = []
for case in json.loads((HERE / 'cases.json').read_bytes()):
    company = case['id'].split('-')[0]  # Named experiment case, not runtime selection.
    package = HERE.parent / '2026-10-07-parser-quality-v2' / company
    source = json.loads((package / 'source.json').read_bytes())
    manifest = json.loads((package / 'manifest.json').read_bytes())
    result = json.loads((HERE / case['id'] / 'result.json').read_bytes())
    blocks = {b['block_id']: b for b in map(json.loads, (package / 'blocks.jsonl').read_text().splitlines())}
    assert source['company_id'] == case['company_id']
    assert source['source_snapshot_id'] == case['source_id']
    evidence_checks = []
    for eid, ev in result['evidence'].items():
        assert source['raw_sha256'] == ev['source_sha256']
        block = blocks[ev['block_id']]
        assert block['text_hash'] == ev['text_hash']
        assert block['text'][ev['source_start']:ev['source_end']] == ev['quote']
        evidence_checks.append(dict(evidence_id=eid, block_id=ev['block_id'],
            text_hash=ev['text_hash'], old_index_id=ev['index_id'], new_index_id=source['index_id'],
            new_reported_page=block.get('reported_page')))
    checks.append(dict(case=case['id'], source_sha256=source['raw_sha256'],
        new_package=str(package.relative_to(ROOT)), new_package_id=manifest['package_id'],
        new_manifest_sha256=sha256((package/'manifest.json').read_bytes()).hexdigest(),
        unchanged_evidence_spans=evidence_checks))
receipt = dict(status='passed', migration_performed=False, model_calls=0, checks=checks,
    note='Exact source bytes, block hashes and quote offsets agree. Old query references remain old references; this receipt does not silently rewrite index IDs or adopt the candidates.')
target = HERE / 'parser-evidence-compatibility.json'
data = json.dumps(receipt, ensure_ascii=False, indent=2)+'\n'
if target.exists() and target.read_text() != data:
    raise ValueError('Existing receipt differs; preserve it and use a new experiment version.')
target.write_text(data)
print('Verified exact evidence spans against both new parser packages; no migration.')
