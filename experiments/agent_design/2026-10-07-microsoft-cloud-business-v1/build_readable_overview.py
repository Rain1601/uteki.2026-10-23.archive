"""Presentation-only layered map over an explicitly selected reviewed candidate."""
import argparse,hashlib,json,html
from pathlib import Path
from lxml import html as H
esc=lambda x:html.escape(str(x),quote=True)
def build(base,candidate,output):
 data=json.loads(candidate.read_text());nodes={n['id']:n for n in data['businesses']};ids={k:f'N{i:03}' for i,k in enumerate(nodes)}
 segments=[n for n in nodes.values() if n['kind']=='reportable_segment']
 if len(segments)!=1:raise ValueError('select_one_segment_for_this_view')
 segment=segments[0];children={k:[] for k in nodes};parent={};edge_index={}
 for i,e in enumerate(data['relationships']):
  if e['kind'] not in ('part_of','reported_under') or e['basis']=='unknown':continue
  a,b=e['source_id'],e['target_id']
  if a in parent:raise ValueError('multiple_parents_require_linked_view')
  children[b].append(a);parent[a]=b;edge_index[a]=(i,e['basis'])
 seen=set()
 def link(n):return f'<a href="#node-{ids[n["id"]]}">{esc(n["name"])}</a>'
 def facts(n):
  products=n.get('products_services',[])
  text='<ul class="product-list">'+''.join('<li>'+esc(p)+'</li>' for p in products)+'</ul>' if products else ''
  if n.get('customers'):text+='<p class="audience"><b>服务对象 / Customers</b> '+esc(' · '.join(n['customers']))+'</p>'
  return text
 def node(k,depth=0):
  if k in seen:raise ValueError('cycle_or_duplicate')
  seen.add(k);n=nodes[k];idx,basis=edge_index[k]
  badge='原文明示 / Explicit' if basis=='explicit' else '有据推断 / Derived'
  cls='derived' if basis=='derived' else 'explicit'
  return f'<article class="business-unit depth-{depth} {cls}" data-business-id="{esc(k)}"><div class="unit-title"><h3>{link(n)}</h3><a class="relation-proof" href="#edge-R{idx+1:02}">{badge} ↗</a></div><p class="unit-description">{esc(n["description"])}</p>'+facts(n)+('<div class="child-grid">'+''.join(node(x,depth+1) for x in children[k])+'</div>' if children[k] else '')+'</article>'
 primary=''.join(node(k) for k in children[segment['id']]);seen.add(segment['id'])
 others=[n for n in nodes.values() if n['id'] not in seen and n['kind']!='company']
 cards=''.join('<article class="related-unit" data-business-id="'+esc(n['id'])+'"><h3>'+link(n)+'</h3><p>'+esc(n['description'])+'</p>'+facts(n)+'</article>' for n in others)
 graph=f'''<section id="graph" class="readable-map"><p class="eyebrow">业务结构 / BUSINESS STRUCTURE · {esc(data['metadata']['period_end'])}</p><h1>{esc(segment['name'])}</h1><p class="scope-note">{esc(next(n['name'] for n in nodes.values() if n['kind']=='company'))} · 仅展示所选报告小节，不是公司全部业务 / Selected subsection only</p><div class="segment-root"><strong>{link(segment)}</strong><span>{esc(segment['description'])}</span></div><div class="branch-label">主要业务构成 / Main business groups</div><div class="business-branches">{primary}</div><div class="related-heading"><h2>小节中的其他具名业务 / Other named businesses</h2><p>下列业务均有原文描述；当前产物未确定其整体归属。独立摆放不表示业务独立，也不代表它们属于同一业务线。</p></div><div class="related-grid">{cards}</div><p class="map-footnote">{len(nodes)} 个业务及上下文节点 · {len(data['relationships'])} 条已记录关系 · {len(data['unknowns'])} 项未决事项。<a href="#gaps">查看未决说明 ↗</a><br>分组与连接保留原候选的依据等级；节点面积不表示收入。点击名称查看逐字段引文，点击关系标签查看关系依据。</p></section>'''
 doc=H.fromstring(base.read_text());old=doc.get_element_by_id('graph');old.getparent().replace(old,H.fromstring(graph))
 style=H.Element('style');style.text='''
.readable-map{max-width:1400px}.readable-map h1{font-size:30px;margin:2px 0 5px}.eyebrow{font-size:11px;letter-spacing:.1em;color:#61736a;margin:0}.scope-note{font-size:12px;color:#6b655d;margin-bottom:20px}.segment-root{background:#263c46;color:#fff;padding:16px 20px;display:flex;gap:20px;align-items:center;border-radius:7px}.segment-root strong{min-width:160px;font-size:19px}.segment-root a{color:inherit;text-decoration:none}.segment-root span{font-size:14px;line-height:1.7}.branch-label{text-align:center;font-size:12px;color:#66796d;padding:15px 0;position:relative}.branch-label:before{content:'';display:block;height:16px;border-left:1px solid #a4b8a7;position:absolute;left:50%;top:0;transform:translateY(-1px)}.business-branches{display:grid;grid-template-columns:minmax(0,2fr) minmax(220px,1fr);gap:18px;align-items:start}.business-unit{border:1px solid #bccac2;border-top:3px solid #698d78;background:white;border-radius:5px;padding:15px;min-width:0}.business-unit.derived{border-top-style:dashed}.unit-title{display:flex;flex-direction:column;gap:5px}.unit-title h3{font-size:17px;line-height:1.4;margin:0}.unit-title h3 a,.related-unit h3 a{color:#244436;text-decoration:none}.unit-title h3 a:hover,.related-unit h3 a:hover{text-decoration:underline}.relation-proof{font-size:11px;color:#6a786f}.unit-description{font-size:14px;margin:10px 0;line-height:1.65}.product-list{padding-left:17px;font-size:13px;line-height:1.65;margin:10px 0}.product-list li{margin:5px 0;overflow-wrap:anywhere}.depth-2>.product-list{display:flex;flex-wrap:wrap;gap:5px;padding:0;list-style:none}.depth-2>.product-list li{padding:2px 6px;background:#edf2ed;border-radius:3px;margin:0}.audience{font-size:12px;color:#645e55;line-height:1.7;margin-bottom:0}.audience b{display:block;font-weight:500;color:#374e42}.child-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:18px;padding-top:15px;border-top:1px solid #c5d0c9}.depth-1{background:#f5f8f4;padding:12px}.depth-1 h3{font-size:15px}.depth-1 .child-grid{display:block;border:0;padding:0}.depth-2{margin-top:14px;padding:12px;background:white}.depth-2 h3{font-size:15px}.related-heading{margin-top:32px;border-top:1px solid #ded8cf;padding-top:22px}.related-heading h2{font-size:18px;margin:0 0 6px}.related-heading p{font-size:13px;color:#76644b;max-width:850px}.related-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.related-unit{border:1px solid #dfd4c4;background:#fbf7f0;border-radius:5px;padding:15px}.related-unit h3{font-size:16px;margin:0 0 10px}.related-unit p{font-size:13px;line-height:1.7}.map-footnote{font-size:12px;color:#6b655d;margin-top:18px}.workspace{grid-template-columns:155px minmax(0,1fr)}main{padding:22px}aside{padding:20px 9px}.readable-map .business-unit:has(>.child-grid)>.product-list{display:none}@media(max-width:1100px){.business-branches{grid-template-columns:minmax(0,1.7fr) minmax(210px,1fr)}.related-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.business-branches,.related-grid{grid-template-columns:1fr}.segment-root{display:block}.segment-root span{display:block;margin-top:8px}.workspace{grid-template-columns:120px minmax(0,1fr)}main{padding:14px}.child-grid{grid-template-columns:1fr}}'''
 # Do not hide a parent's product facts: subsets can be absent from child entities.
 style.text=style.text.replace('.readable-map .business-unit:has(>.child-grid)>.product-list{display:none}','')
 doc.find('head').append(style)
 doc.get_element_by_id('artifacts').insert(1,H.fromstring('<p>本候选来自完整稿修订及两项模型字段修正；本轮仅重排展示，未调用模型。原始审阅、修改记录与文件指纹见下方。</p>'))
 for anchor in doc.xpath('//a'):
  if anchor.text in ('Mermaid','SVG'):anchor.text='旧版关系图 / '+anchor.text
 header=doc.find('body/header/small');header.text='内容已复核 · 图形待确认 / View under review'
 footer=doc.find('.//footer');footer.text='选定业务小节的候选。业务数据和引文保持原样；展示改为分层业务概览。内容复核与视觉认可分开。'
 output.write_text('<!doctype html>\n'+H.tostring(doc,encoding='unicode'))
 rendered=H.fromstring(output.read_text()); displayed=rendered.xpath('//*[@data-business-id]/@data-business-id')
 expected=set(nodes)-{n['id'] for n in nodes.values() if n['kind'] in ('company','reportable_segment')}
 assert set(displayed)==expected and len(displayed)==len(expected)
 for a in rendered.xpath('//a[starts-with(@href,"#")]/@href'):
  assert rendered.xpath('//*[@id=$id]',id=a[1:]),a
 verification={'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),'node_ids_rendered':displayed,'related_without_confirmed_parent':[n['id'] for n in others],'unknown_items':len(data['unknowns']),'model_calls':0,'data_mutated':False,'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
 output.with_name('overview-verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n');print(json.dumps(verification))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.base,a.candidate,a.output)
