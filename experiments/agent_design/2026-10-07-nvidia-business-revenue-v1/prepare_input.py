"""Freeze an explicitly selected NVIDIA FY2025 PDF excerpt, without model answers.

This is a versioned experiment adapter, not a general PDF table extractor.
Selected page regions and column boundaries describe the reviewed PDF geometry.
Every table word comes from pdftotext -bbox-layout, not a financial answer list.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

from lxml import etree
from lxml import html as lhtml

from uteki.agents.business_map.product_run import verify_packet

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'input'
SOURCE = ROOT / 'experiments/agent_design/2026-10-07-business-map-mermaid-v1/nvidia'
PDF_SHA = '757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc'
LEGACY_HTML_SHA = '47daa32ef7787e4d705d55cb2209b383edc2a6a504fbb7cc995ec431bdaaa24b'
COMPANY = 'nvidia'
DOCUMENT = 'nvidia-fy2025-annual-report-10k'
PERIOD_END = '2025-01-26'
URL = 'https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf'

# Explicitly selected PDF geometry, in page points. No amounts, chart answers,
# normalized accounting labels or expected totals enter this adapter.
TABLE_REGIONS = [
    dict(id='table-pdf133-revenue', page=133, printed_page=41,
         section=['Form 10-K', 'Item 7', 'Reportable Segments', 'Revenue by Reportable Segments'],
         columns=[49, 284, 304, 359, 379, 434, 454, 500, 552, 565],
         rows=[73, 88, 113, 129, 143, 157, 172],
         spans={0: [(0, 1), (1, 8)], 1: [(0, 1), (1, 2), (3, 2), (5, 2), (7, 2)], 2: [(0, 1), (1, 8)]}),
    dict(id='table-pdf172-markets', page=172, printed_page=80,
         section=['Form 10-K', 'Notes', 'Note 16. Segment Information', 'Revenue by End Market'],
         columns=[49, 329, 347, 408, 424, 485, 501, 565],
         rows=[245, 260, 278, 293, 309, 324, 338, 353, 368, 383, 398, 412],
         spans={0: [(0, 1), (1, 6)], 1: [(0, 1), (1, 2), (3, 2), (5, 2)], 2: [(0, 1), (1, 6)]}),
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def norm(text):
    return ' '.join(text.split())


def freeze(path, raw):
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f'Frozen file differs; use a new experiment version: {path}')
    path.write_bytes(raw)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def rel(path):
    return str(path.relative_to(ROOT))


def section_for(ordinal):
    if ordinal < 842:
        return ['Form 10-K', 'Cover']
    if ordinal <= 856:
        return ['Form 10-K', 'Item 1. Business', 'Our Company']
    if ordinal <= 859:
        return ['Form 10-K', 'Item 1. Business', 'Our Businesses']
    if ordinal <= 881:
        return ['Form 10-K', 'Item 1. Business', 'Our Markets']
    if ordinal == 1265:
        return ['Form 10-K', 'Item 7', 'Reportable Segments', 'Revenue by Reportable Segments']
    if 1427 <= ordinal <= 1431:
        return ['Form 10-K', 'Notes', 'Note 1', 'Reporting scope and fiscal year']
    if 1433 <= ordinal <= 1443:
        return ['Form 10-K', 'Notes', 'Note 1', 'Revenue Recognition']
    if ordinal == 1450:
        return ['Form 10-K', 'Notes', 'Note 1', 'Foreign Currency Remeasurement']
    return ['Form 10-K', 'Notes', 'Note 16. Segment Information']


def table_cells(config, pdf):
    with tempfile.TemporaryDirectory(prefix='uteki-nvidia-bbox-') as tmp:
        target = Path(tmp) / 'page.html'
        subprocess.run(['pdftotext', '-f', str(config['page']), '-l', str(config['page']),
                        '-bbox-layout', str(pdf), str(target)], check=True)
        dom = etree.parse(str(target))
    words = []
    for index, w in enumerate(dom.xpath('//*[local-name()="word"]')):
        box = [float(w.get(k)) for k in ('xMin', 'yMin', 'xMax', 'yMax')]
        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
        if config['columns'][0] <= cx < config['columns'][-1] and config['rows'][0] <= cy < config['rows'][-1]:
            words.append(dict(index=index, text=''.join(w.itertext()), bbox=box, cx=cx, cy=cy))
    cells, assigned = [], []
    for ri, (top, bottom) in enumerate(zip(config['rows'], config['rows'][1:])):
        for ci, span in config['spans'].get(ri, [(c, 1) for c in range(len(config['columns'])-1)]):
            left, right = config['columns'][ci], config['columns'][ci+span]
            selected = [w for w in words if top <= w['cy'] < bottom and left <= w['cx'] < right]
            selected.sort(key=lambda w: (round(w['bbox'][1], 1), w['bbox'][0]))
            assigned.extend(w['index'] for w in selected)
            cell_id = f"cell-{config['id']}-r{ri:03}-c{ci:03}"
            cells.append(dict(id=cell_id, row_index=ri, column_index=ci, rowspan=1, colspan=span,
                              text=norm(' '.join(w['text'] for w in selected)),
                              pdf_bbox=[left, top, right, bottom],
                              pdf_words=[dict(text=w['text'], bbox=w['bbox']) for w in selected]))
    if len(set(assigned)) != len(assigned) or set(assigned) != {w['index'] for w in words}:
        raise ValueError('PDF table word coverage is incomplete or duplicated')
    return cells, len(words)


def main():
    OUT.mkdir(exist_ok=True, parents=True)
    pdf = SOURCE / 'source.pdf'
    legacy_html = SOURCE / 'source.html'
    text_path = SOURCE / 'source.txt'
    assert sha(pdf.read_bytes()) == PDF_SHA, 'PDF changed'
    assert sha(legacy_html.read_bytes()) == LEGACY_HTML_SHA, 'Existing PDF text projection changed'
    # Re-extract the full original using the same declared Poppler layout mode.
    # The parsed paragraphs are checked against both this text and the frozen
    # pre-existing paragraph projection, without reading any business_map file.
    fresh = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], check=True, capture_output=True).stdout.decode()
    if fresh != text_path.read_text():
        raise ValueError('Frozen PDF text does not match fresh pdftotext -layout output')
    legacy_dom = lhtml.fromstring(legacy_html.read_bytes())
    legacy_tree = legacy_dom.getroottree()
    legacy_by_id = {el.get('id'): el for el in legacy_dom.xpath('//p[@id]')}
    selected_ordinals = set([818, 819, 1265, 1427, 1430, 1431, 1450, 1711])
    selected_ordinals.update(range(842, 882))
    selected_ordinals.update(range(1433, 1444))
    selected_ordinals.update(range(1683, 1689))
    selected_ordinals.difference_update([852, 866, 878, 1437, 1438])  # page numbers / repeated running heading
    entries, ordinal = [], 0
    for page, text in enumerate(fresh.split('\f'), 1):
        for page_block, content in enumerate(re.split(r'\n\s*\n', text), 1):
            text = norm(content)
            if not text:
                continue
            ordinal += 1
            if ordinal not in selected_ordinals:
                continue
            old_id = f'p-{ordinal:05}'
            old_el = legacy_by_id[old_id]
            assert norm(''.join(old_el.itertext())) == text
            assert old_el.getparent().get('id') == f'page-{page}'
            assert int(old_el.get('data-page-block')) == page_block
            bid = f'pdf-block-{ordinal:06}-{sha(text.encode())[:8]}'
            entries.append(dict(id=bid, ordinal=ordinal, text=text, text_sha256=sha(text.encode()),
                                type='paragraph', section_path=section_for(ordinal),
                                pdf_page_number=page, pdf_page_index=page-1, pdf_page_block=page_block,
                                reported_page=(page-92 if page >= 96 else None), original_source_fragment=f'page={page}',
                                original_source_path=rel(pdf), original_source_sha256=PDF_SHA,
                                origin_text_fragment=old_id, origin_text_dom_path=legacy_tree.getpath(old_el),
                                origin_text_source_local_path=rel(legacy_html),
                                origin_text_source_sha256=LEGACY_HTML_SHA))
    assert {b['ordinal'] for b in entries} == selected_ordinals
    table_data, word_counts = [], {}
    for config in TABLE_REGIONS:
        cells, words = table_cells(config, pdf)
        table_data.append((config, cells))
        word_counts[config['id']] = words
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><title>NVIDIA FY2025 selected PDF source</title>',
             '<style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:16px/1.6 sans-serif}section{margin:30px 0}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:5px;text-align:left}h2{font-size:18px}small{color:#555}</style></head><body>',
             '<h1>NVIDIA FY2025 — PDF-derived selected source</h1>',
             '<p>This is a derived reading view. Paragraphs preserve pdftotext -layout text; tables are reconstructed from explicitly reviewed PDF coordinates. It is not official HTML.</p>']
    pdf_link = '../../2026-10-07-business-map-mermaid-v1/nvidia/source.pdf'
    for block in entries:
        parts.append(f'<section id="{block["id"]}"><small><a href="{pdf_link}#page={block["pdf_page_number"]}">PDF page {block["pdf_page_number"]}</a>, text block {block["pdf_page_block"]}</small>')
        parts.append(f'<p id="text-{block["id"]}">{html.escape(block["text"])}</p></section>')
    for config, cells in table_data:
        parts.append(f'<section><h2><a href="{pdf_link}#page={config["page"]}">PDF page {config["page"]}</a> · {html.escape(config["section"][-1])}</h2><table id="{config["id"]}">')
        for ri in range(len(config['rows'])-1):
            parts.append('<tr>')
            for cell in [c for c in cells if c['row_index']==ri]:
                tag = 'th' if ri < 3 else 'td'
                parts.append(f'<{tag} id="{cell["id"]}" colspan="{cell["colspan"]}">{html.escape(cell["text"])}</{tag}>')
            parts.append('</tr>')
        parts.append('</table></section>')
    parts.append('</body></html>')
    source_raw = '\n'.join(parts).encode()
    source_file = OUT / 'source.html'
    freeze(source_file, source_raw)
    dom = lhtml.fromstring(source_raw); tree = dom.getroottree()
    for block in entries:
        el = dom.get_element_by_id('text-'+block['id'])
        block.update(source_dom_path=tree.getpath(el), fragment='text-'+block['id'])
    tables = []
    for config, cells in table_data:
        el = dom.get_element_by_id(config['id'])
        text = norm(''.join(el.itertext()))
        bid = 'pdf-'+config['id']
        entries.append(dict(id=bid, ordinal=10000+config['page'], type='table',
                            text=text, text_sha256=sha(text.encode()), source_dom_path=tree.getpath(el),
                            fragment=config['id'], section_path=config['section'],
                            pdf_page_number=config['page'], pdf_page_index=config['page']-1,
                            reported_page=config['printed_page'], original_source_path=rel(pdf),
                            original_source_sha256=PDF_SHA, original_source_fragment=f'page={config["page"]}'))
        rows = []
        for cell in cells:
            ce = dom.get_element_by_id(cell['id'])
            cell.update(source_dom_path=tree.getpath(ce), text_sha256=sha(cell['text'].encode()),
                        is_header=ce.tag=='th', pdf_page_number=config['page'])
        for ri in range(len(config['rows'])-1):
            rows.append(dict(row_index=ri, cell_ids=[c['id'] for c in cells if c['row_index']==ri]))
        tables.append(dict(id=config['id'], block_id=bid, source_dom_path=tree.getpath(el),
                           rows=rows, cells=cells, pdf_page_number=config['page'],
                           geometry_source='pdftotext -bbox-layout; explicitly selected versioned page regions',
                           pdf_column_boundaries=config['columns'], pdf_row_boundaries=config['rows']))
    manifest = dict(schema_version='pdf-derived-source-manifest-v1', company_id=COMPANY,
                    document_id=DOCUMENT, period_end=PERIOD_END, source_url=URL,
                    content_sha256=sha(source_raw), content_kind='derived_html_from_official_ir_pdf',
                    original_source_path=rel(pdf), original_source_sha256=PDF_SHA,
                    original_source_text_path=rel(text_path), original_source_text_sha256=sha(text_path.read_bytes()),
                    derivation='Fresh pdftotext -layout paragraphs; complete tables from PDF word bounding boxes. No model or target answers.',
                    script_path=rel(Path(__file__)), script_sha256=sha(Path(__file__).read_bytes()))
    manifest_path = OUT/'source_manifest.json';freeze(manifest_path,json_bytes(manifest))
    by_ord={b['ordinal']:b['id'] for b in entries}
    packet=dict(schema_version='source-packet-v1',company_id=COMPANY,document_id=DOCUMENT,
                period_end=PERIOD_END,requested_period_label='Jan 26, 2025',financial_currency='USD',financial_unit='million',
                scope_evidence_block_ids=dict(period=[by_ord[818],by_ord[1430]],currency=[by_ord[1450]],
                                              unit=[t['block_id'] for t in tables]),
                source_sha256=sha(source_raw),source_sha256_basis='UTF-8 derived HTML bytes; distinct from original official PDF hash',
                source_local_path=rel(source_file),source_encoding='utf-8',source_url=URL,
                original_source_path=rel(pdf),original_source_sha256=PDF_SHA,source_kind='pdf_derived_selected_html',form_type='10-K',
                source_manifest=dict(local_path=rel(manifest_path),sha256=sha(manifest_path.read_bytes())),
                text_normalization='Paragraphs: fresh pdftotext -layout, blank-line blocks, Unicode whitespace collapsed. Table cells: original PDF words joined with spaces by reviewed row/column geometry; no numeric rewriting.',
                fragment_scope='Selected continuous business description through Automotive, revenue recognition, reporting scope, fiscal/currency policy, two complete revenue tables. Not whole-report coverage.',
                blocks=entries,tables=tables)
    verify_packet(packet,ROOT,company_id=COMPANY,document_id=DOCUMENT,period_end=PERIOD_END)
    packet_path=OUT/'source_packet.json';freeze(packet_path,json_bytes(packet))
    validation=dict(schema_version='nvidia-input-verification-v1',company_id=COMPANY,document_id=DOCUMENT,period_end=PERIOD_END,
                    requested_period_label=packet['requested_period_label'],original_pdf_sha256=PDF_SHA,
                    fresh_pdf_text_matches_frozen_text=True,selected_paragraphs_match_legacy_projection=True,
                    selected_paragraph_count=len(entries)-len(tables),blocks=len(entries),tables=len(tables),
                    physical_cells=sum(len(t['cells']) for t in tables),table_word_counts=word_counts,
                    table_word_assignment='all words in selected regions assigned exactly once',
                    packet_sha256=sha(packet_path.read_bytes()),packet_bytes=packet_path.stat().st_size,
                    skill_sha256=sha((OUT/'skill-v0.4.md').read_bytes()),
                    host_verify_packet='passed',model_calls=0,
                    limitation='Reviewed PDF geometry adapter; not universal automatic PDF parsing, not a blind holdout')
    freeze(OUT/'validation.json',json_bytes(validation))
    print(json.dumps(validation,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
