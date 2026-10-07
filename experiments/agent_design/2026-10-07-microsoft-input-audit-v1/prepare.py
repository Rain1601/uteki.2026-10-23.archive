"""Explicit source/input audit; no model invocation or expected answers in packet."""
import json,hashlib,copy
from pathlib import Path
from lxml import html
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
OLD=ROOT/'experiments/agent_design/2026-10-07-microsoft-cloud-business-v1'
sha=lambda b:hashlib.sha256(b).hexdigest()
def save(name,data):
 raw=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode();p=HERE/name
 if p.exists() and p.read_bytes()!=raw:raise ValueError('immutable audit output changed')
 p.write_bytes(raw)
p=json.loads((OLD/'input/source_packet.json').read_text());r=json.loads((OLD/'complete-candidate-v3/request.json').read_text())
wire=json.loads(r['messages'][0]['content']); assert p==wire
original=(ROOT/p['source_local_path']).read_bytes();assert sha(original)==p['source_sha256']
index=[json.loads(x) for x in (ROOT/'data/company_workspace/extraction_ab_v1/corpus/msft/dataset/indexes/msft-2025-10k/blocks.jsonl').read_text().splitlines()]
dom=html.fromstring(original);tree=dom.getroottree();paths={tree.getpath(e):e for e in dom.iter()}
for b in p['blocks']:assert ' '.join(''.join(paths[b['source_dom_path']].itertext()).split())==b['text']
selected=[b for b in index if b['ordinal'] in (6,8) or 85<=b['ordinal']<186]
assert next(b for b in index if b['ordinal']==85)['text']=='OPERATING SEGMENTS'
assert next(b for b in index if b['ordinal']==186)['text']=='HUMAN CAPITAL RESOURCES'
blocks=[];heading='OPERATING SEGMENTS'
for b in selected:
 text=' '.join(''.join(paths[b['dom_path']].itertext()).split());assert text==b['text'] and sha(text.encode())==b['text_hash']
 if b['ordinal'] in (90,117,143):heading=text
 blocks.append(dict(id=b['block_id'],ordinal=b['ordinal'],type=b['type'],text=text,text_sha256=b['text_hash'],source_dom_path=b['dom_path'],section_path=['Form 10-K','Item 1. Business','Operating Segments',heading],reported_page=b['reported_page'],input_role='scope_metadata' if b['ordinal'] in (6,8) else 'selected_subsection'))
texts=dom.xpath('//text()'); start=paths[next(b['dom_path'] for b in index if b['ordinal']==85)];end=paths[next(b['dom_path'] for b in index if b['ordinal']==186)]
def offset(e):return next(i for i,t in enumerate(texts) if not t.is_tail and (t.getparent() is e or e in t.getparent().iterancestors()))
nonwhite=lambda t:''.join(t.split())
assert nonwhite(''.join(str(t) for t in texts[offset(start):offset(end)]))==nonwhite(''.join(b['text'] for b in blocks if b['input_role']=='selected_subsection'))
new=copy.deepcopy(p);new['blocks']=blocks;new['extraction_scope'].update(title='Item 1. Business / Operating Segments (all three segments)',start_ordinal=85,end_ordinal_inclusive=185,end_boundary_exclusive_ordinal=186,end_boundary_exclusive_title='HUMAN CAPITAL RESOURCES',section_block_ids=[b['id'] for b in blocks if b['input_role']=='selected_subsection'],scope_metadata_block_ids=[b['id'] for b in blocks if b['input_role']=='scope_metadata'],instruction='Extract the entire selected Operating Segments section covering all three segments. Preserve business and product relationships with evidence and distinguish explicit facts from grounded inference. This is reported business coverage, not a claim to include every product Microsoft sells.')
save('clean-source-packet.json',new)
report=dict(source_sha256=p['source_sha256'],old_request_sha256=sha((OLD/'complete-candidate-v3/request.json').read_bytes()),old_packet_equals_request=True,old_blocks=len(p['blocks']),old_blocks_match_original=True,new_blocks=len(blocks),new_contiguous_section_blocks=101,new_section_dom_text_equal=True,new_packet_sha256=sha((HERE/'clean-source-packet.json').read_bytes()),old_scope=p['extraction_scope']['title'],new_scope=new['extraction_scope']['title'],api_calls=0,old_request_contains_prior_candidate='<prior_candidate_data>' in r['system'],old_request_locks_twelve_nodes='Preserve all 12 existing node IDs' in r['system'],new_packet_contains_no_prior_candidate=True)
save('verification.json',report)
(HERE/'operating-segments.txt').write_text('\n\n'.join(f"[{b['id']}] {b['text']}" for b in blocks))
print(json.dumps(report,ensure_ascii=False))
