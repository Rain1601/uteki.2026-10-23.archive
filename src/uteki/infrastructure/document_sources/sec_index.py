from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import replace
from urllib.parse import urljoin

from lxml import etree, html

from uteki.domain.documents import (
    AssetReference,
    DocumentIndex,
    DocumentNode,
    IndexDiagnostic,
    ParsedDocument,
    SourceAnchor,
    SourceBlock,
    TableCell,
    TableStructure,
    TocEntry,
)
from uteki.infrastructure.document_sources.sec import normalize_text, text_hash


SCHEMA_VERSION = "document-index-v0.1"
PARSER_VERSION = "sec-source-blocks-v0.1.1"
SUPPORTED_PARSER_VERSIONS = frozenset({
    'sec-source-blocks-v0.1.1', 'sec-source-blocks-v0.1.2-quarterly',
    'sec-source-blocks-v0.1.3', 'sec-source-blocks-v0.1.3-quarterly',
    'sec-source-blocks-v0.1.4-quarterly', 'sec-source-blocks-v0.1.5',
    'sec-source-blocks-v0.1.6', 'sec-source-blocks-v0.1.7', 'sec-source-blocks-v0.1.8',
    'sec-source-blocks-v0.1.9', 'sec-source-blocks-v0.1.10', 'sec-source-blocks-v0.1.11',
    'sec-source-blocks-v0.1.12', 'sec-source-blocks-v0.1.13',
})
_CONTENT_CELL_TOC_PARSERS = frozenset({'sec-source-blocks-v0.1.13'})
_LINE_BREAK_PARSERS = frozenset({'sec-source-blocks-v0.1.12'}) | _CONTENT_CELL_TOC_PARSERS
_INHERITED_PAGE_PARSERS = frozenset({'sec-source-blocks-v0.1.11'}) | _LINE_BREAK_PARSERS
_TABLE_ITEM_PARSERS = frozenset({'sec-source-blocks-v0.1.10'}) | _INHERITED_PAGE_PARSERS
NAVIGATION_PARSERS = frozenset({'sec-source-blocks-v0.1.9'}) | _TABLE_ITEM_PARSERS
CONTAINMENT_PARSERS = frozenset({'sec-source-blocks-v0.1.8'}) | NAVIGATION_PARSERS
_NEAREST_TABLE_PARSERS = frozenset({'sec-source-blocks-v0.1.7'}) | CONTAINMENT_PARSERS
_VISIBLE_PARSERS = frozenset({'sec-source-blocks-v0.1.6'}) | _NEAREST_TABLE_PARSERS
_PART_RE = re.compile(r"^PART\s+([IVX]+)(?:[.\s—–:-]+(?:FINANCIAL INFORMATION|OTHER INFORMATION))?\.?$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^ITEM\s+(\d+[A-Z]?)\.?\s*(.*)$", re.IGNORECASE)
_STRUCTURAL_ANCHOR_RE = re.compile(r"^i[a-f0-9]{16,}_\d+$", re.IGNORECASE)
_STYLE_KEYS = (
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "line-height",
    "margin-top",
    "padding-left",
    "text-align",
    "text-indent",
)


def _tag(element: etree._Element) -> str:
    return str(element.tag).lower() if isinstance(element.tag, str) else ""


def _hidden(element):
    for node in (element, *element.iterancestors()):
        tag = _tag(node)
        if tag == 'ix:hidden' or 'hidden' in node.attrib or re.search(
                r'(?:^|;)\s*display\s*:\s*none\s*(?:!important\s*)?(?:;|$)',
                node.get('style', ''), re.I):
            return True
    return False


def _visible_text(element, *, preserve_line_breaks=False):
    """Read visible text without removing DOM nodes or changing source paths."""
    if _hidden(element) or _tag(element) in {'script', 'style', 'noscript'}:
        return ''
    if preserve_line_breaks and _tag(element) == 'br':
        # A visible HTML line break is a word boundary, including in table
        # headers and notes. Adjacent inline markup must still concatenate.
        return '\n'
    pieces = [element.text or '']
    for child in element:
        if _tag(child):
            pieces.append(_visible_text(child, preserve_line_breaks=preserve_line_breaks))
        pieces.append(child.tail or '')
    return ''.join(pieces)


def _style_values(element: etree._Element) -> tuple[tuple[str, str], ...]:
    values: dict[str, str] = {}
    styled = [element, *element.xpath(".//*[@style]")[:3]]
    for candidate in styled:
        for declaration in (candidate.get("style") or "").split(";"):
            if ":" not in declaration:
                continue
            key, value = (part.strip().lower() for part in declaration.split(":", 1))
            if key in _STYLE_KEYS and value and key not in values:
                values[key] = value
    return tuple(sorted(values.items()))


def _table_rows(table, *, nearest_table=False):
    if nearest_table:
        return [row for row in table.xpath('.//tr') if next(row.iterancestors('table'), None) is table]
    # Historical parser versions retain their frozen row-selection semantics.
    return table.xpath('.//tr[not(ancestor::table[2])]')


def _table_structure(table: etree._Element, *, visible_only=False, nearest_table=False, preserve_line_breaks=False) -> TableStructure:
    cells: list[TableCell] = []
    occupied: set[tuple[int, int]] = set()
    max_column = 0
    rows = _table_rows(table, nearest_table=nearest_table)
    if visible_only:
        rows = [row for row in rows if not _hidden(row)]
    for row_number, row in enumerate(rows):
        column = 0
        for cell in row.xpath("./th|./td"):
            if visible_only and _hidden(cell):
                continue
            while (row_number, column) in occupied:
                column += 1
            try:
                rowspan = max(1, int(cell.get("rowspan", "1")))
            except ValueError:
                rowspan = 1
            try:
                colspan = max(1, int(cell.get("colspan", "1")))
            except ValueError:
                colspan = 1
            cells.append(
                TableCell(
                    text=normalize_text(_visible_text(cell, preserve_line_breaks=preserve_line_breaks) if visible_only else cell.text_content()),
                    row=row_number,
                    column=column,
                    rowspan=rowspan,
                    colspan=colspan,
                    is_header=_tag(cell) == "th",
                )
            )
            for covered_row in range(row_number, row_number + rowspan):
                for covered_column in range(column, column + colspan):
                    occupied.add((covered_row, covered_column))
            column += colspan
            max_column = max(max_column, column)
    return TableStructure(row_count=len(rows), column_count=max_column, cells=tuple(cells))


def _toc_table(root: etree._Element, *, nearest_table=False) -> etree._Element | None:
    scored: list[tuple[int, etree._Element]] = []
    for table in root.xpath("//table"):
        count = sum(
            bool(_ITEM_RE.match(normalize_text(row.text_content())))
            for row in _table_rows(table, nearest_table=nearest_table)
        )
        if count:
            scored.append((count, table))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _toc_entries(table: etree._Element | None, blocks=(), anchors=(), verify_link_roles=False, nearest_table=False, linked_titles=False, preserve_line_breaks=False, content_cells=False) -> tuple[tuple[TocEntry, ...], tuple[IndexDiagnostic, ...]]:
    if table is None:
        return (), (
            IndexDiagnostic("toc_missing", "warning", "No Part/Item table of contents was detected; body headings will be used."),
        )
    def row_hrefs(element):
        return list(dict.fromkeys(link.get("href")
            for link in element.xpath('.//a[starts-with(@href,"#")]')
            if not content_cells or not _hidden(link)))

    entries: list[TocEntry] = []
    diagnostics: list[IndexDiagnostic] = []
    seen_items: set[tuple[str, str]] = set()
    current_part = ""
    for row_number, row in enumerate(_table_rows(table, nearest_table=nearest_table), start=1):
        row_cells = row.xpath("./th|./td")
        if content_cells:
            # Physical positions include arbitrary leading/interleaved spacer
            # cells. Interpret Item, title and page using visible content roles.
            # Keep original DOM/cell geometry intact; legacy versions retain
            # their frozen positional behavior.
            row_cells = [cell for cell in row_cells
                         if normalize_text(_visible_text(cell, preserve_line_breaks=preserve_line_breaks))]
        cell_text = [normalize_text(_visible_text(cell, preserve_line_breaks=True) if preserve_line_breaks else cell.text_content()) for cell in row_cells]
        row_text = normalize_text(_visible_text(row, preserve_line_breaks=True) if preserve_line_breaks else row.text_content())
        part_match = _PART_RE.match(next((value for value in cell_text if value), row_text))
        if part_match:
            current_part = part_match.group(1).upper()
            entries.append(TocEntry("part", current_part, f"PART {current_part}", None, None, len(entries) + 1))
            continue
        item_match = _ITEM_RE.match(cell_text[0] if cell_text else row_text)
        if not item_match:
            continue
        number = item_match.group(1).upper()
        title = cell_text[1] if len(cell_text) > 1 and cell_text[1] else item_match.group(2).strip()
        if content_cells:
            inline_title = item_match.group(2).strip()
            title = inline_title or next((value for value in cell_text[1:] if not value.isdigit()), '')
        page_text = cell_text[-1] if cell_text else ""
        if linked_titles and (len(cell_text) < 2 or not cell_text[1]):
            # Spacer cells are layout, not the title or the reported page.
            title_cells = [normalize_text(_visible_text(cell, preserve_line_breaks=preserve_line_breaks)) for cell in row_cells]
            title_cells = [value for value in title_cells[1:] if value and not value.isdigit()]
            if len(title_cells) == 1:
                title = title_cells[0]
            title_links = {normalize_text(_visible_text(a, preserve_line_breaks=preserve_line_breaks)) for a in row.xpath('.//a[starts-with(@href,"#")]')
                           if normalize_text(_visible_text(a, preserve_line_breaks=preserve_line_breaks)) and not normalize_text(_visible_text(a, preserve_line_breaks=preserve_line_breaks)).isdigit()}
            title_links = {text for text in title_links if not _ITEM_RE.match(text)}
            if len(title_links) == 1:
                title = next(iter(title_links))
            elif len(title_links) > 1:
                title = ''
                diagnostics.append(IndexDiagnostic('toc_row_title_conflict', 'error',
                    f'TOC row {row_number} for Item {number} contains conflicting titles.'))
            page_text = next((value for value in reversed(cell_text) if value), '')
        reported_page = int(page_text) if page_text.isdigit() else None
        hrefs = row_hrefs(row)
        source_anchor = hrefs[0][1:] if hrefs else None
        equivalent_page_link = False
        if verify_link_roles and len(hrefs) == 2 and reported_page is not None:
            cells = row_cells
            title_links = row_hrefs(cells[1]) if len(cells) > 2 else []
            if content_cells:
                title_cell_index = 0 if item_match.group(2).strip() else 1
                title_links = row_hrefs(cells[title_cell_index]) if len(cells) > title_cell_index + 1 else []
            page_links = row_hrefs(cells[-1]) if cells else []
            if len(title_links) == len(page_links) == 1:
                by_id = {b.block_id: b for b in blocks}
                by_anchor = {a.anchor: by_id.get(a.target_block_id) for a in anchors}
                title_block = by_anchor.get(title_links[0][1:])
                page_block = by_anchor.get(page_links[0][1:])
                heading = _ITEM_RE.match(title_block.text) if title_block else None
                part_heading = _PART_RE.match(page_block.text) if page_block else None
                # A page link may land on the enclosing Part heading, but only
                # after verifying title, Part identity, order and reported page.
                equivalent_page_link = bool(
                    heading and heading.group(1).upper() == number
                    and normalize_text(heading.group(2)).casefold() == title.casefold()
                    and part_heading and part_heading.group(1).upper() == current_part
                    and title_block.reported_page == page_block.reported_page == reported_page
                    and page_block.ordinal <= title_block.ordinal
                )
                if equivalent_page_link:
                    source_anchor = title_links[0][1:]
        if len(hrefs) > 1 and not equivalent_page_link:
            diagnostics.append(
                IndexDiagnostic(
                    "toc_row_anchor_conflict",
                    "error",
                    f"TOC row {row_number} for Item {number} contains conflicting anchors: {', '.join(hrefs)}",
                )
            )
            if linked_titles:
                source_anchor = None
        if not source_anchor:
            diagnostics.append(IndexDiagnostic("toc_anchor_missing", "warning", f"TOC Item {number} has no body anchor."))
        identity = (current_part, number)
        if identity in seen_items:
            diagnostics.append(IndexDiagnostic("toc_item_duplicate", "error", f"Duplicate TOC entry for Part {current_part} Item {number}."))
            if linked_titles:
                # A duplicate TOC identity cannot authorize a table heading.
                prior_part = ''
                for index, entry in enumerate(entries):
                    if entry.kind == 'part':
                        prior_part = entry.number
                    elif (prior_part, entry.number) == identity:
                        entries[index] = replace(entry, source_anchor=None)
            continue
        seen_items.add(identity)
        entries.append(TocEntry("item", number, title, source_anchor, reported_page, len(entries) + 1))
    return tuple(entries), tuple(diagnostics)


def _mark_repeated_navigation(blocks, candidates, toc, root, positions):
    """Only complete repeated links to a verified contents location are layout."""
    if toc is None or sum(bool(_ITEM_RE.match(normalize_text(r.text_content())))
                          for r in _table_rows(toc, nearest_table=True)) < 2:
        return blocks, []
    if not toc.xpath('.//a[starts-with(@href,"#")]'):
        return blocks, []
    groups = {}
    verified_targets = {}
    target_elements = {}
    labels = {'', 'index', 'contents', 'table of contents'}
    for index, (block, element) in enumerate(zip(blocks, candidates, strict=True)):
        if block.layout_role or block.type in {'table', 'image'} or block.text.casefold() != 'table of contents':
            continue
        links = [a for a in element.iter('a') if not _hidden(a) and normalize_text(_visible_text(a))]
        if len(links) != 1 or normalize_text(_visible_text(links[0])).casefold() != 'table of contents':
            continue
        href = links[0].get('href', '')
        if not href.startswith('#') or len(href) == 1:
            continue
        if href not in verified_targets:
            targets = root.xpath('//*[@id=$name or (self::a and @name=$name)]', name=href[1:])
            valid = False
            if (len(targets) == 1 and not _hidden(targets[0]) and not any(
                    _tag(node) in {'script', 'style', 'noscript'} for node in (targets[0], *targets[0].iterancestors()))):
                target = targets[0]
                if target in positions and positions[target] <= positions[toc]:
                    between = [b for b, e in zip(blocks, candidates, strict=True)
                               if positions[target] <= positions[e] < positions[toc]]
                    target_text = normalize_text(_visible_text(target)).casefold()
                    near_title = (target_text in labels and len(between) <= 2
                                  and (all(b.text.casefold() in labels for b in between)
                                       or (bool(target_text) and all(b.type != 'table' and len(b.text) <= 100
                                                                   for b in between))))
                    # A whole-document wrapper is not a contents target.
                    children = [(b, e) for b, e in zip(blocks, candidates, strict=True)
                                if target in e.iterancestors()]
                    toc_wrapper = target in toc.iterancestors() and all(
                        e is toc or b.text.casefold() in labels for b, e in children)
                    valid = target is toc or near_title or toc_wrapper
            verified_targets[href] = valid
            if valid:
                target_elements[href] = targets[0]
        if not verified_targets[href]:
            continue
        target = target_elements[href]
        if element is target or element in target.iterancestors() or target in element.iterancestors():
            # A genuine contents title may itself carry a self-link. Its DOM
            # ownership, unlike matching link text, distinguishes the title.
            continue
        # Font-size units can vary within the same source layout (em/px).
        # Do not infer a CSS conversion; compare tag, alignment and other style
        # roles while retaining every original style value on the block.
        layout_style = tuple((key, value) for key, value in block.style_signature
                             if key not in {'font-size', 'line-height'})
        key = (href, _tag(element), layout_style)
        groups.setdefault(key, []).append(index)
    marked = {index for indices in groups.values() if len(indices) >= 2 for index in indices}
    if not marked:
        return blocks, []
    return [replace(block, layout_role='repeated_navigation') if i in marked else block
            for i, block in enumerate(blocks)], [IndexDiagnostic('repeated_navigation_marked', 'warning',
        f'{len(marked)} repeated verified contents links retained as source blocks; default reader search/read excludes them.')]


def _candidate_elements(body: etree._Element) -> list[etree._Element]:
    candidates: list[etree._Element] = []
    for child in body:
        # Comments and processing instructions are DOM nodes, but not content
        # elements accepted by lxml's text_content(). Keep the source DOM intact.
        if not _tag(child):
            continue
        tables = child.xpath(".//table") if _tag(child) != "table" else [child]
        images = child.xpath(".//img") if _tag(child) != "img" else [child]
        if tables or images:
            candidates.extend(tables)
            candidates.extend(images)
            continue
        if normalize_text(child.text_content()):
            candidates.append(child)
    positions = {id(element): index for index, element in enumerate(body.iter())}
    unique = {id(element): element for element in candidates}
    return sorted(unique.values(), key=lambda element: positions[id(element)])


def _nested_candidate_elements(body: etree._Element, *, visible_only=False, preserve_nested_assets=False) -> list[etree._Element]:
    """Unwrap layout/XBRL containers, retaining paragraph-level inline markup.

    Tables remain atomic. Mixed direct text is kept intact rather than dropped.
    No new DOM nodes are created, so source paths remain valid.
    """
    result = []
    boundaries = {'div', 'p', 'li', 'ul', 'ol', 'table', 'img', 'section',
                  'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def walk(element):
        tag = _tag(element)
        if not tag or tag in {'script', 'style', 'noscript'} or (visible_only and _hidden(element)):
            return
        if tag in {'table', 'img'}:
            result.append(element)
            # Nested table/image assets also have their own source identities.
            result.extend(e for e in element.xpath('.//table|.//img') if not visible_only or not _hidden(e))
            return
        has_blocks = any(_tag(child) in boundaries for child in element.iterdescendants())
        direct_text = normalize_text(element.text or '') or any(normalize_text(c.tail or '') for c in element)
        if has_blocks and not direct_text:
            for child in element:
                walk(child)
        elif normalize_text(_visible_text(element) if visible_only else element.text_content()):
            result.append(element)
            if preserve_nested_assets:
                # Keep mixed prose intact, while also giving descendant assets
                # their own DOM-bound blocks. Older versions keep atomic prose.
                result.extend(e for e in element.xpath('.//table|.//img') if not visible_only or not _hidden(e))

    for child in body:
        walk(child)
    return result


def _block_type(element: etree._Element, value: str, styles: tuple[tuple[str, str], ...]) -> str:
    tag = _tag(element)
    if tag == "table":
        return "table"
    if tag == "img":
        return "image"
    style = dict(styles)
    if re.fullmatch(r"\d{1,3}\.?", value) and style.get("text-align") == "center":
        return "page_marker"
    if tag == "li":
        return "list_item"
    weight = style.get("font-weight", "")
    is_bold = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or _PART_RE.match(value) or _ITEM_RE.match(value) or (is_bold and len(value) <= 180):
        return "heading_candidate"
    if tag in {"div", "p"} or tag.startswith("ix:"):
        return "paragraph"
    return "other"


def _inherited_page_alignment(element: etree._Element, value: str) -> bool:
    """Recognize centered numeric footers inside text-identical wrappers only.

    Block traversal unwraps layout containers, while text-align is inherited in
    HTML. Do not inherit from a whole page, a table, or a mixed-content wrapper:
    that would turn ordinary numbers into page markers. An explicit alignment
    on a nearer wrapper takes precedence. Existing parser versions retain their
    own page-marker behavior and unchanged style signatures.
    """
    if not re.fullmatch(r"\d{1,3}\.?", value):
        return False
    for node in (element, *element.iterancestors()):
        if _tag(node) in {"body", "html", "table", "tr", "td", "th"}:
            return False
        if normalize_text(_visible_text(node)) != value:
            return False
        alignments = [declaration.split(":", 1)[1].strip().lower()
                      for declaration in (node.get("style") or "").split(";")
                      if ":" in declaration and declaration.split(":", 1)[0].strip().lower() == "text-align"]
        if alignments:
            return alignments[-1] == "center"
    return False


def _asset_reference(element: etree._Element, source_url: str, ordinal: int, dom_path: str) -> AssetReference:
    source_path = element.get("src", "")
    digest = hashlib.sha256(f"{source_path}:{ordinal}".encode()).hexdigest()[:12]
    return AssetReference(
        asset_id=f"asset-{digest}",
        source_url=urljoin(source_url, source_path),
        source_path=source_path,
        alt=element.get("alt"),
        dom_path=dom_path,
    )


def validate_parser_version(parser_version: str) -> str:
    """Reject unknown identities instead of silently selecting legacy behavior."""
    if not isinstance(parser_version, str) or parser_version not in SUPPORTED_PARSER_VERSIONS:
        raise ValueError('unsupported SEC parser version')
    return parser_version


def parse_sec_source(
    document_id: str,
    source_url: str,
    raw_html: bytes,
    *,
    source_snapshot_id: str | None = None,
    form_type: str = "10-K",
    parser_version: str = PARSER_VERSION,
) -> ParsedDocument:
    """Parse SEC HTML into source-faithful blocks without changing legacy paragraphs."""
    validate_parser_version(parser_version)
    if form_type in {"10-Q", "10-Q/A"} and parser_version == PARSER_VERSION:
        parser_version = "sec-source-blocks-v0.1.4-quarterly"
    content_hash = hashlib.sha256(raw_html).hexdigest()
    source_snapshot_id = source_snapshot_id or f"{document_id}-{content_hash[:8]}"
    parser = html.HTMLParser(encoding="utf-8", recover=True, remove_comments=False)
    root = html.document_fromstring(raw_html, parser=parser)
    body_matches = root.xpath("//body")
    if not body_matches:
        raise ValueError("SEC source HTML has no body element")
    body = body_matches[0]
    tree = root.getroottree()
    all_elements = list(body.iter())
    positions = {id(element): index for index, element in enumerate(all_elements)}
    preserve_line_breaks = parser_version in _LINE_BREAK_PARSERS
    visible_only = parser_version in _VISIBLE_PARSERS
    nearest_table = parser_version in _NEAREST_TABLE_PARSERS
    nested = visible_only or parser_version in {"sec-source-blocks-v0.1.4-quarterly", "sec-source-blocks-v0.1.5"}
    candidates = _nested_candidate_elements(body, visible_only=visible_only,
        preserve_nested_assets=nearest_table) if nested else _candidate_elements(body)
    candidate_positions = [positions[id(element)] for element in candidates]
    toc = _toc_table(root, nearest_table=nearest_table)
    toc_path = tree.getpath(toc) if toc is not None else None

    structural_anchors: list[tuple[int, str]] = []
    for element in all_elements:
        anchor = element.get("id") or (element.get("name") if _tag(element) == "a" else None)
        if anchor and (_STRUCTURAL_ANCHOR_RE.match(anchor) or not normalize_text(element.text_content())):
            structural_anchors.append((positions[id(element)], anchor))

    blocks: list[SourceBlock] = []
    assets: list[AssetReference] = []
    for ordinal, element in enumerate(candidates, start=1):
        dom_path = tree.getpath(element)
        tag = _tag(element)
        value = normalize_text(element.get("alt", "")) if tag == "img" else normalize_text(
            _visible_text(element, preserve_line_breaks=preserve_line_breaks) if visible_only else element.text_content())
        styles = _style_values(element)
        kind = _block_type(element, value, styles)
        if (parser_version in _INHERITED_PAGE_PARSERS and kind not in {"table", "image", "page_marker"}
                and _inherited_page_alignment(element, value)):
            kind = "page_marker"
        if nested and kind not in {'table', 'image'} and value.startswith(('•', '◦')):
            kind = 'list_item'
        element_position = positions[id(element)]
        preceding = [item for item in structural_anchors if item[0] <= element_position]
        source_anchor = preceding[-1][1] if preceding else None
        table = _table_structure(element, visible_only=visible_only, nearest_table=nearest_table, preserve_line_breaks=preserve_line_breaks) if kind == "table" else None
        image_asset_id = None
        if kind == "image":
            asset = _asset_reference(element, source_url, ordinal, dom_path)
            assets.append(asset)
            image_asset_id = asset.asset_id
        layout_role = None
        if dom_path == toc_path:
            layout_role = "table_of_contents"
        elif kind == "page_marker":
            layout_role = "reported_page_number"
        elif kind == "table" and "Table of Contents" in value and len(value) < 100:
            layout_role = "running_header"
        digest = text_hash(value)
        blocks.append(
            SourceBlock(
                block_id=f"block-{ordinal:06d}-{digest[:8]}",
                ordinal=ordinal,
                type=kind,  # type: ignore[arg-type]
                text=value,
                text_hash=digest,
                source_anchor=source_anchor,
                dom_path=dom_path,
                reported_page=int(value.rstrip(".")) if kind == "page_marker" else None,
                style_signature=styles,
                table=table,
                image_asset_id=image_asset_id,
                layout_role=layout_role,
            )
        )

    # SEC's printed page number is a footer: it labels the blocks that precede
    # it, not the blocks that follow it. Backfill each page segment only after
    # the footer is known so Item starts do not inherit the previous page.
    paged_blocks = list(blocks)
    segment_start = 0
    for index, block in enumerate(blocks):
        if block.type != "page_marker" or block.reported_page is None:
            continue
        for segment_index in range(segment_start, index + 1):
            paged_blocks[segment_index] = replace(paged_blocks[segment_index], reported_page=block.reported_page)
        segment_start = index + 1
    blocks = paged_blocks

    header_diagnostics = []
    if visible_only:
        titled, current_part = set(), None
        for block in blocks:
            if block.type != 'heading_candidate' or block.layout_role:
                continue
            part, item = _PART_RE.match(block.text), _ITEM_RE.match(block.text)
            if part:
                current_part = part.group(1).upper()
            elif item and current_part and item.group(2).strip(' .'):
                titled.add((current_part, item.group(1).upper()))
        seen, current_part, ignored = set(), None, 0
        for index, block in enumerate(blocks):
            if block.type != 'heading_candidate' or block.layout_role:
                continue
            part, item = _PART_RE.match(block.text), _ITEM_RE.match(block.text)
            key, bare_label = None, False
            if part:
                current_part = part.group(1).upper()
                key = ('part', current_part)
            elif item and current_part:
                number, title = item.group(1).upper(), item.group(2).strip(' .')
                key = ('item', current_part, number, title.casefold())
                bare_label = not title and (current_part, number) in titled
            if key is not None:
                if key in seen or bare_label:
                    blocks[index] = replace(block, layout_role='running_header')
                    ignored += 1
                seen.add(key)
        if ignored:
            header_diagnostics.append(IndexDiagnostic('repeated_legal_headers_excluded', 'warning',
                f'{ignored} repeated or titleless page labels excluded from body coverage and outline starts.'))

    block_positions = [
        (positions[id(element)], block.block_id)
        for element, block in zip(candidates, blocks, strict=True)
        if block.type != "page_marker" and block.layout_role != "running_header"
    ]
    only_positions = [position for position, _ in block_positions]
    anchors: list[SourceAnchor] = []
    anchor_diagnostics: list[IndexDiagnostic] = []
    containing_first = parser_version in CONTAINMENT_PARSERS
    element_blocks = {element: block.block_id for element, block in zip(candidates, blocks, strict=True)
                      if block.type != 'page_marker' and block.layout_role != 'running_header'}
    seen_anchors: set[str] = set()
    for element in all_elements:
        anchor = element.get("id") or (element.get("name") if _tag(element) == "a" else None)
        if not anchor:
            continue
        if containing_first and anchor in seen_anchors:
            anchor_diagnostics.append(IndexDiagnostic('duplicate_source_anchor', 'warning',
                f'Duplicate source anchor {anchor!r} at {tree.getpath(element)}; first DOM occurrence retained.'))
            continue
        seen_anchors.add(anchor)
        target_block_id = None
        visible_anchor = not _hidden(element) and not any(
            _tag(node) in {'script', 'style', 'noscript'} for node in (element, *element.iterancestors()))
        if containing_first and visible_anchor:
            target_block_id = next((element_blocks[node] for node in (element, *element.iterancestors())
                                    if node in element_blocks), None)
        if not containing_first or (visible_anchor and target_block_id is None):
            # v0.1.7 and earlier retain their historical forward-only mapping.
            # In v0.1.8 only anchors outside a represented block use a successor.
            index = bisect.bisect_left(only_positions, positions[id(element)])
            target_block_id = block_positions[index][1] if index < len(block_positions) else None
        anchors.append(SourceAnchor(anchor, tree.getpath(element), target_block_id))

    toc_entries, toc_diagnostics = _toc_entries(toc, blocks, anchors,
        verify_link_roles=visible_only or parser_version in {"sec-source-blocks-v0.1.3-quarterly", "sec-source-blocks-v0.1.4-quarterly", "sec-source-blocks-v0.1.5"},
        nearest_table=nearest_table, linked_titles=parser_version in _TABLE_ITEM_PARSERS, preserve_line_breaks=preserve_line_breaks,
        content_cells=parser_version in _CONTENT_CELL_TOC_PARSERS)
    navigation_diagnostics = []
    if parser_version in NAVIGATION_PARSERS:
        blocks, navigation_diagnostics = _mark_repeated_navigation(blocks, candidates, toc, root,
            {element: position for position, element in enumerate(all_elements)})
    return ParsedDocument(
        document_id=document_id,
        source_url=source_url,
        content_hash=content_hash,
        source_snapshot_id=source_snapshot_id,
        form_type=form_type,
        parser_version=parser_version,
        blocks=tuple(blocks),
        anchors=tuple(anchors),
        toc_entries=toc_entries,
        assets=tuple(assets),
        parser_diagnostics=tuple(toc_diagnostics) + tuple(header_diagnostics) + tuple(anchor_diagnostics) + tuple(navigation_diagnostics),
    )


def _body_outline_entries(parsed: ParsedDocument) -> tuple[TocEntry, ...]:
    entries: list[TocEntry] = []
    current_part = ""
    for block in parsed.blocks:
        if block.type != "heading_candidate":
            continue
        part_match = _PART_RE.match(block.text)
        if part_match:
            current_part = part_match.group(1).upper()
            entries.append(TocEntry("part", current_part, f"PART {current_part}", block.source_anchor, block.reported_page, len(entries) + 1))
            continue
        item_match = _ITEM_RE.match(block.text)
        if item_match and current_part:
            entries.append(
                TocEntry(
                    "item",
                    item_match.group(1).upper(),
                    item_match.group(2).strip(" .") or f"Item {item_match.group(1).upper()}",
                    block.source_anchor,
                    block.reported_page,
                    len(entries) + 1,
                )
            )
    return tuple(entries)


def _verified_table_item_headings(parsed):
    """Table structure + unique TOC identity, title, Part and exact anchor agree.

    Tables remain source tables. This recognizes navigation boundaries only,
    not the semantic membership of everything between consecutive headings.
    """
    toc, current_part = {}, None
    for entry in parsed.toc_entries:
        if entry.kind == 'part':
            current_part = entry.number
        elif current_part:
            toc[(current_part, entry.number)] = entry
    anchors = {a.anchor: a.target_block_id for a in parsed.anchors}
    table_paths = {b.dom_path for b in parsed.blocks if b.type == 'table'}
    candidates, diagnostics, current_part = {}, [], None
    for block in parsed.blocks:
        if block.type == 'heading_candidate' and not block.layout_role and (part := _PART_RE.match(block.text)):
            current_part = part.group(1).upper()
        if block.type != 'table' or block.layout_role or not block.table:
            continue
        cells = block.table.cells
        if not cells or not re.fullmatch(r'ITEM\s+\d+[A-Z]?\.', cells[0].text, re.I):
            continue
        reason = None
        nested = any(path != block.dom_path and (path.startswith(block.dom_path + '/')
                     or block.dom_path.startswith(path + '/')) for path in table_paths)
        if nested:
            reason = 'nested_table'
        elif (block.table.row_count != 1 or block.table.column_count != 2 or len(cells) != 2
              or any(c.rowspan != 1 or c.colspan != 1 for c in cells)):
            reason = 'unsupported_table_shape'
        title = cells[1].text if len(cells) == 2 else ''
        if not reason and (not title or len(title) > 180 or not any(c.isalpha() for c in title)
                           or any(c.isalpha() and not c.isascii() for c in title)):
            reason = 'unsupported_title_script_or_length'
        number = re.fullmatch(r'ITEM\s+(\d+[A-Z]?)\.', cells[0].text, re.I).group(1).upper()
        entry = toc.get((current_part, number))
        if not reason and (not entry or not entry.title):
            reason = 'missing_unique_toc_identity'
        if reason:
            diagnostics.append(IndexDiagnostic('table_item_heading_rejected', 'warning',
                f'{block.block_id}: {reason}; table retained without an Item node.'))
            continue
        candidates.setdefault((current_part, number), []).append((block, title, entry))
    accepted, delimiters = {}, []
    for (part, number), values in candidates.items():
        # A TOC-title-confirmed legal boundary still stops the preceding Item
        # when its anchor is missing/wrong. It does not authorize a new node.
        delimiters.extend(block.ordinal for block, title, entry in values
                          if title.casefold() == entry.title.casefold())
        if len({title.casefold() for _, title, _ in values}) > 1:
            diagnostics.append(IndexDiagnostic('table_item_heading_conflict', 'error',
                f'Part {part} Item {number}: conflicting table titles; no Item range published.'))
            delimiters.extend(block.ordinal for block, _, _ in values)
            continue
        verified = [(block, title) for block, title, entry in values
                    if title.casefold() == entry.title.casefold()
                    and anchors.get(entry.source_anchor) == block.block_id]
        if len(verified) != 1:
            diagnostics.append(IndexDiagnostic('table_item_heading_rejected', 'warning',
                f'Part {part} Item {number}: title or exact TOC anchor mismatch; table retained without an Item node.'))
            continue
        block, title = verified[0]
        accepted[block.block_id] = (number, title, values[0][2])
        if len(values) > 1:
            diagnostics.append(IndexDiagnostic('repeated_table_item_heading', 'warning',
                f'Part {part} Item {number}: only the unique TOC-anchored repeated title creates a node.'))
    return accepted, delimiters, diagnostics


def _qualified_text_items(parsed):
    """New outline branches distinguish an Item reference from a title.

    Exact TOC title correspondence or explicit heading typography is required;
    a paragraph does not become a heading merely by beginning with 'Item n'.
    The same selected blocks are used for published nodes and range boundaries.
    """
    toc, current_part = {}, None
    for entry in parsed.toc_entries:
        if entry.kind == 'part':
            current_part = entry.number
        elif current_part:
            toc[(current_part, entry.number)] = entry.title.casefold()
    qualified, current_part = set(), None
    for block in parsed.blocks:
        if block.type != 'heading_candidate' or block.layout_role:
            continue
        if part := _PART_RE.match(block.text):
            current_part = part.group(1).upper()
            continue
        item = _ITEM_RE.match(block.text)
        if not item or not current_part or len(block.text) > 300:
            continue
        title = item.group(2).strip(' .')
        exact_toc = bool(title) and toc.get((current_part,item.group(1).upper())) == title.casefold()
        heading_tag = bool(re.search(r'/h[1-6](?:\[\d+\])?$',block.dom_path))
        weight = dict(block.style_signature).get('font-weight','')
        bold_title = (weight == 'bold' or weight.isdigit() and int(weight) >= 600) and block.text.isupper()
        if exact_toc or heading_tag or (bold_title and re.match(r'^ITEM\s+\d+[A-Z]?\.',block.text,re.I)):
            qualified.add(block.block_id)
    return qualified


def _verified_body_outline(parsed, table_items=None, text_items=None):
    """Bind legal headings to their actual blocks, not inherited wrapper IDs."""
    parts, items, diagnostics = {}, {}, []
    current_part = None
    for block in parsed.blocks:
        if table_items and block.block_id in table_items and current_part:
            number, title, _ = table_items[block.block_id]
            items.setdefault((current_part, number), []).append((block, title))
            continue
        if block.type != 'heading_candidate' or block.layout_role or len(block.text) > 300:
            continue
        part = _PART_RE.match(block.text)
        if part:
            current_part = part.group(1).upper()
            parts.setdefault(current_part, block)
            continue
        item = _ITEM_RE.match(block.text)
        if text_items is not None and block.block_id not in text_items:
            continue
        if item and current_part:
            key = (current_part, item.group(1).upper())
            items.setdefault(key, []).append((block, item.group(2).strip(' .')))
    chosen = [('part', number, f'PART {number}', block) for number, block in parts.items()]
    anchors = {a.anchor: a.target_block_id for a in parsed.anchors}
    for (part, number), candidates in items.items():
        titled = [(block, title) for block, title in candidates if title]
        if len({title.casefold() for _, title in titled}) > 1:
            diagnostics.append(IndexDiagnostic('item_heading_ambiguous', 'error',
                f'Part {part} Item {number} has conflicting body titles; no range published.'))
            continue
        block, title = (titled or candidates)[0]
        if len(candidates) > 1:
            diagnostics.append(IndexDiagnostic('repeated_legal_heading', 'warning',
                f'Part {part} Item {number}: repeated labels do not create additional nodes.'))
        if block.source_anchor and anchors.get(block.source_anchor) != block.block_id:
            diagnostics.append(IndexDiagnostic('item_anchor_body_override', 'warning',
                f'Part {part} Item {number}: inherited anchor does not locate the heading; using its original DOM block.'))
        chosen.append(('item', number, title or f'Item {number}', block))
    chosen.sort(key=lambda value: value[3].ordinal)
    entries, targets = [], {}
    for ordinal, (kind, number, title, block) in enumerate(chosen, 1):
        verified_toc = table_items[block.block_id][2] if table_items and block.block_id in table_items else None
        entry = TocEntry(kind, number, title, verified_toc.source_anchor if verified_toc else block.source_anchor,
                         verified_toc.reported_page if verified_toc else block.reported_page, ordinal)
        entries.append(entry)
        targets[ordinal] = block
    if not items:
        diagnostics.append(IndexDiagnostic('item_unresolved', 'error', 'No visible legal Item body headings were found.'))
    return tuple(entries), targets, diagnostics


def build_legal_outline(parsed_document: ParsedDocument, *, schema_version: str = SCHEMA_VERSION) -> DocumentIndex:
    """Build only the filing's legal Document → Part → Item hierarchy."""
    blocks = parsed_document.blocks
    if not blocks:
        raise ValueError("cannot build an outline for a document without blocks")
    by_id = {block.block_id: block for block in blocks}
    anchor_targets = {anchor.anchor: anchor.target_block_id for anchor in parsed_document.anchors}
    diagnostics = list(parsed_document.parser_diagnostics)
    entries = parsed_document.toc_entries
    verified_targets = {}
    table_items, table_delimiters = {}, []
    text_items = None
    if parsed_document.parser_version in _TABLE_ITEM_PARSERS:
        text_items = _qualified_text_items(parsed_document)
        table_items, table_delimiters, table_diagnostics = _verified_table_item_headings(parsed_document)
        diagnostics.extend(table_diagnostics)
        diagnostics.append(IndexDiagnostic('outline_ranges_are_navigation', 'warning',
            'Part/Item ranges are contiguous source navigation intervals; attachments, signatures and financial statements within a range are not inferred to share its semantic topic.'))
    if parsed_document.parser_version in _VISIBLE_PARSERS:
        entries, verified_targets, body_diagnostics = _verified_body_outline(parsed_document, table_items, text_items)
        diagnostics.extend(body_diagnostics)
    elif not any(entry.kind == "item" for entry in entries):
        entries = _body_outline_entries(parsed_document)
        diagnostics.append(IndexDiagnostic("outline_body_fallback", "warning", "The legal outline was built from deterministic body heading patterns."))

    resolved: list[tuple[TocEntry, SourceBlock]] = []
    current_part = ""
    search_after = 0
    for entry in entries:
        if entry.kind == "part":
            current_part = entry.number
            candidates = [
                block for block in blocks
                if block.ordinal >= search_after and _PART_RE.match(block.text) and _PART_RE.match(block.text).group(1).upper() == entry.number
            ]
            if entry.ordinal in verified_targets:
                candidates = [verified_targets[entry.ordinal]]
            if candidates:
                resolved.append((entry, candidates[0]))
                search_after = candidates[0].ordinal
            else:
                diagnostics.append(IndexDiagnostic("part_heading_missing", "warning", f"PART {entry.number} was listed in the TOC but no body heading was found."))
            continue
        target_id = anchor_targets.get(entry.source_anchor or "")
        target = by_id.get(target_id or "")
        if entry.ordinal in verified_targets:
            target = verified_targets[entry.ordinal]
        if target is None:
            candidates = [
                block for block in blocks
                if block.ordinal >= search_after
                and (match := _ITEM_RE.match(block.text))
                and match.group(1).upper() == entry.number
            ]
            target = candidates[0] if candidates else None
            if target:
                diagnostics.append(IndexDiagnostic("item_anchor_fallback", "warning", f"Item {entry.number} used its deterministic body heading fallback."))
        if target is None:
            diagnostics.append(IndexDiagnostic("item_unresolved", "error", f"Item {entry.number} could not be mapped to a source block."))
            continue
        heading_match = _ITEM_RE.match(target.text)
        if not heading_match or heading_match.group(1).upper() != entry.number:
            diagnostics.append(IndexDiagnostic("item_anchor_title_mismatch", "error", f"Item {entry.number} anchor resolves near {target.text[:80]!r}."))
        resolved.append((entry, target))
        search_after = target.ordinal

    index_seed = f"{parsed_document.content_hash}:{schema_version}:{parsed_document.parser_version}"
    index_id = f"didx-{hashlib.sha256(index_seed.encode()).hexdigest()[:16]}"
    root_id = f"{index_id}-document"
    starts: list[tuple[TocEntry, SourceBlock, str, str | None, str | None]] = []
    part_node_id: str | None = None
    current_part_number: str | None = None
    for entry, block in resolved:
        if entry.kind == "part":
            current_part_number = entry.number
            part_node_id = f"{index_id}-part-{entry.number.lower()}"
            starts.append((entry, block, part_node_id, root_id, current_part_number))
        elif part_node_id:
            starts.append((entry, block, f"{part_node_id}-item-{entry.number.lower()}", part_node_id, current_part_number))
        else:
            diagnostics.append(IndexDiagnostic("item_without_part", "error", f"Item {entry.number} has no resolved Part parent."))

    nodes: list[DocumentNode] = [
        DocumentNode(
            node_id=root_id,
            parent_id=None,
            kind="document",
            title=parsed_document.document_id,
            part_number=None,
            item_number=None,
            start_block_id=blocks[0].block_id,
            end_block_id=blocks[-1].block_id,
            source_anchor=blocks[0].source_anchor,
            reported_page=blocks[0].reported_page,
        )
    ]
    part_start_ordinals = [block.ordinal for entry, block, _, _, _ in starts if entry.kind == "part"]
    all_start_ordinals = [block.ordinal for _, block, _, _, _ in starts]
    all_start_ordinals.extend(table_delimiters)
    if parsed_document.parser_version in _VISIBLE_PARSERS:
        # Unresolved/conflicting headings still delimit their preceding section;
        # omitting an ambiguous node must not absorb it into a different Item.
        all_start_ordinals.extend(block.ordinal for block in blocks
            if block.type == 'heading_candidate' and not block.layout_role and _ITEM_RE.match(block.text)
            and (text_items is None or block.block_id in text_items))
    for entry, start, node_id, parent_id, part_number in starts:
        boundaries = part_start_ordinals if entry.kind == "part" else all_start_ordinals
        following = [ordinal for ordinal in boundaries if ordinal > start.ordinal]
        end_ordinal = (min(following) - 1) if following else blocks[-1].ordinal
        if parsed_document.parser_version in _VISIBLE_PARSERS:
            while end_ordinal > start.ordinal and blocks[end_ordinal - 1].layout_role:
                end_ordinal -= 1
        if end_ordinal < start.ordinal:
            diagnostics.append(IndexDiagnostic("node_range_invalid", "error", f"Invalid source range for {node_id}.", node_id))
            end_ordinal = start.ordinal
        end = blocks[end_ordinal - 1]
        nodes.append(
            DocumentNode(
                node_id=node_id,
                parent_id=parent_id,
                kind=entry.kind,
                title=entry.title,
                part_number=part_number,
                item_number=entry.number if entry.kind == "item" else None,
                start_block_id=start.block_id,
                end_block_id=end.block_id,
                source_anchor=entry.source_anchor or start.source_anchor,
                reported_page=entry.reported_page if entry.reported_page is not None else start.reported_page,
            )
        )

    return DocumentIndex(
        index_id=index_id,
        schema_version=schema_version,
        parser_version=parsed_document.parser_version,
        source_snapshot_id=parsed_document.source_snapshot_id,
        form_type=parsed_document.form_type,
        nodes=tuple(nodes),
        diagnostics=tuple(diagnostics),
    )
