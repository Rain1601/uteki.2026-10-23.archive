"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.connectors.filing_integrity`."""
import sys

from uteki.data_platform.connectors import filing_integrity as _implementation

sys.modules[__name__] = _implementation
