# 把原文投影封装为带出处的候选结果，并且只登记最终响应实际包含的证据。
# ResultRef 标识本次返回；locator 与内容摘要标识原件位置，两者承担不同的追溯职责。
"""Prepare source-bound response items; only final returned items are registered."""
from __future__ import annotations

from copy import deepcopy

from ..contracts.common import CatalogError, canonical, digest, new_id
from ..contracts.evidence import HtmlEvidenceRef
from ..contracts.run import ResultRef, result_handle
from .session import ref_key


# 为候选结果分配本次运行/操作的引用；仅创建返回对象，此时尚未登记为已展示。
def result_item(session, operation, kind, value):
    reference = ResultRef(run_id=session.data['context']['run_id'],operation_id=operation,kind=kind,item_id=new_id('res'))
    return deepcopy(value) | dict(result_ref=reference.model_dump(mode='json'),
                                  result_handle=result_handle(reference))


# 递归收集响应中的结果，校验归属与依赖闭包，登记后返回新增证据数量。
def register_returned(session, operation, response):
    found = {}
    # 遍历响应中的嵌套结果；同一个 ResultRef 若对应不同内容则拒绝登记。
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
    # 依赖必须与目标一起出现在最终响应；不能引用生成过却未实际返回的候选。
    for value in found.values():
        for ref in value.get('operand_refs',[]) + value.get('dependency_refs',[]):
            if ref_key(ref) not in found:
                raise CatalogError('RESULT_REF_INVALID','response omitted a required dependency')
    seen = set(session.data['seen_results'])
    before = len(seen)
    for item in found.values():
        if item['result_ref']['kind']=='metadata':
            # Existing metadata progress keys are independent of page grouping
            # and citation IDs. Do not count the same navigation twice.
            continue
        # A fresh ResultRef for the same source range/value is not new evidence.
        # 忽略每次新分配的结果 ID，按原文范围和依赖内容判断是否真的取得新证据。
        stable = {k:v for k,v in item.items() if k not in {'result_ref','result_handle','operand_refs','dependency_refs','requested_target_index'}}
        for key in ('operand_refs','dependency_refs'):
            stable[key] = [{k:v for k,v in found[ref_key(r)].items() if k not in {'result_ref','result_handle','operand_refs','dependency_refs'}} for r in item.get(key,[])]
        seen.add(digest(canonical(stable)))
    session.data['seen_results'] = sorted(seen)
    session.data['results'].update(found)
    return len(seen)-before


def metadata_keys(tool, response):
    """Navigation progress is metadata, distinct from source-fact progress.

    Ignore request IDs, timing, cursors, ranking and page grouping. Splitting or
    reordering the same metadata must not reset the no-progress limit.
    """
    if response.get('status') not in {'ok','partial'}:
        return set()
    if tool == 'search_asset' and response.get('navigation_asset_ref'):
        return {digest(canonical(dict(kind='document_navigation',asset_ref=response['navigation_asset_ref'],
                    item={k:v for k,v in item.items() if k not in {'result_ref','result_handle'}})))
                for item in response['items']}
    if tool not in {'find_assets','get_asset_schema'}:
        return set()
    keys = set()
    for item in response['items']:
        if tool=='find_assets':
            value = {k:item[k] for k in ('asset_ref','title','metadata','readiness')}
            keys.add(digest(canonical(dict(kind='asset_metadata',value=value))))
        else:
            # Capability/index generation tokens can change without providing
            # new information; retain actual readiness and source metadata.
            value = {k:item[k] for k in ('asset_ref','overview','readiness','capabilities','coverage')}
            value['capabilities'] = sorted(value['capabilities'])
            keys.add(digest(canonical(dict(kind='schema_metadata',value=value))))
            for facet in item['facets']:
                keys.add(digest(canonical(dict(kind='schema_facet',asset_ref=item['asset_ref'],facet=facet))))
            for node in item.get('directory',{}).get('nodes',[]):
                keys.add(digest(canonical(dict(kind='document_directory',asset_ref=item['asset_ref'],node=node))))
    return keys


def metadata_history(session):
    if 'seen_metadata' in session.data:
        return set(session.data['seen_metadata'])
    # Older saved sessions have no metadata history field. Reconstruct it from
    # completed responses, so reopening/upgrading cannot make old pages new.
    seen = set()
    for operation in session.data['operations'].values():
        if operation['status']=='completed':
            seen.update(metadata_keys(operation['tool'],operation['response']))
    return seen


def register_metadata(session, tool, response):
    seen = metadata_history(session)
    before = len(seen)
    seen.update(metadata_keys(tool,response))
    session.data['seen_metadata'] = sorted(seen)
    return len(seen)-before


# 按冻结读者定位原文，可截取精确字符范围；保留来源对象、定位摘要与类型上下文。
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
    # 截取后同步调整原件坐标和文本 hash，避免片段沿用全文定位。
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


# 把已解析记录与原始值、XBRL 期间/单位上下文和来源地址一起返回。
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


# 在条数和字节预算内选择完整条目，返回选中项、下一位置及预算截断标记。
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


# 将指定块范围拆成带精确出处的小片段；空范围也保留可追踪的空结果。
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
