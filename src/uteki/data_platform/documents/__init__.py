"""Document-first storage and retrieval; no SDK or extraction dependency."""
from .store import DocumentStore, DocumentStoreError

__all__ = ['DocumentStore', 'DocumentStoreError']
