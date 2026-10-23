"""Native PDF navigation with source-matched boundaries; no inferred child nodes.

Original observations remain in the parser artifact. Unmatched outlines remain
visible in issues; typography is used only for local title matching here.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from difflib import SequenceMatcher
from statistics import median
import re
import unicodedata

VERSION = 'pdf-native-passages-1'


def _key(text):
    return ''.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def _matches_title(text, title):
    if _key(text) == _key(title):
        return True
    # Layout models can merge a title and a parenthesized subtitle/units. Match
    # only the entire remaining title, never arbitrary prefixes or substrings.
    without_subtitle = re.sub(r'\s*\([^()]*\)\s*$', '', text)
    return without_subtitle != text and _key(without_subtitle) == _key(title)


def make_code(title):
    text = unicodedata.normalize('NFKC', title).strip()
    # A source numbering prefix remains in title; the machine segment is readable.
    text = re.sub(r'^item\s+\d+[a-z]?\s*[.:\-]?\s+', '', text, flags=re.I)
    return re.sub(r'[^\w]+', '_', text, flags=re.UNICODE).strip('_') or 'Section'


def _point(block):
    loc = block['locations'][0]
    return loc['page_number'], loc['bbox'][1]


def _line_match(block, title, observations):
    """Locate a whole source line inside a merged heading, without slicing text."""
    if block['role'] != 'heading':
        return False
    for loc in block['locations']:
        x0, y0, x1, y1 = loc['bbox']
        for cell in observations:
            pos = cell['location']
            a, b, c, d = pos['bbox']
            if (pos['page_number']==loc['page_number'] and x0 <= (a+c)/2 <= x1
                    and y0 <= (b+d)/2 <= y1 and _key(cell['text'])==_key(title)):
                return True
    return False


def _contents_table(block, native_nodes, previous, context_title=''):
    """Require a source contents/index heading plus multiple outline row matches."""
    if block['type']!='table' or not block.get('table'):
        return False
    label=r'\b(table of contents|index to|index of)\b'
    source_context=bool(re.search(label,context_title,re.I))
    previous_heading=(previous is not None and previous['type']=='text' and previous['role']=='heading'
                      and _point(previous)[0]==_point(block)[0] and re.search(label,previous['text'],re.I))
    if not source_context and not previous_heading:
        return False
    rows = {}
    for cell in block['table']['cells']:
        rows.setdefault(cell['row'],[]).append(cell)
    matches = set()
    titles = {_key(n['title']) for n in native_nodes if len(_key(n['title']))>=10}
    for cells in rows.values():
        cells.sort(key=lambda c:c['column'])
        if len(cells)<2 or not re.fullmatch(r'\d{1,4}',cells[-1]['text'].strip()):
            continue
        text=_key(' '.join(c['text'] for c in cells[:-1]))
        matches.update(title for title in titles if title==text)
    return len(matches)>=3


def _style(block, observations):
    cells = []
    for loc in block['locations']:
        x0, y0, x1, y1 = loc['bbox']
        for cell in observations:
            pos = cell['location']
            if pos['page_number'] != loc['page_number'] or not cell.get('font_name'):
                continue
            a, b, c, d = pos['bbox']
            if x0 <= (a+c)/2 <= x1 and y0 <= (b+d)/2 <= y1:
                cells.append(cell)
    if not cells:
        return None
    fonts = Counter()
    for cell in cells:
        fonts[cell['font_name']] += len(cell['text'])
    font, count = fonts.most_common(1)[0]
    dominant = [c for c in cells if c['font_name'] == font]
    return dict(font=font, purity=count/max(1, sum(fonts.values())),
                height=median(c['location']['bbox'][3]-c['location']['bbox'][1] for c in dominant),
                left=min(c['location']['bbox'][0] for c in dominant),
                weight=max(c.get('font_weight', 400) for c in dominant),
                italic=any(c.get('font_italic', False) for c in dominant))


def _same_style(a, b):
    return bool(a and b and a['font'] == b['font'] and
                abs(a['height']-b['height']) <= max(a['height'], b['height'])*0.08)


def build_sections(blocks, observations, native_directory):
    """Return a new directory and block assignments; preserve all source blocks."""
    blocks = deepcopy(blocks)
    raw_nodes = native_directory['nodes']
    raw_by_id = {n['node_id']: n for n in raw_nodes}
    issues = list(native_directory['issues'])
    by_id = {b['block_id']: b for b in blocks}
    styles = {b['block_id']: _style(b, observations) for b in blocks if b['type'] == 'text'}
    anchors, selected = {}, {}
    pages = {loc['page_number'] for b in blocks for loc in b['locations']}
    for block in blocks:
        role = block['role']
        exclude = role in ('header', 'footer')
        block['body_selection'] = dict(decision='exclude' if exclude else 'keep',
            reason='parser_'+role if exclude else 'source_content', policy_version=VERSION)
        block['directory_node_ids'] = []
        block['directory_assignment'] = 'outside_directory'
    for node in raw_nodes:
        if not node['locations']:
            continue
        dest = node['locations'][0]
        if dest['page_number'] not in pages:
            continue
        # Source bookmarks remain available even when no body heading matches.
        # A destination-only boundary is explicit and never labelled a text match.
        current = node
        while current['node_id'] not in selected:
            selected[current['node_id']] = deepcopy(current)
            if current['parent_id'] is None:
                break
            current = raw_by_id[current['parent_id']]
        selected[node['node_id']]['hierarchy_basis']='bookmark_destination_only'
        eligible = [b for b in blocks if b['type']=='text' and b['role'] not in ('caption','footnote')
                    and _point(b)[0] == dest['page_number']]
        candidates = [b for b in eligible if _matches_title(b['text'], node['title'])
                      or _line_match(b,node['title'],observations)]
        body_candidates=[b for b in candidates if b['role'] not in ('header','footer')]
        if body_candidates:
            candidates=body_candidates
        basis='bookmark_title_and_page'
        if not candidates and dest.get('y') is not None:
            # Same mechanism as Docling's title similarity, with conservative
            # page/position/uniqueness constraints; source spelling is retained.
            scored=[]
            for b in eligible:
                style=styles.get(b['block_id'])
                if b['role']!='heading' or not style or abs(_point(b)[1]-dest['y'])>3*style['height']:
                    continue
                score=SequenceMatcher(None,_key(b['text']),_key(node['title']),autojunk=False).ratio()
                if score>=.97:scored.append((score,b))
            scored.sort(key=lambda pair:pair[0],reverse=True)
            if scored and (len(scored)==1 or scored[0][0]-scored[1][0]>.03):
                candidates=[scored[0][1]];basis='bookmark_similar_title_and_position'
        if len(candidates) > 1 and dest.get('y') is not None:
            candidates.sort(key=lambda b: abs(_point(b)[1]-dest['y']))
            if abs(_point(candidates[0])[1]-dest['y'])+2 < abs(_point(candidates[1])[1]-dest['y']):
                candidates = candidates[:1]
        if len(candidates) != 1:
            issues.append('outline_heading_unmatched:'+node['node_id'])
            continue
        block = candidates[0]
        if block['block_id'] in anchors:
            issues.append('outline_heading_conflict:'+node['node_id'])
            continue
        anchors[block['block_id']] = node['node_id']
        selected[node['node_id']].update(heading_block_id=block['block_id'],
            locations=block['locations'], hierarchy_basis=basis)
        if block['role'] in ('header','footer'):
            block['issues']=[*block.get('issues',[]),'source_role:'+block['role']]
            block['body_selection'].update(decision='keep',reason='source_bookmark_heading')
            block['role']='heading'

    # Restrict content by source regions, not only by titles the layout model found.
    events=[]
    for node in selected.values():
        if not node['locations'] or node['locations'][0]['page_number'] not in pages:
            continue
        loc=node['locations'][0]
        point=_point(by_id[node['heading_block_id']]) if node.get('heading_block_id') else (loc['page_number'],loc.get('y') or 0.)
        depth=0;parent=node['parent_id']
        while parent is not None:depth+=1;parent=selected[parent]['parent_id']
        events.append((point,depth,node['order'],node['node_id']))
    events.sort()
    previous=None
    for block in blocks:
        if block['body_selection']['decision']=='exclude':continue
        eligible=[event for event in events if event[0]<=_point(block)]
        context_title=selected[eligible[-1][3]]['title'] if eligible else ''
        if _contents_table(block,raw_nodes,previous,context_title):
            block['body_selection'].update(decision='exclude',reason='source_contents_table_with_outline_rows')
        previous=block

    # Repeated display context immediately preceding anchored titles (e.g. a
    # report's masthead) is retained with that section, not made its own branch.
    preambles = {}
    for i, block in enumerate(blocks[:-1]):
        following = blocks[i+1]
        if (block['role']=='heading' and block['block_id'] not in anchors
                and following['block_id'] in anchors and _point(block)[0]==_point(following)[0]):
            preambles[block['block_id']] = anchors[following['block_id']]
    for bid in list(preambles):
        block = by_id[bid]
        peers = [by_id[other] for other in preambles if other != bid
                 and _key(by_id[other]['text']) == _key(block['text'])
                 and _point(by_id[other])[0] != _point(block)[0]
                 and _same_style(styles.get(other), styles.get(bid))
                 and abs(_point(by_id[other])[1]-_point(block)[1]) < styles[bid]['height']]
        if not peers:
            del preambles[bid]

    # The native outline alone defines navigation. Typography belongs to
    # passage grouping, never to directory membership or parent inference.
    for block in blocks:
        bid = block['block_id']
        if block['body_selection']['decision']=='exclude':
            continue
        eligible=[event for event in events if event[0]<=_point(block)]
        scope=eligible[-1][3] if eligible else None
        if bid in anchors:
            scope=anchors[bid]
            block['role']='heading'
        elif bid in preambles:
            scope=preambles[bid]
            block['role']='body'
            block['issues']=[*block.get('issues',[]),'repeated_pre_anchor_context']
        if scope is not None:
            block['directory_node_ids']=[scope]
            block['directory_assignment']='assigned'
        elif not selected:
            block['directory_assignment']='unresolved'

    # Stable, unique code segments. The original title and source ID are retained.
    codes = set()
    nodes = []
    for order, node in enumerate(selected.values()):
        node['order'] = order
        code = make_code(node['title'])
        if (node['parent_id'], code) in codes:
            code += '__'+sha256(node['node_id'].encode()).hexdigest()[:8]
        node['code'] = code
        codes.add((node['parent_id'], code))
        nodes.append(node)
    # Preserve the source outline order, including original parents and aliases.
    nodes.sort(key=lambda node: raw_by_id[node['node_id']]['order'])
    for order, node in enumerate(nodes):
        node['order']=order
    return dict(has_source_directory=native_directory['has_source_directory'],
                status='partial' if issues else 'complete', nodes=nodes,
                issues=list(dict.fromkeys(issues))), blocks
