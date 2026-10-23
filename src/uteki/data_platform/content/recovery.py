"""Explicit recovery under the same exclusive catalog lock; no automatic retry."""
from __future__ import annotations

import os
import stat

from pydantic import ValidationError

from ..contracts.common import CatalogError
from .store import ContentStoreError
from .publication import Publication


# 只读审计最终目录与数据库身份是否一致，并重新验证所有 frozen/published 版本；不修补内容。
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
        # 除目录身份匹配外，已确认版本还必须通过内容级校验；损坏不能伪装成可恢复的未完成状态。
        for identity,row in snapshots.items():
            if row["status"] == "frozen":
                publication.verify_snapshot(identity)
        for row in builds.values():
            if row["status"] == "published":
                publication.verify_build(row,final=True)
    except (CatalogError,ContentStoreError,OSError,ValueError,KeyError) as error:
        raise CatalogError("CATALOG_INCONSISTENT", "frozen or published state failed verification") from error


# 在已持有独占锁的前提下收敛中断状态：完整最终目录可确认提交，其余未完成工作记为失败。
def recover_catalog(catalog):
    """The held flock, not age or a stale PID, proves prior ownership ended."""
    catalog.database.assert_open()
    publication = Publication(catalog)
    results = []
    # 恢复只接纳最终目录里的完整候选；仍仅在 staging 的中断任务记失败，不自动继续发布。
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
    # 中断/校验失败可以证明局部任务失败；成功补提交却不能推定调用者整项任务已经完成。
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
        # 未知暂存目录仅列为保留项，不删除或据此创建新身份，以免丢失故障证据。
        for entry in stage.iterdir():
            if entry.name not in known:
                results.append(dict(orphan_staging=entry.name,status="retained"))
    return results
