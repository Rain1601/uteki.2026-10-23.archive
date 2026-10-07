"""Explicit-case BusinessMap -> Mermaid and local review page. No model calls."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from lxml import html as lhtml

from uteki.domain.business_map.models import business_map_from_dict

KIND = {'company':'公司','reportable_segment':'报告分部','business':'业务 / 平台',
        'offering_group':'产品 / 服务','revenue_line':'收入分类'}
# Domain edges point child -> parent; the drawing expands parent -> child.
# This is a reading orientation, never a claim about money or execution order.
INVERSE = {'part_of':'包含','reported_under':'报告中列示','revenue_component_of':'收入构成','supports':'支撑来自'}
ROOT = Path(__file__).resolve().parents[3]


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def escaped(value): return html.escape(str(value), quote=True)
def label(value):
    return str(value).replace('"','#quot;').replace('<','#lt;').replace('>','#gt;').replace('\n',' ')
def local_path(value):
    root=ROOT.resolve();path=(root/value).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('missing_or_outside_repo_source: '+str(value))
    return path
def link(path, output, fragment=''):
    return os.path.relpath(path,output)+('#'+fragment if fragment else '')


def validate(path):
    data=json.loads(path.read_text())
    model=business_map_from_dict(data)
    meta=data['metadata']
    for field in ('report_label','period_end','source_local_path','source_url','source_sha256','evidence_locators'):
        if not meta.get(field):raise ValueError('missing_metadata: '+field)
    source=local_path(meta['source_local_path'])
    source_bytes=gzip.decompress(source.read_bytes()) if source.suffix=='.gz' else source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest()!=meta['source_sha256']:raise ValueError('source_hash_mismatch')
    if meta.get('source_html_path'):
        if local_path(meta['source_html_path']).read_bytes()!=source_bytes:raise ValueError('html_copy_not_identical')
    if meta.get('original_source_path'):
        if sha(local_path(meta['original_source_path']))!=meta.get('original_source_sha256'):
            raise ValueError('original_source_hash_mismatch')
    if meta.get('extraction_method')!='codex_source_review':raise ValueError('unexpected_extraction_method')
    if len([n for n in data['businesses'] if n['kind']=='company'])!=1:raise ValueError('one_company_required')
    for node in data['businesses']:
        if not node['evidence_ids'] or node.get('review_status')!='candidate':raise ValueError('node_missing_evidence_or_wrong_status')
    for edge in data['relationships']:
        if not edge['evidence_ids'] or edge.get('review_status')!='candidate':raise ValueError('edge_missing_evidence_or_wrong_status')
    source_soup=lhtml.fromstring(source_bytes)
    normalize=lambda text: ' '.join(text.split())
    source_texts=[normalize(joiner.join(source_soup.itertext())) for joiner in ('',' ')]
    targets={}
    for evidence in data['evidence']:
        if evidence['document_id']!=data['document_id']:raise ValueError('cross_document_evidence')
        loc=meta['evidence_locators'][evidence['id']]
        target=local_path(loc['local_path'])
        if not loc.get('fragment') or not loc.get('exact_quote'):raise ValueError('precise_evidence_required')
        if target not in targets:targets[target]=lhtml.fromstring(target.read_bytes())
        matches=targets[target].xpath('//*[@id=$fragment or @name=$fragment]',fragment=loc['fragment'])
        if len(matches)!=1:raise ValueError('missing_or_duplicate_evidence_anchor: '+loc['fragment'])
        element=matches[0]
        quote=normalize(loc['exact_quote'])
        if quote not in normalize(' '.join(element.itertext())):
            raise ValueError('quote_not_in_anchored_fragment: '+evidence['id'])
        if not any(quote in text for text in source_texts):raise ValueError('quote_not_in_source: '+evidence['id'])
    return data,model


def presentation_edges(data):
    if data.get('schema_version') == 'business-map-v0.2':
        raise ValueError('business_map_v2_display_requires_basis_aware_renderer')
    result=[]
    for edge in data['relationships']:
        market=edge['kind']=='supports' and data['metadata'].get('node_roles',{}).get(edge['target_id'])=='market'
        result.append({'source':edge['source_id'] if market else edge['target_id'],
                       'target':edge['target_id'] if market else edge['source_id'],
                       'label':'面向市场' if market else INVERSE[edge['kind']],
                       'kind':edge['kind'],'evidence_ids':edge['evidence_ids']})
    return result


def layer_ranks(data):
    edges=presentation_edges(data)
    incoming={n['id']:0 for n in data['businesses']};ranks={n:0 for n in incoming}
    for edge in edges:incoming[edge['target']]+=1
    queue=[n for n,count in incoming.items() if count==0];visited=[]
    while queue:
        current=queue.pop(0);visited.append(current)
        for edge in edges:
            if edge['source']!=current:continue
            target=edge['target'];ranks[target]=max(ranks[target],ranks[current]+1);incoming[target]-=1
            if incoming[target]==0:queue.append(target)
    # A cyclic network may still have a valid relationship view. Never force it
    # into a hierarchy by deleting real edges.
    return ranks if len(visited)==len(incoming) else None


def mermaid(data):
    ids={node['id']:f'N{i:03}' for i,node in enumerate(data['businesses'])}
    lines=['flowchart LR','  accTitle: '+label(data['metadata']['report_label'])+' business map',
           '  accDescr: Source-grounded candidate business structure. Edge labels define the relationship.']
    for node in data['businesses']:
        display=data['metadata'].get('node_labels',{}).get(node['id'],{}).get('zh') or node['name']
        role=data['metadata'].get('node_roles',{}).get(node['id'])
        style='market' if role=='market' else node['kind']
        lines.append(f'  {ids[node["id"]]}["{label(display)}"]:::{style}')
    for edge in presentation_edges(data):
        # Preserve the semantic relation via its inverse label. Dotted supports
        # edges distinguish technical support from a company ownership tree.
        arrow='-.->' if edge['kind']=='supports' else '-->'
        lines.append(f'  {ids[edge["source"]]} {arrow}|"{edge["label"]}"| {ids[edge["target"]]}')
    lines += ['  classDef company fill:#263c46,color:#fff,stroke:#263c46,stroke-width:1.5px',
              '  classDef reportable_segment fill:#e4eef2,color:#203c49,stroke:#91aeba,stroke-width:1px',
              '  classDef business fill:#eaf1e9,color:#2b4432,stroke:#a4b8a7,stroke-width:1px',
              '  classDef offering_group fill:#fff,color:#302c26,stroke:#c9c2b7,stroke-width:1px',
              '  classDef revenue_line fill:#f7eddc,color:#58442c,stroke:#c9b691,stroke-width:1px',
              '  classDef market fill:#f1edf7,color:#473857,stroke:#b7a6c8,stroke-width:1px,stroke-dasharray:4 3']
    return '\n'.join(lines)+'\n',ids


def inline_svg(path, data, ids):
    svg=ET.fromstring(path.read_text())
    reverse={value:key for key,value in ids.items()}
    names={n['id']:data['metadata'].get('node_labels',{}).get(n['id'],{}).get('zh') or n['name'] for n in data['businesses']}
    seen=set()
    for element in svg.iter():
        if element.tag.split('}')[-1] in ('script','foreignObject'):raise ValueError('active_svg_not_allowed')
        if any(key.lower().startswith('on') for key in element.attrib):raise ValueError('svg_handler_not_allowed')
        if element.tag.split('}')[-1]=='g' and 'node' in element.get('class','').split():
            match=re.fullmatch(r'flowchart-(N\d+)-\d+',element.get('id',''))
            if match:
                node_id=reverse[match[1]];seen.add(node_id)
                actual=' '.join(''.join(e.itertext()) for e in element.iter() if e.tag.split('}')[-1]=='text')
                if ''.join(actual.split())!=''.join(names[node_id].split()):raise ValueError('svg_label_mismatch: '+node_id)
                element.set('data-node-id',node_id);element.set('tabindex','0');element.set('role','button')
                element.set('aria-label','查看 '+names[node_id]+' 的信息与依据')
    if seen!=set(names):raise ValueError('svg_node_mismatch')
    # Each embedded graph needs unique DOM IDs (including marker/style IDs).
    raw=ET.tostring(svg,encoding='unicode')
    for old in sorted({e.get('id') for e in svg.iter() if e.get('id')},key=len,reverse=True):
        new=data['company_id']+'-'+old
        raw=raw.replace('id="'+old+'"','id="'+new+'"').replace('#'+old, '#'+new)
    # Register the SVG namespace for valid HTML embedding without ns0 prefixes.
    ET.register_namespace('','http://www.w3.org/2000/svg')
    raw=ET.tostring(ET.fromstring(raw),encoding='unicode')
    return raw


def build(inputs,output,with_svg=False):
    output.mkdir(parents=True,exist_ok=True)
    assets=output/'assets';assets.mkdir(exist_ok=True)
    maps=[];sections=[];checks=[]
    for path in inputs:
        data,_=validate(path)
        mmd,ids=mermaid(data)
        folder=path.parent
        (folder/'business-map.mmd').write_text(mmd)
        (assets/(data['company_id']+'.mmd')).write_text(mmd)
        diagram_path=assets/(data['company_id']+'.svg')
        meta=data['metadata']
        public={**data,'presentation_edges':presentation_edges(data),'layer_ranks':layer_ranks(data),
                'source_href':link(local_path(meta.get('source_html_path',meta['source_local_path'])),output),
                'json_href':link(path,output), 'readme_href':link(folder/'README.zh-CN.md',output)}
        for e in public['evidence']:
            loc=meta['evidence_locators'][e['id']]
            e['href']=link(local_path(loc['local_path']),output,loc['fragment'])
            e['quote']=loc['exact_quote']
        maps.append(public)
        if with_svg:
            rendered=inline_svg(diagram_path,data,ids)
            company=data['company_id']
            sections.append(f'<section class="map-section" data-company="{escaped(company)}" hidden><div class="diagram-scroll" tabindex="0" aria-label="{escaped(company)}业务图">{rendered}</div></section>')
        checks.append({'company_id':data['company_id'],'report':meta['report_label'],'period_end':meta['period_end'],
            'nodes':len(data['businesses']),'relationships':len(data['relationships']),'evidence':len(data['evidence']),
            'input_sha256':sha(path),'mermaid_sha256':sha(folder/'business-map.mmd'),
            'source_sha256':meta['source_sha256'],'svg_sha256':sha(diagram_path) if with_svg else None})
    if len({d['company_id'] for d in maps})!=len(maps):raise ValueError('duplicate_company_scope')
    if with_svg:
        template=(Path(__file__).parent/'view-template.html').read_text()
        payload=json.dumps(maps,ensure_ascii=False).replace('<','\\u003c').replace('&','\\u0026')
        template=template.replace('<!-- DIAGRAMS -->',''.join(sections)).replace('/* DATA */',payload)
        (output/'index.html').write_text(template)
    result={'schema_version':'business-map-mermaid-review-v1','extraction':'Codex source review, candidate',
        'model_api_calls':0,'graph_generation':'BusinessMap → Mermaid → SVG','cases':checks,
        'checks':{'existing_business_map_contract':True,'node_and_edge_evidence':True,'source_hashes':True,'source_and_fragment_quotes':True,
                  'evidence_anchors':True,'svg_node_mapping':with_svg},
        'not_claimed':['Production agent extraction','Complete annual-report coverage','Cross-period comparability','User visual approval','Claude review']}
    (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'cases':len(checks),'with_svg':with_svg,'nodes':sum(c['nodes'] for c in checks)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maps',type=Path,nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--with-svg',action='store_true')
    args=parser.parse_args()
    build(args.maps,args.output,args.with_svg)
