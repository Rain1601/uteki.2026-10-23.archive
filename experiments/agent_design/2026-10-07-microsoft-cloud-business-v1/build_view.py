#!/usr/bin/env python3
"""Explicit run -> scoped business acceptance page. Offline; original artifacts stay immutable."""
import argparse
from collections import Counter
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

from lxml import html as lhtml

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from uteki.agents.runtime.strict_json import parse_json_object
from uteki.presentation.business_map_view import BASIS,KIND,RELATION,mermaid,inline_svg

HERE=Path(__file__).resolve().parent
esc=lambda x:html.escape(str(x),quote=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
norm=lambda s:' '.join(s.split())
read=lambda p:parse_json_object(p.read_text())


def local(value):
    path=(ROOT/value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('local_artifact_missing_or_outside_repo')
    return path


def href(path,output,fragment=''):
    return quote(os.path.relpath(path,output),safe='/')+('#'+quote(fragment,safe='') if fragment else '')


def anchor(title,url):
    return f'<a href="{esc(url)}">{esc(title)}</a>'


def validate_execution(data,result,paths,run):
    """Bind a repaired candidate to the untouched failed extraction and actual patch request."""
    meta=data['metadata'];mode=result.get('execution_mode','direct_extraction')
    if meta.get('execution_mode','direct_extraction')!=mode:raise ValueError('execution_mode_mismatch')
    if mode=='direct_extraction':return
    if mode=='typed_field_revision':
        for key in ('parent_run_dir','parent_trace_id','parent_result_sha256','parent_response_sha256','actual_skill_context'):
            if meta.get(key)!=result.get(key) or not result.get(key):raise ValueError('field_revision_lineage_mismatch')
        parent=(ROOT/result['parent_run_dir']).resolve()
        if not parent.is_relative_to(ROOT) or parent==run:raise ValueError('invalid_field_revision_parent')
        for name,key in [('result.json','parent_result_sha256'),('response.txt','parent_response_sha256')]:
            path=local(str(parent/name))
            if sha(path)!=result[key]:raise ValueError('field_revision_parent_hash_mismatch')
            paths['parent-'+name]=path
        if read(parent/'result.json')['trace_id']!=result['parent_trace_id']:raise ValueError('field_revision_trace_mismatch')
        paths['field-changes.json']=local(str(run/'field-changes.json'))
        return
    if mode!='model_patch_repair':raise ValueError('unsupported_execution_mode')
    fields=('parent_run_dir','parent_trace_id','parent_result_sha256','parent_response_sha256',
        'parent_request_sha256','parent_extraction_skill_sha256','repair_system_sha256','patch_schema_sha256','actual_skill_context')
    if any(not result.get(key) or meta.get(key)!=result[key] for key in fields):raise ValueError('repair_lineage_mismatch')
    if result['actual_skill_context']!='parent_extraction_snapshot_not_resent':raise ValueError('repair_skill_context_mismatch')
    parent=(ROOT/result['parent_run_dir']).resolve()
    if parent==run or not parent.is_relative_to(ROOT):raise ValueError('repair_parent_path_mismatch')
    for name,key in [('result.json','parent_result_sha256'),('response.txt','parent_response_sha256'),('request.json','parent_request_sha256')]:
        path=local(str(parent/name))
        if sha(path)!=result[key]:raise ValueError('repair_parent_fingerprint_mismatch')
        paths['parent-'+name]=path
    parent_result=read(paths['parent-result.json'])
    if parent_result.get('trace_id')!=result['parent_trace_id'] or parent_result.get('status')!='failed':raise ValueError('repair_parent_status_mismatch')
    if (parent_result.get('source_packet_sha256')!=result['source_packet_sha256'] or
            parent_result.get('skill_sha256')!=result['parent_extraction_skill_sha256'] or
            result['skill_sha256']!=result['parent_extraction_skill_sha256']):raise ValueError('repair_parent_input_mismatch')
    request=read(paths['request.json'])
    if not isinstance(request.get('system'),str) or hashlib.sha256(request['system'].encode()).hexdigest()!=result['repair_system_sha256']:
        raise ValueError('repair_system_fingerprint_mismatch')
    for name in ('configuration.json','patch_output_schema.json','patch.json','patch-diff.json','patched-draft.json'):
        paths[name]=local(str(run/name))
    if sha(paths['patch_output_schema.json'])!=result['patch_schema_sha256']:raise ValueError('patch_schema_fingerprint_mismatch')


def execution_details(result,paths,output):
    if result.get('execution_mode')=='typed_field_revision':
        return ('<div class="notice"><strong>完整候选 + 两字段模型修正 / Full candidate + typed field revision</strong>'
            '<p>完整候选基于历史稿与冻结原文生成，随后模型补正一项描述引文和一项未知关系说明；程序仅合并字段与引用索引。'
            '这是经过问题反馈的迭代样例，不是首次提取或盲测成功。</p>'+anchor('字段修改记录 / Field changes',href(paths['field-changes.json'],output))+
            ' · '+anchor('父候选 / Parent result',href(paths['parent-result.json'],output))+'</div>')
    if result.get('execution_mode')!='model_patch_repair':
        return '<p class="caption">本次路径 / Execution · 原始提取候选 / Direct extraction candidate</p>'
    parent_trace=anchor(result['parent_trace_id'],'http://127.0.0.1:8765/agent-runs?run='+quote(result['parent_trace_id'],safe=''))
    return ('<div class="notice"><strong>经一次模型局部修正 / One model patch repair</strong>'
        '<p>本候选源于原始提取，再由一次独立模型请求局部修正。原始运行仍记录为失败；这不是原始提取直接成功。'
        'The original failed run remains preserved.</p><p>原始提取 / Parent trace · '+parent_trace+' · '+
        anchor('原始失败记录 / Failed result',href(paths['parent-result.json'],output))+'</p>'
        '<p class="caption">Skill 文件是父提取快照，本次修复未重发该 Skill。修复使用独立的 system、配置和请求。'
        'Skill is a parent snapshot; the patch has its own system and request.</p></div>')


def validate(run,output,review_path):
    paths={name:local(str(run/name)) for name in ('business_map.json','source_packet.json','result.json','skill.md','request.json','manifest.json','evidence.html')}
    data,packet,result=(read(paths[name]) for name in ('business_map.json','source_packet.json','result.json'))
    _,view=mermaid(data)
    meta=data['metadata']
    if result.get('status')!='candidate' or result.get('validation')!='passed':raise ValueError('candidate_run_required')
    if meta.get('extraction_method')!='system_agent':raise ValueError('actual_system_agent_required')
    for key in ('company_id','document_id'):
        if data[key]!=packet[key] or result[key]!=packet[key]:raise ValueError('scope_mismatch')
    if meta['period_end']!=packet['period_end'] or result['period_end']!=packet['period_end']:raise ValueError('period_mismatch')
    if meta['trace_id']!=result['trace_id']:raise ValueError('trace_mismatch')
    for key,name in [('source_packet_sha256','source_packet.json'),('skill_sha256','skill.md')]:
        if meta[key]!=sha(paths[name]) or result[key]!=meta[key]:raise ValueError('input_fingerprint_mismatch')
    if result['request_sha256']!=sha(paths['request.json']):raise ValueError('request_fingerprint_mismatch')
    if result.get('artifacts_sha256',{}).get('business_map.json')!=sha(paths['business_map.json']):raise ValueError('map_fingerprint_mismatch')
    if result['artifacts_sha256'].get('evidence.html')!=sha(paths['evidence.html']):raise ValueError('evidence_fingerprint_mismatch')
    validate_execution(data,result,paths,run)
    if any(n.get('review_status')!='candidate' for n in data['businesses']):raise ValueError('candidate_nodes_required')
    if any(e.get('review_status')!='candidate' for e in data['relationships']):raise ValueError('candidate_relationships_required')
    if meta.get('extraction_scope')!=packet.get('extraction_scope') or not packet.get('extraction_scope'):raise ValueError('section_scope_mismatch')
    paths['source']=local(packet['source_local_path'])
    raw=paths['source'].read_bytes()
    if paths['source'].suffix=='.gz':raw=gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest()!=packet['source_sha256'] or meta['source_sha256']!=packet['source_sha256']:raise ValueError('source_hash_mismatch')
    dom=lhtml.fromstring(raw);tree=dom.getroottree();source_nodes={tree.getpath(e):e for e in dom.iter()}
    by_id={b['id']:b for b in packet['blocks']}
    if len(by_id)!=len(packet['blocks']):raise ValueError('duplicate_packet_block')
    dispositions=meta.get('block_disposition',[])
    if (len(dispositions)!=len(by_id) or {item.get('block_id') for item in dispositions}!=by_id.keys()
            or any(item.get('disposition') not in {'used','context','layout_noise','not_used'}
                or not isinstance(item.get('reason'),str) or not item['reason'].strip() for item in dispositions)):
        raise ValueError('block_disposition_coverage_mismatch')
    for b in packet['blocks']:
        element=source_nodes.get(b['source_dom_path'])
        if element is None or norm(''.join(element.itertext()))!=b['text'] or hashlib.sha256(b['text'].encode()).hexdigest()!=b['text_sha256']:
            raise ValueError('original_source_block_mismatch')
    evidence={};targets={}
    for e in data['evidence']:
        block=by_id.get(e['id']);loc=meta['evidence_locators'].get(e['id'])
        if not block or not loc:raise ValueError('evidence_not_in_selected_packet')
        if (e['support']!=block['text'] or e['text_hash']!=block['text_sha256']
                or loc['source_dom_path']!=block['source_dom_path'] or loc['exact_quote']!=block['text']):
            raise ValueError('evidence_source_mismatch')
        target=local(loc['local_path'])
        if target!=paths['evidence.html']:raise ValueError('evidence_target_mismatch')
        if target not in targets:targets[target]=lhtml.fromstring(target.read_bytes())
        hits=targets[target].xpath('//*[@id=$fragment]',fragment=loc['fragment'])
        if len(hits)!=1 or block['text'] not in norm(' '.join(hits[0].itertext())):raise ValueError('precise_evidence_anchor_mismatch')
        evidence[e['id']]={**e,'href':href(target,output,loc['fragment']),'block':block}
    binding={key:meta[key] for key in ('trace_id','source_packet_sha256','skill_sha256')}
    binding.update(result_sha256=sha(paths['result.json']),business_map_sha256=sha(paths['business_map.json']),request_sha256=sha(paths['request.json']))
    review=None
    if review_path:
        paths['review']=local(str(review_path));review=read(paths['review'])
        if any(review.get('binding',{}).get(k)!=v for k,v in binding.items()):raise ValueError('review_binding_mismatch')
        for c in review['checks']:
            if c['status'] not in {'pass','needs_improvement','gap'} or not set(c.get('source_block_ids',[]))<=by_id.keys():raise ValueError('review_check_mismatch')
    return data,packet,result,view,evidence,paths,binding,review


def sections(data,packet,evidence,view,review,output,paths):
    names={n['id']:n['name'] for n in data['businesses']}
    def refs(excerpts):
        return ''.join('<div class="citation"><blockquote>'+esc(item['quote'])+'</blockquote>'+anchor(
            item['evidence_id']+' · 定位原文 / Source',evidence[item['evidence_id']]['href'])+'</div>' for item in excerpts)
    def node_link(nid):return anchor(names[nid],'#node-'+view['ids'][nid])
    nodes=[]
    fields={'name':'名称 / Name','description':'说明 / Description','products_services':'产品服务 / Product or service',
        'customers':'客户 / Customer','monetization':'收费方式 / Monetization','importance_signals':'重要性说明 / Significance'}
    for n in data['businesses']:
        claims=[]
        for c in n['claim_evidence']:
            value=n[c['field']] if c['item_index'] is None else n[c['field']][c['item_index']]
            basis=''
            if c['field']=='monetization':basis=' · '+BASIS[value['basis']];value=value['description']
            claims.append('<details class="claim"><summary>'+esc(fields[c['field']]+basis)+'<span>'+esc(value)+'</span></summary>'+refs(c['excerpts'])+'</details>')
        for m in n.get('monetization',[]):
            if m['basis']=='unknown':claims.append('<p class="uncertain">'+esc(BASIS['unknown']+' · '+m['description'])+'</p>')
        nodes.append(f'<details class="node-detail" id="node-{view["ids"][n["id"]]}"><summary><span class="tag">{esc(KIND[n["kind"]])}</span> {esc(n["name"])}</summary><p class="muted">{esc(n["id"])} · 候选 / Candidate</p>'+''.join(claims)+
            '<details><summary>节点背景引用 / Context references</summary>'+''.join(anchor(eid,evidence[eid]['href'])+' ' for eid in n['evidence_ids'])+'</details></details>')
    edges=[]
    for i,e in enumerate(data['relationships']):
        key=f'R{i+1:02}'
        edges.append(f'<details class="edge-detail" id="edge-{key}"><summary><span class="tag {esc(e["basis"])}">{esc(BASIS[e["basis"]])}</span> {key} · {esc(names[e["source_id"]])} → {esc(names[e["target_id"]])}</summary>'+f'<p>{esc(RELATION[e["kind"]])} · {esc(e["description"])}</p><p><b>判断依据 / Rationale</b> · {esc(e["rationale"])}</p>'+refs(e['excerpts'])+
            ('<p class="uncertain">关系未确定，未作为图中连线。Unresolved; no asserted graph edge.</p>' if e['basis']=='unknown' else '')+'</details>')
    gaps=''.join('<li><b>'+esc(g['question'])+'</b><p>'+esc(g['reason_unanswered'])+'</p>'+ ' · '.join(node_link(nid) for nid in g['related_business_ids'])+'</li>' for g in data['unknowns'])
    blockrows=[]
    dispositions=data['metadata'].get('block_disposition',[])
    roles={'selected_subsection':'选定小节 / Selected subsection','scope_metadata':'身份与报告期上下文 / Scope metadata'}
    for d in dispositions:
        block=next(b for b in packet['blocks'] if b['id']==d['block_id'])
        role=roles.get(block.get('input_role'),'未标注角色 / Role not recorded')
        blockrows.append('<details><summary>'+esc(d['block_id']+' · '+role)+'</summary><p><b>模型自报 / Model report · '+esc(d['disposition'])+'</b> · '+esc(d['reason'])+'</p><blockquote>'+esc(block['text'])+'</blockquote><code>'+esc(block['source_dom_path'])+'</code></details>')
    counts=Counter(b.get('input_role') for b in packet['blocks'])
    role_summary=' · '.join(f'{label}: {counts[role]}' for role,label in roles.items())
    scope='<p>'+esc(packet['extraction_scope']['title'])+' · '+str(len(packet['blocks']))+' 块 / blocks</p><p>'+esc(role_summary)+'</p><p class="muted">输入角色由调用者确定；模型自报的处理状态不等于逐项内容验收。Input roles define scope; model-reported handling is not semantic coverage proof.</p>'+''.join(blockrows)
    if review:
        checks=''.join('<details><summary>'+esc(c['label']+' · '+c['status'])+'</summary><p>'+esc(c.get('observation',c.get('actual','')))+' '+esc(c.get('note',''))+'</p>'+''.join(
            '<details><summary>'+esc(bid)+'</summary><blockquote>'+esc(next(b['text'] for b in packet['blocks'] if b['id']==bid))+'</blockquote></details>' for bid in c.get('source_block_ids',[]))+'</details>' for c in review['checks'])
        review_html='<p>'+esc(review['summary'])+'</p><p class="muted">'+esc(review.get('review_method','未记录'))+'</p>'+checks+'<ul>'+''.join('<li>'+esc(x)+'</li>' for x in review.get('limitations',[]))+'</ul>'
    else:review_html='<p>内容复核尚未附上。Schema checks do not establish semantic acceptance.</p>'
    return {'NODES':''.join(nodes),'EDGES':''.join(edges),'GAPS':gaps or '<li>候选未列出具体缺口；这不证明输入完整。</li>',
            'SCOPE':scope,'REVIEW':review_html}


def build(run,output,review_path=None,with_svg=False):
    run=run.resolve();output=output.resolve()
    if not output.is_relative_to(ROOT):raise ValueError('output_outside_project')
    data,packet,result,view,evidence,paths,binding,review=validate(run,output,review_path)
    code,_=mermaid(data)
    output.mkdir(parents=True,exist_ok=True);assets=output/'assets';assets.mkdir(exist_ok=True)
    mmd=assets/'business.mmd';svg=assets/'business.svg'
    if with_svg and (not mmd.exists() or mmd.read_text()!=code):raise ValueError('render_current_mermaid_first')
    mmd.write_text(code);(assets/'business-ids.json').write_text(json.dumps(view,ensure_ascii=False,indent=2)+'\n')
    if not with_svg:
        print(json.dumps({'status':'mermaid_prepared_svg_pending','mermaid':str(mmd)}));return
    diagram=inline_svg(svg.read_text(),view)
    values=sections(data,packet,evidence,view,review,output,paths)
    company=next(n for n in data['businesses'] if n['kind']=='company')
    review_counts=Counter(c['status'] for c in review['checks']) if review else Counter()
    if review_counts['needs_improvement'] or review_counts['gap']:
        quality='候选待修 / Candidate needs work'
        quality_note=f'本次复核：{review_counts["needs_improvement"]} 项需改进，{review_counts["gap"]} 项缺口。具体问题见内容复核；这份产物尚未通过内容验收。'
        semantic_status='needs_work'
    elif review and review['checks']:
        quality='已复核候选 / Reviewed candidate'
        quality_note='已附本次内容复核，产物仍为候选。复核范围与限制见下方记录；这不表示全报告覆盖或生产采纳。'
        semantic_status='reviewed_candidate'
    else:
        quality='候选待复核 / Candidate awaiting review'
        quality_note='内容复核尚未完成。格式、引用与制图检查不能代替内容验收。Semantic review is pending.'
        semantic_status='not_evaluated'
    values.update(TITLE=esc(company['name']+' · '+packet['extraction_scope']['title']),SUMMARY=esc(data['summary']),
        QUALITY=esc(quality),QUALITY_NOTE=esc(quality_note),
        EXECUTION=execution_details(result,paths,output),
        PERIOD=esc(packet['period_end']),TRACE=esc(data['metadata']['trace_id']),DIAGRAM=diagram,
        TRACE_URL=esc('http://127.0.0.1:8765/agent-runs?run='+quote(data['metadata']['trace_id'],safe='')),
        COUNTS=esc(f'{len(data["businesses"])} 节点 / nodes · {len(view["edges"])} 已声明关系 / asserted edges · {len(view["unresolved"])} 未决关系 / unresolved'),
        ARTIFACTS=' '.join(anchor('父提取 Skill 快照 / Parent Skill snapshot' if name=='skill.md' and result.get('execution_mode')=='model_patch_repair' else name,
            href(path,output)) for name,path in {**paths,'Mermaid':mmd,'SVG':svg}.items()),
        BINDING=esc(json.dumps(binding,ensure_ascii=False,indent=2)))
    page=(HERE/'page-template.html').read_text()
    for key,value in values.items():page=page.replace('<!-- '+key+' -->',value)
    (output/'index.html').write_text(page)
    doc=lhtml.fromstring(page);seen=Counter(doc.xpath('//*[@id]/@id'))
    if any(v!=1 for v in seen.values()):raise ValueError('duplicate_page_id')
    checked=[]
    for url in doc.xpath('//a/@href'):
        if url.startswith('http'):continue
        from urllib.parse import unquote,urlsplit
        parsed=urlsplit(url);target=output/unquote(parsed.path) if parsed.path else output/'index.html'
        if not target.is_file():raise ValueError('broken_local_link')
        if parsed.fragment and target.suffix=='.html':
            targetdoc=doc if target==output/'index.html' else lhtml.fromstring(target.read_bytes())
            if len(targetdoc.xpath('//*[@id=$f]',f=unquote(parsed.fragment)))!=1:raise ValueError('broken_fragment')
        checked.append(url)
    verification={'status':'rendered_candidate','schema_version':'business-map-page-check-v1','binding':binding,
        'execution_mode':result.get('execution_mode','direct_extraction'),'parent_trace_id':result.get('parent_trace_id'),
        'nodes':len(data['businesses']),'asserted_edges':len(view['edges']),'unresolved_edges':len(view['unresolved']),
        'source_blocks_verified':len(packet['blocks']),'evidence_fragments_verified':len(evidence),
        'local_links_checked':len(checked),'review_attached':review is not None,'model_calls':0,
        'svg_mapping_checked':True,'browser_visual_review':'not_performed','semantic_acceptance':semantic_status,
        'files':{name:sha(path) for name,path in {'html':output/'index.html','svg':svg,'mermaid':mmd,'builder':Path(__file__),
            'template':HERE/'page-template.html','renderer':ROOT/'src/uteki/presentation/business_map_view.py'}.items()}}
    (output/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(verification,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--review',type=Path);parser.add_argument('--with-svg',action='store_true')
    args=parser.parse_args();build(args.run,args.output,args.review,args.with_svg)
