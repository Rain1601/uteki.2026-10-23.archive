"""Explicit experiment selection of a complete Alphabet Item 1; source only.

Reuses the previous complete-subsection preparation's immutable writer and
official source manifest/packet shape. No prior candidate or review is loaded.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import html
from uteki.agents.business_map.product_run import verify_packet

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PRIOR_PREPARER = ROOT/'experiments/agent_design/2026-10-07-microsoft-cloud-business-v1/prepare_input.py'
spec = importlib.util.spec_from_file_location('subsection_preparation', PRIOR_PREPARER)
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)
freeze, json_bytes = preparation.freeze, preparation.json_bytes
sha = lambda data: hashlib.sha256(data).hexdigest()
relative = lambda path: str(path.relative_to(ROOT))
CORPUS = ROOT/'data/company_workspace/extraction_ab_v1/corpus/googl'
SOURCE = CORPUS/'originals/googl-2025-10k.html'
INDEX = CORPUS/'dataset/indexes/googl-2025-10k/blocks.jsonl'
ACQUISITION = CORPUS/'acquisition.json'
SOURCE_SHA = 'c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161'
INDEX_SHA = '72331e3c3c8b5edab2781bb669b4ea48d920ecda0ce1214f38ab4dda1f7744c8'
COMPANY, DOCUMENT, PERIOD = 'sec-0001652044', 'googl-2025-10k', '2025-12-31'
START, END_EXCLUSIVE, METADATA = 61, 152, [11, 17]


def main():
    raw = SOURCE.read_bytes()
    assert sha(raw) == SOURCE_SHA and sha(INDEX.read_bytes()) == INDEX_SHA
    acquisition = json.loads(ACQUISITION.read_bytes())
    source = next(d for d in acquisition['documents'] if d['source_id'] == DOCUMENT)
    assert acquisition['company']['company_id'] == COMPANY
    assert source['period_end'] == PERIOD and source['content_sha256'] == SOURCE_SHA
    assert source['form'] == '10-K' and source['mime_type'] == 'text/html'
    dom = html.fromstring(raw)
    tree = dom.getroottree()
    paths = {tree.getpath(el): el for el in dom.iter()}
    indexed = {b['ordinal']: b for b in map(json.loads, INDEX.read_text().splitlines())}
    assert indexed[START]['text'] == 'ITEM 1.BUSINESS'
    assert indexed[END_EXCLUSIVE]['text'] == 'ITEM 1A.RISK FACTORS'
    assert indexed[11]['text'] == 'For the fiscal year ended December 31, 2025'
    assert indexed[17]['text'] == 'Alphabet Inc.'
    blocks = []
    heading = indexed[START]['text']
    for ordinal in METADATA + list(range(START, END_EXCLUSIVE)):
        block = indexed[ordinal]
        text = ' '.join(''.join(paths[block['dom_path']].itertext()).split())
        assert text == block['text'] and sha(text.encode()) == block['text_hash']
        if ordinal >= START and block['type'] == 'heading_candidate':
            heading = text
        metadata = ordinal in METADATA
        blocks.append(dict(id=block['block_id'], ordinal=ordinal, type=block['type'],
            text=text, text_sha256=block['text_hash'], source_dom_path=block['dom_path'],
            section_path=['Form 10-K', 'Cover'] if metadata else ['Form 10-K', 'Item 1. Business', heading],
            reported_page=block['reported_page'], input_role='scope_metadata' if metadata else 'selected_subsection'))
    section = [b for b in blocks if b['input_role'] == 'selected_subsection']
    texts = dom.xpath('//text()')
    def offset(element):
        return next(i for i, text in enumerate(texts) if not text.is_tail and
                    (text.getparent() is element or element in text.getparent().iterancestors()))
    lo, hi = [offset(paths[indexed[i]['dom_path']]) for i in (START, END_EXCLUSIVE)]
    compact = lambda value: ''.join(value.split())
    assert compact(''.join(str(t) for t in texts[lo:hi])) == compact(''.join(b['text'] for b in section))
    manifest = dict(schema_version='official-html-source-manifest-v1', company_id=COMPANY,
        document_id=DOCUMENT, period_end=PERIOD, source_url=source['source_url'], content_sha256=SOURCE_SHA,
        source_local_path=relative(SOURCE), content_kind='official_sec_html', source_bytes=len(raw),
        network_refetch_performed=False, acquisition_local_path=relative(ACQUISITION),
        acquisition_sha256=sha(ACQUISITION.read_bytes()), index_local_path=relative(INDEX), index_sha256=INDEX_SHA)
    packet = dict(schema_version='source-packet-v1', company_id=COMPANY, document_id=DOCUMENT,
        period_end=PERIOD, requested_period_label='2025', source_local_path=relative(SOURCE),
        source_sha256=SOURCE_SHA, source_url=source['source_url'], source_kind='official_sec_html', form_type='10-K',
        source_manifest=dict(local_path=relative(HERE/'source_manifest.json'), sha256=sha(json_bytes(manifest))),
        text_normalization='Original DOM itertext; Unicode whitespace collapsed. Original wording preserved; no source block filtered.',
        extraction_scope=dict(kind='complete_report_subsection', title='Item 1. Business (complete Item)',
            start_ordinal=START, end_ordinal_inclusive=END_EXCLUSIVE-1,
            end_boundary_exclusive_ordinal=END_EXCLUSIVE, end_boundary_exclusive_title=indexed[END_EXCLUSIVE]['text'],
            section_block_ids=[b['id'] for b in section],
            scope_metadata_block_ids=[b['id'] for b in blocks if b['input_role']=='scope_metadata'],
            includes_competition=True, filtered_block_ids=[], financial_analysis=False,
            instruction='Extract the entire selected Item 1 Business. All original blocks, including competition, workforce, regulation, intellectual property, available-information disclosures and page navigation, are retained. Preserve reported business scope and exact evidence; cross references do not mean the referenced sections were supplied. This is selected filing coverage, not an exhaustive external product catalog.'),
        scope_evidence_block_ids=dict(company=[indexed[17]['block_id']], period=[indexed[11]['block_id']]),
        blocks=blocks, tables=[])
    freeze(HERE/'source_manifest.json', json_bytes(manifest))
    # Uses the actual production preflight, including original DOM/source verification.
    verify_packet(packet, ROOT, company_id=COMPANY, document_id=DOCUMENT,
                  period_end=PERIOD, contract_version='business-draft-v2')
    freeze(HERE/'source_packet.json', json_bytes(packet))
    audit = dict(schema_version='subsection-selection-verification-v1', status='source_dom_verified',
        company_id=COMPANY, document_id=DOCUMENT, period_end=PERIOD, source_sha256=SOURCE_SHA,
        source_packet_sha256=sha(json_bytes(packet)), source_packet_bytes=len(json_bytes(packet)),
        index_sha256=INDEX_SHA, source_index_parser_version='sec-source-blocks-v0.1.6',
        selected_subsection_blocks=len(section), scope_metadata_blocks=len(METADATA), total_blocks=len(blocks),
        selected_ordinals=[b['ordinal'] for b in blocks], excluded_blocks=[],
        total_text_characters=sum(len(b['text']) for b in blocks),
        total_text_utf8_bytes=sum(len(b['text'].encode()) for b in blocks),
        subsection_text_sha256=sha('\n'.join(b['text'] for b in section).encode()),
        navigation_table_blocks=[b['id'] for b in section if b['type']=='table'],
        table_representation='Navigation table text preserved in blocks; no financial cell-selection task or numeric table supplied.',
        boundary={key:dict(ordinal=i, block_id=indexed[i]['block_id'], text=indexed[i]['text'],
                           source_dom_path=indexed[i]['dom_path'])
                  for key,i in [('start',START),('end_exclusive',END_EXCLUSIVE)]},
        all_selected_blocks_match_original_dom_and_index=True, complete_boundary_dom_text_equal=True,
        production_verify_packet='passed', no_expected_answers_loaded=True, model_api_calls=0,
        preparation_reuse=dict(path=relative(PRIOR_PREPARER), sha256=sha(PRIOR_PREPARER.read_bytes()),
                               reused='immutable freeze and JSON serialization; same official manifest and complete-subsection packet contract'),
        input_files=[dict(path=relative(p),sha256=sha(p.read_bytes())) for p in (SOURCE, INDEX, ACQUISITION)],
        limits=['Explicit experiment selection; not general section discovery.',
                'Complete Item 1 only; referenced Risk Factors and MD&A are outside input.',
                'Historical corpus index is retained because its block text matches the production DOM normalization; no index or original is overwritten.',
                'Local verified original reuse, no network acquisition.',
                'No model output, previous candidate, review, or expected business classification is loaded.'])
    freeze(HERE/'verification.json', json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('source_packet_sha256','source_packet_bytes','total_blocks','total_text_characters')},ensure_ascii=False))


if __name__ == '__main__':
    main()
