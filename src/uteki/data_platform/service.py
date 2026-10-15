"""Shared data tools and an injected query runtime; no model loop or fallback."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import time
import sqlite3

import duckdb

from pydantic import ValidationError

from .application.delivery import assemble, stopped_request, delivery_usage
from .application.clarification import parent_session, validate_narrowing, bind_answer, inherited_state
from .application.evidence import register_returned
from .application.session import Session
from .application.limits import ExecutionLimit
from .contracts.common import CatalogError, canonical, digest, new_id, nonblank, utc_now
from .contracts.content import ObjectRef
from .contracts.query import ContextRequest, ReadPolicy, TOOLS, parse
from .contracts.run import ClarifyRequest, DeliveryRequest, QueryRuntime, TaskState
from .retrieval.assets import resolve_entities


def error_response(operation_id, error, elapsed=0):
    return dict(operation_id=operation_id,status='error',items=[],next_cursor=None,truncated=False,
        coverage=dict(status='failed'),issues=[],error=dict(code=error.code,message=str(error)),
        resource_usage=dict(elapsed_ms=round(elapsed*1000,3),external_calls=0,model_calls=0,cost_usd='0'))


class DataService:
    def __init__(self, catalog, *, acquisition_adapter=None, query_runtime: QueryRuntime | None = None):
        catalog.database.assert_open()
        if query_runtime is not None and not callable(query_runtime):
            raise CatalogError('INVALID_REQUEST','query_runtime must be an explicitly configured callable')
        self.catalog = catalog
        self.acquisition_adapter = acquisition_adapter
        self.query_runtime = query_runtime

    async def run_query(self, context_ref, *, recover=False):
        """Run the explicitly bound SDK; cancelling this call cancels its shared run."""
        started=time.monotonic()
        self.catalog.database.assert_open()
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
        if self.query_runtime is None:
            raise CatalogError('CAPABILITY_UNSUPPORTED','run_query requires an explicitly configured runtime')
        return await self.query_runtime(self,context_ref,recover=recover,started=started)

    def create_context(self, request, *, request_key, recover=False, checkpoint=None):
        request = parse(ContextRequest,request)
        nonblank(request_key)
        checkpoint = checkpoint or (lambda phase: None)
        parent = parent_session(self.catalog,request)
        stamp = utc_now()
        interpretation_clock = parent.data['context']['clock'] if parent else stamp
        clock = request.as_of or datetime.fromisoformat(interpretation_clock)
        companies, securities = resolve_entities(self.catalog,request.entities,clock)
        registered = self.catalog._get('policies','policy_ref',request.source_policy_ref)
        policy = parse(ReadPolicy,json.loads(json.loads(registered['payload'])['definition']))
        if request.caller.prior_delivery_refs:
            raise CatalogError('CAPABILITY_UNSUPPORTED','cross-run continuation requires the later runtime contract; explicit evidence can be reread in a new context')
        continuation, inherited = None, None
        if parent:
            validate_narrowing(parent,request,companies,policy)
            request_key = bind_answer(self.catalog,parent,request,policy,request_key,recover=recover,checkpoint=checkpoint)
            prior = parent.data['context']
            continuation = dict(revises_context_ref=prior['context_ref'],prior_run_id=prior['run_id'],root_run_id=prior['root_run_id'],
                root_context_ref=(prior.get('continuation') or {}).get('root_context_ref',prior['context_ref']),
                clarification_id=request.clarification_response.clarification_id)
            inherited = inherited_state(parent)
        else:
            self.catalog._existing('data-context-submission',request_key,
                dict(request=request.context_payload(),read_policy=policy.model_dump(mode='json')))
        context = dict(context_ref=new_id('req'),clock=interpretation_clock,created_at=stamp,request=request.context_payload(),
            company_ids=companies,resolved_entities=[dict(company_id=c,name=self.catalog.get_company(c)['canonical_name']) for c in companies],
            matched_securities=securities,read_policy=policy.model_dump(mode='json'),unresolved=[],continuation=continuation)
        return deepcopy(Session.create(self.catalog,context,request_key,recover=recover,checkpoint=checkpoint,inherited=inherited).data['context'])

    def inspect_context(self, context_ref):
        session = Session(self.catalog,context_ref)
        native=session.data.get('native_execution') or {}
        catalog_status=self.catalog._get('runs','run_id',session.data['context']['run_id'])['status']
        return deepcopy(dict(context=session.data['context'],status=session.data['status'],plan=session.data['plan'],
            state=session.data['state'],turns=session.data['turns'],operations=session.data['operations'],delivery=session.data['delivery'],
            clarification=session.data.get('clarification'),plan_history=session.data['plan_history'],
            wall_seconds=session.data['wall_seconds'],no_progress_turns=session.data['no_progress_turns'],
            inherited_state=session.data.get('inherited_state'),execution_time_uncertain=session.data.get('execution_time_uncertain'),
            time_reconciliations=session.data.get('time_reconciliations'),
            recovery_attempts=native.get('recovery_attempts',[]),completion_clock=native.get('completion_clock'),
            lifecycle=dict(catalog_status=catalog_status,native_phase=native.get('phase'),
                result_kind=(native.get('outcome') or {}).get('kind'),
                completion_pending=bool(native.get('outcome_intent') and not native.get('outcome_object')),
                closure_requested=bool(native.get('close_intent')))))

    def read_run_result(self, context_ref):
        from .application.run_completion import read_result
        session=Session(self.catalog,context_ref)
        native=session.data.get('native_execution') or {}
        if native.get('outcome_intent') and not native.get('outcome_object'):
            raise CatalogError('RECOVERY_REQUIRED','runtime result awaits terminal confirmation')
        value=read_result(session)
        if value is None:raise CatalogError('NOT_FOUND','no saved runtime result')
        return value

    def close_run(self, context_ref, *, request_key, reason, checkpoint=None):
        from .application.run_completion import close_run
        try:
            return close_run(self,context_ref,request_key=request_key,reason=reason,checkpoint=checkpoint)
        except CatalogError:
            raise
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise CatalogError('RECOVERY_REQUIRED','run closure could not be confirmed; inspect the original intent') from error

    def call(self, context_ref, tool, request, *, state, request_key, should_cancel=None, checkpoint=None, recover=False):
        from .application.tools import ToolExecution
        start = time.monotonic()
        session = None
        limit = None
        operation_id = new_id('op')
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
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
            if recover:
                from .application.operation_recovery import recover_operation
                return recover_operation(self,session,request_key,signature,request,checkpoint=checkpoint)
            replay = session.replay(request_key,signature)
            if replay is not None:
                return replay
            plan = session.proposed_plan(state,tool)
            if tool=='request_asset_update' and request.need_id not in {n['need_id'] for n in plan['needs']}:
                raise CatalogError('INVALID_REQUEST','update refers to unknown need')
            policy = session.data['context']['request']['run_policy']
            limit = ExecutionLimit(policy['max_wall_seconds']-session.data['wall_seconds'],
                started=start,should_cancel=should_cancel)
            if (session.data['turns'] >= policy['max_turns'] or session.data['wall_seconds'] >= policy['max_wall_seconds']
                    or session.data['no_progress_turns'] >= policy['max_no_progress_turns']):
                raise CatalogError('BUDGET_EXCEEDED','synchronous run limit exhausted')
            limit.check('before_preflight')
            executor = ToolExecution(self.catalog,session,tool,request,should_cancel=should_cancel,checkpoint=checkpoint,
                acquisition_adapter=self.acquisition_adapter,limit=limit)
            executor.preflight()
            executor.check('preflight_complete')
            operation_id = session.accept(key=request_key,fingerprint=signature,tool=tool,request=request,state=state,plan=plan)
        except ValidationError as error:
            return error_response(operation_id,CatalogError('INVALID_REQUEST',str(error)))
        except CatalogError as error:
            if error.code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
                raise
            if limit is not None:
                session.data['wall_seconds'] += limit.elapsed()
                session.save()
            return error_response(operation_id,error,time.monotonic()-start)
        try:
            response = executor.execute(operation_id)
            executor.check('before_return')
            elapsed = limit.elapsed()
            response['resource_usage'] = dict(elapsed_ms=round(elapsed*1000,3),**executor.resource_usage)
            if len(canonical(response)) > getattr(request,'max_bytes',200000):
                raise CatalogError('OUTPUT_LIMIT','complete response exceeds byte budget; narrow targets or increase max_bytes')
            limit.check('before_result_registration')
            self._register_response(session,operation_id,tool,request,response)
        except (CatalogError,OSError,ValueError,sqlite3.DatabaseError,duckdb.Error) as error:
            if any(effect.get('status')=='uncertain' or effect.get('recovery_required') for effect in executor.effects):
                uncertain = CatalogError('RECOVERY_REQUIRED','tool side effect has no confirmed acknowledgement')
                uncertain.details = dict(operation_id=operation_id,effects=deepcopy(executor.effects))
                raise uncertain from error
            if isinstance(error,CatalogError) and error.code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
                error.details = dict(operation_id=operation_id,effects=deepcopy(executor.effects))
                raise
            elapsed = limit.elapsed()
            error = error if isinstance(error,CatalogError) else CatalogError('INTERNAL_ERROR',type(error).__name__+': '+str(error))
            response = error_response(operation_id,error,elapsed)
            response['resource_usage'].update(executor.resource_usage)
            if executor.effects:
                response['error']['details'] = dict(effects=deepcopy(executor.effects))
            session.data['no_progress_turns'] += 1
        elapsed = limit.elapsed()
        response['resource_usage']['elapsed_ms'] = round(elapsed*1000,3)
        session.prepare_response(operation_id,response,elapsed)
        if checkpoint is not None:
            checkpoint('tool_response_prepared')
        result = session.complete(operation_id,response,elapsed)
        if checkpoint is not None:
            checkpoint('response_committed')
        return result

    def resolve_update(self, context_ref, *, request_key, action, checkpoint=None, should_cancel=None):
        """Host-only continuation/closure of an accepted acquisition, never a new URL."""
        from .application.update_resolution import resolve_update
        try:
            return resolve_update(self,context_ref,request_key=request_key,action=action,
                checkpoint=checkpoint,should_cancel=should_cancel)
        except CatalogError:
            raise
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise CatalogError('RECOVERY_REQUIRED','acquisition resolution could not be verified: '+type(error).__name__) from error

    def _register_response(self, session, operation_id, tool, request, response):
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

    def deliver(self, context_ref, request, *, state, request_key, recover=False, checkpoint=None):
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
        nonblank(request_key)
        request = parse(DeliveryRequest,request)
        state = parse(TaskState,state)
        session = Session(self.catalog,context_ref)
        signature = digest(canonical(dict(tool='deliver',request=request.model_dump(mode='json'),state=state.model_dump(mode='json'))))
        previous = next((o for o in session.data['operations'].values() if o['request_key']==request_key),None)
        if previous is not None and previous['fingerprint'] != signature:
            raise CatalogError('IDEMPOTENCY_CONFLICT','delivery request differs from its accepted intent')
        if previous is not None and previous['status'] != 'completed' and recover:
            intent = previous.get('terminal_intent')
            if previous['tool'] != 'deliver' or not isinstance(intent,dict) or intent.get('kind') != 'delivery':
                raise CatalogError('RECOVERY_REQUIRED','interrupted delivery has no durable package intent; cannot regenerate it')
            package = intent['package']
            context = session.data['context']
            if any(package.get(k) != context[k] for k in ('context_ref','run_id','root_run_id')):
                raise CatalogError('RECOVERY_REQUIRED','delivery intent belongs to another context/run')
            return self._commit_delivery(session,previous['operation_id'],package,checkpoint)
        replay = session.replay(request_key,signature)
        if replay is not None:
            frozen = ObjectRef.model_validate(replay['delivery_object'])
            if self.catalog.content.read_object(frozen) != canonical(replay['delivery']):
                raise CatalogError('RECOVERY_REQUIRED','committed delivery differs from its immutable object')
            self.catalog.finish_run(session.data['context']['run_id'],status=self._delivery_run_status(replay['delivery']))
            return replay
        plan = session.proposed_plan(state,'deliver')
        package = assemble(session,request,state,plan)
        operation = session.accept(key=request_key,fingerprint=signature,tool='deliver',request=request,state=state,plan=plan,
            terminal_intent=dict(kind='delivery',package=package))
        if checkpoint is not None:
            checkpoint('delivery_accepted')
        return self._commit_delivery(session,operation,package,checkpoint)

    def force_delivery(self, context_ref, *, stop_reason, visible_results, checkpoint=None):
        """Host-only stop path; it never invokes a model or a new business tool."""
        if stop_reason not in {'cancelled','wall_time','max_turns','no_progress','model_budget','native_max_turns'}:
            raise CatalogError('INVALID_REQUEST','unsupported forced stop reason')
        session = Session(self.catalog,context_ref)
        key = 'runtime-stop:'+session.data['context']['run_id']
        previous = next((o for o in session.data['operations'].values() if o['request_key']==key),None)
        if previous is not None:
            intent = previous.get('terminal_intent',{})
            if intent.get('origin') != 'runtime_stop' or intent['package']['stop_reason'] != stop_reason:
                raise CatalogError('IDEMPOTENCY_CONFLICT','forced delivery stop reason differs')
            return self.deliver(context_ref,previous['request'],state=previous['state'],request_key=key,
                                recover=True,checkpoint=checkpoint)
        if any(o['status'] != 'completed' for o in session.data['operations'].values()):
            raise CatalogError('RECOVERY_REQUIRED','unconfirmed business effects must be inspected before partial delivery')
        request,state = stopped_request(session,stop_reason,visible_results)
        plan = session.proposed_plan(state,'deliver')
        package = assemble(session,request,state,plan)
        package.update(stop_reason=stop_reason,business_status='cancelled' if stop_reason=='cancelled' else 'partial',
                       terminal_origin='host_validated_state')
        signature = digest(canonical(dict(tool='deliver',request=request.model_dump(mode='json'),state=state.model_dump(mode='json'))))
        operation = session.accept(key=key,fingerprint=signature,tool='deliver',request=request,state=state,plan=plan,
            terminal_intent=dict(kind='delivery',origin='runtime_stop',package=package),count_turn=False)
        if checkpoint is not None:checkpoint('delivery_accepted')
        return self._commit_delivery(session,operation,package,checkpoint)

    @staticmethod
    def _delivery_run_status(package):
        return 'cancelled' if package.get('business_status')=='cancelled' else 'completed'

    def _commit_delivery(self, session, operation, package, checkpoint):
        """Finish the exact saved package; no new delivery ID or model call."""
        return self._commit_terminal(session,operation,package,'delivery',checkpoint)

    def _commit_terminal(self, session, operation, package, kind, checkpoint):
        frozen = self.catalog.content.put_object(canonical(package))
        if checkpoint is not None:
            checkpoint(kind+'_object_written')
        response = dict(kind='needs_clarification' if kind=='clarification' else 'delivery',
            **{kind:package,kind+'_object':frozen.model_dump(mode='json')})
        session.data[kind] = {kind+'_id':package[kind+'_id'],'object_ref':frozen.model_dump(mode='json')}
        session.data['status'] = 'needs_clarification' if kind=='clarification' else self._delivery_run_status(package)
        result = session.complete(operation,response,0)
        if checkpoint is not None:
            checkpoint(kind+'_response_committed')
        self.catalog.finish_run(session.data['context']['run_id'],status='completed' if kind=='clarification' else self._delivery_run_status(package))
        return result

    def clarify(self, context_ref, request, *, state, request_key, recover=False, checkpoint=None):
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
        nonblank(request_key)
        request,state = parse(ClarifyRequest,request),parse(TaskState,state)
        session = Session(self.catalog,context_ref)
        signature = digest(canonical(dict(tool='clarify',request=request.model_dump(mode='json'),state=state.model_dump(mode='json'))))
        previous = next((o for o in session.data['operations'].values() if o['request_key']==request_key),None)
        if previous is not None and previous['fingerprint']!=signature:
            raise CatalogError('IDEMPOTENCY_CONFLICT','clarification request differs')
        if previous is not None and previous['status']!='completed' and recover:
            intent = previous.get('terminal_intent',{})
            if intent.get('kind')!='clarification':
                raise CatalogError('RECOVERY_REQUIRED','clarification has no saved terminal intent')
            return self._commit_terminal(session,previous['operation_id'],intent['package'],'clarification',checkpoint)
        replay = session.replay(request_key,signature)
        if replay is not None:
            if self.catalog.content.read_object(ObjectRef.model_validate(replay['clarification_object']))!=canonical(replay['clarification']):
                raise CatalogError('RECOVERY_REQUIRED','clarification object differs')
            self.catalog.finish_run(session.data['context']['run_id'],status='completed')
            return replay
        plan = session.proposed_plan(state,'clarify')
        if not set(request.blocking_need_ids)<={n.need_id for n in state.gaps}:
            raise CatalogError('INVALID_REQUEST','clarification must refer to unresolved plan needs')
        context = session.data['context']
        usage = delivery_usage(session)
        from decimal import Decimal
        spent = Decimal(usage.get('cost_usd') or usage.get('synthetic_cost_usd') or '0')
        held = Decimal(usage['unknown_cost_reserved_usd'])+Decimal(usage.get('in_flight_reserved_usd','0'))
        package = dict(schema_version='uteki-clarification-v1',clarification_id=new_id('cl'),
            context_ref=context_ref,run_id=context['run_id'],root_run_id=context['root_run_id'],
            original_question=context['request']['question'],question=request.question,blocking_need_ids=list(request.blocking_need_ids),
            needs_plan=plan,state=state.model_dump(mode='json'),usage=usage,
            remaining_budget=str(Decimal(context['request']['run_policy']['max_usd'])-spent-held),created_at=utc_now())
        operation = session.accept(key=request_key,fingerprint=signature,tool='clarify',request=request,state=state,plan=plan,
            terminal_intent=dict(kind='clarification',package=package))
        if checkpoint is not None:checkpoint('clarification_accepted')
        return self._commit_terminal(session,operation,package,'clarification',checkpoint)

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
