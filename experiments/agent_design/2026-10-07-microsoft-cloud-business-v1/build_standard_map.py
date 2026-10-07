"""Restore approved Mermaid canvas profile; no extraction or factual edits."""
import argparse,json,sys,re,hashlib
from pathlib import Path
from lxml import html as H
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'src'))
from uteki.presentation.business_map_view import mermaid,inline_svg,KIND
from html import escape as esc
PROFILE=ROOT/'skills/uteki-business-diagrams/assets/mermaid-config.json'
def build(base,candidate,output,rendered=False):
 data=json.loads(candidate.read_text());code,view=mermaid(data)
 connected={e[k] for e in view['edges'] for k in ('source','target')}
 others=[n for n in data['businesses'] if view['ids'][n['id']] not in connected]
 projected={**view,'ids':{k:v for k,v in view['ids'].items() if v in connected},'labels':{k:v for k,v in view['labels'].items() if view['ids'][k] in connected}}
 # Remove only unconnected declarations from the primary view. All remain visible
 # as same-ID node controls below, not attached to invented parent edges.
 for n in others:
  token=view['ids'][n['id']];code='\n'.join(line for line in code.split('\n') if not line.startswith('  '+token+'['))
 # Edge details already provide ID/basis. Keep canvas labels short like baseline.
 for e in view['edges']:
  short=re.sub(r'^R\d+ · ','',e['label']).split(' · ')[0]
  short={'包含 / Includes':'包含','报告列示 / Reports':'报告中列示','支撑 / Supports':'支撑'}.get(short,short)
  code=code.replace(e['label'],short);e['label']=short
 mmd=output.parent/'assets/business-standard.mmd';svg=mmd.with_suffix('.svg')
 if not rendered:mmd.write_text(code);print(str(mmd));return
 if mmd.read_text()!=code:raise ValueError('render_current_source_first')
 diagram=inline_svg(svg.read_text(),projected)
 doc=H.fromstring(base.read_text());old=doc.get_element_by_id('graph')
 company=next(n for n in data['businesses'] if n['kind']=='company');segment=next(n for n in data['businesses'] if n['kind']=='reportable_segment')
 buttons=''.join(f'<button class="map-node {esc(n["kind"])}" data-node-key="{view["ids"][n["id"]]}">{esc(n["name"])}</button>' for n in others)
 graph=f'''<section id="graph"><div class="scope"><div><h1>{esc(company['name'])} · {esc(segment['name'])}</h1><p class="caption">业务结构 / Business structure · {esc(data['metadata']['period_end'])} · 仅选定小节 / Selected subsection</p></div><span class="tag">图形待反馈 / View under review</span></div><div class="standard-canvas"><div class="map-toolbar"><span>{len(data['businesses'])} 个节点 · {len(data['relationships'])} 条已记录关系</span><div><button id="map-fit" aria-pressed="true">适合宽度</button><button id="map-original" aria-pressed="false">原始尺寸</button></div></div><div class="map-drawing" id="map-drawing" tabindex="0" aria-label="Mermaid业务结构图">{diagram}</div><div class="map-unplaced"><p><b>本节涉及 · 整体归属待核验 / Placement unresolved</b></p><p class="caption">这些节点有原文依据，但当前候选未建立其整体归属；不挂在公司下冒充同级关系。点击查看业务与证据。</p><div class="map-node-list">{buttons}</div></div></div><p class="caption">可横向滚动查看完整结构；缩放后字号过小时，默认使用原始尺寸。实线：明示 · 虚线：有据推断。公司深色、报告分部蓝色、业务绿色、产品服务白色。点击节点或连线查看依据。<a href="#gaps">{len(data['unknowns'])} 项未决事项 ↗</a></p></section>'''
 old.getparent().replace(old,H.fromstring(graph))
 style=H.Element('style');style.text=(ROOT/'skills/uteki-business-diagrams/assets/canvas.css').read_text();doc.find('head').append(style)
 script=H.Element('script');script.text=(ROOT/'skills/uteki-business-diagrams/assets/canvas.js').read_text();doc.find('body').append(script)
 doc.find('body/header/small').text='统一 Mermaid 基线 / Standard Mermaid view'
 artifacts=doc.get_element_by_id('artifacts');artifacts.insert(1,H.fromstring('<p>本轮仅恢复统一渲染基线，未改提取结果；<a href="assets/business-standard.mmd">当前 Mermaid</a> · <a href="assets/business-standard.svg">当前 SVG</a>。旧文件作为历史保留。</p>'))
 for a in doc.xpath('//a'):
  if a.text in ('Mermaid','SVG'):a.text='历史 / '+a.text
 # Preserve scope and process summaries in a collapsed audit block, not above map.
 details=H.Element('details');summary=H.Element('summary');summary.text='生成过程与范围说明 / Generation context';details.append(summary)
 for child in old:
  if child.get('class') in ('notice','summary','runline'):details.append(child)
 artifacts.insert(2,details)
 output.write_text('<!doctype html>\n'+H.tostring(doc,encoding='unicode'))
 check=H.fromstring(output.read_text());actual=check.xpath('//*[@id="graph"]//*[@data-node-key]/@data-node-key')
 assert len(actual)==len(set(actual))==len(view['ids']) and set(actual)==set(view['ids'].values())
 for href in check.xpath('//a[starts-with(@href,"#")]/@href'):assert check.xpath('//*[@id=$k]',k=href[1:]),href
 report={'profile':'uteki-business-mermaid-v1','data_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),'profile_sha256':hashlib.sha256(PROFILE.read_bytes()).hexdigest(),'all_nodes_preserved':True,'main_edges':len(view['edges']),'unplaced_nodes':[n['id'] for n in others],'unknown_items':len(data['unknowns']),'model_calls':0,'source_unchanged':True,'page_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
 output.with_name('standard-map-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--rendered',action='store_true');a=p.parse_args();build(a.base,a.candidate,a.output,a.rendered)
