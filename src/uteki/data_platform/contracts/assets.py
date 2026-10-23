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


# 元数据判断的证据描述：保留原件引用、定位、判断方法与核验状态；不等同于已核实事实。
class Evidence(Contract):
    description: Text
    object_ref: ObjectRef | None
    locator: Text | None
    method: Literal["source_direct", "rule", "model", "manual"]
    method_ref: Text
    content_check: Literal["confirmed", "unverified", "rejected"]


# 公司登记输入：确认身份需要明确身份依据及已确认的证据。
class CompanyInput(Contract):
    canonical_name: Text
    status: Literal["confirmed", "pending_identity"]
    identity_basis_kind: Literal["sec_cik", "lei", "manual_verified"] | None
    identity_basis_value: Text | None
    evidence: Evidence

    # 身份依据类型和值必须成对出现；禁止仅凭公司名称把状态提升为 confirmed。
    @model_validator(mode="after")
    def identity(self):
        if (self.identity_basis_kind is None) != (self.identity_basis_value is None):
            raise ValueError("identity basis kind/value must be provided together")
        if self.status == "confirmed" and (self.identity_basis_value is None or self.evidence.content_check != "confirmed"):
            raise ValueError("confirmed company needs confirmed identity evidence")
        return self


# 证券代码与公司之间有有效期的关系，交易所代码参与区分同名 ticker。
class SecurityInput(Contract):
    company_id: CompanyId
    ticker: Annotated[str, Field(pattern=r"^[A-Z0-9.\-]+$")]
    exchange_mic: Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]
    security_type: Literal["common", "preferred", "adr", "unit", "warrant", "other"]
    valid_from: date | None
    valid_to: date | None
    status: Literal["confirmed", "pending"]
    evidence: Evidence

    # 校验有效期方向，并确保已确认证券关系有已确认的证据支持。
    @model_validator(mode="after")
    def interval(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("security interval is reversed")
        if self.status == "confirmed" and self.evidence.content_check != "confirmed":
            raise ValueError("confirmed security needs confirmed evidence")
        return self


# 来源登记信息与策略引用；发布者、来源平台和具体网址分别保留。
class SourceInput(Contract):
    source_kind: Literal["sec_edgar", "sec_xbrl_api", "official_site", "user_file"]
    publisher_name: Text
    publisher_company_id: CompanyId | None
    platform_name: Text | None
    canonical_url: Text | None
    policy_ref: Text


# 逻辑资产的登记描述，与之后某次下载的原件快照、格式和构建版本分离。
class AssetInput(Contract):
    asset_kind: Literal["document", "dataset"]
    material_type: Text
    title: Text
    language: Text | None
    natural_key: Text | None
    reporting_period: FiscalPeriod | None
    declared_scope: Text | None
    evidence: Evidence

    # 数据集必须说明覆盖范围，避免把边界未知的数据登记成完整集合。
    @model_validator(mode="after")
    def scoped_dataset(self):
        if self.asset_kind == "dataset" and self.declared_scope is None:
            raise ValueError("dataset requires declared scope")
        return self


# 一次采集的来源、请求与最终地址及时间记录；采集时间和来源可用时间分别保存。
class Acquisition(Contract):
    source_id: SourceId
    request_url: Text | None
    final_url: Text | None
    acquired_at: Text
    published_at: SourceTime
    available_at: SourceTime
    source_revised_at: SourceTime

    # 采集时刻必须显式为 UTC；不把没有时区的本地时间默认为 UTC。
    @model_validator(mode="after")
    def acquired_utc(self):
        from datetime import datetime, timedelta
        value = datetime.fromisoformat(self.acquired_at)
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("acquired_at must explicitly be UTC")
        return self


# 快照与公司的关系声明，区分发行者、主体和仅被提及者，并保留确认依据。
class SnapshotRelation(Contract):
    company_id: CompanyId
    role: Literal["issuer", "subject", "mentioned"]
    basis: Literal["source_metadata", "rule", "model"]
    status: Literal["confirmed", "candidate"]
    evidence: Evidence

    # 关系状态为 confirmed 时，关联证据也必须已经确认。
    @model_validator(mode="after")
    def confirmed_basis(self):
        if self.status == "confirmed" and self.evidence.content_check != "confirmed":
            raise ValueError("confirmed relation requires confirmed evidence")
        return self


# 完整版本引用：逻辑资产、原件快照、格式表示和处理构建缺一不可。
class AssetRef(Contract):
    asset_id: AssetId
    snapshot_id: SnapshotId
    representation_id: RepresentationId
    build_id: BuildId


# 同一快照的一种格式表示，通过输入清单绑定主原件与附属资源。
class Representation(Contract):
    representation_id: RepresentationId
    format: Literal["pdf", "html", "xbrl_instance", "api_json"]
    input_manifest: ObjectRef


# 记录处理器版本、配置对象、处理配置档和分类体系引用，描述构建可复现的输入条件。
class BuildRecipe(Contract):
    processor_version: Text
    config: ObjectRef
    profile_ref: Text
    taxonomy_ref: Text

    # 由输入清单和处理配方生成确定性摘要；不纳入 build_id，便于识别相同构建条件。
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


# 仅接受规范的 POSIX 相对路径，拒绝绝对路径、回退片段和反斜杠等含混表示。
def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or value != path.as_posix() or any(p in {".", ".."} for p in path.parts) or not path.parts:
        raise ValueError("canonical relative artifact path required")
    return value


ArtifactPath = Annotated[Text, AfterValidator(safe_relative)]


# 将构建内的规范相对路径绑定到不可变内容对象，供发布时核对字节。
class ArtifactFile(Contract):
    path: ArtifactPath
    object_ref: ObjectRef


# 一个构建的发布清单：绑定完整版本、输入、配方以及各产物的内容摘要。
class BuildManifest(Contract):
    schema_version: Literal["uteki-build-v1", "uteki-html-build-v1"]
    asset_ref: AssetRef
    input_manifest: ObjectRef
    recipe: BuildRecipe
    files: tuple[ArtifactFile, ...]

    # 文件路径不能重复，也不能把 manifest.json 自己纳入清单形成自引用。
    @model_validator(mode="after")
    def unique_files(self):
        names = [f.path for f in self.files]
        if len(set(names)) != len(names) or "manifest.json" in names:
            raise ValueError("duplicate or self-referencing manifest file")
        return self

    # 按路径排序文件列表后再编码，使文件登记顺序不影响清单的内容身份。
    def canonical_bytes(self):
        value = BuildManifest.model_validate(self).model_dump(mode="json")
        value["files"].sort(key=lambda item: item["path"])
        return canonical(value)


# 存储层的简单章节节点，仅保存标题与父节点关系。
class Section(Contract):
    id: Text
    title: Text
    parent_id: Text | None


# 在输入资源中定位半开字节区间 [start, end)，区别于 HTML 文本字符定位。
class ByteLocator(Contract):
    kind: Literal["input_bytes"]
    resource_key: Text | None
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]

    # 除字段自身的非负约束外，字节范围还必须非空且方向正确。
    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("empty or reversed byte range")
        return self


# 绑定原件字节范围的文本块，同时保留所属章节和需要一起解释的依赖块 ID。
class Block(Contract):
    id: Text
    section_id: Text | None
    text: Text
    locator: ByteLocator
    dependency_ids: tuple[Text, ...]


Readiness = Literal["ready", "partial", "not_ready"]


# 存储基础能力的就绪声明；这里尚不支持的表格、图片、记录和搜索被限定为 not_ready。
class ContentReadiness(Contract):
    original: Readiness
    text: Readiness
    outline: Readiness
    tables: Literal["not_ready"]
    images: Literal["not_ready"]
    records: Literal["not_ready"]
    search: Literal["not_ready"]


# 对外描述构建的内容就绪度、发布就绪度与缺口，避免把生成产物等同于可用能力。
class BuildSchema(Contract):
    schema_version: Literal["uteki-asset-schema-storage-v1"]
    asset_ref: AssetRef
    content_readiness: ContentReadiness
    published_readiness: ContentReadiness
    gaps: tuple[Text, ...]
    description: Text | None


# 保存问题和覆盖程度；没有问题条目也不自动证明 coverage 为 complete。
class Quality(Contract):
    issues: tuple[Text, ...]
    coverage: Literal["complete", "partial", "unknown"]
