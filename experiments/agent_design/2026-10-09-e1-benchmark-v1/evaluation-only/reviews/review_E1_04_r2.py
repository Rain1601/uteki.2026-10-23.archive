"""E1-04 original-source audit. Evaluation only; never consumed by Agent runtime."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-04-sonnet-r2';freeze_path=E/'evaluation-only/frozen/E1-04-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def save(p,d):
 with p.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
_verify_manifest(run);freeze=read(freeze_path);reference=E/freeze['reference_path'];assert h(reference)==freeze['reference_sha256'];ref=read(reference)
packetpath=run/'attempt-01/review-01/input.json';packet=read(packetpath);assert packet==read(run/'attempt-01/review-packet.json');assert packet['question']==freeze['case']['query_zh']
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
 if b['type']=='table':
  table=b;start=t.index('Revenue:');total=t.index('Total revenue');end=t.index(' Cost of revenue:')
  parts=[(0,start,'required',['A1']),(start,total,'table_structure',[]),(total,end,'required',['A1']),(end,len(t),'table_structure',[])]
 else:parts=[(0,len(t),'necessary_context',[])]
 deliveries.append({'id':f'D{i+1}','source_id':sid,'block_id':b['block_id'],'start':0,'end':len(t),'quote':t,'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in parts]})
def cite(a,z):return {'source_id':sid,'block_id':table['block_id'],'start':a,'end':z,'quote':table['text'][a:z]}
calls=[read(p) for p in run.rglob('*-end.json')];known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0));unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0));failedcost=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None and c['status']!='succeeded'),Decimal(0))
usage=Counter()
for c in calls:
 for k,v in (c.get('usage') or {}).items():
  if type(v)is int:usage[k]+=v
protocol=[]
for p in sorted((run/'attempt-01/data-query/model').glob('decision-*-attempt-*.json')):
 d=read(p)
 if d['status']!='decision_returned':protocol.append({'path':str(p.relative_to(run)),'status':d['status'],'validation':d.get('validation'),'error_type':d.get('error_type'),'retry_flag':d.get('retry'),'elapsed_seconds':d.get('elapsed_seconds')})
review={'schema_version':'evidence-review-v1','case_id':'E1-04','question':packet['question'],'reviewer':'Codex e1_gold_reading; original-first evaluation after case frozen; not blind to inherited history','requirements':[
{'id':'A1','status':'supported','reason':'FY2024原件利润表Total revenue行的2024列为245,122，In millions表头、原始标签scale=6与USD单位一致。无分部维度的记录交付为245122000000 USD。','citations':[cite(0,start),cite(total,end)]},
{'id':'A2','status':'supported','reason':'交付记录实际包含2023-07-01至2024-06-30；本轮复核原件context C_6dbdb3a2-9baf-41b4-922d-f59879124337完全一致。不是根据Year Ended June30擅补起日。','citations':[{'kind':'metadata','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']}]},
{'id':'T1','status':'supported','reason':'实际交付FY2024 available_at=2024-07-30，早于2024-08-01。全8轮查询/正文审计仅FY2024；FY2025可得日2025-07-30只能作排除元数据。','citations':[{'kind':'metadata','source_id':sid,'field':'available_at','value':metadata['available_at']}]}],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'Microsoft FY2024原年报在2024-08-01前可得，查找/查询结果/已读正文/交付无FY2025财务正文。','truth':'原始数值节点、USD定义、scale、无分部维度、期间和原文均重新核验。','provenance':'运行/数据集/冻结标准hash核对；数字定位原表行11列3及字符175:182。','focus':'集中在一张原始利润表及两标题，没有多取章节或重复表。在冻结整表粒度标准下通过；仍有767字符表内非必需数据，未达到最小充分压缩。'}.items()},
'deliveries':deliveries,'metadata_deliveries':[{'id':'M1','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']},{'id':'M2','source_id':sid,'field':'available_at','value':metadata['available_at']}],
'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)},
'category_interpretation':{'table_structure':'767 visible characters of removable incidental table data, not necessary structural syntax. Includes86 revenue-component chars and681 cost/profit/EPS/share-count chars.','necessary_context':'68 chars of location/table labels; useful navigation context, not all semantically indispensable.','irrelevant_zero_means':'No separately selected unrelated passages; does not mean zero removable content.'},
'limitations':['No assertion of unique minimum evidence set.','Visible character score excludes repeated JSON serialization and metadata bytes; packet cost reported separately.','Frozen criteria preserved; no new threshold based on observed result.']}
score=evaluate(gold,review,corpus)
checks={'source_sha256':h(raw),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'gold_freeze_sha256':h(freeze_path),'reference_sha256':h(reference),'packet_sha256':h(packetpath),'body_dom_matches':len(deliveries),'xbrl_context_verified':True,'xbrl_context_xml':html.tostring(ctx,encoding='unicode'),'original_numeric_attributes':dict(numeric.attrib),'unit_definition':'iso4217:USD','cell_verified':True,'model_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'protocol_validation_failures':protocol,'failed_known_estimated_usd':str(failedcost),'known_estimated_usd':str(known),'unknown_reserved_usd':str(unknown),'usage':dict(usage),'visible_body_characters':sum(len(x['text']) for x in docs[0]['blocks']),'packet_file_bytes':packetpath.stat().st_size,'review_input_file_bytes':packetpath.stat().st_size,'bytes_note':'review input packet file only; not a measurement of complete HTTP request, system prompt or all model calls','gold_projection_note':'A1 semantics carried to body citations; A2 fiscal metadata and T1 source available_at metadata bind actual delivered data and original. No answer fabricated or injected.','trace_note':'All 10 API calls succeeded; both reviewer outputs failed application protocol validation. See workflow-status.json; data-content pass does not mean r2 workflow passed.'}
future='source-360182cbf562dcf9a8ab9c4e';cutoff='2024-08-01';query=Path(packet['query_ref']['path'])
assert packet['scope']['knowledge_cutoff']==cutoff
assert docs[0]['available_at']==source['available_at']=='2024-07-30'<=cutoff
future_source=next(s for s in sources if s['source_snapshot_id']==future);assert future_source['available_at']=='2025-07-30'>cutoff
receiptpath=E/'acquisition/workspace/source-runs/20261008T205046-a663c12323dd/receipts'/f'{sid}.json';receipt=read(receiptpath)
assert receipt['document']['filed_at']==source['available_at'] and receipt['document']['content_sha256']==source['source_sha256']
def walk(x,path=''):
 if isinstance(x,dict):
  yield path,x
  for k,v in x.items():yield from walk(v,path+'/'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):yield from walk(v,path+'/'+str(i))
 else:yield path,x
files=[];future_paths=[];bodychecks=0;recordchecks=0
for path in sorted(query.rglob('*.json')):
 data=read(path);files.append({'path':str(path.relative_to(run)),'sha256':h(path)})
 for pointer,value in walk(data):
  if value==future:
   assert pointer.endswith('/source_snapshot_ids/1') or pointer.endswith('/trace/0/parameters/8'),(path,pointer)
   future_paths.append({'path':str(path.relative_to(run)),'pointer':pointer,'classification':'scope_or_bound_sql_parameter_only'})
  if isinstance(value,dict):
   if value.get('source_snapshot_id') is not None:assert value['source_snapshot_id']==sid,(path,pointer)
   if value.get('block_id') in blocks and isinstance(value.get('text'),str):
    assert value['text']==blocks[value['block_id']]['text'];bodychecks+=1
   if value.get('record_id') and value.get('value_decimal') and 'available_at' in value:
    assert value['available_at']<=cutoff and value['source_snapshot_id']==sid;recordchecks+=1
turns=[]
for path in sorted(query.glob('turn-*/input.json')):
 data=read(path);ds=data['catalog']['discovery']['sources'];assert len(ds)==1 and ds[0]['source_snapshot_id']==sid and ds[0]['available_at']<=cutoff
 decision=read(path.with_name('decision.json'));turns.append({'turn':path.parent.name,'action':decision['action'],'discovery_sources':[s['source_snapshot_id'] for s in ds]})
assert len(turns)==8
sqltrace=read(query/'turn-004/input.json')['observation']['result']['trace'];assert len(sqltrace)==1
sql=sqltrace[0];sqltext=next(v for v in sql.values() if isinstance(v,str) and 'SELECT payload' in v)
assert sqltext.count('available_at <= ?')==2 and sql['parameters'].count(cutoff)==2
reviewer_audits=[];protocol=[]
for name in ['review-01','review-02']:
 rp=run/'attempt-01'/name;wrapper=read(rp/'model/review-0001-input.json');mi=json.loads(wrapper['model_input']);exclusions=[]
 for pointer,value in walk(mi):
  if value==future:assert pointer.endswith('/source_snapshot_ids/1') or pointer=='/scope_source_availability/1/source_snapshot_id',(name,pointer)
  if isinstance(value,dict) and value.get('source_snapshot_id')==future:
   assert set(value)=={'source_snapshot_id','company_id','source_period_end','available_at','status'} and value['status']=='not_available_at_cutoff';exclusions.append(value)
 parsed=read(rp/'model/review-0001-parsed.json');result=read(rp/'result.json');assert result['status']=='failed' and not result['analysis_eligible']
 reviewer_audits.append({'review':name,'model_input_sha256':sha256(wrapper['model_input'].encode()).hexdigest(),'future_metadata':exclusions,'future_financial_body':False,'response_source_checks':parsed.get('source_checks')})
 protocol.append({'review':name,'status':result['status'],'analysis_eligible':result['analysis_eligible'],'failures':result['failures']})
cutoff_audit={'status':'pass','scope':'r2 all query snapshots/tool results/artifacts, planner discovery/retained body, both actual serialized reviewer inputs, final packet','files':files,'turns':turns,'bound_sql':sqltrace,'future_occurrences':future_paths,'source_bound_text_instances_verified':bodychecks,'eligible_record_instances_verified':recordchecks,'reviewer_inputs':reviewer_audits,'available_at':{'eligible_source':source['available_at'],'future_source':future_source['available_at'],'cutoff':cutoff,'acquisition_receipt':str(receiptpath.relative_to(E)),'receipt_sha256':h(receiptpath),'receipt_filed_at':receipt['document']['filed_at'],'limitation':'Uses frozen acquisition filing-date provenance; no new live SEC metadata fetch in this independent review. Original XBRL verifies fiscal interval, not publication date.'},'interpretation':'Future ID in selected dataset scope and SQL IN parameters is not delivered financial content. Availability-only exclusion metadata is explicitly allowed by frozen gold.'}
result=read(run/'result.json');assert result['status']=='blocked_by_review_failure'
workflow={'original_run_status':result['status'],'independent_data_content_verdict':score['status'],'independent_cutoff_audit':'pass','original_workflow_accepted':False,'analysis_called':result['analysis_called'],'adoption':result['adoption'],'review_protocol_failures':protocol,'cause':'Two reviewer responses include a source_check for future FY2025 source outside actual source_documents; application protocol rejects them despite complete API responses.','successful_api_calls':len(calls),'review_failed_known_estimated_usd':str(sum((Decimal(c['estimated_usd']) for c in calls if c['stage']=='record_review'),Decimal(0))),'note':'Independent content pass cannot retroactively release original r2 workflow.'}
checks['review_protocol_failures']=protocol;checks['available_at_verified_against_acquisition_receipt']=True
score['evaluation_scope']='data_content_and_cutoff_only';score['workflow_status']=result['status'];score['workflow_accepted']=False
recovery=E/'runs/E1-04-sonnet-review-recovery-r1';_verify_manifest(recovery);rr=read(recovery/'result.json');rpacket=read(recovery/'attempt-01/review-01/input.json')
assert rr['status']=='reviewed_data_ready' and rr['attempts'][0]['execution']=='reused_frozen' and rr['final_query_ref']==result['final_query_ref']
assert rpacket['source_documents']==packet['source_documents'] and rpacket['facts']==packet['facts'] and rpacket['scope']==packet['scope']
rreviewpath=Path(rr['final_review_ref']['path']);_verify_manifest(rreviewpath,rr['final_review_ref']['manifest_sha256']);rreview=read(rreviewpath/'result.json');assert rreview['analysis_eligible'] is True and rreview['status']=='reviewed'
rcalls=[read(p) for p in recovery.rglob('*-end.json')];assert len(rcalls)==1 and rcalls[0]['status']=='succeeded';recoverycost=Decimal(rcalls[0]['estimated_usd'])
recovery_audit={'status':'verified_recovery','recovery_run':str(recovery.relative_to(E)),'manifest_sha256':h(recovery/'manifest.json'),'original_run_status_preserved':result['status'],'recovery_status':rr['status'],'reused_query_ref':rr['final_query_ref'],'facts_identical':True,'source_documents_identical':True,'scope_identical':True,'analysis_eligible':True,'analysis_called':rr['analysis_called'],'adoption':rr['adoption'],'new_model_calls':len(rcalls),'additional_known_estimated_usd':str(recoverycost),'r2_plus_recovery_known_estimated_usd':str(known+recoverycost),'no_new_retrieval':True,'frozen_criteria_unchanged':True,'note':'Recovery repairs workflow validation only. Data sufficiency is independently established by original/XBRL/cutoff audit above. No regenerated evidence or edited frozen standard.'}
rparsed=read(rreviewpath/'model/review-0001-parsed.json');assert [x['source_snapshot_id'] for x in rparsed['source_checks']]==[sid]
rmi=json.loads(read(rreviewpath/'model/review-0001-input.json')['model_input'])
for pointer,value in walk(rmi):
 if isinstance(value,dict) and value.get('source_snapshot_id')==future:assert set(value)=={'source_snapshot_id','company_id','source_period_end','available_at','status'} and value['status']=='not_available_at_cutoff'
recovery_audit['source_checks']=rparsed['source_checks'];recovery_audit['recovered_input_future_financial_body']=False
output=E/'evaluation-only/reviews/E1-04-sonnet-r2';output.mkdir()
for name,data in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',checks),('cutoff-audit.json',cutoff_audit),('workflow-status.json',workflow),('recovery-chain.json',recovery_audit)]:save(output/name,data)
print(json.dumps({'score':score,'cost':str(known),'recovery_cost':str(recoverycost),'packet_bytes':packetpath.stat().st_size,'usage':dict(usage),'bodychecks':bodychecks,'records':recordchecks},ensure_ascii=False,indent=2))
