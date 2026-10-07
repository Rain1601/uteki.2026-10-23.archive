"""Deterministic reading overlay; never rewrites source blocks or legal nodes."""
import re

VERSION = 'reading-groups-v0.3'


def is_list_item(block):
    # Legacy composite containers can start with a bullet but contain whole sections.
    if sum(block['text'].count(mark) for mark in ('•', '◦')) > 1:
        return False
    return block['type'] == 'list_item' or (
        block['type'] == 'paragraph' and block['text'].lstrip().startswith(('•', '◦')))


def _table_note_links(note, source):
    """Recognize adjacent note rows without assigning their financial meaning.

    Require an isolated marker cell followed by a prose definition cell. Numeric
    and symbol markers must also occur as whole cells in the source table: this
    intentionally leaves inline/superscript and remote-note cases unresolved.
    """
    if note['type'] != 'table' or note.get('layout_role'):
        return []
    rows = {}
    for cell in (note.get('table') or {}).get('cells', []):
        if cell.get('text', '').strip():
            rows.setdefault(cell['row'], []).append(cell)
    if not rows:
        return []
    source_cells = (source.get('table') or {}).get('cells', [])
    links = []
    for cells in rows.values():
        cells = sorted(cells, key=lambda c: c['column'])
        if len(cells) != 2:
            return []
        marker_cell, definition = cells
        marker = marker_cell['text'].strip()
        if not re.fullmatch(r'(?:\(\d+\)|\[\d+\]|[*†‡]+|Note:)', marker):
            return []
        # Pure values or empty cells are not explanatory prose.
        if not re.search(r'[A-Za-z]', definition['text']):
            return []
        matches = [c for c in source_cells if c.get('text', '').strip() == marker]
        if marker != 'Note:' and not matches:
            return []
        def location(cell):
            return {k: cell[k] for k in ('row', 'column', 'rowspan', 'colspan') if k in cell}
        links.append({
            'note_block_id': note['block_id'], 'marker': marker,
            'marker_cell': location(marker_cell), 'definition_cell': location(definition),
            'source_marker_cells': [location(c) for c in matches],
            'association_basis': 'adjacent_explicit_note' if marker == 'Note:' else 'adjacent_matching_marker',
            'semantic_applicability': 'not_inferred',
        })
    return links


def build_reading_groups(blocks, nodes):
    boundaries = {n['start_block_id'] for n in nodes if n['kind'] in ('part', 'item')}
    groups = []
    i = 0
    while i < len(blocks):
        if not is_list_item(blocks[i]):
            i += 1
            continue
        start = i
        end = i + 1
        while end < len(blocks):
            b = blocks[end]
            if b['block_id'] in boundaries:
                break
            if is_list_item(b):
                end += 1
                continue
            # A page footer/header is not a semantic list boundary.
            if b.get('layout_role') or b['type'] == 'page_marker':
                probe = end
                while probe < len(blocks) and (blocks[probe].get('layout_role') or blocks[probe]['type'] == 'page_marker'):
                    if blocks[probe]['block_id'] in boundaries:
                        break
                    probe += 1
                if probe < len(blocks) and blocks[probe]['block_id'] not in boundaries and is_list_item(blocks[probe]):
                    end = probe + 1
                    continue
            break
        if start and blocks[start]['block_id'] not in boundaries:
            prior = start - 1
            while prior >= 0 and (blocks[prior].get('layout_role') or blocks[prior]['type'] == 'page_marker') and blocks[prior]['block_id'] not in boundaries:
                prior -= 1
            prev = blocks[prior] if prior >= 0 else {}
            if prev.get('type') == 'paragraph' and not is_list_item(prev) and prev['text'].rstrip().endswith((':', '：')):
                start = prior
                if start and blocks[start]['block_id'] not in boundaries and blocks[start - 1]['type'] == 'heading_candidate':
                    start -= 1
        selected = blocks[start:end]
        item_nodes = []
        parent = None
        for b in selected:
            if not is_list_item(b):
                continue
            child = b['text'].lstrip().startswith('◦')
            item_nodes.append({'block_id': b['block_id'], 'parent_id': parent if child else None})
            if not child:
                parent = b['block_id']
        groups.append({'group_id': 'list-' + selected[0]['block_id'], 'version': VERSION,
                       'kind': 'list_context', 'block_ids': [b['block_id'] for b in selected],
                       'item_ids': [b['block_id'] for b in selected if is_list_item(b)],
                       'items': item_nodes,
                       'rule': 'consecutive bullet items + colon introduction + adjacent heading'})
        i = end
    # Attach nearby table context conservatively; do not invent remote footnote links.
    attached_notes = set()
    for i, block in enumerate(blocks):
        if block['type'] != 'table' or block.get('layout_role') or block['block_id'] in attached_notes:
            continue
        start = i
        for _ in range(4):
            if start == 0 or blocks[start]['block_id'] in boundaries:
                break
            prev = blocks[start - 1]
            if prev.get('layout_role') or prev['type'] == 'page_marker':
                start -= 1
            elif prev['type'] == 'heading_candidate' or (prev['type'] == 'paragraph' and
                    (re.search(r'\b(table|millions|thousands)\b', prev['text'], re.I) or prev['text'].rstrip().endswith(':'))):
                start -= 1
            else:
                break
        end = i + 1
        note_links = []
        while end < len(blocks) and blocks[end]['block_id'] not in boundaries:
            b = blocks[end]
            if b['type'] == 'paragraph' and re.match(r'^\s*(\(\d+\)|\[\d+\]|\*|Note:)', b['text']):
                end += 1
            elif links := _table_note_links(b, block):
                note_links.extend(links)
                attached_notes.add(b['block_id'])
                end += 1
            else:
                break
        groups.append({'group_id': 'table-' + block['block_id'], 'version': VERSION,
                       'kind': 'table_context', 'block_ids': [b['block_id'] for b in blocks[start:end]],
                       'item_ids': [], 'table_id': block['block_id'], 'note_links': note_links,
                       'rule': 'nearby heading/unit/introduction and immediately following marked paragraphs or structurally marked note tables; remote notes and semantic applicability not resolved'})
    return groups
