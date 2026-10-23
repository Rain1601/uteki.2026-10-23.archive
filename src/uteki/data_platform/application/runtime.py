# SDK 无关的运行记录与准入控制：把原生调用、业务工具、可见证据、预算和结束结果绑定起来。
# 本模块保存事实并检查能否继续；实际模型循环及原生会话恢复由各 SDK 适配层执行。
"""Durable business runtime records; never an SDK loop or a second cost ledger."""
from __future__ import annotations

from copy import deepcopy
import asyncio
import json
import math
import os
import threading
import time
import uuid
from decimal import Decimal

from uteki.infrastructure.run_budget import RunBudget, BudgetExceeded, RequestRecoveryRequired

from ..catalog.database import ensure_directory
from ..contracts.common import CatalogError, canonical, digest, nonblank, utc_now
from ..contracts.query import parse
from ..contracts.run import RuntimeLimits
from .session import Session
from .execution_clock import start_clock, reconcile_time, begin_segment, TimeObservationError
from .run_completion import commit_result, read_result, save_result
from .recovery_clock import RecoveryClock, pending_recoveries
from .runtime_initialization import SCHEMA as INITIALIZATION_SCHEMA, new_root_descriptor, check_root_ready, complete_initialization
from .gateway_batch import load_gateway_binding, open_runtime_budget

FORCED_STOPS = {'cancelled','wall_time','max_turns','no_progress','model_budget','native_max_turns'}

# 同一目录/上下文的并发调用共享一个在途任务；不同绑定拒绝合并，取消也汇入同一清理流程。
async def run_once(service, context_ref, identity, factory):
    """Join the same live host execution; this is not a replacement SDK loop."""
    registry = getattr(service.catalog, '_native_executions', None)
    if registry is None:
        registry = service.catalog._native_executions = {}
    fingerprint = digest(canonical(identity))
    current = registry.get(context_ref)
    if current is not None:
        if current['fingerprint'] != fingerprint:
            raise CatalogError('IDEMPOTENCY_CONFLICT', 'active context has a different native binding')
        task = current['task']
    else:
        current = dict(fingerprint=fingerprint,journal=None,cancel_requested=False)
        # 把日志对象挂到共享任务；初始化期间收到的取消会在挂接后立即生效。
        def attach(journal):
            current['journal']=journal
            if current['cancel_requested']:journal.stop('cancelled')
        task = asyncio.create_task(factory(attach))
        current['task']=task
        registry[context_ref] = current
        # 任务结束后只移除自己仍持有的登记项，避免误清理后续执行。
        def completed(done):
            if registry.get(context_ref) is current:registry.pop(context_ref,None)
        task.add_done_callback(completed)
    try:
        while True:
            try:
                # 屏蔽调用者对共享任务的直接取消；下方显式记录停止决定后只触发一次清理。
                return deepcopy(await asyncio.shield(task))
            except asyncio.CancelledError:
                if task.done():return deepcopy(task.result())
                # Cancellation is a durable host decision, not contingent on
                # the SDK propagating CancelledError. Repeated callers/signals
                # join the same cleanup instead of cancelling it again.
                if not current['cancel_requested']:
                    current['cancel_requested']=True
                    try:
                        if current['journal'] is not None:current['journal'].stop('cancelled')
                    finally:
                        task.cancel()
    finally:
        if task.done() and registry.get(context_ref, {}).get('task') is task:
            registry.pop(context_ref, None)


# 原生运行的持久记录门面；会话写入限定在目录所属线程，传输线程使用预算与只读绑定。
class RuntimeJournal:
    """One immutable context/native binding, stored in the existing Session head.

    Model transport threads may use only `budget`, `guard_transport` and the
    immutable binding. Session mutations stay on the Catalog owner's thread.
    """
    # 校验 profile/限额/账本绑定；返回既有结果、显式恢复原运行，或持久初始化新运行。
    def __init__(self, service, context_ref, profile, limits, *, recover=False, checkpoint=None, started=None, gateway_binding=None):
        now=time.monotonic()
        if started is not None and (type(started) not in (int,float) or not math.isfinite(started) or not 0<=started<=now):
            raise CatalogError('INVALID_REQUEST','host invocation start must be a finite prior monotonic time')
        self.started = now if started is None else started
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
        self.service, self.catalog, self.context_ref = service, service.catalog, context_ref
        self.limits = parse(RuntimeLimits, limits)
        self.profile = deepcopy(profile)
        self.stopped = threading.Event()
        self.stop_reason = None
        self.failure_code = None
        self.resuming = False
        self.budget = None
        self.recovery_clock = None
        self.checkpoint = checkpoint or (lambda phase: None)
        session = self.session()
        self.context = deepcopy(session.data['context'])
        root_session = session.root_session()
        self.root_policy = root_session.data['context']['request']['run_policy']
        self.prior_elapsed = 0.0
        self.initial_seconds = session.data['wall_seconds']
        self.deadline = self.started + self.context['request']['run_policy']['max_wall_seconds'] - self.initial_seconds
        self.gateway_binding=deepcopy(gateway_binding)
        self.gateway=(load_gateway_binding(session,self.gateway_binding,self.profile,self.limits.model_dump(mode='json'))
            if self.gateway_binding is not None else None)
        self.mode=self.gateway['mode'] if self.gateway else 'offline'
        binding = dict(profile=self.profile, limits=self.limits.model_dump(mode='json'), mode=self.mode)
        if self.gateway_binding is not None:binding['gateway']=self.gateway_binding
        current = session.data.get('native_execution')
        recovery_pending = bool(current and pending_recoveries(current))
        completion_pending = bool(current and current.get('completion_clock',{}).get('status')=='pending')
        if completion_pending and not recover:
            raise CatalogError('RECOVERY_REQUIRED','result timing confirmation is incomplete; use explicit recovery')
        if recovery_pending and not recover:
            raise CatalogError('RECOVERY_REQUIRED','interrupted recovery requires explicit reconciliation')
        # 恢复必须沿用原模型、SDK、限额和网关绑定，不能把改配置当成原运行继续。
        if current is not None and current['binding'] != binding:
            raise CatalogError('IDEMPOTENCY_CONFLICT', 'native kernel/profile/limits differ from this context')
        pending_result = current is not None and current.get('outcome_intent') and not current.get('outcome_object')
        self.cached = read_result(session) if current is not None and not pending_result else None
        if current is not None and current.get('close_intent') and self.cached is None:
            raise CatalogError('RECOVERY_REQUIRED','host closure is in progress; repeat the original close_run')
        if current is not None and current.get('outcome_intent') and not current.get('outcome_object'):
            if not recover:
                raise CatalogError('RECOVERY_REQUIRED','runtime result awaits terminal confirmation; use explicit recovery')
            self.cached = None
        if self.cached is not None and not (recover and (recovery_pending or completion_pending or self.cached.get('kind')=='recovery_required'
                or current.get('exit_observation') and (current.get('execution_time_uncertain')
                    or session.data.get('execution_time_uncertain') or not current.get('time_reconciliation')))):
            self.budget = open_runtime_budget(session)
            return
        if current is not None:
            if recover:
                self.prior_elapsed = current['elapsed_seconds']
                if current['phase']=='initializing':
                    if not current.get('initialization'):
                        raise CatalogError('RECOVERY_REQUIRED','legacy initialization lacks a frozen creation intent; never recreate its ledger')
                    self._resume_initialization()
                    return
                self.budget = open_runtime_budget(session)
                root_stop=self._persistent_stop()
                if root_stop:self.stop(root_stop)
                self.recovery_clock = RecoveryClock(self.session(),started=self.started)
                try:
                    if self.recovery_clock.timed_out:self.stop('wall_time')
                    self.checkpoint('host_recovery_started')
                    self.cached = self._recover_existing_results()
                except BaseException:
                    self.recovery_clock.close()
                    raise
                if not self.resuming:self.finish_recovery()
                return
            raise CatalogError('RECOVERY_REQUIRED', 'previous native execution lacks a confirmed outcome; no automatic restart')
        if session.data['status'] != 'open':
            raise CatalogError('INVALID_STATE', 'cannot start an SDK on a terminal deterministic context')
        if any(o['status'] != 'completed' for o in session.data['operations'].values()):
            raise CatalogError('RECOVERY_REQUIRED', 'previous business operation has an uncertain outcome')
        path = (self.catalog.root/self.gateway['ledger_path'] if self.gateway else
            ensure_directory(self.catalog.root, 'runs/'+self.context['root_run_id'])/'budget.sqlite')
        existing_root = root_session.data.get('root_budget') or root_session.data.get('native_execution')
        # 没有可验证根描述的既存账本不能自动认领，避免串账或重置费用历史。
        if self.gateway is None and existing_root is None and (path.exists() or path.is_symlink()):
            raise CatalogError('RECOVERY_REQUIRED','unexpected existing root ledger; never adopt it')
        if existing_root is not None:
            check_root_ready(self,existing_root)
            if existing_root['ledger_path']!=path.relative_to(self.catalog.root).as_posix():
                raise CatalogError('RECOVERY_REQUIRED','root ledger binding differs')
            self.budget = (self.gateway['budget'] if self.gateway else
                RunBudget.open_existing(path,self.root_policy['max_usd'],root_run_id=self.context['root_run_id']))
            root = self.budget.inspect_root()
            if self.gateway is not None:
                if existing_root.get('gateway')!=self.gateway_binding:
                    raise CatalogError('RECOVERY_REQUIRED','business root gateway binding differs')
            elif (root['mode']!='offline' or self.limits.max_model_requests>root['max_requests']
                    or self.limits.max_request_bytes>root['policy']['request_bytes']
                    or self.limits.max_response_bytes>root['policy']['response_bytes']):
                raise CatalogError('SCOPE_VIOLATION','child runtime cannot expand frozen root transport limits')
        native_id=str(uuid.uuid4())
        ledger_path=path.relative_to(self.catalog.root).as_posix()
        initialization=dict(schema_version=INITIALIZATION_SCHEMA,owns_new_root=existing_root is None)
        if existing_root is None:
            initialization['root_descriptor']=new_root_descriptor(self,root_session,native_id,ledger_path)
        session.data['native_execution'] = dict(schema_version='uteki-native-execution-v1',
            binding=binding, phase='initializing', native_session_id=native_id,
            owner_pid=os.getpid(), execution_started_at=utc_now(), elapsed_seconds=0.0,
            execution_clock=start_clock(self.started,self.initial_seconds),
            tool_calls={}, observed_results=[], events=[], outcome=None,
            ledger_path=ledger_path,initialization=initialization)
        session.save()
        self.checkpoint('native_initialization_saved')
        self.budget=complete_initialization(self)
        session = self.session()
        session.data['native_execution']['phase'] = 'active'
        session.save()

    # 原 SDK 尚未启动时，核验旧进程退出并完成原初始化意图，然后开始新计时段。
    def _resume_initialization(self):
        """No SDK was started: finish the original intent after observing its owner."""
        if not self.state().get('exit_observation'):
            raise CatalogError('RECOVERY_REQUIRED','initialization needs its original worker exit observation')
        self.recovery_clock=RecoveryClock(self.session(),started=self.started)
        try:
            self.checkpoint('host_recovery_started')
            accounted=reconcile_time(self.session(),active_recovery_id=self.recovery_clock.attempt_id)
            self.prior_elapsed=max(self.prior_elapsed,
                self.state().get('prior_elapsed_seconds',0.0)+accounted['native_elapsed_upper'])
            self.budget=complete_initialization(self)
            root_stop=self._persistent_stop()
            if root_stop:self.stop(root_stop)
            if accounted['timed_out'] or self.recovery_clock.timed_out:self.stop('wall_time')
            self.finish_recovery()
            self.started=time.monotonic()
            self.initial_seconds=self.session().data['wall_seconds']
            self.deadline=self.started+self.context['request']['run_policy']['max_wall_seconds']-self.initial_seconds
            begin_segment(self.session(),started=self.started,prior_elapsed=self.prior_elapsed)
            self.checkpoint('runtime_initialization_resumed')
            self.cached=None
        except BaseException:
            self.recovery_clock.close()
            raise

    # 先核清在途请求、业务副作用和耗时，再判断能否恢复原生会话或确认原终态。
    def _recover_existing_results(self):
        """Reconcile effects/time; only an adapter's verified state can continue."""
        saved=self.session()
        native=saved.data['native_execution']
        if native.get('outcome_intent'):
            # A late supervisor observation updates current execution accounting,
            # not the already frozen business result or its historical snapshot.
            if native.get('exit_observation'):
                reconcile_time(saved,active_recovery_id=self.recovery_clock.attempt_id)
            elif native.get('completion_clock',{}).get('status')=='pending':
                native['execution_time_uncertain']=True
                saved.save()
            return commit_result(saved,checkpoint=self.checkpoint)
        self._recover_requests()
        session = self.session()
        native = session.data['native_execution']
        native['events'].append(dict(type='explicit_recovery',at=utc_now(),previous_owner_pid=native['owner_pid']))
        native['execution_time_uncertain'] = True
        session.save()
        reconciled = []
        for operation in session.data['operations'].values():
            if operation['tool'] in {'deliver','clarify'}:
                continue
            calls = [v for v in self.state()['tool_calls'].values() if v['request_key']==operation['request_key']]
            if operation['status']=='completed' and all(v['output'] is not None for v in calls):
                continue
            try:
                response = self.service.call(self.context_ref,operation['tool'],operation['request'],state=operation['state'],
                    request_key=operation['request_key'],recover=True)
                saved = self.session().data['operations'][operation['operation_id']]
                if saved['status']!='completed' or saved['response']!=response:
                    return self._recovery_pending('original tool response could not be reconciled with its binding',reconciled)
                for call in calls:self.record_tool(call['call_id'],response)
                reconciled.append(operation['operation_id'])
            except CatalogError as error:
                return self._recovery_pending(str(error),reconciled)
        session = self.session()
        try:
            accounted=reconcile_time(session,active_recovery_id=self.recovery_clock.attempt_id)
        except CatalogError as error:
            if isinstance(error,TimeObservationError):
                # Keep diagnosis outside reconcile_time: failed validation
                # itself must not alter the time/head being validated.
                proof=self.catalog.content.put_object(canonical(error.diagnostic)).model_dump(mode='json')
                session=self.session()
                failures=session.data['native_execution'].setdefault('time_reconciliation_failures',[])
                if proof not in failures:failures.append(proof)
                session.save()
            return self._recovery_pending(str(error),reconciled)
        if accounted is not None:
            self.initial_seconds=accounted['wall_seconds']
            self.prior_elapsed=max(self.prior_elapsed,
                native.get('prior_elapsed_seconds',0.0)+accounted['native_elapsed_upper'])
            self.deadline=self.started+self.context['request']['run_policy']['max_wall_seconds']-self.initial_seconds
            if accounted['timed_out']:self.stop('wall_time')
        deliveries = [o for o in session.data['operations'].values() if o['tool'] in {'deliver','clarify'}]
        if (not deliveries and accounted is not None and not self.stopped.is_set()
                and session.data['status']=='open'
                and ((self.profile['kernel']=='openai' and native.get('openai_checkpoint') is not None)
                     or (self.profile['kernel']=='claude' and native.get('claude_session') is not None))):
            # 业务副作用已核清仍不足以续跑；模型响应或收费未知也必须先解决。
            if self.budget.summary()['unknown_requests'] or self.budget.inspect_root()['request_stages'].get('outcome_unknown'):
                return self._recovery_pending('root response or fee remains unknown; native continuation blocked',reconciled)
            self.resuming = True
            return None
        if len(deliveries)!=1 or any(o['status']!='completed' and o['tool'] not in {'deliver','clarify'}
                                    for o in session.data['operations'].values()):
            return self._recovery_pending('saved tool effects reconciled; native continuation still requires recovery'
                + ('; execution time remains unconfirmed' if accounted is None else ''),reconciled)
        operation = deliveries[0]
        response = getattr(self.service,operation['tool'])(self.context_ref,operation['request'],state=operation['state'],
            request_key=operation['request_key'],recover=True)
        for item in self.state()['tool_calls'].values():
            if item['request_key']==operation['request_key']:
                self.record_tool(item['call_id'],response)
        clarification = response['kind']=='needs_clarification'
        return self.finish(dict(kind=response['kind'],status='needs_clarification' if clarification else response['delivery'].get('business_status','completed'),
            delivery=None if clarification else response,clarification=response if clarification else None,
            committed_delivery=None,committed_clarification=None,error=None,native_success=False,
            native_error='UNCONFIRMED_AFTER_PROCESS_EXIT',profile=self.profile,
            native_events=[dict(type='terminal_reconciled_without_sdk_restart')],tool_events=[],
            mode='offline',real_model_calls=0,gateway_cost_usd=None))

    # 把尚不能安全继续的原因与已核清操作保存为恢复待办结果。
    def _recovery_pending(self, error, reconciled):
        return self.finish(dict(kind='recovery_required',status='failed',delivery=None,clarification=None,
            committed_delivery=None,committed_clarification=None,error=error,native_success=False,
            native_error='UNCONFIRMED_AFTER_PROCESS_EXIT',profile=self.profile,
            native_events=[dict(type='existing_tool_results_reconciled',operation_ids=reconciled)],tool_events=[],
            mode='offline',real_model_calls=0,gateway_cost_usd=None))

    # 每次重新加载会话最新 head，避免用旧内存副本覆盖其他已提交记录。
    def session(self):
        return Session(self.catalog, self.context_ref)

    # 返回原生执行记录副本，供 SDK 适配层检查恢复点和可见结果。
    def state(self):
        return deepcopy(self.session().data['native_execution'])

    # 适配层验证原生恢复数据后，结束恢复计时并开始新的受剩余额度约束的执行段。
    def begin_continuation(self):
        """Start a new timed execution only after the adapter validates its state."""
        if not self.resuming:
            return
        self.finish_recovery()
        session = self.session()
        self.started = time.monotonic()
        self.initial_seconds = session.data['wall_seconds']
        self.deadline = self.started+self.context['request']['run_policy']['max_wall_seconds']-self.initial_seconds
        begin_segment(session,started=self.started,prior_elapsed=self.prior_elapsed)
        self.checkpoint('native_continuation_started')

    # 幂等结束本宿主的恢复计时，把恢复耗时计入原任务。
    def finish_recovery(self):
        if self.recovery_clock is not None and not self.recovery_clock.closed:
            self.recovery_clock.close()
            self.checkpoint('host_recovery_completed')

    # 发送模型请求前检查取消、持久停止标记及总时限；不写业务会话。
    def guard_transport(self):
        if self.stopped.is_set():
            raise CatalogError('RUN_STOPPED', self.stop_reason or 'runtime stopped')
        if self.budget is not None:
            root_stop=self._persistent_stop()
            if root_stop:
                self.stop(root_stop)
                raise CatalogError('RUN_STOPPED',self.stop_reason)
        if time.monotonic() >= self.deadline:
            self.stop('wall_time')
            raise CatalogError('BUDGET_EXCEEDED', 'root execution time exhausted')

    # 记录首次停止原因；预算类停止同步到根账本或当前网关 scope，阻止后续请求。
    def stop(self, reason):
        if not self.stopped.is_set():
            self.stop_reason = reason
            self.stopped.set()
        if reason in FORCED_STOPS and self.budget is not None:
            self.stop_reason=(self.budget.stop_scope(self.gateway_binding['scope_id'],reason)['stop_reason']
                if self.gateway_binding else self.budget.stop_root(reason)['stop_reason'])

    # 根运行停止优先，其次读取当前控制 scope 的停止原因。
    def _persistent_stop(self):
        root_stop=self.budget.inspect_root()['stop_reason']
        return root_stop or (self.budget.inspect_scope(self.gateway_binding['scope_id'])['stop_reason']
            if self.gateway_binding else None)

    # 核清本运行或 scope 中断请求；沿用原账本，不创建新的请求额度。
    def _recover_requests(self):
        return self.budget.recover_requests(**({'scope_id':self.gateway_binding['scope_id']} if self.gateway_binding else {}))

    # 把当前执行段耗时累计到会话；恢复阶段交由独立 RecoveryClock 防止混算。
    def tick(self, *, completion=False):
        if self.recovery_clock is not None and not self.recovery_clock.closed:
            self.recovery_clock.tick()
            return
        session = self.session()
        now=time.monotonic()
        elapsed = max(0.0, now-self.started)
        session.data['native_execution']['elapsed_seconds'] = self.prior_elapsed+elapsed
        session.data['wall_seconds'] = max(session.data['wall_seconds'], self.initial_seconds+elapsed)
        if completion:
            session.data['native_execution']['completion_clock'].update(status='recorded',
                through_monotonic=now,wall_seconds=session.data['wall_seconds'])
        session.save()

    # 业务工具开始前进一步检查未确认操作、未知费用、金额、轮次及无进展限制。
    def guard_action(self):
        self.guard_transport()
        self.tick()
        data = self.session().data
        if data.get('execution_time_uncertain'):
            self.failure_code = 'RECOVERY_REQUIRED'
            raise CatalogError('RECOVERY_REQUIRED','interrupted tool execution time must be reconciled before continuing')
        if any(o['status'] != 'completed' for o in data['operations'].values()):
            self.failure_code = 'RECOVERY_REQUIRED'
            raise CatalogError('RECOVERY_REQUIRED', 'accepted business operation lacks a durable response')
        policy = data['context']['request']['run_policy']
        root = self.budget.inspect_root()
        if self.budget.summary()['unknown_requests'] or root['request_stages'].get('outcome_unknown'):
            self.failure_code = 'RECOVERY_REQUIRED'
            raise CatalogError('RECOVERY_REQUIRED','root request/fee uncertainty must be reconciled before continuing')
        cost = self.budget.summary()
        # Gateway scopes share a registered batch allowance. An explicit money-
        # only revision preserves their original context snapshots; the current
        # binding carries the authorized pool ceiling. Offline child caps stay local.
        monetary_limit = self.gateway['plan']['limit_usd'] if self.gateway else policy['max_usd']
        if Decimal(cost['estimated_spent_usd'])+Decimal(cost['held_usd'])>Decimal(monetary_limit):
            self.stop('model_budget')
            raise CatalogError('BUDGET_EXCEEDED','child monetary limit is below cumulative root costs')
        if data['turns'] >= policy['max_turns']:
            self.stop('max_turns')
            raise CatalogError('BUDGET_EXCEEDED', 'business tool limit exhausted')
        if data['no_progress_turns'] >= policy['max_no_progress_turns']:
            self.stop('no_progress')
            raise CatalogError('BUDGET_EXCEEDED', 'no-progress limit exhausted')

    # 仅为离线模型请求登记零费用预留并标记发出；真实网关必须在 HTTP 边界计量。
    def prepare_model(self, request, *, request_bytes=None, request_key=None):
        if self.gateway_binding is not None:
            raise CatalogError('INVALID_STATE','gateway requests must use the physical HTTP boundary, not zero-cost offline metering')
        self.guard_transport()
        existing = next((r for r in self.budget.inspect_requests() if r['request_key']==request_key),None) if request_key else None
        if existing is None and self.budget.summary()['requests']>=self.limits.max_model_requests:
            self.stop('model_budget')
            raise CatalogError('BUDGET_EXCEEDED','cumulative model request limit exhausted')
        size = len(canonical(request)) if request_bytes is None else request_bytes
        if size > self.limits.max_request_bytes:
            raise CatalogError('REQUEST_TOO_LARGE', 'model request exceeds the explicit envelope bound')
        key = request_key or 'model:'+uuid.uuid4().hex
        try:
            # 账本先登记请求意图，再标记已发出；两步间的中断与发出后的未知结果可分别恢复。
            self.budget.prepare_request(key, dict(run_id=self.context['run_id'],
                context_ref=self.context_ref, profile=self.profile, request=request), reserve_usd='0')
        except BudgetExceeded:
            self.stop('model_budget')
            raise
        self.checkpoint('model_prepared')
        self.guard_transport()
        try:
            self.budget.begin_request(key)
        except BudgetExceeded:
            self.stop('model_budget')
            raise
        self.checkpoint('model_dispatched')
        return key

    # 保存离线模型响应；完整响应记合成零费用，不完整响应保留未知。
    def record_model(self, key, response, *, complete):
        if self.gateway_binding is not None:
            raise CatalogError('INVALID_STATE','gateway responses require raw transport and billing evidence')
        self.checkpoint('model_response_received')
        self.budget.record_response(key, response, billed_usd='0' if complete else None)
        self.checkpoint('model_response_committed')

    # 将 SDK call_id 与工具名/参数绑定为幂等键；重复调用复用原输出而不重新执行。
    def tool_key(self, call_id, name, arguments):
        nonblank(call_id)
        session = self.session()
        calls = session.data['native_execution']['tool_calls']
        identity = digest(canonical(dict(call_id=call_id, kernel=self.profile['kernel'])))
        fingerprint = digest(canonical(dict(name=name, arguments=arguments)))
        existing = calls.get(identity)
        if existing is not None:
            if existing['fingerprint'] != fingerprint:
                raise CatalogError('IDEMPOTENCY_CONFLICT', 'native tool ID reused with different name or arguments')
            return existing['request_key'], deepcopy(existing['output'])
        self.guard_action()
        session = self.session()
        calls = session.data['native_execution']['tool_calls']
        key = 'sdk:'+identity
        calls[identity] = dict(call_id=call_id, name=name, fingerprint=fingerprint,
                               request_key=key, status='prepared', output=None)
        session.save()
        self.checkpoint('native_tool_prepared')
        return key, None

    # 保存 SDK 工具的精确返回；同一调用 ID 已确认的输出不可改变。
    def record_tool(self, call_id, output):
        identity = digest(canonical(dict(call_id=call_id, kernel=self.profile['kernel'])))
        session = self.session()
        item = session.data['native_execution']['tool_calls'][identity]
        if item['output'] is not None and item['output'] != output:
            raise CatalogError('IDEMPOTENCY_CONFLICT', 'native tool response differs from saved response')
        item.update(status='completed', output=deepcopy(output))
        session.save()
        self.checkpoint('native_tool_response_committed')

    # 登记原生 SDK 实际观察到的结果引用与事件，供交付可见性检查使用。
    def observe(self, references, event):
        session = self.session()
        native = session.data['native_execution']
        observed = {canonical(r) for r in native['observed_results']}
        observed.update(references)
        native['observed_results'] = [json.loads(r) for r in sorted(observed)]
        native['events'].append(deepcopy(event))
        session.save()

    # 核清在途请求，必要时生成受证据约束的部分交付，再持久保存运行终态和结束耗时。
    def finish(self, outcome):
        self.tick()
        value = deepcopy(outcome)
        if self.failure_code is not None:
            value.update(kind='recovery_required',status='failed',error=self.failure_code)
        own_requests=[r for r in self.budget.inspect_requests() if not self.gateway_binding
            or r.get('control_scope_id')==self.gateway_binding['scope_id']]
        if any(r['stage']=='dispatched' for r in own_requests):
            # Native error/cancellation may leave a request without a response.
            # Preserve the outcome uncertainty, never release that reservation.
            self._recover_requests()
        terminal = any(value.get(k) for k in ('delivery','committed_delivery','clarification','committed_clarification'))
        if self.stop_reason in FORCED_STOPS and not terminal:
            try:
                if self.state().get('execution_time_uncertain'):
                    raise CatalogError('RECOVERY_REQUIRED','root stop does not verify the prior execution interval')
                response = self.service.force_delivery(self.context_ref,stop_reason=self.stop_reason,
                    visible_results=self.state()['observed_results'],checkpoint=self.checkpoint)
                value.update(kind='delivery',status=response['delivery']['business_status'],delivery=response,
                             native_error=value.get('error'),error=None)
            except CatalogError as error:
                if error.code not in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
                    raise
                value.update(kind='recovery_required',status='failed',error=error.code)
        self.stop('terminal')
        session = self.session()
        native=session.data['native_execution']
        # 只有当前进程持有的执行段才能记录自身结束计时；恢复宿主不能冒记原 worker 的时间。
        owns_clock=(self.recovery_clock is None or self.recovery_clock.closed) and (
            native.get('owner_pid')==os.getpid() and native.get('execution_clock',{}).get('started_monotonic')==self.started)
        if owns_clock:
            native['completion_clock']=dict(status='pending',owner_pid=os.getpid(),
                started_monotonic=self.started)
            session.save()
            self.checkpoint('runtime_completion_clock_pending')
        if not any(value.get(k) for k in ('delivery','committed_delivery','clarification','committed_clarification')):
            if any(o['status'] != 'completed' for o in session.data['operations'].values()):
                value.update(kind='recovery_required',status='failed')
        result=save_result(session,self.budget,value,checkpoint=self.checkpoint)
        if owns_clock:
            self.tick(completion=True)
            if time.monotonic()>=self.deadline:self.stop('wall_time')
            self.checkpoint('runtime_completion_clock_recorded')
        self.finish_recovery()
        return result

    # SDK 装配阶段尚无工具绑定时，构造失败结果并区分普通失败与需恢复状态。
    def failure_outcome(self, error, *, error_code=None, events=None):
        """A failed SDK assembly has no ToolBinding from which to build a result."""
        return dict(kind='recovery_required' if error_code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'} else 'failed',
            status='failed',error=error,native_success=False,delivery=None,clarification=None,
            committed_delivery=None,committed_clarification=None,profile=self.profile,
            native_events=events or [],tool_events=[],mode='offline',real_model_calls=0,gateway_cost_usd=None)
