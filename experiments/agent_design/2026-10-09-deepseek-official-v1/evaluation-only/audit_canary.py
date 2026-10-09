"""Explicit E2-M1 evaluation fixture; never imported by production/runtime."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json, sqlite3, sys
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.answer_handoff import validate_saved_assessment

E=Path(__file__).resolve().parents[1]
R=E/'runs'/sys.argv[1]
D=E.parent/'2026-10-09-e1-benchmark-v1'
def read(p): return json.loads(p.read_text())
def h(p): return sha256(p.read_bytes()).hexdigest()
def save(p,d):
 with p.open('x') as f: json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
_verify_manifest(R)
result=read(R/'result.json')
packet=read(R/'attempt-01/review-packet.json')
freeze=D/'evaluation-only/frozen/E1-04-v1.json'; gold=read(freeze)
assert packet['question']==gold['case']['query_zh']
dataset=Path(packet['dataset_ref']['path'])
_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256'])
assert h(dataset/'manifest.json')==gold['dataset_manifest_sha256']
query=Path(packet['query_ref']['path']); _verify_manifest(query,packet['query_ref']['manifest_sha256'])
sources=read(dataset/'sources.json');sid='source-8602d79f703e48c18c2f27c3'
s=next(s for s in sources if s['source_snapshot_id']==sid)
raw=dataset/s['raw_file']; assert h(raw)==s['source_sha256']
tree=html.fromstring(raw.read_bytes());et=tree.getroottree()
nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/s['index_folder']/'blocks.jsonl').read_text().splitlines())}
docs=packet['source_documents']; assert len(docs)==1 and docs[0]['source_snapshot_id']==sid
for b in docs[0]['blocks']:
 assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
rec=next(f['value'] for f in packet['facts'] if f['kind']=='record')
assert rec['entity_id']=='sec-0000789019' and rec['dimensions']=={} and rec['metric_id']=='revenue'
assert rec['value_decimal']=='245122000000' and rec['unit']=='USD'
num=tree.xpath('//*[@id="F_3c083f9d-9cbe-4037-b6c1-310e199227a1"]')[0]
assert num.text_content()=='245,122' and num.get('scale')=='6' and num.get('contextref')==rec['origin']['context_ref']
ctx=tree.xpath('//*[@id="'+num.get('contextref')+'"]')[0]
fields={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)}
assert fields['identifier']=='0000789019' and fields['startdate']==rec['period']['start']=='2023-07-01'
assert fields['enddate']==rec['period']['end']=='2024-06-30' and 'segment' not in fields
unit=tree.xpath('//*[@id="'+num.get('unitref')+'"]')[0];assert unit.text_content()=='iso4217:USD'
cutoff=packet['scope']['knowledge_cutoff']; assert s['available_at']==rec['available_at']=='2024-07-30'<=cutoff=='2024-08-01'
receipt=D/'acquisition/workspace/source-runs/20261008T205046-a663c12323dd/receipts'/f'{sid}.json'
assert read(receipt)['document']['filed_at']==s['available_at']
future=next(s for s in sources if s['source_snapshot_id']!=sid)
futureblocks={b['block_id'] for b in map(json.loads,(dataset/future['index_folder']/'blocks.jsonl').read_text().splitlines())}
def walk(x):
 if isinstance(x,dict):
  yield x
  for v in x.values():yield from walk(v)
 elif isinstance(x,list):
  for v in x:yield from walk(v)
files=0;body_instances=0
for path in query.rglob('*.json'):
 files+=1
 for x in walk(read(path)):
  assert x.get('block_id') not in futureblocks
  if x.get('source_snapshot_id')==future['source_snapshot_id']:
   assert not any(k in x for k in ('text','blocks','value_decimal'))
  if x.get('block_id') in blocks and isinstance(x.get('text'),str):
   assert x['text']==blocks[x['block_id']]['text'];body_instances+=1
  if x.get('record_id') and x.get('value_decimal') and x.get('available_at'):
   assert x['available_at']<=cutoff and x['source_snapshot_id']==sid
workflow=result['status']=='reviewed_data_ready'
if workflow:
 review=Path(result['final_review_ref']['path']);_verify_manifest(review,result['final_review_ref']['manifest_sha256'])
 assessment,eligible=validate_saved_assessment(review,packet)
 assert eligible and read(review/'result.json')['analysis_eligible']
assert result['analysis_called'] is False
calls=[read(p) for p in (E/'runs').rglob('*-end.json') if '/calls/' in str(p)]
assert all(c['provider']=='deepseek' and c['requested_model']=='deepseek-flash' and c['configuration_snapshot']['fields']['base_url']['value']=='https://api.deepseek.com' for c in calls)
known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0))
with sqlite3.connect('file:'+str(E/'costs.sqlite')+'?mode=ro',uri=True) as db:
 rows=db.execute('select reserved,actual,state from reservations').fetchall()
 limit=db.execute('select usd from config').fetchone()[0]
assert limit=='3' and len(rows)==len(calls) and all(x[2]=='settled' for x in rows)
assert known==sum((Decimal(x[1]) for x in rows),Decimal(0))
table=next(b for b in docs[0]['blocks'] if b['type']=='table')['text']
a=table.index('Revenue:');z=table.index('Total revenue');end=table.index(' Cost of revenue:')
required_chars=a+(end-z);table_extra=len(table)-required_chars
output={'case_id':'E2-M1','gold_reference_sha256':h(freeze),'run_manifest_sha256':h(R/'manifest.json'),
'question':packet['question'],'workflow_status':result['status'],'content_required_supported':['A1','A2','T1'],
'content_required_count':3,'content_required_total':3,'source_truth_provenance':'pass','cutoff_full_query_audit':'pass',
'original_dom_blocks_checked':len(docs[0]['blocks']),'query_json_files_audited':files,'body_instances_checked':body_instances,
'original_numeric_attributes':dict(num.attrib),'original_context_xml':html.tostring(ctx,encoding='unicode'),
'source_url':s.get('url',s.get('source_url')),'source_raw_sha256':h(raw),'acquisition_receipt_sha256':h(receipt),
'answer':{'revenue':'245122000000','unit':'USD','period_start':'2023-07-01','period_end':'2024-06-30','available_at':'2024-07-30'},
'visible_body_chars':sum(len(b['text']) for b in docs[0]['blocks']),'table_nonrequired_chars':table_extra,
'focus':'pass at frozen whole-table granularity; excess income-statement rows retained explicitly',
'new_task_total_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),
'new_task_known_estimated_usd':str(known),'new_task_unknown_reserved_usd':'0','new_task_inflight':0,
'ledger_cap_usd':limit,'actual_billed_usd':None,'endpoints':sorted({c['configuration_snapshot']['fields']['base_url']['value'] for c in calls}),
'limitations':['Reuses known frozen E1 question, not a blind or strict A/B test.','Partial-stage recovery does not prove a fresh complete first-pass run.','Worker configured and offline-tested; this numerical canary may use planner-only decisions.','Whole-table delivery contains nonrequired rows.','Historical E1 ledger missing; old fees retained as frozen reported history, not reconciled.','No new SEC request; source date checked against frozen acquisition receipt.']}
out=E/'evaluation-only'/R.name;out.mkdir(exist_ok=False);save(out/'independent-audit.json',output)
print(json.dumps(output,ensure_ascii=False,indent=2))
