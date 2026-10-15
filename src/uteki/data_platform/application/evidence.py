"""Prepare source-bound response items; only final returned items are registered."""
from __future__ import annotations

from copy import deepcopy

from ..contracts.common import CatalogError, canonical, digest, new_id
from ..contracts.evidence import HtmlEvidenceRef
from ..contracts.run import ResultRef
from .session import ref_key


def result_item(session, operation, kind, value):
    reference = ResultRef(run_id=session.data['context']['run_id'],operation_id=operation,kind=kind,item_id=new_id('res'))
    return deepcopy(value) | dict(result_ref=reference.model_dump(mode='json'))


def register_returned(session, operation, response):
    found = {}
    def visit(value):
        if isinstance(value,dict):
            if 'result_ref' in value:
                reference = ResultRef.model_validate(value['result_ref'])
                if reference.run_id != session.data['context']['run_id'] or reference.operation_id != operation:
                    raise CatalogError('RESULT_REF_INVALID','response contains a foreign result')
                key = ref_key(reference)
                if key in found and found[key] != value:
                    raise CatalogError('RESULT_REF_INVALID','same result has different returned contents')
                found[key] = deepcopy(value)
            for item in value.values():
                visit(item)
        elif isinstance(value,list):
            for item in value:
                visit(item)
    visit(response)
    for value in found.values():
        for ref in value.get('operand_refs',[]) + value.get('dependency_refs',[]):
            if ref_key(ref) not in found:
                raise CatalogError('RESULT_REF_INVALID','response omitted a required dependency')
    seen = set(session.data['seen_results'])
    before = len(seen)
    for item in found.values():
        # A fresh ResultRef for the same source range/value is not new evidence.
        stable = {k:v for k,v in item.items() if k not in {'result_ref','operand_refs','dependency_refs','requested_target_index'}}
        for key in ('operand_refs','dependency_refs'):
            stable[key] = [{k:v for k,v in found[ref_key(r)].items() if k not in {'result_ref','operand_refs','dependency_refs'}} for r in item.get(key,[])]
        seen.add(digest(canonical(stable)))
    session.data['seen_results'] = sorted(seen)
    session.data['results'].update(found)
    return len(seen)-before


def source_evidence(reader, kind, item_id, *, start=None, end=None, role='target', context_kind=None):
    evidence_ref = HtmlEvidenceRef(asset_ref=reader.reference,kind=kind,item_id=item_id,
        field='raw_value' if kind=='record_field' else 'text')
    read = reader.read(evidence_ref)
    text = read['source']['text']
    locator = deepcopy(read['source']['locator'])
    lower = 0 if start is None else start
    upper = len(text) if end is None else end
    if lower < 0 or upper < lower or upper > len(text):
        raise CatalogError('INVALID_REQUEST','source range is outside the returned item')
    text = text[lower:upper]
    locator.update(char_start=locator['char_start']+lower,char_end=locator['char_start']+upper,text_sha256=digest(text.encode()))
    value = dict(asset_ref=reader.reference.model_dump(mode='json'),locator=locator,
        reader_ref=evidence_ref.model_dump(mode='json'),kind='record' if kind=='record_field' else 'table' if kind=='table_cell' else 'text',
        role=role,context_kind=context_kind,dependency_refs=[],content={'text':text},
        source_object=read['source']['source_object'],source_url=read['source']['source_url'],
        quality=dict(extraction='xbrl' if kind=='record_field' else 'html',issues=[]),truncated=start is not None or end is not None)
    if kind=='table_cell':
        table = read['context']['table']
        cell = next(c for c in table['cells'] if c['id']==item_id)
        value['content'].update(table_id=table['id'],cell_id=cell['id'],row=cell['row'],col=cell['col'],
            row_span=cell['row_span'],col_span=cell['col_span'],header=cell['header'],caption=table['caption'],
            explicit_header_ids=cell['explicit_headers'],header_candidate_ids=cell['header_candidates'],footnote_links=cell['footnote_links'])
    if kind=='record_field':
        value['content']['record'] = read['context']['record']
        value['content']['context_source'] = read['context']['xbrl_context']
        value['content']['unit_source'] = read['context']['xbrl_unit']
    return value


def record_item(reader, record):
    evidence = reader.read(HtmlEvidenceRef(asset_ref=reader.reference,kind='record_field',item_id=record['id'],field='raw_value'))
    from ..retrieval.index import concept_id
    return dict(asset_ref=reader.reference.model_dump(mode='json'),record_id=record['id'],concept_id=concept_id(record),
        value=record['value_decimal'],raw_value=record['raw_value'],status=record['status'],period=record['period'],
        unit=record['unit'],dimensions=record['dimensions'],entity_identifier=record['entity_identifier'],entity_scheme=record['entity_scheme'],
        context_ref=record['context_ref'],decimals=record['decimals'],scale=record['scale'],sign=record['sign'],
        duplicate_group=record['duplicate_group'],issues=record['issues'],locator=record['locator'],
        source_object=evidence['source']['source_object'],source_url=evidence['source']['source_url'],
        context_source=evidence['context']['xbrl_context'],unit_source=evidence['context']['xbrl_unit'])


def fit_page(items, start, *, limit, max_bytes):
    """Whole items only. Callers split long text with exact ranges beforehand."""
    selected = []
    index = start
    while index < len(items) and len(selected) < limit:
        candidate = items[index]
        if len(canonical(selected+[candidate])) > max_bytes:
            break
        selected.append(candidate)
        index += 1
    return selected, index, index<len(items) and len(selected)<limit


def text_fragments(reader, block_id, *, start=None, end=None, max_chars=500):
    block = reader._blocks.get(block_id)
    if block is None:
        raise CatalogError('TARGET_NOT_FOUND','block does not exist')
    lower = 0 if start is None else start
    upper = len(block.text) if end is None else end
    if lower < 0 or upper < lower or upper > len(block.text):
        raise CatalogError('INVALID_REQUEST','invalid block range')
    for offset in range(lower,upper,max_chars):
        yield source_evidence(reader,'block',block_id,start=offset,end=min(offset+max_chars,upper))
    if lower == upper:
        yield source_evidence(reader,'block',block_id,start=lower,end=upper)
