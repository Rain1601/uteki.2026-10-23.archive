"""Freeze one complete, caller-selected report subsection; never load answers.

This file is an explicit Microsoft experiment adapter, not shared extraction
logic. All selected text is independently re-read from the frozen original DOM.
"""
import hashlib
import json
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORPUS = ROOT / 'data/company_workspace/extraction_ab_v1/corpus/msft'
SOURCE = CORPUS / 'originals/msft-2025-10k.html'
INDEX = CORPUS / 'dataset/indexes/msft-2025-10k/blocks.jsonl'
ACQUISITION = CORPUS / 'acquisition.json'
SOURCE_SHA = '0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6'
INDEX_SHA = 'f538b960f9d3d893e2b7288b4c228409c0f7ce6a6cecd7c47cf206c91546a9d7'
COMPANY, DOCUMENT, PERIOD = 'sec-0000789019', 'msft-2025-10k', '2025-06-30'
URL = 'https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm'
START, END_EXCLUSIVE = 117, 143
METADATA_ORDINALS = [6, 8, 86, 87]
sha = lambda b: hashlib.sha256(b).hexdigest()
json_bytes = lambda v: (json.dumps(v, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
relative = lambda p: str(p.relative_to(ROOT))


def freeze(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('frozen_output_changed_use_new_version: ' + str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)


def make_packet():
    raw = SOURCE.read_bytes()
    if sha(raw) != SOURCE_SHA or sha(INDEX.read_bytes()) != INDEX_SHA:
        raise ValueError('original_or_index_hash_changed')
    acquisition = json.loads(ACQUISITION.read_bytes())
    doc = next(d for d in acquisition['documents'] if d['source_id'] == DOCUMENT)
    assert acquisition['company']['company_id'] == COMPANY
    assert doc['period_end'] == PERIOD and doc['source_url'] == URL and doc['content_sha256'] == SOURCE_SHA
    dom = html.fromstring(raw); tree = dom.getroottree()
    source_by_path = {tree.getpath(el): el for el in dom.iter()}
    indexed = {b['ordinal']: b for b in map(json.loads, INDEX.read_text().splitlines())}
    assert indexed[START]['text'] == 'Intelligent Cloud'
    assert indexed[END_EXCLUSIVE]['text'] == 'More Personal Computing'
    assert indexed[START]['type'] == indexed[END_EXCLUSIVE]['type'] == 'heading_candidate'
    selected = METADATA_ORDINALS + list(range(START, END_EXCLUSIVE))
    blocks = []
    for ordinal in selected:
        source = indexed[ordinal]
        text = ' '.join(''.join(source_by_path[source['dom_path']].itertext()).split())
        assert text == source['text'] and sha(text.encode()) == source['text_hash']
        metadata = ordinal in METADATA_ORDINALS
        path = (['Form 10-K', 'Cover'] if ordinal in (6,8) else
                ['Form 10-K', 'Item 1. Business', 'Operating Segments (scope metadata)'] if metadata else
                ['Form 10-K', 'Item 1. Business', 'Intelligent Cloud'] + (['Competition'] if ordinal >= 133 else []))
        blocks.append(dict(id=source['block_id'], ordinal=ordinal, type=source['type'], text=text,
            text_sha256=source['text_hash'], source_dom_path=source['dom_path'], section_path=path,
            reported_page=source['reported_page'], input_role='scope_metadata' if metadata else 'selected_subsection'))
    section_blocks = [b for b in blocks if b['input_role'] == 'selected_subsection']
    scope_ids = [b['id'] for b in blocks if b['input_role'] == 'scope_metadata']
    section_text = '\n'.join(b['text'] for b in section_blocks).encode()
    manifest = dict(schema_version='official-html-source-manifest-v1', company_id=COMPANY,
        document_id=DOCUMENT, period_end=PERIOD, source_url=URL, content_sha256=SOURCE_SHA,
        source_local_path=relative(SOURCE), content_kind='official_sec_html', source_bytes=len(raw),
        network_refetch_performed=False, acquisition_local_path=relative(ACQUISITION),
        acquisition_sha256=sha(ACQUISITION.read_bytes()), index_local_path=relative(INDEX), index_sha256=INDEX_SHA)
    manifest_path = HERE / 'input/source_manifest.json'
    packet = dict(schema_version='source-packet-v1', company_id=COMPANY, document_id=DOCUMENT,
        period_end=PERIOD, requested_period_label='2025', source_local_path=relative(SOURCE),
        source_sha256=SOURCE_SHA, source_url=URL, source_kind='official_sec_html', form_type='10-K',
        source_manifest=dict(local_path=relative(manifest_path), sha256=sha(json_bytes(manifest))),
        text_normalization='Original DOM itertext; Unicode whitespace collapsed. Original wording preserved; no source block filtered.',
        extraction_scope=dict(kind='complete_report_subsection', title='Item 1. Business / Intelligent Cloud',
            start_ordinal=START, end_ordinal_inclusive=END_EXCLUSIVE-1, end_boundary_exclusive_ordinal=END_EXCLUSIVE,
            end_boundary_exclusive_title=indexed[END_EXCLUSIVE]['text'],
            section_block_ids=[b['id'] for b in section_blocks], scope_metadata_block_ids=scope_ids,
            includes_competition=True, filtered_block_ids=[], financial_analysis=False,
            instruction='Extract the selected Intelligent Cloud subsection. Other segment names in scope metadata only establish reporting context; their businesses are outside this selected task.'),
        scope_evidence_block_ids=dict(company=[indexed[8]['block_id']], period=[indexed[6]['block_id']],
            reporting_segments=[indexed[86]['block_id']], current_period_changes=[indexed[87]['block_id']]),
        blocks=blocks, tables=[])
    audit = dict(schema_version='subsection-selection-verification-v1', status='source_dom_verified',
        company_id=COMPANY, document_id=DOCUMENT, period_end=PERIOD, source_sha256=SOURCE_SHA,
        index_sha256=INDEX_SHA, source_packet_sha256=sha(json_bytes(packet)), source_packet_bytes=len(json_bytes(packet)),
        selected_subsection_blocks=len(section_blocks), scope_metadata_blocks=len(scope_ids), total_blocks=len(blocks),
        tables=0, excluded_blocks=[], selected_ordinals=selected,
        subsection_text_sha256=sha(section_text), subsection_text_utf8_bytes=len(section_text),
        subsection_text_digest_basis='Original normalized block text joined in original ordinal order with one LF, no trailing LF.',
        boundary=dict(start=dict(ordinal=START,block_id=indexed[START]['block_id'],text=indexed[START]['text'],source_dom_path=indexed[START]['dom_path']),
            end_exclusive=dict(ordinal=END_EXCLUSIVE,block_id=indexed[END_EXCLUSIVE]['block_id'],text=indexed[END_EXCLUSIVE]['text'],source_dom_path=indexed[END_EXCLUSIVE]['dom_path'])),
        blocks=[dict(id=b['id'],ordinal=b['ordinal'],input_role=b['input_role'],text_sha256=b['text_sha256'],source_dom_path=b['source_dom_path']) for b in blocks],
        all_selected_blocks_match_original_dom_and_index=True, no_expected_answers_loaded=True, model_api_calls=0,
        limits=['Explicit experiment section selection, not general section discovery.',
            'Scope metadata includes other reportable segment names; those segments are not extraction targets.',
            'Competition contains both competitor context and statements about Microsoft offerings; all are retained.',
            'No financial decomposition requested, so there is no financial table or USD/million assertion.'])
    return packet, manifest, audit


def main():
    packet, manifest, audit = make_packet()
    freeze(HERE/'input/source_manifest.json', json_bytes(manifest))
    freeze(HERE/'input/source_packet.json', json_bytes(packet))
    freeze(HERE/'input/selection-verification.json', json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('source_packet_sha256','source_packet_bytes','total_blocks','selected_subsection_blocks','subsection_text_sha256')},ensure_ascii=False))


if __name__ == '__main__':
    main()
