"""Compatibility alias for the shared, SDK-independent budget implementation."""
import sys

from uteki.infrastructure import run_budget as _implementation

sys.modules[__name__] = _implementation
