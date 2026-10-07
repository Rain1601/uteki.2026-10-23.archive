#!/usr/bin/env python3
"""Render an explicitly selected, real BusinessMap run; never infer business edges.

Prepare with --run RUN --output PAGE_DIR; render every assets/*.mmd using the
shared Mermaid profile, then repeat with --with-svg. Optional --review must bind
to this exact run. No model calls; historical candidates remain untouched.
"""
import argparse
from collections import Counter
import copy
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

from lxml import html as H

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from uteki.presentation.business_map_view import BASIS, KIND, RELATION, mermaid, inline_svg
from uteki.agents.runtime.strict_json import parse_json_object
from uteki.presentation.business_overview import overview_selection

PROFILE_DIR = ROOT / 'skills/uteki-business-diagrams/assets'
esc = lambda value: html.escape(str(value), quote=True)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda path: parse_json_object(path.read_text())
norm = lambda value: ' '.join(value.split())


def local(path):
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('local_artifact_missing_or_outside_project: ' + str(path))
    return path


def href(path, output, fragment=''):
    return quote(os.path.relpath(path, output), safe='/') + ('#' + quote(fragment, safe='') if fragment else '')


def link(label, url):
    return '<a href="' + esc(url) + '">' + esc(label) + '</a>'


def load(run, output, review_path):
    paths = {name: local(run / name) for name in ('business_map.json', 'source_packet.json', 'result.json', 'skill.md', 'request.json', 'manifest.json', 'evidence.html')}
    for name in ('protocol-projection.json', 'configuration.json', 'response.txt', 'response_metadata.json'):
        if (run / name).is_file():
            paths[name] = local(run / name)
    data, packet, result = (read(paths[name]) for name in ('business_map.json', 'source_packet.json', 'result.json'))
    code, view = mermaid(data)
    meta = data['metadata']
    patched = result.get('execution_mode') == 'business_critic_revision'
    validation = result.get('contract_validation') if patched else result.get('validation')
    if result.get('status') != 'candidate' or validation != 'passed':
        raise ValueError('validated_candidate_required')
    if meta.get('extraction_method') != 'system_agent':
        raise ValueError('real_system_agent_run_required')
    for key in ('company_id', 'document_id'):
        if data[key] != packet[key] or result[key] != packet[key]:
            raise ValueError('scope_mismatch')
    if meta['period_end'] != packet['period_end'] or result['period_end'] != packet['period_end']:
        raise ValueError('period_mismatch')
    if meta['trace_id'] != result['trace_id']:
        raise ValueError('trace_mismatch')
    for key, name in [('source_packet_sha256', 'source_packet.json'), ('skill_sha256', 'skill.md')]:
        if meta[key] != sha(paths[name]) or result[key] != meta[key]:
            raise ValueError('input_fingerprint_mismatch')
    if result['request_sha256'] != sha(paths['request.json']):
        raise ValueError('request_fingerprint_mismatch')
    manifest = read(paths['manifest.json'])
    if result.get('execution_mode') != manifest.get('execution_mode'):
        raise ValueError('execution_mode_mismatch')
    if result.get('execution_mode') in {'reviewed_graph_revision', 'typed_graph_completion'}:
        request = read(paths['request.json'])
        payload = parse_json_object(request['messages'][0]['content'])
        if (set(payload) != {'frozen_source_packet', 'prior_candidate', 'review_feedback'}
                or payload['frozen_source_packet'] != packet
                or not result.get('parent_trace_id') or not result.get('parent_response_sha256')):
            raise ValueError('reviewed_revision_input_mismatch')
    if patched:
        # This receipt version publishes hashes in the observation record.
        # Read that immutable publication instead of rewriting the run receipt.
        from uteki.agents.business_map.coverage_run import verify_published_artifacts
        verify_published_artifacts(root=ROOT, observation_root=ROOT/'data/agent_observability/local',
            stage=run.resolve(), trace_id=result['trace_id'],
            relative_paths=['business_map.json','evidence.html','draft.json','diff.json','result.json'])
    else:
        for name in ('business_map.json', 'evidence.html'):
            if result['artifacts_sha256'][name] != sha(paths[name]):
                raise ValueError('artifact_fingerprint_mismatch')
    if meta.get('extraction_scope') != packet.get('extraction_scope') or not packet.get('extraction_scope'):
        raise ValueError('extraction_scope_mismatch')
    paths['source'] = local(packet['source_local_path'])
    raw = paths['source'].read_bytes()
    if paths['source'].suffix == '.gz':
        raw = gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest() != packet['source_sha256'] or meta['source_sha256'] != packet['source_sha256']:
        raise ValueError('original_source_hash_mismatch')
    source = H.fromstring(raw)
    tree = source.getroottree()
    source_nodes = {tree.getpath(node): node for node in source.iter()}
    blocks = {block['id']: block for block in packet['blocks']}
    if len(blocks) != len(packet['blocks']):
        raise ValueError('duplicate_block_id')
    for block in blocks.values():
        node = source_nodes.get(block['source_dom_path'])
        if node is None or norm(''.join(node.itertext())) != block['text'] or hashlib.sha256(block['text'].encode()).hexdigest() != block['text_sha256']:
            raise ValueError('source_block_mismatch: ' + block['id'])
    evidence_dom = H.fromstring(paths['evidence.html'].read_bytes())
    evidence = {}
    for item in data['evidence']:
        block = blocks[item['id']]
        loc = meta['evidence_locators'][item['id']]
        target = local(loc['local_path'])
        hits = evidence_dom.xpath('//*[@id=$value]', value=loc['fragment'])
        if (target != paths['evidence.html'] or item['support'] != block['text'] or item['text_hash'] != block['text_sha256']
                or loc['source_dom_path'] != block['source_dom_path'] or loc['exact_quote'] != block['text']
                or len(hits) != 1 or block['text'] not in norm(' '.join(hits[0].itertext()))):
            raise ValueError('evidence_target_mismatch')
        evidence[item['id']] = href(target, output, loc['fragment'])
    binding = {key: meta[key] for key in ('trace_id', 'source_packet_sha256', 'skill_sha256')}
    binding.update({key: sha(paths[name]) for key, name in [('business_map_sha256', 'business_map.json'), ('result_sha256', 'result.json'), ('request_sha256', 'request.json')]})
    review = None
    if review_path:
        paths['review'] = local(review_path)
        review = read(paths['review'])
        if any(review.get('binding', {}).get(key) != value for key, value in binding.items()):
            raise ValueError('review_not_bound_to_this_run')
        for check in review['checks']:
            if check['status'] not in {'pass', 'needs_improvement', 'gap'} or not set(check.get('source_block_ids', [])) <= blocks.keys():
                raise ValueError('review_check_mismatch')
    return data, packet, result, view, code, paths, binding, evidence, review


def graph_variants(data, code, view, overview=False):
    """Projection only: select reported membership/containment, never make edges."""
    parents = {node['id']: set() for node in data['businesses']}
    children = {node['id']: set() for node in data['businesses']}
    for edge in data['relationships']:
        if edge['basis'] != 'unknown' and edge['kind'] in {'part_of', 'reported_under'}:
            parents[edge['source_id']].add(edge['target_id'])
            children[edge['target_id']].add(edge['source_id'])
    def closure(seeds, adjacency):
        seen = set(seeds)
        todo = list(seeds)
        while todo:
            for item in adjacency[todo.pop()]:
                if item not in seen:
                    seen.add(item)
                    todo.append(item)
        return seen
    roots = [node['id'] for node in data['businesses'] if node['kind'] == 'company']
    if len(roots) != 1:
        raise ValueError('one_company_root_required')
    reached = closure(roots, children)
    unplaced = set(view['ids']) - reached
    groups = [('all', '完整对象与关系 / All objects and relations', set(view['ids']))]
    if overview:
        selection = overview_selection(data)
        groups.insert(0, ('overview', '业务总览 / Overview', set(selection['selected_node_ids'])))
    for node in data['businesses']:
        if node['kind'] == 'reportable_segment':
            selected = closure([node['id']], children) | closure([node['id']], parents)
            groups.append(('segment-' + view['ids'][node['id']], node['name'], selected))
    variants = []
    for key, title, selected in groups:
        projected = copy.deepcopy(view)
        projected['ids'] = {nid: val for nid, val in view['ids'].items() if nid in selected}
        projected['labels'] = {nid: val for nid, val in view['labels'].items() if nid in selected}
        projected['edges'] = [copy.deepcopy(edge) for edge in view['edges'] if edge['domain_source'] in selected and edge['domain_target'] in selected]
        projected['unresolved'] = [copy.deepcopy(edge) for edge in view['unresolved'] if edge['domain_source'] in selected and edge['domain_target'] in selected]
        node_keys = set(projected['ids'].values())
        lines = []
        orphan_lines = []
        for line in code.splitlines():
            node_match = re.match(r'^  (N\d+)\[', line)
            edge_match = re.match(r'^  (N\d+) (?:-->|-\.->)', line)
            if node_match:
                if node_match[1] in node_keys:
                    nid = next(nid for nid, token in view['ids'].items() if token == node_match[1])
                    (orphan_lines if key == 'all' and nid in unplaced else lines).append(line)
                continue
            if edge_match:
                continue
            lines.append(line)
        if orphan_lines:
            lines.extend(['  subgraph Unplaced["归属待核验 / Placement unresolved"]', *orphan_lines, '  end', '  style Unplaced fill:#fcf8ef,stroke:#c7ad89,stroke-dasharray:4 3'])
        for edge in projected['edges']:
            edge['label'] = {'part_of': '包含', 'reported_under': '报告中列示', 'supports': '支撑'}[edge['kind']]
            arrow = '-->' if edge['basis'] == 'explicit' else '-.->'
            lines.append(f'  {edge["source"]} {arrow}|"{edge["label"]}"| {edge["target"]}')
        variants.append({'key': key, 'title': title, 'code': '\n'.join(lines) + '\n', 'view': projected, 'unplaced': sorted(unplaced & selected)})
    return variants


def execution_notice(result, paths, output):
    mode = result.get('execution_mode')
    if mode in {'reviewed_graph_revision', 'typed_graph_completion'}:
        parent_url = 'http://127.0.0.1:8765/agent-runs?run=' + quote(result['parent_trace_id'], safe='')
        title = '审阅后的模型补全 / Reviewed graph completion' if mode == 'typed_graph_completion' else '经原文复核后的模型修订 / Reviewed graph revision'
        explanation = ('本次模型读取冻结原文、上一版候选及审阅反馈，补全指定的描述、引用、节点与关系；程序合并返回字段，并根据已有摘录整理引用索引。'
            if mode == 'typed_graph_completion' else '本次模型请求同时读取冻结原文、上一版候选及审阅反馈，并可重新调整节点与关系。')
        recovery = ''
        if result.get('protocol_recovery'):
            response_trace = result.get('actual_model_response_trace_id')
            recovery = '<p class="caption">工程恢复 / Protocol recovery · ' + esc(result['protocol_recovery'])
            if result.get('model_calls_in_this_trace') == 0:
                recovery += '。此产物整理阶段没有新增模型请求。'
            if response_trace:
                recovery += ' ' + link('实际模型响应 / Model response trace', 'http://127.0.0.1:8765/agent-runs?run=' + quote(response_trace, safe=''))
            if 'protocol-projection.json' in paths:
                recovery += ' · ' + link('具体修改记录 / Exact changes', href(paths['protocol-projection.json'], output))
            recovery += '</p>'
        return ('<div class="notice"><strong>' + title + '</strong><p>' + explanation +
            '这是带反馈的修订结果，不能视为独立提取或一次成功。此前失败记录保持原状。</p><p class="caption">'
            + link('上一轮运行 / Parent run', parent_url) + ' · '
            + link('本轮实际请求 / Actual request', href(paths['request.json'], output)) + '</p>' + recovery + '</div>')
    if mode:
        return '<p class="caption">记录的执行模式 / Recorded execution mode · ' + esc(mode) + '</p>'
    return '<p class="caption">本次请求与执行记录见下方文件；是否首次成功与内容验收分别判断。See the recorded request and result.</p>'


def namespaced_svg(raw, view, namespace):
    """Validate exact source projection, then avoid duplicate IDs across views."""
    valid = inline_svg(raw, view)
    svg = ET.fromstring(valid)
    replacements = {el.attrib['id']: namespace + '-' + el.attrib['id'] for el in svg.iter() if 'id' in el.attrib}
    for el in svg.iter():
        for key, value in list(el.attrib.items()):
            if key == 'id':
                el.set(key, replacements[value])
            else:
                if key in {'aria-labelledby', 'aria-describedby'}:
                    value = ' '.join(replacements.get(token, token) for token in value.split())
                value = re.sub(r'url\(#([^)]*)\)', lambda m: 'url(#' + replacements.get(m[1], m[1]) + ')', value)
                if key.split('}')[-1] == 'href' and value.startswith('#'):
                    value = '#' + replacements.get(value[1:], value[1:])
                el.set(key, value)
        if el.tag.split('}')[-1] == 'style' and el.text:
            # Mermaid CSS is scoped to its SVG root. Preserve that scoping after ID namespacing.
            root_id = next(iter(replacements))
            el.text = el.text.replace('#' + root_id, '#' + replacements[root_id])
    return ET.tostring(svg, encoding='unicode')


STYLE = '''
:root{color-scheme:light;--ink:#292722;--muted:#6b655d;--line:#e4dfd5;--accent:#355d9f}*{box-sizing:border-box}body{margin:0;background:#faf8f4;color:var(--ink);font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",Arial,sans-serif}a{color:var(--accent);text-underline-offset:3px}header{height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid var(--line);background:white}header small,.caption,.muted{color:var(--muted);font-size:12px}.workspace{display:grid;grid-template-columns:174px minmax(0,1fr);height:calc(100dvh - 52px)}aside{border-right:1px solid var(--line);padding:20px 12px;overflow:auto}aside a{display:block;padding:8px;text-decoration:none}main{overflow:auto;padding:22px 26px;scroll-padding:20px}h1{font-size:24px;line-height:1.4;margin:0 0 8px}h2{font-size:19px;margin:0 0 12px}p{margin:8px 0 12px}section{padding-bottom:24px;margin-bottom:24px;border-bottom:1px solid var(--line)}.source-links{display:flex;gap:10px 20px;flex-wrap:wrap;padding:12px 0;margin-bottom:8px}.view-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 12px}.view-tabs button{font:inherit;border:1px solid var(--line);padding:8px 12px;background:white;border-radius:5px;cursor:pointer}.view-tabs button[aria-selected=true]{background:#263c46;color:white;border-color:#263c46}.view-panel[hidden]{display:none}.tag{display:inline-block;padding:1px 7px;border:1px solid var(--line);font-size:12px;border-radius:4px}.notice{border-left:3px solid #c0aa86;padding:6px 14px;background:#f4efe6}.map-drawing{height:540px;align-items:flex-start}.legend{display:flex;gap:18px;flex-wrap:wrap}.swatch{display:inline-block;width:25px;border-top:2px solid #9da79f;margin-right:6px;vertical-align:middle}.swatch.derived{border-top-style:dashed}details{padding:8px 0}summary{cursor:pointer}summary:hover{color:var(--accent)}.node-detail,.edge-detail{padding:12px 0;border-top:1px solid var(--line)}.node-detail:target,.edge-detail:target{background:#f1ede5}.claim{padding:8px 12px;margin:5px 0;background:white}.claim summary{font-size:12px;color:var(--muted)}.claim summary span{display:block;font-size:14px;color:var(--ink);padding-left:12px}blockquote{border-left:2px solid #b7c8c0;margin:8px 0;padding:5px 14px;white-space:pre-wrap;overflow-wrap:anywhere;background:#fbfcfa}code,pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.links{display:flex;gap:10px 18px;flex-wrap:wrap}.review-check{border-bottom:1px solid var(--line)}.count{font-variant-numeric:tabular-nums}.status{color:#6d614d}footer{font-size:12px;color:var(--muted)}@media(max-width:760px){.workspace{grid-template-columns:130px minmax(0,1fr)}main{padding:16px}.map-drawing{height:450px}header{padding:0 16px}header small{display:none}}
'''


def source_index(packet, output, original):
    rows = []
    for block in packet['blocks']:
        page = '报告页 / Report page ' + str(block['reported_page']) if block.get('reported_page') is not None else '页码未记录 / Page not recorded'
        rows.append('<article id="' + esc(block['id']) + '"><h2>' + esc(block['id']) + '</h2><p class="caption">' + esc(page + ' · ' + block.get('input_role', '')) + '</p><p>' + esc(' / '.join(block.get('section_path', []))) + '</p><blockquote>' + esc(block['text']) + '</blockquote><details><summary>固定定位 / Fixed locator</summary><code>' + esc(block['source_dom_path']) + '</code><p><code>' + esc(block['text_sha256']) + '</code></p></details></article>')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>固定段落索引 / Frozen source index</title><style>' + STYLE + 'body{padding:28px;max-width:1000px;margin:auto}article{padding:18px 0;border-top:1px solid #e4dfd5}article:target{background:#f1ede5}</style></head><body><h1>固定段落索引 / Frozen source index</h1><p>' + esc(packet['document_id'] + ' · ' + packet['extraction_scope']['title']) + '</p><p>' + link('返回业务图 / Map', 'index.html#graph') + ' · ' + link('官方原报告 / Official filing', packet['source_url']) + ' · ' + link('冻结原件 / Frozen original', href(original, output)) + '</p><p>按传入模型的原始顺序保留全部 ' + str(len(packet['blocks'])) + ' 块。这里只做空白规范化，块 ID、原文位置与哈希保持不变。Exact input blocks and fixed locators.</p>' + ''.join(rows) + '</body></html>'


CLASSIFICATION = {
    'input_not_covered': '本次输入未覆盖 / Outside model input',
    'not_disclosed': '选定范围未披露 / Not disclosed in reviewed scope',
    'grounded_inference': '有据推断 / Grounded inference',
    'extraction_omission': '提取遗漏 / Extraction omission',
    'needs_evidence': '需要补证 / More evidence needed',
}


def supplemental_index(review, supplemental_path, packet, output):
    """Supplemental evidence is review-only and never presented as model input."""
    if not supplemental_path:
        if review and any(check.get('supplemental_source_block_ids') for check in review['checks']):
            raise ValueError('supplemental_evidence_artifact_required')
        return None
    if review is None:
        raise ValueError('supplemental_requires_bound_review')
    artifact = local(supplemental_path)
    supplemental = read(artifact)
    if supplemental.get('purpose') != 'review_only_not_model_input':
        raise ValueError('supplemental_purpose_mismatch')
    index_path = local(supplemental['index_path'])
    if sha(index_path) != supplemental['index_sha256']:
        raise ValueError('supplemental_index_hash_mismatch')
    index = {item['block_id']: item for item in (parse_json_object(line) for line in index_path.read_text().splitlines() if line.strip())}
    wanted = {bid for check in review['checks'] for bid in check.get('supplemental_source_block_ids', [])}
    if not wanted <= index.keys():
        raise ValueError('unknown_supplemental_block')
    if wanted & {block['id'] for block in packet['blocks']}:
        raise ValueError('input_block_mislabeled_as_supplemental')
    source_path = local(packet['source_local_path'])
    raw = source_path.read_bytes()
    if source_path.suffix == '.gz':
        raw = gzip.decompress(raw)
    source = H.fromstring(raw)
    tree = source.getroottree()
    elements = {tree.getpath(element): element for element in source.iter()}
    rows = []
    for block in sorted((index[bid] for bid in wanted), key=lambda item: item['ordinal']):
        element = elements.get(block['dom_path'])
        if element is None or norm(''.join(element.itertext())) != block['text'] or hashlib.sha256(block['text'].encode()).hexdigest() != block['text_hash']:
            raise ValueError('supplemental_original_source_mismatch')
        rows.append('<article id="' + esc(block['block_id']) + '"><h2>' + esc(block['block_id']) + '</h2><p class="caption">报告页 / Report page ' + esc(block.get('reported_page', '未记录')) + '</p><blockquote>' + esc(block['text']) + '</blockquote><code>' + esc(block['dom_path']) + '</code></article>')
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>复核补证 / Review-only evidence</title><style>' + STYLE + 'body{padding:28px;max-width:1000px;margin:auto}article{padding:18px 0;border-top:1px solid #e4dfd5}article:target{background:#f1ede5}</style></head><body><h1>复核补证 / Review-only evidence</h1><p class="notice">以下片段来自同一冻结财报全文，是 Codex 在模型运行之后补查的材料。本轮模型没有读取这些片段，不能据此声称本轮已提取。Not part of this model request.</p><p>' + link('返回本轮复核 / Review', 'index.html#review') + ' · ' + link('完整搜索记录 / Search record', href(artifact, output)) + ' · ' + link('原始财报 / Filing', packet['source_url']) + '</p>' + ''.join(rows) + '</body></html>'
    path = output / 'supplemental-index.html'
    path.write_text(page)
    return {'artifact': artifact, 'page': path, 'count': len(wanted), 'index_sha256': supplemental['index_sha256']}


def details_html(data, packet, view, evidence, review, supplemental=None, graph_stage=False):
    names = {node['id']: node['name'] for node in data['businesses']}
    role_labels = {'application_platform': '应用平台 / Application platform', 'market': '市场 / Market', 'brand': '品牌 / Brand', 'operating_business': '经营业务 / Operating business', 'legal_entity': '法律实体 / Legal entity', 'offering_group': '产品服务组 / Offering group'}
    def refs(excerpts):
        return ''.join('<blockquote>' + esc(item['quote']) + '</blockquote><p class="caption">' + link(item['evidence_id'] + ' · 运行证据 / Evidence', evidence[item['evidence_id']]) + ' · ' + link('固定段落 / Indexed paragraph', 'source-index.html#' + item['evidence_id']) + '</p>' for item in excerpts)
    fields = {'name': '名称 / Name', 'description': '业务说明 / Description', 'products_services': '产品服务 / Offering', 'customers': '客户 / Customer', 'monetization': '收费方式 / Monetization', 'importance_signals': '重要性 / Significance'}
    nodes = []
    for node in data['businesses']:
        claims = []
        for claim in node['claim_evidence']:
            value = node[claim['field']] if claim['item_index'] is None else node[claim['field']][claim['item_index']]
            if isinstance(value, dict):
                value = value['description'] + ' · ' + BASIS[value['basis']]
            claims.append('<details class="claim"><summary>' + esc(fields[claim['field']]) + '<span>' + esc(value) + '</span></summary>' + refs(claim['excerpts']) + '</details>')
        for item in node.get('monetization', []):
            if item['basis'] == 'unknown':
                claims.append('<p class="notice">' + esc(BASIS['unknown'] + ' · ' + item['description']) + '</p>')
        stage_note = '<p class="caption">本轮仅提取对象名称、业务说明与关系。产品/客户/收费明细尚未提取；空数组不表示原文没有披露。Attribute extraction is a later stage.</p>' if graph_stage else ''
        role = data['metadata'].get('node_roles', {}).get(node['id'])
        role_tag = ' <span class="tag">' + esc(role_labels.get(role, role)) + '</span>' if role else ''
        nodes.append('<details class="node-detail" id="node-' + view['ids'][node['id']] + '"><summary><span class="tag">' + esc(KIND[node['kind']]) + '</span>' + role_tag + ' ' + esc(node['name']) + '</summary><p class="caption">' + esc(node['id']) + ' · 候选 / Candidate</p>' + stage_note + ''.join(claims) + '</details>')
    edges = []
    for i, edge in enumerate(data['relationships']):
        token = f'R{i+1:02}'
        edges.append('<details class="edge-detail" id="edge-' + token + '"><summary><span class="tag">' + esc(BASIS[edge['basis']]) + '</span> ' + token + ' · ' + esc(names[edge['source_id']] + ' → ' + names[edge['target_id']]) + '</summary><p>' + esc(RELATION[edge['kind']] + ' · ' + edge['description']) + '</p><p><b>判断依据 / Rationale</b> · ' + esc(edge['rationale']) + '</p>' + refs(edge['excerpts']) + ('<p class="notice">尚未确定，因此未画成已成立的连线。Unresolved relationship.</p>' if edge['basis'] == 'unknown' else '') + '</details>')
    gaps = []
    for gap in data['unknowns']:
        gaps.append('<li><b>' + esc(gap['question']) + '</b><p>' + esc(gap['reason_unanswered']) + '</p>' + ' · '.join(link(names[nid], '#node-' + view['ids'][nid]) for nid in gap['related_business_ids']) + '</li>')
    if review:
        review_html = '<p>' + esc(review.get('summary', '')) + '</p><p class="caption">' + esc(review.get('review_method', '')) + '</p>'
        gap_classifications = []
        for check in review['checks']:
            classification = check.get('classification')
            if classification and classification not in CLASSIFICATION:
                raise ValueError('unknown_review_classification')
            badge = '<span class="tag">' + esc(CLASSIFICATION[classification]) + '</span> ' if classification else ''
            supplemental_links = ('<p class="notice">复核补查 · 本轮模型未读取 / Review-only: ' + ' · '.join(link(bid, 'supplemental-index.html#' + bid) for bid in check['supplemental_source_block_ids']) + '</p>') if check.get('supplemental_source_block_ids') else ''
            review_html += '<details class="review-check"><summary>' + badge + esc(check['label'] + ' · ' + check['status']) + '</summary><p>' + esc(check.get('observation', check.get('actual', ''))) + '</p><p>' + esc(check.get('note', '')) + '</p>' + ' · '.join(link(bid, 'source-index.html#' + bid) for bid in check.get('source_block_ids', [])) + supplemental_links + '</details>'
            if classification:
                gap_classifications.append('<li>' + badge + '<b>' + esc(check['label']) + '</b><p>' + esc(check.get('observation', check.get('actual', ''))) + '</p>' + supplemental_links + '</li>')
        review_html += '<ul>' + ''.join('<li>' + esc(item) + '</li>' for item in review.get('limitations', [])) + '</ul>'
        gap_summary = '<h3>复核判断 / Review classification</h3><ul>' + ''.join(gap_classifications) + '</ul>' if gap_classifications else '<p class="caption">本轮尚未记录逐项缺口分类。Gap classification not recorded.</p>'
    else:
        review_html = '<p>本轮内容复核尚未附上。格式合法、引用可定位与内容正确是三个不同的检查。Content review pending.</p>'
        gap_summary = '<p class="caption">下面是模型记录的待确认事项。原文复核与缺口分类尚未附上。Review classification pending.</p>'
    dispositions = data['metadata'].get('block_disposition', [])
    scope_html = '<p>' + esc(packet['extraction_scope']['title']) + '</p><p>' + esc(packet['extraction_scope'].get('instruction', '')) + '</p><p class="caption">逐块处理状态由模型自报，不代替内容覆盖验收。Block disposition is model-reported.</p>'
    scope_html += ''.join('<details><summary>' + esc(item['block_id'] + ' · ' + item['disposition']) + '</summary><p>' + esc(item['reason']) + '</p>' + link('定位冻结原文 / Locate source', 'source-index.html#' + item['block_id']) + '</details>' for item in dispositions)
    return { 'nodes': ''.join(nodes), 'edges': ''.join(edges), 'gaps': gap_summary + '<h3>模型原始待确认事项 / Original model questions</h3><ul>' + (''.join(gaps) or '<li>模型未列出具体问题；这不能证明没有遗漏。No model-reported gaps; completeness is not established.</li>') + '</ul>', 'review': review_html, 'scope': scope_html }


SCRIPT = '''
'use strict';
function reveal(id){const el=document.getElementById(id);if(!el)return;for(let p=el;p;p=p.parentElement){if(p.tagName==='DETAILS')p.open=true;}el.scrollIntoView({block:'start'});history.replaceState(null,'','#'+id);}
document.querySelectorAll('[data-node-key],[data-relation-key]').forEach(el=>{const id=el.dataset.nodeKey?'node-'+el.dataset.nodeKey:'edge-'+el.dataset.relationKey;el.addEventListener('click',()=>reveal(id));el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();reveal(id);}});});
document.querySelectorAll('a[href^="#node-"],a[href^="#edge-"]').forEach(el=>el.addEventListener('click',event=>{event.preventDefault();reveal(el.hash.slice(1));}));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-view]').forEach(el=>el.setAttribute('aria-selected',String(el===button)));document.querySelectorAll('.view-panel').forEach(panel=>{panel.hidden=panel.dataset.panel!==button.dataset.view;});}));
if(/^#(?:node-N\\d+|edge-R\\d+)$/.test(location.hash))reveal(location.hash.slice(1));
'''


def build(run, output, review_path=None, with_svg=False, supplemental_path=None, graph_stage=False, overview=False):
    run, output = run.resolve(), output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('output_outside_project')
    data, packet, result, view, code, paths, binding, evidence, review = load(run, output, review_path)
    if graph_stage and any(node.get(field) for node in data['businesses'] for field in ('products_services', 'customers', 'monetization')):
        raise ValueError('graph_stage_contains_unexpected_attribute_extraction')
    variants = graph_variants(data, code, view, overview=overview)
    output.mkdir(parents=True, exist_ok=True)
    assets = output / 'assets'
    assets.mkdir(exist_ok=True)
    for variant in variants:
        variant['mmd'] = assets / ('business-' + variant['key'] + '.mmd')
        variant['svg'] = variant['mmd'].with_suffix('.svg')
        if with_svg and (not variant['mmd'].is_file() or variant['mmd'].read_text() != variant['code']):
            raise ValueError('render_current_mermaid_first')
        variant['mmd'].write_text(variant['code'])
    (assets / 'business-ids.json').write_text(json.dumps(view, ensure_ascii=False, indent=2) + '\n')
    if overview:
        selection = overview_selection(data)
        selection['binding'] = binding
        (assets / 'overview-selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n')
    (output / 'source-index.html').write_text(source_index(packet, output, paths['source']))
    if not with_svg:
        print(json.dumps({'status': 'mermaid_prepared_svg_pending', 'profile': str(PROFILE_DIR / 'mermaid-config.json'), 'diagrams': [str(v['mmd']) for v in variants]}, ensure_ascii=False))
        return
    supplemental = supplemental_index(review, supplemental_path, packet, output)
    if supplemental:
        paths['复核补证 / Review-only evidence'] = supplemental['page']
        paths['全文搜索记录 / Full-text review search'] = supplemental['artifact']
    panels, canvas_scripts, tabs = [], [], []
    for i, variant in enumerate(variants):
        svg = namespaced_svg(variant['svg'].read_text(), variant['view'], variant['key'])
        key = variant['key']
        tabs.append('<button role="tab" aria-selected="' + ('true' if i == 0 else 'false') + '" aria-controls="view-' + key + '" data-view="' + key + '">' + esc(variant['title']) + '</button>')
        panels.append('<div class="view-panel" role="tabpanel" id="view-' + key + '" data-panel="' + key + '"' + ('' if i == 0 else ' hidden') + '><div class="standard-canvas"><div class="map-toolbar"><span>' + str(len(variant['view']['ids'])) + ' 个节点 · ' + str(len(variant['view']['edges'])) + ' 条已声明关系</span><div><button id="map-fit-' + key + '" aria-pressed="false">适合宽度</button><button id="map-original-' + key + '" aria-pressed="true">原始尺寸</button></div></div><div class="map-drawing" id="map-drawing-' + key + '" tabindex="0" aria-label="' + esc(variant['title']) + '">' + svg + '</div></div><p class="caption">' + esc(variant['title']) + ' · ' + link('Mermaid 源码', href(variant['mmd'], output)) + ' · ' + link('SVG', href(variant['svg'], output)) + '</p></div>')
        shared_js = (PROFILE_DIR / 'canvas.js').read_text()
        for token in ('map-drawing', 'map-fit', 'map-original'):
            shared_js = shared_js.replace("'" + token + "'", "'" + token + '-' + key + "'")
        canvas_scripts.append(shared_js)
    counts = Counter(check['status'] for check in review['checks']) if review else Counter()
    status = '候选待复核 / Review pending'
    semantic = 'not_evaluated'
    if review and review['checks']:
        stage_status = review.get('separate_statuses', {})
        if (graph_stage and not counts['needs_improvement']
                and review.get('status') == 'passed_for_graph_stage_with_declared_gaps'
                and stage_status.get('selected_stage_semantic_fidelity') == 'passed'
                and stage_status.get('major_business_relationship_coverage') == 'passed_for_selected_stage'):
            status = '对象与关系已复核 · 仍有 ' + str(len(data['unknowns'])) + ' 项未决 / Graph reviewed with gaps'
            semantic = 'passed_for_graph_stage_with_declared_gaps'
        elif counts['gap'] or counts['needs_improvement']:
            status, semantic = '候选需改进 / Needs work', 'needs_work'
        else:
            status, semantic = '已附内容复核 / Review attached', 'reviewed_candidate'
    company = next(node for node in data['businesses'] if node['kind'] == 'company')
    details = details_html(data, packet, view, evidence, review, supplemental, graph_stage)
    navigation = [('graph', '业务图 / Map'), ('nodes', '节点依据 / Claims'), ('edges', '关系依据 / Relations'), ('gaps', '未决事项 / Gaps · ' + str(len(data['unknowns']))), ('review', '内容复核 / Review'), ('scope', '输入范围 / Scope'), ('artifacts', '文件与过程 / Artifacts')]
    artifacts = {**paths, '固定段落索引 / Source index': output / 'source-index.html', '节点映射 / Node IDs': assets / 'business-ids.json'}
    title = company['name'] + ' · 业务结构 / Business structure'
    intro = '<h1>' + esc(title) + '</h1><p class="caption">报告期末 / Period end · ' + esc(packet['period_end']) + ' · ' + esc(packet['extraction_scope']['title']) + '</p><div class="source-links">' + link('官方原财报 / Official filing ↗', packet['source_url']) + link('冻结原件 / Frozen original ↗', href(paths['source'], output)) + link('固定段落索引 / Indexed input (' + str(len(packet['blocks'])) + ') ↗', 'source-index.html') + link('运行引用原文 / Run evidence ↗', href(paths['evidence.html'], output)) + '</div><p>' + esc(data['summary']) + '</p><p class="caption">' + esc(result['model'] + ' · ' + result['provider']) + ' · ' + link(data['metadata']['trace_id'], 'http://127.0.0.1:8765/agent-runs?run=' + quote(data['metadata']['trace_id'], safe='')) + ' · ' + esc(status) + '</p>'
    if graph_stage:
        intro += '<div class="notice"><strong>本轮验收对象与关系 / Object and relationship stage</strong><p>先检查业务对象是否完整、归属与关联是否清楚。产品/客户/收费明细尚未提取。空数组表示本阶段未执行属性提取，不代表原文没有披露；未复用此前失败运行的属性。</p></div>'
    intro += execution_notice(result, paths, output)
    if overview:
        artifacts['总览投影记录 / Overview selection'] = assets / 'overview-selection.json'
        intro += ('<p class="notice"><strong>先看业务总览，再展开细节 / Overview first</strong><br>'
            + str(len(selection['selected_node_ids'])) + ' 个总览节点；' + str(len(selection['folded_node_ids']))
            + ' 个下层对象保留在完整图与分部图；' + str(len(selection['unplaced_node_ids']))
            + ' 个对象尚无通向公司根节点的已记录归属路径。总览沿用候选的报告分部及其直接构成，同层不保证原文同级，不代表收入权重或重要性排名；候选内容仍需修订。点击下方分部标签展开。'
            + '</p>')
        if selection['unplaced_node_ids']:
            names = {node['id']: node['name'] for node in data['businesses']}
            intro += '<details><summary>查看未记录归属路径的对象 / Placement gaps</summary><p>' + ' · '.join(link(names[nid], '#node-' + view['ids'][nid]) for nid in selection['unplaced_node_ids']) + '</p><p class="caption">缺少已记录路径不代表这些对象独立存在；完整候选仍保留其已有关系。Missing paths do not establish independence.</p></details>'
    intro += '<p class="caption">' + link(str(len(data['unknowns'])) + ' 项已记录未决问题 / Recorded questions', '#gaps') + '。图中已记录的归属关系清楚，不代表所有业务细节均已回答。</p>'
    graph = '<section id="graph">' + intro + '<div class="view-tabs" role="tablist" aria-label="图的范围 / Diagram scope">' + ''.join(tabs) + '</div>' + ''.join(panels) + '<div class="legend"><span><i class="swatch"></i>原文明示 / Explicit</span><span><i class="swatch derived"></i>有据推断 / Derived</span></div><p class="caption">公司深色 · 报告分部蓝色 · 业务绿色 · 产品服务白色。节点大小不表示财务权重。可横向滚动，点击节点或连线查看具体依据。</p><p class="caption">聚焦图只展示已记录归属的分支；完整图保留全部节点。缺少归属的节点位于标注框中，不能据此认定业务独立。尚未确定的关系保留在关系与未决事项中，不画成事实连线。</p></section>'
    body = graph + ''.join('<section id="' + key + '"><h2>' + dict(navigation)[key] + '</h2>' + details[key] + '</section>' for key in ('nodes', 'edges', 'gaps', 'review', 'scope'))
    body += '<section id="artifacts"><h2>文件与过程 / Artifacts</h2><div class="links">' + ''.join(link(name, href(path, output)) for name, path in artifacts.items()) + '</div><details><summary>运行与原件绑定 / Run bindings</summary><pre>' + esc(json.dumps(binding, ensure_ascii=False, indent=2)) + '</pre></details></section><footer>覆盖范围来自本次明确选择的财报章节。此页保留当前运行候选，不等于全公司所有产品覆盖或生产采纳。源码、原文、格式、引用与图形映射分别检查；本轮未执行浏览器视觉验收。</footer>'
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(title) + '</title><style>' + (PROFILE_DIR / 'canvas.css').read_text() + STYLE + '</style></head><body><header><strong>Uteki · 业务提取验收 / Business extraction</strong><small>' + esc(status) + '</small></header><div class="workspace"><aside>' + ''.join(link(label, '#' + key) for key, label in navigation) + '</aside><main>' + body + '</main></div><script>' + '\n'.join(canvas_scripts) + SCRIPT + '</script></body></html>'
    (output / 'index.html').write_text(page)
    doc = H.fromstring(page)
    id_counts = Counter(doc.xpath('//*[@id]/@id'))
    if any(count != 1 for count in id_counts.values()):
        raise ValueError('duplicate_page_id')
    all_nodes = doc.xpath('//*[@id="view-all"]//*[@data-node-key]/@data-node-key')
    if Counter(all_nodes) != Counter(view['ids'].values()):
        raise ValueError('full_graph_lost_nodes')
    checked = []
    for url in doc.xpath('//a/@href'):
        if urlsplit(url).scheme in {'http', 'https'}:
            continue
        parsed = urlsplit(url)
        target = (output / unquote(parsed.path)).resolve() if parsed.path else output / 'index.html'
        if not target.is_file() or not target.is_relative_to(ROOT):
            raise ValueError('broken_or_outside_local_link: ' + url)
        if parsed.fragment and target.suffix == '.html':
            target_dom = doc if target == output / 'index.html' else H.fromstring(target.read_bytes())
            if len(target_dom.xpath('//*[@id=$fragment]', fragment=unquote(parsed.fragment))) != 1:
                raise ValueError('broken_local_fragment: ' + url)
        checked.append(url)
    files = {'page': output / 'index.html', 'source_index': output / 'source-index.html', 'builder': Path(__file__), 'renderer': ROOT / 'src/uteki/presentation/business_map_view.py', 'profile': PROFILE_DIR / 'mermaid-config.json', 'viewer_css': PROFILE_DIR / 'canvas.css', 'viewer_js': PROFILE_DIR / 'canvas.js'}
    for variant in variants:
        files[variant['key'] + '_mermaid'] = variant['mmd']
        files[variant['key'] + '_svg'] = variant['svg']
    if supplemental:
        files['supplemental_evidence'] = supplemental['page']
        files['supplemental_search'] = supplemental['artifact']
    if overview:
        files['overview_selection'] = assets / 'overview-selection.json'
        files['overview_projector'] = ROOT / 'src/uteki/presentation/business_overview.py'
    verification = {'schema_version': 'business-map-page-check-v1', 'status': 'rendered_candidate', 'binding': binding, 'execution_mode': result.get('execution_mode', 'not_recorded'), 'parent_trace_id': result.get('parent_trace_id'), 'presentation_stage': 'objects_and_relationships_only' if graph_stage else 'run_candidate', 'attribute_extraction': 'not_performed_in_this_stage' if graph_stage else 'as_recorded_in_run', 'semantic_acceptance': semantic, 'browser_visual_review': 'not_performed', 'source_blocks_verified': len(packet['blocks']), 'evidence_fragments_verified': len(evidence), 'nodes_in_full_graph': len(all_nodes), 'relationships_preserved': len(view['edges']), 'unresolved_relationships': len(view['unresolved']), 'unknown_questions': len(data['unknowns']), 'unplaced_nodes': next(v for v in variants if v['key'] == 'all')['unplaced'], 'source_index_blocks': len(packet['blocks']), 'local_links_checked': len(checked), 'views': [{'key': v['key'], 'nodes': list(v['view']['ids']), 'edges': [e['id'] for e in v['view']['edges']]} for v in variants], 'model_calls': 0, 'files': {name: sha(path) for name, path in files.items()}}
    (output / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: verification[key] for key in ('status', 'semantic_acceptance', 'nodes_in_full_graph', 'relationships_preserved', 'unplaced_nodes', 'source_index_blocks', 'local_links_checked')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--with-svg', action='store_true')
    parser.add_argument('--supplemental', type=Path)
    parser.add_argument('--graph-stage', action='store_true', help='Explicitly mark products/customers/monetization as not extracted in this stage')
    args = parser.parse_args()
    build(args.run, args.output, args.review, args.with_svg, args.supplemental, args.graph_stage)
