"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.build.sec`."""
import sys

from uteki.data_platform.build import sec as _implementation

sys.modules[__name__] = _implementation
