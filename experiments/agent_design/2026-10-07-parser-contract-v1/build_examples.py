"""Experimental deterministic parsing package. No model, network, or production writes.

Run ``.venv/bin/python .../build_examples.py --verify`` from the repository.
The explicit cases below select frozen materials; build_package has no sample defaults.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
from html import escape
import inspect
import json
from pathlib import Path, PurePosixPath
import platform
import sys
import tempfile
from typing import Annotated, Literal
from urllib.parse import urlsplit

import lxml
from lxml import etree
import pydantic
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from uteki.domain.documents import AssetReference, DocumentIndex, SourceAnchor, SourceBlock, TocEntry
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import build_legal_outline, parse_sec_source

HERE = Path(__file__).resolve().parent
PARSER = "sec-source-blocks-v0.1.7"
EXPORT = "uteki-parsed-document-v0.1-experiment"
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TEXT = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceSelection(Contract):
    company_id: TEXT
    document_id: TEXT
    source_snapshot_id: TEXT
    source_url: TEXT
    raw_sha256: SHA
    form_type: Literal["10-K", "20-F"]
    report_period_end: date
    parser_version: Literal["sec-source-blocks-v0.1.7"]
    export_version: Literal["uteki-parsed-document-v0.1-experiment"]

    @field_validator("company_id", "document_id", "source_snapshot_id", "source_url")
    @classmethod
    def unpadded(cls, value):
        if value != value.strip():
            raise ValueError("identity must be nonblank and unpadded")
        return value

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        url = urlsplit(value)
        if url.scheme not in ("https", "http") or not url.netloc or url.username or url.password:
            raise ValueError("source URL must be an explicit HTTP(S) URL without credentials")
        return value


class SourceMetadata(SourceSelection):
    index_id: TEXT
    source_identity_sha256: SHA
    available_at: date | None
    status: Literal["candidate_parsed_material"]
    semantic_review: Literal["not_reviewed"]
    text_representation: Literal["normalized-visible-html-text-v1"]
    character_offsets: Literal["zero-based Unicode code points in canonical block text; end exclusive"]
    asset_policy: Literal["references_only; bytes_not_included; OCR_and_vision_not_run"]


class Assets(Contract):
    status: Literal["metadata_only"]
    bytes_status: Literal["not_included"]
    ocr_status: Literal["not_run"]
    vision_status: Literal["not_run"]
    assets: list[AssetReference]


class ContentFile(Contract):
    sha256: SHA
    bytes: int = Field(ge=0)


class Runtime(Contract):
    python: TEXT
    pydantic: TEXT
    lxml: TEXT
    libxml2: TEXT
    implementation_sha256: dict[str, SHA]


class Manifest(Contract):
    schema_version: Literal["uteki-parser-package-manifest-v1"]
    package_id: TEXT
    source_identity_sha256: SHA
    export_version: Literal["uteki-parsed-document-v0.1-experiment"]
    parser_version: Literal["sec-source-blocks-v0.1.7"]
    runtime: Runtime
    files: dict[str, ContentFile]


ADAPTERS = {
    "source.json": TypeAdapter(SourceMetadata),
    "blocks.jsonl": TypeAdapter(SourceBlock),
    "index.json": TypeAdapter(DocumentIndex),
    "anchors.json": TypeAdapter(list[SourceAnchor]),
    "toc.json": TypeAdapter(list[TocEntry]),
    "assets.json": TypeAdapter(Assets),
    "manifest.json": TypeAdapter(Manifest),
}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def schema_name(name):
    return "schemas/" + name.removesuffix(".jsonl").removesuffix(".json") + ".schema.json"


def json_value(adapter, value):
    encoded = adapter.dump_json(adapter.validate_python(value), warnings="error")
    # Revalidate the persisted representation, not just the Python object.
    decoded = adapter.validate_json(encoded)
    return adapter.dump_python(decoded, mode="json")


def runtime_fingerprint():
    from uteki.domain.documents import models
    files = {"document_models": Path(inspect.getfile(models)),
             "sec_parser": Path(inspect.getfile(parse_sec_source)),
             "text_normalization": Path(inspect.getfile(normalize_text)),
             "experimental_exporter": Path(__file__).resolve()}
    return Runtime(python=platform.python_version(), pydantic=pydantic.__version__,
        lxml=lxml.__version__, libxml2=".".join(map(str, etree.LIBXML_VERSION)),
        implementation_sha256={key: sha(path.read_bytes()) for key, path in sorted(files.items())})


def contained(root, relative):
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("explicit relative frozen path required")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("frozen path must stay within selected dataset")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError("frozen file is absent or outside selected dataset")
    return resolved


def selected_source(dataset, selection):
    """Authenticate selected metadata/raw bytes against its frozen dataset manifest."""
    dataset = Path(dataset).resolve()
    manifest = json.loads((dataset / "manifest.json").read_bytes())
    pins = manifest.get("files", {})

    def read(name):
        if name not in pins:
            raise ValueError("selected input is not pinned in dataset manifest")
        raw = contained(dataset, name).read_bytes()
        if sha(raw) != pins[name]:
            raise ValueError("frozen dataset input hash mismatch")
        return raw

    sources = json.loads(read("sources.json"))
    matched = [source for source in sources if source.get("source_snapshot_id") == selection.source_snapshot_id]
    if len(matched) != 1:
        raise ValueError("source snapshot must select exactly one frozen source")
    source = matched[0]
    names = {"company_id": "company_id", "document_id": "document_id", "source_snapshot_id": "source_snapshot_id",
             "source_url": "source_url", "raw_sha256": "source_sha256", "form_type": "form",
             "report_period_end": "period_end"}
    explicit = selection.model_dump(mode="json")
    if any(source.get(stored) != explicit[provided] for provided, stored in names.items()):
        raise ValueError("explicit source identity conflicts with frozen metadata")
    raw = read(source["raw_file"])
    if sha(raw) != selection.raw_sha256 or source.get("raw_file_sha256") != selection.raw_sha256:
        raise ValueError("raw bytes conflict with selected source hash")
    if source.get("parsed_mime_type", source.get("declared_mime_type")) not in ("text/html", "application/xhtml+xml"):
        raise ValueError("this experiment accepts HTML sources only")
    return source, raw


STYLE = """body{font:16px/1.65 system-ui,sans-serif;color:#192127;background:#fff;margin:0 auto;padding:32px;max-width:1120px}h1{font-size:28px}h2{font-size:22px}a{color:#175e77}header,nav,.notes{border-bottom:1px solid #ccd4d7;padding-bottom:20px;margin-bottom:24px}.meta{font:12px/1.6 ui-monospace,monospace;color:#58676e;overflow-wrap:anywhere}.block{padding:14px 0;border-bottom:1px solid #e5e9eb;scroll-margin-top:15px}.block p{margin:8px 0}.heading{font-weight:650}.layout{background:#f6f7f7}.table-wrap{overflow:auto}table{border-collapse:collapse;width:max-content;min-width:65%;max-width:none}td,th{border:1px solid #b9c5ca;padding:4px 8px;max-width:600px;vertical-align:top;white-space:normal}th{background:#edf2f3}.cell-ref{display:block;font-size:10px;color:#6b777b}summary{cursor:pointer}.warning{color:#824214}.source-text{white-space:pre-wrap}.asset{padding:12px;background:#f3f5f5}footer{margin-top:28px}@media print{body{padding:12px;max-width:none}.table-wrap{overflow:visible}table{width:100%;min-width:0}td,th{max-width:350px}.block{break-inside:auto}}"""


def render_document(source, blocks, index):
    """A deterministic reading representation, never an LLM rewrite or a new source."""
    esc = lambda value: escape(str(value), quote=True)
    title = f"{source['company_id']} · {source['form_type']} · {source['report_period_end']}"
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; base-uri \'none\'">',
        f'<title>{esc(title)}</title><style>{STYLE}</style></head><body>',
        f'<header><h1>{esc(title)}</h1><p>标准解析文档 / Canonical parsed document</p>',
        f'<p><a href="{esc(source["source_url"])}" rel="noreferrer noopener">原始来源 / Original source</a> · <a href="source.json">来源说明 / Source contract</a> · <a href="manifest.json">文件校验 / Manifest</a></p>',
        f'<p class="meta">Snapshot: {esc(source["source_snapshot_id"])}<br>Raw SHA-256: {esc(source["raw_sha256"])}<br>Parser: {esc(source["parser_version"])} · Export: {esc(source["export_version"])}</p></header>',
        '<section class="notes"><h2>阅读范围与限制 / Reading scope</h2><p>这是冻结 HTML 的确定性解析视图。空白已规范化；没有翻译、精编、事实语义提取或模型摘要。This view preserves parsed blocks in source order, with normalized whitespace.</p>',
        '<p>标题候选不等于已确认目录。表格含布局表；外层块可能含内层表的重复文字。单元格保留行列及合并信息，但未判定财务口径。Reported page is a source page label, not a PDF page. Image bytes, OCR and vision are not included.</p>',
        '<p>状态：候选解析材料，内容尚未审核。报告截止日不代表每个单元格的财务期间。This export does not establish complete source coverage or financial correctness.</p>',
        '<p>字符区间以 blocks.jsonl 中的 Unicode 字符计数，零起点、末端不含。原始 HTML 字节以 source.json 的 hash 固定。引用应同时保留 snapshot、index、block 与所需 cell。</p></section>',
        '<nav aria-label="Legal outline"><h2>已解析法定目录 / Parsed legal outline</h2><ul>']
    for node in index["nodes"]:
        parts.append(f'<li><a href="#{esc(node["start_block_id"])}">{esc(node["kind"])} · {esc(node["title"])}</a> <span class="meta">{esc(node["node_id"])}</span></li>')
    parts.append('</ul><details open><summary>解析诊断 / Diagnostics</summary><ul>')
    for diagnostic in index["diagnostics"]:
        parts.append(f'<li class="warning">{esc(diagnostic["severity"])} · {esc(diagnostic["code"])} — {esc(diagnostic["message"])}</li>')
    if not index["diagnostics"]:
        parts.append('<li>No parser diagnostics; this is not a completeness guarantee.</li>')
    parts.append('</ul></details></nav><main>')
    for block in blocks:
        bid = block["block_id"]
        role = block.get("layout_role")
        kind = block["type"]
        parts.append(f'<article class="block{ " layout" if role else ""}" id="{esc(bid)}" data-block-id="{esc(bid)}">')
        parts.append(f'<p class="meta"><a href="#{esc(bid)}">{esc(bid)}</a> · {esc(kind)} · report page: {esc(block.get("reported_page") if block.get("reported_page") is not None else "unknown")} · layout: {esc(role or "unclassified")}</p>')
        if kind == "table" and block.get("table") is not None:
            table = block["table"]
            by_row = {}
            for cell in table["cells"]:
                by_row.setdefault(cell["row"], []).append(cell)
            parts.append('<div class="table-wrap"><table><tbody>')
            for row in range(table["row_count"]):
                parts.append('<tr>')
                for cell in sorted(by_row.get(row, []), key=lambda item: item["column"]):
                    tag = "th" if cell["is_header"] else "td"
                    cid = f'{bid}--r{cell["row"]}-c{cell["column"]}'
                    parts.append(f'<{tag} id="{esc(cid)}" data-row="{cell["row"]}" data-column="{cell["column"]}" rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}"><a class="cell-ref" href="#{esc(cid)}">r{cell["row"]} c{cell["column"]}</a><span class="cell-text">{esc(cell["text"])}</span></{tag}>')
                parts.append('</tr>')
            parts.append('</tbody></table></div>')
            parts.append(f'<details><summary>规范化块文字 / Normalized block text</summary><p class="source-text">{esc(block["text"])}</p></details>')
        elif kind == "image":
            parts.append(f'<p class="asset">图片引用 / Image reference: {esc(block.get("image_asset_id") or "unknown")}<br>Alt text: {esc(block["text"])}<br>Bytes not included · OCR not run · Vision not run</p>')
        else:
            parts.append(f'<p class="source-text{ " heading" if kind == "heading_candidate" else ""}">{esc(block["text"])}</p>')
        parts.append('</article>')
    parts.append('</main><footer>Generated deterministically from this package’s blocks.jsonl and index.json. All content remains candidate parsed material.</footer></body></html>\n')
    return "".join(parts).encode("utf-8")


def validate_content(source, blocks, index, assets):
    if not blocks:
        raise ValueError("source has no parsed blocks")
    ids = [block["block_id"] for block in blocks]
    if len(ids) != len(set(ids)) or [b["ordinal"] for b in blocks] != list(range(1, len(blocks) + 1)):
        raise ValueError("blocks require unique IDs and source-ordered contiguous ordinals")
    positions = {bid: n for n, bid in enumerate(ids)}
    for block in blocks:
        if normalize_text(block["text"]) != block["text"] or sha(block["text"].encode()) != block["text_hash"]:
            raise ValueError("canonical block text/hash mismatch")
        if block["type"] == "table":
            table = block["table"]
            if table is None:
                raise ValueError("table block requires table structure")
            seen = set()
            for cell in table["cells"]:
                pos = (cell["row"], cell["column"])
                if (pos in seen or not 0 <= pos[0] < table["row_count"] or not 0 <= pos[1] < table["column_count"]
                        or min(cell["rowspan"], cell["colspan"]) < 1):
                    raise ValueError("invalid or duplicate cell coordinates")
                seen.add(pos)
    nodes = {n["node_id"]: n for n in index["nodes"]}
    if len(nodes) != len(index["nodes"]):
        raise ValueError("duplicate outline node")
    if (index["source_snapshot_id"] != source["source_snapshot_id"] or index["index_id"] != source["index_id"]
            or index["parser_version"] != source["parser_version"] or index["form_type"] != source["form_type"]):
        raise ValueError("index identity mismatch")
    for node in nodes.values():
        lo, hi = positions[node["start_block_id"]], positions[node["end_block_id"]]
        if lo > hi:
            raise ValueError("outline range reversed")
        if node["parent_id"]:
            parent = nodes[node["parent_id"]]
            if not positions[parent["start_block_id"]] <= lo <= hi <= positions[parent["end_block_id"]]:
                raise ValueError("outline child outside parent")
    asset_ids = {a["asset_id"] for a in assets["assets"]}
    if len(asset_ids) != len(assets["assets"]) or any(b.get("image_asset_id") not in asset_ids for b in blocks if b["type"] == "image"):
        raise ValueError("image block has no unique asset reference")


def build_package(dataset, selection, output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("output already exists; preserve the previous package")
    selection = SourceSelection.model_validate(selection)
    dataset = Path(dataset).resolve()
    if output.resolve().is_relative_to(dataset):
        raise ValueError("output must not modify the frozen dataset")
    stored, raw = selected_source(dataset, selection)
    parsed = parse_sec_source(selection.document_id, selection.source_url, raw,
        source_snapshot_id=selection.source_snapshot_id, form_type=selection.form_type, parser_version=selection.parser_version)
    index = json_value(ADAPTERS["index.json"], build_legal_outline(parsed))
    identity_sha = sha(canonical(selection.model_dump(mode="json")))
    source = SourceMetadata(**selection.model_dump(), index_id=index["index_id"], source_identity_sha256=identity_sha,
        available_at=stored.get("available_at"), status="candidate_parsed_material", semantic_review="not_reviewed",
        text_representation="normalized-visible-html-text-v1",
        character_offsets="zero-based Unicode code points in canonical block text; end exclusive",
        asset_policy="references_only; bytes_not_included; OCR_and_vision_not_run")
    payloads = {"source.json": json_value(ADAPTERS["source.json"], source), "index.json": index,
        "anchors.json": json_value(ADAPTERS["anchors.json"], list(parsed.anchors)),
        "toc.json": json_value(ADAPTERS["toc.json"], list(parsed.toc_entries)),
        "assets.json": json_value(ADAPTERS["assets.json"], Assets(status="metadata_only", bytes_status="not_included",
             ocr_status="not_run", vision_status="not_run", assets=list(parsed.assets)))}
    blocks = [json_value(ADAPTERS["blocks.jsonl"], block) for block in parsed.blocks]
    validate_content(payloads["source.json"], blocks, index, payloads["assets.json"])
    if any(a["target_block_id"] is not None and a["target_block_id"] not in {b["block_id"] for b in blocks} for a in payloads["anchors.json"]):
        raise ValueError("anchor targets absent block")
    files = {name: canonical(value) for name, value in payloads.items()}
    files["blocks.jsonl"] = b"".join(canonical(block) for block in blocks)
    files["document.html"] = render_document(payloads["source.json"], blocks, index)
    for name, adapter in ADAPTERS.items():
        schema = adapter.json_schema()
        schema["$comment"] = f"{EXPORT}; {'one JSON object per line' if name.endswith('.jsonl') else 'complete JSON document'}. Semantic integrity checks also run in build_examples.validate_content."
        files[schema_name(name)] = canonical(schema)
    entries = {name: {"sha256": sha(content), "bytes": len(content)} for name, content in sorted(files.items())}
    runtime = runtime_fingerprint()
    package_id = "parsed-" + sha(canonical({"source_identity_sha256": identity_sha, "files": entries,
                                           "runtime": runtime.model_dump(mode="json")}))[:24]
    manifest = Manifest(schema_version="uteki-parser-package-manifest-v1", package_id=package_id,
        source_identity_sha256=identity_sha, export_version=EXPORT, parser_version=PARSER, runtime=runtime, files=entries)
    files["manifest.json"] = canonical(json_value(ADAPTERS["manifest.json"], manifest))
    output.mkdir(parents=True, exist_ok=False)
    for name, content in sorted(files.items()):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    verify_package(output)
    return {"package_id": package_id, "source_identity_sha256": identity_sha, "blocks": len(blocks),
        "block_types": dict(sorted(Counter(b["type"] for b in blocks).items())),
        "tables": sum(b["type"] == "table" for b in blocks),
        "cells": sum(len(b["table"]["cells"]) for b in blocks if b["table"]),
        "assets": len(parsed.assets), "anchors": len(parsed.anchors), "toc_entries": len(parsed.toc_entries),
        "node_types": dict(sorted(Counter(n["kind"] for n in index["nodes"]).items())),
        "diagnostics": index["diagnostics"], "file_count": len(files)}


def verify_package(folder):
    folder = Path(folder)
    manifest = Manifest.model_validate_json((folder / "manifest.json").read_bytes())
    observed = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if observed != set(manifest.files) | {"manifest.json"}:
        raise ValueError("package files differ from manifest")
    for name, ref in manifest.files.items():
        raw = contained(folder, name).read_bytes()
        if len(raw) != ref.bytes or sha(raw) != ref.sha256:
            raise ValueError("package content hash mismatch")
    values = {}
    for name, adapter in ADAPTERS.items():
        raw = (folder / name).read_bytes()
        if name == "blocks.jsonl":
            values[name] = [adapter.dump_python(adapter.validate_json(line), mode="json") for line in raw.splitlines()]
        else:
            values[name] = adapter.dump_python(adapter.validate_json(raw), mode="json")
    validate_content(values["source.json"], values["blocks.jsonl"], values["index.json"], values["assets.json"])
    source = values["source.json"]
    selection = {key: source[key] for key in SourceSelection.model_fields}
    if sha(canonical(selection)) != source["source_identity_sha256"] or source["source_identity_sha256"] != manifest.source_identity_sha256:
        raise ValueError("source identity fingerprint mismatch")
    expected_id = "parsed-" + sha(canonical({"source_identity_sha256": manifest.source_identity_sha256,
        "files": {key: ref.model_dump() for key, ref in manifest.files.items()}, "runtime": manifest.runtime.model_dump(mode="json")}))[:24]
    if manifest.package_id != expected_id:
        raise ValueError("package identity mismatch")
    from lxml import html
    document = html.fromstring((folder / "document.html").read_bytes())
    if document.xpath("//script|//img|//iframe|//object|//embed|//link[@href]"):
        raise ValueError("reading document must not load external content or scripts")
    elements = document.xpath("//*[@id]")
    element_ids = [element.get("id") for element in elements]
    if len(element_ids) != len(set(element_ids)):
        raise ValueError("duplicate HTML anchor")
    by_id = {element.get("id"): element for element in elements}
    blocks = values["blocks.jsonl"]
    if document.xpath("//article/@data-block-id") != [b["block_id"] for b in blocks]:
        raise ValueError("HTML block order mismatch")
    for block in blocks:
        if block["type"] == "table":
            for cell in block["table"]["cells"]:
                cid = f'{block["block_id"]}--r{cell["row"]}-c{cell["column"]}'
                element = by_id.get(cid)
                if element is None or element.findtext("span[@class='cell-text']") != cell["text"]:
                    raise ValueError("HTML cell text/anchor mismatch")
                if element.get("rowspan") != str(cell["rowspan"]) or element.get("colspan") != str(cell["colspan"]):
                    raise ValueError("HTML merged cell mismatch")
    if render_document(source, blocks, values["index.json"]) != (folder / "document.html").read_bytes():
        raise ValueError("HTML differs from deterministic source rendering")
    return {"files_verified": len(observed), "blocks_verified": len(blocks),
            "cells_verified": sum(len(b["table"]["cells"]) for b in blocks if b["table"])}


BASE = "experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1"
CASES = [
    {"case_id": "amd-fy2023-10k", "dataset": BASE + "/amd-fy2023-formal-batch-00-v1/extraction-01/dataset",
     "selection": {"company_id": "sec-0000002488", "document_id": "source-291485b98a75d8cfabe47571",
        "source_snapshot_id": "source-291485b98a75d8cfabe47571", "source_url": "https://www.sec.gov/Archives/edgar/data/2488/000000248824000012/amd-20231230.htm",
        "raw_sha256": "47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808",
        "form_type": "10-K", "report_period_end": "2023-12-30", "parser_version": PARSER, "export_version": EXPORT}},
    {"case_id": "tsmc-fy2023-20f", "dataset": BASE + "/tsmc-fy2023-operating-cash-flow-batch-v2/extraction-01/dataset",
     "selection": {"company_id": "sec-0001046179", "document_id": "source-6719837a8d24b2b7df359f29",
        "source_snapshot_id": "source-6719837a8d24b2b7df359f29", "source_url": "https://www.sec.gov/Archives/edgar/data/1046179/000119312524099840/d592628d20f.htm",
        "raw_sha256": "8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1",
        "form_type": "20-F", "report_period_end": "2023-12-31", "parser_version": PARSER, "export_version": EXPORT}},
]


def verify_examples():
    report_path = HERE / "verification.json"
    if report_path.exists() or any((HERE / "examples" / case["case_id"]).exists() for case in CASES):
        raise FileExistsError("example outputs already exist; never overwrite a frozen experiment")
    report = {"experiment": EXPORT, "performed_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_fingerprint().model_dump(mode="json"), "cases": [],
        "limits": ["Two fixed real HTML inputs do not establish general parsing accuracy.",
                   "TSMC Item outline is unresolved; diagnostics remain errors.",
                   "Assets are references only. No OCR, model extraction, query case or network call ran.",
                   "All package bytes compared across different directories in this runtime; cross-runtime reproducibility is not claimed."]}
    for case in CASES:
        output = HERE / "examples" / case["case_id"]
        summary = build_package(ROOT / case["dataset"], case["selection"], output)
        with tempfile.TemporaryDirectory(prefix="uteki-parser-replay-") as temp:
            replay = Path(temp) / "different-depth" / "replayed-package"
            second = build_package(ROOT / case["dataset"], case["selection"], replay)
            hashes = {p.relative_to(output).as_posix(): sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}
            compared = {p.relative_to(replay).as_posix(): sha(p.read_bytes()) for p in sorted(replay.rglob("*")) if p.is_file()}
            if hashes != compared or summary != second:
                raise ValueError("same input/config package replay is not byte identical")
        report["cases"].append({"case_id": case["case_id"], "input_dataset": case["dataset"],
            "source_selection": case["selection"], "output": str(output.relative_to(ROOT)),
            "summary": summary, "same_input_second_export_all_files_identical": True,
            "checks": verify_package(output), "file_sha256": hashes})
        print(json.dumps({"case": case["case_id"], **summary, "replay_identical": True}, ensure_ascii=False), flush=True)
    with report_path.open("xb") as stream:
        stream.write(canonical(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", required=True)
    parser.parse_args()
    verify_examples()
