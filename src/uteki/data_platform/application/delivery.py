"""Copy registered, actually returned results into an immutable dependency closure."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, new_id, utc_now
from .session import ref_key


def assemble(session, request, state, plan):
    needs = {n.need_id:n for n in request.needs}
    planned = {n['need_id'] for n in plan['needs']}
    if len(needs) != len(request.needs) or set(needs) != planned:
        raise CatalogError('INVALID_REQUEST','delivery must cover every registered need exactly once')
    satisfied = {n.need_id:n for n in state.satisfied}
    gaps = {n.need_id:n for n in state.gaps}
    conflicts = {c.need_id for c in request.conflicts}
    if not conflicts <= planned:
        raise CatalogError('INVALID_REQUEST','conflict refers to unknown need')
    roots = []
    for name, need in needs.items():
        if need.status == 'supported':
            if not need.result_refs or need.gaps or name in conflicts or name not in satisfied:
                raise CatalogError('INVALID_REQUEST','supported need has a gap, conflict or inconsistent state')
            expected = satisfied[name].result_refs
            for reference in need.result_refs:
                value = session.lookup(reference)
                if reference.kind == 'calculation' and value.get('value') is None:
                    raise CatalogError('INVALID_REQUEST','invalid calculation cannot support a completed numerical need')
        else:
            if not need.gaps or name not in gaps:
                raise CatalogError('INVALID_REQUEST','partial/unresolved needs require explicit gaps and matching state')
            expected = gaps[name].result_refs
            if gaps[name].missing not in need.gaps:
                raise CatalogError('INVALID_REQUEST','delivery omitted the accepted state gap')
        if {ref_key(r) for r in expected} != {ref_key(r) for r in need.result_refs}:
            raise CatalogError('RESULT_REF_INVALID','delivery and task-state result references differ')
        roots.extend(need.result_refs)
    for conflict in request.conflicts:
        roots.extend(conflict.result_refs)
    visited, active = {}, set()

    def visit(reference):
        key = ref_key(reference)
        if key in active:
            raise CatalogError('RESULT_REF_INVALID','cyclic evidence dependencies')
        if key in visited:
            return
        active.add(key)
        item = session.lookup(reference)
        for dependency in item.get('dependency_refs',[]) + item.get('operand_refs',[]):
            visit(dependency)
        active.remove(key)
        visited[key] = item

    for reference in roots:
        visit(reference)
    groups = {'evidence':[], 'record':[], 'calculation':[]}
    assets = {}
    for item in visited.values():
        kind = item['result_ref']['kind']
        groups[kind].append(item)
        if kind != 'calculation':
            if 'asset_ref' not in item or 'locator' not in item:
                raise CatalogError('RESULT_REF_INVALID','original result lacks a frozen source binding')
            assets[canonical(item['asset_ref'])] = item['asset_ref']
    context = session.data['context']
    return dict(schema_version='uteki-delivery-v1',delivery_id=new_id('dl'),context_ref=context['context_ref'],
        run_id=context['run_id'],root_run_id=context['root_run_id'],prior_delivery_refs=context['request']['caller']['prior_delivery_refs'],
        needs_plan=plan,needs=[n.model_dump(mode='json') | {'note_origin':'caller_statement_not_semantically_verified'} for n in request.needs],
        evidence=groups['evidence'],records=groups['record'],calculations=groups['calculation'],
        assets_used=[assets[k] for k in sorted(assets)], conflicts=[c.model_dump(mode='json') for c in request.conflicts],
        gaps=[dict(need_id=n.need_id,reason=g) for n in request.needs for g in n.gaps],
        search_log_ref=dict(run_id=context['run_id'],session_revision=session.data['revision']),
        usage=dict(model_calls=0,cost_usd='0',unknown_cost_reserved_usd='0',wall_seconds=session.data['wall_seconds']),
        stop_reason='delivered',created_at=utc_now(),business_sufficiency_evaluated=False)
