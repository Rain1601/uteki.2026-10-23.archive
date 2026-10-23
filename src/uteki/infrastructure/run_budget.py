"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.application.run_budget`."""
import sys

from uteki.data_platform.application import run_budget as _implementation

sys.modules[__name__] = _implementation
