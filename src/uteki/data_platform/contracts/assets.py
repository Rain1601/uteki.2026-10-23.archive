"""Identity, source, snapshot and publication contracts for the catalog slice."""
from __future__ import annotations

from datetime import date
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, AfterValidator, model_validator

from .common import Contract, Text, SourceTime, FiscalPeriod, id_type, digest, canonical
from .content import ObjectRef

CompanyId = id_type("co")
AssetId = id_type("as")
SnapshotId = id_type("sn")
RepresentationId = id_type("rp")
BuildId = id_type("bd")
RunId = id_type("run")
SourceId = id_type("src")


class Evidence(Contract):
    description: Text
    object_ref: ObjectRef | None
    locator: Text | None
    method: Literal["source_direct", "rule", "model", "manual"]
    method_ref: Text
    content_check: Literal["confirmed", "unverified", "rejected"]


class CompanyInput(Contract):
    canonical_name: Text
    status: Literal["confirmed", "pending_identity"]
    identity_basis_kind: Literal["sec_cik", "lei", "manual_verified"] | None
    identity_basis_value: Text | None
    evidence: Evidence

    @model_validator(mode="after")
    def identity(self):
        if (self.identity_basis_kind is None) != (self.identity_basis_value is None):
            raise ValueError("identity basis kind/value must be provided together")
        if self.status == "confirmed" and (self.identity_basis_value is None or self.evidence.content_check != "confirmed"):
            raise ValueError("confirmed company needs confirmed identity evidence")
        return self


class SecurityInput(Contract):
    company_id: CompanyId
    ticker: Annotated[str, Field(pattern=r"^[A-Z0-9.\-]+$")]
    exchange_mic: Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]
    security_type: Literal["common", "preferred", "adr", "unit", "warrant", "other"]
    valid_from: date | None
    valid_to: date | None
    status: Literal["confirmed", "pending"]
    evidence: Evidence

    @model_validator(mode="after")
    def interval(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("security interval is reversed")
        if self.status == "confirmed" and self.evidence.content_check != "confirmed":
            raise ValueError("confirmed security needs confirmed evidence")
        return self


class SourceInput(Contract):
    source_kind: Literal["sec_edgar", "sec_xbrl_api", "official_site", "user_file"]
    publisher_name: Text
    publisher_company_id: CompanyId | None
    platform_name: Text | None
    canonical_url: Text | None
    policy_ref: Text


class AssetInput(Contract):
    asset_kind: Literal["document", "dataset"]
    material_type: Text
    title: Text
    language: Text | None
    natural_key: Text | None
    reporting_period: FiscalPeriod | None
    declared_scope: Text | None
    evidence: Evidence

    @model_validator(mode="after")
    def scoped_dataset(self):
        if self.asset_kind == "dataset" and self.declared_scope is None:
            raise ValueError("dataset requires declared scope")
        return self


class Acquisition(Contract):
    source_id: SourceId
    request_url: Text | None
    final_url: Text | None
    acquired_at: Text
    published_at: SourceTime
    available_at: SourceTime
    source_revised_at: SourceTime

    @model_validator(mode="after")
    def acquired_utc(self):
        from datetime import datetime, timedelta
        value = datetime.fromisoformat(self.acquired_at)
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("acquired_at must explicitly be UTC")
        return self


class SnapshotRelation(Contract):
    company_id: CompanyId
    role: Literal["issuer", "subject", "mentioned"]
    basis: Literal["source_metadata", "rule", "model"]
    status: Literal["confirmed", "candidate"]
    evidence: Evidence

    @model_validator(mode="after")
    def confirmed_basis(self):
        if self.status == "confirmed" and self.evidence.content_check != "confirmed":
            raise ValueError("confirmed relation requires confirmed evidence")
        return self


class AssetRef(Contract):
    asset_id: AssetId
    snapshot_id: SnapshotId
    representation_id: RepresentationId
    build_id: BuildId


class Representation(Contract):
    representation_id: RepresentationId
    format: Literal["pdf", "html", "xbrl_instance", "api_json"]
    input_manifest: ObjectRef


class BuildRecipe(Contract):
    processor_version: Text
    config: ObjectRef
    profile_ref: Text
    taxonomy_ref: Text

    def build_key(self, reference: AssetRef, input_manifest: ObjectRef) -> str:
        recipe = BuildRecipe.model_validate(self)
        reference = AssetRef.model_validate(reference)
        input_manifest = ObjectRef.model_validate(input_manifest)
        value = {
            "schema_version": "uteki-build-key-v1", "asset_id": reference.asset_id,
            "snapshot_id": reference.snapshot_id, "representation_id": reference.representation_id,
            "input_manifest_sha256": input_manifest.sha256, "processor_version": recipe.processor_version,
            "config_sha256": recipe.config.sha256, "profile_ref": recipe.profile_ref, "taxonomy_ref": recipe.taxonomy_ref,
        }
        return digest(canonical(value))


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or value != path.as_posix() or any(p in {".", ".."} for p in path.parts) or not path.parts:
        raise ValueError("canonical relative artifact path required")
    return value


ArtifactPath = Annotated[Text, AfterValidator(safe_relative)]


class ArtifactFile(Contract):
    path: ArtifactPath
    object_ref: ObjectRef


class BuildManifest(Contract):
    schema_version: Literal["uteki-build-v1"]
    asset_ref: AssetRef
    input_manifest: ObjectRef
    recipe: BuildRecipe
    files: tuple[ArtifactFile, ...]

    @model_validator(mode="after")
    def unique_files(self):
        names = [f.path for f in self.files]
        if len(set(names)) != len(names) or "manifest.json" in names:
            raise ValueError("duplicate or self-referencing manifest file")
        return self

    def canonical_bytes(self):
        value = BuildManifest.model_validate(self).model_dump(mode="json")
        value["files"].sort(key=lambda item: item["path"])
        return canonical(value)


class Section(Contract):
    id: Text
    title: Text
    parent_id: Text | None


class ByteLocator(Contract):
    kind: Literal["input_bytes"]
    resource_key: Text | None
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("empty or reversed byte range")
        return self


class Block(Contract):
    id: Text
    section_id: Text | None
    text: Text
    locator: ByteLocator
    dependency_ids: tuple[Text, ...]


Readiness = Literal["ready", "partial", "not_ready"]


class ContentReadiness(Contract):
    original: Readiness
    text: Readiness
    outline: Readiness
    tables: Literal["not_ready"]
    images: Literal["not_ready"]
    records: Literal["not_ready"]
    search: Literal["not_ready"]


class BuildSchema(Contract):
    schema_version: Literal["uteki-asset-schema-storage-v1"]
    asset_ref: AssetRef
    content_readiness: ContentReadiness
    published_readiness: ContentReadiness
    gaps: tuple[Text, ...]
    description: Text | None


class Quality(Contract):
    issues: tuple[Text, ...]
    coverage: Literal["complete", "partial", "unknown"]
