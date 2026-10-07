"""Read-only source-to-block audit. Structural observations never certify meaning."""
from bisect import bisect_right
from collections import Counter
import hashlib
import re

from lxml import html
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _hidden, _visible_text

VERSION = 'html-tenk-coverage-audit-v1'
SUPPORTED_PARSERS = {'sec-source-blocks-v0.1.11', 'sec-source-blocks-v0.1.12'}


def audit_html_tenk(raw, source, index, blocks):
    """Return full DOM text disposition ledger and disjoint navigation sections.

    Caller supplies explicit frozen source identity. Coverage uses the parser's
    inline visibility/text rules; CSS rendering, image interpretation, reading
    order and financial semantics are deliberately separate unreviewed domains.
    """
    required = ('company_id', 'document_id', 'source_snapshot_id', 'report_period_end',
                'source_url', 'raw_sha256', 'form_type', 'parser_version')
    if any(not isinstance(source.get(k), str) or not source[k].strip() for k in required):
        raise ValueError('Explicit complete source identity required')
    if source['form_type'] != '10-K' or index.get('form_type') != '10-K':
        raise ValueError('Only explicitly selected HTML 10-K supported')
    if source['parser_version'] not in SUPPORTED_PARSERS:
        raise ValueError('Unsupported parser text representation')
    if (index.get('source_snapshot_id'), index.get('parser_version')) != (source['source_snapshot_id'], source['parser_version']):
        raise ValueError('Source/index scope mismatch')
    if hashlib.sha256(raw).hexdigest() != source['raw_sha256']:
        raise ValueError('Original source hash mismatch')
    if not blocks or len({b['block_id'] for b in blocks}) != len(blocks):
        raise ValueError('Nonempty unique blocks required')
    root = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8', recover=True))
    body = root.find('body')
    if body is None:
        raise ValueError('HTML body required')
    tree = root.getroottree()
    elements = [e for e in root.iter() if isinstance(e.tag, str)]
    by_path = {tree.getpath(e): e for e in elements}
    positions = {tree.getpath(e): p for p, e in enumerate(elements)}
    block_at = {}
    for b in blocks:
        if b['dom_path'] not in by_path:
            raise ValueError('Block DOM path does not exist: ' + b['block_id'])
        block_at.setdefault(b['dom_path'], []).append(b)
    block_positions = {b['block_id']: i for i, b in enumerate(blocks)}
    sections = []
    boundaries = []
    for n in index['nodes']:
        if n['kind'] not in ('part', 'item'):
            continue
        if n['start_block_id'] not in block_positions or n['end_block_id'] not in block_positions:
            raise ValueError('Outline references absent block')
        b = blocks[block_positions[n['start_block_id']]]
        boundaries.append((positions[b['dom_path']], n))
    # A Part intro receives its own interval, then each Item. These are source
    # navigation intervals, not inferred semantic topics of everything inside.
    boundaries.sort(key=lambda pair: (pair[0], pair[1]['kind'] == 'item'))
    starts = [-1]
    sections.append({'section_id': 'document-front', 'title': 'Before first legal heading', 'kind': 'front'})
    for pos, n in boundaries:
        if pos == starts[-1]:
            sections[-1] = {'section_id': n['node_id'], 'title': n['title'], 'kind': n['kind']}
        else:
            starts.append(pos)
            sections.append({'section_id': n['node_id'], 'title': n['title'], 'kind': n['kind']})
    for section in sections:
        section.update(block_ids=[], table_ids=[], counts=Counter(), findings=[],
                       independent_semantic_review='not_performed', visual_reading_order_review='not_performed')

    def section_at(element):
        return sections[bisect_right(starts, positions[tree.getpath(element)]) - 1]

    def excluded(element):
        return _hidden(element) or any(str(e.tag).lower() in {'script', 'style', 'noscript'}
                                      for e in (element, *element.iterancestors()))

    ledger = []
    for element in body.iter():
        for value, owner, kind in ((element.text, element, 'text'), (element.tail, element.getparent(), 'tail')):
            if (kind == 'text' and not isinstance(element.tag, str)) or owner is None or not value or not normalize_text(value):
                continue
            text = normalize_text(value)
            section = section_at(owner)
            candidates = [b for e in (owner, *owner.iterancestors()) for b in block_at.get(tree.getpath(e), [])]
            if excluded(owner):
                status = 'excluded_by_inline_visibility_rule'
            elif not candidates:
                status = 'uncovered_visible_text'
            elif not any(text in b['text'] for b in candidates):
                status = 'represented_ancestor_but_text_missing'
            else:
                status = 'structurally_represented'
            section['counts'][status] += 1
            entry = {'dom_path': tree.getpath(element), 'owner_dom_path': tree.getpath(owner), 'text_kind': kind,
                     'text': text, 'status': status, 'section_id': section['section_id'],
                     'block_ids': [b['block_id'] for b in candidates]}
            ledger.append(entry)
            if status in ('uncovered_visible_text', 'represented_ancestor_but_text_missing'):
                section['findings'].append({'code': status, 'dom_path': entry['dom_path'], 'text_kind': kind, 'text': text})
    preserve_breaks = source['parser_version'] == 'sec-source-blocks-v0.1.12'
    for b in blocks:
        element = by_path[b['dom_path']]
        section = section_at(element)
        section['block_ids'].append(b['block_id'])
        expected = normalize_text(element.get('alt', '')) if b['type'] == 'image' else normalize_text(_visible_text(element, preserve_line_breaks=preserve_breaks))
        if expected != b['text']:
            section['findings'].append({'code': 'block_text_mismatch', 'block_id': b['block_id'], 'dom_path': b['dom_path']})
        if b.get('layout_role'):
            section['counts']['layout_classified_blocks_retained'] += 1
        if b['type'] == 'table':
            section['table_ids'].append(b['block_id'])
            section['findings'].append({'code': 'table_semantics_not_reviewed', 'block_id': b['block_id'],
                                       'requires': ['header/value alignment', 'unit scope', 'all applicable note associations']})
        if re.search(r'\b(?:see|refer|included|incorporated)\b.{0,100}\b(?:note|item|part|statement|proxy)\b', b['text'], re.I):
            section['findings'].append({'code': 'cross_reference_candidate_not_resolved', 'block_id': b['block_id']})
    for element in body.iter():
        if not isinstance(element.tag, str) or excluded(element):
            continue
        if element.tag.lower() in ('img', 'svg', 'canvas', 'object', 'iframe'):
            section_at(element)['findings'].append({'code': 'visual_or_embedded_content_not_read',
                'dom_path': tree.getpath(element), 'tag': element.tag,
                'src': element.get('src') or element.get('data'), 'alt': element.get('alt'),
                'block_ids': [b['block_id'] for b in block_at.get(tree.getpath(element), [])]})
    for section in sections:
        bad = {'uncovered_visible_text', 'represented_ancestor_but_text_missing', 'block_text_mismatch'}
        section['structural_text_status'] = 'defects_found' if any(f['code'] in bad for f in section['findings']) else 'covered_under_declared_text_rules'
        section['counts'] = dict(section['counts'])
    order_inversions = [
        {'before_block_id': a['block_id'], 'after_block_id': b['block_id']}
        for a, b in zip(blocks, blocks[1:])
        if positions[a['dom_path']] > positions[b['dom_path']]]
    layout_locations = [
        {'dom_path': tree.getpath(e), 'style': e.get('style'), 'section_id': section_at(e)['section_id'],
         'status': 'computed_layout_not_reviewed_not_a_confirmed_defect'}
        for e in body.iter() if isinstance(e.tag, str) and not excluded(e)
        and re.search(r'(?:position\s*:\s*(?:absolute|fixed)|display\s*:\s*(?:grid|flex)|column-count\s*:|order\s*:|float\s*:)', e.get('style', ''), re.I)]
    totals = Counter(e['status'] for e in ledger)
    findings = Counter(f['code'] for s in sections for f in s['findings'])
    return {'schema_version': VERSION, 'source': {k: source[k] for k in required},
            'status': 'structural_audit_completed_with_explicit_unreviewed_domains',
            'todo03_complete': False,
            'block_dom_order': {'status': 'monotonic' if not order_inversions else 'inversions_found', 'inversions': order_inversions},
            'layout_review_locations': layout_locations,
            'totals': dict(totals), 'finding_counts': dict(findings), 'sections': sections, 'text_ledger': ledger,
            'limits': ['Visibility and text normalization reuse parser rules; no independent computed CSS rendering.',
                       'DOM ancestor containment and equal text do not prove visual reading order or financial correctness.',
                       'All financial tables require unit/note/header semantic review; remote notes are not resolved here.',
                       'Image/embedded bytes are not interpreted; text alternatives are not certified equivalent.',
                       'Legal sections are navigation intervals, not a claim about every enclosed block topic.']}
