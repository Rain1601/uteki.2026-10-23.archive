"""Synthetic catalog setup, executable example and subprocess fault injection."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.content.publication import Publication
from uteki.data_platform.contracts.assets import (
    Acquisition, AssetInput, ArtifactFile, Block, BuildManifest, BuildRecipe,
    BuildSchema, ByteLocator, CompanyInput, ContentReadiness, Evidence, Quality,
    Section, SnapshotRelation, SourceInput,
)
from uteki.data_platform.contracts.common import SourceTime, canonical, digest
from uteki.data_platform.contracts.content import InputManifest, MissingResource, ObjectRef, PresentResource


def evidence(label="synthetic evidence", *, confirmed=True):
    return Evidence(description=label,object_ref=None,locator=None,method="manual",
                    method_ref="synthetic-fixture-v1",content_check="confirmed" if confirmed else "unverified")


def company(label, *, confirmed=True):
    return CompanyInput(canonical_name="Synthetic "+label,status="confirmed" if confirmed else "pending_identity",
        identity_basis_kind="manual_verified" if confirmed else None,
        identity_basis_value="fixture:"+label if confirmed else None,evidence=evidence(confirmed=confirmed))


def setup(catalog, label="alpha", *, main=b"synthetic original", figure=b"figure one", missing=False):
    run = catalog.start_run("run:"+label,purpose="synthetic storage acceptance",kind="build")["run_id"]
    catalog.register_policy("synthetic-policy-v1",definition="synthetic local fixtures only; no network",run_id=run)
    catalog.register_material_type("synthetic-document",asset_kind="document",description="synthetic fixture document",run_id=run)
    co = catalog.register_company("company:"+label,company(label),run_id=run)
    source = catalog.register_source("source:"+label,SourceInput(source_kind="user_file",publisher_name="Synthetic "+label,
        publisher_company_id=co,platform_name=None,canonical_url=None,policy_ref="synthetic-policy-v1"),run_id=run)
    asset = catalog.register_asset("asset:"+label,AssetInput(asset_kind="document",material_type="synthetic-document",
        title="Synthetic material "+label,language=None,natural_key="synthetic-material:"+label,reporting_period=None,
        declared_scope=None,evidence=evidence()),run_id=run)
    result = dict(run_id=run,company_id=co,source_id=source,asset_id=asset)
    return result | snapshot(catalog,result,label,main=main,figure=figure,missing=missing)


def snapshot(catalog, context, label, *, main=b"synthetic original", figure=b"figure one", missing=False, previous=None, freeze=True):
    absent = SourceTime(value=None,basis=None,unknown_reason="not_processed")
    acquisition = Acquisition(source_id=context["source_id"],request_url=None,final_url=None,
        acquired_at="2026-01-01T00:00:00+00:00",published_at=absent,available_at=absent,source_revised_at=absent)
    main_ref = catalog.content.put_object(main)
    figure_ref = catalog.content.put_object(figure)
    resources = (PresentResource(status="present",resource_key="figure",source_url=None,object_ref=figure_ref),)
    if missing:
        resources += (MissingResource(status="missing",resource_key="appendix",source_url=None,reason="not supplied"),)
    input_ref = catalog.content.put_manifest(InputManifest(schema_version="uteki-input-manifest-v1",main=main_ref,
        main_source_url=None,resources=resources))
    sn = catalog.begin_snapshot("snapshot:"+label,asset_id=context["asset_id"],acquisition=acquisition,
        completeness="partial" if missing else "complete",version_consistency="consistent",
        revision_of_snapshot_id=previous,revision_basis="synthetic version update" if previous else None,run_id=context["run_id"])
    rp = catalog.add_representation("representation:"+label,snapshot_id=sn,format="html",input_manifest=input_ref)
    catalog.relate_snapshot(sn,SnapshotRelation(company_id=context["company_id"],role="issuer",basis="source_metadata",
        status="confirmed",evidence=evidence()))
    if freeze:
        catalog.freeze_snapshot(sn)
    return dict(snapshot_id=sn,representation_id=rp,input_ref=input_ref.model_dump())


def begin(catalog, context, *, variant="one", retry_of=None):
    config = catalog.content.put_object(canonical(dict(capabilities=["original","text","outline"],targets=["document"],
        rules={"variant":variant},models=[])))
    recipe = BuildRecipe(processor_version="synthetic-fixture-v1",config=config,profile_ref="fixture-v1",taxonomy_ref="fixture-v1")
    return catalog.begin_build(snapshot_id=context["snapshot_id"],representation_id=context["representation_id"],
        recipe=recipe,run_id=context["run_id"],retry_of_build_id=retry_of)


def bundle(catalog, build):
    reference = catalog.asset_ref(build)
    inputs = catalog.content.read_manifest(ObjectRef.model_validate_json(build["input_ref"]))
    has_gap = any(isinstance(r,MissingResource) for r in inputs.resources)
    section = Section(id="section-one",title="Synthetic section",parent_id=None)
    block = Block(id="block-one",section_id=section.id,text="synthetic original",
        locator=ByteLocator(kind="input_bytes",resource_key=None,start=0,end=inputs.main.byte_length),dependency_ids=())
    state = "partial" if has_gap else "ready"
    readiness = ContentReadiness(original=state,text=state,outline=state,tables="not_ready",images="not_ready",records="not_ready",search="not_ready")
    schema = BuildSchema(schema_version="uteki-asset-schema-storage-v1",asset_ref=reference,
        content_readiness=readiness,published_readiness=readiness,gaps=("appendix not supplied",) if has_gap else (),description=None)
    files = {"sections.jsonl":section.canonical_bytes()+b"\n","blocks.jsonl":block.canonical_bytes()+b"\n",
             "quality.json":Quality(issues=(),coverage="partial" if has_gap else "complete").canonical_bytes(),
             "asset-schema.json":schema.canonical_bytes()}
    return files, manifest_for(build,reference,files)


def manifest_for(build, reference, files):
    return BuildManifest(schema_version="uteki-build-v1",asset_ref=reference,
        input_manifest=ObjectRef.model_validate_json(build["input_ref"]),recipe=BuildRecipe.model_validate_json(build["recipe"]),
        files=tuple(ArtifactFile(path=name,object_ref=ObjectRef(sha256=digest(raw),byte_length=len(raw))) for name,raw in files.items()))


def publish(catalog, build):
    files,manifest = bundle(catalog,build)
    Publication(catalog).stage(build["build_id"],files=files,manifest=manifest)
    return Publication(catalog).publish(build["build_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["example","open","hold","recover","snapshot_before_move","snapshot_after_move",
        "build_before_move","build_after_move","build_after_commit"])
    parser.add_argument("root",type=Path)
    parser.add_argument("--identity")
    parser.add_argument("--ready",type=Path)
    args = parser.parse_args()
    if args.mode == "example":
        with Catalog.initialize(args.root) as catalog:
            first = setup(catalog)
            old = publish(catalog,begin(catalog,first))
            second = first | snapshot(catalog,first,"alpha-revision",figure=b"figure two",previous=first["snapshot_id"])
            new = publish(catalog,begin(catalog,second))
            catalog.finish_run(first["run_id"],status="completed")
        with Catalog.open(args.root) as reopened:
            assert old != new
            assert reopened.read_artifact(old,"blocks.jsonl")
            assert reopened.read_artifact(new,"blocks.jsonl")
            print(json.dumps(dict(old=old.model_dump(),new=new.model_dump(),old_snapshot=reopened.read_snapshot(old.snapshot_id),
                                 new_snapshot=reopened.read_snapshot(new.snapshot_id),reopened=True,business_verified=False)))
        return
    with Catalog.open(args.root,recover=args.mode=="recover") as catalog:
        if args.mode=="open":
            print(catalog.view().model_dump_json())
        elif args.mode=="recover":
            print(json.dumps(catalog.recover()))
        elif args.mode=="hold":
            args.ready.write_text("locked")
            deadline=time.monotonic()+15
            while args.ready.exists() and time.monotonic()<deadline:
                time.sleep(0.02)
        elif args.mode=="build_after_commit":
            from uteki.data_platform.catalog import database
            real_write = database.write_control
            def interrupted(path,raw,**kwargs):
                if path.name=="catalog-head.json" and catalog.get_build(args.identity)["status"]=="published":
                    os._exit(73)
                return real_write(path,raw,**kwargs)
            with patch.object(database,"write_control",side_effect=interrupted):
                Publication(catalog).publish(args.identity)
        else:
            real_rename = os.rename
            def interrupted(source,target):
                if args.mode.endswith("after_move"):
                    real_rename(source,target)
                os._exit(73)
            with patch("uteki.data_platform.content.publication.os.rename",side_effect=interrupted):
                if args.mode.startswith("snapshot"):
                    catalog.freeze_snapshot(args.identity)
                else:
                    Publication(catalog).publish(args.identity)


if __name__=="__main__":
    main()
