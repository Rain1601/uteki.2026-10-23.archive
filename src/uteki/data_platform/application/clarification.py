"""A clarification has one immutable answer binding and one child context."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json

from ..contracts.common import CatalogError
from ..contracts.content import ObjectRef
from .session import Session


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


def validate_narrowing(parent, request, company_ids, read_policy):
    before = parent.data['context']
    old, new = before['request'], request.context_payload()
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


def inherited_state(parent):
    data = parent.data
    value = {k:deepcopy(data[k]) for k in ('plan','plan_history','turns','wall_seconds','no_progress_turns','seen_results')}
    value['seen_updates'] = deepcopy(data.get('seen_updates',[]))
    if data.get('time_reconciliations'):
        value['time_reconciliations']=deepcopy(data['time_reconciliations'])
    value['inherited_state'] = deepcopy(data['state'])
    value['state'] = dict(plan_update=None,satisfied=[],gaps=[dict(need_id=n['need_id'],
        missing='Revalidate this need after clarification; previous-run evidence is not yet reread',result_refs=[])
        for n in data['plan']['needs']],next_action='pending_model_decision',reason='Continue with inherited plan and explicit answer')
    return value
