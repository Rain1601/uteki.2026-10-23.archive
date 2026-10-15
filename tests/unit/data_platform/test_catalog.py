"""Behavioral tests for the fixed catalog/visibility/recovery contract."""
from contextlib import closing
from datetime import date
import errno
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from uteki.data_platform.catalog import Catalog, CatalogError
from uteki.data_platform.catalog import database
from uteki.data_platform.content import ContentStoreError
from uteki.data_platform.content.publication import Publication
from uteki.data_platform.contracts.assets import AssetInput, SecurityInput, SnapshotRelation
from uteki.data_platform.contracts.common import SourceTime, TemporalValue, canonical, new_id
from uteki.data_platform.contracts.content import ObjectRef

FIXTURE = runpy.run_path(str(Path(__file__).resolve().parents[2]/"fixtures/data_platform/catalog_worker.py"))
setup, snapshot, begin, bundle, publish, evidence, company, manifest_for = (
    FIXTURE[name] for name in ("setup","snapshot","begin","bundle","publish","evidence","company","manifest_for"))


class CommonContractTests(unittest.TestCase):
    def test_ulid_layout_and_temporal_precision(self):
        identity = new_id("co")
        self.assertRegex(identity,r"^co_[0-7][0-9A-HJKMNP-TV-Z]{25}$")
        known = TemporalValue(value="2026-02-04",precision="date")
        self.assertEqual(known.bounds(),("2026-02-03T10:00:00+00:00","2026-02-05T12:00:00+00:00"))
        self.assertEqual(TemporalValue(value="2024-02",precision="month").bounds()[1],"2024-03-01T12:00:00+00:00")
        with self.assertRaises(ValidationError):
            TemporalValue(value="2026-02-04T00:00:00",precision="datetime")
        with self.assertRaises(ValidationError):
            SourceTime(value=None,basis=None,unknown_reason=None)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uteki-catalog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.catalog = Catalog.initialize(self.root)
        self.addCleanup(lambda: self.catalog.close())

    def code(self, expected, function, *args, **kwargs):
        with self.assertRaises((CatalogError,)) as raised:
            function(*args,**kwargs)
        self.assertEqual(raised.exception.code,expected)
        return raised.exception

    def test_explicit_initialization_and_open_do_not_create_fallback(self):
        self.code("CATALOG_BUSY",Catalog.open,self.root)
        self.catalog.close()
        self.code("INVALID_STATE",Catalog.initialize,self.root)
        with tempfile.TemporaryDirectory() as empty:
            self.code("NOT_FOUND",Catalog.open,Path(empty).resolve())
            self.assertFalse((Path(empty)/"catalog.sqlite").exists())
        with Catalog.open(self.root) as reopened:
            self.assertEqual(reopened.view().revision,0)

    def test_migration_failure_is_not_initialized_and_retry_is_explicit(self):
        with tempfile.TemporaryDirectory() as empty:
            root = Path(empty).resolve()
            original = database.migration_sources()
            broken = [(original[0][0],original[0][1]+b"\nTHIS IS INVALID SQL;\n")]
            with patch.object(database,"migration_sources",return_value=broken):
                self.code("CATALOG_INCONSISTENT",Catalog.initialize,root)
            self.assertFalse((root/"catalog.sqlite").exists())
            self.code("NOT_FOUND",Catalog.open,root)
            with Catalog.initialize(root) as valid:
                self.assertEqual(valid.view().revision,0)
            self.assertTrue(list(root.glob(".catalog-initializing-*")))

    def test_changed_migration_history_is_rejected(self):
        self.catalog._db.execute("UPDATE schema_migrations SET sha256=?",("0"*64,))
        self.catalog.close()
        self.code("MIGRATION_MISMATCH",Catalog.open,self.root)

    def test_schema_foreign_key_status_and_build_uniqueness_are_real(self):
        context = setup(self.catalog)
        build = begin(self.catalog,context)
        self.assertEqual(self.catalog._db.execute("PRAGMA foreign_keys").fetchone()[0],1)
        with self.assertRaises(sqlite3.IntegrityError), self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE sources SET policy_ref='missing'")
        with self.assertRaises(sqlite3.IntegrityError), self.catalog.database.transaction():
            self.catalog._db.execute("UPDATE asset_builds SET status='invented'")
        with self.assertRaises(sqlite3.IntegrityError), self.catalog.database.transaction():
            row = {k:v for k,v in build.items() if k not in {"created_at","updated_at"}}
            row.update(build_id=new_id("bd"),job_id=new_id("job"))
            self.catalog._insert("asset_builds",row)
        self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"staging")

    def test_idempotency_pending_identity_and_name_ambiguity(self):
        context = setup(self.catalog)
        run = context["run_id"]
        revision = self.catalog.view()
        self.assertEqual(self.catalog.register_company("company:alpha",company("alpha"),run_id=run),context["company_id"])
        self.assertEqual(self.catalog.view(),revision)
        self.code("IDEMPOTENCY_CONFLICT",self.catalog.register_company,"company:alpha",company("changed"),run_id=run)
        pending = self.catalog.register_company("pending",company("pending",confirmed=False),run_id=run)
        self.code("NOT_FOUND",self.catalog.resolve_company,"Synthetic pending",as_of=date(2026,1,1))
        for identity in (context["company_id"],pending):
            self.catalog.register_alias("alias:"+identity,company_id=identity,alias="Shared label",alias_kind="short_name",
                valid_from=None,valid_to=None,evidence=evidence(),run_id=run)
        self.code("AMBIGUOUS_ENTITY",self.catalog.resolve_company,"Shared label",as_of=date(2026,1,1))

    def test_unregistered_material_and_identity_conflicts_do_not_merge(self):
        context = setup(self.catalog)
        registered = AssetInput.model_validate_json(self.catalog._get("assets","asset_id",context["asset_id"])["payload"])
        self.code("NOT_FOUND",self.catalog.register_asset,"unknown-kind",registered.model_copy(update={"material_type":"unregistered"}),run_id=context["run_id"])
        self.code("IDENTITY_CONFLICT",self.catalog.register_asset,"different",registered.model_copy(update={"title":"different material"}),run_id=context["run_id"])
        second = setup(self.catalog,"beta")
        self.assertNotEqual(context["asset_id"],second["asset_id"])
        self.assertEqual(context["input_ref"],second["input_ref"])
        first_build,second_build = begin(self.catalog,context),begin(self.catalog,second)
        self.assertNotEqual(first_build["build_key"],second_build["build_key"])
        references = [publish(self.catalog,build) for build in (first_build,second_build)]
        self.assertEqual(len(self.catalog.list_published()["items"]),2)
        for reference in references:
            frozen = self.catalog.read_snapshot(reference.snapshot_id)
            self.assertEqual(frozen["asset_id"],reference.asset_id)
            self.catalog.read_published(reference)

    def test_security_intervals_do_not_overlap_or_guess_dates(self):
        context = setup(self.catalog)
        first = SecurityInput(company_id=context["company_id"],ticker="SYN",exchange_mic="XNAS",security_type="common",
            valid_from=date(2020,1,1),valid_to=date(2020,12,31),status="confirmed",evidence=evidence())
        identity = self.catalog.register_security("security:1",first,run_id=context["run_id"])
        self.code("IDENTITY_CONFLICT",self.catalog.register_security,"security:overlap",first.model_copy(update={"valid_from":None}),run_id=context["run_id"])
        self.assertEqual(self.catalog.resolve_security("SYN","XNAS",as_of=date(2020,6,1))["security_id"],identity)
        self.code("NOT_FOUND",self.catalog.resolve_security,"SYN","XNAS",as_of=date(2021,1,1))

    def test_unknown_security_dates_cannot_prove_historical_applicability(self):
        context=setup(self.catalog)
        unknown=SecurityInput(company_id=context["company_id"],ticker="UNK",exchange_mic="XNAS",security_type="common",
            valid_from=None,valid_to=None,status="confirmed",evidence=evidence())
        self.catalog.register_security("unknown-dates",unknown,run_id=context["run_id"])
        self.code("UNRESOLVED_TIME",self.catalog.resolve_security,"UNK","XNAS",as_of=date(2026,1,1))
        self.catalog.register_alias("unknown-alias",company_id=context["company_id"],alias="Undated alias",alias_kind="short_name",
            valid_from=None,valid_to=None,evidence=evidence(),run_id=context["run_id"])
        self.assertEqual(len(self.catalog.find_companies("Undated alias",as_of=date(2026,1,1))),1)
        self.code("UNRESOLVED_TIME",self.catalog.resolve_company,"Undated alias",as_of=date(2026,1,1))
        self.catalog.register_alias("candidate-alias",company_id=context["company_id"],alias="Candidate alias",alias_kind="short_name",
            valid_from=date(2020,1,1),valid_to=date(2030,1,1),evidence=evidence(confirmed=False),run_id=context["run_id"])
        self.code("INVALID_STATE",self.catalog.resolve_company,"Candidate alias",as_of=date(2026,1,1))

    def test_recovery_must_retry_failed_destination_directory_sync(self):
        context=setup(self.catalog)
        build=begin(self.catalog,context)
        files,manifest=bundle(self.catalog,build)
        publication=Publication(self.catalog)
        publication.stage(build["build_id"],files=files,manifest=manifest)
        final=publication.build_path(build,final=True)
        real_fsync=os.fsync
        def fail_destination(fd):
            if final.exists() and os.fstat(fd).st_ino==final.parent.stat().st_ino:
                raise OSError(errno.EIO,"synthetic destination directory cannot sync")
            return real_fsync(fd)
        with patch("uteki.data_platform.content.publication.os.fsync",side_effect=fail_destination):
            self.code("STORAGE_IO_ERROR",publication.publish,build["build_id"])
            self.code("STORAGE_IO_ERROR",self.catalog.recover)
        self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"staging")
        self.catalog.recover()
        self.catalog.read_published(self.catalog.asset_ref(build))

    def test_unknown_source_time_is_not_acquisition_time(self):
        context = setup(self.catalog)
        source = self.catalog._db.execute("SELECT * FROM source_records WHERE snapshot_id=?",(context["snapshot_id"],)).fetchone()
        self.assertIsNone(source["available_at_value"])
        self.assertIsNone(source["published_at_upper_utc"])
        self.assertIsNotNone(source["acquired_at"])
        frozen = self.catalog.read_snapshot(context["snapshot_id"])
        self.assertEqual(frozen["metadata"]["acquisition"]["available_at"]["unknown_reason"],"not_processed")

    def test_metadata_candidates_history_and_exact_supersession(self):
        context = setup(self.catalog)
        identity = context["company_id"]
        original = self.catalog.revisions("company",identity)[0]
        common = dict(object_type="company",object_id=identity,field="canonical_name",value="Revised name",reason="synthetic correction",
                      evidence=evidence(),run_id=context["run_id"])
        self.catalog.record_revision(**common,status="candidate",supersedes_revision_id=None)
        self.assertEqual(self.catalog.get_company(identity)["canonical_name"],"Synthetic alpha")
        self.code("IDENTITY_CONFLICT",self.catalog.record_revision,**common,status="current",supersedes_revision_id=None)
        self.catalog.record_revision(**common,status="current",supersedes_revision_id=original["revision_id"])
        self.assertEqual(self.catalog.get_company(identity)["canonical_name"],"Revised name")
        self.assertEqual({r["status"] for r in self.catalog.revisions("company",identity)},{"superseded","candidate","current"})
        frozen = self.catalog.read_snapshot(context["snapshot_id"])
        self.assertIn("Synthetic alpha",frozen["metadata"]["source_metadata"]["payload"])

    def test_snapshot_relations_do_not_flow_back_into_old_versions(self):
        context = setup(self.catalog)
        beta = self.catalog.register_company("company:beta",company("beta"),run_id=context["run_id"])
        second = snapshot(self.catalog,context,"second",previous=context["snapshot_id"],freeze=False)
        self.catalog.relate_snapshot(second["snapshot_id"],SnapshotRelation(company_id=beta,role="mentioned",basis="source_metadata",
            status="confirmed",evidence=evidence()))
        self.catalog.freeze_snapshot(second["snapshot_id"])
        self.assertNotIn(beta,{r["company_id"] for r in self.catalog.read_snapshot(context["snapshot_id"])["relations"]})
        self.assertIn(beta,{r["company_id"] for r in self.catalog.read_snapshot(second["snapshot_id"])["relations"]})
        self.code("INVALID_STATE",self.catalog.add_representation,"late",snapshot_id=context["snapshot_id"],format="html",input_manifest=ObjectRef.model_validate(context["input_ref"]))

    def test_complete_claim_with_missing_resource_cannot_freeze(self):
        context = setup(self.catalog)
        second = snapshot(self.catalog,context,"gap",missing=True,freeze=False)
        row = self.catalog.get_snapshot(second["snapshot_id"])
        payload = json.loads(row["payload"]); payload["completeness"]="complete"
        # Simulate invalid persisted state at the boundary; the freeze must recheck.
        self.catalog._db.execute("UPDATE asset_snapshots SET payload=? WHERE snapshot_id=?",(canonical(payload).decode(),second["snapshot_id"]))
        self.code("PUBLICATION_INVALID",self.catalog.freeze_snapshot,second["snapshot_id"])
        self.assertEqual(self.catalog.get_snapshot(second["snapshot_id"])["status"],"failed")
        self.catalog.read_snapshot(context["snapshot_id"])

    def test_build_staging_published_and_failed_reuse_rules(self):
        context = setup(self.catalog)
        first = begin(self.catalog,context)
        self.assertEqual(begin(self.catalog,context)["build_id"],first["build_id"])
        self.code("INVALID_STATE",self.catalog.read_published,self.catalog.asset_ref(first))
        self.catalog.fail_build(first["build_id"],failure_code="SYNTHETIC_FAILURE")
        self.code("INVALID_STATE",begin,self.catalog,context)
        retry = begin(self.catalog,context,retry_of=first["build_id"])
        self.assertNotEqual(retry["build_id"],first["build_id"])
        self.assertEqual(retry["retry_of_build_id"],first["build_id"])
        reference = publish(self.catalog,retry)
        self.assertEqual(begin(self.catalog,context)["build_id"],reference.build_id)
        self.assertEqual(self.catalog.get_build(first["build_id"])["status"],"failed")

    def test_retry_run_inherits_root_and_cannot_end_while_collecting(self):
        context=setup(self.catalog)
        build=begin(self.catalog,context)
        self.catalog.fail_build(build["build_id"],failure_code="SYNTHETIC_FAILURE")
        self.catalog.finish_run(context["run_id"],status="failed",failure_code="SYNTHETIC_FAILURE")
        wrong=self.catalog.start_run("unrelated",purpose="synthetic retry",kind="build")
        self.code("IDENTITY_CONFLICT",begin,self.catalog,context|{"run_id":wrong["run_id"]},retry_of=build["build_id"])
        child=self.catalog.start_run("continuation",purpose="synthetic retry",kind="build",parent_run_id=context["run_id"])
        self.assertEqual(child["root_run_id"],context["run_id"])
        retry=begin(self.catalog,context|{"run_id":child["run_id"]},retry_of=build["build_id"])
        publish(self.catalog,retry)
        snapshot(self.catalog,context|{"run_id":child["run_id"]},"collecting",freeze=False)
        self.code("INVALID_STATE",self.catalog.finish_run,child["run_id"],status="completed")

    def test_directory_visibility_latest_build_and_explicit_old_reference(self):
        context=setup(self.catalog)
        build=begin(self.catalog,context)
        self.assertEqual(self.catalog.list_published()["items"],[])
        first=publish(self.catalog,build)
        second=publish(self.catalog,begin(self.catalog,context,variant="second processor config"))
        result=self.catalog.list_published()
        self.assertEqual(result["items"],[dict(asset_ref=second.model_dump(),other_builds=1)])
        self.catalog.read_published(first)
        self.catalog.record_revision(object_type="asset",object_id=context["asset_id"],field="status",value="retired",
            status="current",reason="synthetic retirement",evidence=evidence(),supersedes_revision_id=None,run_id=context["run_id"])
        self.assertEqual(self.catalog.list_published()["items"],[])
        self.catalog.read_published(first)

    def test_amendment_is_a_distinct_asset_with_explicit_relation(self):
        original=setup(self.catalog)
        amendment=setup(self.catalog,"amendment")
        self.catalog.relate_assets(amendment["asset_id"],original["asset_id"],kind="amends",evidence=evidence(),run_id=amendment["run_id"])
        relation=self.catalog.get_asset(amendment["asset_id"])["relations"][0]
        self.assertEqual(relation["to_asset_id"],original["asset_id"])
        self.assertNotEqual(amendment["asset_id"],original["asset_id"])

    def test_old_reference_and_artifacts_survive_new_attachment_version(self):
        context = setup(self.catalog)
        old = publish(self.catalog,begin(self.catalog,context))
        old_bytes = self.catalog.read_artifact(old,"blocks.jsonl")
        second = context | snapshot(self.catalog,context,"changed-figure",figure=b"figure changed",previous=context["snapshot_id"])
        new = publish(self.catalog,begin(self.catalog,second))
        self.assertNotEqual(context["input_ref"],second["input_ref"])
        self.assertNotEqual(old,new)
        self.catalog.close(); self.catalog=Catalog.open(self.root)
        self.assertEqual(self.catalog.read_artifact(old,"blocks.jsonl"),old_bytes)
        self.catalog.read_published(new)
        for reference,expected in ((old,b"figure one"),(new,b"figure changed")):
            manifest = self.catalog.read_published(reference)
            inputs = self.catalog.content.read_manifest(manifest.input_manifest)
            self.assertEqual(self.catalog.content.read_object(inputs.resources[0].object_ref),expected)
        self.code("IDENTITY_CONFLICT",self.catalog.read_published,old.model_copy(update={"snapshot_id":new.snapshot_id}))

    def test_view_expires_but_explicit_old_reference_remains_readable(self):
        context = setup(self.catalog)
        reference = publish(self.catalog,begin(self.catalog,context))
        old = self.catalog.view()
        self.catalog.register_company("new-company",company("beta"),run_id=context["run_id"])
        self.code("CURSOR_EXPIRED",self.catalog.read_published,reference,view=old)
        self.catalog.read_published(reference)

    def test_missing_or_corrupt_staged_file_cannot_publish(self):
        context = setup(self.catalog)
        for kind in ("missing","corrupt"):
            with self.subTest(kind=kind):
                build = begin(self.catalog,context,variant=kind)
                files,manifest = bundle(self.catalog,build)
                Publication(self.catalog).stage(build["build_id"],files=files,manifest=manifest)
                path = self.root/"staging"/build["job_id"]/"blocks.jsonl"
                if kind=="missing": path.unlink()
                else: path.write_bytes(b"corrupt")
                with self.assertRaises(CatalogError): Publication(self.catalog).publish(build["build_id"])
                self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"failed")
                self.code("INVALID_STATE",self.catalog.read_published,self.catalog.asset_ref(build))

    def test_actual_content_references_and_readiness_are_validated(self):
        context = setup(self.catalog)
        changes = [
            ("blocks.jsonl",lambda x:x.update(section_id="absent")),
            ("blocks.jsonl",lambda x:x.update(dependency_ids=["absent"])),
            ("blocks.jsonl",lambda x:x.update(dependency_ids=[x["id"]])),
            ("blocks.jsonl",lambda x:x["locator"].update(end=99999)),
            ("blocks.jsonl",lambda x:x["locator"].update(resource_key="missing")),
            ("sections.jsonl",lambda x:x.update(parent_id=x["id"])),
            ("asset-schema.json",lambda x:x["published_readiness"].update(text="not_ready")),
        ]
        for number,(name,change) in enumerate(changes):
            with self.subTest(number=number):
                build=begin(self.catalog,context,variant=str(number))
                files,_=bundle(self.catalog,build)
                value=json.loads(files[name]); change(value)
                files[name]=canonical(value)+(b"\n" if name.endswith(".jsonl") else b"")
                manifest=manifest_for(build,self.catalog.asset_ref(build),files)
                self.code("PUBLICATION_INVALID",Publication(self.catalog).stage,build["build_id"],files=files,manifest=manifest)
                self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"failed")

    def test_ambiguous_json_keys_cannot_enter_published_content(self):
        context=setup(self.catalog)
        build=begin(self.catalog,context)
        files,_=bundle(self.catalog,build)
        files["sections.jsonl"]=files["sections.jsonl"].replace(b'"parent_id":null',b'"parent_id":"missing","parent_id":null')
        manifest=manifest_for(build,self.catalog.asset_ref(build),files)
        self.code("PUBLICATION_INVALID",Publication(self.catalog).stage,build["build_id"],files=files,manifest=manifest)

    def test_published_corruption_and_database_only_restore_are_rejected(self):
        context=setup(self.catalog)
        reference=publish(self.catalog,begin(self.catalog,context))
        backup=self.root/"older.sqlite"
        with closing(sqlite3.connect(backup)) as target: self.catalog._db.backup(target)
        self.catalog.register_company("later",company("later"),run_id=context["run_id"])
        self.catalog.close()
        current=(self.root/"catalog.sqlite").read_bytes()
        shutil.copyfile(backup,self.root/"catalog.sqlite")
        self.code("CATALOG_INCONSISTENT",Catalog.open,self.root)
        (self.root/"catalog.sqlite").write_bytes(current)
        path=self.root/"assets"/reference.asset_id/"builds"/reference.build_id/"blocks.jsonl"
        path.chmod(0o600); path.write_bytes(b"corrupt")
        self.code("CATALOG_INCONSISTENT",Catalog.open,self.root,recover=True)
        self.assertEqual(path.read_bytes(),b"corrupt")

    def test_commit_head_failure_requires_explicit_recovery(self):
        real=database.write_control
        def fail_head(path,raw,**kwargs):
            if path.name=="catalog-head.json": raise OSError(errno.EIO,"synthetic head sync failure")
            return real(path,raw,**kwargs)
        with patch.object(database,"write_control",side_effect=fail_head):
            self.code("RECOVERY_REQUIRED",self.catalog.start_run,"uncertain",purpose="synthetic",kind="build")
        self.code("RECOVERY_REQUIRED",self.catalog.view)
        self.catalog.close()
        self.code("RECOVERY_REQUIRED",Catalog.open,self.root)
        self.catalog=Catalog.open(self.root,recover=True)
        self.assertEqual(self.catalog.start_run("uncertain",purpose="synthetic",kind="build")["status"],"running")

    def test_orphan_staging_is_retained_and_unknown_final_is_rejected(self):
        orphan=self.root/"staging"/"orphan"; orphan.mkdir(parents=True)
        (orphan/"partial").write_bytes(b"unfinished")
        report=self.catalog.recover()
        self.assertEqual(report,[dict(orphan_staging="orphan",status="retained")])
        self.assertEqual((orphan/"partial").read_bytes(),b"unfinished")
        (self.root/"assets"/new_id("as")/"builds"/new_id("bd")).mkdir(parents=True)
        self.catalog.close()
        self.code("CATALOG_INCONSISTENT",Catalog.open,self.root)

    def test_initialization_head_failure_can_only_recover_a_valid_commit_chain(self):
        self.catalog.close()
        for broken in (False,True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve()
                with patch.object(database,"write_control",side_effect=OSError(errno.EIO,"synthetic initial head failure")):
                    self.code("STORAGE_IO_ERROR",Catalog.initialize,root)
                self.assertTrue((root/"catalog.sqlite").exists())
                self.code("RECOVERY_REQUIRED",Catalog.open,root)
                if broken:
                    with closing(sqlite3.connect(root/"catalog.sqlite")) as db, db:
                        db.execute("DELETE FROM catalog_commits")
                    self.code("CATALOG_INCONSISTENT",Catalog.open,root,recover=True)
                else:
                    with Catalog.open(root,recover=True) as recovered:
                        self.assertEqual(recovered.view().revision,0)

    def test_sqlite_sidecar_links_are_rejected_before_opening_database(self):
        self.catalog.close()
        with tempfile.TemporaryDirectory() as directory:
            outside=Path(directory)/"outside"; outside.write_bytes(b"must not touch")
            (self.root/"catalog.sqlite-wal").symlink_to(outside)
            with patch.object(database.sqlite3,"connect",wraps=sqlite3.connect) as connect:
                self.code("CATALOG_INCONSISTENT",Catalog.open,self.root)
                connect.assert_not_called()
            self.assertEqual(outside.read_bytes(),b"must not touch")

    def test_complete_quiescent_copy_restores_same_frozen_references(self):
        context=setup(self.catalog)
        reference=publish(self.catalog,begin(self.catalog,context))
        raw=self.catalog.read_artifact(reference,"blocks.jsonl")
        self.catalog.close()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"restored"
            shutil.copytree(self.root,target)
            with Catalog.open(target) as restored:
                self.assertEqual(restored.read_artifact(reference.model_dump(),"blocks.jsonl"),raw)

    def test_moved_but_corrupt_candidate_fails_recovery_without_touching_old_build(self):
        context=setup(self.catalog)
        old=publish(self.catalog,begin(self.catalog,context))
        build=begin(self.catalog,context,variant="interrupted")
        files,manifest=bundle(self.catalog,build)
        publication=Publication(self.catalog)
        publication.stage(build["build_id"],files=files,manifest=manifest)
        with patch.object(publication,"commit_build",side_effect=OSError(errno.EIO,"synthetic crash before commit")):
            self.code("STORAGE_IO_ERROR",publication.publish,build["build_id"])
        path=publication.build_path(build,final=True)/"blocks.jsonl"
        path.chmod(0o600); path.write_bytes(b"damaged after move")
        self.catalog.recover()
        self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"failed")
        self.assertEqual(self.catalog._get("runs","run_id",context["run_id"])["status"],"failed")
        self.catalog.read_published(old)
        self.assertEqual(path.read_bytes(),b"damaged after move")

    def test_publication_transaction_rollback_keeps_moved_build_invisible(self):
        context=setup(self.catalog)
        old=publish(self.catalog,begin(self.catalog,context))
        build=begin(self.catalog,context,variant="transaction failure")
        files,manifest=bundle(self.catalog,build)
        publication=Publication(self.catalog)
        publication.stage(build["build_id"],files=files,manifest=manifest)
        before=self.catalog.view()
        self.catalog._db.execute("""CREATE TRIGGER reject_publication BEFORE UPDATE OF status ON asset_builds
            WHEN NEW.status='published' BEGIN SELECT RAISE(ABORT,'synthetic transaction failure'); END""")
        error=self.code("IDENTITY_CONFLICT",publication.publish,build["build_id"])
        self.assertIsInstance(error.__cause__,sqlite3.IntegrityError)
        self.assertEqual(self.catalog.view(),before)
        self.assertTrue(publication.build_path(build,final=True).is_dir())
        self.assertEqual(self.catalog.get_build(build["build_id"])["status"],"staging")
        self.code("INVALID_STATE",self.catalog.read_published,self.catalog.asset_ref(build))
        self.assertEqual(self.catalog.list_published()["items"],[dict(asset_ref=old.model_dump(),other_builds=0)])
        self.catalog._db.execute("DROP TRIGGER reject_publication")
        self.catalog.close()
        self.catalog=Catalog.open(self.root,recover=True)
        self.assertEqual(self.catalog.read_artifact(self.catalog.asset_ref(build),"blocks.jsonl"),files["blocks.jsonl"])
        self.catalog.read_published(old)

    def test_freeze_rechecks_registered_resource_bytes_and_preserves_old_snapshot(self):
        context=setup(self.catalog)
        old=publish(self.catalog,begin(self.catalog,context))
        for failure in ("missing","corrupt"):
            with self.subTest(failure=failure):
                pending=snapshot(self.catalog,context,failure,figure=failure.encode(),freeze=False)
                inputs=self.catalog.content.read_manifest(ObjectRef.model_validate(pending["input_ref"]))
                path=self.catalog.content._path(inputs.resources[0].object_ref)
                if failure=="missing":
                    path.unlink()
                else:
                    path.chmod(0o600); path.write_bytes(b"damaged")
                with self.assertRaises(ContentStoreError) as error:
                    self.catalog.freeze_snapshot(pending["snapshot_id"])
                expected="OBJECT_MISSING" if failure=="missing" else "OBJECT_CORRUPT"
                self.assertEqual(error.exception.code,expected)
                row=self.catalog.get_snapshot(pending["snapshot_id"])
                self.assertEqual((row["status"],row["failure_code"]),("failed",expected))
                self.code("INVALID_STATE",self.catalog.read_snapshot,pending["snapshot_id"])
                self.catalog.read_published(old)
        self.catalog.close()
        self.catalog=Catalog.open(self.root)
        self.catalog.read_published(old)


if __name__=="__main__":
    unittest.main()
