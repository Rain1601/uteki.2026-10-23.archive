"""Offline acceptance: explicit frozen HTML 10-K inputs; no model or source edits."""
import hashlib
import importlib.util
import json
from pathlib import Path
from uteki.agents.reading.document_reader import DocumentReader
from uteki.agents.reading.reading_groups import build_reading_groups, VERSION

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DATA = ROOT / 'experiments/agent_design/2026-10-08-acquisition-reuse-v1'
CASES = [
    ('AMD FY2023', 'amd/preparation/dataset/indexes/source-291485b98a75d8cfabe47571',
     'block-000804-7db735ca', 'block-000805-1e1260e7'),
    ('AMD FY2024', 'amd/preparation/dataset/indexes/source-e4a71173a2513dd3e8a683fe',
     'block-000800-9c7fca45', 'block-000801-1e1260e7'),
    ('Alphabet FY2025', 'googl/dataset/indexes/googl-2025-10k',
     'block-001306-e8854eab', 'block-001307-0e3cb34c'),
    ('Microsoft FY2025', 'msft/dataset/indexes/msft-2025-10k', None, None),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('before', HERE / 'reading_groups_before.py')
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    reports = []
    for label, folder, table_id, note_id in CASES:
        path = DATA / folder
        hashes = {name: sha(path / name) for name in ('blocks.jsonl', 'index.json', 'manifest.json')}
        reader = DocumentReader(path)
        assert reader.index['form_type'] == '10-K'
        old = before.build_reading_groups(reader.blocks, reader.index['nodes'])
        new = build_reading_groups(reader.blocks, reader.index['nodes'])
        links = [g for g in new if g.get('note_links')]
        record = {'label': label, 'input_folder': str(path.relative_to(ROOT)), 'input_sha256': hashes,
                  'source_block_count': len(reader.blocks), 'before_group_count': len(old),
                  'after_group_count': len(new), 'linked_table_notes': links}
        if table_id:
            pos = reader.positions[table_id]
            # Narrowest legal node containing both original table and note.
            node = min((n for n in reader.index['nodes']
                        if reader.positions[n['start_block_id']] <= pos
                        and reader.positions[n['end_block_id']] >= reader.positions[note_id]),
                       key=lambda n: reader.positions[n['end_block_id']] - reader.positions[n['start_block_id']])
            reader.groups = old
            old_ids = [b['block_id'] for b in reader.read(node['node_id'], table_id, count=1)['blocks']]
            reader.groups = new
            result = reader.read(node['node_id'], table_id, count=1)
            new_ids = [b['block_id'] for b in result['blocks']]
            assert note_id not in old_ids and note_id in new_ids
            assert set(new_ids) - set(old_ids) == {note_id}, (label, old_ids, new_ids)
            assert [b['block_id'] for b in reader.read(node['node_id'], note_id, count=1)['blocks']] == new_ids
            record['acceptance'] = {'node_id': node['node_id'], 'read_table_id': table_id,
                                    'before_block_ids': old_ids, 'after_block_ids': new_ids,
                                    'added_exactly_expected_note': True, 'reverse_read_includes_table': True}
        else:
            # This sample had no matching table-note pattern: block grouping stays unchanged.
            assert [g['block_ids'] for g in old] == [g['block_ids'] for g in new]
            record['acceptance'] = {'block_group_membership_unchanged': True}
        assert hashes == {name: sha(path / name) for name in hashes}
        record['originals_unchanged'] = True
        reports.append(record)
    result = {'status': 'passed', 'scope': 'selected frozen HTML 10-K table reading contexts',
              'reading_group_version': VERSION, 'prior_implementation_sha256': sha(HERE / 'reading_groups_before.py'),
              'implementation_sha256': sha(ROOT / 'src/uteki/agents/reading/reading_groups.py'),
              'model_calls': 0, 'cases': reports,
              'limits': ['Only immediately adjacent table-shaped notes with isolated markers are linked.',
                         'Whole-cell marker matches are lexical context, not validated financial applicability.',
                         'Inline/superscript, remote and page-separated note links remain unresolved.',
                         'No new assertion of complete semantic extraction or whole-document reading-order correctness.']}
    (HERE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'cases': len(reports),
                      'added_note_links': sum(len(x['linked_table_notes']) for x in reports)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
