"""Versioned lossless model-reading projection of a fully verified source packet.

The host keeps the original packet. Only enumerated host provenance fields are
omitted; source text, IDs, scope and physical cell geometry are never compressed
semantically. Full mode deliberately preserves the historical request shape.
"""
from __future__ import annotations
import copy
import json

FULL = 'full'
COMPACT = 'compact-v1'
FORMAT = 'business-revenue-source-compact-v1'
INSTRUCTIONS = '''\n<source_wire_format>
The source packet uses compact-v1. Scope is in scope; blocks keep their original
text and IDs. Each table has cell_columns and cells: each cell is an ordered tuple
whose fields correspond exactly to cell_columns. Blank strings are real empty
cells, not missing rows. row_index and column_index are zero-based physical grid
coordinates; rowspan/colspan preserve merged geometry. row_indices, if present,
retain all original rows, including empty ones. Use the same original block and
cell IDs in the output. Host DOM paths/hashes are omitted from this reading view
but remain in the frozen evidence packet. No source text or financial value was
removed or rewritten.
</source_wire_format>'''

TOP_HOST = {'source_local_path', 'source_html_path', 'source_sha256', 'source_sha256_basis', 'source_manifest',
            'original_source_path', 'original_source_local_path', 'original_source_sha256', 'source_encoding'}
BLOCK_HOST = {'source_dom_path', 'text_sha256', 'fragment', 'source_anchor', 'original_source_path',
              'original_source_sha256', 'origin_text_fragment', 'origin_text_dom_path',
              'origin_text_source_local_path', 'origin_text_source_sha256'}
TABLE_HOST = {'source_dom_path', 'pdf_column_boundaries', 'pdf_row_boundaries', 'geometry_source'}
CELL_HOST = {'source_dom_path', 'text_sha256', 'pdf_bbox', 'pdf_words'}
CELL_REQUIRED = ('id', 'text', 'row_index', 'column_index', 'rowspan', 'colspan')


def require(condition, error):
    if not condition:
        raise ValueError(error)


def semantic_projection(packet):
    """Define exactly the fields compact-v1 must preserve and reconstitute."""
    require(isinstance(packet, dict), 'wire_packet_object_required')
    for field in ('company_id', 'document_id', 'period_end', 'requested_period_label', 'financial_currency', 'financial_unit'):
        require(isinstance(packet.get(field), str) and bool(packet[field].strip()), 'wire_scope_required: ' + field)
    require(isinstance(packet.get('blocks'), list) and packet['blocks'] and isinstance(packet.get('tables'), list), 'wire_blocks_tables_required')
    scope = {k: copy.deepcopy(v) for k,v in packet.items() if k not in TOP_HOST | {'blocks', 'tables'}}
    blocks = []
    for block in packet['blocks']:
        require(isinstance(block, dict), 'wire_block_object_required')
        require(all(k in block for k in ('id', 'text', 'ordinal', 'section_path')), 'wire_block_key_missing')
        blocks.append({k: copy.deepcopy(v) for k,v in block.items() if k not in BLOCK_HOST})
    tables = []
    for table in packet['tables']:
        require(isinstance(table, dict) and all(k in table for k in ('id', 'block_id', 'cells')), 'wire_table_key_missing')
        require(isinstance(table['cells'], list), 'wire_cells_list_required')
        public = {k: copy.deepcopy(v) for k,v in table.items() if k not in TABLE_HOST | {'cells', 'rows'}}
        cells, signatures = [], set()
        for cell in table['cells']:
            require(isinstance(cell, dict) and all(k in cell for k in CELL_REQUIRED), 'wire_cell_key_missing')
            require(isinstance(cell['id'], str) and cell['id'] and isinstance(cell['text'], str), 'wire_cell_id_text_invalid')
            for k in ('row_index', 'column_index', 'rowspan', 'colspan'):
                require(type(cell[k]) is int and cell[k] >= (1 if k in ('rowspan','colspan') else 0), 'wire_cell_geometry_invalid')
            item = {k: copy.deepcopy(v) for k,v in cell.items() if k not in CELL_HOST}
            signatures.add(tuple(sorted(item)))
            cells.append(item)
        require(len(signatures) <= 1, 'wire_heterogeneous_cell_fields')
        require(len({c['id'] for c in cells}) == len(cells), 'wire_duplicate_cell_id')
        public['cells'] = cells
        if 'rows' in table:
            rows = table['rows']
            require(isinstance(rows, list), 'wire_rows_list_required')
            require(all(isinstance(r, dict) and set(r) == {'row_index','cell_ids'} and type(r['row_index']) is int and r['row_index'] >= 0 for r in rows), 'wire_row_fields_invalid')
            require(len({r['row_index'] for r in rows}) == len(rows), 'wire_duplicate_row_index')
            require(all(isinstance(r['cell_ids'], list) and r['cell_ids'] == [c['id'] for c in cells if c['row_index'] == r['row_index']] for r in rows), 'wire_row_cell_ids_mismatch')
            require({c['row_index'] for c in cells} <= {r['row_index'] for r in rows}, 'wire_cell_row_missing')
            public['rows'] = copy.deepcopy(rows)
        tables.append(public)
    return {'scope': scope, 'blocks': blocks, 'tables': tables}


def expand_compact(wire):
    require(isinstance(wire, dict) and set(wire) == {'wire_format','scope','blocks','tables'} and wire['wire_format'] == FORMAT, 'wire_format_invalid')
    require(isinstance(wire['scope'], dict) and isinstance(wire['blocks'], list) and isinstance(wire['tables'], list), 'wire_compact_shape_invalid')
    tables = []
    for table in wire['tables']:
        require(isinstance(table, dict) and 'cell_columns' in table and isinstance(table.get('cells'), list), 'wire_compact_table_invalid')
        columns = table['cell_columns']
        require(isinstance(columns, list) and all(isinstance(k,str) for k in columns) and len(set(columns)) == len(columns) and set(CELL_REQUIRED) <= set(columns), 'wire_columns_invalid')
        require(all(isinstance(row,list) and len(row) == len(columns) for row in table['cells']), 'wire_tuple_length_mismatch')
        public = {k: copy.deepcopy(v) for k,v in table.items() if k not in {'cell_columns','cells','row_indices'}}
        public['cells'] = [dict(zip(columns, copy.deepcopy(row))) for row in table['cells']]
        if 'row_indices' in table:
            indices = table['row_indices']
            require(isinstance(indices,list) and all(type(r) is int and r >= 0 for r in indices) and len(set(indices)) == len(indices), 'wire_row_indices_invalid')
            public['rows'] = [{'row_index': r, 'cell_ids': [c['id'] for c in public['cells'] if c['row_index'] == r]} for r in indices]
        tables.append(public)
    return {'scope': copy.deepcopy(wire['scope']), 'blocks': copy.deepcopy(wire['blocks']), 'tables': tables}


def build_wire_packet(packet, mode=FULL):
    if mode == FULL:
        return copy.deepcopy(packet)
    require(mode == COMPACT, 'unsupported_source_wire_mode')
    projected = semantic_projection(packet)
    wire = {'wire_format': FORMAT, 'scope': projected['scope'], 'blocks': projected['blocks'], 'tables': []}
    for table in projected['tables']:
        extra = sorted(set(table['cells'][0]) - set(CELL_REQUIRED)) if table['cells'] else []
        columns = list(CELL_REQUIRED) + extra
        compact = {k: copy.deepcopy(v) for k,v in table.items() if k not in {'cells','rows'}}
        require(not {'cell_columns','row_indices'} & compact.keys(), 'wire_reserved_table_field')
        compact['cell_columns'] = columns
        compact['cells'] = [[c[k] for k in columns] for c in table['cells']]
        if 'rows' in table:
            compact['row_indices'] = [r['row_index'] for r in table['rows']]
        wire['tables'].append(compact)
    require(expand_compact(wire) == projected, 'wire_roundtrip_mismatch')
    return wire


def serialize_wire(packet, mode=FULL):
    return json.dumps(build_wire_packet(packet, mode), ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def verify_wire(packet, content, mode=FULL):
    require(isinstance(content, str) and content == serialize_wire(packet, mode), 'wire_content_or_mode_mismatch')
    if mode == COMPACT:
        require(expand_compact(json.loads(content)) == semantic_projection(packet), 'wire_roundtrip_mismatch')
