"""Durable business completion and explicit host closure; no SDK loop/history edits."""
from copy import deepcopy
import json
import os
import time

from uteki.infrastructure.run_budget import RunBudget

from ..contracts.common import CatalogError, canonical, nonblank, utc_now
from ..contracts.content import ObjectRef
from ..contracts.run import RunQueryResult
from .execution_clock import begin_segment, reconcile_time
from .session import Session


def result_value(session, budget, outcome):
    value=deepcopy(outcome)
    delivery=value.get('delivery') or value.get('committed_delivery')
    clarification=value.get('clarification') or value.get('committed_clarification')
    if delivery is not None or clarification is not None:
        value.update(native_error=value.get('native_error') or value.get('error'),error=None,
            kind='delivery' if delivery else 'needs_clarification',
            status=delivery['delivery'].get('business_status','completed') if delivery else 'needs_clarification',
            delivery=delivery,clarification=clarification)
    native=session.data['native_execution'];context=session.data['context']
    root=budget.inspect_root()
    uncertain=bool(native.get('execution_time_uncertain') or session.data.get('execution_time_uncertain'))
    unknown_transports=[]
    for operation in session.data['operations'].values():
        details=((operation.get('response') or {}).get('error') or {}).get('details') or {}
        if details.get('transport_outcome_unknown'):
            reference=details['retained_ref']
            session.catalog.content.read_object(ObjectRef.model_validate(reference))
            unknown_transports.append(dict(operation_id=operation['operation_id'],retained_ref=reference))
    value['runtime']=dict(context_ref=context['context_ref'],run_id=context['run_id'],root_run_id=context['root_run_id'],
        native_session_id=native['native_session_id'],budget=root,elapsed_seconds=native['elapsed_seconds'],
        execution_time_uncertain=uncertain,unknown_transports=unknown_transports)
    from .recovery_clock import recovery_seconds
    value['runtime'].update(wall_seconds=session.data['wall_seconds'],host_recovery_seconds=recovery_seconds(native),
        timing_scope='through_result_preparation')
    for key in ('time_reconciliation','time_reconciliation_failures','close_intent'):
        if native.get(key) is not None:value['runtime'][key]=deepcopy(native[key])
    value.update(schema_version='uteki-run-query-result-v1',terminal=value['kind']!='recovery_required',
        reconciliation_required=bool(value['kind']=='recovery_required' or uncertain or unknown_transports or budget.summary()['unknown_requests']
            or root['request_stages'].get('outcome_unknown') or root['request_stages'].get('dispatched')))
    return RunQueryResult.model_validate(value).model_dump(mode='json')


def validate_result(session, value):
    """Validate immutable result bindings, including any already accepted package."""
    RunQueryResult.model_validate(value)
    native=session.data['native_execution'];context=session.data['context']
    if (any(value['runtime'].get(k)!=context[k] for k in ('context_ref','run_id','root_run_id'))
            or value['runtime'].get('native_session_id')!=native['native_session_id']
            or value['profile']!=native['binding']['profile']
            or value['runtime']['budget']['root_run_id']!=context['root_run_id']):
        raise CatalogError('RECOVERY_REQUIRED','runtime result binding differs')
    for kind in ('delivery','clarification'):
        response=value.get(kind)
        if response is None:
            if session.data.get(kind) is not None:
                raise CatalogError('RECOVERY_REQUIRED','runtime result omits a committed business package')
            continue
        saved=session.data.get(kind)
        if not saved or response[kind+'_object']!=saved['object_ref']:
            raise CatalogError('RECOVERY_REQUIRED','runtime result has no matching committed package')
        if session.catalog.content.read_object(ObjectRef.model_validate(saved['object_ref']))!=canonical(response[kind]):
            raise CatalogError('RECOVERY_REQUIRED','runtime result package differs from immutable bytes')


def commit_result(session, *, checkpoint=None):
    checkpoint=checkpoint or (lambda phase:None)
    native=session.data['native_execution'];intent=native['outcome_intent']
    raw=session.catalog.content.read_object(ObjectRef.model_validate(intent['object_ref']))
    value=json.loads(raw)
    if canonical(value)!=raw:raise CatalogError('RECOVERY_REQUIRED','noncanonical runtime result')
    validate_result(session,value)
    if not value['terminal']:raise CatalogError('RECOVERY_REQUIRED','nonterminal result cannot end a run')
    status='failed' if value['kind']=='failed' else 'needs_clarification' if value['kind']=='needs_clarification' else (
        'cancelled' if value['status']=='cancelled' else 'completed')
    expected_code='RUN_CLOSED' if native.get('close_intent') else 'RUNTIME_FAILED'
    if intent.get('failure_code')!=(expected_code if status=='failed' else None):
        raise CatalogError('RECOVERY_REQUIRED','runtime result failure identity differs')
    if any(o['status'] not in {'completed','closed'} for o in session.data['operations'].values()):
        raise CatalogError('RECOVERY_REQUIRED','runtime completion has an unresolved business operation')
    if session.data['status'] not in {'open',status}:
        raise CatalogError('RECOVERY_REQUIRED','business terminal state differs from result intent')
    if session.data['status']!=status:
        session.data['status']=status;session.save()
    checkpoint('runtime_session_terminal')
    session.catalog.finish_run(session.data['context']['run_id'],
        status='completed' if status=='needs_clarification' else status,failure_code=intent['failure_code'])
    checkpoint('runtime_catalog_terminal')
    native.update(phase='terminal',outcome=value,outcome_object=intent['object_ref'])
    session.save()
    checkpoint('native_outcome_committed')
    return deepcopy(value)


def save_result(session, budget, outcome, *, checkpoint=None):
    checkpoint=checkpoint or (lambda phase:None)
    value=result_value(session,budget,outcome)
    validate_result(session,value)
    native=session.data['native_execution']
    if not value['terminal']:
        native.update(phase='recovery_required',outcome=value)
        session.save();checkpoint('native_outcome_committed')
        return deepcopy(value)
    reference=session.catalog.content.put_object(canonical(value)).model_dump(mode='json')
    intent=dict(object_ref=reference,failure_code=(
        'RUN_CLOSED' if native.get('close_intent') else 'RUNTIME_FAILED') if value['kind']=='failed' else None)
    if native.get('outcome_intent') is not None and native['outcome_intent']!=intent:
        raise CatalogError('RECOVERY_REQUIRED','another result was already prepared; confirm the original intent')
    native['outcome_intent']=intent
    session.save();checkpoint('native_outcome_prepared')
    return commit_result(session,checkpoint=checkpoint)


def read_result(session):
    native=session.data.get('native_execution') or {}
    value=native.get('outcome')
    if value and value.get('schema_version')=='uteki-run-query-result-v1':
        validate_result(session,value)
        if value['terminal']:
            reference=native.get('outcome_object')
            if reference!=native.get('outcome_intent',{}).get('object_ref') or not reference:
                raise CatalogError('RECOVERY_REQUIRED','terminal runtime lacks its immutable result')
            if session.catalog.content.read_object(ObjectRef.model_validate(reference))!=canonical(value):
                raise CatalogError('RECOVERY_REQUIRED','saved runtime outcome differs from immutable result')
            row=session.catalog._get('runs','run_id',session.data['context']['run_id'])
            expected='failed' if value['kind']=='failed' else 'cancelled' if value['status']=='cancelled' else 'completed'
            business='needs_clarification' if value['kind']=='needs_clarification' else expected
            if (session.data['status']!=business or row['status']!=expected
                    or row['failure_code']!=native['outcome_intent']['failure_code']):
                raise CatalogError('RECOVERY_REQUIRED','catalog lacks the result terminal confirmation')
    return deepcopy(value)


def close_run(service, context_ref, *, request_key, reason, checkpoint=None):
    """Close an observed, abandoned native run; retain unknown costs and history."""
    started=time.monotonic();checkpoint=checkpoint or (lambda phase:None)
    nonblank(request_key);nonblank(reason)
    active=getattr(service.catalog,'_native_executions',{}).get(context_ref)
    if active is not None and not active['task'].done():
        raise CatalogError('INVALID_STATE','live SDK task must be cancelled and observed before host closure')
    session=Session(service.catalog,context_ref);native=session.data.get('native_execution')
    if native is None:raise CatalogError('INVALID_STATE','no native execution to close')
    context=session.data['context'];root=session.root_session()
    expected='runs/'+context['root_run_id']+'/budget.sqlite'
    if native['ledger_path']!=expected:raise CatalogError('RECOVERY_REQUIRED','root ledger path differs')
    budget=RunBudget.open_existing(service.catalog.root/expected,root.data['context']['request']['run_policy']['max_usd'],
        root_run_id=context['root_run_id'])
    saved=native.get('close_intent')
    if saved and (saved['request_key'],saved['reason'])!=(request_key,reason):
        raise CatalogError('IDEMPOTENCY_CONFLICT','closure identity or reason differs')
    if native.get('outcome_intent'):
        if not saved:raise CatalogError('INVALID_STATE','existing terminal intent must be confirmed, not replaced')
        if native.get('outcome_object'):return read_result(session)
        return commit_result(session,checkpoint=checkpoint)
    if saved is None:
        if session.data['status']!='open' or any(o['tool'] in {'deliver','clarify'} for o in session.data['operations'].values()):
            raise CatalogError('INVALID_STATE','existing delivery/clarification cannot be revoked by closure')
        abandoned=[]
        for op in session.data['operations'].values():
            if op['status']=='completed':continue
            if (op['status']!='accepted' or op['tool'] not in
                    {'find_assets','get_asset_schema','search_asset','read_evidence','query_records'}
                    or op.get('effect_intent') is not None or op.get('response_intent') is not None):
                raise CatalogError('RECOVERY_REQUIRED','confirm or close original business effects/responses before closing the run')
            abandoned.append(op['operation_id'])
        if service.catalog._db.execute("SELECT 1 FROM runs WHERE parent_run_id=? AND status='running'",
                (session.data['context']['run_id'],)).fetchone():
            raise CatalogError('RECOVERY_REQUIRED','an owned child run remains open')
        accounted=reconcile_time(session)
        if accounted is None:raise CatalogError('RECOVERY_REQUIRED','actual worker exit observation is required for closure')
        prior=max(native['elapsed_seconds'],native.get('prior_elapsed_seconds',0.0)+accounted['native_elapsed_upper'])
        saved=dict(request_key=request_key,reason=reason,abandoned_operation_ids=abandoned,
            at=utc_now(),prior_head=session.head_ref.model_dump(mode='json'))
        native['close_intent']=saved
        begin_segment(session,started=started,prior_elapsed=prior)
        checkpoint('run_close_prepared')
    elif native.get('owner_pid')!=os.getpid():
        accounted=reconcile_time(session)
        if accounted is None:raise CatalogError('RECOVERY_REQUIRED','interrupted closure worker exit is not confirmed')
        begin_segment(session,started=started,prior_elapsed=max(native['elapsed_seconds'],
            native.get('prior_elapsed_seconds',0.0)+accounted['native_elapsed_upper']))
    budget.stop_root('run_closed');budget.recover_requests()
    for request in budget.inspect_requests():
        if request['stage']=='prepared':budget.abandon_prepared(request['request_key'],reason='run_closed_before_dispatch')
    checkpoint('run_close_root_stopped')
    for identity in saved['abandoned_operation_ids']:
        op=session.data['operations'][identity]
        if op['status'] not in {'accepted','closed'}:raise CatalogError('RECOVERY_REQUIRED','abandoned operation changed')
        op.update(status='closed',closure=dict(reason=reason,request_key=request_key,at=saved['at']))
    elapsed=max(0.0,time.monotonic()-native['execution_clock']['started_monotonic'])
    native['elapsed_seconds']=native['prior_elapsed_seconds']+elapsed
    session.data['wall_seconds']=max(session.data['wall_seconds'],native['execution_clock']['initial_wall_seconds']+elapsed)
    session.save();checkpoint('run_close_operations_closed')
    return save_result(session,budget,dict(kind='failed',status='failed',error='RUN_CLOSED',native_success=False,
        native_error='UNCONFIRMED_NATIVE_COMPLETION',delivery=None,clarification=None,
        committed_delivery=None,committed_clarification=None,profile=native['binding']['profile'],
        native_events=[dict(type='host_closed_without_sdk_restart')],tool_events=[],
        mode='offline',real_model_calls=0,gateway_cost_usd=None),checkpoint=checkpoint)
