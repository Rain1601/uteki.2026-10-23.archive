"""Versioned access to immutable run artifacts, independent of financial evidence."""
from typing import Literal
from pydantic import Field
from .query_contract import Contract
from .execution_scope import ExecutionScope

ARTIFACT_READ_MAX_BYTES = 100000


class ArtifactRef(Contract):
    schema_version: Literal['run-artifact-v1'] = 'run-artifact-v1'
    artifact_id: str
    kind: str
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=0)
    scope: ExecutionScope
    scope_id: str
    created_step: int = Field(ge=0)
    parent_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    evidence_id: str | None = None


class ArtifactCursor(Contract):
    cursor_version: Literal['run-artifact-cursor-v1'] = 'run-artifact-cursor-v1'
    artifact_id: str
    sha256: str
    scope_id: str
    snapshot_id: str
    pointer: str
    offset: int = Field(ge=0)


class ArtifactReadRequest(Contract):
    artifact_id: str = Field(min_length=1)
    pointer: str = Field(default='', max_length=2000)
    offset: int | None = Field(default=None, ge=0)
    cursor: ArtifactCursor | None = None
    limit: int = Field(default=12, ge=1, le=1000)
    max_bytes: int = Field(default=12000, ge=512, le=ARTIFACT_READ_MAX_BYTES)


class ToolReceipt(Contract):
    schema_version: Literal['data-tool-receipt-v1'] = 'data-tool-receipt-v1'
    step: int
    action: str
    requirement_ids: tuple[str, ...] = ()
    request_fingerprint: str
    status: str
    error_code: str | None = None
    layer: str
    retryable: bool = False
    artifact: ArtifactRef
    progress_delta: bool
    observation_bytes: int
    execution_limited: bool = False
    preview_truncated: bool = False
