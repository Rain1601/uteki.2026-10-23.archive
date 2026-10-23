# 澄清是原问题的受限续接：一个已提交追问只绑定一份回答和一个子上下文。
# 子上下文继承累计消耗与需求计划，但必须重新读取证据，不能借澄清扩大范围或重置预算。
"""A clarification has one immutable answer binding and one child context."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json

from ..contracts.common import CatalogError, canonical
from ..contracts.content import ObjectRef
from .session import Session


# 验证被续接上下文确已完成匹配的澄清，且原执行与恢复计时均无未确认状态。
def parent_session(catalog, request):
    if request.revises_context_ref is None:
        return None
    if request.clarification_response is None:
        raise CatalogError('CAPABILITY_UNSUPPORTED','non-clarification continuation requires its explicit handoff contract')
    parent = Session(catalog,request.revises_context_ref)
    if parent.data.get('execution_time_uncertain'):
        raise CatalogError('RECOVERY_REQUIRED','unconfirmed tool execution time cannot be reset by clarification')
    saved = parent.data.get('clarification')
    if parent.data['status']!='needs_clarification' or saved is None:
        raise CatalogError('CLARIFICATION_MISMATCH','parent has no committed clarification')
    record = json.loads(catalog.content.read_object(ObjectRef.model_validate(saved['object_ref'])))
    if (saved['clarification_id']!=request.clarification_response.clarification_id
            or record['clarification_id']!=saved['clarification_id']
            or record['context_ref']!=request.revises_context_ref):
        raise CatalogError('CLARIFICATION_MISMATCH','answer does not match the original clarification')
    native = parent.data.get('native_execution')
    if native and (native['phase']!='terminal' or native['outcome'] is None):
        raise CatalogError('RECOVERY_REQUIRED','parent native execution must finish or explicitly recover before continuing')
    from .recovery_clock import pending_recoveries
    if native and (native.get('execution_time_uncertain') or pending_recoveries(native)
            or native.get('completion_clock',{}).get('status')=='pending'):
        raise CatalogError('RECOVERY_REQUIRED','unconfirmed prior execution time cannot be reset by clarification')
    return parent


# 逐项检查问题、调用者、公司、期间、来源及额度；回答只能保持或缩小原授权范围。
def validate_narrowing(parent, request, company_ids, read_policy):
    before = parent.data['context']
    old, new = before['request'], request.context_payload()
    if (old.get('required_securities') and
            {canonical(s) for s in old['required_securities']} !=
            {canonical(s) for s in new.get('required_securities',[])}):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot remove or replace required security lookups')
    if old.get('documents') or new.get('documents'):
        prior_documents, next_documents = old.get('documents'), new.get('documents')
        if (not prior_documents or not next_documents
                or prior_documents['data_root'] != next_documents['data_root']
                or not {canonical(b) for b in next_documents['bindings']} <= {canonical(b) for b in prior_documents['bindings']}):
            raise CatalogError('SCOPE_VIOLATION','clarification cannot change the store or widen document versions/bindings')
    if new['question']!=old['question'] or new['caller']!=old['caller']:
        raise CatalogError('CLARIFICATION_MISMATCH','original question and caller must be preserved')
    if not set(company_ids)<=set(before['company_ids']):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot add another company')
    for key,value in new['run_policy'].items():
        if Decimal(str(value))>Decimal(str(old['run_policy'][key])):
            raise CatalogError('SCOPE_VIOLATION','clarification cannot increase '+key)
    if old['as_of'] is not None and (new['as_of'] is None or datetime.fromisoformat(new['as_of'])>datetime.fromisoformat(old['as_of'])):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot expand the source cutoff')
    if old['periods']:
        if not new['periods'] or not all(any(all(p[k] is None or q[k]==p[k]
            for k in ('label','fiscal_year','fiscal_quarter','start','end')) for p in old['periods']) for q in new['periods']):
            raise CatalogError('SCOPE_VIOLATION','clarification cannot remove or replace a known fiscal-period constraint')
    policy = read_policy.model_dump(mode='json')
    prior = before['read_policy']
    if not set(policy['source_kinds'])<=set(prior['source_kinds']):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot add source kinds')
    if prior['source_ids'] and (not policy['source_ids'] or not set(policy['source_ids'])<=set(prior['source_ids'])):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot add source IDs')
    a,b = old['expansion'],new['expansion']
    if b['mode']=='controlled' and (a['mode']!='controlled'
            or not all(rule in a['allow'] or rule.split(':',1)[0] in a['allow'] for rule in b['allow'])
            or not all(rule in b['deny'] or rule.split(':',1)[0] in b['deny'] for rule in a['deny'])):
        raise CatalogError('SCOPE_VIOLATION','clarification cannot expand acquisition/processing permissions')


# 在目录事务中绑定澄清 ID、回答内容与请求键；相同回答的不同调用键归并到原始子运行。
def bind_answer(catalog, parent, request, policy, request_key, *, recover, checkpoint):
    """Existing registration transactions enforce both caller keys and answer IDs."""
    binding = dict(request=request.context_payload(),read_policy=policy.model_dump(mode='json'))
    identity = request.clarification_response.clarification_id
    try:
        first = catalog._existing('data-clarification-answer',identity,binding)
    except CatalogError as error:
        if error.code=='IDEMPOTENCY_CONFLICT':
            raise CatalogError('CLARIFICATION_MISMATCH','this clarification already has a different answer/context') from error
        raise
    # 先前已登记的回答拥有唯一原始键；调用者换键不能创建第二份子上下文。
    original_key = first or request_key
    run = catalog._db.execute('SELECT parent_run_id FROM runs WHERE request_key=?',('data-context:'+request_key,)).fetchone()
    if run is not None and (request_key!=original_key or run['parent_run_id']!=parent.data['context']['run_id']):
        raise CatalogError('IDEMPOTENCY_CONFLICT','request key already belongs to another run')
    alias = catalog._existing('data-context-submission',request_key,binding)
    if alias is not None and alias!=original_key:
        raise CatalogError('IDEMPOTENCY_CONFLICT','request key is already bound to another context')
    if first is not None and not recover and catalog._db.execute('SELECT run_id FROM runs WHERE request_key=?',
            ('data-context:'+original_key,)).fetchone() is None:
        raise CatalogError('RECOVERY_REQUIRED','answer binding is durable but child creation is incomplete; use recover=True')
    with catalog.database.transaction():
        if first is None:catalog._register_key('data-clarification-answer',identity,binding,original_key)
        if alias is None:catalog._register_key('data-context-submission',request_key,binding,original_key)
    checkpoint('clarification_answer_registered')
    return original_key


# 复制计划和累计计数，但把所有需求重新标为待核验，不复制旧运行的可用结果引用。
def inherited_state(parent):
    from .evidence import metadata_history
    data = parent.data
    value = {k:deepcopy(data[k]) for k in ('plan','plan_history','turns','wall_seconds','no_progress_turns','seen_results')}
    value['seen_updates'] = deepcopy(data.get('seen_updates',[]))
    value['seen_metadata'] = sorted(metadata_history(parent))
    if data.get('time_reconciliations'):
        value['time_reconciliations']=deepcopy(data['time_reconciliations'])
    value['inherited_state'] = deepcopy(data['state'])
    # 保留需求意图而重置证据满足状态：旧 ResultRef 属于父运行，不能直接冒充新运行已读。
    value['state'] = dict(plan_update=None,satisfied=[],gaps=[dict(need_id=n['need_id'],
        missing='Revalidate this need after clarification; previous-run evidence is not yet reread',result_refs=[])
        for n in data['plan']['needs']],next_action='pending_model_decision',reason='Continue with inherited plan and explicit answer')
    return value
