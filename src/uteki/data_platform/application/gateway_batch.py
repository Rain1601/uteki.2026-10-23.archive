"""Persistent evaluation-batch binding; the existing RunBudget owns all money.

This module creates no SDK session and performs no network or authorization.
A batch consists of explicit independent business roots in one Catalog.
"""
from copy import deepcopy
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import uuid

from uteki.data_platform.application.run_budget import RunBudget
from ..catalog.database import ensure_directory, read_regular
from ..contracts.common import CatalogError, canonical, digest, new_id, nonblank, utc_now
from ..contracts.content import ObjectRef
from ..contracts.run import RuntimeLimits
from .session import Session

SCHEMA='uteki-gateway-batch-v1'


# 同一额度范围内的新执行可调整 SDK 控制和显式请求字节上限；不增加钱、次数或改变业务输入。
def validate_execution_policy(original, current):
    """A new session may use the confirmed SDK controls, never a new allowance."""
    if set(current)!=set(original):raise ValueError('execution policy fields differ')
    for name, permitted in (('limits',{'max_request_bytes'}),('transport',{'max_request_bytes','reserve_usd'})):
        if ({k:v for k,v in current[name].items() if k not in permitted}
                != {k:v for k,v in original[name].items() if k not in permitted}):
            raise ValueError('new execution cannot change other transport or runtime limits')
    size=current['limits']['max_request_bytes']
    if (type(size) is not int or size<original['limits']['max_request_bytes']
            or current['transport']['max_request_bytes']!=size):
        raise ValueError('explicit consistent request byte bound required')
    reservation=Decimal(current['transport']['reserve_usd'])
    if not reservation.is_finite() or reservation<Decimal(original['transport']['reserve_usd']):
        raise ValueError('request reservation cannot be reduced')
    allowed={'sdk_version','parallel_tool_calls','mcp_max_result_chars'}
    if ({k:v for k,v in current['profile'].items() if k not in allowed}
            != {k:v for k,v in original['profile'].items() if k not in allowed}):
        raise ValueError('new execution cannot change model, route, prompt or business capabilities')
    for key in ('context_ref','business_root_run_id','context_sha256'):
        nonblank(current[key])


# 比较业务输入时排除新会话生成的身份和创建时间，其余问题、时钟、实体及读取策略必须一致。
def _business_context(context):
    return {k:v for k,v in context.items() if k not in {'context_ref','run_id','root_run_id','created_at'}}


# 在原 batch/scope 上登记新会话，不新建账本；共享原请求次数、累计费用及停止状态。
def prepare_gateway_attempt(catalog, binding, profile, *, request_key, max_request_bytes=None):
    """Register a fresh session against an existing lane; no new ledger or SDK run."""
    nonblank(request_key)
    if set(binding)!={'batch_ref','scope_id'}:
        raise ValueError('start from the original batch binding, not another attempt')
    descriptor=json.loads(catalog.content.read_object(ObjectRef.model_validate(binding['batch_ref'])))
    original=next(s for s in descriptor['plan']['scopes'] if s['scope_id']==binding['scope_id'])['policy']
    prior=Session(catalog,original['context_ref'])
    gateway=load_gateway_binding(prior,binding,original['profile'],original['limits'])
    from ..agent.profiles import Profile
    Profile.model_validate_json(json.dumps(profile))
    proposed=deepcopy(original) | {'profile':profile}
    identity=dict(base_binding=deepcopy(binding),profile=deepcopy(profile))
    if max_request_bytes is not None:
        if type(max_request_bytes) is not int or max_request_bytes<original['limits']['max_request_bytes']:
            raise ValueError('request byte override must be an explicit increase')
        proposed['limits']['max_request_bytes']=max_request_bytes
        proposed['transport']['max_request_bytes']=max_request_bytes
        if descriptor['plan']['origin']=='live':
            from ..agent.providers.live_policy import price_tokens
            contract=descriptor.get('execution_contract')
            if contract is None:raise ValueError('request byte revision requires the registered live contract')
            pricing=contract['scopes'][binding['scope_id']]['pricing']
            proposed['transport']['reserve_usd']=str(max(Decimal(original['transport']['reserve_usd']),
                price_tokens(pricing,max_request_bytes+16384,profile['max_output_tokens'])))
        if Decimal(proposed['transport']['reserve_usd'])>Decimal(gateway['budget'].inspect_root()['limit_usd']):
            raise ValueError('maximum request reservation exceeds the existing batch allowance')
        identity['max_request_bytes']=max_request_bytes
    validate_execution_policy(original,proposed)
    # 同一幂等键只能复用同一绑定和配置；已有登记需再次完整核验后才能返回。
    stored=catalog._existing('gateway-attempt',request_key,identity)
    if stored is not None:
        reference=ObjectRef.model_validate_json(stored)
        attempt=json.loads(catalog.content.read_object(reference))
        result=dict(binding=deepcopy(binding) | {'attempt_ref':reference.model_dump(mode='json')},
                    context_ref=attempt['policy']['context_ref'])
        load_gateway_binding(Session(catalog,result['context_ref']),result['binding'],profile,proposed['limits'])
        return result
    budget=gateway['budget'];root=budget.inspect_root();scope=budget.inspect_scope(binding['scope_id'])
    if root['policy']!=_root_policy(descriptor['plan']):
        raise CatalogError('RUN_STOPPED','use the current authorized batch revision for new execution')
    if root['stop_reason'] or scope['stop_reason']:
        raise CatalogError('RUN_STOPPED','original root or lane is stopped; a new session cannot reopen it')
    occupied=lambda stages:sum(n for stage,n in stages.items() if stage!='abandoned')
    if occupied(root['request_stages'])>=root['max_requests'] or occupied(scope['request_stages'])>=scope['max_requests']:
        raise CatalogError('BUDGET_EXCEEDED','original request allowance is exhausted')
    # 根账本仍有待发送、已发未确认或未知请求时，必须先恢复处置，不能靠新会话绕过。
    if any(root['request_stages'].get(stage) for stage in ('prepared','dispatched','outcome_unknown')):
        raise CatalogError('RECOVERY_REQUIRED','resolve pending or uncertain requests before a fresh session')
    native=prior.data.get('native_execution')
    if native and not native.get('outcome_object'):
        raise CatalogError('RECOVERY_REQUIRED','original native execution has no confirmed outcome')
    context=deepcopy(prior.data['context'])
    context.update(context_ref=new_id('req'),created_at=utc_now())
    context.pop('run_id');context.pop('root_run_id')
    # Session.create retains the exact frozen question, clock, entities and
    # read policy, and its existing durable request-key recovery semantics.
    # 新建的是独立业务根会话，冻结输入保持不变，费用和请求额度仍落在原控制范围。
    session=Session.create(catalog,context,'gateway-attempt:'+request_key,recover=True)
    context=session.data['context']
    policy=proposed | dict(context_ref=context['context_ref'],business_root_run_id=context['root_run_id'],
        context_sha256=digest(canonical(context)),profile=deepcopy(profile))
    attempt=dict(schema_version='uteki-gateway-attempt-v1',request_key=request_key,**identity,policy=policy)
    reference=catalog.content.put_object(canonical(attempt))
    with catalog.database.transaction():
        catalog._register_key('gateway-attempt',request_key,identity,reference.model_dump_json())
    return dict(binding=deepcopy(binding) | {'attempt_ref':reference.model_dump(mode='json')},
                context_ref=context['context_ref'])


# 校验并冻结批次计划：每个 scope 对应独立业务根，统一共享批次额度且物理请求串行。
def _plan(catalog, batch_id, scopes, limit_usd, max_requests, origin, contract_sha256):
    if str(uuid.UUID(batch_id))!=batch_id:raise ValueError('canonical batch UUID required')
    amount=Decimal(str(limit_usd))
    if not amount.is_finite() or amount<=0:raise ValueError('positive batch limit required')
    if type(max_requests) is not int or max_requests<1:raise ValueError('positive physical request limit required')
    if origin not in {'synthetic','openrouter','live'}:raise ValueError('explicit execution origin required')
    if not isinstance(contract_sha256,str) or len(contract_sha256)!=64 or any(c not in '0123456789abcdef' for c in contract_sha256):
        raise ValueError('explicit execution contract hash required')
    if not isinstance(scopes,list) or not scopes:raise ValueError('explicit scope list required')
    frozen=[];ids=set();contexts=set()
    for item in scopes:
        if set(item)!={'scope_id','context_ref','profile','limits','transport'}:raise ValueError('exact scope fields required')
        scope_id=item['scope_id']
        if not isinstance(scope_id,str) or not scope_id.strip() or scope_id in ids:raise ValueError('unique scope ID required')
        context=Session(catalog,item['context_ref']).data['context']
        if context['run_id']!=context['root_run_id'] or item['context_ref'] in contexts:
            raise CatalogError('SCOPE_VIOLATION','each batch scope requires a distinct explicit business root')
        # 各业务根保留同一批次金额上限，不把各 scope 的声明额度相加成新的总预算。
        if Decimal(context['request']['run_policy']['max_usd'])!=amount:
            raise CatalogError('SCOPE_VIOLATION','each scope must retain the same frozen batch monetary ceiling')
        limits=RuntimeLimits.model_validate(item['limits']).model_dump(mode='json')
        if limits['max_model_requests']>max_requests:raise ValueError('scope cannot expand batch request limit')
        profile=deepcopy(item['profile']);transport=deepcopy(item['transport'])
        if not isinstance(profile,dict) or profile.get('kernel') not in {'openai','claude'}:
            raise ValueError('explicit SDK profile required')
        # 运行层与传输层的字节限制必须一致，单次费用预留和超时也不能越过业务上限。
        if (set(transport)!={'max_request_bytes','max_response_bytes','request_timeout_seconds','reserve_usd'}
                or transport['max_request_bytes']!=limits['max_request_bytes']
                or transport['max_response_bytes']!=limits['max_response_bytes']):
            raise ValueError('transport byte limits must equal runtime limits')
        reserve=Decimal(str(transport['reserve_usd']))
        duration=Decimal(str(transport['request_timeout_seconds']))
        if (not reserve.is_finite() or not 0<reserve<=amount or not duration.is_finite()
                or not 0<duration<=Decimal(str(context['request']['run_policy']['max_wall_seconds']))):
            raise ValueError('bounded positive request reservation and timeout required')
        ids.add(scope_id);contexts.add(item['context_ref'])
        frozen.append(dict(scope_id=scope_id,max_requests=limits['max_model_requests'],policy=dict(
            context_ref=item['context_ref'],business_root_run_id=context['root_run_id'],context_sha256=digest(canonical(context)),
            profile=profile,limits=limits,transport=transport)))
    return dict(schema_version=SCHEMA,batch_id=batch_id,origin=origin,limit_usd=str(amount),max_requests=max_requests,
        max_in_flight_requests=1,execution_contract_sha256=contract_sha256,scopes=sorted(frozen,key=lambda item:item['scope_id']))


# 根策略绑定完整计划和授权契约摘要；live 模式保留仅有用量估算时的费用预留。
def _root_policy(plan):
    policy=dict(gateway_batch_plan_sha256=digest(canonical(plan)),execution_contract_sha256=plan['execution_contract_sha256'])
    if plan['origin']=='live':policy['retain_usage_estimate_reservations']=True
    if plan.get('spending_limits'):policy['spending_limits']=deepcopy(plan['spending_limits'])
    return policy


# 先冻结空账本镜像及创建意图，再发布账本和就绪标记；启用后的账本丢失不能重建。
def create_gateway_batch(catalog, *, batch_id, scopes, limit_usd, max_requests, origin, contract_sha256,
                         recover=False, checkpoint=None):
    """Freeze an empty ledger image before publishing; never recreate an enabled ledger."""
    from .runtime_initialization import _publish
    checkpoint=checkpoint or (lambda phase:None)
    if type(recover) is not bool:raise ValueError('explicit recovery boolean required')
    plan=_plan(catalog,batch_id,scopes,limit_usd,max_requests,origin,contract_sha256)
    directory=ensure_directory(catalog.root,'gateway-batches/'+batch_id)
    stored=catalog._existing('gateway-batch',batch_id,plan)
    if stored is None:
        if any(directory.iterdir()):raise CatalogError('RECOVERY_REQUIRED','unbound batch files cannot be adopted')
        with tempfile.TemporaryDirectory(prefix='.batch-image-',dir=directory) as temporary:
            budget=RunBudget(Path(temporary)/'empty.sqlite',plan['limit_usd'])
            budget.bind_root(batch_id,mode='remote',max_requests=plan['max_requests'],
                max_in_flight_requests=1,scope_ids=[s['scope_id'] for s in plan['scopes']],policy=_root_policy(plan))
            for scope in plan['scopes']:budget.bind_scope(**scope)
            image=catalog.content.put_object(budget.path.read_bytes())
        # 保存精确空账本原件，崩溃恢复只能继续发布该镜像，不能重新生成另一份起始账本。
        descriptor=dict(plan=plan,ledger_image=image.model_dump(mode='json'))
        reference=catalog.content.put_object(canonical(descriptor))
        with catalog.database.transaction():
            catalog._register_key('gateway-batch',batch_id,plan,reference.model_dump_json())
        checkpoint('gateway_batch_intent_saved')
    else:
        reference=ObjectRef.model_validate_json(stored)
        descriptor=json.loads(catalog.content.read_object(reference))
        if descriptor['plan']!=plan:raise CatalogError('RECOVERY_REQUIRED','frozen batch plan differs')
        if catalog._existing('gateway-batch-enabled',batch_id,plan) is None and not recover:
            raise CatalogError('RECOVERY_REQUIRED','repeat original batch creation with explicit recovery')
    # 只有尚未启用的批次可以继续首次发布；数据库中的启用记录最后提交。
    if catalog._existing('gateway-batch-enabled',batch_id,plan) is None:
        raw=catalog.content.read_object(ObjectRef.model_validate(descriptor['ledger_image']))
        _publish(directory/'budget.sqlite',raw,checkpoint)
        checkpoint('gateway_batch_ledger_published')
        _publish(directory/'ready.json',canonical(reference.model_dump(mode='json')),checkpoint)
        with catalog.database.transaction():
            catalog._register_key('gateway-batch-enabled',batch_id,plan,reference.model_dump_json())
        checkpoint('gateway_batch_ready')
    try:_open_batch(catalog,reference,descriptor)
    except (OSError,ValueError,sqlite3.Error) as error:
        raise CatalogError('RECOVERY_REQUIRED','enabled batch ledger or readiness is missing or corrupt; never recreate it') from error
    return {s['scope_id']:dict(batch_ref=reference.model_dump(mode='json'),scope_id=s['scope_id']) for s in plan['scopes']}


# 重新打开时同时核验目录就绪标记、数据库启用记录及账本各 scope，拒绝接管来历不明文件。
def _batch_anchor(catalog, reference, descriptor):
    while 'revision_inputs' in descriptor:
        inputs=descriptor['revision_inputs'];key=inputs['authorization']['authorization_id']
        registered=catalog._existing('gateway-batch-revision',key,inputs)
        if registered is None or ObjectRef.model_validate_json(registered)!=reference:
            raise CatalogError('RECOVERY_REQUIRED','batch revision is not registered')
        reference=ObjectRef.model_validate(inputs['previous_ref'])
        descriptor=json.loads(catalog.content.read_object(reference))
    registered=catalog._existing('gateway-batch',descriptor['plan']['batch_id'],descriptor['plan'])
    if registered is None or ObjectRef.model_validate_json(registered)!=reference:
        raise CatalogError('RECOVERY_REQUIRED','batch is not owned by this catalog')
    return reference,descriptor


def _open_batch(catalog, reference, descriptor):
    plan=descriptor['plan'];directory=catalog.root/'gateway-batches'/plan['batch_id']
    anchor,original=_batch_anchor(catalog,reference,descriptor)
    enabled=catalog._existing('gateway-batch-enabled',plan['batch_id'],original['plan'])
    if enabled is None or ObjectRef.model_validate_json(enabled)!=anchor:
        raise CatalogError('RECOVERY_REQUIRED','batch has no durable activation confirmation')
    if read_regular(directory/'ready.json')!=canonical(anchor.model_dump(mode='json')):
        raise CatalogError('RECOVERY_REQUIRED','batch readiness binding is missing or differs')
    path=directory/'budget.sqlite'
    if not path.is_file() or path.is_symlink():raise ValueError('existing regular ledger required')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        amount=db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
    budget=RunBudget.open_existing(path,amount,root_run_id=plan['batch_id'])
    root=budget.inspect_root()
    expected=dict(mode='remote',root_run_id=plan['batch_id'],limit_usd=plan['limit_usd'],max_requests=plan['max_requests'],max_in_flight_requests=1,
        scope_ids=[s['scope_id'] for s in plan['scopes']],policy=_root_policy(plan))
    if any(root.get(key)!=value for key,value in expected.items()):
        if budget.historical_contract(expected,plan['scopes']):return budget
        raise CatalogError('RECOVERY_REQUIRED','enabled batch contract differs; never recreate it')
    for scope in plan['scopes']:
        current=budget.inspect_scope(scope['scope_id'])
        if any(current.get(key)!=scope[key] for key in ('scope_id','max_requests','policy')):
            raise CatalogError('RECOVERY_REQUIRED','enabled scope contract differs')
    return budget


# 统一校验 Catalog 所有权、批次身份、会话原文摘要、配置与限制，输出可供运行层使用的绑定。
def load_gateway_binding(session, binding, profile, limits, *, open_ledger=True):
    """Validate both catalog ownership and exact immutable business/native inputs."""
    try:
        if set(binding) not in ({'batch_ref','scope_id'},{'batch_ref','scope_id','attempt_ref'}):
            raise ValueError('exact gateway binding fields required')
        reference=ObjectRef.model_validate(binding['batch_ref'])
        raw=session.catalog.content.read_object(reference);descriptor=json.loads(raw)
        if canonical(descriptor)!=raw or set(descriptor) not in (
                {'plan','ledger_image'},
                {'plan','ledger_image','revision_inputs','execution_contract','previous_root'}):
            raise ValueError('invalid batch descriptor')
        plan=descriptor['plan']
        if plan['schema_version']!=SCHEMA or str(uuid.UUID(plan['batch_id']))!=plan['batch_id']:
            raise ValueError('invalid batch identity')
        _batch_anchor(session.catalog,reference,descriptor)
        scope=next(s for s in plan['scopes'] if s['scope_id']==binding['scope_id'])
        context=session.data['context'];policy=scope['policy']
        # 新执行必须有独立登记的 attempt，并证明仅更新了允许的 SDK 控制及新会话身份。
        if 'attempt_ref' in binding:
            attempt_ref=ObjectRef.model_validate(binding['attempt_ref'])
            attempt_raw=session.catalog.content.read_object(attempt_ref);attempt=json.loads(attempt_raw)
            base={k:binding[k] for k in ('batch_ref','scope_id')}
            identity=dict(base_binding=base,profile=profile)
            if 'max_request_bytes' in attempt:
                identity['max_request_bytes']=attempt['max_request_bytes']
                if attempt['max_request_bytes']!=attempt['policy']['limits']['max_request_bytes']:
                    raise ValueError('request byte override differs from registered execution')
            registered=session.catalog._existing('gateway-attempt',attempt['request_key'],identity)
            if (canonical(attempt)!=attempt_raw or attempt.get('schema_version')!='uteki-gateway-attempt-v1'
                    or attempt.get('base_binding')!=base or attempt.get('profile')!=profile
                    or registered is None or ObjectRef.model_validate_json(registered)!=attempt_ref):
                raise ValueError('fresh execution is not registered against this original lane')
            original_context=Session(session.catalog,policy['context_ref']).data['context']
            if (context['context_ref']==original_context['context_ref'] or context['run_id']!=context['root_run_id']
                    or _business_context(context)!=_business_context(original_context)):
                raise ValueError('fresh execution changes the frozen business input')
            validate_execution_policy(policy,attempt['policy'])
            policy=attempt['policy']
        # 最终以当前执行策略绑定精确上下文，防止把另一会话或修改后的问题接到原 scope。
        if (policy['context_ref']!=context['context_ref'] or policy['business_root_run_id']!=context['root_run_id']
                or policy['context_sha256']!=digest(canonical(context)) or policy['profile']!=profile
                or policy['limits']!=limits):
            raise ValueError('business context, profile or limits differ from frozen scope')
        value=dict(binding=deepcopy(binding),plan=plan,scope=scope,execution_policy=deepcopy(policy),
            ledger_path='gateway-batches/'+plan['batch_id']+'/budget.sqlite',
            allowance_revision=descriptor.get('revision_inputs',{}).get('authorization',{}).get('authorization_id'),
            mode='gateway_synthetic' if plan['origin']=='synthetic' else 'remote')
        if open_ledger:value['budget']=_open_batch(session.catalog,reference,descriptor)
        return value
    except (KeyError,TypeError,ValueError,StopIteration,OSError,sqlite3.Error) as error:
        raise CatalogError('RECOVERY_REQUIRED','gateway batch binding is missing, corrupt or inconsistent') from error


# 仅打开原生运行已绑定的既有账本；网关还须证明业务根已完成对该批次的初始化认领。
def open_runtime_budget(session):
    native=session.data['native_execution'];binding=native['binding']
    if binding.get('gateway') is not None:
        gateway=load_gateway_binding(session,binding['gateway'],binding['profile'],binding['limits'])
        if native['ledger_path']!=gateway['ledger_path']:
            raise CatalogError('RECOVERY_REQUIRED','native gateway ledger path differs')
        descriptor=session.root_session().data.get('root_budget')
        root=gateway['budget'].inspect_root()
        marker=(descriptor or {}).get('initialization') or {}
        if (descriptor is None or descriptor.get('gateway')!=binding['gateway']
                or descriptor.get('ledger_path')!=gateway['ledger_path']
                or any(descriptor.get(key)!=root[key] for key in ('mode','max_requests','policy'))
                or marker.get('status')!='ready' or marker.get('context_ref')!=session.data['context']['context_ref']
                or marker.get('native_session_id')!=native['native_session_id']):
            raise CatalogError('RECOVERY_REQUIRED','business root gateway claim is missing or differs')
        return gateway['budget']
    context=session.data['context'];expected='runs/'+context['root_run_id']+'/budget.sqlite'
    if native['ledger_path']!=expected:raise CatalogError('RECOVERY_REQUIRED','stored root ledger path differs')
    root=session.root_session()
    return RunBudget.open_existing(session.catalog.root/expected,root.data['context']['request']['run_policy']['max_usd'],
        root_run_id=context['root_run_id'])
