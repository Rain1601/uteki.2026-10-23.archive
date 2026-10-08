"""E1-04 original-source audit. Evaluation only; never consumed by Agent runtime."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from compare_configs import verify_manifest as _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs'/sys.argv[1];freeze_path=E/'evaluation-only/frozen/E1-04-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def save(p,d):
 with p.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
_verify_manifest(run);freeze=read(freeze_path);reference=E/freeze['reference_path'];assert h(reference)==freeze['reference_sha256'];ref=read(reference)
run_result=read(run/'result.json');last=run/run_result['attempts'][-1]['path'];packetpath=last/'review-01/input.json';packet=read(packetpath);assert packet==read(last/'review-packet.json');assert packet['question']==freeze['case']['query_zh']
_verify_manifest(Path(packet['query_ref']['path']),packet['query_ref']['manifest_sha256']);dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256']);assert h(dataset/'manifest.json')==freeze['dataset_manifest_sha256']
sources=read(dataset/'sources.json');assert len(sources)==2;source=next(s for s in sources if s['source_snapshot_id']=='source-8602d79f703e48c18c2f27c3');sid=source['source_snapshot_id'];assert sid=='source-8602d79f703e48c18c2f27c3';raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']==next(s for s in ref['sources'] if s['source_snapshot_id']==sid)['raw_sha256']
assert set(packet['scope']['source_snapshot_ids'])==set(s['source_snapshot_id'] for s in sources) and packet['scope']['company_ids']==['sec-0000789019']
tree=html.fromstring(raw.read_bytes());et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
docs=packet['source_documents'];assert len(docs)==1 and docs[0]['source_snapshot_id']==sid
for body in docs[0]['blocks']:
 assert body['text']==blocks[body['block_id']]['text']==' '.join(nodes[body['dom_path']].text_content().split())
records=[x for x in packet['facts'] if x['kind']=='record'];assert len(records)==1;record=records[0]['value']
assert record['entity_id']=='sec-0000789019' and record['metric_id']=='revenue' and record['dimensions']=={} and record['origin']['raw_dimensions']=={}
assert record['value_decimal']=='245122000000' and record['unit']=='USD' and record['available_at']=='2024-07-30'
quote=records[0]['citations'][0];assert quote['source_snapshot_id']==sid and quote['quote']=='245,122'
b=blocks[quote['block_id']];assert b['text'][quote['char_start']:quote['char_end']]==quote['quote']
table_node=nodes[b['dom_path']];cell=table_node.xpath('.//tr')[quote['cell']['row']].xpath('./td|./th')[quote['cell']['column']];assert ' '.join(cell.text_content().split())=='245,122'
numeric=next(n for n in cell.iter() if n.get('contextref'));assert numeric.get('contextref')==record['origin']['context_ref'] and numeric.get('name')==record['origin']['concept'] and numeric.get('scale')=='6'
unit=next(n for n in tree.iter() if n.get('id')==numeric.get('unitref'));assert ' '.join(unit.itertext()).strip()=='iso4217:USD'
ctx=next(n for n in tree.iter() if n.get('id')==numeric.get('contextref'));values={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)}
assert values['identifier']=='0000789019' and values['startdate']==record['period']['start']=='2023-07-01' and values['enddate']==record['period']['end']=='2024-06-30' and 'segment' not in values
assert record['period']['basis']=='source' and docs[0]['source_period_end']==source['period_end']=='2024-06-30'
metadata={'fiscal_period':record['period'],'available_at':docs[0]['available_at']}
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:v['text'] for k,v in blocks.items()},'metadata':metadata}}
gold={'schema_version':'evidence-gold-v1','case_id':'E1-04','question':packet['question'],'company_ids':[source['company_id']],'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'metadata' if r['id'] in ['A2','T1'] else 'text'} for r in freeze['case']['requirements']],'optional':[]}
deliveries=[]
for i,b in enumerate(docs[0]['blocks']):
 t=b['text']
 if b['type']=='table' and 'Total revenue' in t:
  table=b;start=t.index('Revenue:');total=t.index('Total revenue');end=t.index(' Cost of revenue:')
  parts=[(0,start,'required',['A1']),(start,total,'table_structure',[]),(total,end,'required',['A1']),(end,len(t),'table_structure',[])]
 elif b['block_id'].startswith('block-000006-'):
  split=t.index(' OR ');parts=[(0,split,'necessary_context',[]),(split,len(t),'irrelevant',[])]
 else:parts=[(0,len(t),'necessary_context',[])]
 deliveries.append({'id':f'D{i+1}','source_id':sid,'block_id':b['block_id'],'start':0,'end':len(t),'quote':t,'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in parts]})
def cite(a,z):return {'source_id':sid,'block_id':table['block_id'],'start':a,'end':z,'quote':table['text'][a:z]}
calls=[read(p) for p in run.rglob('*-end.json')];known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0));unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0));failedcost=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None and c['status']!='succeeded'),Decimal(0))
usage=Counter()
for c in calls:
 for k,v in (c.get('usage') or {}).items():
  if type(v)is int:usage[k]+=v
protocol=[]
for p in sorted(run.glob('attempt-*/data-query/model/decision-*-attempt-*.json')):
 d=read(p)
 if d['status']!='decision_returned':protocol.append({'path':str(p.relative_to(run)),'status':d['status'],'validation':d.get('validation'),'error_type':d.get('error_type'),'retry_flag':d.get('retry'),'elapsed_seconds':d.get('elapsed_seconds')})
review={'schema_version':'evidence-review-v1','case_id':'E1-04','question':packet['question'],'reviewer':'Codex e1_gold_reading; original-first evaluation after case frozen; not blind to inherited history','requirements':[
{'id':'A1','status':'supported','reason':'FY2024原件利润表Total revenue行的2024列为245,122，In millions表头、原始标签scale=6与USD单位一致。无分部维度的记录交付为245122000000 USD。','citations':[cite(0,start),cite(total,end)]},
{'id':'A2','status':'supported','reason':'交付记录实际包含2023-07-01至2024-06-30；本轮复核原件context C_6dbdb3a2-9baf-41b4-922d-f59879124337完全一致。不是根据Year Ended June30擅补起日。','citations':[{'kind':'metadata','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']}]},
{'id':'T1','status':'supported','reason':'实际交付FY2024 available_at=2024-07-30，早于2024-08-01。全程查询/正文审计仅FY2024；FY2025可得日2025-07-30只能作排除元数据。','citations':[{'kind':'metadata','source_id':sid,'field':'available_at','value':metadata['available_at']}]}],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'Microsoft FY2024原年报在2024-08-01前可得，查找/查询结果/已读正文/交付无FY2025财务正文。','truth':'原始数值节点、USD定义、scale、无分部维度、期间和原文均重新核验。','provenance':'运行/数据集/冻结标准hash核对；数字定位原表行11列3及字符175:182。','focus':'最终单张利润表、两财务标题与两处短封面类型/财年上下文。未取无关业务章节；按冻结整块标准通过。但封面期间重复、未勾选过渡期模板128字符、表内767字符可压缩，最小材料未达标。'}.items()},
'deliveries':deliveries,'metadata_deliveries':[{'id':'M1','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']},{'id':'M2','source_id':sid,'field':'available_at','value':metadata['available_at']}],
'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)},
'category_interpretation':{'table_structure':'767 visible characters of removable incidental table data, not necessary structural syntax. Includes86 revenue-component chars and681 cost/profit/EPS/share-count chars.','necessary_context':'Title/context includes financial statement labels plus FORM10K and fiscal-end cover wording if selected; useful identity context, not all indispensable.','irrelevant':'Unselected transition-period template wording within a selected cover block, if present. Does not establish a transition fiscal period.'},
'limitations':['No assertion of unique minimum evidence set.','Visible character score excludes repeated JSON serialization and metadata bytes; packet cost reported separately.','Frozen criteria preserved; no new threshold based on observed result.']}
score=evaluate(gold,review,corpus)
checks={'source_sha256':h(raw),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'gold_freeze_sha256':h(freeze_path),'reference_sha256':h(reference),'packet_sha256':h(packetpath),'body_dom_matches':len(deliveries),'xbrl_context_verified':True,'xbrl_context_xml':html.tostring(ctx,encoding='unicode'),'original_numeric_attributes':dict(numeric.attrib),'unit_definition':'iso4217:USD','cell_verified':True,'model_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'protocol_validation_failures':protocol,'failed_known_estimated_usd':str(failedcost),'known_estimated_usd':str(known),'unknown_reserved_usd':str(unknown),'usage':dict(usage),'visible_body_characters':sum(len(x['text']) for x in docs[0]['blocks']),'packet_file_bytes':packetpath.stat().st_size,'review_input_file_bytes':packetpath.stat().st_size,'bytes_note':'review input packet file only; not a measurement of complete HTTP request, system prompt or all model calls','gold_projection_note':'A1 semantics carried to body citations; A2 fiscal metadata and T1 source available_at metadata bind actual delivered data and original. No answer fabricated or injected.','trace_note':'Fresh configuration run; all query artifacts and actual serialized reviewer inputs are checked below. API transport and application outcomes remain distinct.'}
# Inspect the full process; future-source IDs in scope and exclusion metadata are allowed.
future_source=next(s for s in sources if s['source_snapshot_id']!=sid);future=future_source['source_snapshot_id'];cutoff='2024-08-01';query=Path(packet['query_ref']['path'])
assert packet['scope']['knowledge_cutoff']==cutoff and source['available_at']=='2024-07-30'<=cutoff<future_source['available_at']
futureblocks={b['block_id']:b for b in map(json.loads,(dataset/future_source['index_folder']/'blocks.jsonl').read_text().splitlines())}
receiptpath=E/'acquisition/workspace/source-runs/20261008T205046-a663c12323dd/receipts'/f'{sid}.json';receipt=read(receiptpath)
assert receipt['document']['filed_at']==source['available_at'] and receipt['document']['content_sha256']==source['source_sha256']
def walk(x,path=''):
 if isinstance(x,dict):
  yield path,x
  for k,v in x.items():yield from walk(v,path+'/'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):yield from walk(v,path+'/'+str(i))
 else:yield path,x
bodychecks=0;recordchecks=0;occurrences=[];files=[];sqlchecks=[]
def inspect(data,label):
 global bodychecks,recordchecks
 for pointer,v in walk(data):
  if v==future:occurrences.append({'path':label,'pointer':pointer,'classification':'scope_sql_or_availability_only'})
  if not isinstance(v,dict):continue
  if v.get('source_snapshot_id')==future or v.get('source_id')==future:
   assert set(v)<={'source_snapshot_id','source_id','company_id','source_period_end','available_at','status'},(label,pointer,list(v))
   assert v.get('available_at','9999')>cutoff and not ('text' in v or 'blocks' in v),(label,pointer)
  if v.get('block_id') in futureblocks and v.get('block_id') not in blocks:raise AssertionError(('future block',label,pointer))
  if v.get('block_id') in blocks and isinstance(v.get('text'),str):
   assert v['text']==blocks[v['block_id']]['text'];bodychecks+=1
  if v.get('record_id') and v.get('value_decimal') and 'available_at' in v:
   assert v['available_at']<=cutoff and v['source_snapshot_id']==sid;recordchecks+=1
  if 'parameters' in v:
   texts=[x for x in v.values() if isinstance(x,str) and 'SELECT payload' in x]
   for text in texts:
    assert text.count('available_at <= ?')==2 and v['parameters'].count(cutoff)==2
    sqlchecks.append({'path':label,'trace':v})
queries=[Path(a['query_ref']['path']) for a in run_result['attempts']]
for a,q in zip(run_result['attempts'],queries):_verify_manifest(q,a['query_ref']['manifest_sha256'])
for p in sorted(p for q in queries for p in q.rglob('*.json')):
 files.append({'path':str(p.relative_to(run)),'sha256':h(p)});inspect(read(p),str(p.relative_to(run)))
turns=[]
for p in sorted(p for q in queries for p in q.glob('turn-*/input.json')):
 d=read(p);ds=d['catalog']['discovery']['sources'];assert all(s['source_snapshot_id']==sid and s['available_at']<=cutoff for s in ds)
 turns.append({'turn':str(p.parent.relative_to(run)),'action':read(p.with_name('decision.json'))['action'] if p.with_name('decision.json').exists() else 'no_valid_decision','discovery_sources':[s['source_snapshot_id'] for s in ds]})
reviewinputs=[]
for p in sorted(run.glob('attempt-*/review-*/model/review-*-input.json')):
 wrapper=read(p);mi=json.loads(wrapper['model_input']);inspect(mi,str(p.relative_to(run)));reviewinputs.append({'path':str(p.relative_to(run)),'sha256':h(p),'serialized_input_sha256':sha256(wrapper['model_input'].encode()).hexdigest()})
assert sqlchecks and turns and reviewinputs
result=read(run/'result.json');assert result['status'] in ['reviewed_data_ready','attempts_exhausted'] and not result['analysis_called'] and all(a['execution']=='new' for a in result['attempts'])
rp=Path(result['final_review_ref']['path']);_verify_manifest(rp,result['final_review_ref']['manifest_sha256']);rr=read(rp/'result.json');assert rr['analysis_eligible']==(result['status']=='reviewed_data_ready')
score['workflow_status']=result['status'];score['workflow_accepted']=rr['analysis_eligible'];score['evaluation_scope']='data_content_and_full_process_cutoff'
review['workflow_status']=result['status'];review['run_binding']={'run_manifest_sha256':h(run/'manifest.json'),'packet_sha256':h(packetpath),'query_ref':packet['query_ref']}
checks.update(available_at_verified_against_acquisition_receipt=True,workflow_status=result['status'],analysis_eligible=rr['analysis_eligible'],analysis_called=False,query_manifest_sha256=h(query/'manifest.json'),review_protocol_failures=rr['failures'])
cutoffaudit={'status':'pass','cutoff':cutoff,'files':files,'turns':turns,'future_occurrences':occurrences,'future_financial_body':False,'source_bound_text_instances_verified':bodychecks,'eligible_record_instances_verified':recordchecks,'bound_sql_checks':sqlchecks,'serialized_review_inputs':reviewinputs,'source_available_at':source['available_at'],'future_available_at':future_source['available_at'],'acquisition_receipt_sha256':h(receiptpath),'publication_date_limitation':'Filed date checked against frozen acquisition receipt; no new live SEC fetch. Original XBRL verifies fiscal dates, not public filing time.'}
review['minimum_sufficient_delivery']={'status':'not_demonstrated','reason':'整表及标题/封面模板仍可压缩，冻结粒度通过不等于严格最少。'}
checks['unknown_receipts']=[{'call_id':c['call_id'],'status':c['status'],'reserved_usd':c.get('reserved_usd'),'transport_phase':c.get('transport_phase'),'dispatch_status':c.get('dispatch_status')} for c in calls if c.get('estimated_usd') is None]
checks['attempt_costs']={a.name:{'calls':len(list(a.glob('**/calls/*-end.json'))),'known_usd':str(sum((Decimal(read(p)['estimated_usd']) for p in a.glob('**/calls/*-end.json') if read(p).get('estimated_usd') is not None),Decimal(0))),'unknown_reserved_usd':str(sum((Decimal(read(p)['reserved_usd']) for p in a.glob('**/calls/*-end.json') if read(p).get('estimated_usd') is None),Decimal(0)))} for a in run.glob('attempt-*')}
checks['final_revision_requests']=(rr.get('assessment') or {}).get('revision_requests',[])
cutoffaudit['scope_note']='All recorded query input snapshots and tool artifacts across every attempt, plus actual serialized reviewer inputs. Planner retry logs carry request fingerprints rather than full wire request bodies; no claim to independently reconstruct unrecorded transport bytes.'
output=E/'evaluation-only/reviews'/run.name;output.mkdir()
for name,data in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',checks),('cutoff-audit.json',cutoffaudit)]:save(output/name,data)
print(json.dumps({'run':run.name,'score':score,'calls':len(calls),'cost':str(known),'packet_bytes':packetpath.stat().st_size,'bodychecks':bodychecks,'records':recordchecks,'turns':len(turns)},ensure_ascii=False,indent=2))
