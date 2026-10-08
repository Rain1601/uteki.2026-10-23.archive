"""Scriptless response copies of explicitly selected frozen source documents.

Locator metadata never authorizes a filesystem read. The registered dataset and
source loaders establish identity first; a locator only selects within those
verified bytes. Nothing in this module writes to the source snapshot.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import re

from lxml import etree, html

from apps.review_workbench.data.evaluation_artifacts import load_dataset, load_raw_source
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import (
    _hidden, _visible_text, _VISIBLE_PARSERS, _LINE_BREAK_PARSERS, _NEAREST_TABLE_PARSERS,
    _table_rows, _table_structure,
)
from uteki.infrastructure.research_data.evidence_coordinates import character_span


PREVIEW_CSP = (
    "sandbox; default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "img-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; "
    "worker-src 'none'; form-action 'none'; base-uri 'none'"
)
_SEGMENT = re.compile(r"([A-Za-z][A-Za-z0-9_:.-]*)(?:\[([1-9][0-9]*)\])?\Z")
_ACTIVE_TAGS = {"script", "iframe", "frame", "frameset", "object", "embed", "base", "link"}
_NOTICES = {
    "not_requested": ("完整原件预览；尚未选择需要定位的证据。", "Complete source preview; no evidence location selected."),
    "block": ("已定位并标出对应原文块；高亮范围可能是整张表格。", "The matching source block is highlighted; this may be an entire table."),
    "character": ("已按索引原文的明确字符范围高亮。", "The explicit indexed-text character range is highlighted."),
    "cell": ("已按明确行列坐标高亮原始单元格。", "The original table cell at the explicit row and column is highlighted."),
    "page": ("可定位至来源记录中的 PDF 页，尚不支持页内精确高亮。", "A source-recorded PDF page is available; exact highlighting within the page is unavailable."),
    "unavailable": ("无法唯一核对这条证据在原件中的位置；下方保留完整原件，不猜测位置。", "This evidence could not be uniquely located in the original. The complete source remains available without a guessed location."),
    "pdf_unavailable": ("这条证据没有真实 PDF 页映射；报告印刷页码不能代替 PDF 页码。", "No PDF-page mapping is recorded for this evidence; printed page numbers are not PDF page numbers."),
    "unsupported": ("此原件格式暂不支持内嵌预览。", "This source format does not support an inline preview."),
}


def _selection(selection):
    if (not isinstance(selection, dict) or not {"dataset", "source"} <= set(selection)
            or set(selection) - {"dataset", "source", "block", "char_start", "char_end", "cell_row", "cell_column", "quote", "text_hash", "source_sha256"}):
        raise ValueError("Explicit dataset and source, with an optional block, are required")
    for values in selection.values():
        if (not isinstance(values, list) or len(values) != 1
                or not isinstance(values[0], str) or not values[0].strip()):
            raise ValueError("Source preview identities must be single, nonblank values")
    args = {key: values[0] for key, values in selection.items()}
    precise = any(key in args for key in ('char_start', 'char_end', 'cell_row', 'cell_column'))
    if precise and 'block' not in args:
        raise ValueError('Precise evidence requires an explicit block')
    for keys in (('char_start', 'char_end'), ('cell_row', 'cell_column')):
        if any(key in args for key in keys):
            if not all(key in args and re.fullmatch(r'0|[1-9][0-9]*', args[key]) for key in keys):
                raise ValueError('Precise evidence requires paired nonnegative integer coordinates')
            for key in keys:
                args[key] = int(args[key])
    character_span(args)
    for key in ('text_hash', 'source_sha256'):
        if key in args and not re.fullmatch('[0-9a-f]{64}', args[key]):
            raise ValueError('Explicit evidence hashes must be lowercase SHA256')
    return args


def _notice(kind):
    zh, en = _NOTICES[kind]
    return {"zh": zh, "en": en}


def _dom_target(document, path):
    """Resolve only an absolute child/index path, including inline-XBRL tags."""
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    steps = path[1:].split("/")
    parsed = [_SEGMENT.fullmatch(step) for step in steps]
    if not parsed or any(match is None for match in parsed):
        return None
    first = parsed[0]
    if first[1].lower() != str(document.tag).lower() or first[2] not in (None, "1"):
        return None
    current = document
    for match in parsed[1:]:
        matches = [child for child in current if isinstance(child.tag, str)
                   and child.tag.lower() == match[1].lower()]
        if match[2] is None:
            if len(matches) != 1:
                return None
            current = matches[0]
        else:
            index = int(match[2]) - 1
            if index >= len(matches):
                return None
            current = matches[index]
    return current


def _matches(target, block, parser_version):
    if target is None or not block.get("text") or block.get("type") == "image":
        return False
    if _hidden(target) or any(str(node.tag).lower().split(":")[-1] in _ACTIVE_TAGS | {"style", "noscript"}
           for node in (target, *target.iterancestors())):
        return False
    text = _visible_text(target, preserve_line_breaks=parser_version in _LINE_BREAK_PARSERS) if parser_version in _VISIBLE_PARSERS else target.text_content()
    return normalize_text(text) == block["text"]


def _locate(document, block, parser_version):
    target = _dom_target(document, block.get("dom_path"))
    if _matches(target, block, parser_version):
        return target
    anchor = block.get("source_anchor")
    if not isinstance(anchor, str) or not anchor:
        return None
    matches = document.xpath("//*[@id=$anchor or (self::a and @name=$anchor)]", anchor=anchor)
    # A preceding empty anchor is not the block; do not guess a neighboring node.
    if len(matches) == 1 and _matches(matches[0], block, parser_version):
        return matches[0]
    return None



def _text_slots(target, *, visible_only, line_breaks):
    """Mirror indexed text order with a reversible map to actual DOM text slots."""
    slots = []
    def visit(node):
        tag = str(node.tag).lower() if isinstance(node.tag, str) else ''
        if visible_only and (_hidden(node) or tag in {'script', 'style', 'noscript'}):
            return
        if line_breaks and tag == 'br':
            slots.append((None, None, '\n'))
            return
        if node.text:
            slots.append((node, 'text', node.text))
        for child in node:
            if isinstance(child.tag, str):
                visit(child)
            if child.tail:
                slots.append((child, 'tail', child.tail))
    visit(target)
    return slots


def _range_slots(target, block, parser_version, start, end):
    slots = _text_slots(target, visible_only=parser_version in _VISIBLE_PARSERS,
                        line_breaks=parser_version in _LINE_BREAK_PARSERS)
    raw = ''.join(value for _, _, value in slots)
    # Normalize precisely like the index parser, retaining source character offsets.
    mapping, chars = [], []
    for match in re.finditer(r'\s+|[^\s]', raw):
        chars.append(' ' if match.group().isspace() else match.group())
        mapping.append((match.start(), match.end()))
    while chars and chars[0] == ' ': chars.pop(0); mapping.pop(0)
    while chars and chars[-1] == ' ': chars.pop(); mapping.pop()
    if ''.join(chars) != block['text'] or not 0 <= start < end <= len(mapping):
        return None
    lo, hi = mapping[start][0], mapping[end - 1][1]
    selected, offset = [], 0
    for node, field, value in slots:
        left, right = max(0, lo - offset), min(len(value), hi - offset)
        if left < right and node is not None:
            # Never make hidden/active text look like visible evidence, even for old indexes.
            if _hidden(node) or str(node.tag).lower() in _ACTIVE_TAGS | {'style', 'noscript'}:
                return None
            selected.append((node, field, value, left, right))
        offset += len(value)
    return selected or None


def _mark_range(slots):
    marks = []
    for node, field, value, lo, hi in slots:
        mark = etree.Element('mark', {'class': 'workspace-evidence-range'})
        mark.text, mark.tail = value[lo:hi], value[hi:]
        setattr(node, field, value[:lo])
        if field == 'text': node.insert(0, mark)
        else: node.addnext(mark)
        marks.append(mark)
    return marks[0]


def _cell_target(target, block, parser_version, row, column):
    if block.get('type') != 'table' or str(target.tag).lower() != 'table':
        return None
    visible = parser_version in _VISIBLE_PARSERS
    nearest = parser_version in _NEAREST_TABLE_PARSERS
    actual = _table_structure(target, visible_only=visible, nearest_table=nearest,
                              preserve_line_breaks=parser_version in _LINE_BREAK_PARSERS)
    expected = block.get('table')
    # Compare the whole frozen grid before attaching a coordinate to a DOM cell.
    if not expected or {'row_count': actual.row_count, 'column_count': actual.column_count, 'cells': [asdict(cell) for cell in actual.cells]} != expected:
        return None
    rows = _table_rows(target, nearest_table=nearest)
    nodes = [cell for r in rows if not visible or not _hidden(r)
             for cell in r.xpath('./th|./td') if not visible or not _hidden(cell)]
    found = [node for cell, node in zip(actual.cells, nodes) if cell.row == row and cell.column == column]
    return found[0] if len(found) == 1 else None


def _precise_target(target, block, parser_version, args):
    if target is None:
        return None, 'none'
    cell = _cell_target(target, block, parser_version, args['cell_row'], args['cell_column']) if 'cell_row' in args else None
    if 'cell_row' in args and cell is None:
        return None, 'none'
    span = character_span(args, text=block['text'])
    if span is not None:
        slots = _range_slots(target, block, parser_version, *span)
        if not slots:
            return None, 'none'
        if cell is not None and any((node if field == 'text' else node.getparent()) is not cell
                and cell not in (node if field == 'text' else node.getparent()).iterancestors()
                for node, field, _, _, _ in slots):
            raise ValueError('Character evidence range conflicts with selected table cell')
        return _mark_range(slots), 'character'
    if cell is not None:
        if args.get('quote') is not None:
            text = normalize_text(_visible_text(cell, preserve_line_breaks=parser_version in _LINE_BREAK_PARSERS)
                                  if parser_version in _VISIBLE_PARSERS else cell.text_content())
            if args['quote'] != text:
                raise ValueError('Evidence quote differs from selected table cell')
        return cell, 'cell'
    return target, 'block'


def _isolate(document):
    """Remove active surfaces while retaining source text and inline layout."""
    for node in list(document.iter()):
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower().split(":")[-1]
        if tag in _ACTIVE_TAGS or tag == "meta":
            parent = node.getparent()
            if parent is not None:
                node.drop_tree()
            continue
        classes = node.get('class', '').split()
        if 'workspace-evidence-range' in classes:
            node.set('class', ' '.join(c for c in classes if c != 'workspace-evidence-range'))
        for name, value in list(node.attrib.items()):
            local = name.lower().split(":")[-1]
            if (local.startswith("on") or local in {"srcdoc", "action", "formaction", "target", "ping", "download", "srcset", "autofocus"}
                    or (local == "href" and not value.startswith("#"))
                    or (local == "src" and not (tag == "img" and value.lower().startswith("data:")))):
                del node.attrib[name]
            elif local in {"id", "name"} and value in {"workspace-evidence", "workspace-source-notice"}:
                del node.attrib[name]


def _decorate(document, notice, target=None):
    head = document.find("head")
    if head is None:
        head = etree.Element("head")
        document.insert(0, head)
    etree.SubElement(head, "meta", charset="utf-8")
    etree.SubElement(head, "meta", {"http-equiv": "Content-Security-Policy", "content": PREVIEW_CSP})
    style = etree.SubElement(head, "style")
    style.text = (
        "#workspace-evidence, .workspace-evidence-range { outline: 3px solid #b45f06 !important; "
        "background-color: #fff4c2 !important; scroll-margin-top: 12px; }"
        "#workspace-source-notice { display:block !important; padding:12px !important; "
        "margin:0 0 16px !important; color:#26231f !important; background:#fff4c2 !important; "
        "font:14px/1.5 sans-serif !important; white-space:normal !important; }"
    )
    body = document.find("body")
    if body is None:
        body = etree.SubElement(document, "body")
    banner = etree.Element("div", id="workspace-source-notice", role="status")
    banner.text = notice["zh"] + " / " + notice["en"]
    body.insert(0, banner)
    if target is not None:
        old_id = target.get("id")
        if old_id:
            target.set("data-workspace-original-id", old_id)
            # Keep existing same-document links usable after assigning one unique target.
            if len(document.xpath("//*[@id=$identity]", identity=old_id)) == 1:
                for link in document.xpath("//*[@href=$href]", href="#" + old_id):
                    link.set("href", "#workspace-evidence")
        target.set("id", "workspace-evidence")
    return html.tostring(document, encoding="utf-8", method="html", doctype="<!doctype html>")


def load_source_preview(root, selection):
    """Return bytes, restrictive headers and honest source-location metadata.

    Callers must send ``headers`` with the response and keep iframe ``sandbox``
    empty. HTML/text highlights use ``#workspace-evidence``; PDF locations use
    only an explicitly recorded ``pdf_page``. A reported/printed page is never
    converted to a PDF page. No loader path or SQL is accepted from the caller.
    """
    args = _selection(selection)
    dataset = load_dataset(root, args["dataset"])
    sources = [source for source in dataset["sources"] if source["source_snapshot_id"] == args["source"]]
    if len(sources) != 1:
        raise ValueError("Source is missing or ambiguous in the selected dataset")
    source = sources[0]
    block = None
    if "block" in args:
        matches = [item for item in dataset["blocks"][args["source"]] if item["block_id"] == args["block"]]
        if len(matches) != 1:
            raise ValueError("Block is missing or ambiguous in the selected source")
        block = matches[0]
    raw = load_raw_source(root, args["dataset"], args["source"])
    if (raw["sha256"] != source["source_sha256"]
            or hashlib.sha256(raw["content"]).hexdigest() != source["source_sha256"]):
        raise ValueError("Preview bytes differ from the selected source snapshot")
    result = {"mime_type": raw["mime_type"], "content": raw["content"],
              "headers": {"Content-Security-Policy": PREVIEW_CSP, "X-Content-Type-Options": "nosniff",
                          "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
              "dataset_id": args["dataset"], "source_snapshot_id": args["source"],
              "source_sha256": source["source_sha256"], "block_id": args.get("block"),
              "locator_status": "not_requested" if block is None else "unavailable",
              "locator_precision": "none", "fragment": "",
              "notice": _notice("not_requested" if block is None else "unavailable")}
    if args.get('source_sha256') is not None and args['source_sha256'] != source['source_sha256']:
        raise ValueError('Evidence source hash differs from selected snapshot')
    if args.get('text_hash') is not None and (block is None or args['text_hash'] != block.get('text_hash')):
        raise ValueError('Evidence text hash differs from selected block')
    if block is not None:
        character_span(args, text=block['text'])
    result['requested_precision'] = ('character' if 'char_start' in args else 'cell' if 'cell_row' in args else 'block' if block else 'none')
    for key in ('char_start', 'char_end', 'cell_row', 'cell_column'):
        if key in args: result[key] = args[key]
    mime = raw["mime_type"]
    if mime == "text/html":
        document = html.document_fromstring(raw["content"], parser=html.HTMLParser(encoding="utf-8", recover=True, no_network=True))
        parser_version = dataset["indexes"][args["source"]].get("parser_version")
        target = _locate(document, block, parser_version) if block else None
        _isolate(document)
        target, precision = _precise_target(target, block, parser_version, args) if block else (None, 'none')
        if target is not None:
            result.update(locator_status="located", locator_precision=precision, fragment="workspace-evidence", notice=_notice(precision))
        result["content"] = _decorate(document, result["notice"], target)
    elif mime == "application/pdf":
        if block is not None and result['requested_precision'] == 'block':
            pdf_page = block.get("pdf_page")
            if isinstance(pdf_page, int) and not isinstance(pdf_page, bool) and pdf_page >= 1:
                result.update(locator_status="located", locator_precision="page", fragment=f"page={pdf_page}",
                              pdf_page=pdf_page, notice=_notice("page"))
            else:
                result["notice"] = _notice("pdf_unavailable")
    elif mime == "text/plain":
        if block is not None:
            try:
                text = raw["content"].decode("utf-8-sig")
            except UnicodeDecodeError:
                return result
            needle = block.get("text")
            positions = [match.start() for match in re.finditer(re.escape(needle), text)] if needle else []
            document = html.document_fromstring("<html><head></head><body><pre></pre></body></html>")
            pre = document.find("body/pre")
            target = None
            if len(positions) == 1 and 'cell_row' not in args:
                span = character_span(args, text=block['text']) or (0, len(needle))
                start, end = positions[0] + span[0], positions[0] + span[1]
                pre.text = text[:start]
                target = etree.SubElement(pre, "mark")
                target.text = text[start:end]
                target.tail = text[end:]
                precision = result['requested_precision']
                result.update(locator_status="located", locator_precision=precision, fragment="workspace-evidence", notice=_notice(precision))
            else:
                pre.text = text
            result.update(mime_type="text/html", content=_decorate(document, result["notice"], target))
    else:
        result.update(mime_type="application/octet-stream", notice=_notice("unsupported"))
        result["headers"]["Content-Disposition"] = "attachment"
    return result
