"""Persistent evaluation-batch binding; the existing RunBudget owns all money.

This module creates no SDK session and performs no network or authorization.
A batch consists of explicit independent business roots in one Catalog.
"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import uuid

from uteki.infrastructure.run_budget import RunBudget
from ..catalog.database import ensure_directory, read_regular
from ..contracts.common import CatalogError, canonical, digest
from ..contracts.content import ObjectRef
from ..contracts.run import RuntimeLimits
from .session import Session

SCHEMA='uteki-gateway-batch-v1'


def _plan(catalog, batch_id, scopes, limit_usd, max_requests, origin, contract_sha256):
    if str(uuid.UUID(batch_id))!=batch_id:raise ValueError('canonical batch UUID required')
    amount=Decimal(str(limit_usd))
    if not amount.is_finite() or amount<=0:raise ValueError('positive batch limit required')
    if type(max_requests) is not int or max_requests<1:raise ValueError('positive physical request limit required')
    if origin not in {'synthetic','openrouter'}:raise ValueError('explicit execution origin required')
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
        if Decimal(context['request']['run_policy']['max_usd'])!=amount:
            raise CatalogError('SCOPE_VIOLATION','each scope must retain the same frozen batch monetary ceiling')
        limits=RuntimeLimits.model_validate(item['limits']).model_dump(mode='json')
        if limits['max_model_requests']>max_requests:raise ValueError('scope cannot expand batch request limit')
        profile=deepcopy(item['profile']);transport=deepcopy(item['transport'])
        if not isinstance(profile,dict) or profile.get('kernel') not in {'openai','claude'}:
            raise ValueError('explicit SDK profile required')
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


def _root_policy(plan):
    return dict(gateway_batch_plan_sha256=digest(canonical(plan)),execution_contract_sha256=plan['execution_contract_sha256'])


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


def _open_batch(catalog, reference, descriptor):
    plan=descriptor['plan'];directory=catalog.root/'gateway-batches'/plan['batch_id']
    enabled=catalog._existing('gateway-batch-enabled',plan['batch_id'],plan)
    if enabled is None or ObjectRef.model_validate_json(enabled)!=reference:
        raise CatalogError('RECOVERY_REQUIRED','batch has no durable activation confirmation')
    if read_regular(directory/'ready.json')!=canonical(reference.model_dump(mode='json')):
        raise CatalogError('RECOVERY_REQUIRED','batch readiness binding is missing or differs')
    budget=RunBudget.open_existing(directory/'budget.sqlite',plan['limit_usd'],root_run_id=plan['batch_id'])
    root=budget.inspect_root()
    expected=dict(mode='remote',max_requests=plan['max_requests'],max_in_flight_requests=1,
        scope_ids=[s['scope_id'] for s in plan['scopes']],policy=_root_policy(plan))
    if any(root.get(key)!=value for key,value in expected.items()):
        raise CatalogError('RECOVERY_REQUIRED','enabled batch contract differs; never recreate it')
    for scope in plan['scopes']:
        current=budget.inspect_scope(scope['scope_id'])
        if any(current.get(key)!=scope[key] for key in ('scope_id','max_requests','policy')):
            raise CatalogError('RECOVERY_REQUIRED','enabled scope contract differs')
    return budget


def load_gateway_binding(session, binding, profile, limits, *, open_ledger=True):
    """Validate both catalog ownership and exact immutable business/native inputs."""
    try:
        if set(binding)!={'batch_ref','scope_id'}:raise ValueError('exact gateway binding fields required')
        reference=ObjectRef.model_validate(binding['batch_ref'])
        raw=session.catalog.content.read_object(reference);descriptor=json.loads(raw)
        if canonical(descriptor)!=raw or set(descriptor)!={'plan','ledger_image'}:raise ValueError('invalid batch descriptor')
        plan=descriptor['plan']
        if plan['schema_version']!=SCHEMA or str(uuid.UUID(plan['batch_id']))!=plan['batch_id']:
            raise ValueError('invalid batch identity')
        registered=session.catalog._existing('gateway-batch',plan['batch_id'],plan)
        if registered is None or ObjectRef.model_validate_json(registered)!=reference:
            raise ValueError('batch is not owned by this catalog')
        scope=next(s for s in plan['scopes'] if s['scope_id']==binding['scope_id'])
        context=session.data['context'];policy=scope['policy']
        if (policy['context_ref']!=context['context_ref'] or policy['business_root_run_id']!=context['root_run_id']
                or policy['context_sha256']!=digest(canonical(context)) or policy['profile']!=profile
                or policy['limits']!=limits):
            raise ValueError('business context, profile or limits differ from frozen scope')
        value=dict(binding=deepcopy(binding),plan=plan,scope=scope,
            ledger_path='gateway-batches/'+plan['batch_id']+'/budget.sqlite',
            mode='gateway_synthetic' if plan['origin']=='synthetic' else 'remote')
        if open_ledger:value['budget']=_open_batch(session.catalog,reference,descriptor)
        return value
    except (KeyError,TypeError,ValueError,StopIteration,OSError,sqlite3.Error) as error:
        raise CatalogError('RECOVERY_REQUIRED','gateway batch binding is missing, corrupt or inconsistent') from error


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
