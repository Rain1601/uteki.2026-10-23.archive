"""Original-source cross-vintage segment review; no runtime changes."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-07-sonnet-r1';fp=E/'evaluation-only/frozen/E1-07-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def cost(r):
 cs=[read(p) for p in r.rglob('*-end.json')];u=Counter()
 for c in cs:
  for k,v in (c.get('usage') or {}).items():
   if type(v)is int:u[k]+=v
 return {'calls':len(cs),'known_estimated_usd':str(sum((Decimal(c['estimated_usd']) for c in cs if c.get('estimated_usd') is not None),Decimal(0))),'unknown_reserved_usd':str(sum((Decimal(c['reserved_usd']) for c in cs if c.get('estimated_usd') is None),Decimal(0))),'call_statuses':dict(Counter(c['status'] for c in cs)),'usage':dict(u)}
_verify_manifest(run);freeze=read(fp);ref=E/freeze['reference_path'];assert h(ref)==freeze['reference_sha256'];packetpath=run/'attempt-02/review-packet.json';packet=read(packetpath);assert packet['question']==freeze['case']['query_zh'];dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,freeze['dataset_manifest_sha256']);query=Path(packet['query_ref']['path']);_verify_manifest(query,packet['query_ref']['manifest_sha256']);sources=read(dataset/'sources.json');assert len(sources)==2
expected={'source-8602d79f703e48c18c2f27c3':('2024-06-30','2024-07-30','S1',{'msft:ProductivityAndBusinessProcessesMember':'77728','msft:IntelligentCloudMember':'105362','msft:MorePersonalComputingMember':'62032'}),'source-360182cbf562dcf9a8ab9c4e':('2025-06-30','2025-07-30','S2',{'msft:ProductivityAndBusinessProcessesMember':'106820','msft:IntelligentCloudMember':'87464','msft:MorePersonalComputingMember':'50838'})}
records=[f for f in packet['facts'] if f['kind']=='record'];assert len(records)==6;assert {f['kind'] for f in packet['facts']}=={'record','source_block'};assert set(packet['scope']['source_snapshot_ids'])==set(expected);assert packet['scope']['company_ids']==['sec-0000789019'];assert len(packet['source_documents'])==2
corpus={};deliveries=[];metadel=[];support={k:[] for k in ['S1','S2','S3']};numericchecks=[];differences={}
for source in sources:
 sid=source['source_snapshot_id'];year,available,rid,values=expected[sid];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256'];tree=html.fromstring(raw.read_bytes());rt=tree.getroottree();nodes={rt.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)};blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())};doc=next(d for d in packet['source_documents'] if d['source_snapshot_id']==sid);assert doc['source_period_end']==year and doc['available_at']==available
 sr=[f for f in records if f['value']['source_snapshot_id']==sid];assert len(sr)==3;bindings=[]
 for f in sr:
  v=f['value'];assert v['metric_id']=='revenue' and v['unit']=='USD' and v['available_at']==available and v['value_kind']=='actual';assert len(v['dimensions'])==1;member=v['dimensions']['us-gaap:StatementBusinessSegmentsAxis'];assert Decimal(v['value_decimal'])==Decimal(values[member])*1000000
  cite=f['citations'][0];assert cite['source_snapshot_id']==sid;body=blocks[cite['block_id']];assert body['text'][cite['char_start']:cite['char_end']]==cite['quote'];table=nodes[body['dom_path']];cell=table.xpath('.//tr')[cite['cell']['row']].xpath('./td|./th')[cite['cell']['column']];assert ' '.join(cell.text_content().split())==cite['quote'];num=next(n for n in cell.iter() if n.get('contextref'));assert num.get('contextref')==v['origin']['context_ref'] and num.get('name')==v['origin']['concept'] and num.get('scale')=='6'
  ctx=next(n for n in tree.iter() if n.get('id')==num.get('contextref'));cv={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)};assert cv['identifier']=='0000789019' and cv['startdate']==v['period']['start']=='2023-07-01' and cv['enddate']==v['period']['end']=='2024-06-30';members=[n for n in ctx.iter() if n.tag.split(':')[-1]=='explicitmember'];assert len(members)==1 and members[0].get('dimension')=='us-gaap:StatementBusinessSegmentsAxis' and ''.join(members[0].itertext()).strip()==member
  unit=next(n for n in tree.iter() if n.get('id')==num.get('unitref'));assert ''.join(unit.itertext()).strip()=='iso4217:USD';assert v['origin']['raw_dimensions']==v['dimensions']
  binding={k:v[k] for k in ['record_id','source_snapshot_id','value_decimal','unit','period','dimensions','available_at','accounting_basis']};binding.update(source_sha256=doc['source_sha256'],report_period_end=year);bindings.append(binding)
  numericchecks.append({'source_id':sid,'record_id':v['record_id'],'member':member,'amount_million':values[member],'cell':cite['cell'],'block_id':cite['block_id'],'dom_path':rt.getpath(num),'original_numeric_attributes':dict(num.attrib),'context_xml':html.tostring(ctx,encoding='unicode'),'unit':'iso4217:USD'})
  differences.setdefault(member,{})[year]=Decimal(values[member])
 m=sorted(bindings,key=lambda b:b['record_id']);corpus[sid]={'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{'delivered_versioned_records':m}};metadel.append({'id':'M'+str(len(metadel)+1),'source_id':sid,'field':'delivered_versioned_records','value':m})
 for b in doc['blocks']:
  t=b['text'];assert t==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split());n=int(b['block_id'].split('-')[1]);parts=[]
  if rid=='S1' and b['type']=='table':
   end=t.index(' Total');parts=[(0,end,'required',[rid]),(end,len(t),'table_structure',[])]
  elif rid=='S2' and b['type']=='table':
   end=t.index(' Productivity');spans=[(0,end)]
   for label in ['Productivity and Business Processes Revenue','Intelligent Cloud Revenue','More Personal Computing Revenue']:
    a=t.index(label);z=t.index(' Cost of revenue',a);spans.append((a,z))
   cursor=0
   for a,z in spans:
    if a>cursor:parts.append((cursor,a,'table_structure',[]))
    parts.append((a,z,'required',[rid]));cursor=z
   if cursor<len(t):parts.append((cursor,len(t),'table_structure',[]))
  elif n==817:
   end=t.index(' These changes primarily impacted');parts=[(0,end,'required',['S3']),(end,len(t),'necessary_context',[])]
  else:parts=[(0,len(t),'necessary_context',[])]
  deliveries.append({'id':'D'+str(len(deliveries)+1),'source_id':sid,'block_id':b['block_id'],'start':0,'end':len(t),'quote':t,'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in parts]})
  for a,z,c,ids in parts:
   for i in ids:support[i].append({'source_id':sid,'block_id':b['block_id'],'start':a,'end':z,'quote':t[a:z]})
assert len(deliveries)==5;assert all(len(v)==2 for v in differences.values());assert sum(v['2024-06-30'] for v in differences.values())==sum(v['2025-06-30'] for v in differences.values())==Decimal(245122)
plans=[]
for p in sorted(query.glob('turn-*/decision.json')):
 d=read(p)
 if d.get('plan'):
  assert not d['plan']['calculations'];plans.append({'path':str(p.relative_to(run)),'calculations':d['plan']['calculations']})
assert plans
cst=cost(run);gold={'schema_version':'evidence-gold-v1','case_id':'E1-07','question':packet['question'],'company_ids':['sec-0000789019'],'sources':[{'source_id':s['source_snapshot_id'],'company_id':s['company_id'],'sha256':s['source_sha256']} for s in sources],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'metadata' if r['id']=='S4' else 'text'} for r in freeze['case']['requirements']],'optional':[]}
reasons={'S1':'FY2024原表三分部FY2024列77728/105362/62032 millionUSD齐全；三个原始数值标签、单位、维度和FY2024context分别验证。','S2':'FY2025原表FY2024比较列106820/87464/50838 millionUSD齐全；未用FY2025本年值，三个XBRLcontext仍是2023-07-01至2024-06-30。','S3':'FY2025原件E0817明确2024年8月组成调整、M365商业组成集中PBP及以前期间按FY2025口径重列；本题正是条件触发，必须保留。','S4':'六条真实交付记录保留两个source/hash、available_at和报告期版本，观察期间均FY2024；原文将FY2025比较数说明为重列。旧数未覆盖，未相加或生成自然同比计算。accounting_basis字段本身只写reported_dimensioned，as-reported/recast语义由来源版本和原文共同提供，不伪称存在专门重列标签。'}
review={'schema_version':'evidence-review-v1','case_id':'E1-07','question':packet['question'],'reviewer':'Codex e1_gold_reading; original/XBRL/frozen-standard independent content review, inherited history known','requirements':[{'id':r['id'],'status':'supported','reason':reasons[r['id']],'citations':[dict(m,kind='metadata') for m in metadel] if r['id']=='S4' else support[r['id']]} for r in freeze['case']['requirements']],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'Microsoft同一观察财年FY2024，两份明确来源版本；没有把FY2025本期金额混入。','truth':'六项原表数值/单位/分部维度/context及重列原文逐一核验。差异有口径变化解释，不是自然增长。','provenance':'源hash、记录与原表单元格、FY2024期间和两个来源版本保留；query/run/数据集/冻结标准manifest均核对。','focus':'两份相关分部表+各表短引导+一次重列说明，均服务跨版本比较；没有双份同年表或产品清单。整表成本利润及非目标年份仍属可裁切附带内容，固定粒度通过不等于最小字符。'}.items()},'deliveries':deliveries,'metadata_deliveries':metadel,'cost':{'known_usd':cst['known_estimated_usd'],'unknown_reserved_usd':cst['unknown_reserved_usd']},'workflow_status':'attempts_exhausted','workflow_accepted':False,'minimum_sufficient_delivery':{'status':'adequate_but_not_minimal','reason':'没有必需材料缺口，但原表其他年及成本/利润行可裁切；来源重复是任务所需，不是应删除的重复事实。'},'category_interpretation':{'table_structure':'非目标年份/费用利润等原表随附内容，不是每字必要。','necessary_context':'表引导及Note引用尾句；可进一步压缩，不是独立业务扩展。'},'conditional_context_assessment':{'recast_context_required_and_present':True,'unchanged_consolidated_total_claim_delivered':False,'business_migration_amount_claim_delivered':False,'note':'两张原表自带合计，不是Agent额外生成总额不变结论；独立校验合计不冒充已交付E0818。'},'limitations':['content pass does not override ambiguity workflow guard','metadata preserves source variants; no explicit recast-basis field is claimed','not unique mathematical minimum']}
corpus_score=evaluate(gold,review,corpus);assert corpus_score['status']=='pass' and corpus_score['required_coverage']['numerator']==4;corpus_score.update(evaluation_scope='independent_content_only',workflow_status='attempts_exhausted',workflow_accepted=False)
result=read(run/'result.json');assert result['status']=='attempts_exhausted';attempts=[]
for a in sorted(run.glob('attempt-*')):
 p=read(a/'review-packet.json');qr=read(a/'data-query/query/result.json');rr=read(a/'review-01/result.json');assert not rr['analysis_eligible'];attempts.append({'attempt':a.name,'query_status':qr['status'],'query_stop_reason':qr['stop_reason'],'review_status':rr['status'],'analysis_eligible':rr['analysis_eligible'],'model_requirement_verdicts':rr['assessment']['requirements'],'program_gaps':p['program_gaps'],'query_checks':[check for req in p['requirements'] for check in req.get('query_checks',[])],'cost':cost(a)})
audit={'source_numeric_checks':numericchecks,'body_dom_matches':len(deliveries),'actual_records_count':len(records),'gold_freeze_sha256':h(fp),'reference_sha256':h(ref),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'query_manifest_sha256':h(query/'manifest.json'),'packet_sha256':h(packetpath),'packet_file_bytes':packetpath.stat().st_size,'visible_body_characters':sum(len(d['quote']) for d in deliveries),'cost':cst,'workflow_status':result['status'],'analysis_called':result['analysis_called'],'adoption':result['adoption'],'attempts':attempts,'calculation_checks':plans,'independent_recast_differences_million':{k:str(v['2025-06-30']-v['2024-06-30']) for k,v in differences.items()},'difference_note':'Reviewer arithmetic sanity check, not a runtime-generated result or natural growth calculation.'}
issue={'observed':'Each segment query spans both source vintages, yielding two correct FY2024 values. Query guard marks each pair ambiguous and keeps requirement_incomplete even though both records and source-bound original tables plus recast explanation are delivered.','material_missing':False,'content_sufficient_for_requested_source_comparison':True,'distinguish':'For a one-value query this ambiguity guard is appropriate; this explicit two-version comparison needs source-bound variant semantics, not arbitrary latest-wins or blanket ambiguity bypass.','guard_preserved':True,'runtime_change_made':False,'independent_record_pairs':{k:{year:str(v) for year,v in vals.items()} for k,vals in differences.items()}}
out=E/'evaluation-only/reviews/E1-07-sonnet-r1';out.mkdir()
for fn,obj in [('gold-projection.json',gold),('review.json',review),('score.json',corpus_score),('original-check.json',audit),('workflow-diagnosis.json',issue)]:
 with (out/fn).open('x') as o:json.dump(obj,o,ensure_ascii=False,indent=2);o.write('\n')
print(json.dumps({'score':corpus_score,'cost':cst,'bytes':packetpath.stat().st_size,'chars':audit['visible_body_characters']},ensure_ascii=False,indent=2))
