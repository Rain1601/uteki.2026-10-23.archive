"""Render this explicit two-company acceptance case from verified frozen packages."""
from __future__ import annotations
import ast
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
from lxml import html

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from uteki.infrastructure.document_sources.parsed_package import verify_parsed_package
from uteki.agents.reading.document_reader import DocumentReader
PAGE = ROOT / 'docs/design/data-agent-acceptance/parser-navigation-v1/index.html'
BASELINE = HERE.parent / '2026-10-07-data-foundation-v1'

def read(path): return json.loads(path.read_text())
def sha(path): return sha256(path.read_bytes()).hexdigest()
def blocks(folder): return [json.loads(s) for s in (folder/'blocks.jsonl').read_text().splitlines()]
def pretty(obj): return '<pre><code>'+escape(json.dumps(obj, ensure_ascii=False, indent=2))+'</code></pre>'
def link(path, label, fragment=''):
    return '<a href="'+escape(os.path.relpath(path, PAGE.parent)+fragment, quote=True)+'">'+escape(label)+'</a>'
def table(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+escape(s)+'</th>' for s in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
def detail(label, content): return '<details><summary>'+escape(label)+'</summary>'+content+'</details>'

def build():
    reports = {s: read(HERE/f'{s}-verification.json') for s in ('stage-a','stage-b')}
    assert all(r['status']=='local_program_checks_passed' and r['model_calls']==0 for r in reports.values())
    assert read(HERE/'verification.json')['status']=='passed'
    # Reuse the approved acceptance-page shell. This does not execute that builder.
    tree = ast.parse((BASELINE/'build_delivery.py').read_text())
    css = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='css' for t in n.targets))
    summaries, navigation_rows, examples, source_rows, all_items, stamps = [], [], [], [], [], []
    for company in ('amd','tsmc'):
        old = BASELINE/f'anchor-fix-v2-{company}'
        a, b = HERE/f'stage-a-{company}', HERE/f'stage-b-{company}'
        for folder in (old,a,b):
            verify_parsed_package(folder)
            stamps.append({'path':str((folder/'manifest.json').relative_to(ROOT)), 'sha256':sha(folder/'manifest.json')})
        oldblocks, ablocks, bblocks = (blocks(f) for f in (old,a,b))
        assert len(oldblocks)==len(ablocks)==len(bblocks)
        # Contents, block identity, table structure and all other fields stay exact.
        strip = lambda bs: [{k:v for k,v in x.items() if k!='layout_role'} for x in bs]
        assert strip(oldblocks)==strip(ablocks)==strip(bblocks)
        assert ablocks==bblocks
        nav = [x for x in ablocks if x.get('layout_role')=='repeated_navigation']
        assert nav
        r0, ra = DocumentReader(old), DocumentReader(a)
        n0 = next(x['node_id'] for x in r0.nodes.values() if x['kind']=='document')
        na = next(x['node_id'] for x in ra.nodes.values() if x['kind']=='document')
        s0, sa = r0.search(n0,'Table of Contents'), ra.search(na,'Table of Contents')
        sample = nav[0]
        before = r0.read(n0,sample['block_id'],count=1)
        after = ra.read(na,sample['block_id'],count=1)
        assert sample['block_id'] in [x['block_id'] for x in before['blocks']]
        assert sample['block_id'] not in [x['block_id'] for x in after['blocks']]
        # A direct read of excluded navigation must not invent unrelated evidence.
        expected_retained = [x for x in before['blocks'] if x['block_id'] not in {z['block_id'] for z in nav}]
        assert after['blocks']==expected_retained
        source = read(b/'source.json')
        assert read(old/'source.json')['raw_sha256']==source['raw_sha256']
        ii0 = [x for x in read(old/'index.json')['nodes'] if x['kind']=='item']
        iia = [x for x in read(a/'index.json')['nodes'] if x['kind']=='item']
        iib = [x for x in read(b/'index.json')['nodes'] if x['kind']=='item']
        assert len(ii0)==len(iia)
        summaries.append([company.upper(), str(len(nav)), f"{s0['total']} → {sa['total']}", f'{len(iia)} → {len(iib)}'])
        source_rows.append([company.upper(),escape(source['form_type']),escape(source['report_period_end']),link(b/'source.json','来源与固定范围 / Source'),link(b/'document.html','完整解析文档 / Document')])
        navigation_rows.append([company.upper(),escape(sample['text']),link(old/'document.html','旧版：作为普通正文','#'+sample['block_id']),link(a/'document.html','新版：保留并标为导航','#'+sample['block_id'])])
        examples.append(detail(company.upper()+' · 实际 search / read 返回', pretty({'selected_block_id':sample['block_id'],'search_before':s0,'search_after':sa,'read_before':before,'read_after':after})))
        if company=='tsmc':
            assert len(iib)==29
            true_title=next(x for x in bblocks if x['text']=='TABLE OF CONTENTS' and x.get('layout_role')!='repeated_navigation')
            true_title_link=link(b/'document.html','被保留的真实目录标题 / Kept contents heading','#'+true_title['block_id'])
            positions={x['block_id']:x for x in bblocks}
            for node in iib:
                start,end=positions[node['start_block_id']],positions[node['end_block_id']]
                assert start['type']=='table'
                all_items.append([escape(start['text']),str(node['reported_page']),f"{start['ordinal']}–{end['ordinal']}",link(b/'document.html','定位标题 / Open','#'+start['block_id'])])
            item4=next(x for x in iib if positions[x['start_block_id']]['text'].upper().startswith('ITEM 4.'))
            item18=next(x for x in iib if positions[x['start_block_id']]['text'].upper().startswith('ITEM 18.'))
            item4link=link(b/'document.html','Item 4 · Information on the Company','#'+item4['start_block_id'])
            item18link=link(b/'document.html','Item 18 · Financial Statements','#'+item18['start_block_id'])
    body='<section id="overview"><p class="eyebrow">ITERATION 02 · 2026-10-07</p><h1>让 Agent 少读导航，准确找到章节</h1><p class="lead">两个解析阶段已交付。输入是同两份冻结财报，输出是四份独立版本的解析包。</p><span class="status">本地程序验收 / Local checks</span><p>本轮处理原文导航和章节定位。未运行新的模型提取或问答评测；不据此宣称财务内容已完整核验。</p>'
    body+=table(['材料','标记的重复导航','全文检索 TOC：旧 → A','Item 节点：A → B'],summaries)
    body+='<p>检索数是文字命中数，不是 token 数。真正的目录标题及含同名短语的有效正文继续保留。</p></section>'
    body+='<section id="stage-a"><h2>阶段 A · 重复导航 <small>Navigation</small></h2><p><b>输入：</b>AMD 10-K、TSMC 20-F 的冻结 HTML。<b>动作：</b>验证短链接文字、重复版式和目录目标，再标记导航。<b>输出：</b>v0.1.9 解析包。</p><p>原文、块 ID、表格和来源位置保留。默认搜索与上下文读取会排除标记的重复导航，并报告省略情况；直接下载原始解析文档仍能看到它。</p>'
    body+=table(['材料','原文','修复前','修复后'],navigation_rows)
    body+='<p><b>验收：</b>真正的目录标题、包含同名词语的叙述、错误链接目标和不重复链接不能被误滤。单独读取导航时，不自动换成后面的业务内容。</p>'
    body+='<p>'+true_title_link+'</p><p>当前保守规则要求已识别的目录至少有两个 Item，导航至少两次重复，且是完整短链接。单项目录、带页码导航文字、单次链接与其他语言变体可能保留，后续按真实材料分别扩展。</p>'
    body+=''.join(examples)
    body+='<div class="links">'+link(HERE/'stage-a-verification.zh-CN.md','阶段 A 验收记录 / Verification')+link(HERE/'stage-a-verification.json','完整检查数据 / Data')+'</div></section>'
    body+='<section id="stage-b"><h2>阶段 B · 表格形式的章节标题 <small>Item outline</small></h2><p><b>输入：</b>阶段 A 保留的原文。<b>动作：</b>将短表格标题与原始目录、链接目标及 Part 位置相互核对。<b>输出：</b>v0.1.10 解析包。</p><p>TSMC 原来只有 Part 层级，现在增加 29 个 Item。原表格仍是表格，单元格和证据位置保持原样。</p><div class="links">'+item4link+item18link+'</div>'
    body+='<p class="notice">目录节点表示连续导航范围。Item 17 和 Item 18 通过正文指向后面的财务报表；Item 19 后还有签名、财务索引及 F 页。查找完整财务信息仍须跟随交叉引用，不能把后文一概算作 Exhibits。</p>'
    body+=detail('展开 29 个真实章节 / All Item entries',table(['原文标题','目录页码','导航块范围','原文位置'],all_items))
    body+='<p>章节节点的页码采用已核对的原目录。原文块的历史页码标签本轮未重算，例如 Item 16C 标题块旧标签为 71，原目录与新章节节点为 70；精确引用优先使用块/单元格位置。</p>'
    body+='<div class="links">'+link(HERE/'stage-b-verification.zh-CN.md','阶段 B 验收记录 / Verification')+link(HERE/'stage-b-verification.json','完整检查数据 / Data')+'</div></section>'
    body+='<section id="acceptance"><h2>如何验收 <small>Acceptance</small></h2><ol class="steps"><li><b>独立核对原件</b><span>先从原 DOM 和目录链接固定期望值，不把解析器自己的输出当答案。</span></li><li><b>比较实际产物</b><span>导航仅增加标记；标题仅增加目录识别。两阶段的原文字段、块 ID 和表格内容均保持。</span></li><li><b>验证消费边界和版本</b><span>检查默认 search/read、空返回和续读边界。旧包保留；新版在同环境重建并比较文件。</span></li></ol>'
    body+='<p class="notice">独立基准的 16 个原始用例已全部执行：10 个满足原预期，6 个保守拒识或诊断粒度不足。包括单项目录、缺 Part 或唯一目录锚点等情况；原文保留，但尚未产生预期导航/章节。本轮不把这些限制计作通过，也不据此宣称通用解析已完成。</p>'
    body+='<div class="links">'+link(HERE/'independent-oracle.zh-CN.md','原件核对与边界 / Independent review')+link(HERE/'verification.json','阶段汇总 / Stage checks')+link(HERE/'independent-review.zh-CN.md','独立复查 / Review')+link(HERE/'handoff-check.json','下游完整阅读检查 / Consumer check')+link(HERE/'limitations.zh-CN.md','支持范围补件 / Limits')+'</div><p>这些是离线程序与原件结构检查。全文语义、所有图片/脚注、模型质量、实际 token 节省和通用多格式支持仍未完成。页面的文件与定位链接由程序核对，浏览器视觉审核未执行。</p></section>'
    body+='<section id="source"><h2>产物与版本 <small>Artifacts</small></h2>'+table(['材料','形式','报告期末','范围','最终阅读版'],source_rows)
    for stage,version in [('stage-a','v0.1.9'),('stage-b','v0.1.10')]:
        body+='<h3>'+stage+' · '+version+'</h3><div class="links">'+''.join(link(HERE/f'{stage}-{c}'/'manifest.json',c.upper()+' 文件清单 / Manifest') for c in ('amd','tsmc'))+'</div>'
    body+=detail('固定文件与校验 / Pinned files',pretty(stamps))+'<p>'+link(ROOT/'docs/design/data-agent-acceptance/first-iteration-v1/index.html','上一批：产物小样与锚点修复')+' · '+link(ROOT/'TODO.md','持续更新的任务清单 / TODO')+'</p></section>'
    nav=[('overview','交付概览 / Overview'),('stage-a','阶段 A · 导航'),('stage-b','阶段 B · 章节'),('acceptance','验收依据 / Checks'),('source','产物与版本 / Artifacts')]
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Data Agent · 导航与章节验收</title><style>'+css+'</style><header><b>UTEKI · Data Agent</b><span>逐阶段验收 / Stage acceptance</span></header><div class="workspace"><aside><nav aria-label="验收目录">'+''.join(f'<a href="#{key}">{label}</a>' for key,label in nav)+'</nav></aside><main>'+body+'</main></div></html>'
    PAGE.parent.mkdir(parents=True,exist_ok=True)
    PAGE.write_text(page)
    dom=html.fromstring(page)
    cache={PAGE.resolve():dom}; checked=[]
    for href in dom.xpath('//a/@href'):
        parsed=urlsplit(href)
        assert not parsed.scheme and not parsed.netloc,'Unexpected remote artifact link'
        path=(PAGE.parent/unquote(parsed.path)).resolve() if parsed.path else PAGE.resolve()
        assert path.is_relative_to(ROOT) and path.is_file(),href
        if parsed.fragment:
            if path not in cache:cache[path]=html.fromstring(path.read_bytes())
            assert cache[path].xpath('//*[@id=$id]',id=unquote(parsed.fragment)),href
        checked.append(href)
    result={'kind':'artifact_and_local_link_verification','status':'passed','page_sha256':sha(PAGE),'local_links_checked':len(checked),'details_count':len(dom.xpath('//details')),'browser_visual_review':'not_run','model_calls_by_builder':0,'inputs':stamps,'report_hashes':{s:sha(HERE/f'{s}-verification.json') for s in reports}}
    (HERE/'delivery-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':build()
