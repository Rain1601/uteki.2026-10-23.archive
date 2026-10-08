"""Independent final-delivery E1-06 review; never feeds runtime."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-06-sonnet-r4';fp=E/'evaluation-only/frozen/E1-06-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def cost(r):
 cs=[read(p) for p in r.rglob('*-end.json')];u=Counter()
 for c in cs:
  for k,v in (c.get('usage') or {}).items():
   if type(v)is int:u[k]+=v
 return {'calls':len(cs),'known_estimated_usd':str(sum((Decimal(c['estimated_usd']) for c in cs if c.get('estimated_usd') is not None),Decimal(0))),'unknown_reserved_usd':str(sum((Decimal(c['reserved_usd']) for c in cs if c.get('estimated_usd') is None),Decimal(0))),'call_statuses':dict(Counter(c['status'] for c in cs)),'usage':dict(u)}
_verify_manifest(run);freeze=read(fp);ref=E/freeze['reference_path'];assert h(ref)==freeze['reference_sha256'];packetpath=run/'attempt-02/review-packet.json';packet=read(packetpath);assert packet['question']==freeze['case']['query_zh'];dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,freeze['dataset_manifest_sha256']);query=Path(packet['query_ref']['path']);_verify_manifest(query,packet['query_ref']['manifest_sha256']);source=read(dataset/'sources.json')[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256'];tree=html.fromstring(raw.read_bytes());rt=tree.getroottree();nodes={rt.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)};bs=list(map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines()));blocks={b['block_id']:b for b in bs};by={int(b['block_id'].split('-')[1]):b for b in bs}
assert len(packet['source_documents'])==1;doc=packet['source_documents'][0];actual={int(b['block_id'].split('-')[1]):b for b in doc['blocks']};assert set(actual)=={117,118,120,122,515,517,527,561,587};assert not any(f['kind']=='record' for f in packet['facts'])
for b in actual.values():assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
original_check=[]
for n in [127,515,517,527,551,557,561,587,613,817,1227]:
 b=by[n];assert b['text']==' '.join(nodes[b['dom_path']].text_content().split());original_check.append({'block_id':b['block_id'],'dom_path':b['dom_path'],'text':b['text']})
# Verify IC revenue cell and exact period against the original inline XBRL (audit only).
b=actual[587];table=nodes[b['dom_path']];num=next(n for n in tree.iter() if n.get('name')=='us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax' and ''.join(n.itertext()).strip()=='106,265');assert num.get('scale')=='6';ctx=next(n for n in tree.iter() if n.get('id')==num.get('contextref'));cx={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)};assert 'IntelligentCloud' in html.tostring(ctx,encoding='unicode');assert cx['startdate']=='2024-07-01' and cx['enddate']=='2025-06-30';unit=next(n for n in tree.iter() if n.get('id')==num.get('unitref'));assert ''.join(unit.itertext()).strip()=='iso4217:USD';assert doc['source_period_end']=='2025-06-30'
intervals={}
for n,b in actual.items():
 t=b['text']
 if n in [117,118]:parts=[(0,len(t),'required',['C2'])]
 elif n==120:parts=[(0,len(t),'required',['C2','C4','C6'])]
 elif n==122:parts=[(0,len(t),'required',['C2','C6'])]
 elif n==515:parts=[(0,len(t),'required',['C1','C5'])]
 elif n==517:parts=[(0,len(t),'required',['C1'])]
 elif n==527:
  start=t.index('Azure and other');parts=[(0,start,'necessary_context',[]),(start,len(t),'required',['C5'])]
 elif n==561:
  start=t.index('Microsoft Cloud revenue and revenue growth');end=t.index(' Microsoft Cloud gross margin');parts=[(0,start,'table_structure',[]),(start,end,'required',['C1','C6']),(end,len(t),'table_structure',[])]
 elif n==587:
  end=t.index(' Productivity and Business Processes');start=t.index('Intelligent Cloud Revenue');stop=t.index(' Cost of revenue',start);parts=[(0,end,'required',['C3']),(end,start,'table_structure',[]),(start,stop,'required',['C3']),(stop,len(t),'table_structure',[])]
 intervals[n]=parts
citations={i:[] for i in ['C1','C2','C3','C4','C5','C7','C6']};deliveries=[]
for n,b in actual.items():
 deliveries.append({'id':f'D{n}','source_id':sid,'block_id':b['block_id'],'start':0,'end':len(b['text']),'quote':b['text'],'segments':[{'start':a,'end':z,'category':c,'requirement_ids':ids} for a,z,c,ids in intervals[n]]})
 for a,z,c,ids in intervals[n]:
  for rid in ids:citations[rid].append({'source_id':sid,'block_id':b['block_id'],'start':a,'end':z,'quote':b['text'][a:z]})
reasons={'C1':'E0561定义表与E0517的168.9billionUSD、E0515年度比较标签共同支撑，等价于预列E1227语义。','C2':'E0117/118/120/122给出报告分部及服务器/云服务和企业伙伴服务两类。','C3':'E0587明确In millions及2025栏，IC Revenue106265；来源元数据June30 2025与原件同数值XBRL FY2025上下文核对，附带2024列不替代本题FY2025金额。','C4':'E0120完整列Azure and other cloud services含cloud/AI consumption、GitHubcloud、NuanceHealthcarecloud、virtualdesktop及other，且与Serverproducts分开。','C5':'E0527明确该组合收入增长34%，E0515对应FY2025与FY2024比较；不是美元金额，也非固定汇率标签。原件复核允许等价出处，不锁死E0613。','C7':'缺失：最终9块只描述Azure and other cloud services组合，没有Azure自身面向开发者/IT/企业构建、部署、管理应用的平台定义，也无IaaS/PaaS消费驱动。原件E0127有该定义，最终未交付任何等价材料。','C6':'E0561组成含Azureandother，E0120显示它在IC服务器/云组合之内，IC另含企业伙伴服务；组成足以支持重叠判别，无需原件出现不可相加四字。未交付任何相加或推算Azure金额。'}
gold={'schema_version':'evidence-gold-v1','case_id':'E1-06','question':packet['question'],'company_ids':[source['company_id']],'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'text'} for r in freeze['case']['requirements']],'optional':[]};cst=cost(run)
review={'schema_version':'evidence-review-v1','case_id':'E1-06','question':packet['question'],'reviewer':'Codex e1_gold_reading; frozen-standard original-source review; prior history and attempt01 observed','requirements':[{'id':r['id'],'status':'missing' if r['id']=='C7' else 'supported','reason':reasons[r['id']],'citations':citations[r['id']]} for r in freeze['case']['requirements']],
'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'仅指定Microsoft FY2025原件，无跨公司/报告替换。','truth':'最终交付金额、增长率、组成与原文一致；未推算Azure金额。缺少平台定义单独计C7missing，不把组合定义冒充完整覆盖。','provenance':'9个DOM原块、原件hash、dataset/query/run和冻结标准均核验；IC金额原件XBRL期间/单位也核对。','focus':'额外E0611/613/615/616/618收入、利润、成本增长段已删除。剩余块均支撑口径/指标，整表附带内容按冻结粒度保留；这不是最少材料达标，且C7仍缺。'}.items()},'deliveries':deliveries,'metadata_deliveries':[],'cost':{'known_usd':cst['known_estimated_usd'],'unknown_reserved_usd':cst['unknown_reserved_usd']},'workflow_status':'reviewed_data_ready','independent_overall_acceptance':False,
'conditional_context_assessment':{'recast_context_triggered':False,'reason':'题目仅FY2025；FY2024比较列及其百分比为保留原表的附带信息，未另作跨版本/FY2024可比性分析。没有事后把它扩大为必须交付历史重组段的任务。若下游实际解释跨期可比性需再取重列说明。','actual_growth_basis':'E0515明示FY2025相较FY2024，为增长期间的等价说明；无固定汇率结论。'},
'category_interpretation':{'table_structure':'定义表和分部表的非必需附带数据，可进一步裁切，不是全部必要语法。','necessary_context':'同一短增长句中对服务器产品大类增长的引导，非Azure组合34%的独立必需内容。'},'minimum_sufficient_delivery':{'status':'fail','reason':'C7缺失；同时整表中有可删的其他业务/利润/费用/历史列。固定块粒度focus通过不代表用户最小充分目标达成。'},'limitations':['不因系统自审通过而降低冻结七要点。','评测等价出处已回原件核验；未更改冻结标准或向模型喂答案。']}
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}};score=evaluate(gold,review,corpus);assert score['required_coverage']['numerator']==6 and score['required_coverage']['denominator']==7 and score['status']=='fail';score['workflow_status']='reviewed_data_ready';score['independent_overall_acceptance']=False
result=read(run/'result.json');assert result['status']=='reviewed_data_ready';finalreview=read(Path(result['final_review_ref']['path'])/'result.json');assert finalreview['analysis_eligible'] is True
first=read(run/'attempt-01/review-packet.json');firstbs={b['block_id']:b for b in first['source_documents'][0]['blocks']};lastbs={b['block_id']:b for b in doc['blocks']};assert set(firstbs)-set(lastbs)=={'block-000611-8968a2bf','block-000613-2b412f2d','block-000615-f2839461','block-000616-b682a4da','block-000618-117c3023'}
for bid,b in lastbs.items():assert b==firstbs[bid]
prior=cost(E/'runs/E1-06-sonnet-r2');r1cost=cost(E/'runs/E1-06-sonnet-r1');r3cost=cost(E/'runs/E1-06-sonnet-r3')
r3packet=read(E/'runs/E1-06-sonnet-r3/attempt-02/review-packet.json');assert packet['source_documents']==r3packet['source_documents'];assert {f['fact_id']:(f['value'],f['citations']) for f in packet['facts']}=={f['fact_id']:(f['value'],f['citations']) for f in r3packet['facts']}
audit={'gold_freeze_sha256':h(fp),'reference_sha256':h(ref),'source_sha256':h(raw),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'query_manifest_sha256':h(query/'manifest.json'),'packet_sha256':h(packetpath),'original_dom_delivery_matches':9,'original_neighbor_and_missing_definition_readings':original_check,'ic_numeric_attrs':dict(num.attrib),'ic_numeric_location':rt.getpath(num),'ic_numeric_note':'MD&A table has no inline numeric tag at this cell; separately checked same IntelligentCloud FY2025 amount in Note18 inline XBRL. This corroboration is reviewer-only, not delivered extra evidence.','ic_context_xml':html.tostring(ctx,encoding='unicode'),'final_packet_bytes':packetpath.stat().st_size,'final_body_characters':sum(len(b['text']) for b in actual.values()),'removed_from_attempt01':sorted(set(firstbs)-set(lastbs)),'system_final_status':result['status'],'system_analysis_eligible':finalreview['analysis_eligible'],'analysis_called':result['analysis_called'],'cost':cst,'attempt_costs':{a.name:cost(a) for a in sorted(run.glob('attempt-*'))},'prior_r2_failed_cost':prior,'prior_r3_cost':r3cost,'final_body_identical_to_r3':True,'fact_values_and_citations_identical_to_r3':True,'fact_order_and_requirement_links_identical_to_r3':False,'prior_r1_not_sent_cost':r1cost,'case_cumulative_known_estimated_usd':str(Decimal(cst['known_estimated_usd'])+Decimal(prior['known_estimated_usd'])+Decimal(r1cost['known_estimated_usd'])+Decimal(r3cost['known_estimated_usd'])),'interpretation':'R4 final source_documents and fact values/citations match R3, while fact ordering and requirement links changed; coverage remains6/7. All seven frozen requirements were rechecked against original, not only known C7. Process success and independent sufficiency remain distinct.'}
out=E/'evaluation-only/reviews/E1-06-sonnet-r4';out.mkdir()
for fn,obj in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit)]:
 with (out/fn).open('x') as o:json.dump(obj,o,ensure_ascii=False,indent=2);o.write('\n')
print(json.dumps({'score':score,'cost':cst,'chars':audit['final_body_characters'],'bytes':audit['final_packet_bytes'],'cumulative':audit['case_cumulative_known_estimated_usd']},ensure_ascii=False,indent=2))
