#!/usr/bin/env python3
"""Render this explicitly scoped failed-run checkpoint, without inventing a business map."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import html
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from lxml import html as lhtml

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUTPUT=ROOT/'docs/design/data-agent-acceptance/microsoft-cloud-business-v1'
RUN_NAMES=('run-01','run-02','repair-run-01','repair-run-03-contract-v2-connected')
esc=lambda value:html.escape(str(value),quote=True)
read=lambda path:json.loads(path.read_text())
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
norm=lambda text:' '.join(text.split())


def link(label,path,fragment=''):
    url=quote(os.path.relpath(path,OUTPUT),safe='/')+('#'+quote(fragment,safe='') if fragment else '')
    return f'<a href="{esc(url)}">{esc(label)}</a>'


def build():
    packet_path=HERE/'input/source_packet.json';packet=read(packet_path)
    review_path=HERE/'evaluation/run-02-raw-draft-review.json';review=read(review_path)
    original=ROOT/packet['source_local_path']
    if sha(original)!=packet['source_sha256']:raise ValueError('source_hash_mismatch')
    dom=lhtml.fromstring(original.read_bytes());tree=dom.getroottree()
    elements={tree.getpath(el):el for el in dom.iter()}
    for block in packet['blocks']:
        if norm(''.join(elements[block['source_dom_path']].itertext()))!=block['text']:
            raise ValueError('source_block_mismatch')
        if hashlib.sha256(block['text'].encode()).hexdigest()!=block['text_sha256']:
            raise ValueError('source_block_hash_mismatch')
    raw_path=HERE/'run-02/response.txt';raw=read(raw_path)
    expected={'response_sha256':sha(raw_path),'result_sha256':sha(HERE/'run-02/result.json'),
        'source_packet_sha256':sha(packet_path),'coverage_inventory_sha256':sha(HERE/'evaluation/source-coverage-inventory.json')}
    if review['binding']!=expected or not review['not_a_renderable_candidate']:raise ValueError('raw_review_binding_mismatch')
    records=[];total=Decimal('0');rows=[]
    descriptions=('输出达到 16,000 上限，响应截断。','完整 JSON；类型协议校验失败，内容审阅另发现错误。','局部修正达到 6,000 上限，可见正文为空。','HTTP 200 / end_turn；返回完整补丁，但路径不符合协议，内容仍有遗漏。')
    for index,name in enumerate(RUN_NAMES):
        directory=HERE/name;result=read(directory/'result.json');response=read(directory/'response_metadata.json');request=read(directory/'request.json')
        if result['status']!='failed' or (directory/'business_map.json').exists():raise ValueError('checkpoint_no_longer_matches_failed_runs')
        if result['request_sha256']!=sha(directory/'request.json') or response['request_sha256']!=result['request_sha256']:
            raise ValueError('request_hash_mismatch')
        if result['source_packet_sha256']!=sha(packet_path):raise ValueError('run_source_mismatch')
        budget=result['budget']
        if budget['unknown_requests'] or budget['in_flight_requests']:raise ValueError('unsettled_request_cost')
        cost=Decimal(budget['estimated_spent_usd']);total+=cost
        trace=result['trace_id'];usage=response['raw_usage'];text_size=len((directory/'response.txt').read_text())
        trace_url='http://127.0.0.1:8765/agent-runs?run='+quote(trace,safe='')
        record={'run':name,'status':result['status'],'trace_id':trace,'input_tokens':usage['input_tokens'],
            'output_tokens':usage['output_tokens'],'response_stop_reason':response['stop_reason'],
            'estimated_usd':str(cost),'visible_text_chars':text_size,'result_sha256':sha(directory/'result.json'),
            'request_sha256':result['request_sha256'],'response_sha256':sha(directory/'response.txt')}
        records.append(record)
        rows.append('<tr><td><b>'+esc(name)+'</b><br><span class="muted">'+esc('提取 / Extraction' if index<2 else '局部修正 / Patch')+'</span></td><td>'+esc(descriptions[index])+
            '</td><td>'+f'{usage["input_tokens"]:,} / {usage["output_tokens"]:,}'+'</td><td>$'+esc(cost)+'</td><td><a href="'+esc(trace_url)+'">Trace</a> · '+
            link('记录 / Result',directory/'result.json')+'<br>'+link('原响应 / Response',directory/'response.txt')+'</td></tr>')
    if records[2]['visible_text_chars']!=0:raise ValueError('repair_response_is_not_empty')
    roles=Counter(b['input_role'] for b in packet['blocks'])
    source_evidence=HERE/'input/source-evidence.html'
    cite=lambda ordinal:link('原文 '+str(ordinal),source_evidence,next(b['id'] for b in packet['blocks'] if b['ordinal']==ordinal))
    claims=''.join('<li><b>'+esc(node['name'])+'</b> <span class="muted">'+esc(node['id'])+'</span></li>' for node in raw['businesses'])
    style=(HERE/'page-template.html').read_text().split('<style>',1)[1].split('</style>',1)[0]
    style+='table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line)}th{font-size:12px;color:var(--muted);font-weight:500}td:nth-child(3),td:nth-child(4){white-space:nowrap}.compact{margin:8px 0}.compact li{margin:5px 0}.wrap-table{overflow:auto}.tag.pending{background:#f7eddc;color:#855b36}.main-lead{font-size:16px}.topline{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}section{margin-bottom:18px;padding-bottom:15px}main{max-width:1400px}h2{font-size:17px;margin-bottom:8px}'
    timestamp=datetime.now(timezone.utc).isoformat()
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Microsoft · 业务小节阶段复核</title><style>'''+style+'''</style></head><body>
<header><strong>Uteki · 业务小节 / Business section</strong><small>阶段记录 / Checkpoint</small></header><div class="workspace"><aside><a href="#current">当前状态 / Status</a><a href="#runs">运行记录 / Runs</a><a href="#issues">已知问题 / Issues</a><a href="#next">下一步 / Next</a></aside><main>
<section id="current"><p class="notice"><b>已有新版复核候选。</b> <a href="../microsoft-cloud-business-reviewed-v1/index.html">打开业务图、依据与本轮验收 / Open reviewed candidate</a>。以下保留此前失败阶段的历史记录，不代表最新状态。</p><div class="topline"><div><h1>Microsoft · Intelligent Cloud</h1><p class="muted">FY2025 10-K · 报告期末 / Period end: '''+esc(packet['period_end'])+'''</p></div><span class="tag pending">未完成 / Incomplete</span></div>
<p class="main-lead"><b>历史阶段：当时没有合格业务图。</b>最新修复调用已正常返回；补丁路径不符合协议，尚未应用。已有内容改进，但仍有遗漏。</p>
<p>选定材料 / Input · '''+str(roles['selected_subsection'])+' 块 Intelligent Cloud 连续小节 + '+str(roles['scope_metadata'])+''' 块公司与报告期上下文。包含竞争段；不含其他分部业务或收入图。</p>
<p class="links">'''+link('查看 30 块原文 / Selected source',source_evidence)+link('官方报告原件 / Filing',original)+link('输入包 / Input packet',packet_path)+link('范围核验 / Scope check',HERE/'input/dom-coverage-verification.json')+'''</p></section>
<section id="runs"><h2>四次已返回用量的运行 / Four metered attempts</h2><div class="wrap-table"><table><thead><tr><th>运行 / Run</th><th>结果 / Outcome</th><th>输入 / 输出 tokens</th><th>估算费用 / Estimate</th><th>过程与文件 / Records</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div>
<p class="caption">合计 $'''+str(total)+'''，按已返回用量与冻结单价估算，非实际账单；失败费用已包含。模型均为 AIHubMix · Claude Sonnet 5.5。</p></section>
<section id="issues"><h2>完整原始稿：仍未通过 / Complete draft, not accepted</h2><p>'''+str(len(raw['businesses']))+' 个节点、'+str(len(raw['relationships']))+''' 条关系是原始响应内容，不是合格图。'''+link('原始 JSON 响应',raw_path)+' · '+link('逐项内容审阅 / Semantic review',review_path)+'''</p>
<ul class="compact"><li><b>两条归属错误：</b>GitHub、Nuance Healthcare 同时包含云与本地形态，却把整个实体归入仅云服务组。改成虚线不能修复主体范围。'''+cite(120)+' · '+cite(130)+'''</li>
<li><b>类型冲突：</b>Azure AI Foundry 的节点种类与平台角色不兼容，系统因此拒绝产物。'''+cite(128)+'''</li>
<li><b>仍有遗漏：</b>Server products 能力、Azure 混合云整合能力，以及竞争段中自有能力尚未完整表达；部分字段证据与“主要”限定也需补齐。'''+cite(129)+' · '+cite(134)+' · '+cite(140)+'''</li></ul>
<details><summary>展开原始节点清单与审阅范围 / Draft inventory</summary><p>以下仅列原始稿名称，未经类型与关系修复，不画成正确业务图。</p><ul>'''+claims+'''</ul><p>'''+esc(review['review_method'])+'''</p><p class="muted">审阅者参与输入准备，非盲评。原始失败记录与先验覆盖清单均保留。</p></details></section>
<section id="next"><h2>最新修复结果 / Latest patch review</h2>
<p>Sonnet 5.5 · high / between_tools / 6000 · 正常结束，输出 3,631 tokens，估算 $0.049634。AIHubMix 本次接受了 between_tools 配置；这不能证明多次运行稳定。</p>
<ul class="compact"><li><b>已有改进（未应用）：</b>Foundry 改为 business；GitHub/Nuance 的整体归属改为 unknown，并解释云与本地的边界；补充服务器能力和 Azure 混合云说明。</li>
<li><b>协议失败：</b>使用未约定的 /claims/... 路径；还有 remove 数组末尾占位符的非法操作。宿主拒绝应用整个补丁。</li>
<li><b>内容仍未通过：</b>原140块的数据仓库等能力仍被忽略；摘要仍缺少“主要”限定。补丁中的数组索引也需核对，不能直接转换路径后采纳。</li></ul>
<p>'''+link('查看完整补丁 / Model patch',HERE/'repair-run-03-contract-v2-connected/patch.json')+' · '+link('本次验收 / Review',HERE/'evaluation/repair-run-03-review.json')+'''</p>
<p>下一步：简化局部修复协议，让模型按已知节点提交字段与完整证据，宿主负责结构合并与校验。先离线验证，不继续付费重试。</p>
<p class="muted">另有一次本地 ConnectError，未收到 HTTP 响应。原失败与未知预留保留；本次连接恢复根据连接建立失败记录单独核算，非供应商账单。'''+link('连接失败原件',HERE/'repair-run-02-contract-v2/result.json')+' · '+link('连接恢复与核算依据',HERE/'repair-run-03-contract-v2-connected/manifest.json')+'''</p></section>
<details><summary>来源绑定与阶段边界 / Bindings</summary><pre>'''+esc(json.dumps({'review_binding':expected,'runs':records},ensure_ascii=False,indent=2))+'''</pre></details><footer>阶段快照 / Snapshot · '''+esc(timestamp)+''' · 本页零模型调用。已核对本地来源与链接，未做浏览器视觉验收。</footer></main></div></body></html>'''
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/'index.html').write_text(page)
    doc=lhtml.fromstring(page);checked=[]
    for url in doc.xpath('//a/@href'):
        if url.startswith('http'):continue
        parts=urlsplit(url);target=OUTPUT/unquote(parts.path) if parts.path else OUTPUT/'index.html'
        if not target.is_file():raise ValueError('missing_local_link: '+url)
        if parts.fragment:
            targetdoc=doc if target==OUTPUT/'index.html' else lhtml.fromstring(target.read_bytes())
            if len(targetdoc.xpath('//*[@id=$id]',id=unquote(parts.fragment)))!=1:raise ValueError('missing_fragment: '+url)
        checked.append(url)
    verification={'schema_version':'business-stage-page-check-v1','status':'incomplete_no_qualified_map',
        'source_blocks_verified':len(packet['blocks']),'input_roles':dict(roles),'raw_review_binding':expected,
        'completed_attempts':records,'total_estimated_usd':str(total),'next_configuration_status':'provider_accepted_patch_rejected',
        'local_links_checked':len(checked),'page_sha256':sha(OUTPUT/'index.html'),'builder_sha256':sha(Path(__file__)),
        'model_calls_by_builder':0,'browser_visual_review':'not_performed','generated_at':timestamp}
    (OUTPUT/'stage-verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:verification[k] for k in ['status','source_blocks_verified','total_estimated_usd','local_links_checked']},ensure_ascii=False))


if __name__=='__main__':build()
