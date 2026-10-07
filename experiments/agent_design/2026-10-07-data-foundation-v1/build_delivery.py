"""Render the explicitly selected, source-checked acceptance example. No model calls."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
from lxml import html
from pydantic import TypeAdapter
from uteki.domain.business_map.models import BusinessMap, business_map_from_dict
from uteki.agents.business_map.prompts import OUTPUT_SCHEMA_V0_2
from uteki.domain.research_data.query_contract import ResearchRecord, export_query_schema

OUT = Path(__file__).resolve().parent
PAGE = REPO / "docs/design/data-agent-acceptance/first-iteration-v1/index.html"
DATASET = REPO / "experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset"
SID = "source-291485b98a75d8cfabe47571"
PACKAGE = DATASET / "indexes" / SID
RECORDS = REPO / "experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/amd-fy2023-cash-flow-main-agent-v2/query/turn-003/financial_extract/extraction-01/dataset/records.json"
ANSWER = REPO / "experiments/agent_design/2026-10-07-parser-runtime-v1/runs/business-source/query/artifacts/art-120f4cb41161792b97fc14dace14872f.json"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def link(path, label, fragment=""):
    url = os.path.relpath(path, PAGE.parent) + fragment
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def pretty(value):
    return '<pre><code>' + escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</code></pre>'


def build():
    source, manifest, index = read(PACKAGE / "source.json"), read(PACKAGE / "manifest.json"), read(PACKAGE / "index.json")
    for name, expected in manifest["files"].items():
        assert digest(PACKAGE / name) == expected["sha256"], name
    blocks = [json.loads(line) for line in (PACKAGE / "blocks.jsonl").read_text().splitlines()]
    by_id = {b["block_id"]: b for b in blocks}
    selected = blocks[71:77]
    assert [b["ordinal"] for b in selected] == list(range(72, 78))
    assert selected[0]["text"] == "Our four reportable segments are:"
    assert "not a reportable segment" in selected[-1]["text"]
    table = blocks[685]
    cells = {(c["row"], c["column"]): c for c in table["table"]["cells"]}
    assert cells[25, 3]["text"] == "1,667"
    assert cells[2, 3]["text"] == "December 30,2023"
    record = next(r for r in read(RECORDS)["rows"] if r["record_id"] == "direct-a186c066c80e7842aae07df1")
    ResearchRecord.model_validate(record)
    assert record["entity_id"] == source["company_id"] and record["source_snapshot_id"] == SID
    assert record["unit"] == "USD" and record["origin"]["raw"]["unit"] == "USD_millions"
    assert Decimal(record["value_decimal"]) == Decimal(cells[25, 3]["text"].replace(",", "")) * 1_000_000
    raw = DATASET / "raw" / f"{SID}.html"
    assert digest(raw) == source["raw_sha256"]
    tree = html.fromstring(raw.read_bytes())
    fact = tree.xpath('//*[@id="f-313"]')[0]
    assert fact.get("unitref") == "usd" and fact.get("scale") == "6"
    assert fact.text_content().replace(',', '').strip() == '1667'
    assert "iso4217:USD" in tree.xpath('//*[@id="usd"]')[0].text_content()
    assert record["period"]["end"] == source["report_period_end"]
    answer = read(ANSWER)
    assert answer["source_snapshot_id"] == SID and answer["status"] == "candidate"
    for claim in answer["claims"]:
        for citation in claim["citations"]:
            assert citation["quote"] in by_id[citation["block_id"]]["text"]
    node = next(n for n in index["nodes"] if n["title"] == "BUSINESS")
    assert node["start_block_id"] == blocks[39]["block_id"] and node["end_block_id"] == blocks[216]["block_id"]
    map_example = {
        "schema_version": "0.1", "company_id": source["company_id"], "document_id": SID,
        "summary": "设计小样：Data Center 是 AMD 披露的可报告分部，产品原文列举中含 AI accelerators。",
        "businesses": [
            {"id": "amd", "name": "AMD", "kind": "company", "description": "本份申报的公司", "evidence_ids": ["e72"]},
            {"id": "data-center", "name": "Data Center", "kind": "reportable_segment", "description": "披露的可报告分部",
             "products_services": ["server CPUs", "GPUs", "APUs", "DPUs", "FPGAs", "SmartNICs", "AI accelerators", "Adaptive SoC"],
             "customers": [], "monetization": [], "evidence_ids": ["e72", "e73"], "review_status": "candidate"}],
        "relationships": [{"source_id": "data-center", "target_id": "amd", "kind": "reported_under",
                           "description": "Data Center 作为 AMD 的可报告分部披露", "evidence_ids": ["e72", "e73"], "review_status": "candidate"}],
        "unknowns": [{"id": "customers", "question": "具体客户与收入模式是什么？", "materiality": "业务消费所需，超出本段",
                      "related_business_ids": ["data-center"], "reason_unanswered": "所选段落未提供，不代表全文未披露", "evidence_ids": ["e73"]}],
        "evidence": [{"id": f"e{b['ordinal']}", "document_id": SID, "section_path": ["PART I", "BUSINESS"],
                      "paragraph_ordinal": b["ordinal"], "text_hash": b["text_hash"], "source_url": source["source_url"],
                      "support": b["text"]} for b in selected[:2]],
        "metadata": {"presentation_status": "design_example", "coverage": "partial", "assertion_basis": "explicit",
                     "source_snapshot_id": SID, "package_id": manifest["package_id"],
                     "evidence_ordinal_mapping": "This example maps paragraph_ordinal to source block ordinal; not a production adapter.",
                     "product_list_qualifier": "primarily includes"}}
    business_map_from_dict(map_example)
    brief = {"schema_version": "filing-brief-example-v1", "presentation_status": "design_example", "coverage": "partial",
             "company_id": source["company_id"], "source_snapshot_id": SID, "package_id": manifest["package_id"],
             "report_period_end": source["report_period_end"], "selected_block_ids": [b["block_id"] for b in selected],
             "sentences": [
                 {"zh": "AMD 披露四个可报告分部：Data Center、Client、Gaming、Embedded。",
                  "en": "AMD reports four reportable segments: Data Center, Client, Gaming and Embedded.",
                  "evidence_block_ids": [b["block_id"] for b in selected[:5]]},
                 {"zh": "Data Center 主要包括面向数据中心的服务器 CPU、GPU、APU、DPU、FPGA、SmartNIC、AI 加速器和 Adaptive SoC 产品。",
                  "en": "Data Center primarily includes server CPUs, GPUs, APUs, DPUs, FPGAs, SmartNICs, AI accelerators and Adaptive SoC products for data centers.",
                  "evidence_block_ids": [selected[1]["block_id"]]},
                 {"zh": "All Other 是额外类别，不是可报告分部。",
                  "en": "All Other is an additional category, not a reportable segment.",
                  "evidence_block_ids": [selected[-1]["block_id"]]}],
             "gaps": ["仅展示六个原文块；未覆盖业务全文、财务、风险和附注。", "未运行财报精编模型。"]}
    brief_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Filing brief acceptance example — proposed, not production API",
                    "type": "object", "additionalProperties": False,
                    "required": list(brief), "properties": {}}
    for key in brief:
        if key in ("sentences", "selected_block_ids", "gaps"):
            brief_schema["properties"][key] = {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}
        else:
            brief_schema["properties"][key] = {"type": "string", "minLength": 1}
    for key in ("schema_version", "presentation_status", "coverage"):
        brief_schema["properties"][key] = {"const": brief[key]}
    brief_schema["properties"]["sentences"]["items"] = {"type": "object", "additionalProperties": False,
        "required": ["zh", "en", "evidence_block_ids"], "properties": {"zh": {"type": "string", "minLength": 1},
        "en": {"type": "string", "minLength": 1}, "evidence_block_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}}
    import jsonschema
    jsonschema.Draft202012Validator(brief_schema).validate(brief)
    jsonschema.Draft202012Validator(OUTPUT_SCHEMA_V0_2).validate(dict(map_example, metadata={}))
    schemas = OUT / "schemas"
    for name in ("source", "blocks", "index"):
        write_json(schemas / f"{name}.schema.json", read(PACKAGE / f"schemas/{name}.schema.json"))
    write_json(schemas / "numeric-fact.schema.json", export_query_schema(ResearchRecord, version=record["schema_version"]))
    write_json(schemas / "business-map.schema.json", TypeAdapter(BusinessMap).json_schema())
    write_json(schemas / "business-map-model-output.schema.json", OUTPUT_SCHEMA_V0_2)
    write_json(schemas / "brief-example.schema.json", brief_schema)
    sample = {"scope": {"company_id": source["company_id"], "source_snapshot_id": SID, "package_id": manifest["package_id"],
                         "report_period_end": source["report_period_end"], "cutoff": "2026-10-04", "raw_sha256": source["raw_sha256"]},
              "raw_blocks": selected, "cashflow_table_block_id": table["block_id"], "cashflow_cells": [cells[2, 3], cells[25, 0], cells[25, 3]],
              "numeric_historical_candidate": record, "business_historical_answer": answer, "brief_design_example": brief,
              "business_map_design_example": map_example, "index_node": node,
              "source_files": [{"path": str(p.relative_to(REPO)), "sha256": digest(p)} for p in
                               [PACKAGE / "source.json", PACKAGE / "blocks.jsonl", PACKAGE / "index.json", PACKAGE / "manifest.json", RECORDS, ANSWER]]}
    write_json(OUT / "product-samples.json", sample)
    check = {"schema_version": "delivery-preflight-v1", "kind": "offline_artifact_integrity_not_model_benchmark",
             "checks": {"frozen_package_file_hashes": True, "source_raw_hash": True, "quotes_resolve": True,
                        "numeric_existing_contract": True, "numeric_scale_and_inline_currency": True, "business_map_existing_contract": True,
                        "business_map_model_boundary_without_host_metadata": True,
                        "brief_proposed_schema": True, "business_index_selected_range": True},
             "model_calls": 0, "semantic_full_document_review": "not_run", "new_query_benchmark": "not_run",
             "coverage": "Only the explicitly selected examples; no correctness-rate claim.",
             "sample_sha256": digest(OUT / "product-samples.json")}
    write_json(OUT / "delivery-check.json", check)
    render(sample, brief, record, map_example, selected, node, source)
    print("Built source-checked product examples, schemas, acceptance page; zero model calls. Full-document semantic review and new Query benchmark not run.")


def render(sample, brief, record, graph, selected, node, source):
    evidence = ''.join(f'<li><b>{b["ordinal"]} · 第 {b["reported_page"]} 页</b><p>{escape(b["text"])}</p>{link(PACKAGE / "document.html", "定位到原文 / Open passage", "#" + b["block_id"])}</li>' for b in selected)
    details = lambda body: f'<details><summary>字段与消费方式 / Fields & reading</summary>{body}</details>'
    audit_path = OUT / "anchor-fix-v2-verification.json"
    if not audit_path.exists():
        audit_path = OUT / "anchor-fix-verification.json"
    audit_link = link(OUT / "parser-audit.zh-CN.md", "查看整文结构诊断 / Structural audit")
    # This report is populated only when the separately executed repair has evidence.
    fix_status = '<p>修复验证记录尚未登记；不能据本页宣称已修复。</p>'
    if audit_path.exists():
        report = read(audit_path)
        assert report['status'] == 'local_program_checks_passed'
        for case in report['documents'].values():
            assert digest(REPO / case['new_manifest']['path']) == case['new_manifest']['sha256']
            assert case['new_package_rebuild_identical'] and case['old_files_preserved']
        amd = report['documents']['amd']
        change = next(c for c in amd['anchor_changes'] if c['anchor'] == 'f-313')
        assert change['new_target_block_id'] == 'block-000686-a6e8806b'
        old_target = link(PACKAGE / 'document.html', '块 688 · Table of Contents', '#' + change['old_target_block_id'])
        new_package = (REPO / amd['new_manifest']['path']).parent
        new_target = link(new_package / 'document.html', '块 686 · 现金流表 1,667', '#' + change['new_target_block_id'] + '--r25-c3')
        fix_status = '<h3>本轮已修复 / Fixed in this iteration</h3><p>同一个原网页锚点 <code>f-313</code>，现在回到所属表格。</p>' + \
            '<table><thead><tr><th>旧版 v0.1.7</th><th>新版 v0.1.8</th></tr></thead><tbody><tr><td>错位：' + old_target + \
            '</td><td>已修正：' + new_target + '</td></tr></tbody></table>' + \
            '<p>两公司原件和旧包保留；新旧正文与表格不变，新包在同环境重建一致。重复导航和 TSMC Item 目录仍待修复。</p>' + \
            link(audit_path.with_suffix('.zh-CN.md'), '修复核验说明 / Verification') + ' · ' + link(audit_path, '全部锚点差异 / Changes')
    body = f'''<section id="overview"><p class="eyebrow">FIRST ITERATION · 2026-10-07</p><h1>一份财报，怎样变成可信数据？</h1>
      <p class="lead">先看到材料、步骤、产物和验收，再展开字段与证据。</p>
      <p class="notice">本页是验收交付：真实冻结原文 + 历史候选 + 明确标注的设计小样。不是完整财报已处理完毕。</p>
      <div class="scope"><b>AMD · FY2023 · 10-K</b><span>实际期末 2023-12-30</span><span>选择截止日 2026-10-04</span></div>
      <p>整体核查另含 TSMC FY2023 20-F。当前先修原文定位；结构化整文提取、精编执行器与新 Query 评测继续分项推进。</p>
      <div class="links">{link(REPO / "TODO.md", "任务进度 / TODO")}{link(REPO / "docs/design/data-agent-acceptance/first-iteration-v1.zh-CN.md", "技术方案与验收 / Plan")}{link(REPO / "docs/design/data-agent-acceptance/official-scope-v1.zh-CN.md", "官方材料范围 / Sources")}</div></section>
    <section id="process"><h2>处理过程 <small>Processing</small></h2><p>这是拟议的完整流程；各步已有能力与缺口分别列明。</p>
      <ol class="steps">
       <li><b>01 获取并冻结</b><span>程序：原件、身份、版本、哈希。已有年度材料；新增角色与渠道覆盖待补。</span></li>
       <li><b>02 保真拆分</b><span>程序：段落、表格、单元格、图片引用。HTML 已有；图片未 OCR。</span></li>
       <li><b>03 标记噪声，核对目录</b><span>程序为主：导航、正文、表格上下文、位置。保留原件；重复导航与 TSMC Item 仍有缺口。</span></li>
       <li><b>04 按产物加工</b><span>模型：抽取事实、忠实精编、业务关系；程序负责范围和执行。历史局部提取已跑，完整产物未齐。</span></li>
       <li><b>05 分层核验</b><span>程序：Schema、引用、单位、范围；内容核验：真实性、限定、遗漏。结构通过不等于内容正确。</span></li>
       <li><b>06 按问题查找</b><span>模型选数据与工具，系统执行和回读；回答带片段、范围和缺口。独立评价 Query 质量。</span></li>
      </ol></section>
    <section id="raw"><h2>原文与表格 <small>Source & tables</small></h2><span class="status">真实解析产物 / Frozen output</span>
      <p>用来核对“原话是什么、数字在表格哪里”。</p><blockquote>{escape(selected[1]['text'])}</blockquote>
      <p>{link(PACKAGE / "document.html", "AMD 原文第 3 页 · Data Center 段", "#"+selected[1]['block_id'])}</p>
      <table><thead><tr><th>原表行</th><th>实际列头</th><th>值（百万）</th></tr></thead><tbody><tr><td>Net cash provided by operating activities</td><td>December 30, 2023</td><td>1,667</td></tr></tbody></table>
      <p>{link(PACKAGE / "document.html", "定位到现金流单元格 / Open cell", "#block-000686-a6e8806b--r25-c3")}。币种另外核对原件 inline fact 的 unitRef=usd、scale=6。</p>
      {details('<p>按显式来源搜索，再读取 block；表格同时读取行名、列头、单位和脚注。表格坐标为零基，不是原文页码。</p>'+pretty({"source_snapshot_id": SID,"block_id": selected[1]['block_id'],"text_hash":selected[1]['text_hash'],"cashflow_cell":{"block_id":"block-000686-a6e8806b","row":25,"column":3}})+link(OUT/'schemas/blocks.schema.json','现有块 Schema'))}</section>
    <section id="facts"><h2>结构化事实 <small>Structured facts</small></h2><span class="status">历史真实候选 / Historical candidate</span>
      <p>用来按公司、指标、期间和口径精确取数，再做可核验计算。</p>
      <p class="number">1,667 <small>百万美元 · 经营现金流</small></p><p>实际期间：2023-01-01 — 2023-12-30。规范化存储：1,667,000,000 USD。</p>
      <p class="notice">来自历史真实提取，仍为 candidate。当前新 prepare 的数值库有适配缺口；展示历史候选不代表新库已补齐。</p>
      {details('<p>通过显式版本数据集的受约束记录查询读取；核对期间、主体、单位、口径和证据。查询接口不向模型开放任意写库。</p>'+pretty({k:record[k] for k in ('record_id','entity_id','metric_id','period','value_decimal','unit','accounting_basis','source_snapshot_id','status')})+link(RECORDS,'历史完整候选')+' · '+link(OUT/'schemas/numeric-fact.schema.json','现有事实 Schema'))}</section>
    <section id="brief"><h2>精编文档 <small>Condensed report</small></h2><span class="status draft">设计小样 · 局部 / Draft · partial</span>
      <p>用来连续阅读，忠实压缩原文；这一小样由人工组织，未经模型执行，只覆盖业务说明的六个块。</p>
      {''.join('<p>'+escape(s['zh'])+'</p>' for s in brief['sentences'])}
      <details><summary>English sample</summary>{''.join('<p>'+escape(s['en'])+'</p>' for s in brief['sentences'])}</details>
      {details('<p>按章节全文检索/读取，再沿每句引用回原文。“主要包括”的限定必须保留；风险、财务与附注不在本样例范围。拟议 Schema 只用于这份设计例，生产执行器未完成。</p>'+pretty(brief)+link(OUT/'schemas/brief-example.schema.json','拟议小样 Schema'))}</section>
    <section id="map"><h2>公司业务图 <small>Business map</small></h2><span class="status draft">设计小样 · 局部 / Draft · partial</span>
      <p>人工按现有 BusinessMap 契约填写；尚未接通这份材料的生产生成流程。</p>
      <div class="map" aria-label="Data Center is reported under AMD; its product list includes AI accelerators."><b>Data Center</b><span>作为可报告分部披露于 →</span><b>AMD</b></div>
      <p>Data Center 的原文产品列举包含 <b>AI accelerators</b>；没有在这段证据中补写客户、重要性排名或增长原因。</p>
      {details('<p>读取 BusinessMap 的 businesses、relationships、unknowns、evidence。关系沿用 reported_under，方向为分部 → 公司；产品沿用 products_services 字段。小样的块序号映射不是通用生产适配器。</p>'+pretty(graph)+link(OUT/'schemas/business-map.schema.json','现有业务图 Schema'))}</section>
    <section id="index"><h2>目录与索引 <small>Index</small></h2><span class="status">真实解析产物 / Frozen output</span>
      <p>先定位章节，再读取正文。目录本身不能支持业务结论。</p><div class="map"><b>PART I</b><span>→</span><b>BUSINESS</b><span>→ 块 40–217 →</span><b>Data Center · 块 73</b></div>
      {details('<p>按 source_snapshot_id 选择索引，查找节点，再按 start/end block 回读。PageIndex 是待评估的导航方案，尚未替换现有索引。</p>'+pretty(node)+link(OUT/'schemas/index.schema.json','现有索引 Schema'))}</section>
    <section id="acceptance"><h2>怎样判断做对了 <small>Acceptance</small></h2>
      <table><thead><tr><th>检查</th><th>具体预期</th><th>当前结果</th></tr></thead><tbody>
       <tr><td>真实小样与来源</td><td>来源哈希、原句、表格值、币种缩放和 Schema 可核对</td><td>本地检查通过；不等于全文语义验收</td></tr>
       <tr><td>锚点定位</td><td>f-313 回到块 686；空导航、隐藏锚点、重复 ID 等边界分别验证</td><td>见独立修复记录</td></tr>
       <tr><td>精编与业务图</td><td>保留主要包括、All Other 限定；不编客户和因果</td><td>设计例已给出；未运行生产生成器</td></tr>
       <tr><td>Query 专题题集</td><td>四分部及 All Other；缺来源/缺范围如实报告</td><td>标准已定义；新模型 benchmark 未运行</td></tr>
       <tr><td>全文完整性</td><td>逐章、表格、脚注与图片分别核查；遗漏单独计分</td><td>结构诊断已做；整文语义核验未完成</td></tr>
      </tbody></table>{fix_status}<div class="links">{audit_link}{link(OUT/'delivery-check.json','小样核验 / Checks')}{link(OUT/'product-samples.json','完整样例 / Data')}</div>
      <p>模型稳定性比较事实一致、引用完整、限定保留、失败率及总成本，不要求每次正文逐字相同。</p>
      <p>页面已生成，来源和链接按程序核对；浏览器视觉检查未执行，实际阅读效果由用户评审。</p></section>
    <section id="evidence"><h2>逐段证据 <small>Evidence</small></h2><ul class="evidence">{evidence}</ul>
      <details><summary>来源与版本 / Provenance</summary>{pretty(sample['scope'])}{pretty(sample['source_files'])}</details></section>'''
    nav = [('overview','本轮交付 / Overview'),('process','处理步骤 / Process'),('raw','原文表格 / Source'),('facts','结构化事实 / Facts'),('brief','精编文档 / Brief'),('map','业务图 / Map'),('index','目录索引 / Index'),('acceptance','验收 / Acceptance'),('evidence','逐段证据 / Evidence')]
    css = '''*{box-sizing:border-box}body{margin:0;background:#FAF8F4;color:#26231F;font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}a{color:#855034;text-underline-offset:3px}header{height:58px;border-bottom:1px solid #E5E0D7;padding:14px 24px;display:flex;justify-content:space-between;background:#fff}header span{color:#6B655D;font-size:13px}.workspace{height:calc(100dvh - 58px);display:grid;grid-template-columns:238px minmax(0,1fr)}aside{overflow:auto;border-right:1px solid #E5E0D7;padding:22px 16px}nav a{display:block;padding:8px 10px;text-decoration:none;color:inherit;border-radius:6px}nav a:hover,nav a:focus-visible{background:#f0e9e2}main{overflow:auto;scroll-behavior:smooth;padding:0 42px 64px}section{max-width:880px;margin:auto;padding:30px 0;border-bottom:1px solid #E5E0D7;scroll-margin-top:12px}h1{font-size:28px;line-height:1.4;margin:8px 0 12px}h2{font-size:21px;margin:0 0 14px}h2 small,.number small{font-size:14px;font-weight:400;color:#6B655D}.eyebrow{font-size:12px;color:#6B655D;letter-spacing:.09em}.lead{font-size:18px}.notice{padding:12px 16px;background:#f1ece4;border-radius:8px}.scope,.links,.map{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.scope span{color:#6B655D}.links{margin:18px 0}.links a{font-size:14px}.steps{padding-left:26px}.steps li{margin:15px 0}.steps b,.steps span{display:block}.steps span{color:#6B655D}.status{display:inline-block;font-size:12px;padding:3px 8px;background:#e9efea;border-radius:5px}.draft{background:#f2e8da}.number{font-size:32px;margin:16px 0;font-variant-numeric:tabular-nums}blockquote{margin:16px 0;padding:16px;background:white;border-left:3px solid #b9ab9e}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:11px 9px;text-align:left;border-bottom:1px solid #E5E0D7;vertical-align:top}th{font-weight:600;background:#f4f0e9}.map{background:#fff;padding:18px;border:1px solid #E5E0D7;border-radius:8px}.map b{padding:5px 8px;background:#f4f0e9}details{margin:16px 0;padding:12px 14px;background:white;border:1px solid #E5E0D7;border-radius:7px}summary{cursor:pointer;font-weight:500}pre{max-height:430px;overflow:auto;font-size:12px;line-height:1.65;background:#f6f4f0;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere}.evidence{padding-left:22px}.evidence li{margin:20px 0}.evidence p{font-family:Georgia,serif;font-size:16px}a:focus-visible,summary:focus-visible{outline:2px solid #855034;outline-offset:3px}@media(max-width:780px){.workspace{grid-template-columns:185px minmax(0,1fr)}main{padding:0 20px 40px}nav a{font-size:13px}h1{font-size:24px}}@media(prefers-reduced-motion:reduce){main{scroll-behavior:auto}}'''
    doc = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Data Agent · 首批产物与验收</title><style>'+css+'</style><header><b>UTEKI · Data Agent</b><span>本地验收交付 / Local acceptance</span></header><div class="workspace"><aside><nav aria-label="验收目录">'+''.join(f'<a href="#{i}">{label}</a>' for i,label in nav)+'</nav></aside><main>'+body+'</main></div></html>'
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(doc)


if __name__ == '__main__':
    build()
