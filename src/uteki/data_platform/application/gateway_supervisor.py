"""Host supervision of one already-bound gateway worker, not an agent loop."""
import math
import time

from uteki.infrastructure.run_budget import RunBudget

from .gateway_batch import load_gateway_binding
from .session import Session
from ..contracts.common import CatalogError


# 宿主监管一个已绑定 worker 的时间和停止状态，不运行模型循环，也不创建新预算。
class GatewaySupervisor:
    """Prepare while owning the Catalog; release it before spawning the worker.

    The caller supplies the existing ObservedWorker and an explicit batch
    deadline. Only its process group and this frozen scope can be stopped.
    No credentials, SDK imports, inference retries or new ledger are involved.
    """
    # 持有 Catalog 时先核验绑定并打开原账本，监管期限取批次期限与业务剩余时间的较早值。
    def __init__(self, catalog, context_ref, binding, profile, limits, *, batch_deadline):
        if type(batch_deadline) not in (int,float) or not math.isfinite(batch_deadline):
            raise CatalogError('INVALID_REQUEST','explicit finite batch deadline required')
        session=Session(catalog,context_ref)
        gateway=load_gateway_binding(session,binding,profile,limits)
        self.context_ref=context_ref;self.binding=gateway['binding']
        self.budget=RunBudget.open_existing(gateway['budget'].path,gateway['plan']['limit_usd'],
            root_run_id=gateway['plan']['batch_id'],lock_timeout=.05)
        self.scope_id=self.binding['scope_id']
        remaining=session.data['context']['request']['run_policy']['max_wall_seconds']-session.data['wall_seconds']
        self.deadline=min(batch_deadline,time.monotonic()+max(0,remaining))
        self.request_seconds=gateway['scope']['policy']['transport']['request_timeout_seconds']
        self.events=[];self.active_deadlines={};self.worker=None

    # 只接管一个明确 worker，通过其公开等待接口轮询账本、取消信号及传输超时。
    def wait(self, worker, *, cancelled=None):
        if self.worker is not None and self.worker is not worker:
            raise CatalogError('INVALID_STATE','supervisor cannot adopt another worker')
        if cancelled is not None and not callable(cancelled):
            raise CatalogError('INVALID_REQUEST','explicit cancellation observer required')
        self.worker=worker
        previous_poll=worker.launched

        # 优先响应持久化停止，再检查人工取消和期限；不为刚观察到的请求重新赠送完整超时窗口。
        def requested():
            nonlocal previous_poll
            now=time.monotonic()
            status=self.budget.poll_scope(self.scope_id)
            reason=status['root_stop'] or status['scope_stop']
            trigger='persistent_stop' if reason else None
            if reason is None and cancelled is not None and cancelled():
                reason='cancelled';trigger='host_cancel'
            if reason is None and now>=self.deadline:
                reason='wall_time';trigger='host_deadline'
            active={(item['request_key'],item['boundary']) for item in status['active_transports']}
            for identity in active:
                # Start at the PREVIOUS poll (or launch for the first poll),
                # never give a newly observed request an extra timeout window.
                # 以此前轮询时刻为最晚起算边界，按请求键和传输类型分别跟踪在途期限。
                self.active_deadlines.setdefault(identity,previous_poll+self.request_seconds)
                if reason is None and now>=self.active_deadlines[identity]:
                    reason='wall_time';trigger='transport_deadline'
            self.active_deadlines={key:value for key,value in self.active_deadlines.items() if key in active}
            previous_poll=now
            if reason is not None:
                self.events.append(dict(reason=reason,trigger=trigger,observed_monotonic=now,
                    active=[dict(request_key=key,boundary=kind,deadline=self.active_deadlines[(key,kind)])
                            for key,kind in sorted(active)]))
            return reason

        # 停止时通过回调写回原 scope；进程组终止和实际退出观察由传入 worker 负责。
        observation=worker.wait(timeout=max(.001,self.deadline-time.monotonic()),stop_requested=requested,
            on_stop=lambda reason:self.budget.stop_scope(self.scope_id,reason))
        return dict(observation=observation,events=list(self.events),scope=self.budget.inspect_scope(self.scope_id))

    # worker 退出已获确认后才记录所属执行时钟，核对 PID 和网关绑定，不能接管别人的运行。
    def record(self, catalog):
        """Observe the actual owner after its group exits; never steal its clock."""
        if self.worker is None or self.worker.observation is None:
            raise CatalogError('RECOVERY_REQUIRED','supervised worker exit is not confirmed')
        session=Session(catalog,self.context_ref);native=session.data.get('native_execution')
        if native is None:
            return dict(status='not_initialized',observation=self.worker.observation)
        if native['binding'].get('gateway')!=self.binding:
            raise CatalogError('RECOVERY_REQUIRED','exited worker has a different gateway binding')
        owned=[a for a in native.get('recovery_attempts',[]) if a['owner_pid']==self.worker.child.pid]
        # 原生 owner 或仍活动的恢复 owner 才需要记退出；已正常结束的恢复保留其原完成记录。
        if native['owner_pid']==self.worker.child.pid or any(a['status']=='active' for a in owned):
            return dict(status='recorded',reference=self.worker.record(catalog,self.context_ref))
        if self.worker.child.returncode==0 and owned and all(a['status']=='completed' for a in owned):
            return dict(status='recovery_clock_completed',observation=self.worker.observation)
        raise CatalogError('RECOVERY_REQUIRED','exited worker owns neither native nor completed recovery clock')
