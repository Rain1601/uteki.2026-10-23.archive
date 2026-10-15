"""One monotonic deadline for synchronous preflight and execution."""
import time

from ..contracts.common import CatalogError


class ExecutionLimit:
    def __init__(self, seconds, *, started=None, should_cancel=None):
        self.started = time.monotonic() if started is None else started
        self.deadline = self.started + seconds
        self.should_cancel = should_cancel or (lambda: False)

    def stopped(self):
        return self.should_cancel() or time.monotonic() >= self.deadline

    def check(self, phase='execution'):
        if self.should_cancel():
            raise CatalogError('CANCELLED', 'cancelled at '+phase)
        if time.monotonic() >= self.deadline:
            raise CatalogError('BUDGET_EXCEEDED', 'remaining synchronous time exhausted at '+phase)

    def remaining(self):
        self.check()
        return max(0.0, self.deadline-time.monotonic())

    def elapsed(self):
        return time.monotonic()-self.started
