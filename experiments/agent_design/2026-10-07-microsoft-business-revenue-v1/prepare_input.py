"""Freeze explicitly selected original Microsoft FY2025 HTML evidence. No model calls.

This experiment adapter selects source sections, never previously extracted
answers. Geometry is read from original DOM; labels and values are not repaired.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from lxml import html
from uteki.agents.business_map.product_run import verify_packet

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'input'
CORPUS = ROOT / 'data/company_workspace/extraction_ab_v1/corpus/msft'
SOURCE = CORPUS / 'originals/msft-2025-10k.html'
INDEX = CORPUS / 'dataset/indexes/msft-2025-10k/blocks.jsonl'
COMPANY, DOCUMENT, PERIOD = 'sec-0000789019', 'msft-2025-10k', '2025-06-30'
SOURCE_SHA = '0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6'
INDEX_SHA = 'f538b960f9d3d893e2b7288b4c228409c0f7ce6a6cecd7c47cf206c91546a9d7'
URL = 'https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm'
# Caller-selected complete sections; section names are navigation metadata.
SECTIONS = [([6, 8], ['Form 10-K', 'Cover']), (range(39, 50), ['Form 10-K', 'Item 1. Business', 'General / What We Offer']),
    (range(85, 111), ['Form 10-K', 'Item 1. Business', 'Operating Segments / Productivity and Business Processes']),
    (range(117, 133), ['Form 10-K', 'Item 1. Business', 'Intelligent Cloud']),
    (range(143, 181), ['Form 10-K', 'Item 1. Business', 'More Personal Computing']),
    (range(208, 246), ['Form 10-K', 'Item 1. Business', 'Distribution / Licensing Options']),
    ([781], ['Form 10-K', 'Item 8. Financial Statements', 'Income Statements']),
    (range(811, 819), ['Form 10-K', 'Note 1. Accounting Policies', 'Reporting scope / Recast']),
    (range(823, 839), ['Form 10-K', 'Note 1. Accounting Policies', 'Revenue']),
    (range(1180, 1213), ['Form 10-K', 'Note 18. Segment Information and Geographic Data', 'Segments']),
    (range(1216, 1228), ['Form 10-K', 'Note 18. Segment Information and Geographic Data', 'Revenue tables and notes'])]
FINANCIAL_TABLES = [781, 1217, 1219, 1226]
UNIT_DOM = '/html/body/div[1]/ix:header/ix:resources/xbrli:unit[5]'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
norm = lambda el: ' '.join(''.join(el.itertext()).split())
rel = lambda path: str(path.relative_to(ROOT))


def freeze(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('frozen_output_changed_use_new_version: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as out:
            out.write(raw)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def main():
    raw = SOURCE.read_bytes()
    assert sha(raw) == SOURCE_SHA and sha(INDEX.read_bytes()) == INDEX_SHA, 'frozen_source_or_index_changed'
    dom = html.fromstring(raw); tree = dom.getroottree()
    by_path = {tree.getpath(el): el for el in dom.iter()}
    indexed = [json.loads(line) for line in INDEX.read_text().splitlines()]
    by_ordinal = {b['ordinal']: b for b in indexed}
    sections = {ordinal: path for ordinals, path in SECTIONS for ordinal in ordinals}
    blocks, excluded = [], []
    for ordinal in sorted(sections):
        source = by_ordinal[ordinal]
        el = by_path[source['dom_path']]
        text = norm(el)
        assert text == source['text'] and sha(text.encode()) == source['text_hash'], 'index_original_mismatch'
        reason = ('printed_page_marker' if source['type'] == 'page_marker' else
                  'repeated_running_header' if text in ('PART I', 'PART II', 'Item 1', 'Item 8') else
                  'isolated_bullet_without_content' if text in ('•', '●', '▪') else None)
        if reason:
            excluded.append({'ordinal': ordinal, 'block_id': source['block_id'], 'text': text, 'reason': reason})
            continue
        blocks.append({'id': source['block_id'], 'ordinal': ordinal, 'type': source['type'], 'text': text,
                       'text_sha256': source['text_hash'], 'source_dom_path': source['dom_path'],
                       'section_path': sections[ordinal], 'reported_page': source['reported_page']})
    unit = by_path[UNIT_DOM]
    assert unit.get('id') == 'U_USD' and norm(unit) == 'iso4217:USD', 'explicit_xbrl_currency_unit_missing'
    currency_block = {'id': 'source-unit-U_USD', 'ordinal': max(by_ordinal) + 1,
        'type': 'source_unit_metadata', 'text': norm(unit), 'text_sha256': sha(norm(unit).encode()),
        'source_dom_path': UNIT_DOM, 'section_path': ['Form 10-K', 'Inline XBRL resources', 'Currency unit U_USD'],
        'ordinal_basis': 'Original index maximum plus one; metadata node was not included in the original reading index.'}
    blocks.append(currency_block)
    tables, xbrl_evidence = [], []
    for ordinal in FINANCIAL_TABLES:
        source = by_ordinal[ordinal]; table = by_path[source['dom_path']]
        rows, cells, occupied = [], [], set()
        for ri, row in enumerate(table.xpath('./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr')):
            ci = 0; row_ids = []
            for element in row.xpath('./td | ./th'):
                while (ri, ci) in occupied:
                    ci += 1
                rs, cs = int(element.get('rowspan', '1')), int(element.get('colspan', '1'))
                assert rs > 0 and cs > 0
                for rr in range(ri, ri + rs):
                    for cc in range(ci, ci + cs):
                        assert (rr, cc) not in occupied, 'table_span_overlap'
                        occupied.add((rr, cc))
                text = norm(element); cid = f'cell-{source["block_id"]}-r{ri:03}-c{ci:03}'
                cells.append({'id': cid, 'text': text, 'text_sha256': sha(text.encode()), 'source_dom_path': tree.getpath(element),
                              'row_index': ri, 'column_index': ci, 'rowspan': rs, 'colspan': cs})
                for fact in element.iter():
                    if fact.get('unitref'):
                        xbrl_evidence.append({'cell_id': cid, 'fact_dom_path': tree.getpath(fact), 'name': fact.get('name'),
                                              'unitref': fact.get('unitref'), 'scale': fact.get('scale'), 'text': norm(fact)})
                row_ids.append(cid); ci += cs
            rows.append({'row_index': ri, 'cell_ids': row_ids})
        # Cross-check independent index geometry; retain blanks, symbols and spans.
        old = source['table']['cells']
        assert len(cells) == len(old)
        for cell, indexed_cell in zip(cells, old):
            assert (cell['text'], cell['row_index'], cell['column_index'], cell['rowspan'], cell['colspan']) == (
                indexed_cell['text'], indexed_cell['row'], indexed_cell['column'], indexed_cell['rowspan'], indexed_cell['colspan'])
        tables.append({'id': 'table-' + source['block_id'], 'block_id': source['block_id'],
                       'source_dom_path': source['dom_path'], 'rows': rows, 'cells': cells})
    manifest = {'schema_version': 'official-html-source-manifest-v1', 'company_id': COMPANY, 'document_id': DOCUMENT,
        'period_end': PERIOD, 'source_url': URL, 'content_sha256': SOURCE_SHA, 'source_local_path': rel(SOURCE),
        'content_kind': 'official_sec_html', 'source_bytes': len(raw), 'network_refetch_performed': False,
        'index_local_path': rel(INDEX), 'index_sha256': INDEX_SHA,
        'acquisition_local_path': rel(CORPUS / 'acquisition.json'), 'acquisition_sha256': sha((CORPUS / 'acquisition.json').read_bytes())}
    manifest_path = OUT / 'source_manifest.json'; freeze(manifest_path, json_bytes(manifest))
    packet = {'schema_version': 'source-packet-v1', 'company_id': COMPANY, 'document_id': DOCUMENT, 'period_end': PERIOD,
        'requested_period_label': '2025', 'financial_currency': 'USD', 'financial_unit': 'million',
        'source_local_path': rel(SOURCE), 'source_sha256': SOURCE_SHA, 'source_url': URL,
        'source_kind': 'official_sec_html', 'form_type': '10-K',
        'source_manifest': {'local_path': rel(manifest_path), 'sha256': sha(manifest_path.read_bytes())},
        'scope_evidence_block_ids': {'company': [by_ordinal[8]['block_id']], 'period': [by_ordinal[6]['block_id']],
            'currency': [currency_block['id']], 'unit': [by_ordinal[o]['block_id'] for o in FINANCIAL_TABLES]},
        'text_normalization': 'Original DOM itertext; Unicode whitespace collapsed. No wording, values or table geometry rewritten.',
        'fragment_scope': 'Explicit complete business, distribution/licensing and selected revenue-policy sections; four complete financial tables and adjacent notes. Not whole-report coverage. Repeated segment lists retained.',
        'blocks': blocks, 'tables': tables}
    verify_packet(packet, ROOT, company_id=COMPANY, document_id=DOCUMENT, period_end=PERIOD)
    freeze(OUT / 'source_packet.json', json_bytes(packet))
    audit = {'schema_version': 'source-selection-verification-v1', 'scope': {'company_id': COMPANY, 'document_id': DOCUMENT, 'period_end': PERIOD},
        'source_sha256': SOURCE_SHA, 'index_sha256': INDEX_SHA, 'packet_sha256': sha((OUT / 'source_packet.json').read_bytes()),
        'packet_bytes': (OUT / 'source_packet.json').stat().st_size, 'source_selection': [{'ordinals': list(ordinals), 'section_path': path} for ordinals,path in SECTIONS],
        'excluded': excluded, 'blocks': len(blocks), 'tables': [{'id': t['id'], 'rows': len(t['rows']), 'physical_cells': len(t['cells'])} for t in tables],
        'physical_cells': sum(len(t['cells']) for t in tables), 'complete_geometry_matches_original_index': True,
        'scope_and_source_dom_validation': 'passed', 'xbrl_metadata_block': currency_block['id'],
        'financial_fact_unit_evidence': xbrl_evidence, 'expected_answers_used': False, 'model_calls': 0,
        'selection_script_sha256': sha(Path(__file__).read_bytes()),
        'limits': ['Source-bound experiment adapter, not universal section discovery.', 'No company graph, target classification, expected chart count or expected financial total loaded as model input.', 'Printed-page/index diagnostics outside the selected sections remain unreviewed.']}
    freeze(OUT / 'selection-verification.json', json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('packet_sha256','packet_bytes','blocks','physical_cells','tables')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
