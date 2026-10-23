# 恢复宿主的工作时间与原 worker 的执行时间分别记录，最后计入同一任务 wall_seconds。
# 恢复过程本身若中断，也需要该宿主真实退出的观察证据，不能假定未消耗时间。
"""Account host recovery separately from the worker whose effects it confirms."""
from copy import deepcopy
import json
import math
import os
import time
import uuid

from ..contracts.common import CatalogError, canonical, utc_now
from ..contracts.content import ObjectRef
from .session import Session


# 累计已记录的各次恢复耗时，用于从总时间中分离原生执行部分。
def recovery_seconds(native):
    return sum(item['charged_seconds'] for item in native.get('recovery_attempts',[]))


# 列出尚未完成或核清的恢复区间，不把 active 自动解释为零耗时。
def pending_recoveries(native):
    return [item for item in native.get('recovery_attempts',[]) if item['status']=='active']


# 核验其他恢复宿主的退出证据，用可证明的耗时上界补齐未记部分。
def reconcile_recoveries(session, *, active_id=None):
    """Only an actual observation can close another host's interrupted interval."""
    from .execution_clock import clock_domain
    native=session.data['native_execution']
    changes=[]
    for item in pending_recoveries(native):
        if item['attempt_id']==active_id:
            if item['owner_pid']!=os.getpid():
                raise CatalogError('RECOVERY_REQUIRED','active recovery belongs to another host')
            continue
        reference=item.get('exit_observation')
        if reference is None:
            raise CatalogError('RECOVERY_REQUIRED','interrupted recovery host requires its own exit observation')
        try:
            raw=session.catalog.content.read_object(ObjectRef.model_validate(reference))
            observed=json.loads(raw);clock=item['execution_clock']
            expected=dict(schema_version='uteki-observed-exit-v1',context_ref=session.data['context']['context_ref'],
                native_session_id=native['native_session_id'],recovery_attempt_id=item['attempt_id'],
                clock=clock,owner_pid=item['owner_pid'],clock_domain=clock['domain'],process_group_empty=True)
            if canonical(observed)!=raw or any(observed.get(k)!=v for k,v in expected.items()):
                raise ValueError('recovery exit observation binding differs')
            if observed['process_group_empty'] is not True or clock_domain(version=clock.get('domain_version',1))!=clock['domain']:
                raise ValueError('recovery clock domain differs')
            values=[observed['launched_monotonic'],clock['started_monotonic'],observed['exited_monotonic'],item['charged_seconds']]
            if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
                raise ValueError('invalid recovery clock values')
            if not values[0]<=values[1]<=values[2]:
                raise ValueError('recovery clock outside observed process lifetime')
            upper=values[2]-values[1]
            if upper<item['charged_seconds']:
                raise ValueError('recovery exit bound below its recorded execution')
            changes.append((item,upper,observed['timed_out']))
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise CatalogError('RECOVERY_REQUIRED','recovery host observation could not be verified') from error
    # Validate every pending interval before changing the authoritative head.
    # 先验证全部待恢复区间，再修改权威状态，避免半数证据合法时留下部分更新。
    for item,upper,timed_out in changes:
        session.data['wall_seconds']+=upper-item['charged_seconds']
        item.update(status='reconciled',charged_seconds=upper,finished_at=utc_now(),
            reconciliation=dict(kind='supervised_upper_bound',observation_ref=item['exit_observation'],timed_out=timed_out))
    if changes:session.save()


# 跟踪本次恢复尝试的独立计时区间，继续使用同一会话与账本归属。
class RecoveryClock:
    """One host attempt, independent of original native history and billing."""
    # 先核清前次恢复，再登记当前宿主、计时域和起点；历史超时决定继续保留。
    def __init__(self, session, *, started):
        from .execution_clock import start_clock
        reconcile_recoveries(session)
        self.timed_out=any(item.get('reconciliation',{}).get('timed_out')
            for item in session.data['native_execution'].get('recovery_attempts',[]))
        self.catalog,self.context_ref=session.catalog,session.data['context']['context_ref']
        self.started=started
        self.attempt_id=str(uuid.uuid4())
        self.closed=False
        session.data['native_execution'].setdefault('recovery_attempts',[]).append(dict(
            attempt_id=self.attempt_id,owner_pid=os.getpid(),status='active',started_at=utc_now(),
            execution_clock=start_clock(started,session.data['wall_seconds']),charged_seconds=0.0))
        session.save()

    # 仅追加尚未计入的耗时差额；可同时标记本次恢复完成，避免重复计时。
    def tick(self, *, completed=False):
        if self.closed:return
        session=Session(self.catalog,self.context_ref)
        item=next(v for v in session.data['native_execution']['recovery_attempts'] if v['attempt_id']==self.attempt_id)
        if item['status']!='active' or item['owner_pid']!=os.getpid():
            raise CatalogError('RECOVERY_REQUIRED','recovery interval no longer belongs to this host')
        elapsed=max(item['charged_seconds'],time.monotonic()-self.started)
        session.data['wall_seconds']+=elapsed-item['charged_seconds']
        item['charged_seconds']=elapsed
        if completed:item.update(status='completed',finished_at=utc_now())
        session.save()
        self.closed=completed

    # 完成本次恢复计时；已结束时重复调用不再增加消耗。
    def close(self):
        self.tick(completed=True)
