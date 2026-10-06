"""Bind semantic row citations to original DOM facts, never numeric substring guesses."""
import re

from lxml import etree, html

from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _visible_text
from .financial_records import digest, dom_path_query, local_name


def _element(tree, path):
    if not path:
        return None
    if not isinstance(path, str) or not re.fullmatch(r'(?:/[A-Za-z_][\w:.-]*(?:\[[1-9]\d*\])?)+', path):
        raise ValueError('anchor DOM path must be an absolute element path')
    try:
        matches = tree.xpath(dom_path_query(path))
    except etree.XPathError as error:
        raise ValueError('invalid anchor DOM path') from error
    return matches[0] if len(matches) == 1 else None


def _blocks(packet):
    source = packet['source']['source_snapshot_id']
    blocks = {}
    for block in packet['source_blocks']:
        if block['source_snapshot_id'] != source or block['block_id'] in blocks:
            raise ValueError('anchor blocks must be unique and belong to the selected source')
        if digest(block['text'].encode()) != block['text_hash']:
            raise ValueError('anchor block text hash mismatch')
        blocks[block['block_id']] = block
    return blocks


def build_record_anchors(packet, raw: bytes):
    scope = ExecutionScope.model_validate(packet['scope'])
    source = packet['source']
    sid = source['source_snapshot_id']
    if sid not in scope.source_snapshot_ids or source['company_id'] not in scope.company_ids:
        raise ValueError('anchor source outside execution scope')
    if digest(raw) != source['source_sha256']:
        raise ValueError('anchor original bytes hash mismatch')
    if source.get('available_at') is not None and source['available_at'][:10] > str(scope.knowledge_cutoff):
        raise ValueError('anchor source after cutoff')
    blocks = _blocks(packet)
    tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8', no_network=True))
    result = {}
    for item in packet['records']:
        record, evidence = item['record'], item.get('evidence')
        rid = record['record_id']
        if rid in result or record['source_snapshot_id'] != sid:
            raise ValueError('anchor record is duplicated or belongs to another source')
        if record.get('available_at') is not None and record['available_at'][:10] > str(scope.knowledge_cutoff):
            raise ValueError('anchor record after cutoff')
        if record.get('status') == 'candidate' and not scope.include_candidates:
            raise ValueError('anchor candidate access denied')
        def unavailable(reason):
            result[rid] = {'status': 'unavailable', 'reason': reason, 'source_snapshot_id': sid}
        if not evidence:
            unavailable('fact_evidence_missing')
            continue
        if evidence.get('source_snapshot_id') != sid or evidence.get('source_sha256') != source['source_sha256']:
            raise ValueError('anchor evidence belongs to another source')
        if evidence.get('evidence_id') not in record['evidence_ids']:
            raise ValueError('anchor evidence is not bound to the record')
        block = blocks.get(evidence.get('block_id'))
        if block is None:
            unavailable('source_block_not_supplied')
            continue
        if evidence.get('dom_path') != block['dom_path']:
            raise ValueError('anchor evidence block DOM mismatch')
        container = _element(tree, block['dom_path'])
        fact = _element(tree, evidence.get('fact_dom_path'))
        if container is None or fact is None:
            unavailable('fact_or_block_dom_not_unique')
            continue
        if fact is not container and container not in fact.iterancestors():
            raise ValueError('anchor fact DOM is outside its source block')
        quote = evidence.get('quote')
        if not isinstance(quote, str) or not normalize_text(quote) or normalize_text(_visible_text(fact)) != normalize_text(quote):
            unavailable('fact_raw_quote_not_visible_or_mismatched')
            continue
        row = next((node for node in (fact, *fact.iterancestors()) if local_name(node) == 'tr'), None)
        if row is not None:
            if row is not container and container not in row.iterancestors():
                unavailable('complete_table_row_outside_source_block')
                continue
            text, kind = normalize_text(_visible_text(row)), 'table_row'
        else:
            text, kind = normalize_text(_visible_text(container)), 'paragraph'
            if text != block['text']:
                unavailable('visible_paragraph_differs_from_source_block')
                continue
        start = block['text'].find(text) if text else -1
        if start < 0 or block['text'].find(text, start + 1) >= 0:
            unavailable('row_or_paragraph_not_uniquely_located')
            continue
        if normalize_text(quote) not in text:
            unavailable('fact_raw_quote_absent_from_anchor')
            continue
        result[rid] = {'status': 'located', 'source_snapshot_id': sid, 'block_id': block['block_id'],
                       'start': start, 'end': start + len(text), 'text': text, 'kind': kind}
    return result


def validate_record_anchor_coverage(packet, constraint):
    """Each affected record needs one complete row/block citation at an exact offset."""
    constraint = constraint.model_dump(mode='json') if hasattr(constraint, 'model_dump') else constraint
    blocks = _blocks(packet)
    record_ids = {item['record']['record_id'] for item in packet['records']}
    requested = constraint['record_ids']
    if not requested or len(set(requested)) != len(requested) or not set(requested) <= record_ids:
        raise ValueError('anchor constraint record scope mismatch')
    spans = []
    for citation in constraint['citations']:
        citation = citation.model_dump(mode='json') if hasattr(citation, 'model_dump') else citation
        block = blocks.get(citation['block_id'])
        start, quote = citation.get('source_start'), citation.get('quote')
        if block is None or citation['source_snapshot_id'] != block['source_snapshot_id']:
            raise ValueError('anchor citation outside source/block scope')
        if (not isinstance(start, int) or isinstance(start, bool) or start < 0 or not isinstance(quote, str)
                or not quote or block['text'][start:start + len(quote)] != quote):
            raise ValueError('anchor citation needs an exact source_start and contiguous quote')
        spans.append((citation['block_id'], start, start + len(quote)))
    for rid in requested:
        anchor = packet.get('record_anchors', {}).get(rid)
        if not anchor or anchor.get('status') != 'located':
            raise ValueError('record anchor unavailable: ' + rid)
        block = blocks.get(anchor['block_id'])
        start, end = anchor['start'], anchor['end']
        if (block is None or anchor['source_snapshot_id'] != block['source_snapshot_id']
                or not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool)
                or not 0 <= start < end <= len(block['text']) or block['text'][start:end] != anchor['text']):
            raise ValueError('record anchor has invalid scope or range')
        if not any(bid == anchor['block_id'] and lo <= start and hi >= end for bid, lo, hi in spans):
            raise ValueError('citation does not cover the complete record anchor: ' + rid)
