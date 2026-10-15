"""Explicit recovery under the same exclusive catalog lock; no automatic retry."""
from __future__ import annotations

import os
import stat

from pydantic import ValidationError

from ..contracts.common import CatalogError
from .store import ContentStoreError
from .publication import Publication


def audit_catalog(catalog):
    """Reject published corruption and final files from a different DB history."""
    catalog.database.assert_open()
    publication = Publication(catalog)
    snapshots = {row["snapshot_id"]:dict(row) for row in catalog._db.execute("SELECT * FROM asset_snapshots")}
    builds = {row["build_id"]:dict(row) for row in catalog._db.execute("SELECT * FROM asset_builds")}
    try:
        assets = catalog.root/"assets"
        if assets.exists() or assets.is_symlink():
            if assets.is_symlink() or not assets.is_dir():
                raise CatalogError("CATALOG_INCONSISTENT", "unsafe assets directory")
            for asset in assets.iterdir():
                if asset.is_symlink() or not asset.is_dir():
                    raise CatalogError("CATALOG_INCONSISTENT", "unsafe asset directory")
                catalog._get("assets","asset_id",asset.name)
                for group in asset.iterdir():
                    if group.name not in {"snapshots","builds"} or group.is_symlink() or not group.is_dir():
                        raise CatalogError("CATALOG_INCONSISTENT", "unknown final artifact namespace")
                    known = snapshots if group.name=="snapshots" else builds
                    for path in group.iterdir():
                        if path.is_symlink() or not path.is_dir() or path.name not in known or known[path.name]["asset_id"] != asset.name:
                            raise CatalogError("CATALOG_INCONSISTENT", "final artifact has no matching database identity")
        for identity,row in snapshots.items():
            if row["status"] == "frozen":
                publication.verify_snapshot(identity)
        for row in builds.values():
            if row["status"] == "published":
                publication.verify_build(row,final=True)
    except (CatalogError,ContentStoreError,OSError,ValueError,KeyError) as error:
        raise CatalogError("CATALOG_INCONSISTENT", "frozen or published state failed verification") from error


def recover_catalog(catalog):
    """The held flock, not age or a stale PID, proves prior ownership ended."""
    catalog.database.assert_open()
    publication = Publication(catalog)
    results = []
    for row in [dict(r) for r in catalog._db.execute("SELECT * FROM asset_snapshots WHERE status='collecting' ORDER BY snapshot_id")]:
        identity = row["snapshot_id"]
        if publication.snapshot_path(row,final=True).exists():
            try:
                publication.verify_snapshot(identity)
            except (CatalogError,ContentStoreError,OSError,ValidationError,KeyError) as error:
                publication.fail_snapshot(identity,"RECOVERY_INVALID")
                results.append(dict(snapshot_id=identity,status="failed",reason=str(error)))
            else:
                publication.commit_snapshot(identity)
                results.append(dict(snapshot_id=identity,status="frozen"))
        else:
            publication.fail_snapshot(identity,"INTERRUPTED")
            results.append(dict(snapshot_id=identity,status="failed",reason="INTERRUPTED"))
    for row in [dict(r) for r in catalog._db.execute("SELECT * FROM asset_builds WHERE status='staging' ORDER BY build_id")]:
        identity = row["build_id"]
        if publication.build_path(row,final=True).exists():
            try:
                publication.verify_build(row,final=True)
            except (CatalogError,ContentStoreError,OSError,ValidationError,KeyError) as error:
                catalog.fail_build(identity,failure_code="RECOVERY_INVALID")
                results.append(dict(build_id=identity,status="failed",reason=str(error)))
            else:
                publication.commit_build(identity)
                results.append(dict(build_id=identity,status="published"))
        else:
            catalog.fail_build(identity,failure_code="INTERRUPTED")
            results.append(dict(build_id=identity,status="failed",reason="INTERRUPTED"))
    # Failed interrupted work proves a local task failure. Successful recovery
    # cannot decide whether the caller's entire task has been completed.
    failed_runs = {r[0] for r in catalog._db.execute("""SELECT run_id FROM asset_builds
        WHERE status='failed' AND failure_code IN ('INTERRUPTED','RECOVERY_INVALID') UNION
        SELECT run_id FROM asset_snapshots WHERE status='failed' AND failure_code IN ('INTERRUPTED','RECOVERY_INVALID')""")}
    for run_id in failed_runs:
        if catalog._get("runs","run_id",run_id)["status"] == "running":
            catalog.finish_run(run_id,status="failed",failure_code="INTERRUPTED_STORAGE_WORK")
    stage = catalog.root/"staging"
    if stage.exists():
        if stage.is_symlink() or not stage.is_dir():
            raise CatalogError("CATALOG_INCONSISTENT", "unsafe staging directory")
        known = {r[0] for r in catalog._db.execute("SELECT job_id FROM asset_builds")}
        known |= {"snapshot-"+r[0] for r in catalog._db.execute("SELECT snapshot_id FROM asset_snapshots")}
        for entry in stage.iterdir():
            if entry.name not in known:
                results.append(dict(orphan_staging=entry.name,status="retained"))
    return results
