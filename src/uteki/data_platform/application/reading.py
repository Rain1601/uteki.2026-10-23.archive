# 按块、表格、记录或精确 Locator 读取已发布 HTML，并返回所需上下文。
# 分页以“目标片段及其依赖”为完整单位，避免数字返回了但表头、单位或脚注被截掉。
"""Read source targets with indivisible, returned context dependencies."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, digest
from ..contracts.query import BlockTarget, TableTarget, RecordTarget, LocatorTarget
from ..retrieval.cursors import position, advance
from .evidence import source_evidence, text_fragments, result_item


# 读取表头、相邻原文和脚注；缺乏显式表头关联时仅标为候选并返回缺口。
def table_context(reader, inventory, table, cells, options):
    values, issues = [], []
    if 'table_headers' in options:
        explicit = {identity for cell in cells for identity in cell['explicit_headers']}
        candidates = {identity for cell in cells for identity in cell['header_candidates']}
        unresolved = []
        for cell in table['cells']:
            if cell['header'] or cell['id'] in explicit or cell['id'] in candidates:
                # 只把原表头标记或显式引用视为已确认；位置推测不能伪装成表头语义。
                confirmed = cell['header'] or cell['id'] in explicit
                kind = 'table_headers' if confirmed else 'table_header_candidate'
                values.append(source_evidence(reader,'table_cell',cell['id'],role='context',context_kind=kind))
                if not confirmed:
                    unresolved.append(cell['id'])
        if unresolved:
            issues.append(dict(code='HEADER_ASSOCIATION_UNCONFIRMED',message='source lacks explicit header markup; literal candidate context returned without claiming semantic association',
                table_id=table['id'],candidate_cell_ids=unresolved))
    if 'units' in options:
        for block_id in table['context_block_ids']:
            for value in text_fragments(reader,block_id):
                value.update(role='context',context_kind='table_adjacent_source')
                values.append(value)
    if 'footnotes' in options:
        for path in sorted({p for c in cells for p in c['footnote_paths']}):
            block = next((b for b in inventory['blocks'] if b['locator']['dom_path']==path),None)
            if block is None:
                issues.append(dict(code='FOOTNOTE_NOT_RETURNED',message='footnote target has no published text block',dom_path=path))
            else:
                for value in text_fragments(reader,block['id']):
                    value.update(role='context',context_kind='footnotes')
                    values.append(value)
    return values, issues


# 按请求补充章节标题与相邻块，均保留独立原文出处，不生成解释性内容。
def block_context(reader, inventory, block, options, neighbors):
    values = []
    if 'section_title' in options and block['section_id']:
        section = next(s for s in inventory['sections'] if s['id']==block['section_id'])
        value = source_evidence(reader,'block',section['block_id'],role='context',context_kind='section_title')
        values.append(value)
    if 'neighbors' in options:
        blocks = inventory['blocks']
        where = next(i for i,b in enumerate(blocks) if b['id']==block['id'])
        for adjacent in blocks[max(0,where-neighbors.before):where+neighbors.after+1]:
            if adjacent['id'] != block['id']:
                for value in text_fragments(reader,adjacent['id']):
                    value.update(role='context',context_kind='neighbors')
                    values.append(value)
    return values


# 将已验证的定位地址映射回已发布投影，优先使用记录/单元格等更具体视图。
def locator_values(reader, locator, max_chars):
    """Resolve only a published projection, never reinterpret a caller locator."""
    reader._dom.resolve(locator)
    candidates = [('block',b.id,b.locator) for b in reader._items['blocks']]
    candidates += [('table_cell',c.id,c.locator) for _,c in reader._cells.values()]
    candidates += [('record_field',r.id,r.locator) for r in reader._items['records']]
    matches = [(kind,key,base) for kind,key,base in candidates if base.dom_path==locator.dom_path
        and base.projection==locator.projection and base.char_start<=locator.char_start<=locator.char_end<=base.char_end]
    if not matches:
        raise CatalogError('TARGET_NOT_FOUND','locator has no matching published source projection')
    # A table cell may also be a block. Prefer the more specific published view.
    priority = {'record_field':0,'table_cell':1,'block':2}
    kind,key,base = min(matches,key=lambda v:priority[v[0]])
    start,end = locator.char_start-base.char_start,locator.char_end-base.char_start
    if kind=='block':
        return list(text_fragments(reader,key,start=start,end=end,max_chars=max_chars)), kind, key
    return [source_evidence(reader,kind,key,start=start,end=end)], kind, key


# 解析所有目标及依赖，按预算分页返回实际片段，并列出本页尚未返回的目标。
def read_targets(execution):
    request = execution.request
    if request.include_image or 'continuation' in request.context:
        raise CatalogError('CAPABILITY_UNSUPPORTED','images/continuations require a dedicated reader')
    if request.table_representation != 'full':
        raise CatalogError('CAPABILITY_UNSUPPORTED','compact table serialization is not supported by this version')
    reader = execution.reader(request.asset_ref)
    inventory = reader.inventory()
    tables = {t['id']:t for t in inventory['tables']}
    blocks = {b['id']:b for b in inventory['blocks']}
    all_items, contexts, issues = [], {}, []
    max_chars = max(100,min(500,(request.max_bytes-1500)//4))
    for number,target in enumerate(request.targets):
        execution.check('read_target')
        values, dependent = [], []
        block, table, cells = None, None, []
        if isinstance(target,BlockTarget):
            start,end = target.char_range if target.char_range is not None else (None,None)
            values = list(text_fragments(reader,target.block_id,start=start,end=end,max_chars=max_chars))
            block = blocks[target.block_id]
            table = next((t for t in tables.values() if t['block_id']==target.block_id),None)
            cells = table['cells'] if table else []
        elif isinstance(target,TableTarget):
            table = tables.get(target.table_id)
            if table is None:
                raise CatalogError('TARGET_NOT_FOUND','table does not exist')
            if any(r>=table['row_count'] for r in target.rows) or any(c>=table['column_count'] for c in target.cols):
                raise CatalogError('TARGET_NOT_FOUND','table row/column out of range')
            # A merged cell covers its complete span, not only its top-left slot.
            # 行列选择按合并单元格覆盖范围相交判断，而不只检查左上角坐标。
            cells = [c for c in table['cells'] if (not target.rows or any(c['row']<=r<c['row']+c['row_span'] for r in target.rows))
                and (not target.cols or any(c['col']<=col<c['col']+c['col_span'] for col in target.cols))]
            values = [source_evidence(reader,'table_cell',c['id']) for c in cells]
            block = blocks[table['block_id']]
        elif isinstance(target,RecordTarget):
            values = [source_evidence(reader,'record_field',target.record_id)]
            path = reader._records[target.record_id].locator.dom_path
            table = next((t for t in tables.values() if any(path.startswith(c['locator']['dom_path']+'/') for c in t['cells'])),None)
            if table:
                block = blocks[table['block_id']]
                cells = [c for c in table['cells'] if path.startswith(c['locator']['dom_path']+'/')]
            else:
                ancestors = [b for b in blocks.values() if path.startswith(b['locator']['dom_path']+'/')]
                block = max(ancestors,key=lambda b:len(b['locator']['dom_path'])) if ancestors else None
        elif isinstance(target,LocatorTarget):
            values,kind,key = locator_values(reader,target.locator,max_chars)
            if kind=='block':
                block = blocks[key]
                table = next((t for t in tables.values() if t['block_id']==key),None)
            elif kind=='table_cell':
                table = tables[reader._cells[key][0].id]
                block = blocks[table['block_id']]
            else:
                path = reader._records[key].locator.dom_path
                table = next((t for t in tables.values() if path.startswith(t['locator']['dom_path']+'/')),None)
                ancestors = [b for b in blocks.values() if path.startswith(b['locator']['dom_path']+'/')]
                block = blocks[table['block_id']] if table else max(ancestors,key=lambda b:len(b['locator']['dom_path'])) if ancestors else None
            cells = table['cells'] if table else []
            if kind=='table_cell':
                cells = [c for c in cells if c['id']==key]
            elif kind=='record_field':
                cells = [c for c in cells if path.startswith(c['locator']['dom_path']+'/')]
        else:
            raise CatalogError('CAPABILITY_UNSUPPORTED','image evidence is outside this HTML text tool version')
        if block:
            dependent += block_context(reader,inventory,block,request.context,request.neighbors)
        if table:
            added,gaps = table_context(reader,inventory,table,cells,request.context)
            dependent += added
            issues += gaps
        keys = []
        for value in dependent:
            # 同一上下文可被多个目标共享；先去重，再让目标引用同一个返回结果。
            key = digest(canonical(value))
            if key not in contexts:
                contexts[key] = result_item(execution.session,execution.operation,'evidence',value)
            keys.append(key)
        for value in values:
            value['requested_target_index'] = number
            value['dependency_refs'] = [contexts[key]['result_ref'] for key in dict.fromkeys(keys)]
            all_items.append((result_item(execution.session,execution.operation,'evidence',value),keys))
    version = digest(canonical(request.asset_ref.model_dump(mode='json')))
    offset = position(execution.session,execution.tool,request,version)
    if offset>len(all_items):
        raise CatalogError('CURSOR_EXPIRED','cursor outside current source view')
    selected,required,end = [],{},offset
    while end<len(all_items):
        item,keys = all_items[end]
        # 先计算加入当前目标后的全部依赖，再决定是否装入本页，保证依赖闭合。
        proposed = required | {key:contexts[key] for key in keys}
        # Include envelope slack. The service also enforces the final full size.
        if len(canonical(dict(items=selected+[item],context_evidence=list(proposed.values()))))>request.max_bytes-1200:
            break
        selected.append(item)
        required = proposed
        end += 1
    if end==offset and end<len(all_items):
        issues.append(dict(code='ITEM_TOO_LARGE',message='source item and required context exceed budget; narrow context or increase max_bytes'))
    cursor = advance(execution.session,execution.tool,request,version,end) if end<len(all_items) else None
    returned = sorted({v['requested_target_index'] for v in selected})
    unread = [dict(target=i,reason='not_returned_on_this_page') for i in range(len(request.targets)) if i not in returned]
    return execution.response(selected,cursor=cursor,truncated=bool(cursor),issues=issues,context_evidence=list(required.values()),
        coverage=dict(status='partial' if cursor or unread or issues else 'complete',requested_targets=len(request.targets),
            returned_targets=returned,unread=unread,returned_source_fragments=len(selected),matching_source_fragments=len(all_items)))
