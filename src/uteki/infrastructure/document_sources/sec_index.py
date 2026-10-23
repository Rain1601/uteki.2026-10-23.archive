"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.build.sec_index`."""
import sys

from uteki.data_platform.build import sec_index as _implementation

sys.modules[__name__] = _implementation
