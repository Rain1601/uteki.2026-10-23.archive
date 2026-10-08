from pathlib import Path
import json,hashlib,re
from lxml import html
P=Path(__file__).resolve().parent
E=P.parents[1]
NEW=E/'datasets/msft-acquired-fy2025'
source_id='source-360182cbf562dcf9a8ab9c4e'
idx=NEW/'indexes'/source_id
newsource=json.loads((idx/'source.json').read_text())
oldref=json.loads((P/'reference.json').read_text())
rawpath=E/'acquisition/workspace/sources/objects/56d41ecc0adc114c7fcda813d41f5911b244a7e448b545f6dca52dfba9801008.bin'
oldpath=E.parent/'2026-10-09-data-agent-completion-v1/datasets/msft/raw/msft-2025-10k.html'
a=oldpath.read_bytes();b=rawpath.read_bytes()
assert hashlib.sha256(b).hexdigest()==newsource['raw_sha256']
prefix=0
while prefix<min(len(a),len(b)) and a[prefix]==b[prefix]:prefix+=1
suffix=0
while suffix<min(len(a),len(b))-prefix and a[-suffix-1]==b[-suffix-1]:suffix+=1
old=html.fromstring(a);new=html.fromstring(b)
os=[dict(x.attrib) for x in old.xpath('//script')];new_script_attrs=[dict(x.attrib) for x in new.xpath('//script')]
assert len(os)==len(new_script_attrs)
for x in old.xpath('//script'):x.attrib.pop('src',None)
for x in new.xpath('//script'):x.attrib.pop('src',None)
assert html.tostring(old)==html.tostring(new),'Other DOM differences found'
newblocks={x['dom_path']:x for x in [json.loads(s) for s in (idx/'blocks.jsonl').read_text().splitlines()]}
newdoc=html.fromstring(b)
ref=json.loads(json.dumps(oldref)); oldbinding={'source':oldref['source'],'original_sha256_verified':oldref['original_sha256_verified']}
checks=[]
for id,e in ref['evidence_catalog'].items():
    path=re.sub(r'(ix:[a-z]+)',lambda m:'*[name()="'+m[1]+'"]',e['dom_path'])
    ns=newdoc.xpath(path);assert len(ns)==1
    t=' '.join(ns[0].text_content().split());assert t==e['original_text']
    nb=newblocks[e['dom_path']];assert nb['text']==t
    oldid=e['candidate_block_id'];e['previous_candidate_block_id']=oldid;e['candidate_block_id']=nb['block_id'];e['source_anchor']=nb.get('source_anchor');e['reported_page']=nb.get('reported_page');e['ordinal']=nb['ordinal']
    checks.append({'evidence_id':id,'old_block_id':oldid,'new_block_id':nb['block_id'],'dom_path':e['dom_path'],'text_sha256':hashlib.sha256(t.encode()).hexdigest(),'matches':True})
for f in ref['inline_xbrl_total_revenue_check']:
    nodes=newdoc.xpath('//*[@id="'+f['attributes']['id']+'"]');assert len(nodes)==1 and dict(nodes[0].attrib)==f['attributes']
    context=next(n for n in newdoc.iter() if n.get('id')==f['attributes']['contextref'])
    assert html.tostring(context,encoding='unicode')==f['context_xml']
ref['source']=newsource;ref['original_sha256_verified']=newsource['raw_sha256'];ref['prior_source_binding']=oldbinding;ref['binding_revalidation']='source-binding-revalidation.json'
(P/'reference-revalidated.json').write_text(json.dumps(ref,ensure_ascii=False,indent=2)+'\n')
report={'status':'pass','old_raw_sha256':hashlib.sha256(a).hexdigest(),'new_raw_sha256':hashlib.sha256(b).hexdigest(),'old_raw_bytes':len(a),'new_raw_bytes':len(b),'byte_diff':{'common_prefix_bytes':prefix,'common_suffix_bytes':suffix,'old_changed_bytes':a[prefix:len(a)-suffix].decode(),'new_changed_bytes':b[prefix:len(b)-suffix].decode()},'dom_comparison':'entire parsed DOM serializations identical after removing script src attributes; raw originals unchanged','old_script_attributes':os,'new_script_attributes':new_script_attrs,'source_snapshot_id':source_id,'index_source':str(idx.relative_to(E)),'all_199_original_locations_match':checks,'inline_xbrl_original_fact_and_context_bindings_match':True,'old_reference_preserved':'reference.json','new_reference':'reference-revalidated.json'}
(P/'source-binding-revalidation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS',len(checks),'locations, raw source and DOM binding; new reference ready')
