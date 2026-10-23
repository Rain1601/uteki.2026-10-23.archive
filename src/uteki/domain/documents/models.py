"""Compatibility alias until S4; implementation: :mod:`uteki.data_platform.build.document_models`."""
import sys

from uteki.data_platform.build import document_models as _implementation

sys.modules[__name__] = _implementation
