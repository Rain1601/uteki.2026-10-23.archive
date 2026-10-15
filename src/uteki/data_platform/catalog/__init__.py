"""Local metadata catalog, with explicit initialization and ownership."""

from .repository import Catalog
from ..contracts.common import CatalogError

__all__ = ["Catalog", "CatalogError"]
