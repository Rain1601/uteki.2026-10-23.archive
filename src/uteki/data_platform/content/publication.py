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


def validated_json(model, raw):
    def unique_pairs(pairs):
        value = {}
        for key,item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError("non-finite JSON constant")
    json.loads(raw,object_pairs_hook=unique_pairs,parse_constant=invalid_constant)
    # Use JSON validation, preserving the contract's JSON array -> tuple rules.
    return model.model_validate_json(raw)


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


def move_complete(source: Path, destination: Path):
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
    os.rename(source, destination)
    _fsync_directory(source.parent)
    _fsync_directory(destination.parent)


def check_graph(edges: dict[str, tuple[str, ...]]):
    visiting, done = set(), set()
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


class Publication:
    def __init__(self, catalog):
        self.catalog = catalog
        self.root = catalog.root

    def snapshot_path(self, row, *, final):
        if final:
            return self.root / "assets" / row["asset_id"] / "snapshots" / row["snapshot_id"]
        return self.root / "staging" / ("snapshot-" + row["snapshot_id"])

    def build_path(self, row, *, final):
        if final:
            return self.root / "assets" / row["asset_id"] / "builds" / row["build_id"]
        return self.root / "staging" / row["job_id"]

    def _representations(self, snapshot_id):
        return [Representation(representation_id=row["representation_id"],format=row["format"],
                               input_manifest=ObjectRef.model_validate_json(row["input_ref"]))
                for row in self.catalog._db.execute("SELECT * FROM snapshot_representations WHERE snapshot_id=? ORDER BY representation_id", (snapshot_id,))]

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

    @operation
    def freeze_snapshot(self, snapshot_id):
        row = self.catalog.get_snapshot(snapshot_id)
        if row["status"] == "frozen":
            self.verify_snapshot(snapshot_id)
            return row
        if row["status"] != "collecting" or row["manifest_ref"] is not None:
            raise CatalogError("INVALID_STATE", "snapshot is terminal or requires explicit recovery")
        try:
            value = self._snapshot_value(row,utc_now())
            raw = canonical(value)
            reference = self.catalog.content.put_object(raw)
            with self.catalog.database.transaction():
                self.catalog._db.execute("UPDATE asset_snapshots SET manifest_ref=?,updated_at=? WHERE snapshot_id=?",
                                         (reference.model_dump_json(),utc_now(),snapshot_id))
            row = self.catalog.get_snapshot(snapshot_id)
            stage = ensure_directory(self.root,"staging/snapshot-"+snapshot_id)
            write_control(stage/"snapshot-manifest.json",raw)
            representations = ensure_directory(stage,"representations")
            for item in value["representations"]:
                write_control(representations/(item["representation_id"]+".json"),canonical(item))
            self.verify_snapshot(snapshot_id,final=False)
            target_parent = ensure_directory(self.root,f"assets/{row['asset_id']}/snapshots")
            move_complete(stage,target_parent/snapshot_id)
            self.commit_snapshot(snapshot_id)
        except (CatalogError, ContentStoreError, OSError, ValidationError) as error:
            if not self.catalog.database.head_uncertain:
                current = self.catalog.get_snapshot(snapshot_id)
                # A complete moved version can be recovered; do not discard the
                # uncertain publication outcome after a directory sync failure.
                if current["status"] == "collecting" and not self.snapshot_path(current,final=True).exists():
                    self.fail_snapshot(snapshot_id,getattr(error,"code","STORAGE_IO_ERROR"))
            raise
        return self.catalog.get_snapshot(snapshot_id)

    def commit_snapshot(self, snapshot_id):
        row = self.catalog.get_snapshot(snapshot_id)
        self.verify_snapshot(snapshot_id)
        if row["status"] == "frozen":
            return
        if row["status"] != "collecting":
            raise CatalogError("INVALID_STATE", "cannot commit failed snapshot")
        self._sync_moved(self.snapshot_path(row,final=True))
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_snapshots SET status='frozen',updated_at=? WHERE snapshot_id=?", (utc_now(),snapshot_id))
            self.catalog._db.execute("UPDATE assets SET status='has_snapshot',updated_at=? WHERE asset_id=? AND status='registered'", (utc_now(),row["asset_id"]))

    def fail_snapshot(self, snapshot_id, code):
        row = self.catalog.get_snapshot(snapshot_id)
        if row["status"] != "collecting":
            raise CatalogError("INVALID_STATE", "terminal snapshot cannot be failed")
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_snapshots SET status='failed',failure_code=?,updated_at=? WHERE snapshot_id=?", (code,utc_now(),snapshot_id))

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

    @operation
    def stage(self, build_id, *, files: dict[str, bytes], manifest: BuildManifest):
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
                raw = files[item.path]
                if not isinstance(raw,bytes) or len(raw) != item.object_ref.byte_length or digest(raw) != item.object_ref.sha256:
                    raise CatalogError("PUBLICATION_INVALID", "supplied artifact bytes differ from manifest")
                parent = ensure_directory(stage, str(Path(item.path).parent))
                write_control(parent/Path(item.path).name,raw)
            write_control(stage/"manifest.json",manifest.canonical_bytes())
            self.verify_build(build,final=False)
            reference = self.catalog.content.put_object(manifest.canonical_bytes())
            schema = BuildSchema.model_validate_json(files["asset-schema.json"])
            with self.catalog.database.transaction():
                self.catalog._db.execute("UPDATE asset_builds SET manifest_ref=?,readiness_json=?,updated_at=? WHERE build_id=?",
                    (reference.model_dump_json(),schema.published_readiness.canonical_bytes().decode(),utc_now(),build_id))
        except (CatalogError,ContentStoreError,OSError,ValidationError) as error:
            if not self.catalog.database.head_uncertain:
                self.catalog.fail_build(build_id,failure_code=getattr(error,"code","PUBLICATION_INVALID"))
            raise
        return self.catalog.get_build(build_id)

    def _binding(self, build, manifest):
        if (manifest.asset_ref != self.catalog.asset_ref(build)
                or manifest.input_manifest != ObjectRef.model_validate_json(build["input_ref"])
                or manifest.recipe != BuildRecipe.model_validate_json(build["recipe"])
                or manifest.recipe.build_key(manifest.asset_ref,manifest.input_manifest) != build["build_key"]):
            raise CatalogError("PUBLICATION_INVALID", "manifest identity, input or recipe differs from registered build")

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
            if {f.path for f in manifest.files} != REQUIRED_FILES or file_names(directory) != REQUIRED_FILES | {"manifest.json"}:
                raise CatalogError("PUBLICATION_INVALID", "unsupported, missing or extra build files")
            payloads = {}
            for item in manifest.files:
                content = read_regular(directory/item.path)
                if len(content) != item.object_ref.byte_length or digest(content) != item.object_ref.sha256:
                    raise CatalogError("PUBLICATION_INVALID", "artifact hash or size mismatch: "+item.path)
                payloads[item.path] = content
            self.catalog.read_snapshot(build["snapshot_id"])
            inputs = self.catalog.content.read_manifest(manifest.input_manifest)
            sections = [validated_json(Section,line) for line in payloads["sections.jsonl"].splitlines()]
            blocks = [validated_json(Block,line) for line in payloads["blocks.jsonl"].splitlines()]
            if len({s.id for s in sections}) != len(sections) or len({b.id for b in blocks}) != len(blocks):
                raise CatalogError("PUBLICATION_INVALID", "duplicate content item ID")
            section_ids = {s.id for s in sections}
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

    @operation
    def publish(self, build_id):
        build = self.catalog.get_build(build_id)
        if build["status"] == "published":
            self.verify_build(build,final=True)
            return self.catalog.asset_ref(build)
        if build["status"] != "staging":
            raise CatalogError("INVALID_STATE", "failed build requires explicit new attempt")
        destination = self.build_path(build,final=True)
        if destination.exists():
            raise CatalogError("RECOVERY_REQUIRED", "build already moved; explicitly recover")
        try:
            if build["manifest_ref"] is None:
                raise CatalogError("PUBLICATION_INVALID", "build has no sealed candidate")
            self.verify_build(build,final=False)
            ensure_directory(self.root,f"assets/{build['asset_id']}/builds")
            move_complete(self.build_path(build,final=False),destination)
            self.commit_build(build_id)
        except (CatalogError,ContentStoreError,OSError,ValidationError) as error:
            if not self.catalog.database.head_uncertain and not destination.exists():
                self.catalog.fail_build(build_id,failure_code=getattr(error,"code","STORAGE_IO_ERROR"))
            raise
        return self.catalog.asset_ref(self.catalog.get_build(build_id))

    def commit_build(self, build_id):
        build = self.catalog.get_build(build_id)
        self.verify_build(build,final=True)
        if build["status"] == "published":
            return
        if build["status"] != "staging":
            raise CatalogError("INVALID_STATE", "cannot publish a failed build")
        self._sync_moved(self.build_path(build,final=True))
        with self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_builds SET status='published',published_at=?,updated_at=? WHERE build_id=?",
                                     (utc_now(),utc_now(),build_id))

    def _sync_moved(self, directory):
        # Recovery repeats syncs which may have failed after rename. A visible
        # complete directory alone does not acknowledge persistence.
        _fsync_directory(directory)
        _fsync_directory(directory.parent)
        _fsync_directory(self.root/"staging")
