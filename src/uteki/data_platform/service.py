"""Programmatic data tools; no model loop, implicit root, or online fallback."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import time
import sqlite3

import duckdb

from pydantic import ValidationError

from .application.delivery import assemble
from .application.evidence import register_returned
from .application.session import Session
from .contracts.common import CatalogError, canonical, digest, new_id, nonblank, utc_now
from .contracts.content import ObjectRef
from .contracts.query import ContextRequest, ReadPolicy, TOOLS, parse
from .contracts.run import DeliveryRequest, TaskState
from .retrieval.assets import resolve_entities


def error_response(operation_id, error, elapsed=0):
    return dict(operation_id=operation_id,status='error',items=[],next_cursor=None,truncated=False,
        coverage=dict(status='failed'),issues=[],error=dict(code=error.code,message=str(error)),
        resource_usage=dict(elapsed_ms=round(elapsed*1000,3),external_calls=0,model_calls=0,cost_usd='0'))


class DataService:
    def __init__(self, catalog, *, acquisition_adapter=None):
        catalog.database.assert_open()
        self.catalog = catalog
        self.acquisition_adapter = acquisition_adapter

    def create_context(self, request, *, request_key):
        request = parse(ContextRequest,request)
        nonblank(request_key)
        stamp = utc_now()
        clock = request.as_of or datetime.fromisoformat(stamp)
        companies, securities = resolve_entities(self.catalog,request.entities,clock)
        registered = self.catalog._get('policies','policy_ref',request.source_policy_ref)
        policy = parse(ReadPolicy,json.loads(json.loads(registered['payload'])['definition']))
        if request.caller.prior_delivery_refs:
            raise CatalogError('CAPABILITY_UNSUPPORTED','cross-run continuation requires the later runtime contract; explicit evidence can be reread in a new context')
        context = dict(context_ref=new_id('req'),clock=stamp,created_at=stamp,request=request.model_dump(mode='json'),
            company_ids=companies,resolved_entities=[dict(company_id=c,name=self.catalog.get_company(c)['canonical_name']) for c in companies],
            matched_securities=securities,read_policy=policy.model_dump(mode='json'),unresolved=[],continuation=None)
        return deepcopy(Session.create(self.catalog,context,request_key).data['context'])

    def inspect_context(self, context_ref):
        session = Session(self.catalog,context_ref)
        return deepcopy(dict(context=session.data['context'],status=session.data['status'],plan=session.data['plan'],
            state=session.data['state'],turns=session.data['turns'],operations=session.data['operations'],delivery=session.data['delivery']))

    def call(self, context_ref, tool, request, *, state, request_key, should_cancel=None, checkpoint=None):
        from .application.tools import ToolExecution
        operation_id = new_id('op')
        try:
            nonblank(request_key)
            if tool not in TOOLS:
                raise CatalogError('INVALID_REQUEST','unknown data tool')
            request = parse(TOOLS[tool],request)
            state = parse(TaskState,state)
            session = Session(self.catalog,context_ref)
            adapter_binding = None
            if tool=='request_asset_update' and request.action=='acquire' and self.acquisition_adapter is not None:
                adapter_binding = self.acquisition_adapter.binding()
            signed = dict(tool=tool,request=request.model_dump(mode='json'),state=state.model_dump(mode='json'))
            if adapter_binding is not None:
                signed['adapter_binding'] = adapter_binding
            signature = digest(canonical(signed))
            replay = session.replay(request_key,signature)
            if replay is not None:
                return replay
            plan = session.proposed_plan(state,tool)
            if tool=='request_asset_update' and request.need_id not in {n['need_id'] for n in plan['needs']}:
                raise CatalogError('INVALID_REQUEST','update refers to unknown need')
            policy = session.data['context']['request']['run_policy']
            if (session.data['turns'] >= policy['max_turns'] or session.data['wall_seconds'] >= policy['max_wall_seconds']
                    or session.data['no_progress_turns'] >= policy['max_no_progress_turns']):
                raise CatalogError('BUDGET_EXCEEDED','synchronous run limit exhausted')
            if should_cancel is not None and should_cancel():
                raise CatalogError('CANCELLED','cancelled before accepting operation')
            executor = ToolExecution(self.catalog,session,tool,request,should_cancel=should_cancel,checkpoint=checkpoint,
                acquisition_adapter=self.acquisition_adapter)
            executor.preflight()
            operation_id = session.accept(key=request_key,fingerprint=signature,tool=tool,request=request,state=state,plan=plan)
        except ValidationError as error:
            return error_response(operation_id,CatalogError('INVALID_REQUEST',str(error)))
        except CatalogError as error:
            if error.code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
                raise
            return error_response(operation_id,error)
        start = time.monotonic()
        try:
            response = executor.execute(operation_id)
            elapsed = time.monotonic()-start
            if elapsed+session.data['wall_seconds'] > policy['max_wall_seconds']:
                raise CatalogError('BUDGET_EXCEEDED','operation exceeded remaining run wall time')
            if should_cancel is not None and should_cancel():
                raise CatalogError('CANCELLED','cancelled before returning results; inspect update generation if applicable')
            response['resource_usage'] = dict(elapsed_ms=round(elapsed*1000,3),**executor.resource_usage)
            if len(canonical(response)) > getattr(request,'max_bytes',200000):
                raise CatalogError('OUTPUT_LIMIT','complete response exceeds byte budget; narrow targets or increase max_bytes')
            added = register_returned(session,operation_id,response)
            update_progress = False
            if tool=='request_asset_update':
                seen = set(session.data.get('seen_updates',[]))
                for item in response['items']:
                    if item.get('status') in {'completed','partial'} and item.get('new_asset_refs'):
                        key = digest(canonical(dict(action=request.action,assets=item['new_asset_refs'],
                            capabilities=sorted(request.process.capabilities) if request.process else [],gaps=item['gaps'])))
                        update_progress |= key not in seen
                        seen.add(key)
                session.data['seen_updates'] = sorted(seen)
            session.data['no_progress_turns'] = 0 if added or update_progress else session.data['no_progress_turns']+1
        except (CatalogError,OSError,ValueError,sqlite3.DatabaseError,duckdb.Error) as error:
            if isinstance(error,CatalogError) and error.code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
                raise
            elapsed = time.monotonic()-start
            error = error if isinstance(error,CatalogError) else CatalogError('INTERNAL_ERROR',type(error).__name__+': '+str(error))
            response = error_response(operation_id,error,elapsed)
            response['resource_usage'].update(executor.resource_usage)
            session.data['no_progress_turns'] += 1
        result = session.complete(operation_id,response,elapsed)
        if checkpoint is not None:
            checkpoint('response_committed')
        return result

    def deliver(self, context_ref, request, *, state, request_key, checkpoint=None):
        request = parse(DeliveryRequest,request)
        state = parse(TaskState,state)
        session = Session(self.catalog,context_ref)
        signature = digest(canonical(dict(tool='deliver',request=request.model_dump(mode='json'),state=state.model_dump(mode='json'))))
        replay = session.replay(request_key,signature)
        if replay is not None:
            self.catalog.finish_run(session.data['context']['run_id'],status='completed')
            return replay
        plan = session.proposed_plan(state,'deliver')
        package = assemble(session,request,state,plan)
        operation = session.accept(key=request_key,fingerprint=signature,tool='deliver',request=request,state=state,plan=plan)
        if checkpoint is not None:
            checkpoint('delivery_accepted')
        frozen = self.catalog.content.put_object(canonical(package))
        if checkpoint is not None:
            checkpoint('delivery_object_written')
        response = dict(kind='delivery',delivery=package,delivery_object=frozen.model_dump(mode='json'))
        session.data['delivery'] = dict(delivery_id=package['delivery_id'],object_ref=frozen.model_dump(mode='json'))
        session.data['status'] = 'completed'
        result = session.complete(operation,response,0)
        if checkpoint is not None:
            checkpoint('delivery_response_committed')
        self.catalog.finish_run(session.data['context']['run_id'],status='completed')
        return result

    def read_delivery(self, context_ref):
        session = Session(self.catalog,context_ref)
        if session.data['delivery'] is None:
            raise CatalogError('NOT_FOUND','no completed delivery for this context')
        return json.loads(self.catalog.content.read_object(ObjectRef.model_validate(session.data['delivery']['object_ref'])))

    def find_assets(self, context_ref, request, **options):
        return self.call(context_ref,'find_assets',request,**options)

    def get_asset_schema(self, context_ref, request, **options):
        return self.call(context_ref,'get_asset_schema',request,**options)

    def search_asset(self, context_ref, request, **options):
        return self.call(context_ref,'search_asset',request,**options)

    def read_evidence(self, context_ref, request, **options):
        return self.call(context_ref,'read_evidence',request,**options)

    def query_records(self, context_ref, request, **options):
        return self.call(context_ref,'query_records',request,**options)

    def request_asset_update(self, context_ref, request, **options):
        return self.call(context_ref,'request_asset_update',request,**options)
