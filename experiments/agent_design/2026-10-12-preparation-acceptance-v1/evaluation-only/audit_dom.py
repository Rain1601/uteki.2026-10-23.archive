"""Evaluation-only original-DOM audit. Imports no Uteki parser helpers.
Checks text-node ownership (not word frequencies), independently rebuilt grids,
all block anchors and legal TOC links. Does not establish semantic completeness
of charts or arbitrary XBRL concepts.
"""
import argparse,collections,hashlib,json,re
from pathlib import Path
from lxml import html

norm=lambda s:re.sub(r'\s+',' ',s or '').strip()
sha=lambda b:hashlib.sha256(b).hexdigest()

def tag(e): return e.tag.lower() if isinstance(e.tag,str) else ''
def visible(e):
    for a in [e,*e.iterancestors()]:
        t=tag(a)
        if not t or t in ('script','style','noscript','ix:hidden') or 'hidden' in a.attrib:return False
        declarations={}
        for d in a.get('style','').lower().split(';'):
            if ':' in d:
                k,v=d.split(':',1);declarations[k.strip()]=v.replace('!important','').strip()
        if declarations.get('display')=='none':return False
    return True

def text(e):
    if not visible(e):return ''
    # itertext has no HTML break semantics; independently walk events.
    out=[]
    def walk(n):
        if not visible(n):return
        if tag(n)=='br':out.append(' ')
        if n.text:out.append(n.text)
        for c in n:
            if isinstance(c.tag,str):walk(c)
            if c.tail:out.append(c.tail)
    walk(e);return norm(''.join(out))

def grid(e):
    rows=[r for r in e.iter('tr') if next(r.iterancestors('table'),None) is e and visible(r)]
    cells=[];occupied={};maxcol=0;overlaps=[]
    for ri,r in enumerate(rows):
        col=0
        for c in r:
            if tag(c) not in ('td','th') or not visible(c):continue
            while (ri,col) in occupied:col+=1
            spans=[]
            for key in ('rowspan','colspan'):
                try:spans.append(max(1,int(c.get(key,'1'))))
                except ValueError:spans.append(1)
            rs,cs=spans
            cells.append(dict(text=text(c),row=ri,column=col,rowspan=rs,colspan=cs,is_header=tag(c)=='th'))
            for y in range(ri,ri+rs):
                for x in range(col,col+cs):
                    if (y,x) in occupied:overlaps.append([y,x])
                    occupied[y,x]=1
            col+=cs;maxcol=max(maxcol,col)
    return dict(row_count=len(rows),column_count=maxcol,cells=cells),overlaps

def audit(raw_path,package):
    raw=raw_path.read_bytes();root=html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8',no_network=True));tree=root.getroottree();body=root.find('body');allnodes=list(body.iter());paths={tree.getpath(e):e for e in allnodes if tag(e)}
    blocks=[json.loads(l) for l in (package/'blocks.jsonl').read_text().splitlines()];byid={b['block_id']:b for b in blocks};represented=collections.defaultdict(list);errors=[];table_errors=[];table_overlaps=[]
    for b in blocks:
        e=paths.get(b['dom_path'])
        if e is None:errors.append(dict(block_id=b['block_id'],error='missing_dom'));continue
        represented[e].append(b['block_id'])
        actual=norm(e.get('alt','')) if tag(e)=='img' else text(e)
        if actual!=b['text']:errors.append(dict(block_id=b['block_id'],error='text_diff',raw=actual,parsed=b['text']))
        if sha(b['text'].encode())!=b['text_hash']:errors.append(dict(block_id=b['block_id'],error='hash'))
        if b.get('table'):
            actual_grid,overlap=grid(e)
            if actual_grid!=b['table']:table_errors.append(dict(block_id=b['block_id'],expected=actual_grid,actual=b['table']))
            if overlap:table_overlaps.append(dict(block_id=b['block_id'],overlap=overlap))
    missing=[];multiply=[];counts=collections.Counter();nodes=0;chars=0
    for e in allnodes:
        if not tag(e):continue
        for name,owner,value in [('text',e,e.text),('tail',e.getparent(),e.tail)]:
            if owner is None or not norm(value) or not visible(owner):continue
            # A hidden/comment element's tail is still rendered under its parent.
            if name=='text' and not visible(e):continue
            ids=[bid for a in [owner,*owner.iterancestors()] for bid in represented.get(a,[]) if byid[bid]['type']!='image']
            nodes+=1;chars+=len(norm(value));counts[len(ids)]+=1
            rec=dict(dom_path=tree.getpath(e),slot=name,text=norm(value),owners=ids)
            if not ids:missing.append(rec)
            if len(ids)>1:multiply.append(rec)
    repeats=collections.defaultdict(list)
    for b in blocks:
        if len(b['text'])>=100:repeats[b['text']].append(b['block_id'])
    anchors=json.loads((package/'anchors.json').read_text()) if (package/'anchors.json').exists() else []
    anchor_errors=[]
    for a in anchors:
        e=paths.get(a['dom_path']);bid=a['target_block_id']
        if e is None or a['anchor'] not in (e.get('id'),e.get('name')):anchor_errors.append(dict(anchor=a,error='source_anchor_mismatch'))
        if bid and bid not in byid:anchor_errors.append(dict(anchor=a,error='missing_block'))
        if e is not None and visible(e):
            owners=[bid for p in [e,*e.iterancestors()] for bid in represented.get(p,[]) if byid[bid]['type']!='page_marker' and byid[bid].get('layout_role')!='running_header']
            if owners and bid not in owners:anchor_errors.append(dict(anchor=a,error='wrong_containing_block',expected=owners))
    index=json.loads((package/'index.json').read_text());index_errors=[]
    for n in index['nodes']:
        a,z=byid.get(n['start_block_id']),byid.get(n['end_block_id'])
        if not a or not z or a['ordinal']>z['ordinal']:index_errors.append(n)
    raw_tables=[e for e in allnodes if tag(e)=='table' and visible(e)]
    missing_tables=[tree.getpath(e) for e in raw_tables if e not in represented]
    images=[dict(dom_path=tree.getpath(e),src=e.get('src'),alt=e.get('alt'),represented=e in represented) for e in allnodes if tag(e)=='img' and visible(e)]
    facts=[];fact_errors=[];ids={e.get('id'):e for e in allnodes if tag(e) and e.get('id')}
    for e in allnodes:
        if tag(e)!='ix:nonfraction' or not visible(e):continue
        context=ids.get(e.get('contextref'));unit=ids.get(e.get('unitref'))
        owners=[bid for a in [e,*e.iterancestors()] for bid in represented.get(a,[])]
        fact=dict(dom_path=tree.getpath(e),name=e.get('name'),display=text(e),scale=e.get('scale','0'),sign=e.get('sign'),contextref=e.get('contextref'),unitref=e.get('unitref'),owners=owners)
        if not owners or context is None or unit is None:fact_errors.append(fact)
        facts.append(fact)
    report=dict(schema='independent-dom-preparation-audit-v1',raw=str(raw_path),package=str(package),raw_sha256=sha(raw),parser_version=index['parser_version'],block_count=len(blocks),block_text_errors=errors,visible_text_nodes=nodes,visible_text_chars=chars,text_node_owner_counts=dict(counts),omitted_text_nodes=missing,multiply_represented_text_nodes=multiply,original_repeated_text_groups=[dict(text=k,blocks=v) for k,v in repeats.items() if len(v)>1],table_count=len(raw_tables),missing_tables=missing_tables,table_errors=table_errors,source_table_grid_overlaps=table_overlaps,anchor_count=len(anchors),anchor_errors=anchor_errors,index_nodes=index['nodes'],index_errors=index_errors,index_diagnostics=index['diagnostics'],images=images,visible_inline_fact_count=len(facts),inline_fact_representation_errors=fact_errors,limitations=['Inline HTML visibility checked; external/CSS class computed styles and rendering not evaluated.','Original repeated text is retained; ownership overlap is separately reported.','Images are inventory only: require separate visual/byte audit.','Financial semantic mappings and final numeric normalization require separate record audit.'])
    report['structural_pass']=not any([errors,missing,multiply,missing_tables,table_errors,anchor_errors,index_errors,fact_errors])
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.raw,a.package);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['structural_pass','block_count','visible_text_nodes','text_node_owner_counts','table_count','visible_inline_fact_count']},ensure_ascii=False));print({k:len(r[k]) for k in ['block_text_errors','omitted_text_nodes','multiply_represented_text_nodes','table_errors','anchor_errors','inline_fact_representation_errors']})
