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


# 内容对象层的严格不可变契约；只描述字节，不承担公司身份或来源批准职责。
class _Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always",
    )


# 用 SHA-256 与字节长度标识内容；具体读取时仍须核对原件是否与引用一致。
class ObjectRef(_Contract):
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)


# 表示内的附属资源基类：resource_key 是不透明标识，不能直接作为磁盘路径使用。
class _Resource(_Contract):
    # Opaque identity within this representation; never used as a local path.
    resource_key: str = Field(min_length=1)
    # The caller must explicitly provide a URL or acknowledge it is unknown.
    source_url: str | None

    # 允许显式未知的 URL 为 None；一旦提供文本，必须非空且不含控制字符或代理码位。
    @field_validator("resource_key", "source_url")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
        ):
            raise ValueError("text must be nonblank UTF-8 without control characters")
        return value


# 已取得的资源必须给出内容对象引用，不能只用网址表示“已经保存”。
class PresentResource(_Resource):
    status: Literal["present"]
    object_ref: ObjectRef


# 未取得的资源仍保留身份与缺失原因，让输入清单显式表达不完整性。
class MissingResource(_Resource):
    status: Literal["missing"]
    reason: str = Field(min_length=1)

    # 缺失原因沿用文本约束，避免只有空白的说明通过校验。
    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        _Resource.nonblank(value)
        return value


Resource = Annotated[PresentResource | MissingResource, Field(discriminator="status")]


# 一份格式表示的完整输入清单：主原件、来源地址和附属资源状态共同形成内容身份。
class InputManifest(_Contract):
    schema_version: Literal["uteki-input-manifest-v1"]
    main: ObjectRef
    main_source_url: str | None
    resources: tuple[Resource, ...]

    # 主原件 URL 与附属资源 URL 使用同样的文本边界，不猜测未知地址。
    @field_validator("main_source_url")
    @classmethod
    def nonblank_url(cls, value: str | None) -> str | None:
        return _Resource.nonblank(value)

    # 资源键在同一清单内唯一，避免读取时出现一个键对应多个内容或状态。
    @model_validator(mode="after")
    def unique_resources(self) -> InputManifest:
        keys = [resource.resource_key for resource in self.resources]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate resource_key")
        return self

    # 重新校验后按资源键排序再编码，使资源列举顺序不改变清单身份。
    def canonical_bytes(self) -> bytes:
        """Versioned, order-independent JSON encoding; not a general JSON canon."""
        # Frozen models can still be constructed/copied without validation.
        value = InputManifest.model_validate(self).model_dump(mode="json")
        value["resources"].sort(key=lambda resource: resource["resource_key"])
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    # 对规范清单字节求摘要；这标识整份输入集合，不是仅主文件的摘要。
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
