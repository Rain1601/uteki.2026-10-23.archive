"""Deterministic reading overlay; never rewrites source blocks or legal nodes."""
import re

VERSION = 'reading-groups-v0.4'


def is_list_item(block):
    # Legacy composite containers can start with a bullet but contain whole sections.
    if sum(block['text'].count(mark) for mark in ('•', '◦')) > 1:
        return False
    return block['type'] == 'list_item' or (
        block['type'] == 'paragraph' and block['text'].lstrip().startswith(('•', '◦')))


def _dom_parts(block):
    path = block.get('dom_path')
    if not isinstance(path, str) or not path.startswith('/'):
        return ()
    return tuple(part for part in path.split('/') if part)


def _specific_container(parts):
    # A whole document/body is not evidence that neighboring text belongs together.
    return len(parts) >= 3 and parts[-1].split('[', 1)[0].lower() not in {'html', 'body'}


def _split_bullet_end(blocks, start, boundaries):
    """Recognize marker + prose siblings inside one original DOM item container."""
    marker = blocks[start]
    if marker['text'].strip() not in {'•', '◦'}:
        return start + 1
    path = _dom_parts(marker)
    parent = path[:-1]
    if not _specific_container(parent):
        return start + 1
    end = start + 1
    while end < len(blocks):
        block = blocks[end]
        body_path = _dom_parts(block)
        if (block['block_id'] in boundaries or block.get('layout_role')
                or block['type'] not in {'paragraph', 'other', 'heading_candidate'} or is_list_item(block)
                or len(body_path) <= len(parent) or body_path[:len(parent)] != parent):
            break
        end += 1
    return end


def _split_table_note(blocks, start, source, boundaries):
    """Link adjacent separately parsed marker/prose using DOM and a table marker.

    This is a reading relation only, not a financial applicability judgment.
    An arbitrary next paragraph or an unmatched exhibit marker is not a footnote.
    """
    if start + 1 >= len(blocks):
        return None
    marker_block, definition = blocks[start:start + 2]
    marker = marker_block['text'].strip()
    if (marker_block['type'] not in {'other', 'paragraph'}
            or definition['type'] not in {'other', 'paragraph'}
            or marker_block.get('layout_role') or definition.get('layout_role')
            or definition['block_id'] in boundaries
            or not re.fullmatch(r'(?:\((?:[A-Za-z]|\d+)\)|\[(?:[A-Za-z]|\d+)\]|[*†‡]+)', marker)
            or not re.search(r'[A-Za-z]', definition['text']) or is_list_item(definition)):
        return None
    source_parent = _dom_parts(source)[:-1]
    marker_parent = _dom_parts(marker_block)[:-1]
    definition_parent = _dom_parts(definition)[:-1]
    if (not _specific_container(source_parent) or not _specific_container(marker_parent)
            or marker_parent != definition_parent
            or not (marker_parent == source_parent or marker_parent[:-1] == source_parent)):
        return None
    cells = (source.get('table') or {}).get('cells', [])
    if marker.startswith(('(', '[')):
        matches = [cell for cell in cells if marker in cell.get('text', '')]
    else:
        # Do not turn an exhibit such as *10.28 or a different symbol into a match.
        pattern = r'(?<![\w*†‡])' + re.escape(marker) + r'(?![\w*†‡])'
        matches = [cell for cell in cells if re.search(pattern, cell.get('text', ''))]
    if not matches:
        return None
    return {'note_block_id': marker_block['block_id'], 'marker_block_id': marker_block['block_id'],
        'definition_block_id': definition['block_id'], 'marker': marker,
        'source_marker_cells': [{k: cell[k] for k in ('row', 'column', 'rowspan', 'colspan') if k in cell}
                                for cell in matches],
        'association_basis': 'adjacent_split_marker_same_dom_container',
        'semantic_applicability': 'not_inferred'}


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
        end = _split_bullet_end(blocks, i, boundaries)
        while end < len(blocks):
            b = blocks[end]
            if b['block_id'] in boundaries:
                break
            if is_list_item(b):
                end = _split_bullet_end(blocks, end, boundaries)
                continue
            # A page footer/header is not a semantic list boundary.
            if b.get('layout_role') or b['type'] == 'page_marker':
                probe = end
                while probe < len(blocks) and (blocks[probe].get('layout_role') or blocks[probe]['type'] == 'page_marker'):
                    if blocks[probe]['block_id'] in boundaries:
                        break
                    probe += 1
                if probe < len(blocks) and blocks[probe]['block_id'] not in boundaries and is_list_item(blocks[probe]):
                    end = _split_bullet_end(blocks, probe, boundaries)
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
        for pos in range(start, end):
            b = blocks[pos]
            if not is_list_item(b):
                continue
            child = b['text'].lstrip().startswith('◦')
            item = {'block_id': b['block_id'], 'parent_id': parent if child else None}
            split_end = _split_bullet_end(blocks, pos, boundaries)
            if split_end > pos + 1:
                item.update(content_block_ids=[body['block_id'] for body in blocks[pos + 1:split_end]],
                            association_basis='split_bullet_same_dom_container')
            item_nodes.append(item)
            if not child:
                parent = b['block_id']
        groups.append({'group_id': 'list-' + selected[0]['block_id'], 'version': VERSION,
                       'kind': 'list_context', 'block_ids': [b['block_id'] for b in selected],
                       'item_ids': [b['block_id'] for b in selected if is_list_item(b)],
                       'items': item_nodes,
                       'rule': 'consecutive bullet items including DOM-linked split marker/body + colon introduction + adjacent heading'})
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
            if link := _split_table_note(blocks, end, block, boundaries):
                note_links.append(link)
                end += 2
            elif b['type'] == 'paragraph' and re.match(r'^\s*(\(\d+\)|\[\d+\]|\*|Note:)', b['text']):
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
                       'rule': 'nearby heading/unit/introduction and immediately following marked paragraphs, DOM-linked split notes or structurally marked note tables; remote notes and semantic applicability not resolved'})
    return groups
