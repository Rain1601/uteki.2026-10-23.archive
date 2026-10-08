"""E1-03 independent original-source review; evaluation-only."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
from lxml import html
import json
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-03-sonnet-r1';F=E/'evaluation-only/frozen/E1-03-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def save(p,d):
 with p.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
_verify_manifest(run);freeze=read(F);reference=E/freeze['reference_path'];assert h(reference)==freeze['reference_sha256'];ref=read(reference)
pp=run/'attempt-01/review-01/input.json';packet=read(pp);assert packet==read(run/'attempt-01/review-packet.json');assert packet['question']==freeze['case']['query_zh']
_verify_manifest(Path(packet['query_ref']['path']),packet['query_ref']['manifest_sha256']);dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256']);assert h(dataset/'manifest.json')==freeze['dataset_manifest_sha256']
sources=read(dataset/'sources.json');assert len(sources)==2
expected={'source-8602d79f703e48c18c2f27c3':('2024-06-30','2024-07-30','D1'),'source-360182cbf562dcf9a8ab9c4e':('2025-06-30','2025-07-30','D2')}
assert set(packet['scope']['source_snapshot_ids'])==set(expected)
assert packet['scope']['company_ids']==['sec-0000789019']
records=[x for x in packet['facts'] if x['kind']=='record'];assert len(records)==2;assert {r['value']['source_snapshot_id'] for r in records}==set(expected)
assert all(x['kind'] in ['record','source_block'] for x in packet['facts'])
corpus={};deliveries=[];metadel=[];support={};checks=[];tables={}
for source in sources:
 sid=source['source_snapshot_id'];year,available,rid=expected[sid];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']==next(x for x in ref['sources'] if x['source_snapshot_id']==sid)['raw_sha256']
 tree=html.fromstring(raw.read_bytes());et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
 bs={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
 doc=next(d for d in packet['source_documents'] if d['source_snapshot_id']==sid);assert doc['source_period_end']==source['period_end']==year
 selected=next(r for r in records if r['value']['source_snapshot_id']==sid);v=selected['value'];assert v['value_decimal']=='245122000000' and v['unit']=='USD' and v['entity_id']=='sec-0000789019' and v['metric_id']=='revenue' and v['dimensions']=={} and v['available_at']==available
 cit=selected['citations'][0];assert cit['source_snapshot_id']==sid and cit['quote']=='245,122'
 body=bs[cit['block_id']];assert body['text'][cit['char_start']:cit['char_end']]=='245,122';table_node=nodes[body['dom_path']];cell=table_node.xpath('.//tr')[cit['cell']['row']].xpath('./td|./th')[cit['cell']['column']];assert ' '.join(cell.text_content().split())=='245,122'
 num=next(n for n in cell.iter() if n.get('contextref'));assert num.get('contextref')==v['origin']['context_ref'] and num.get('name')==v['origin']['concept'] and num.get('scale')=='6'
 unit=next(n for n in tree.iter() if n.get('id')==num.get('unitref'));assert ' '.join(unit.itertext()).strip()=='iso4217:USD'
 ctx=next(n for n in tree.iter() if n.get('id')==num.get('contextref'));cv={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)}
 assert cv['identifier']=='0000789019' and 'segment' not in cv and cv['startdate']==v['period']['start']=='2023-07-01' and cv['enddate']==v['period']['end']=='2024-06-30' and v['period']['basis']=='source'
 m={'value_decimal':v['value_decimal'],'unit':v['unit'],'period':v['period'],'report_period_end':doc['source_period_end'],'available_at':v['available_at'],'source_snapshot_id':sid,'source_sha256':doc['source_sha256']}
 corpus[sid]={'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in bs.items()},'metadata':{'delivered_record_binding':m}}
 metadel.append({'id':'M'+str(len(metadel)+1),'source_id':sid,'field':'delivered_record_binding','value':m})
 for b in doc['blocks']:
  t=b['text'];assert t==bs[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
  if b['type']=='table':
   start=t.index('Revenue:');total=t.index('Total revenue');end=t.index(' Cost of revenue:');parts=[(0,start,'required',[rid]),(start,total,'table_structure',[]),(total,end,'required',[rid]),(end,len(t),'table_structure',[])];tables[sid]=b
   support[rid]=[{'source_id':sid,'block_id':b['block_id'],'start':a,'end':z,'quote':t[a:z]} for a,z in [(0,start),(total,end)]]
  else:parts=[(0,len(t),'necessary_context',[])]
  deliveries.append({'id':'B'+str(len(deliveries)+1),'source_id':sid,'block_id':b['block_id'],'start':0,'end':len(t),'quote':t,'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in parts]})
 checks.append({'source_id':sid,'source_sha256':h(raw),'body_dom_matches':len(doc['blocks']),'record_id':v['record_id'],'cell':cit['cell'],'char_start':cit['char_start'],'char_end':cit['char_end'],'original_fact_attributes':dict(num.attrib),'original_context_xml':html.tostring(ctx,encoding='unicode'),'unit':'iso4217:USD','source_period_end':year,'observation_period':v['period']})
assert len(packet['source_documents'])==2
plans=[]
for p in sorted((run/'attempt-01/data-query/query').glob('turn-*/decision.json')):
 d=read(p)
 if d.get('plan'):assert d['plan']['calculations']==[];plans.append({'path':str(p.relative_to(run)),'calculations':[]})
assert plans
select=read(run/'attempt-01/data-query/query/turn-008/decision.json');assert select['action']=='select_records' and len(select['record_selection']['record_ids'])==2
calls=[read(p) for p in run.rglob('*-end.json')];known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0));unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0));usage=Counter()
for c in calls:
 for k,v in (c.get('usage') or {}).items():
  if type(v)is int:usage[k]+=v
protocol=[{'path':str(p.relative_to(run)),'status':d['status'],'validation':d.get('validation')} for p in sorted((run/'attempt-01/data-query/model').glob('decision-*-attempt-*.json')) if (d:=read(p))['status']!='decision_returned']
gold={'schema_version':'evidence-gold-v1','case_id':'E1-03','question':packet['question'],'company_ids':['sec-0000789019'],'sources':[{'source_id':s['source_snapshot_id'],'company_id':s['company_id'],'sha256':s['source_sha256']} for s in sources],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'metadata' if r['id']=='D3' else 'text'} for r in freeze['case']['requirements']],'optional':[]}
review={'schema_version':'evidence-review-v1','case_id':'E1-03','question':packet['question'],'reviewer':'Codex e1_gold_reading; after pre-run freeze and original-source reconstruction, not blind to history','requirements':[
{'id':'D1','status':'supported','reason':'FY2024原年报Total revenue行2024列245122百万美元；原数值标签、单位、issuer-only年度context及单元格均验证。','citations':support['D1']},
{'id':'D2','status':'supported','reason':'FY2025原年报Total revenue行2024比较列同为245122百万美元；引用2024列而不是本年281724，原始标签和期间验证。','citations':support['D2']},
{'id':'D3','status':'supported','reason':'实际交付保留两条不同source/hash的收入记录，单位均USD，观察期间均2023-07-01至2024-06-30，值均245122000000。未生成合并金额或计算事实，执行QueryPlan calculations为空；选择步骤明确两来源各一条、不相加。这是原数据足以支持一致性核对，并非评测者向运行填入答案。','citations':[dict(m,kind='metadata') for m in metadel]}],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'Microsoft同公司、两个明确版本；每边都选FY2024观察期间。','truth':'两个原件分别核验数值和XBRL，年度列/单位一致；未把FY2025本年值误作比较列。','provenance':'两份来源、原始hash、实际单元格和记录身份都保留，没有因为数值相同合并掉出处。','focus':'每份报告一张相关原表，无额外章节或同源重复表。两份同额材料是题目必需，不扣重复分；1544字符表内附带仍可裁剪，非最小材料。'}.items()},
'deliveries':deliveries,'metadata_deliveries':metadel,'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)},'category_interpretation':{'table_structure':'1544 chars removable table-internal data, not essential structure','necessary_context':'136 chars location/table labels, not all semantically indispensable','duplicate_zero_means':'The two different source versions are explicitly required; other-row overhead tracked separately.'},'limitations':['D3 checks actual paired records and absence of sum; no separate machine comparison report is generated by Data Agent.','Original-source reviewer judgments, not automated semantic truth proof.','No after-the-fact relaxation or new waste threshold.']}
score=evaluate(gold,review,corpus);out=E/'evaluation-only/reviews/E1-03-sonnet-r1';out.mkdir()
audit={'sources':checks,'run_manifest_sha256':h(run/'manifest.json'),'dataset_manifest_sha256':h(dataset/'manifest.json'),'gold_freeze_sha256':h(F),'reference_sha256':h(reference),'packet_sha256':h(pp),'body_dom_matches':len(deliveries),'xbrl_context_verified':True,'cell_verified':True,'actual_records_count':len(records),'actual_source_count':len(packet['source_documents']),'value_equality_independently_verified':True,'no_sum_check':{'query_plans':plans,'delivered_fact_kinds':dict(Counter(x['kind'] for x in packet['facts'])),'selection_reason':select['reason'],'comment':'No summed financial value generated. Two equal source-bound records enable the requested verification; no synthetic equality flag inserted into runtime.'},'model_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'protocol_validation_failures':protocol,'usage':dict(usage),'known_estimated_usd':str(known),'unknown_reserved_usd':str(unknown),'visible_body_characters':sum(len(x['quote']) for x in deliveries),'review_input_file_bytes':pp.stat().st_size,'bytes_note':'review input file, not total HTTP requests or tokenizer length','gold_projection_note':'D1 and D2 checked by exact source quotes; D3 checked by two actual delivered record bindings plus no-sum trace audit. Two-version semantics preserved.'}
for name,d in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit)]:save(out/name,d)
print(json.dumps({'score':score,'calls':len(calls),'usage':dict(usage),'packet_bytes':pp.stat().st_size},ensure_ascii=False,indent=2))
