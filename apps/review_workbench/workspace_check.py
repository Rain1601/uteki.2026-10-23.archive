"""Read-only preflight for the local workbench, without creating archive state."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zlib


COMPANIES = "data/company_universe/v0.1-candidate/companies.json"
CATALOG = "data/document_library/alphabet/catalog.json"
RELEASE = "data/research_data/alphabet_2025_10k/v0.2-candidate"
SOURCE = "data/source_documents/alphabet_2025_10k"


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def inspect_workspace(root: Path, *, data_path: Path | None = None) -> dict:
    """Check startup inputs and report source/experiment gaps separately.

    Readiness covers the core pages' inputs, not research quality or the
    presence of every historical experiment. No files or directories are made.
    """
    root = Path(root).resolve()
    checks = []

    def record(name, path, required, operation):
        try:
            detail = operation() or "Available / 可用"
            status = "ok"
        except FileNotFoundError as error:
            status, detail = "missing", str(error)
        except (OSError, EOFError, zlib.error, ValueError, KeyError, TypeError, IndexError, AttributeError, ImportError) as error:
            status, detail = "invalid", f"{type(error).__name__}: {error}"
        checks.append(dict(name=name, path=str(path), required=required, status=status, detail=detail))

    def dependency(module):
        if importlib.util.find_spec(module) is None:
            raise FileNotFoundError(f"Python module {module}; install with uv sync --extra analysis")

    if sys.version_info < (3, 11):
        checks.append(dict(name="Python", path=sys.executable, required=True, status="invalid",
                           detail="Python 3.11+ is required / 需要 Python 3.11 及以上"))
        return dict(root=str(root), ready=False, checks=checks)
    record("Document parser / 文档解析依赖", "lxml", True, lambda: dependency("lxml"))
    record("Analysis SDK / 分析扩展", "agents", False, lambda: dependency("agents"))

    def companies():
        from apps.review_workbench.pages.company_universe import render_company_universe_page
        value = _object(root / COMPANIES)
        # Exercise the existing read-only renderer's contract as well as its
        # validator; this catches missing labels without duplicating the schema.
        render_company_universe_page(value)
        return f"{len(value['companies'])} companies / 家公司"

    record("Company list / 公司名单", root / COMPANIES, True, companies)

    def catalog():
        from uteki.agents.material_library import load_catalog
        from apps.review_workbench.pages.company_data import material_table
        value = load_catalog(root)
        material_table(value)
        return f"{len(value['documents'])} catalog entries / 条材料目录记录"

    record("Alphabet material catalog / 材料目录", root / CATALOG, True, catalog)

    for filename in ("manifest.json", "evidence_bundle.json", "business_map.json"):
        path = root / RELEASE / filename
        record("Research data / 研究数据", path, True, lambda path=path: _object(path) and None)

    if all(c["status"] == "ok" for c in checks if c["name"] == "Research data / 研究数据"):
        def release():
            from uteki.infrastructure.research_data.local import LocalResearchDataPort
            port = LocalResearchDataPort(root / RELEASE)
            expected = {"business_map.json", "evidence_bundle.json"}
            if not expected <= set(port.manifest.get("artifacts", {})):
                raise ValueError("Release manifest must pin business_map.json and evidence_bundle.json hashes")
            return "Release hashes and identities checked / 已核对发布文件指纹及身份"
        record("Research release integrity / 研究数据发布完整性", root / RELEASE, True, release)

    if data_path is not None and Path(data_path).resolve() != (root / RELEASE / "business_map.json"):
        def custom_map():
            from uteki.domain.business_map import business_map_from_dict
            business_map_from_dict(_object(Path(data_path)))
        record("Selected business map / 指定业务图", data_path, True, custom_map)

    def source_manifest():
        value = _object(root / SOURCE / "manifest.json")
        for key in ("document_id", "source_snapshot_id", "source_url", "content_sha256"):
            if not isinstance(value[key], str) or not value[key].strip():
                raise ValueError(f"Source manifest requires {key}")
    record("Source manifest / 原文清单", root / SOURCE / "manifest.json", True, source_manifest)

    def source_excerpt():
        value = _object(root / SOURCE / "review_excerpt.json")
        if not isinstance(value["paragraphs"], list) or not value["paragraphs"]:
            raise ValueError("Source excerpt requires a nonempty paragraph list")
        if not isinstance(value["translation"]["notice_zh"], str):
            raise ValueError("Source excerpt requires a translation notice")
        for paragraph in value["paragraphs"]:
            for key in ("text", "text_hash", "translation_zh"):
                if not isinstance(paragraph[key], str) or not paragraph[key].strip():
                    raise ValueError(f"Source excerpt paragraph requires {key}")
            if type(paragraph["ordinal"]) is not int or paragraph["ordinal"] < 1:
                raise ValueError("Source excerpt requires positive paragraph ordinals")
            if not isinstance(paragraph["section_path"], list) or not all(isinstance(s, str) for s in paragraph["section_path"]):
                raise ValueError("Source excerpt section_path must be a list of strings")
        if value["source_snapshot_id"] != _object(root / SOURCE / "manifest.json")["source_snapshot_id"]:
            raise ValueError("Excerpt and source manifest snapshot identities differ")
    record("Source excerpt / 证据摘录", root / SOURCE / "review_excerpt.json", True, source_excerpt)

    if all(c["status"] == "ok" for c in checks if c["required"]):
        def business_map_page():
            from apps.review_workbench.app import render_result_page
            render_result_page(
                _object(Path(data_path) if data_path is not None else root / RELEASE / "business_map.json"),
                _object(root / SOURCE / "review_excerpt.json"),
                bundle=_object(root / RELEASE / "evidence_bundle.json"),
                release_manifest=_object(root / RELEASE / "manifest.json"),
            )
            return "Business map and exact citation contracts checked / 已核对业务图及精确引用契约"
        record("Business map page inputs / 业务图页面输入", root / RELEASE, True, business_map_page)

    def excerpt_hashes():
        from uteki.infrastructure.document_sources.sec import text_hash
        excerpt = _object(root / SOURCE / "review_excerpt.json")
        bad = [str(p["ordinal"]) for p in excerpt["paragraphs"] if text_hash(p["text"]) != p["text_hash"]]
        if bad:
            raise ValueError("Excerpt text hash mismatch at paragraph(s) / 摘录指纹不一致，段落: " + ", ".join(bad))
        return f"{len(excerpt['paragraphs'])} excerpt hashes checked / 段摘录指纹已核对"

    record("Excerpt integrity / 摘录完整性", root / SOURCE / "review_excerpt.json", False, excerpt_hashes)

    def raw_source():
        expected = _object(root / SOURCE / "manifest.json")["content_sha256"]
        with gzip.open(root / SOURCE / "source.html.gz", "rb") as stream:
            actual = hashlib.sha256(stream.read()).hexdigest()
        if actual != expected:
            raise ValueError("Uncompressed source hash does not match the pinned manifest")
    record("Full SEC source / 完整 SEC 原文", root / SOURCE / "source.html.gz", False, raw_source)

    def index(folder):
        from uteki.agents.reading.document_reader import DocumentReader
        DocumentReader(folder)
        _object(folder / "assets.json")
    record("Frozen document index / 已冻结文档索引", root / SOURCE / "indexes/v0.1", False,
           lambda: index(root / SOURCE / "indexes/v0.1"))

    # Verify entries advertised as indexed; absent/uncollected entries remain
    # honest catalog gaps and are not promoted to indexed by this check.
    if any(c["path"] == str(root / CATALOG) and c["status"] == "ok" for c in checks):
        from uteki.agents.material_library import load_catalog
        for document in load_catalog(root)["documents"]:
            if not document.get("status", "").startswith("indexed"):
                continue
            def material(document=document):
                folder = (root / document["index_folder"]).resolve()
                if not folder.is_relative_to(root):
                    raise ValueError("Material index is outside the workspace")
                index(folder)
            record("Material index / 材料索引: " + document["id"], document.get("index_folder", ""), False, material)

    def experiments():
        from apps.review_workbench.data.research_archive_import import import_rows
        rows = import_rows(root)
        if not rows:
            return "No imported reports; an empty report list is allowed / 无可导入报告，允许空列表"
        return f"{len(rows)} importable report candidates / 份可导入候选报告"
    record("Report imports / 报告导入", root / "experiments/analysis_comparison", True, experiments)

    state = root / "data/research_archive/state.json"
    if state.exists():
        def archive():
            from uteki.agents.research_archive import Store
            value = _object(state)
            for key, kind in (("snapshots", dict), ("comments", dict), ("audit_events", list)):
                if not isinstance(value[key], kind):
                    raise ValueError(f"Archive {key} must be a {kind.__name__}")
            if not all(isinstance(event, dict) for event in value["audit_events"]):
                raise ValueError("Archive audit_events must contain objects")
            for versions in value["comments"].values():
                if not isinstance(versions, list) or not versions or not all(isinstance(v, dict) for v in versions):
                    raise ValueError("Archive comments require nonempty version lists")
                for version in versions:
                    if not isinstance(version["snapshot_id"], str):
                        raise ValueError("Archive comment requires a snapshot identity")
            for identity, row in value["snapshots"].items():
                if row["id"] != identity or type(row["revision"]) is not int:
                    raise ValueError("Archive snapshot identity or revision is invalid")
                for key in ("id", "company_id", "scope", "primary_document_id", "status"):
                    if not isinstance(row[key], str) or not row[key]:
                        raise ValueError(f"Archive snapshot requires {key}")
                # Pure helpers only: Store.list/_transaction would create a lock.
                Store._view(value, row)
                Store._sort(row)
        record("Existing review state / 已有审核状态", state, True, archive)

    return dict(root=str(root), ready=all(c["status"] == "ok" for c in checks if c["required"]), checks=checks)


def format_report(report: dict) -> str:
    heading = ("Core workspace inputs ready / 基础工作区输入就绪" if report["ready"]
               else "Workspace data is incomplete / 工作区数据尚未齐备")
    lines = [heading]
    for check in report["checks"]:
        if check["status"] == "ok":
            continue
        level = "REQUIRED / 必需" if check["required"] else "GAP / 缺口"
        lines.extend((f"[{level}] {check['name']}: {check['path']}", f"  {check['detail']}"))
    lines.append("See docs/LOCAL_DEVELOPMENT.md for recovery steps / 恢复步骤见 docs/LOCAL_DEVELOPMENT.md")
    lines.append("Preflight does not approve research or restore historical reviews / 此检查不代表研究验收或历史审核恢复")
    return "\n".join(lines)
