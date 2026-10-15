"""Immutable byte references and representation input manifests.

These contracts describe bytes, not company identity, source approval, or
snapshot publication. Those remain the responsibility of the catalog.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always",
    )


class ObjectRef(_Contract):
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)


class _Resource(_Contract):
    # Opaque identity within this representation; never used as a local path.
    resource_key: str = Field(min_length=1)
    # The caller must explicitly provide a URL or acknowledge it is unknown.
    source_url: str | None

    @field_validator("resource_key", "source_url")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
        ):
            raise ValueError("text must be nonblank UTF-8 without control characters")
        return value


class PresentResource(_Resource):
    status: Literal["present"]
    object_ref: ObjectRef


class MissingResource(_Resource):
    status: Literal["missing"]
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        _Resource.nonblank(value)
        return value


Resource = Annotated[PresentResource | MissingResource, Field(discriminator="status")]


class InputManifest(_Contract):
    schema_version: Literal["uteki-input-manifest-v1"]
    main: ObjectRef
    main_source_url: str | None
    resources: tuple[Resource, ...]

    @field_validator("main_source_url")
    @classmethod
    def nonblank_url(cls, value: str | None) -> str | None:
        return _Resource.nonblank(value)

    @model_validator(mode="after")
    def unique_resources(self) -> InputManifest:
        keys = [resource.resource_key for resource in self.resources]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate resource_key")
        return self

    def canonical_bytes(self) -> bytes:
        """Versioned, order-independent JSON encoding; not a general JSON canon."""
        # Frozen models can still be constructed/copied without validation.
        value = InputManifest.model_validate(self).model_dump(mode="json")
        value["resources"].sort(key=lambda resource: resource["resource_key"])
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
