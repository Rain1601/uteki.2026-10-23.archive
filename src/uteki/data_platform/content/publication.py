"""Real validation and file/SQLite publication for the minimum storage format."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from pydantic import ValidationError

from ..catalog.database import ensure_directory, read_regular, write_control
from ..catalog.repository import operation
from ..contracts.common import CatalogError, canonical, digest, utc_now
from ..contracts.assets import Block, BuildManifest, BuildRecipe, BuildSchema, Quality, Representation, Section
from ..contracts.content import MissingResource, ObjectRef, PresentResource
from .store import ContentStoreError, _fsync_directory

REQUIRED_FILES = {"sections.jsonl", "blocks.jsonl", "quality.json", "asset-schema.json"}


# 先拒绝重复键和非有限数，再由模型按 JSON 规则校验，避免宽松解析掩盖输入歧义。
def validated_json(model, raw):
    # 逐对构造对象，重复键立即失败，避免 JSON 默认以后值覆盖前值。
    def unique_pairs(pairs):
        value = {}
        for key,item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    # 拒绝 NaN/Infinity 等非标准 JSON 常量。
    def invalid_constant(value):
        raise ValueError("non-finite JSON constant")
    json.loads(raw,object_pairs_hook=unique_pairs,parse_constant=invalid_constant)
    # Use JSON validation, preserving the contract's JSON array -> tuple rules.
    return model.model_validate_json(raw)


# 枚举产物目录的相对文件集合；拒绝链接与特殊文件，供完整性检查发现缺件或额外文件。
def file_names(directory: Path) -> set[str]:
    if not directory.is_dir() or directory.is_symlink():
        raise CatalogError("PUBLICATION_INVALID", "missing or unsafe artifact directory")
    result = set()
    for path in directory.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise CatalogError("PUBLICATION_INVALID", "artifact directory contains a link or special file")
        result.add(path.relative_to(directory).as_posix())
    return result


# 在目录独占锁下把完整候选版移动到不可覆盖的最终位置，并同步文件和两侧父目录。
def move_complete(source: Path, destination: Path, *, checkpoint=None):
    if destination.exists() or destination.is_symlink():
        raise CatalogError("CATALOG_INCONSISTENT", "immutable version directory already exists")
    # The Catalog's exclusive root lock protects this no-overwrite precondition.
    for relative in file_names(source):
        path = source / relative
        path.chmod(0o444)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    for path in sorted((p for p in source.rglob("*") if p.is_dir()), reverse=True):
        _fsync_directory(path)
    _fsync_directory(source)
    if checkpoint is not None:
        checkpoint('before_publication_move')
    os.rename(source, destination)
    _fsync_directory(source.parent)
    _fsync_directory(destination.parent)


# 对内容依赖图作深度优先检查，拒绝悬空引用和循环依赖。
def check_graph(edges: dict[str, tuple[str, ...]]):
    visiting, done = set(), set()
    # visiting 表示当前递归路径，done 表示已完成节点；二者区分环与正常共享依赖。
    def visit(node):
        if node not in edges:
            raise CatalogError("PUBLICATION_INVALID", "reference points to a missing content item")
        if node in visiting:
            raise CatalogError("PUBLICATION_INVALID", "content dependency cycle")
        if node in done:
            return
        visiting.add(node)
        for parent in edges[node]:
            visit(parent)
        visiting.remove(node)
        done.add(node)
    for node in edges:
        visit(node)


# 协调文件产物和 SQLite 状态；先校验并移动文件，再确认数据库发布，保留中断后的恢复边界。
class Publication:
    # 绑定目录与可选阶段回调；回调可用于观察或注入中断，不承担自动重试。
    def __init__(self, catalog, *, checkpoint=None):
        self.catalog = catalog
        self.root = catalog.root
        self.checkpoint = checkpoint

    # 若配置了回调则报告当前阶段，回调异常直接传播。
    def check(self, phase):
        if self.checkpoint is not None:
            self.checkpoint(phase)

    # 统一最终目录移动入口，并把阶段回调传给底层持久化流程。
    def move(self, source, destination):
        if self.checkpoint is None:
            move_complete(source,destination)
        else:
            move_complete(source,destination,checkpoint=self.checkpoint)

    # 根据 final 选择快照最终目录或以 snapshot_id 命名的暂存目录。
    def snapshot_path(self, row, *, final):
        if final:
            return self.root / "assets" / row["asset_id"] / "snapshots" / row["snapshot_id"]
        return self.root / "staging" / ("snapshot-" + row["snapshot_id"])

    # 构建最终路径按 build_id 定位，暂存路径按该次作业的 job_id 隔离。
    def build_path(self, row, *, final):
        if final:
            return self.root / "assets" / row["asset_id"] / "builds" / row["build_id"]
        return self.root / "staging" / row["job_id"]

    # 按稳定顺序重建快照的表示列表，并将持久化引用恢复成类型化对象。
    def _representations(self, snapshot_id):
        return [Representation(representation_id=row["representation_id"],format=row["format"],
                               input_manifest=ObjectRef.model_validate_json(row["input_ref"]))
                for row in self.catalog._db.execute("SELECT * FROM snapshot_representations WHERE snapshot_id=? ORDER BY representation_id", (snapshot_id,))]

    # 由当前登记数据生成待封存快照；完整性声明为 complete 时禁止存在缺失资源。
    def _snapshot_value(self, row, frozen_at):
        representations = self._representations(row["snapshot_id"])
        if not representations:
            raise CatalogError("PUBLICATION_INVALID", "snapshot has no representations")
        metadata = json.loads(row["payload"])
        for representation in representations:
            manifest = self.catalog.content.read_manifest(representation.input_manifest)
            if metadata["completeness"] == "complete" and any(isinstance(r,MissingResource) for r in manifest.resources):
                raise CatalogError("PUBLICATION_INVALID", "declared complete snapshot has missing input resources")
        return dict(schema_version="uteki-snapshot-v1",snapshot_id=row["snapshot_id"],asset_id=row["asset_id"],
                    frozen_at=frozen_at,metadata=metadata,representations=[r.model_dump(mode="json") for r in representations],
                    relations=self.catalog.snapshot_relations(row["snapshot_id"]))

    # 封存快照清单、写入暂存文件、验证并移动，最后将 collecting 确认为 frozen。
    @operation
    def freeze_snapshot(self, snapshot_id):
        self.check('snapshot_freeze_started')
        row = self.catalog.get_snapshot(snapshot_id)
        if row["status"] == "frozen":
            self.verify_snapshot(snapshot_id)
            return row
        if row["status"] != "collecting" or row["manifest_ref"] is not None:
            raise CatalogError("INVALID_STATE", "snapshot is terminal or requires explicit recovery")
        try:
            value = self._snapshot_value(row,utc_now())
            raw = canonical(value)
            # 清单字节先写入对象仓库，再将引用登记为封存点；之后不能继续补改快照输入。
            reference = self.catalog.content.put_object(raw)
            self.check('before_snapshot_seal')
            with self.catalog.database.transaction():
                self.catalog._db.execute("UPDATE asset_snapshots SET manifest_ref=?,updated_at=? WHERE snapshot_id=?",
                                         (reference.model_dump_json(),utc_now(),snapshot_id))
            row = self.catalog.get_snapshot(snapshot_id)
            stage = ensure_directory(self.root,"staging/snapshot-"+snapshot_id)
            write_control(stage/"snapshot-manifest.json",raw)
            representations = ensure_directory(stage,"representations")
            for item in value["representations"]:
                self.check('snapshot_representation_write')
                write_control(representations/(item["representation_id"]+".json"),canonical(item))
            # 暂存版先完整验证，再移动到最终目录；数据库 frozen 只在移动并同步成功后确认。
            self.verify_snapshot(snapshot_id,final=False)
            target_parent = ensure_directory(self.root,f"assets/{row['asset_id']}/snapshots")
            self.move(stage,target_parent/snapshot_id)
            self.commit_snapshot(snapshot_id)
        except (CatalogError, ContentStoreError, OSError, ValidationError) as error:
            # 目录已移动或数据库提交头不确定时保留原状态供恢复，不能因末尾 I/O 错误抹成失败。
            if not self.catalog.database.head_uncertain:
                current = self.catalog.get_snapshot(snapshot_id)
                # A complete moved version can be recovered; do not discard the
                # uncertain publication outcome after a directory sync failure.
                if current["status"] == "collecting" and not self.snapshot_path(current,final=True).exists():
                    self.fail_snapshot(snapshot_id,getattr(error,"code","STORAGE_IO_ERROR"))
            raise
        return self.catalog.get_snapshot(snapshot_id)

    # 显式继续既有快照候选：只接纳可验证的原文件，不重写已封存内容。
    @operation
    def continue_snapshot(self, snapshot_id):
        """Explicitly publish an intact candidate; never repair sealed files."""
        row = self.catalog.get_snapshot(snapshot_id)
        if row['status'] == 'frozen' or self.snapshot_path(row,final=True).exists():
            self.commit_snapshot(snapshot_id)
        elif row['status'] != 'collecting':
            raise CatalogError('INVALID_STATE','terminal snapshot cannot be continued')
        elif row['manifest_ref'] is None:
            self.freeze_snapshot(snapshot_id)
        else:
            self.verify_snapshot(snapshot_id,final=False)
            parent = ensure_directory(self.root,f"assets/{row['asset_id']}/snapshots")
            self.move(self.snapshot_path(row,final=False),parent/snapshot_id)
            self.commit_snapshot(snapshot_id)
        return self.catalog.get_snapshot(snapshot_id)

    # 先验证最终快照并补做目录同步，再在事务内确认 frozen 及资产的 has_snapshot 状态。
    def commit_snapshot(self, snapshot_id):
        row = self.catalog.get_snapshot(snapshot_id)
        self.verify_snapshot(snapshot_id)
        if row["status"] == "frozen":
            return
        if row["status"] != "collecting":
            raise CatalogError("INVALID_STATE", "cannot commit failed snapshot")
        self._sync_moved(self.snapshot_path(row,final=True))
        self.check('before_snapshot_commit')
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_snapshots SET status='frozen',updated_at=? WHERE snapshot_id=?", (utc_now(),snapshot_id))
            self.catalog._db.execute("UPDATE assets SET status='has_snapshot',updated_at=? WHERE asset_id=? AND status='registered'", (utc_now(),row["asset_id"]))

    # 只允许 collecting 快照转成失败；已冻结或已失败版本不再更改终态。
    def fail_snapshot(self, snapshot_id, code):
        row = self.catalog.get_snapshot(snapshot_id)
        if row["status"] != "collecting":
            raise CatalogError("INVALID_STATE", "terminal snapshot cannot be failed")
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_snapshots SET status='failed',failure_code=?,updated_at=? WHERE snapshot_id=?", (code,utc_now(),snapshot_id))

    # 交叉比对封存对象、目录字节、数据库输入和完整文件集合，返回通过验证的快照值。
    def verify_snapshot(self, snapshot_id, *, final=True):
        row = self.catalog.get_snapshot(snapshot_id)
        if row["manifest_ref"] is None:
            raise CatalogError("PUBLICATION_INVALID", "no sealed snapshot manifest")
        reference = ObjectRef.model_validate_json(row["manifest_ref"])
        expected = self.catalog.content.read_object(reference)
        directory = self.snapshot_path(row,final=final)
        raw = read_regular(directory/"snapshot-manifest.json")
        if raw != expected:
            raise CatalogError("PUBLICATION_INVALID", "snapshot file differs from sealed content")
        value = json.loads(raw)
        wanted = self._snapshot_value(row,value["frozen_at"])
        if canonical(wanted) != raw:
            raise CatalogError("PUBLICATION_INVALID", "snapshot identity or database inputs differ")
        names = {"snapshot-manifest.json"}
        for item in value["representations"]:
            name = "representations/"+item["representation_id"]+".json"
            names.add(name)
            if read_regular(directory/name) != canonical(item):
                raise CatalogError("PUBLICATION_INVALID", "representation metadata differs")
        if file_names(directory) != names:
            raise CatalogError("PUBLICATION_INVALID", "snapshot file set differs")
        return value

    # 核对构建身份与全部文件字节，写入并验证暂存候选后，封存清单引用和能力就绪状态。
    @operation
    def stage(self, build_id, *, files: dict[str, bytes], manifest: BuildManifest):
        self.check('build_stage_started')
        build = self.catalog.get_build(build_id)
        if build["status"] != "staging" or build["manifest_ref"] is not None:
            raise CatalogError("INVALID_STATE", "build is terminal or already sealed")
        try:
            manifest = BuildManifest.model_validate(manifest)
            self._binding(build,manifest)
            if not isinstance(files,dict) or set(files) != {f.path for f in manifest.files}:
                raise CatalogError("PUBLICATION_INVALID", "supplied files do not match manifest")
            stage = ensure_directory(self.root,"staging/"+build["job_id"])
            for item in manifest.files:
                self.check('build_artifact_write')
                raw = files[item.path]
                if not isinstance(raw,bytes) or len(raw) != item.object_ref.byte_length or digest(raw) != item.object_ref.sha256:
                    raise CatalogError("PUBLICATION_INVALID", "supplied artifact bytes differ from manifest")
                parent = ensure_directory(stage, str(Path(item.path).parent))
                write_control(parent/Path(item.path).name,raw)
            write_control(stage/"manifest.json",manifest.canonical_bytes())
            # 先从实际落盘文件验证内容，再封存清单及就绪状态，避免仅凭调用方声明宣布候选完整。
            self.verify_build(build,final=False)
            reference = self.catalog.content.put_object(manifest.canonical_bytes())
            if manifest.schema_version == "uteki-html-build-v1":
                from ..contracts.evidence import HtmlSchema
                schema = HtmlSchema.model_validate_json(files["asset-schema.json"])
            else:
                schema = BuildSchema.model_validate_json(files["asset-schema.json"])
            self.check('before_build_seal')
            with self.catalog.database.transaction():
                self.catalog._db.execute("UPDATE asset_builds SET manifest_ref=?,readiness_json=?,updated_at=? WHERE build_id=?",
                    (reference.model_dump_json(),schema.published_readiness.canonical_bytes().decode(),utc_now(),build_id))
        except (CatalogError,ContentStoreError,OSError,ValidationError) as error:
            if not self.catalog.database.head_uncertain:
                self.catalog.fail_build(build_id,failure_code=getattr(error,"code","PUBLICATION_INVALID"))
            raise
        return self.catalog.get_build(build_id)

    # 构建清单必须同时匹配资产版本、输入、配方及构建键，防止混用另一份产物。
    def _binding(self, build, manifest):
        if (manifest.asset_ref != self.catalog.asset_ref(build)
                or manifest.input_manifest != ObjectRef.model_validate_json(build["input_ref"])
                or manifest.recipe != BuildRecipe.model_validate_json(build["recipe"])
                or manifest.recipe.build_key(manifest.asset_ref,manifest.input_manifest) != build["build_key"]):
            raise CatalogError("PUBLICATION_INVALID", "manifest identity, input or recipe differs from registered build")

    # 校验文件集、哈希、版本绑定及内容约束；HTML 另按冻结输入重建比对，成功返回清单。
    def verify_build(self, build, *, final):
        directory = self.build_path(build,final=final)
        try:
            raw = read_regular(directory/"manifest.json")
            manifest = validated_json(BuildManifest,raw)
            if manifest.canonical_bytes() != raw:
                raise CatalogError("PUBLICATION_INVALID", "noncanonical build manifest")
            self._binding(build,manifest)
            if build["manifest_ref"] is not None:
                if self.catalog.content.read_object(ObjectRef.model_validate_json(build["manifest_ref"])) != raw:
                    raise CatalogError("PUBLICATION_INVALID", "manifest differs from sealed candidate")
            # 不同版本采用各自精确文件集合；缺文件和额外文件都失败，防止混入旧构建残留。
            required_files = REQUIRED_FILES
            if manifest.schema_version == "uteki-html-build-v1":
                from ..build.pipeline import HTML_FILES
                required_files = HTML_FILES
            if {f.path for f in manifest.files} != required_files or file_names(directory) != required_files | {"manifest.json"}:
                raise CatalogError("PUBLICATION_INVALID", "unsupported, missing or extra build files")
            payloads = {}
            for item in manifest.files:
                content = read_regular(directory/item.path)
                if len(content) != item.object_ref.byte_length or digest(content) != item.object_ref.sha256:
                    raise CatalogError("PUBLICATION_INVALID", "artifact hash or size mismatch: "+item.path)
                payloads[item.path] = content
            # 构建验证还要回到冻结快照和输入原件，确保内容哈希正确但版本绑错的产物不能通过。
            frozen_snapshot = self.catalog.read_snapshot(build["snapshot_id"])
            inputs = self.catalog.content.read_manifest(manifest.input_manifest)
            if manifest.schema_version == "uteki-html-build-v1":
                representation = next(r for r in frozen_snapshot["representations"] if r["representation_id"] == manifest.asset_ref.representation_id)
                if representation["format"] != "html":
                    raise CatalogError("PUBLICATION_INVALID", "HTML build must bind an HTML representation")
                from ..build.validate import validate_html_artifacts
                schema = validate_html_artifacts(self.catalog.content, manifest, inputs, payloads)
                if build["readiness_json"] is not None and build["readiness_json"] != schema.published_readiness.canonical_bytes().decode():
                    raise CatalogError("PUBLICATION_INVALID", "database readiness differs from frozen HTML schema")
                return manifest
            sections = [validated_json(Section,line) for line in payloads["sections.jsonl"].splitlines()]
            blocks = [validated_json(Block,line) for line in payloads["blocks.jsonl"].splitlines()]
            if len({s.id for s in sections}) != len(sections) or len({b.id for b in blocks}) != len(blocks):
                raise CatalogError("PUBLICATION_INVALID", "duplicate content item ID")
            section_ids = {s.id for s in sections}
            # 章节父关系与块依赖分别验图；重复 ID、悬空引用和环都会拒绝发布。
            check_graph({s.id:(s.parent_id,) if s.parent_id else () for s in sections})
            check_graph({b.id:b.dependency_ids for b in blocks})
            original_refs = {None:inputs.main} | {r.resource_key:r.object_ref for r in inputs.resources if isinstance(r,PresentResource)}
            for block in blocks:
                if block.section_id is not None and block.section_id not in section_ids:
                    raise CatalogError("PUBLICATION_INVALID", "block references unknown section")
                source = original_refs.get(block.locator.resource_key)
                if source is None or block.locator.end > source.byte_length:
                    raise CatalogError("PUBLICATION_INVALID", "block locator is outside a present input object")
            schema = validated_json(BuildSchema,payloads["asset-schema.json"])
            quality = validated_json(Quality,payloads["quality.json"])
            if schema.asset_ref != manifest.asset_ref or schema.content_readiness != schema.published_readiness:
                raise CatalogError("PUBLICATION_INVALID", "schema identity/readiness mismatch")
            # 能力状态需与原件缺口、实际内容和覆盖声明相容；数据结构合法不代表业务事实已独立验真。
            readiness = schema.content_readiness
            gap = any(isinstance(r,MissingResource) for r in inputs.resources)
            if readiness.original != ("partial" if gap else "ready"):
                raise CatalogError("PUBLICATION_INVALID", "original readiness contradicts inputs")
            for name,items in (("text",blocks),("outline",sections)):
                state = getattr(readiness,name)
                if (not items and state != "not_ready") or (items and state == "not_ready"):
                    raise CatalogError("PUBLICATION_INVALID", "content readiness contradicts actual content")
                if state == "ready" and quality.coverage != "complete":
                    raise CatalogError("PUBLICATION_INVALID", "ready claim has no declared complete coverage")
            if (gap or quality.coverage != "complete" or not blocks) and not schema.gaps:
                raise CatalogError("PUBLICATION_INVALID", "partial/unprocessed content requires explicit gaps")
            if build["readiness_json"] is not None and build["readiness_json"] != schema.published_readiness.canonical_bytes().decode():
                raise CatalogError("PUBLICATION_INVALID", "database readiness differs from frozen schema")
            return manifest
        except (ValidationError,ValueError,KeyError) as error:
            if isinstance(error,(CatalogError,ContentStoreError)):
                raise
            raise CatalogError("PUBLICATION_INVALID", "invalid content schema or reference") from error

    # 把已封存的 staging 构建发布为不可变版本；发现已移动未提交目录时要求显式恢复。
    @operation
    def publish(self, build_id):
        build = self.catalog.get_build(build_id)
        if build["status"] == "published":
            self.verify_build(build,final=True)
            return self.catalog.asset_ref(build)
        if build["status"] != "staging":
            raise CatalogError("INVALID_STATE", "failed build requires explicit new attempt")
        destination = self.build_path(build,final=True)
        # 目录已在最终位置意味着可能停在移动与事务确认之间，只能走恢复核验，不重新发布。
        if destination.exists():
            raise CatalogError("RECOVERY_REQUIRED", "build already moved; explicitly recover")
        try:
            if build["manifest_ref"] is None:
                raise CatalogError("PUBLICATION_INVALID", "build has no sealed candidate")
            self.verify_build(build,final=False)
            ensure_directory(self.root,f"assets/{build['asset_id']}/builds")
            self.move(self.build_path(build,final=False),destination)
            self.commit_build(build_id)
        except (CatalogError,ContentStoreError,OSError,ValidationError) as error:
            if not self.catalog.database.head_uncertain and not destination.exists():
                self.catalog.fail_build(build_id,failure_code=getattr(error,"code","STORAGE_IO_ERROR"))
            raise
        return self.catalog.asset_ref(self.catalog.get_build(build_id))

    # 重新验证最终产物并同步目录后，仅将 staging 构建确认为 published。
    def commit_build(self, build_id):
        build = self.catalog.get_build(build_id)
        self.verify_build(build,final=True)
        if build["status"] == "published":
            return
        if build["status"] != "staging":
            raise CatalogError("INVALID_STATE", "cannot publish a failed build")
        self._sync_moved(self.build_path(build,final=True))
        self.check('before_build_commit')
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_builds SET status='published',published_at=?,updated_at=? WHERE build_id=?",
                                     (utc_now(),utc_now(),build_id))
        self.check('after_build_commit')

    # 补做重命名后的目录同步；目录可见不等于持久化已确认，恢复时需要再次执行。
    def _sync_moved(self, directory):
        # Recovery repeats syncs which may have failed after rename. A visible
        # complete directory alone does not acknowledge persistence.
        _fsync_directory(directory)
        _fsync_directory(directory.parent)
        _fsync_directory(self.root/"staging")
