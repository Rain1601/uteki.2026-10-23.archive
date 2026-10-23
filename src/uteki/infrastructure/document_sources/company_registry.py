"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.connectors.company_registry`."""
import sys

from uteki.data_platform.connectors import company_registry as _implementation

sys.modules[__name__] = _implementation
