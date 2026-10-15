"""Host-only resolution of one interrupted acquisition; no transport or SDK loop."""
from copy import deepcopy
import json
from pathlib import PurePosixPath
import time

from uteki.infrastructure.run_budget import RunBudget

from ..build.pipeline import build_html, recipe_config
from ..catalog.database import read_regular
from ..content.publication import Publication
from ..content.store import _directory
from ..contracts.assets import Acquisition, BuildRecipe
from ..contracts.common import CatalogError, canonical, digest, nonblank, utc_now
from ..contracts.content import MissingResource, ObjectRef
from ..contracts.query import TOOLS, parse
from ..connectors.recovery import acquired_inputs, confirm_acquisition
from ..connectors.updates import acquisition_result
from .execution_clock import begin_segment, reconcile_time
from .limits import ExecutionLimit
from .session import Session
from .tools import ToolExecution


def owned_run(catalog, context, operation):
    row = catalog._db.execute('SELECT * FROM runs WHERE request_key=?',
        ('acquisition:'+operation['operation_id'],)).fetchone()
    if row is None:
        if operation['effect_intent']['target'].get('run_id') is not None:
            raise CatalogError('RECOVERY_REQUIRED','recorded acquisition run is missing')
        return None
    row = dict(row)
    if (row['parent_run_id']!=context['run_id'] or row['root_run_id']!=context['root_run_id']
            or row['kind']!='build' or operation['effect_intent']['target'].get('run_id',row['run_id'])!=row['run_id']):
        raise CatalogError('RECOVERY_REQUIRED','acquisition run ownership differs')
    return row


def continue_local(execution, frozen):
    catalog, operation = execution.catalog, execution.session.data['operations'][execution.operation]
    plan_ref, plan, report, inputs, usage = frozen
    target = operation['effect_intent']['target']
    recipe = BuildRecipe.model_validate(target['recipe'])
    recipe_config(catalog.content,recipe)
    input_ref = ObjectRef.model_validate(target['input_ref'])
    execution.check('resolution_before_local_work')
    run = owned_run(catalog,execution.context,operation)
    if run is not None and run['status']=='completed':
        return confirm_acquisition(catalog,execution.context,operation,execution.request,checkpoint=execution.check)
    if run is None:
        run = catalog.start_run('acquisition:'+execution.operation,purpose='explicit approved source update',
            kind='build',parent_run_id=execution.context['run_id'])
    if run['status']!='running':
        raise CatalogError('RECOVERY_REQUIRED','terminal acquisition requires confirmation or closure, not a new attempt')
    execution.prepare_acquisition(run_id=run['run_id'])
    main = next(r for r in report['discovery'] if r['status']=='fetched' and r['source_url']==plan.main_url)
    acquisition = Acquisition(source_id=plan.source_id,request_url=plan.main_url,final_url=inputs.main_source_url,
        acquired_at=main['retrieved_at'],published_at=plan.published_at,available_at=plan.available_at,
        source_revised_at=plan.source_revised_at)
    snapshot = catalog.begin_snapshot(execution.operation+':snapshot',asset_id=plan.asset_id,acquisition=acquisition,
        completeness='partial' if any(isinstance(r,MissingResource) for r in inputs.resources) else 'complete',
        version_consistency=plan.version_consistency,revision_of_snapshot_id=plan.revision_of_snapshot_id,
        revision_basis=plan.revision_basis,run_id=run['run_id'])
    row = catalog.get_snapshot(snapshot)
    if row['run_id']!=run['run_id'] or target.get('snapshot_id',snapshot)!=snapshot:
        raise CatalogError('RECOVERY_REQUIRED','original snapshot ownership or identity differs')
    representation = catalog._existing('representation',execution.operation+':html',
        dict(snapshot_id=snapshot,format='html',input_manifest=input_ref.model_dump()))
    if representation is None:
        representation = catalog.add_representation(execution.operation+':html',snapshot_id=snapshot,
            format='html',input_manifest=input_ref)
    registered = catalog._get('snapshot_representations','representation_id',representation)
    if (target.get('representation_id',representation)!=representation or registered['snapshot_id']!=snapshot
            or registered['format']!='html' or json.loads(registered['input_ref'])!=target['input_ref']):
        raise CatalogError('RECOVERY_REQUIRED','original representation differs')
    relations = catalog.snapshot_relations(snapshot)
    if not relations:
        catalog.relate_snapshot(snapshot,plan.relation)
    elif relations!=[plan.relation.model_dump(mode='json')]:
        raise CatalogError('RECOVERY_REQUIRED','original snapshot relations differ')
    execution.prepare_acquisition(snapshot_id=snapshot,representation_id=representation)
    publisher = Publication(catalog,checkpoint=execution.check)
    publisher.continue_snapshot(snapshot)
    execution.check('resolution_snapshot_frozen')
    build = catalog.begin_build(snapshot_id=snapshot,representation_id=representation,recipe=recipe,run_id=run['run_id'])
    if build['run_id']!=run['run_id']:
        raise CatalogError('RECOVERY_REQUIRED','build belongs to a different acquisition')
    if publisher.build_path(build,final=True).exists() or build['status']=='published':
        publisher.commit_build(build['build_id'])
        reference = catalog.asset_ref(catalog.get_build(build['build_id']))
    elif build['manifest_ref'] is not None:
        # A sealed candidate is verified as-is, never reparsed to repair damage.
        reference = publisher.publish(build['build_id'])
    else:
        reference = build_html(catalog,snapshot_id=snapshot,representation_id=representation,recipe=recipe,
            run_id=run['run_id'],checkpoint=execution.check)
    catalog.finish_run(run['run_id'],status='completed')
    execution.check('resolution_build_published')
    return acquisition_result(catalog,reference,inputs,usage,plan_ref,execution.operation,report['run_id'])


def close_local(catalog, context, operation, checkpoint):
    """Retain every receipt/file; fail only candidates owned by this operation."""
    target = operation['effect_intent']['target']
    if target.get('plan_ref'):
        catalog.content.read_object(ObjectRef.model_validate(target['plan_ref']))
    if target.get('input_ref'):
        catalog.content.read_manifest(ObjectRef.model_validate(target['input_ref']))
    receipt = None
    if target.get('receipt_ref'):
        raw = catalog.content.read_object(ObjectRef.model_validate(target['receipt_ref']))
        receipt = json.loads(raw)
        if canonical(receipt)!=raw or receipt['run_id']!=target.get('source_run_id'):
            raise CatalogError('RECOVERY_REQUIRED','acquisition receipt binding differs')
        workspace = catalog.root/'acquisitions'/operation['operation_id']
        for item in receipt['discovery']:
            if item['status']!='fetched':continue
            relative = PurePosixPath(item['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise CatalogError('RECOVERY_REQUIRED','receipt source path is outside its acquisition')
            parent = workspace
            _directory(parent,create=False)
            for part in relative.parts[:-1]:
                parent = parent/part
                _directory(parent,create=False)
            if digest(read_regular(parent/relative.name))!=item['content_sha256']:
                raise CatalogError('RECOVERY_REQUIRED','retained acquisition original is damaged')
    transport = receipt.get('transport_state') if receipt else None
    journal_version = receipt.get('transport_journal_version') if receipt else target.get('transport_journal_version')
    unknown = (journal_version!='uteki-acquisition-transport-v1'
        or transport is not None and transport['status']=='dispatched')
    run = owned_run(catalog,context,operation)
    retained = dict(acquisition_target=deepcopy(target),transport_outcome_unknown=unknown,
        transport_state=deepcopy(transport),snapshots=[],builds=[])
    if run is None:return retained
    publisher = Publication(catalog)
    snapshots = [dict(r) for r in catalog._db.execute('SELECT * FROM asset_snapshots WHERE run_id=?',(run['run_id'],))]
    builds = [dict(r) for r in catalog._db.execute('SELECT * FROM asset_builds WHERE run_id=?',(run['run_id'],))]
    # Validate all visible publications before changing any candidate state.
    for build in builds:
        if build['status']=='published' or publisher.build_path(build,final=True).exists():
            raise CatalogError('RECOVERY_REQUIRED','existing final build must be confirmed; closure cannot revoke publication')
    for snapshot in snapshots:
        if snapshot['status']=='frozen' or publisher.snapshot_path(snapshot,final=True).exists():
            publisher.verify_snapshot(snapshot['snapshot_id'])
    for build in builds:
        if build['status']=='staging':catalog.fail_build(build['build_id'],failure_code='ACQUISITION_CLOSED')
        retained['builds'].append(catalog.get_build(build['build_id']))
        checkpoint('resolution_build_closed')
    for snapshot in snapshots:
        if snapshot['status']=='collecting':
            if publisher.snapshot_path(snapshot,final=True).exists():publisher.commit_snapshot(snapshot['snapshot_id'])
            else:publisher.fail_snapshot(snapshot['snapshot_id'],'ACQUISITION_CLOSED')
        retained['snapshots'].append(catalog.get_snapshot(snapshot['snapshot_id']))
        checkpoint('resolution_snapshot_closed')
    if run['status']=='running':catalog.finish_run(run['run_id'],status='failed',failure_code='ACQUISITION_CLOSED')
    checkpoint('resolution_run_closed')
    return retained


def resolve_update(service, context_ref, *, request_key, action, checkpoint=None, should_cancel=None):
    """No new request parameters/URLs. An explicit host decision binds the action."""
    from ..service import error_response
    nonblank(request_key)
    if not isinstance(action,str) or action not in {'continue_local','close'}:
        raise CatalogError('INVALID_REQUEST','choose continue_local or close')
    checkpoint = checkpoint or (lambda phase: None)
    session = Session(service.catalog,context_ref)
    operation = next((o for o in session.data['operations'].values() if o['request_key']==request_key),None)
    if (operation is None or operation['tool']!='request_asset_update'
            or operation.get('effect_intent',{}).get('kind')!='official_acquisition'):
        raise CatalogError('RECOVERY_REQUIRED','no original acquisition intent')
    request = parse(TOOLS['request_asset_update'],operation['request'])
    if request.action!='acquire':raise CatalogError('INVALID_REQUEST','only acquisition can be resolved here')
    resolution = operation.get('resolution')
    close_after_continue = resolution and resolution['action']=='continue_local' and action=='close' and operation['status']=='accepted' and operation.get('response_intent') is None
    if resolution and resolution['action']!=action and not close_after_continue:
        raise CatalogError('IDEMPOTENCY_CONFLICT','original resolution action differs')
    if operation['status']=='completed':return deepcopy(operation['response'])
    if operation.get('response_intent') is not None:
        intent = operation['response_intent']
        return session.complete(operation['operation_id'],intent['response'],intent['elapsed_seconds'])
    if session.data['status']!='open':raise CatalogError('INVALID_STATE','context is already terminal')
    execution = ToolExecution(service.catalog,session,operation['tool'],request,checkpoint=checkpoint,should_cancel=should_cancel)
    execution.operation = operation['operation_id']
    execution.resource_usage = deepcopy(operation.get('resource_usage',{}))
    frozen = None
    if action=='continue_local':
        adapter = service.acquisition_adapter
        if adapter is None:raise CatalogError('RECOVERY_REQUIRED','original acquisition adapter binding is required')
        signed = dict(tool=operation['tool'],request=operation['request'],state=operation['state'],adapter_binding=adapter.binding())
        if digest(canonical(signed))!=operation['fingerprint']:
            raise CatalogError('IDEMPOTENCY_CONFLICT','acquisition adapter binding changed')
        execution.preflight()
        frozen = acquired_inputs(service.catalog,operation,request)
        if adapter.validate(execution)!=frozen[1]:raise CatalogError('RECOVERY_REQUIRED','frozen plan differs')
        recipe_config(service.catalog.content,BuildRecipe.model_validate(operation['effect_intent']['target']['recipe']))
    native = session.data.get('native_execution')
    accounted = reconcile_time(session) if native else None
    if accounted is None and (native or action=='continue_local'):
        raise CatalogError('RECOVERY_REQUIRED','observed original worker exit is required')
    if action=='continue_local':
        root_session = session.root_session()
        path = 'runs/'+session.data['context']['root_run_id']+'/budget.sqlite'
        if native['ledger_path']!=path:raise CatalogError('RECOVERY_REQUIRED','root ledger binding differs')
        budget = RunBudget.open_existing(service.catalog.root/path,
            root_session.data['context']['request']['run_policy']['max_usd'],root_run_id=session.data['context']['root_run_id'])
        root = budget.inspect_root()
        if (root['stop_reason'] or root['cost']['over_limit'] or budget.summary()['unknown_requests']
                or root['request_stages'].get('dispatched') or root['request_stages'].get('outcome_unknown')):
            raise CatalogError('RECOVERY_REQUIRED','root stopped or has unresolved requests/cost; local continuation denied')
        if accounted['timed_out']:raise CatalogError('BUDGET_EXCEEDED','original worker timed out')
    started = time.monotonic()
    if action=='continue_local':
        execution.limit = ExecutionLimit(session.data['context']['request']['run_policy']['max_wall_seconds']
            -session.data['wall_seconds'],started=started,should_cancel=should_cancel)
        execution.check('resolution_preflight_complete')
    if close_after_continue:
        operation.setdefault('resolution_history',[]).append(deepcopy(resolution))
        operation['resolution'] = dict(action=action,requested_at=utc_now(),
            previous_elapsed_lower_bound=operation.get('elapsed_lower_bound'))
    elif resolution is None:
        operation['resolution'] = dict(action=action,requested_at=utc_now(),
            previous_elapsed_lower_bound=operation.get('elapsed_lower_bound'))
    if native:
        prior = max(native['elapsed_seconds'],native.get('prior_elapsed_seconds',0.0)+accounted['native_elapsed_upper'])
        begin_segment(session,started=started,prior_elapsed=prior)
    else:
        session.data['execution_time_uncertain'] = dict(operation_id=operation['operation_id'],
            reason='closed without an observed native clock',elapsed_lower_bound=operation.get('elapsed_lower_bound',0.0))
        session.save()
    checkpoint('resolution_started')
    if action=='continue_local':
        result = continue_local(execution,frozen)
        response = execution.response([result],issues=[dict(code='ACQUISITION_PARTIAL',message=g) for g in result['gaps']])
        service._register_response(session,operation['operation_id'],operation['tool'],request,response)
    else:
        retained = close_local(service.catalog,session.data['context'],operation,checkpoint)
        proof = service.catalog.content.put_object(canonical(retained)).model_dump(mode='json')
        response = error_response(operation['operation_id'],CatalogError('ACQUISITION_CLOSED','host closed interrupted acquisition; receipts and original bytes retained'))
        response['error']['details'] = dict(retained_ref=proof,transport_outcome_unknown=retained['transport_outcome_unknown'])
        session.data['no_progress_turns'] += 1
    elapsed = time.monotonic()-started
    # An older synchronous operation has no reconciled native clock. Charge its
    # persisted lower bound once, but never call that lower bound complete time.
    lower = operation.get('elapsed_lower_bound',0.0) if accounted is None else 0.0
    response['resource_usage'] = dict(execution.resource_usage,elapsed_ms=None,
        resolution_elapsed_ms=round(elapsed*1000,3),execution_time_uncertain=accounted is None,
        original_elapsed_lower_bound_ms=round(lower*1000,3) if accounted is None else None)
    response['recovery'] = dict(kind=action,original_operation_id=operation['operation_id'])
    operation['resolution']['completed_at'] = utc_now()
    session.prepare_response(operation['operation_id'],response,elapsed+lower)
    checkpoint('resolution_response_prepared')
    result = session.complete(operation['operation_id'],response,elapsed+lower)
    checkpoint('resolution_response_committed')
    return result
