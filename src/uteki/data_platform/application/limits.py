# 同步工具预检与执行共享一个单调时钟截止点，阶段切换不会重新获得完整时限。
"""One monotonic deadline for synchronous preflight and execution."""
import time

from ..contracts.common import CatalogError


# 封装剩余时限和宿主取消信号，供读取、索引与数据库查询共同使用。
class ExecutionLimit:
    # 以调用起点加剩余秒数建立截止时间；可接收服务入口更早的起点。
    def __init__(self, seconds, *, started=None, should_cancel=None):
        self.started = time.monotonic() if started is None else started
        self.deadline = self.started + seconds
        self.should_cancel = should_cancel or (lambda: False)

    # 无异常地查询停止条件，适合数据库中断回调等轮询入口。
    def stopped(self):
        return self.should_cancel() or time.monotonic() >= self.deadline

    # 在阶段边界抛出明确取消或超时错误，并带上阶段名称。
    def check(self, phase='execution'):
        if self.should_cancel():
            raise CatalogError('CANCELLED', 'cancelled at '+phase)
        if time.monotonic() >= self.deadline:
            raise CatalogError('BUDGET_EXCEEDED', 'remaining synchronous time exhausted at '+phase)

    # 先确认尚可执行，再返回当前剩余时间，供底层超时配置使用。
    def remaining(self):
        self.check()
        return max(0.0, self.deadline-time.monotonic())

    # 返回从同一调用起点开始的单调耗时，用于累计资源记录。
    def elapsed(self):
        return time.monotonic()-self.started
