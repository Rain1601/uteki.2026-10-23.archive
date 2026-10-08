"""Audit actual v0.1.11 annual packages; do not inherit old v0.1.12 results."""
import gzip
import hashlib
import json
from pathlib import Path
from uteki.infrastructure.document_sources.coverage_audit import audit_html_tenk

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
summary = []
for company in ('msft', 'googl'):
    dataset = ROOT / 'experiments/agent_design/2026-10-08-acquisition-reuse-v1' / company / 'dataset'
    sources = json.loads((dataset / 'sources.json').read_text())
    assert len(sources) == 1 and sources[0]['form'] == '10-K'
    meta = sources[0]
    package = dataset / meta['index_folder']
    raw = dataset / meta['raw_file']
    paths = [raw, *(package / name for name in ('source.json', 'index.json', 'blocks.jsonl'))]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    source = json.loads((package / 'source.json').read_text())
    index = json.loads((package / 'index.json').read_text())
    blocks = [json.loads(line) for line in (package / 'blocks.jsonl').read_text().splitlines()]
    result = audit_html_tenk(raw.read_bytes(), source, index, blocks)
    ledger = result.pop('text_ledger')
    ledger_bytes = gzip.compress(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ledger).encode(), mtime=0)
    with (HERE / f'{company}-text-ledger.jsonl.gz').open('xb') as stream:
        stream.write(ledger_bytes)
    result['ledger_sha256'] = hashlib.sha256(ledger_bytes).hexdigest()
    result['input_sha256'] = before
    result['originals_unchanged'] = before == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert result['originals_unchanged']
    with (HERE / f'{company}-coverage.json').open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    row = {key: result[key] for key in ('source', 'totals', 'finding_counts', 'block_dom_order', 'originals_unchanged')}
    summary.append(row)
    print(company, row['totals'], row['finding_counts'], row['block_dom_order']['status'])
with (HERE / 'coverage-summary.json').open('x') as stream:
    stream.write(json.dumps({'network_calls': 0, 'model_calls': 0, 'cases': summary}, ensure_ascii=False, indent=2) + '\n')
