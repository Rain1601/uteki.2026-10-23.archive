"""Typed record query, explicit operand resolution and bounded visible dependencies."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, digest
from ..retrieval.cursors import position, advance
from ..application.evidence import record_item, result_item
from .calculations import calculate


# 查询主记录并解析跨构建计算操作数；将必要来源记录与计算结果共同纳入分页预算。
def execute_records(execution):
    request = execution.request
    reader = execution.reader(request.asset_ref)
    inventory = reader.inventory()
    if not inventory['records']:
        raise CatalogError('CAPABILITY_UNSUPPORTED','source has no inline records')
    request.select.validate_fields()
    rows, main_version = execution.index(request.asset_ref).record_rows(concepts=request.select.concepts,filters=request.filters,order=request.order_by)
    issues, calculated, versions = [], [], {request.asset_ref.build_id:main_version}
    returned_records = {}

    # 按完整版本加记录 ID 缓存结果，避免同一事实同时作为主结果和操作数时重复生成引用。
    def as_item(reference, record):
        key = canonical([reference.model_dump(mode='json'),record['id']])
        if key not in returned_records:
            returned_records[key] = result_item(execution.session,execution.operation,'record',record_item(execution.reader(reference),record))
        return returned_records[key]

    for spec in request.calculations:
        execution.check('calculation_operands')
        resolved, dependencies, resolution_issues = [], [], []
        for operand in spec.operands:
            selected, token = execution.index(operand.asset_ref).record_rows(selector=operand.record_selector)
            versions[operand.asset_ref.build_id] = token
            # 操作数必须唯一命中一条来源出现记录；重复值也不能自动挑一个，否则会隐藏来源歧义。
            if len(selected) != 1:
                resolution_issues.append(dict(code='OPERAND_AMBIGUOUS' if selected else 'OPERAND_MISSING',
                    message='selector must identify one source occurrence',asset_ref=operand.asset_ref.model_dump(mode='json'),
                    candidate_record_ids=[r['id'] for r in selected],selector=operand.record_selector.model_dump(mode='json')))
            else:
                resolved.append(selected[0])
                dependencies.append(as_item(operand.asset_ref,selected[0]))
        result = calculate(spec,resolved)
        if resolution_issues:
            result['value'] = None
            result['limitations'] += [i['code'] for i in resolution_issues]
            issues.extend(resolution_issues)
        result['operand_refs'] = [v['result_ref'] for v in dependencies]
        calculated.append((result_item(execution.session,execution.operation,'calculation',result),dependencies))
        if result['limitations']:
            issues.append(dict(code='CALCULATION_UNRESOLVED',message='; '.join(result['limitations']),calc_id=spec.calc_id))
    # 分页版本包含主查询和所有计算操作数的索引 token，任何参与构建的索引更新都会令旧游标过期。
    version = digest(canonical(versions))
    offset = position(execution.session,execution.tool,request,version)
    if offset > len(rows):
        raise CatalogError('CURSOR_EXPIRED','record cursor outside current view')
    # Keep calculation dependencies visible before admitting a calculation.
    support, calculations = {}, []
    for result, dependencies in calculated:
        # 先计入完整依赖再决定是否接纳计算；预算不够时省略该计算并报缺口，不返回失去依据的数字。
        new_support = support | {canonical(v['result_ref']):v for v in dependencies}
        size = len(canonical(dict(items=[],supporting_records=list(new_support.values()),calculations=calculations+[result])))
        if len(new_support) > request.limit or size > request.max_bytes-1000:
            issues.append(dict(code='CALC_DEPENDENCIES_TOO_LARGE',message='calculation omitted because dependencies exceed record/byte limit',calc_id=result['calc_id']))
            continue
        support = new_support
        calculations.append(result)
    items = []
    selected_ids = set()
    end = offset
    truncated = False
    while end < len(rows):
        execution.check('query_record')
        item = as_item(request.asset_ref,rows[end])
        identity = canonical(item['result_ref'])
        total = selected_ids | set(support) | {identity}
        if len(total)>request.limit:
            break
        # 已作为主结果返回的操作数不再重复列为 supporting_records，但两者共享唯一记录数量限制。
        remaining_support = [v for key,v in support.items() if key not in selected_ids|{identity}]
        size = len(canonical(dict(items=items+[item],supporting_records=remaining_support,calculations=calculations)))
        # 为响应元数据预留 1000 字节；当前行放不下时不前移游标，避免在分页中静默丢记录。
        if size > request.max_bytes-1000:
            truncated = True
            break
        items.append(item)
        selected_ids.add(identity)
        end += 1
    if end==offset and end<len(rows):
        issues.append(dict(code='OUTPUT_LIMIT',message='page cannot advance with this limit; increase it or separate calculations from record pagination'))
    cursor = advance(execution.session,execution.tool,request,version,end) if end<len(rows) else None
    return execution.response(items,cursor=cursor,truncated=truncated,issues=issues,
        supporting_records=[v for key,v in support.items() if key not in selected_ids],calculations=calculations,
        coverage=dict(status='partial' if issues or truncated else 'complete',matching_records=len(rows),
            returned_records=len(selected_ids|set(support)),record_states_retained=True,index_versions=versions))
