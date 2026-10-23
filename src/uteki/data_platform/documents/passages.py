"""Flat, source-backed content groups and line locations inside native sections.

Grouping is based on observed layout, not a claim of semantic completeness.
No source text is generated or removed. Every retained non-directory block is
assigned once; an unmarked section stays whole instead of being cut by length.
"""
from collections import defaultdict
from hashlib import sha256
import unicodedata

from .directory import _style, _same_style


def _normalized(text):
    chars, offsets = [], []
    for index, char in enumerate(text):
        for value in unicodedata.normalize('NFKC', char):
            if not value.isspace():
                chars.append(value)
                offsets.append(index)
    return ''.join(chars), offsets


def attach_text_lines(blocks, observations):
    """Align source lines conservatively; absent/ambiguous ranges remain null."""
    pages = defaultdict(list)
    for observation in observations:
        pages[observation['location']['page_number']].append(observation)
    for block in blocks:
        if block['type'] != 'text':
            continue
        cells, seen = [], set()
        for loc in block['locations']:
            x0, y0, x1, y1 = loc['bbox']
            for cell in pages[loc['page_number']]:
                a, b, c, d = cell['location']['bbox']
                key = (cell['text'], loc['page_number'], a, b, c, d)
                if x0 <= (a+c)/2 <= x1 and y0 <= (b+d)/2 <= y1 and key not in seen:
                    cells.append(cell); seen.add(key)
        cells.sort(key=lambda c: (c['location']['page_number'], c['location']['bbox'][1], c['location']['bbox'][0]))
        target, offsets = _normalized(block['text'])
        cursor, lines = 0, []
        for index, cell in enumerate(cells):
            needle, _ = _normalized(cell['text'])
            start = target.find(needle, cursor) if needle else -1
            span = None
            if start >= 0 and target.find(needle, start+1) == -1:
                span = [offsets[start], offsets[start+len(needle)-1]+1]
                cursor = start+len(needle)
            lines.append(dict(line_id=f'line-{index}', text=cell['text'],
                              location=cell['location'], char_range=span))
        block['text_lines'] = lines


def build_passages(blocks, observations, directory):
    headings = {n.get('heading_block_id') for n in directory['nodes']}
    sections = defaultdict(list)
    styles = {b['block_id']:_style(b, observations) for b in blocks if b['type']=='text'}
    for block in sorted(blocks, key=lambda b:b['order']):
        if block['body_selection']['decision']=='exclude' or block['block_id'] in headings:
            continue
        if len(block['directory_node_ids']) == 1:
            sections[block['directory_node_ids'][0]].append(block)
    passages = []
    for node in directory['nodes']:
        members = sections[node['node_id']]
        groups = []
        for index, block in enumerate(members):
            style = styles.get(block['block_id'])
            basis = None
            if block['type']=='text' and 'repeated_pre_anchor_context' not in block.get('issues', []):
                following = members[index+1] if index+1 < len(members) else None
                after = styles.get(following['block_id']) if following else None
                # Whole-block emphasis followed by ordinary prose is a passage
                # lead in every section, independent of Docling heading seeds.
                emphasized = style and style['purity'] >= .95 and (style['weight'] >= 600 or style['italic'])
                if (emphasized and after and not _same_style(style, after)
                    and style['weight'] >= after['weight']
                    and (style['weight'] > after['weight'] or style['italic'] != after['italic'])):
                    basis = 'typographic_lead'
                elif block['role']=='heading':
                    basis = 'parser_heading'
            if not groups or basis:
                groups.append(dict(directory_node_id=node['node_id'],index=len(groups),block_ids=[],
                                   lead_block_id=block['block_id'] if basis else None,
                                   grouping_basis=basis or 'section_content'))
            groups[-1]['block_ids'].append(block['block_id'])
        for group in groups:
            identity = node['node_id']+'\0'+'\0'.join(group['block_ids'])
            group['passage_id'] = 'passage-'+sha256(identity.encode()).hexdigest()[:20]
            passages.append(group)
    return passages
