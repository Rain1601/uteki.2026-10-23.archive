"""Read-only duplicate diagnostics on explicitly selected local material versions.

Equal text in distinct DOM positions is a candidate, not a parse error.
Nested blocks are overlapping representations, not additional source text.
No network/model calls and no modifications to originals or parsed packages.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DATASETS = [
    'experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset',
    'experiments/agent_design/2026-10-08-acquisition-reuse-v1/googl/dataset',
    'data/company_workspace/extraction_ab_v1/corpus/googl/dataset',
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

cases, texts, raw_groups = [], [], defaultdict(list)
for relative in DATASETS:
    dataset = ROOT / relative
    for source in json.loads((dataset / 'sources.json').read_text()):
        package = dataset / source['index_folder']
        blocks = [json.loads(line) for line in (package / 'blocks.jsonl').read_text().splitlines()]
        index = json.loads((package / 'index.json').read_text())
        identity = relative + ':' + source['source_snapshot_id']
        by_path, by_text = defaultdict(list), defaultdict(list)
        for block in blocks:
            by_path[block['dom_path']].append(block['block_id'])
            if block['text'].strip():
                by_text[block['text']].append(block['block_id'])
        nested = [{'parent': parent['block_id'], 'child': child['block_id'],
                   'parent_kind': parent['type'], 'child_kind': child['type']}
                  for parent in blocks for child in blocks
                  if child['dom_path'].startswith(parent['dom_path'] + '/')]
        repeated = [{'text': text, 'block_ids': ids}
                    for text, ids in by_text.items() if len(ids) > 1]
        repeated.sort(key=lambda r: len(r['text']), reverse=True)
        raw = dataset / source['raw_file']
        actual_hash = sha(raw)
        assert actual_hash == source['source_sha256']
        raw_groups[actual_hash].append(identity)
        cases.append({
            'identity': identity, 'company_id': source['company_id'],
            'form': source['form'], 'period_end': source['period_end'],
            'available_at': source['available_at'], 'source_url': source['source_url'],
            'raw_sha256': actual_hash, 'parser_version': index['parser_version'],
            'blocks_sha256': sha(package / 'blocks.jsonl'),
            'block_count': len(blocks),
            'duplicate_block_ids': len(blocks) - len({b['block_id'] for b in blocks}),
            'duplicate_dom_paths': {p: ids for p, ids in by_path.items() if len(ids) > 1},
            'nested_representation_pairs': nested,
            'equal_text_group_count': len(repeated),
            'longest_equal_text_examples': repeated[:5],
        })
        texts.append((identity, actual_hash, source['company_id'], by_text))

cross = []
for i, (left, left_hash, company, left_texts) in enumerate(texts):
    for right, right_hash, other_company, right_texts in texts[i + 1:]:
        if left_hash == right_hash or company != other_company:
            continue
        shared = sorted(set(left_texts) & set(right_texts), key=len, reverse=True)
        cross.append({'left': left, 'right': right, 'equal_text_group_count': len(shared),
                      'longest_examples': [{'text': t, 'left_blocks': left_texts[t],
                                           'right_blocks': right_texts[t]} for t in shared[:5]],
                      'interpretation': 'literal overlap only; do not delete original disclosures'})
result = {'model_calls': 0, 'network_calls': 0, 'source_files_modified': False,
          'scope': 'selected local snapshots only; not an all-filings inventory',
          'cases': cases, 'same_raw_versions': dict(raw_groups), 'cross_document_overlap': cross}
with (HERE / 'verification.json').open('x') as out:
    out.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
for case in cases:
    print(case['identity'], 'blocks=', case['block_count'],
          'duplicate_paths=', len(case['duplicate_dom_paths']),
          'nested_pairs=', len(case['nested_representation_pairs']),
          'equal_text_groups=', case['equal_text_group_count'])
