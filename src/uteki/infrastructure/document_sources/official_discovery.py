"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.connectors.official_discovery`."""
import sys

from uteki.data_platform.connectors import official_discovery as _implementation

sys.modules[__name__] = _implementation
