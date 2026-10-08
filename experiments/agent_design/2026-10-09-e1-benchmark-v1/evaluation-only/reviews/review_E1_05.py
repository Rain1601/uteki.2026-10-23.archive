"""Independent original-source review; evaluation-only, no runtime input changes."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-05-sonnet-r1';fp=E/'evaluation-only/frozen/E1-05-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
_verify_manifest(run);freeze=read(fp);refpath=E/freeze['reference_path'];assert h(refpath)==freeze['reference_sha256']
packetpath=run/'attempt-01/review-packet.json';packet=read(packetpath);assert packet['question']==freeze['case']['query_zh']
dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256']);assert h(dataset/'manifest.json')==freeze['dataset_manifest_sha256'];_verify_manifest(Path(packet['query_ref']['path']),packet['query_ref']['manifest_sha256'])
sources=read(dataset/'sources.json');assert len(sources)==1;source=sources[0];sid=source['source_snapshot_id'];assert sid=='source-360182cbf562dcf9a8ab9c4e';raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']=='56d41ecc0adc114c7fcda813d41f5911b244a7e448b545f6dca52dfba9801008'
tree=html.fromstring(raw.read_bytes());et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())};bynumber={int(k.split('-')[1]):v for k,v in blocks.items()}
docs=packet['source_documents'];assert len(docs)==1 and docs[0]['source_snapshot_id']==sid and docs[0]['source_period_end']=='2025-06-30'
delivered=docs[0]['blocks'];actual={int(b['block_id'].split('-')[1]):b for b in delivered}
for b in delivered:assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
# Independently inspect nearby definitions, business function paragraphs and the alternative Note18 listing.
read_numbers=list(range(85,101))+[101,103,108,110]+list(range(117,133))+[143,144,146,148,150,152]+list(range(1181,1211))+[551,817]
reading=[]
for n in read_numbers:
 b=bynumber[n];text=' '.join(nodes[b['dom_path']].text_content().split());assert text==b['text'];reading.append({'block_id':b['block_id'],'dom_path':b['dom_path'],'text':text,'role':'original_neighbor_or_equivalent_check'})
expected={86,87,89,90,91,93,95,97,99,117,118,120,122,143,144,146,148,150};assert set(actual)==expected
required={86:'B1',90:'B2',91:'B2',93:'B2',95:'B2',97:'B2',99:'B2',117:'B3',118:'B3',120:'B3',122:'B3',143:'B4',144:'B4',146:'B4',148:'B4',150:'B4'}
# Core source meanings are required; full paragraph retention is allowed by frozen granularity policy.
# Distinguish finer product examples from required core groups instead of calling all text essential.
intervals={}
for n,b in actual.items():
 t=b['text'];rid=required.get(n);parts=[]
 if n==86:
  end=t.index('.')+1;parts=[(0,end,'required',[rid]),(end,len(t),'irrelevant',[])]
 elif n==87:parts=[(0,len(t),'irrelevant',[])] # No FY24 comparison or explanation of membership change requested.
 elif n==89:parts=[(0,len(t),'necessary_context',[])]
 elif n in [90,91,117,118,143,144]:parts=[(0,len(t),'required',[rid])]
 elif n==120:
  spans=[]
  for phrase in ['Server products and cloud services','Azure and other cloud services','Server products, comprising']:
   a=t.index(phrase);spans.append((a,a+len(phrase)))
  cur=0
  for a,z in sorted(spans):
   if a>cur:parts.append((cur,a,'necessary_context',[]))
   parts.append((a,z,'required',[rid]));cur=z
  if cur<len(t):parts.append((cur,len(t),'necessary_context',[]))
 elif n==146:parts=[(0,t.index(' and Devices, comprising'),'required',[rid]),(t.index(' and Devices, comprising'),len(t),'necessary_context',[])]
 elif n==93:
  spans=[]
  for phrase in ['Microsoft 365 Commercial products and cloud services','the cloud portion of Windows Commercial','Windows Commercial on-premises']:
   a=t.index(phrase);spans.append((a,a+len(phrase)))
  cur=0
  for a,z in sorted(spans):
   if a>cur:parts.append((cur,a,'necessary_context',[]))
   parts.append((a,z,'required',[rid]));cur=z
  if cur<len(t):parts.append((cur,len(t),'necessary_context',[]))
 else:
  end=t.index(',');parts=[(0,end,'required',[rid]),(end,len(t),'necessary_context',[])]
 intervals[n]=parts
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}}
gold={'schema_version':'evidence-gold-v1','case_id':'E1-05','question':packet['question'],'company_ids':[source['company_id']],'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'text'} for r in freeze['case']['requirements']],'optional':[]}
deliveries=[];citations={i:[] for i in ['B1','B2','B3','B4']}
for n,b in actual.items():
 deliveries.append({'id':f'D{n}','source_id':sid,'block_id':b['block_id'],'start':0,'end':len(b['text']),'quote':b['text'],'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in intervals[n]]})
 for a,z,c,ids in intervals[n]:
  for rid in ids:citations[rid].append({'source_id':sid,'block_id':b['block_id'],'start':a,'end':z,'quote':b['text'][a:z]})
reasons={'B1':'原件明确 three segments，并完整列出三个分部。未将 Microsoft Cloud 或任何产品提升为第四分部。','B2':'连续PBP标题/总述和四个列表保留Commercial、Consumer、LinkedIn、Dynamics所属关系；Windows Commercial的云和本地组成均明确属于Commercial组合。','B3':'IC标题/总述、Server products and cloud services及Enterprise and partner services两类齐全；前者同时包含Azure and other cloud services和Server products，不只交Azure。','B4':'MPC标题/总述与Windows and Devices、Gaming、Search and news advertising三类齐全；Windows明确限定OEM渠道，避免误把所有Windows商业组成归MPC。'}
calls=[read(p) for p in run.rglob('*-end.json')];known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0));unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0));usage=Counter()
for c in calls:
 for k,v in (c.get('usage') or {}).items():
  if type(v)is int:usage[k]+=v
review={'schema_version':'evidence-review-v1','case_id':'E1-05','question':packet['question'],'reviewer':'Codex e1_gold_reading; original-first after frozen gold; inherited prior summaries, not fully blind','requirements':[{'id':rid,'status':'supported','reason':reasons[rid],'citations':citations[rid]} for rid in reasons],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'只采用指定Microsoft FY2025原年报，保留当年分部所属。','truth':'18个交付块逐一核对原件DOM文本；另外回读相邻业务段与Note18替代列表，三个分部九个顶层业务组合齐全，非根据模型自审判断。','provenance':'原件hash、冻结标准、数据集、query和run manifest均核对，所有引用原文精确定位。','focus':'按冻结原段落保留政策通过，无整份财报、重复Note18列表、整段竞对/增长/AI战略。仍有管理目的与未触发跨年需求的重组历史可删；子产品列表不等于必需独立节点。未在事后加一个字符阈值。'}.items()},'deliveries':deliveries,'metadata_deliveries':[],'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)},
'conditional_context_assessment':{'FY24_segment_amounts_delivered':False,'FY24_comparison_requested':False,'membership_change_explanation_requested':False,'reorganization_paragraph_required':False,'reason':'交付保留FY2025的Windows Commercial/OEM划分，没有比较FY2024或声称变化，故历史变更段不自动变成必需。'},
'category_interpretation':{'necessary_context':'原列表内支持性产品说明、连接词及引导句；按冻结段落保留规则允许，但不表示所有子产品细节都不可删。','irrelevant':'可删的管理目的说明和未触发条件的重组历史；不含错误事实。','required':'直接支撑分部、顶层组合、所属及Windows必要限定的原文范围；分部总述保留功能和列表连接。'},'limitations':['不是证明唯一数学最小证据集。','标题和列表共同建立归属；无需每个子产品独立节点。','评价是预冻结问题的取材充分性，不等于财报整体解析质量或所有query已验收。']}
review['checks']['focus']={'status':'fail','reason':'B1-B4覆盖完整，但E0087是可整块删除的490字符重组历史。题目没有FY2024比较、金额或归属变化解释，冻结conditional_context未触发；删除不会破坏三个分部九组归属。原段落保留许可只支持必需列表的细产品名，不豁免额外无关整段。另E0086后320字符管理说明可压缩。'}
review['minimum_sufficient_delivery']={'status':'fail','whole_block_removable':[{'block_id':actual[87]['block_id'],'characters':len(actual[87]['text']),'coverage_after_removal':'B1-B4 all supported; membership/current-year context remains in source metadata, headings and lists'}],'other_compressible_characters':320,'limitation':'Not a proof of unique smallest text; identifies a definite removable whole block.'}
score=evaluate(gold,review,corpus)
results=[]
for p in sorted((run/'attempt-01').glob('review-*/result.json')):
 rr=read(p);results.append({'review':p.parent.name,'status':rr['status'],'analysis_eligible':rr['analysis_eligible'],'failures':rr['failures'],'known_estimated_usd':rr['usage']['summary']['calls']['known_estimated_usd']})
rr=read(run/'result.json');assert rr['status']=='reviewed_data_ready' and len(results)==2 and results[0]['status']=='failed' and results[1]['analysis_eligible'] is True
protocol=[]
for p in sorted((run/'attempt-01/data-query/model').glob('decision-*-attempt-*.json')):
 d=read(p)
 if d['status']!='decision_returned':protocol.append({'path':str(p.relative_to(run)),'status':d['status'],'validation':d.get('validation'),'error_type':d.get('error_type')})
audit={'gold_freeze_sha256':h(fp),'reference_sha256':h(refpath),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'source_sha256':h(raw),'packet_sha256':h(packetpath),'original_dom_delivery_matches':len(delivered),'independent_neighbor_and_alternative_readings':reading,'required_groups':9,'all_groups_present':True,'missing_required_groups':[],'retrieval_protocol_failures':protocol,'review_attempts':results,'workflow_status':rr['status'],'analysis_called':rr['analysis_called'],'adoption':rr['adoption'],'model_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'known_estimated_usd':str(known),'unknown_reserved_usd':str(unknown),'usage':dict(usage),'visible_body_characters':sum(len(b['text']) for b in delivered),'packet_file_bytes':packetpath.stat().st_size,'bytes_note':'review-packet file only, not complete HTTP request or all model inputs','excess_detail':{'management_purpose_after_segment_identity':len(actual[86]['text'])-actual[86]['text'].index('.')-1,'untriggered_reorganization_history':len(actual[87]['text'])},'audit_boundary':'No paid calls, runtime input changes or gold changes. Original text with neighboring sections reviewed; not full-filing exhaustive audit.'}
out=E/'evaluation-only/reviews/E1-05-sonnet-r1';out.mkdir()
for name,data in [('review.json',review),('score.json',score),('original-check.json',audit),('gold-projection.json',gold)]:
 with (out/name).open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'score':score,'cost':str(known),'calls':len(calls),'packet_bytes':packetpath.stat().st_size,'usage':dict(usage),'reviews':results,'extra':audit['excess_detail']},ensure_ascii=False,indent=2))
