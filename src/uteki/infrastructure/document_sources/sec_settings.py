"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.connectors.sec_settings`."""
import sys

from uteki.data_platform.connectors import sec_settings as _implementation

sys.modules[__name__] = _implementation
