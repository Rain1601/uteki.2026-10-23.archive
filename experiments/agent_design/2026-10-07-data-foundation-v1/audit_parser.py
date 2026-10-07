#!/usr/bin/env python3
"""Offline, read-only audit of two explicitly selected frozen HTML packages.

Default: print a compact result. --write exclusively creates this experiment's
    two reports. --check compares input/diagnostic recomputation with both reports. Never
rewrites sources, packages, production code, or tests; makes no model/HTTP calls.
Run with the repository .venv Python (lxml/pydantic are already dependencies).
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from lxml import html
from uteki.infrastructure.document_sources.parsed_package import verify_parsed_package
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _hidden, _visible_text, parse_sec_source


# Explicit historical audit cases, never defaults for a production parser.
CASES = {
    "amd": {
        "dataset": "experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset",
        "source_id": "source-291485b98a75d8cfabe47571",
        "raw_sha256": "47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808",
        "package_manifest_sha256": "7a9ee2adc1bca4c6ca621e4011d474938e3eb320e79d68b69965515b2e5fa55d",
    },
    "tsmc": {
        "dataset": "experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-tsmc/dataset",
        "source_id": "source-6719837a8d24b2b7df359f29",
        "raw_sha256": "8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1",
        "package_manifest_sha256": "b8fe2a7f4d6a27f01c2e2c97b9e564aaa757aca4460cbd0c735f778bd5c2281f",
    },
}
SAMPLE_LIMIT = 20
ITEM = re.compile(r"^ITEM\s+(\d+[A-Z]?)\.\s+(.+)$")
UNITS = re.compile(r"\b(?:in|US\$|NT\$)\s*(?:millions|thousands|billions)\b", re.I)
IMPLEMENTATION = [
    "src/uteki/infrastructure/document_sources/sec_index.py",
    "src/uteki/infrastructure/document_sources/parsed_package.py",
    "src/uteki/infrastructure/document_sources/sec.py",
    "src/uteki/domain/documents/models.py",
]
REVIEWED = [
    "AGENTS.md", "TODO.md",
    "experiments/agent_design/2026-10-07-parser-runtime-v1/README.zh-CN.md",
    "tests/unit/test_sec_visible_outline.py", "tests/unit/test_sec_document_index.py",
    "tests/unit/test_nested_source_blocks.py", "tests/unit/test_parsed_package.py",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def reference(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(raw), "bytes": len(raw)}


def location(block):
    return {k: block.get(k) for k in ("block_id", "ordinal", "type", "dom_path", "reported_page", "text_hash", "layout_role")}


def snippet(block):
    return {**location(block), "text_prefix": block["text"][:180], "text_characters": len(block["text"])}


def audit_case(key, case):
    dataset = ROOT / case["dataset"]
    sources = read_json(dataset / "sources.json")
    selected = [s for s in sources if s["source_snapshot_id"] == case["source_id"]]
    if len(selected) != 1:
        raise ValueError("explicit audit source missing or duplicated")
    source = selected[0]
    raw_path, package = dataset / source["raw_file"], dataset / source["index_folder"]
    raw = raw_path.read_bytes()
    if sha(raw) != case["raw_sha256"] or sha((package / "manifest.json").read_bytes()) != case["package_manifest_sha256"]:
        raise ValueError("frozen audit input fingerprint changed")
    verified = verify_parsed_package(package)
    blocks = [json.loads(line) for line in (package / "blocks.jsonl").read_bytes().splitlines()]
    by_id = {b["block_id"]: b for b in blocks}
    by_path = {b["dom_path"]: b for b in blocks}
    index, toc, anchors, assets = (read_json(package / name) for name in ("index.json", "toc.json", "anchors.json", "assets.json"))
    root = html.document_fromstring(raw, parser=html.HTMLParser(encoding="utf-8", recover=True, remove_comments=False))
    tree = root.getroottree()
    elements = {tree.getpath(e): e for e in root.iter() if isinstance(e.tag, str)}
    body = root.find("body")
    if body is None:
        raise ValueError("audit HTML body absent")

    block_mismatches = []
    for b in blocks:
        element = elements.get(b["dom_path"])
        expected = None if element is None else normalize_text(element.get("alt", "") if b["type"] == "image" else _visible_text(element))
        if expected != b["text"]:
            block_mismatches.append(snippet(b))

    # Every visible DOM text/tail segment is classified once. This checks DOM
    # containment coverage, not reading order, semantic completeness, or CSS.
    segment_counts = Counter()
    uncovered, overlapping = [], []
    for element in body.iter():
        for segment, owner, kind in ((element.text, element, "text"), (element.tail, element.getparent(), "tail")):
            if not segment or not normalize_text(segment) or owner is None or not isinstance(owner.tag, str):
                continue
            ancestors = [owner, *owner.iterancestors()]
            if kind == "text" and not isinstance(element.tag, str):
                continue
            if _hidden(owner) or any(str(e.tag).lower() in {"script", "style", "noscript"} for e in ancestors):
                segment_counts["excluded_hidden_or_script_segments"] += 1
                continue
            segment_counts["visible_text_segments"] += 1
            containing = [by_path[tree.getpath(e)] for e in ancestors if tree.getpath(e) in by_path]
            item = {"dom_path": tree.getpath(element), "segment": kind, "text_prefix": normalize_text(segment)[:160]}
            if not containing:
                segment_counts["uncovered_visible_text_segments"] += 1
                uncovered.append(item)
            else:
                segment_counts["covered_visible_text_segments"] += 1
                if len(containing) > 1:
                    segment_counts["multiply_covered_visible_text_segments"] += 1
                    overlapping.append({**item, "block_ids": [b["block_id"] for b in containing]})

    nav = [b for b in blocks if b["text"] == "Table of Contents"]
    groups = {}
    for b in blocks:
        if b["text"]:
            groups.setdefault(b["text"], []).append(b)
    repeats = sorted((v for v in groups.values() if len(v) > 1), key=lambda v: (-len(v), v[0]["ordinal"]))
    headings = [b for b in blocks if len(b["text"]) <= 180 and ITEM.fullmatch(b["text"]) and not b["layout_role"]]
    tables = [b for b in blocks if b["table"]]
    eligible_paths = {b["dom_path"]: b for b in blocks if b["type"] != "page_marker" and b["layout_role"] != "running_header"}
    anchor_counts = Counter()
    anchor_mismatches, hidden_anchors = [], []
    by_anchor = {}
    for a in anchors:
        by_anchor.setdefault(a["anchor"], []).append(a)
        element = elements.get(a["dom_path"])
        anchor_counts["all_anchor_occurrences"] += 1
        if element is None:
            anchor_counts["unresolved_dom_path"] += 1
            continue
        if _hidden(element):
            anchor_counts["hidden_anchor_occurrences"] += 1
            if a["target_block_id"] is not None:
                anchor_counts["hidden_anchors_with_visible_targets"] += 1
                hidden_anchors.append(a)
            continue
        container = next((eligible_paths[tree.getpath(e)] for e in [element, *element.iterancestors()] if tree.getpath(e) in eligible_paths), None)
        if container is None:
            anchor_counts["no_containing_eligible_block"] += 1
        else:
            anchor_counts["inside_eligible_block"] += 1
            if a["target_block_id"] != container["block_id"]:
                anchor_counts["containing_block_target_mismatch"] += 1
                anchor_mismatches.append({**a, "expected_containing_block": location(container),
                    "observed_target": snippet(by_id[a["target_block_id"]]) if a["target_block_id"] in by_id else None})

    notes = [b for b in blocks if UNITS.search(b["text"])]
    result = {
        "selection": {"label": key, "company_id": source["company_id"], "source_snapshot_id": source["source_snapshot_id"],
            "form": source["form"], "period_end": source["period_end"], "source_url": source["source_url"]},
        "inputs": {"raw": reference(raw_path), "dataset_manifest": reference(dataset / "manifest.json"),
            "sources": reference(dataset / "sources.json"), "package_files": [reference(p) for p in sorted(package.rglob("*")) if p.is_file()]},
        "frozen_runtime": read_json(package / "manifest.json")["runtime"],
        "structural_verification": {"status": "passed", **verified, "block_dom_text_mismatch_count": len(block_mismatches),
            "block_dom_text_mismatches": block_mismatches},
        "counts": {"blocks": len(blocks), "block_types": dict(sorted(Counter(b["type"] for b in blocks).items())),
            "layout_roles": dict(sorted(Counter(b["layout_role"] or "unclassified" for b in blocks).items())),
            "tables": len(tables), "cells": sum(len(b["table"]["cells"]) for b in tables),
            "merged_cells": sum(c["rowspan"] > 1 or c["colspan"] > 1 for b in tables for c in b["table"]["cells"]),
            "nested_table_blocks": sum(any(str(e.tag).lower() == "table" for e in elements[b["dom_path"]].iterancestors()) for b in tables),
            "raw_img_elements": len(root.xpath("//img")), "image_blocks": sum(b["type"] == "image" for b in blocks),
            "asset_references": len(assets["assets"]), "index_kinds": dict(sorted(Counter(n["kind"] for n in index["nodes"]).items())),
            "toc_entries": len(toc), "toc_items": sum(t["kind"] == "item" for t in toc)},
        "visible_text_containment_scan": {**dict(sorted(segment_counts.items())), "sample_limit": SAMPLE_LIMIT,
            "uncovered_samples": uncovered[:SAMPLE_LIMIT], "multiple_owner_samples": overlapping[:SAMPLE_LIMIT],
            "limitation": "Uses parser visibility rules; DOM containment only, not unique representation, browser CSS, or sentence-level semantic review."},
        "navigation": {"exact_label": "Table of Contents", "count": len(nav),
            "unclassified_count": sum(not b["layout_role"] for b in nav), "locations": [location(b) for b in nav],
            "raw_link_samples": [{**location(b), "hrefs": elements[b["dom_path"]].xpath(".//a/@href")} for b in nav[:3]]},
        "exact_repeats": {"groups": len(repeats), "extra_occurrences": sum(len(v)-1 for v in repeats),
            "samples": [{"count": len(v), "text_prefix": v[0]["text"][:100], "first": location(v[0])} for v in repeats[:SAMPLE_LIMIT]],
            "limitation": "Repeated strings are diagnostic candidates, not permission to remove duplicate financial facts or qualifications."},
        "outline": {"nodes": index["nodes"], "diagnostics": index["diagnostics"],
            "short_uppercase_item_candidate_count": len(headings), "short_uppercase_item_candidates": [snippet(b) for b in headings],
            "candidate_rule": "Explicit uppercase ITEM number+title, <=180 characters, no layout role; a discovery rule, not semantic acceptance."},
        "anchors": {**dict(sorted(anchor_counts.items())), "duplicate_anchor_names": sorted(k for k,v in by_anchor.items() if len(v)>1),
            "mismatch_samples": anchor_mismatches[:SAMPLE_LIMIT], "hidden_target_samples": hidden_anchors[:SAMPLE_LIMIT], "sample_limit": SAMPLE_LIMIT},
        "units_and_footnotes": {"unit_pattern_block_count": len(notes), "unit_pattern_samples": [snippet(b) for b in notes[:SAMPLE_LIMIT]],
            "binding_status": "not_implemented_or_not_verified", "semantic_footnote_completeness": "not_reviewed",
            "limitation": "Units/footnotes remain source text and table cells; occurrence counts do not prove associations to all numeric facts."},
        "images": {"bytes_status": assets["bytes_status"], "ocr_status": assets["ocr_status"], "vision_status": assets["vision_status"]},
        "semantic_review": "not_performed_whole_document", "production_code_changed": False,
    }
    if key == "amd":
        a = by_anchor["f-313"][0]
        element = elements[a["dom_path"]]
        table = next(by_path[tree.getpath(e)] for e in element.iterancestors() if tree.getpath(e) in by_path and by_path[tree.getpath(e)]["type"] == "table")
        result["f313"] = {**a, "raw_id_byte_offset_zero_based": raw.index(b'id="f-313"'),
            "source_text": normalize_text(element.text_content()), "expected_block": snippet(table),
            "observed_target": snippet(by_id[a["target_block_id"]]),
            "matching_cells": [c for c in table["table"]["cells"] if c["text"] == normalize_text(element.text_content())],
            "unit_text_present_in_same_table": "(In millions)" in table["text"],
            "reading_cell_fragment": table["block_id"] + "--r25-c3"}
    return result


def synthetic_probes():
    # Expected ownership is authored independently of the current bisect result.
    cases = [
        ("inline_in_paragraph", '<p>A <span id="a">inside</span> B</p><p>Following</p>', "A inside B", "paragraph"),
        ("inline_in_table", '<table><tr><td><span id="a">17</span></td></tr></table><p>Following</p>', "17", "table"),
        ("nested_table_nearest", '<table><tr><td>Outer<table><tr><td><i id="a">Inner</i></td></tr></table></td></tr></table><p>Following</p>', "Inner", "table"),
        ("inside_final_block", '<p>Final <span id="a">17</span></p>', "Final 17", "paragraph"),
        ("exact_block", '<p id="a">Exact</p><p>Following</p>', "Exact", "paragraph"),
        ("empty_marker_before_block", '<p>Prior</p><a id="a"></a><p>Following</p>', "Following", "paragraph"),
        ("wrapper_before_children", '<section id="a"><p>Child one</p><p>Child two</p></section>', "Child one", "paragraph"),
        ("hidden_id", '<p>Visible<span hidden id="a">Hidden</span> text</p><p>Following</p>', None, None),
    ]
    out = []
    for name, markup, expected_text, expected_type in cases:
        raw = ("<html><body>" + markup + "</body></html>").encode()
        parsed = parse_sec_source("synthetic-"+name, "https://example.invalid/audit/"+name, raw,
            source_snapshot_id="synthetic-"+name, form_type="10-K", parser_version="sec-source-blocks-v0.1.7")
        a = next(a for a in parsed.anchors if a.anchor == "a")
        target = next((b for b in parsed.blocks if b.block_id == a.target_block_id), None)
        matches = target is None if expected_text is None else target is not None and (target.text, target.type) == (expected_text, expected_type)
        out.append({"name": name, "synthetic_html": raw.decode(), "sha256": sha(raw), "anchor": asdict(a),
            "expected_text": expected_text, "expected_type": expected_type,
            "actual_target": {"block_id": target.block_id, "type": target.type, "text": target.text} if target else None,
            "current_parser_matches_proposed_acceptance": matches})
    return out


def build_report():
    return {"schema_version": "parser-structure-audit-v1", "status": "diagnosis_and_proposal_only",
        "scope": "Two explicitly pinned complete HTML files; structural scans plus three inspected defects, no whole-document semantic review.",
        "model_calls": 0, "network_calls": 0,
        "runner": reference(Path(__file__).resolve()),
        "implementation": [reference(ROOT / p) for p in IMPLEMENTATION],
        "reviewed_context": [reference(ROOT / p) for p in REVIEWED],
        "documents": {key: audit_case(key, case) for key,case in CASES.items()},
        "synthetic_anchor_probes": synthetic_probes(),
        "unreviewed": ["Sentence-level omissions and semantic equivalence", "Correct association of every financial footnote/unit/header",
            "Browser-computed CSS visibility", "Image bytes, OCR and visual information", "PDF or scanned documents",
            "Generalization beyond selected 10-K and 20-F HTML", "Production fix or post-fix acceptance"],
    }


def markdown(report):
    amd, tsm = report["documents"]["amd"], report["documents"]["tsmc"]
    rows = []
    for key, value in report["documents"].items():
        c, s, a = value["counts"], value["visible_text_containment_scan"], value["anchors"]
        rows.append(f"| {key.upper()} | {c['blocks']} | {c['tables']} / {c['cells']} | {c['merged_cells']} | {c['index_kinds'].get('item',0)} | {value['navigation']['count']} / {value['navigation']['unclassified_count']} | {a.get('containing_block_target_mismatch',0)} / {a.get('inside_eligible_block',0)} |")
    probes = report["synthetic_anchor_probes"]
    passed = sum(p["current_parser_matches_proposed_acceptance"] for p in probes)
    lines = ["# 整文解析结构审计与最小修复建议", "", "状态：诊断与拟议验收；未修生产代码，未做完整语义复核，未调用模型或网络。",
        "", "## 范围与复跑", "", "显式输入为上一轮冻结 AMD FY2023 10-K 与 TSMC FY2023 20-F。程序扫描两份完整 HTML 和全部解析块/表格/锚点；具体复核三项已知缺陷。没有逐段判断内容重要性或金融含义。",
        "", "```sh", ".venv/bin/python experiments/agent_design/2026-10-07-data-foundation-v1/audit_parser.py --check", "```",
        "", "默认命令只输出摘要；`--write` 仅首次独占创建本目录两个报告，拒绝覆盖。`--check` 比较冻结输入、诊断及文字报告；单独报告当前实现/上下文指纹是否仍等于审计时，允许后续新版本继续复核旧解析结果。原件和旧包不改写。",
        "", "完整位置、SHA-256、分母、抽样上限和合成输入见 [parser-audit.json](parser-audit.json)。原轮说明见 [README](../2026-10-07-parser-runtime-v1/README.zh-CN.md)。",
        "", "## 实际结构统计", "", "| 材料 | 块 | 表 / 单元格 | 合并格 | Item 节点 | 完全重复导航 / 未标记 | 块内锚点错位 / 块内锚点总数 |", "|---|---:|---:|---:|---:|---:|---:|", *rows,
        "", "表数包含版式表格；合并格按 rowspan>1 或 colspan>1 的格起点计数。重复导航仅统计全文完全等于 `Table of Contents` 的块，不能据此删除所有重复正文。锚点错位分母仅含可定位到非页码/非 running_header 块内的可见锚点；独立标记另计。",
    ]
    for key, value in report["documents"].items():
        s = value["visible_text_containment_scan"]
        lines += ["", f"- {key.upper()}：包 {value['structural_verification']['files_verified']} 文件校验通过；全部块 DOM 正文比对不一致 {value['structural_verification']['block_dom_text_mismatch_count']}。可见 DOM 文本段 {s.get('visible_text_segments',0)}，无块包含 {s.get('uncovered_visible_text_segments',0)}，多块包含 {s.get('multiply_covered_visible_text_segments',0)}。原件 SHA-256：`{value['inputs']['raw']['sha256']}`。"]
    lines += ["", "这些数字验证结构与表示一致性。多块包含可能来自父块与嵌套表重复表达；即使无遗漏文本段，也不证明浏览器可见性、顺序、单元格归属或金融语义全部正确。",
        "", "## 三项已复现缺陷", "", "### 1. 重复导航仍混入正文", "",
        f"AMD 的 {amd['navigation']['count']} 个 `Table of Contents` 块全部未标 layout_role；TSMC 同类块为 {tsm['navigation']['count']} 个，也全部未标。AMD 首例 `block-000038-a9360e02`，完整位置清单在 JSON navigation.locations。",
        "", "原因：当前 running_header 短语规则只处理 table，而这些导航是 paragraph。拟议先依据重复短文本、同一目录目标链接及页面上下文给布局角色打标；原文与块 ID 保留。检索/模型输入视图可按角色过滤并记录排除范围；不要物理删原件，也不要对正文中的普通“目录”字样直接删块。",
        "", "### 2. TSMC 目录有条目，索引没有 Item", "",
        f"`toc.json` 有 {tsm['counts']['toc_items']} 个 Item 条目，正文扫描得到 {tsm['outline']['short_uppercase_item_candidate_count']} 个短大写 ITEM 标题；全部保存在 table 块。当前 index 只有 1 Document + 3 Parts，0 Items，诊断 `item_unresolved`。例如 `block-000126-0b5ba9ef`（ITEM 1，`/html/body/div[7]/div/table[1]`）。",
        "", "原因：`_block_type` 先将 table 分类，`_verified_body_outline` 只接受 heading_candidate。拟议保留表格类型与单元格，同时将可验证的单行法律标题表纳入独立标题候选判断；核对原文目录目标、当前 Part、标题及邻接范围。避免把正文提到 Item、目录整表或多行财务表误当章节。29 是此材料的观察数，不是跨公司硬编码。",
        "", "### 3. 表内原始锚点跳到后继块", "",
        "AMD `f-313` 原文为 `1,667`，DOM 为 `/html/body/div[741]/table/tr[26]/td[2]/span/ix:nonfraction`。其 id 属性起始字节偏移为 958343（零基）。它属于 `block-000686-a6e8806b`，单元格为零基 row=25、column=3、colspan=2；阅读锚点 `block-000686-a6e8806b--r25-c3`。同表有 `(In millions)`，但这不是全部单位关系验收。",
        "", "现 anchors.json 却把它指向 `block-000688-a9360e02`，文字为 `Table of Contents`。算法对所有 id/name 使用 DOM 起点的 bisect 后继，忽略原始元素位于现有块内部；当前包校验只检查目标存在，所以错误仍可通过。",
        "", "## TODO 04：最小 anchor 修复提案（未实施）", "",
        "1. 在已有解析 DOM 和候选块上建立 element→block 映射；不新建或移动 DOM。先排除隐藏源锚点，保留 null/明确诊断。",
        "2. 可见锚点先匹配块本身，再向祖先找最近的合格包含块；嵌套表选择最近内表，不能映射到外表或后继块。页码及 running_header 的既有排除政策需显式保留。",
        "3. 只有不属于块的独立空锚点/包装锚点再走现有后继规则；记录这是 marker/wrapper 解析，不把 hidden、文末无后继或歧义强行定位。重复 id 的处理单独显式报冲突。",
        "4. 补 DOM 归属校验，而非只校验 target 存在。发布新 parser 版本并重建新包；不覆盖 v0.1.7 包。最小修复只改映射，不在同一补丁中删导航、改块序号或重写表格。",
        "", f"本脚本内置 8 个小型合成锚点反例/控制例；当前实现符合拟议预期 {passed}/8（这是修复前诊断，不是新增测试通过）。完整输入及现/期望结果见 JSON。",
        "", "| 合成验收 | 修复后应得到 |", "|---|---|", "| 段内 span、表内数值、末块内 id | 包含它的段落/表格；末块不得为 null |", "| 嵌套表内部 id | 最近内表，原表/文字不变 |", "| 块自身 id | 仍指向自身 |", "| 两块间空 a 标记；父包装 id | 仍可到下一块/首个子块 |", "| hidden id | 不声称定位到可见正文 |",
        "", "其他拟议验收：重复目录链接只被标记，不误删正文引用；包含“Item 16G”普通段落不成章节；合并格和单位/脚注文字保持；原件 SHA 不变；新包完整结构校验通过；另一个独立公司/期间复验。未实施的预期不能计作已通过。",
        "", "## 逐步产物与程序/模型职责", "", "```mermaid", "flowchart LR", " A[原件字节与身份哈希] --> B[程序：可见性与布局标记]", " B --> C[程序：原文块与表格单元格]", " C --> D[程序：目录及精确锚点]", " D --> E[程序：选择范围并记录未读/排除项]", " E --> F[后续模型：事实候选/忠实精编/业务图]", " F --> G[结构校验+来源回读+漏项与语义核验]", "```",
        "", "- 原件：不可改写，作为所有派生产物的根。过滤：当前只有有限可见性规则；新增布局标记和消费视图不能替代原件。",
        "- 切块：保留规范化原文、DOM、表格跨度与原始顺序；重叠与图片信息单列。目录和 anchor：提供导航与坐标，不算事实。",
        "- 模型加工：尚未在本审计执行。显式范围、规则、Schema、配置和证据引用形成候选；正文压缩与研究推断分开，未读部分保持缺口。",
        "", "## 支持边界与下一步", "", "本次只检查两个 HTML 10-K/20-F。10-Q 的已存在分支和单元测试不等于本轮真实整文验收；PDF 是另一条 pdftotext 文本坐标路径，扫描件/OCR、图片理解未运行。单位/脚注关联、内容遗漏、财务语义仍未逐项核验。",
        "", "优先：先审定 anchor 归属与隐藏/歧义政策，再实施有界新版本修复；随后分别处理重复导航和标题表，并保留独立验收分母。TODO 03 已交付结构诊断样本，不应标为完整逐段语义核查完成；TODO 04 尚未完成。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report()
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    narrative = markdown(report).encode()
    paths = [(HERE / "parser-audit.json", encoded), (HERE / "parser-audit.zh-CN.md", narrative)]
    if args.write:
        if any(path.exists() for path,_ in paths):
            raise FileExistsError("preserve existing audit; --check recomputes without writing")
        for path,raw in paths:
            with path.open("xb") as stream:
                stream.write(raw)
    context_matches = None
    if args.check:
        recorded = read_json(paths[0][0])
        context_matches = all(recorded[k] == report[k] for k in ("implementation", "reviewed_context"))
        facts = lambda value: {k:v for k,v in value.items() if k not in {"implementation", "reviewed_context"}}
        if facts(recorded) != facts(report) or paths[1][0].read_bytes() != narrative:
            raise ValueError("audit differs from recomputation; preserve historical report")
    print(json.dumps({"mode": "write" if args.write else "check" if args.check else "read_only",
        "documents": {k: {"blocks": v["counts"]["blocks"], "navigation": v["navigation"]["count"],
            "item_nodes": v["counts"]["index_kinds"].get("item",0), "anchor_containment_mismatches": v["anchors"].get("containing_block_target_mismatch",0)} for k,v in report["documents"].items()},
        "model_calls": 0, "execution_context_matches_recorded": context_matches, "recomputed_report_sha256": sha(encoded)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
