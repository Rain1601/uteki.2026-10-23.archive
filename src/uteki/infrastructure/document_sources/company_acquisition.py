"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.connectors.company_acquisition`."""
import sys

from uteki.data_platform.connectors import company_acquisition as _implementation

sys.modules[__name__] = _implementation
