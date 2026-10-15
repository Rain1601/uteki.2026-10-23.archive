"""Typed record query, explicit operand resolution and bounded visible dependencies."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, digest
from ..retrieval.cursors import position, advance
from ..application.evidence import record_item, result_item
from .calculations import calculate


def execute_records(execution):
    request = execution.request
    reader = execution.reader(request.asset_ref)
    inventory = reader.inventory()
    if not inventory['records']:
        raise CatalogError('CAPABILITY_UNSUPPORTED','source has no inline records')
    allowed_fields = {'record_id','concept_id','value','raw_value','status','period','unit','dimensions','entity_identifier',
        'entity_scheme','context_ref','decimals','scale','sign','duplicate_group','issues','locator','source_object','source_url',
        'context_source','unit_source','asset_ref','result_ref'}
    if not set(request.select.fields) <= allowed_fields:
        raise CatalogError('INVALID_REQUEST','unknown record field')
    rows, main_version = execution.index(request.asset_ref).record_rows(concepts=request.select.concepts,filters=request.filters,order=request.order_by)
    issues, calculated, versions = [], [], {request.asset_ref.build_id:main_version}
    returned_records = {}

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
    version = digest(canonical(versions))
    offset = position(execution.session,execution.tool,request,version)
    if offset > len(rows):
        raise CatalogError('CURSOR_EXPIRED','record cursor outside current view')
    # Keep calculation dependencies visible before admitting a calculation.
    support, calculations = {}, []
    for result, dependencies in calculated:
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
        remaining_support = [v for key,v in support.items() if key not in selected_ids|{identity}]
        size = len(canonical(dict(items=items+[item],supporting_records=remaining_support,calculations=calculations)))
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
