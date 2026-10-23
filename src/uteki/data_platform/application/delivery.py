# 交付只复制本会话已登记的结果及其依赖，不让模型在终态包中重新填写原文或数值。
# 格式、引用闭包与状态一致性可以确定性校验；这些检查不等于已判断业务证据充分。
"""Copy registered, actually returned results into an immutable dependency closure."""
from __future__ import annotations

from copy import deepcopy

from uteki.infrastructure.run_budget import RunBudget
from ..contracts.common import CatalogError, canonical, new_id, utc_now
from ..contracts.run import DeliveryRequest, TaskState
from .session import ref_key
from .delivery_checks import section_coverage, checked_source_claims


# 从根运行唯一账本读取已核费用、未知/在途预留及调用数，区分合成与真实运行。
def delivery_usage(session):
    root_session = session.root_session()
    native = session.data.get('native_execution') or root_session.data.get('root_budget') or root_session.data.get('native_execution')
    if native is None:
        return dict(model_calls=0,cost_usd='0',unknown_cost_reserved_usd='0',wall_seconds=session.data['wall_seconds'])
    context = session.data['context']
    gateway = None
    if native.get('binding',{}).get('gateway') is not None:
        from .gateway_batch import load_gateway_binding, open_runtime_budget
        budget = open_runtime_budget(session)
        gateway = load_gateway_binding(session,native['binding']['gateway'],native['binding']['profile'],
            native['binding']['limits'],open_ledger=False)
    else:
        expected = 'runs/'+context['root_run_id']+'/budget.sqlite'
        if native['ledger_path'] != expected:
            raise CatalogError('RECOVERY_REQUIRED','delivery ledger differs from its root identity')
        root_policy = root_session.data['context']['request']['run_policy']
        budget = RunBudget.open_existing(session.catalog.root/expected,root_policy['max_usd'],
                                         root_run_id=context['root_run_id'])
    root, summary = budget.inspect_root(), budget.summary()
    calls = sum(v for k,v in root['request_stages'].items() if k in {'dispatched','responded','outcome_unknown'})
    usage = dict(model_calls=calls,real_model_calls=0 if root['mode']=='offline' else calls,
        cost_usd=root['cost']['known_billed_usd'],synthetic_cost_usd=root['cost']['synthetic_cost_usd'],
        unknown_cost_reserved_usd=root['cost']['unknown_reserved_usd'],
        in_flight_reserved_usd=root['cost']['in_flight_reserved_usd'],unknown_requests=summary['unknown_requests'],
        wall_seconds=session.data['wall_seconds'],root_run_id=context['root_run_id'],mode=root['mode'])
    if gateway is not None:
        scope_id=gateway['binding']['scope_id']
        usage.update(mode=gateway['mode'],budget_root_run_id=root['root_run_id'],control_scope_id=scope_id,
            scope_model_calls=sum(r['stage'] in {'dispatched','responded','outcome_unknown'}
                for r in budget.inspect_requests() if r.get('control_scope_id')==scope_id))
        if gateway['mode']=='gateway_synthetic':
            usage.update(real_model_calls=0,cost_usd=None,synthetic_cost_usd=root['cost']['known_billed_usd'])
        # 保留全额预留后继续不代表费用已核实，不能把账本中的确定部分冒充完整实付费用。
        if summary.get('unbilled_bounded_requests'):
            usage.update(cost_usd=None,
                unbilled_bounded_reserved_usd=root['cost']['unbilled_bounded_reserved_usd'],
                provider_billing_verified=False)
    if session.data.get('time_reconciliations'):
        usage['time_reconciliations']=deepcopy(session.data['time_reconciliations'])
    return usage


# 宿主停止时依据最后已接受状态构造部分交付；只保留原生执行中可见的完整证据。
def stopped_request(session, reason, visible_results):
    """Only the last accepted state may support a host-generated partial result."""
    visible = {canonical(r) for r in visible_results}
    plan = session.data['plan']
    update = None
    if not plan['needs']:
        update = dict(base_version=0,needs=[dict(need_id='original-question',
            description=session.data['context']['request']['question'],required=True)])
        planned = update['needs']
    else:
        planned = plan['needs']
    prior = session.data['state'] or dict(satisfied=[],gaps=[])
    supported = {n['need_id']:n for n in prior['satisfied']}
    gaps = {n['need_id']:n for n in prior['gaps']}
    needs, accepted, missing = [], [], []

    # 递归检查结果及全部依赖均已展示；循环依赖属于非法引用。
    def is_visible(reference, active=None):
        key = canonical(reference)
        active = set() if active is None else active
        if key in active:
            raise CatalogError('RESULT_REF_INVALID','cyclic dependencies in stopped execution')
        item = session.lookup(reference)
        if key not in visible:
            return False
        return all(is_visible(r,active | {key}) for r in item.get('dependency_refs',[])+item.get('operand_refs',[]))

    for need in planned:
        identity = need['need_id']
        previous = supported.get(identity) or gaps.get(identity) or {}
        refs = previous.get('result_refs',[])
        usable = [r for r in refs if is_visible(r)]
        # 原来标记满足的需求，只有全部支撑引用都可见时才保持满足，否则降为带缺口的状态。
        if identity in supported and usable and len(usable)==len(refs):
            accepted.append(dict(need_id=identity,result_refs=usable))
            needs.append(dict(need_id=identity,status='supported',result_refs=usable,gaps=[]))
        else:
            gap = previous.get('missing') or 'No confirmed completion before execution stopped: '+reason
            if len(usable)!=len(refs):
                gap += '; some evidence was not visible in this native execution'
            missing.append(dict(need_id=identity,missing=gap,result_refs=usable))
            needs.append(dict(need_id=identity,status='partial' if usable else 'unresolved',result_refs=usable,gaps=[gap]))
    request = DeliveryRequest.model_validate_json(canonical(dict(needs=needs)))
    state = TaskState.model_validate_json(canonical(dict(plan_update=update,satisfied=accepted,gaps=missing,
        next_action='deliver',reason='Host stopped execution: '+reason)))
    return request, state


# 校验每个需求的状态和引用，再递归收集证据闭包，生成可冻结的交付包。
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
        if need.note is not None:
            raise CatalogError('DELIVERY_NOTE_UNSUPPORTED', 'delivery does not accept free-form note; source_claims require exact source quotes, disclosed qualifications go in limitations, and missing work stays in gaps')
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
        # 交付引用必须与已提交任务状态完全一致，防止终态临时换证据或丢弃已知缺口。
        if {ref_key(r) for r in expected} != {ref_key(r) for r in need.result_refs}:
            raise CatalogError('RESULT_REF_INVALID','delivery and task-state result references differ')
        roots.extend(need.result_refs)
    for conflict in request.conflicts:
        roots.extend(conflict.result_refs)
    visited, active = {}, set()

    # 深度遍历证据/操作数依赖并去重；active 用于检测循环，visited 保存已收集结果。
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
    groups = {'evidence':[], 'record':[], 'calculation':[], 'metadata':[]}
    assets = {}
    for item in visited.values():
        kind = item['result_ref']['kind']
        groups[kind].append(item)
        if kind != 'calculation':
            if 'asset_ref' not in item or 'locator' not in item:
                raise CatalogError('RESULT_REF_INVALID','original result lacks a frozen source binding')
            assets[canonical(item['asset_ref'])] = item['asset_ref']
    context = session.data['context']
    delivered_needs = [n.model_dump(mode='json') | dict(
        note_origin='caller_statement_not_semantically_verified',
        source_claims=checked_source_claims(n, visited)) for n in request.needs]
    return dict(schema_version='uteki-delivery-v1',delivery_id=new_id('dl'),context_ref=context['context_ref'],
        run_id=context['run_id'],root_run_id=context['root_run_id'],prior_delivery_refs=context['request']['caller']['prior_delivery_refs'],
        needs_plan=plan,needs=delivered_needs,
        evidence=groups['evidence'],records=groups['record'],calculations=groups['calculation'],
        metadata=groups['metadata'],
        read_coverage=section_coverage(groups['evidence']),
        assets_used=[assets[k] for k in sorted(assets)], conflicts=[c.model_dump(mode='json') for c in request.conflicts],
        gaps=[dict(need_id=n.need_id,reason=g) for n in request.needs for g in n.gaps],
        limitations=[dict(need_id=n.need_id,reason=limitation,origin='caller_statement_not_semantically_verified')
                     for n in request.needs for limitation in n.limitations],
        completion_basis='requested_work_not_source_quality_certification',
        search_log_ref=dict(run_id=context['run_id'],session_revision=session.data['revision']),
        usage=delivery_usage(session),
        stop_reason='delivered',business_status='completed' if all(n.status=='supported' for n in request.needs) else 'partial',
        # 此标志明确：引用与包结构通过，并不代表系统独立验证了整题业务充分性。
        created_at=utc_now(),business_sufficiency_evaluated=False)
