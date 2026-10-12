"""Explicit on-demand figure supplement contract; never an inferred material scope."""
from pydantic import Field
from .query_contract import Contract

FIGURE_EVIDENCE_VERSION = 'figure-evidence-v1'

class FigureBundleRef(Contract):
    path: str = Field(min_length=1, pattern=r'\S')
    manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

class FigureReadRequest(Contract):
    source_snapshot_id: str = Field(min_length=1, pattern=r'\S')
    figure_id: str = Field(min_length=1, pattern=r'\S')

class FigureDelivery(Contract):
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=32, json_schema_extra={'uniqueItems': True})
