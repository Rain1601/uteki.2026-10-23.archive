"""Derive exact record coordinates from immutable indexed originals, without models."""
from dataclasses import asdict
import json
from pathlib import Path
import re

from lxml import html

from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import (
    _hidden, _tag, _visible_text, _LINE_BREAK_PARSERS, _VISIBLE_PARSERS,
    _NEAREST_TABLE_PARSERS, _table_rows, _table_structure, validate_parser_version,
)
from .evidence_coordinates import character_span
from .financial_records import digest
from .query_dataset import contained
from .semantic_anchors import _element, _dom_span


def resolve_record_locator(dataset_dir, evidence):
    """Resolve one frozen record citation to block-relative Unicode coordinates.

    The caller owns scope and externally pinned dataset-manifest verification.
    This function verifies each source/index/raw file against that manifest and
    verifies evidence identity against the exact source/block. Existing offsets
    remain authoritative only when verified and consistent with a supplied DOM
    fact. Without a DOM fact or offsets, a quote must occur exactly once.
    """
    root = Path(dataset_dir).resolve()
    manifest = json.loads((root/'manifest.json').read_bytes())
    def read(relative):
        expected = manifest['files'].get(relative)
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Record locator input is not pinned in the dataset manifest')
        raw = contained(root, relative).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Record locator frozen input hash mismatch')
        return raw
    sid, bid = evidence.get('source_snapshot_id'), evidence.get('block_id')
    if not isinstance(sid, str) or not sid or not isinstance(bid, str) or not bid:
        raise ValueError('Record locator requires explicit source and block identities')
    sources = [source for source in json.loads(read('sources.json')) if source['source_snapshot_id'] == sid]
    if len(sources) != 1:
        raise ValueError('Record locator source is missing or ambiguous')
    source = sources[0]
    prefix = source['index_folder'] + '/'
    index_manifest_raw = read(prefix + 'manifest.json')
    index_raw, block_raw = read(prefix + 'index.json'), read(prefix + 'blocks.jsonl')
    index_manifest, index = json.loads(index_manifest_raw), json.loads(index_raw)
    for name, raw in (('index.json', index_raw), ('blocks.jsonl', block_raw)):
        if index_manifest['artifacts'][name]['sha256'] != digest(raw):
            raise ValueError('Record locator index manifest differs from frozen artifact')
    if (index['index_id'] != source['index_id'] or index.get('source_snapshot_id') != sid
            or index.get('source_sha256', source['source_sha256']) != source['source_sha256']
            or index_manifest.get('source_snapshot_id') != sid
            or index_manifest.get('source_sha256') != source['source_sha256']):
        raise ValueError('Record locator source/index identity mismatch')
    blocks = [json.loads(line) for line in block_raw.splitlines() if line]
    matches = [block for block in blocks if block['block_id'] == bid]
    if len(matches) != 1 or matches[0].get('type') == 'image':
        raise ValueError('Record locator block is absent, ambiguous or non-text')
    block = matches[0]
    if block.get('source_snapshot_id', sid) != sid:
        raise ValueError('Indexed record block belongs to another source')
    if digest(block['text'].encode('utf-8')) != block['text_hash']:
        raise ValueError('Record locator indexed text hash mismatch')
    for key, expected in (('source_sha256', source['source_sha256']), ('index_id', source['index_id']),
                           ('text_hash', block['text_hash'])):
        if evidence.get(key) != expected:
            raise ValueError('Record evidence source/index/text identity mismatch')
    if evidence.get('dom_path') is not None and evidence['dom_path'] != block.get('dom_path'):
        raise ValueError('Record evidence block DOM path mismatch')
    raw = read(source['raw_file'])
    if digest(raw) != source['source_sha256'] or source.get('raw_file_sha256', source['source_sha256']) != source['source_sha256']:
        raise ValueError('Record source bytes differ from frozen source identity')
    quote = evidence.get('quote')
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('Record locator requires a nonblank original quote')
    explicit = character_span(evidence, text=block['text'])
    located_cell = None
    if evidence.get('fact_dom_path') is not None:
        if source.get('parsed_mime_type', source.get('declared_mime_type')) != 'text/html':
            raise ValueError('Fact DOM locator requires frozen HTML')
        parser = index.get('parser_version')
        validate_parser_version(parser)
        if parser not in _VISIBLE_PARSERS:
            raise ValueError('Exact fact DOM mapping requires a supported visible-text parser')
        line_breaks = parser in _LINE_BREAK_PARSERS
        tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8', no_network=True))
        container, fact = _element(tree, block.get('dom_path')), _element(tree, evidence['fact_dom_path'])
        if container is None or fact is None:
            raise ValueError('Record fact or block DOM is not uniquely located')
        if fact is not container and container not in fact.iterancestors():
            raise ValueError('Record fact DOM is outside the selected source block')
        if _tag(fact) not in {'ix:nonfraction', 'ix:nonnumeric', 'ix:fraction'}:
            raise ValueError('Record fact DOM must identify an inline XBRL fact')
        for field, attribute in (('fact_id', 'id'), ('context_ref', 'contextref'),
                                 ('unit_ref', 'unitref'), ('concept', 'name')):
            if evidence.get(field) is not None and evidence[field] != fact.get(attribute):
                raise ValueError('Record fact metadata differs from selected DOM fact')
        if normalize_text(_visible_text(fact, preserve_line_breaks=line_breaks)) != quote:
            raise ValueError('Record fact quote differs from visible DOM text')
        span = _dom_span(container, fact, block['text'], preserve_line_breaks=line_breaks)
        if span is None or block['text'][span[0]:span[1]] != quote:
            raise ValueError('Record fact cannot be mapped exactly into indexed block text')
        if explicit is not None and explicit != span:
            raise ValueError('Record DOM fact conflicts with explicit character coordinates')
        cell = next((node for node in fact.iterancestors() if _tag(node) in {'td', 'th'}), None)
        if block.get('type') == 'table':
            if cell is None or container not in cell.iterancestors():
                raise ValueError('Record fact does not belong to a cell in the selected table')
            nearest = parser in _NEAREST_TABLE_PARSERS
            grid = _table_structure(container, visible_only=True, nearest_table=nearest, preserve_line_breaks=line_breaks)
            frozen_grid = {'row_count': grid.row_count, 'column_count': grid.column_count,
                           'cells': [asdict(item) for item in grid.cells]}
            if frozen_grid != block.get('table'):
                raise ValueError('Record fact original table grid differs from indexed table')
            cells = [item for row in _table_rows(container, nearest_table=nearest) if not _hidden(row)
                     for item in row.xpath('./th|./td') if not _hidden(item)]
            positions = [position for position, node in zip(grid.cells, cells) if node is cell]
            if len(positions) != 1:
                raise ValueError('Record fact cell is not uniquely mapped to the indexed grid')
            located_cell = {'row': positions[0].row, 'column': positions[0].column}
    else:
        if explicit is not None:
            span = explicit
        else:
            matches = [match.start() for match in re.finditer('(?=' + re.escape(quote) + ')', block['text'])]
            if len(matches) != 1:
                raise ValueError('Record quote is ambiguous or absent without a DOM fact or explicit coordinates')
            span = matches[0], matches[0] + len(quote)
    if evidence.get('cell') is not None:
        recorded = evidence['cell']
        if not isinstance(recorded, dict) or any(type(recorded.get(key)) is not int or recorded[key] < 0 for key in ('row', 'column')):
            raise ValueError('Recorded evidence cell requires explicit integer row and column')
        if located_cell is not None and any(recorded[key] != located_cell[key] for key in ('row', 'column')):
            raise ValueError('Record DOM fact conflicts with recorded cell coordinates')
        if located_cell is None:
            occurrences = [match.start() for match in re.finditer('(?=' + re.escape(quote) + ')', block['text'])]
            if len(occurrences) != 1:
                raise ValueError('Cannot bind repeated quote offsets to a recorded cell without a DOM fact')
            cells = (block.get('table') or {}).get('cells', [])
            matching = [cell for cell in cells if all(cell.get(key) == value for key, value in recorded.items())]
            if len(matching) != 1 or quote not in matching[0]['text']:
                raise ValueError('Recorded evidence cell differs from indexed table')
            located_cell = {key: recorded[key] for key in ('row', 'column')}
    return {'char_start': span[0], 'char_end': span[1], 'text_hash': block['text_hash'],
            **({'cell': located_cell} if located_cell is not None else {})}
