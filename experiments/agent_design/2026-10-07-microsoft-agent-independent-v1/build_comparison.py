#!/usr/bin/env python3
"""Read-only comparison renderer. Neither this module nor reference data enter model input.

All run/page paths must be explicit. A failed candidate never borrows a reference
graph. The optional review binds to both exact BusinessMap hashes.
"""
import argparse
from decimal import Decimal
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, unquote, urlsplit

from lxml import html as H

ROOT = Path(__file__).resolve().parents[3]
VIEW_FILE = ROOT / 'experiments/agent_design/2026-10-07-microsoft-clean-reextract-v1/build_view.py'
spec = importlib.util.spec_from_file_location('frozen_business_view', VIEW_FILE)
view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(view)
esc = lambda value: html.escape(str(value), quote=True)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda path: json.loads(path.read_text())


def selected(path, *, file=False):
    path = path.resolve()
    if not path.is_relative_to(ROOT) or (file and not path.is_file()):
        raise ValueError('explicit_project_path_required: ' + str(path))
    return path


def href(path, output, fragment=''):
    return quote(os.path.relpath(path, output), safe='/') + ('#' + quote(fragment, safe='') if fragment else '')


def link(label, path, output, fragment=''):
    return '<a href="' + esc(href(path, output, fragment)) + '">' + esc(label) + '</a>'


def load_validated(run, page, output, prefix):
    data, packet, result, mapping, code, paths, binding, evidence, _ = view.load(run, output, None)
    all_graph = view.graph_variants(data, code, mapping)[0]
    code, mapping = all_graph['code'], all_graph['view']
    verification = read(selected(page / 'verification.json', file=True))
    if verification['binding'] != binding:
        raise ValueError('page_run_binding_mismatch')
    code_path = selected(page / 'assets/business-all.mmd', file=True)
    svg_path = selected(page / 'assets/business-all.svg', file=True)
    if code_path.read_text() != code or verification['files']['all_svg'] != sha(svg_path):
        raise ValueError('page_diagram_mismatch')
    svg = view.namespaced_svg(svg_path.read_text(), mapping, prefix)
    return {'data': data, 'packet': packet, 'result': result, 'mapping': mapping,
            'binding': binding, 'svg': svg, 'page': page, 'run': run, 'prefix': prefix,
            'semantic': verification['semantic_acceptance'],
            'mode': result.get('execution_mode') or ('independent_initial' if verification.get('independent_execution_mode') == 'independent_generation_with_bounded_self_revision' and verification.get('extraction_attempts') == 1 else 'not_recorded')}


def panel(candidate, title, description, output):
    data, prefix = candidate['data'], candidate['prefix']
    diagram = candidate['svg']
    count = f"{len(data['businesses'])} 个节点 / nodes · {len(data['relationships'])} 条关系 / relations"
    return ('<article><div class="panel-heading"><h2>' + esc(title) + '</h2><p>' + esc(description) + '</p>'
            + link('完整图与依据 / Details ↗', candidate['page'] / 'index.html', output, 'graph') + '</div>'
            + '<div class="standard-canvas"><div class="map-toolbar"><span>' + count + '</span><div>'
            + '<button id="map-fit-' + prefix + '" aria-pressed="false">适合宽度 / Fit</button>'
            + '<button id="map-original-' + prefix + '" aria-pressed="true">原始尺寸 / Original</button></div></div>'
            + '<div class="map-drawing" id="map-drawing-' + prefix + '" tabindex="0">' + diagram + '</div></div>'
            + '<div class="panel-foot"><p>Trace · <code>' + esc(candidate['result']['trace_id']) + '</code></p>'
            + '<p>' + link('原始产物 / BusinessMap', candidate['run'] / 'business_map.json', output) + ' · '
            + link('Mermaid', candidate['page'] / 'assets/business-all.mmd', output) + ' · '
            + link('请求 / Request', candidate['run'] / 'request.json', output) + '</p></div></article>')


def failure_panel(run, output, error):
    files = []
    if run:
        for name in ('result.json', 'failure.json', 'error.json', 'response.txt', 'response_metadata.json', 'request.json', 'manifest.json'):
            if (run / name).is_file():
                files.append(link(name, run / name, output))
    status = '待运行 / Pending' if run is None else '尚无可展示的合法候选 / No validated candidate'
    return ('<article><div class="panel-heading"><h2>B · Uteki Agent + Sonnet</h2><p>' + status
            + '</p></div><div class="empty"><p>' + esc(error) + '</p><p>此处只显示新运行的真实结果。没有候选时不借用参考图。</p>'
            + '<p>Only this run’s output is shown; no reference graph is substituted.</p><div class="links">'
            + ' · '.join(files) + '</div></div></article>')


def review_html(path, bindings, output, candidate_binding=None):
    if path is None:
        return '<p>语义差异待复核 / Semantic differences have not yet been reviewed.</p>', None
    doc = read(selected(path, file=True))
    if any(doc.get('bindings', {}).get(key) != value for key, value in bindings.items()):
        raise ValueError('comparison_review_hash_mismatch')
    if candidate_binding:
        for key in ('source_packet_sha256', 'request_sha256', 'skill_sha256'):
            if key in doc['bindings'] and doc['bindings'][key] != candidate_binding[key]:
                raise ValueError('comparison_review_input_mismatch')
        if 'candidate_trace_id' in doc['bindings'] and doc['bindings']['candidate_trace_id'] != candidate_binding['trace_id']:
            raise ValueError('comparison_review_trace_mismatch')
    rows = []
    for item in doc.get('checks', []):
        rows.append('<tr>' + ''.join('<td>' + esc(item.get(key, '')) + '</td>' for key in ('topic', 'status', 'reference', 'agent', 'evidence', 'note')) + '</tr>')
    return ('<p>' + esc(doc.get('summary', '')) + '</p><table><thead><tr>'
            + ''.join('<th>' + esc(label) + '</th>' for label in ('检查点 / Topic', '状态 / Status', '参考 / Reference', 'Agent', '依据 / Evidence', '说明 / Note'))
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table><p>' + link('完整差异复核 / Review', path, output) + '</p>'), sha(path)


STYLE = '''
:root{color-scheme:light;--line:#e5e0d7;--muted:#6b655d}*{box-sizing:border-box}body{margin:0;background:#faf8f4;color:#26231f;font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid var(--line);padding:12px 24px;display:flex;gap:16px;align-items:center;justify-content:space-between}main{padding:24px;max-width:2200px;margin:auto}h1{font-size:25px;margin:0 0 8px}h2{font-size:18px;margin:0 0 8px}p{margin:8px 0}a{color:#365e70;text-underline-offset:3px}.caption{color:var(--muted);font-size:12px}.notice{padding:12px 16px;background:#f2eee6;border-left:3px solid #bfa982;margin:16px 0}.comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}article{background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}.panel-heading,.panel-foot{padding:16px 18px}.panel-heading p{color:var(--muted)}.panel-foot{font-size:12px;overflow-wrap:anywhere}.standard-canvas{border-left:0;border-right:0;border-radius:0}.map-drawing{height:580px;align-items:flex-start}.empty{padding:24px;min-height:580px;background:#faf8f4;overflow-wrap:anywhere}.links{display:flex;gap:12px;flex-wrap:wrap}section{margin:24px 0}table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-weight:600}code{font-size:12px;overflow-wrap:anywhere}details{margin:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.scroll{overflow:auto}@media(max-width:1050px){.comparison{grid-template-columns:minmax(0,1fr)}main{padding:16px}header{padding:12px 16px}}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference-run', type=Path, required=True)
    p.add_argument('--reference-page', type=Path, required=True)
    p.add_argument('--candidate-run', type=Path)
    p.add_argument('--candidate-page', type=Path)
    p.add_argument('--previous-agent-page', type=Path, help='Preserved independent initial version; never substitute its data for the selected candidate')
    p.add_argument('--execution-record', type=Path)
    p.add_argument('--initial-execution-record', type=Path, help='Required with a semantic self-review ledger to calculate task total once')
    p.add_argument('--review', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    output = selected(args.output)
    output.mkdir(parents=True, exist_ok=True)
    ref = load_validated(selected(args.reference_run), selected(args.reference_page), output, 'reference')
    agent, error = None, '独立执行尚未交付 / Independent run has not delivered a candidate.'
    if args.candidate_run:
        args.candidate_run = selected(args.candidate_run)
        if args.candidate_page is None:
            error = '新运行暂无已验证图页；请查看真实运行记录 / A verified diagram page is not available.'
        else:
            try:
                agent = load_validated(args.candidate_run, selected(args.candidate_page), output, 'agent')
            except (ValueError, KeyError, FileNotFoundError) as exc:
                error = '图页校验未通过 / Diagram verification failed: ' + str(exc)
    bindings = {'reference_business_map_sha256': ref['binding']['business_map_sha256'],
                'candidate_business_map_sha256': agent['binding']['business_map_sha256'] if agent else None}
    same_input = bool(agent and ref['binding']['source_packet_sha256'] == agent['binding']['source_packet_sha256'])
    review, review_sha = review_html(args.review, bindings, output, agent['binding'] if agent else None)
    rows = []
    for label, a, b in [
        ('范围 / Scope', ref['packet'].get('extraction_scope', {}).get('title', ''), agent['packet'].get('extraction_scope', {}).get('title', '') if agent else '未交付'),
        ('输入块 / Source blocks', len(ref['packet']['blocks']), len(agent['packet']['blocks']) if agent else '—'),
        ('模型 / Model', ref['result'].get('model'), agent['result'].get('model') if agent else '—'),
        ('模式 / Mode', ref['mode'], agent['mode'] if agent else '—'),
        ('结构校验 / Protocol', ref['result'].get('validation'), agent['result'].get('validation') if agent else '未通过 / 未交付'),
        ('内容复核 / Semantics', ref['semantic'], agent['semantic'] if agent else '待评估')]:
        rows.append('<tr>' + ''.join('<td>' + esc(value) + '</td>' for value in (label, a, b)) + '</tr>')
    scripts = []
    for item in (ref, agent):
        if not item:
            continue
        prefix = item['prefix']
        js = (view.PROFILE_DIR / 'canvas.js').read_text()
        for element in ('map-drawing', 'map-fit', 'map-original'):
            js = js.replace("'" + element + "'", "'" + element + '-' + prefix + "'")
        scripts.append(js)
        # Both graphs keep their own node/edge IDs. Navigation targets their own detail page.
        detail_url = href(item['page'] / 'index.html', output)
        detail_dom = H.fromstring((item['page'] / 'index.html').read_bytes())
        svg_dom = H.fromstring(item['svg'])
        for element in svg_dom.xpath('//*[@data-node-key or @data-relation-key]'):
            fragment = ('node-' + element.attrib['data-node-key']) if 'data-node-key' in element.attrib else ('edge-' + element.attrib['data-relation-key'])
            if not detail_dom.xpath('//*[@id=$id]', id=fragment):
                raise ValueError('diagram_detail_mapping_missing: ' + fragment)
        scripts.append('(()=>{const url=' + json.dumps(detail_url) + ';document.querySelectorAll("#map-drawing-' + prefix + ' [data-node-key],#map-drawing-' + prefix + ' [data-relation-key]").forEach(el=>{const fragment=el.dataset.nodeKey?"node-"+el.dataset.nodeKey:"edge-"+el.dataset.relationKey;el.setAttribute("tabindex","0");el.setAttribute("role","link");el.addEventListener("click",()=>location.href=url+"#"+fragment);el.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();location.href=url+"#"+fragment}})})})();')
    execution = ''
    if args.execution_record:
        record_path = selected(args.execution_record, file=True)
        record = read(record_path)
        execution = '<p>' + link('执行过程与费用 / Execution and cost', record_path, output) + '</p>'
        if record.get('schema_version') == 'independent-business-run-v1':
            if agent and (selected(ROOT / record['candidate_path']) != args.candidate_run
                          or record['source_packet_sha256'] != agent['binding']['source_packet_sha256']):
                raise ValueError('execution_record_candidate_mismatch')
            execution += ('<p>新任务 / New task · ' + esc(record['status']) + ' · ' + str(len(record.get('attempts', [])))
                          + ' 次尝试 / attempts · 累计估算 $' + esc(record['estimated_spent_usd']) + ' / 上限 $'
                          + esc(record['budget_limit_usd']) + '。含失败用量；实际账单未核对。历史参考费用另计。</p>')
        elif record.get('schema_version') == 'business-semantic-self-review-v1':
            if not args.initial_execution_record:
                raise ValueError('initial_ledger_required_for_self_review_cost')
            initial_path = selected(args.initial_execution_record, file=True)
            initial = read(initial_path)
            if (not agent or selected(ROOT/record['candidate_path']) != args.candidate_run
                    or record['input_run'] != initial['candidate_path']
                    or record['source_packet_sha256'] != agent['binding']['source_packet_sha256']):
                raise ValueError('self_review_execution_record_mismatch')
            total = Decimal(initial['estimated_spent_usd']) + Decimal(record['estimated_spent_usd'])
            calls = len(initial['attempts']) + record['budget']['requests']
            execution += ('<p>Agent 首次生成 → 模型自检 → 自动修订 / Generation → self-review → revision · '
                          + str(calls) + ' 次调用 · 本任务累计估算 $' + str(total) + '（首次 $'
                          + esc(initial['estimated_spent_usd']) + ' + 自检/修订共享累计 $' + esc(record['estimated_spent_usd'])
                          + '）。实际账单未核对。模型自检不等于独立验收；下面另列运行后原文复核。</p><p>'
                          + link('首次生成账本 / Initial ledger', initial_path, output) + '</p>')
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Microsoft · Agent 独立执行对照</title><style>'
            + (view.PROFILE_DIR / 'canvas.css').read_text() + STYLE + '</style></head><body><header><strong>Uteki · Agent 独立执行对照</strong><span class="caption">Reference comparison · 非严格 A/B</span></header><main>'
            + '<h1>同一份财报材料，Agent 能独立做到什么？</h1><p>参考版保留，独立版单独交付。两边用相同的 Mermaid 渲染基线。</p>'
            + '<div class="notice">参考版经过 Sonnet 多轮生成与 Codex 原文审阅、工程修复。独立版由 Uteki Agent 调用 Sonnet 执行；开发和运行后评审由 Codex 完成。参考答案仅供运行后比较，不能进入新运行的模型输入。<br>Reference includes reviewed revisions. This is a method comparison, not a controlled model A/B.</div>'
            + '<p>' + ('已核对：输入包 hash 相同。' if same_input else '新候选输入包尚未与参考核对，或输入包不同。') + ' 输入范围为已选财报章节，不代表整份财报或全部产品覆盖。属性补全另行处理。</p>'
            + '<p>' + link('固定原文索引 / Frozen source index', ref['page'] / 'source-index.html', output) + '</p>'
            + ('<div class="notice"><strong>运行后内容复核 / Post-run source review</strong><p>' + esc(read(args.review).get('summary', '')) + '</p></div>' if args.review else '')
            + ('<p>' + link('B1 · 首次独立生成（保留原版） / Initial Agent version', selected(args.previous_agent_page / 'index.html', file=True), output) + '</p>' if args.previous_agent_page else '')
            + '<div class="comparison">' + panel(ref, 'A · 已审阅参考版 / Reviewed reference', '多轮模型生成 + Codex 审阅与工程恢复；用户认可图的表达。', output)
            + (panel(agent, 'B · Uteki Agent + Sonnet', '新运行独立产物；结构通过、语义正确和稳定性分别判断。', output) if agent else failure_panel(args.candidate_run, output, error))
            + '</div><section><h2>范围与执行 / Scope and execution</h2><div class="scroll"><table><thead><tr><th>项目</th><th>A · Reference</th><th>B · Agent</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' + execution
            + '</section><section><h2>差异复核 / Reviewed differences</h2><p>节点数量和名称不直接作为分数；核对业务覆盖、整体与子集、关系含义和原文依据。</p><div class="scroll">' + review + '</div></section>'
            + '<footer class="caption">图的大小不表示财务权重。实线表示明示、虚线表示推断。渲染与链接已做静态校验；本轮未进行浏览器视觉验收。</footer></main><script>' + '\n'.join(scripts) + '</script></body></html>')
    (output / 'index.html').write_text(page)
    tree = H.fromstring(page)
    checked = 0
    for url in tree.xpath('//@href'):
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            continue
        target = (output / unquote(parts.path)).resolve() if parts.path else output / 'index.html'
        if not target.is_file():
            raise ValueError('broken_local_link: ' + url)
        if parts.fragment and target.suffix == '.html':
            if not H.fromstring(target.read_bytes()).xpath('//*[@id=$id]', id=unquote(parts.fragment)):
                raise ValueError('broken_fragment: ' + url)
        checked += 1
    verification = {'schema_version': 'business-comparison-page-v1', 'bindings': bindings,
                    'candidate_display': 'validated_graph' if agent else 'no_validated_graph',
                    'same_source_packet': same_input, 'comparison_kind': 'reference_not_strict_ab',
                    'reference_binding': ref['binding'], 'candidate_binding': agent['binding'] if agent else None,
                    'review_sha256': review_sha, 'model_calls': 0, 'browser_visual_review': 'not_performed',
                    'local_links_checked': checked, 'html_sha256': sha(output / 'index.html')}
    (output / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(verification, ensure_ascii=False))


if __name__ == '__main__':
    main()
