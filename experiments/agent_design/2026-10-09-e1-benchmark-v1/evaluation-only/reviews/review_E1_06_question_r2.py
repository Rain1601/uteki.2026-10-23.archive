"""Offline frozen-standard check of system-selected Azure definition recovery."""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
from decimal import Decimal
import json
import sys
from lxml import html
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];sys.path.insert(0,str(E))
from compare_configs import verify_manifest
from summarize_runs import summarize

def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
name='E1-06-sonnet-question-audit-r2';run=E/'runs'/name;runhash=verify_manifest(run);result=read(run/'result.json')
assert result['status']=='reviewed_data_ready' and not result['analysis_called']
assert [(a['execution'],a['status']) for a in result['attempts']]==[('reused_frozen','needs_revision'),('new','reviewed_data_ready')]
fp=E/'evaluation-only/frozen/E1-06-v1.json';frozen=read(fp);reference=E/frozen['reference_path'];assert h(reference)==frozen['reference_sha256']
packetpath=run/'attempt-02/review-packet.json';packet=read(packetpath);assert packet['question']==frozen['case']['query_zh']
query=Path(result['final_query_ref']['path']);verify_manifest(query,result['final_query_ref']['manifest_sha256'])
assert query.is_relative_to(run)
dataset=Path(packet['dataset_ref']['path']);verify_manifest(dataset,frozen['dataset_manifest_sha256'])
source=read(dataset/'sources.json')[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']
tree=html.fromstring(raw.read_bytes());rt=tree.getroottree();nodes={rt.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
actual={b['block_id']:b for b in packet['source_documents'][0]['blocks']};assert len(actual)==10
for b in actual.values():assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
first=read(run/'attempt-01/review-packet.json');priorpacket=read(E/'runs/E1-06-sonnet-r4/attempt-02/review-packet.json');assert first['source_documents']==priorpacket['source_documents'] and first['facts']==priorpacket['facts']
oldblocks={b['block_id']:b for b in first['source_documents'][0]['blocks']};assert all(actual[k]==v for k,v in oldblocks.items());assert set(actual)-set(oldblocks)=={'block-000127-93a9159b'}
oldreviewdir=E/'evaluation-only/reviews/E1-06-sonnet-r4';oldaudit=read(oldreviewdir/'original-check.json');assert oldaudit['gold_freeze_sha256']==h(fp)
gold=read(oldreviewdir/'gold-projection.json');assert [r['id'] for r in gold['required']]==[r['id'] for r in frozen['case']['requirements']]
review=deepcopy(read(oldreviewdir/'review.json'))
new=actual['block-000127-93a9159b'];t=new['text'];a=t.index(' Customers');b=t.index(' Azure enables');c=t.index(' Azure revenue')
assert (a,b,c,len(t))==(180,385,563,681)
parts=[(0,a,'required',['C7']),(a,b,'necessary_context',[]),(b,c,'irrelevant',[]),(c,len(t),'required',['C7'])]
review['deliveries'].append({'id':'D127','source_id':sid,'block_id':new['block_id'],'start':0,'end':len(t),'quote':t,'segments':[{'start':i,'end':j,'category':cat,'requirement_ids':ids} for i,j,cat,ids in parts]})
c7=next(r for r in review['requirements'] if r['id']=='C7');c7.update(status='supported',reason='新增原文E0127直接定义Azure为开发者/IT/企业构建、部署和管理应用的云平台，并说明收入主要受IaaS/PaaS消费驱动；与既有Azure and other组合定义分开，补齐原冻结缺口。',citations=[{'source_id':sid,'block_id':new['block_id'],'start':i,'end':j,'quote':t[i:j]} for i,j,cat,ids in parts if cat=='required'])
review['reviewer']='Codex e1_gold_reading; original frozen seven requirements; all ten delivered blocks verified against original DOM; inherited prior context'
review['checks']['provenance']['reason']='新run/query/packet/gold/dataset/原件绑定核对，10个原文块逐一DOM匹配；IC数值另核原件XBRL。原9块未改，仅系统补取Azure定义段。'
review['checks']['truth']['reason']='三个口径、金额与增长率、Azure自身定义均和原件一致；34%仍属于Azure and other cloud services组合，未推算Azure收入。'
review['checks']['focus']['reason']='新增Azure定义段直接补C7，没有可整块去掉而不损覆盖的新增材料。段内服务例子可压缩，客户收益句178字符与本题定义/指标无关；原整表926附带仍在。按冻结整块标准通过，不等于最小充分交付。'
review['workflow_status']=result['status'];review['independent_overall_acceptance']=True
review['minimum_sufficient_delivery']={'status':'not_demonstrated','reason':'七项覆盖齐全；仍有926字符整表附带、178字符客户收益描述，以及可压缩的服务例子与上下文。没有宣称数学意义的最少材料。'}
review['category_interpretation']['necessary_context']='保留短增长句引导67字符及Azure服务例子205字符。后者作为定义段内支持性背景保留，非不可删除要求。'
review['category_interpretation']['irrelevant']='Azure客户可更多关注应用而非自建运维的收益句178字符；对本题平台定义及披露指标不必要，可在片段精简阶段删去。'
review['limitations']=['本轮从已付费r4查询恢复后补取，不是从零一次完成，旧成本单列。','全7项与原件复核，未改gold；新审核识别缺口和后续系统补取已分别核验。','固定粒度focus通过不等于交付已不可再精简。']
costs={r['run']:r for r in summarize(E/'runs')['runs']};cst=costs[name];assert cst['calls']==20 and Decimal(cst['known_estimated_usd'])==Decimal('1.934868')
review['cost']={'known_usd':cst['known_estimated_usd'],'unknown_reserved_usd':cst['unknown_reserved_usd']}
review['run_binding']={'run_path':str(run),'manifest_sha256':runhash,'packet_sha256':h(packetpath),'query_ref':packet['query_ref']}
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}}
score=evaluate(gold,review,corpus);assert score['status']=='pass' and score['required_coverage']['numerator']==7
score['workflow_status']=result['status'];score['independent_overall_acceptance']=True
reviewpath=Path(result['final_review_ref']['path']);verify_manifest(reviewpath,result['final_review_ref']['manifest_sha256']);finalreview=read(reviewpath/'result.json');assert finalreview['analysis_eligible']
feedback=read(run/'attempt-01/review-01/result.json');assert feedback['status']=='needs_revision' and not feedback['analysis_eligible']
request2=read(run/'attempt-02/request.json');qfirst=read(run/'attempt-01/review-01/question-response.json');qlast=read(reviewpath/'question-response.json');assert qfirst['question_coverage']=='incomplete' and qlast['question_coverage']=='complete'
assert request2['review_feedback']['assessment']['revision_requests']==feedback['assessment']['revision_requests']
num=next(n for n in tree.iter() if n.get('name')=='us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax' and ''.join(n.itertext()).strip()=='106,265');ctx=next(n for n in tree.iter() if n.get('id')==num.get('contextref'));xml=html.tostring(ctx,encoding='unicode');assert 'IntelligentCloud' in xml and '2024-07-01' in xml and '2025-06-30' in xml and num.get('scale')=='6';unit=next(n for n in tree.iter() if n.get('id')==num.get('unitref'));assert ''.join(unit.itertext()).strip()=='iso4217:USD'
audit={'gold_freeze_sha256':h(fp),'reference_sha256':h(reference),'dataset_manifest_sha256':h(dataset/'manifest.json'),'source_sha256':h(raw),'run_manifest_sha256':runhash,'query_manifest_sha256':h(query/'manifest.json'),'packet_sha256':h(packetpath),'final_packet_bytes':packetpath.stat().st_size,'final_body_characters':sum(len(b['text']) for b in actual.values()),'original_dom_delivery_matches':10,'new_definition_original':new,'ic_original_context_xml':xml,'system_final_status':result['status'],'system_analysis_eligible':True,'analysis_called':False,'cost':cst,'prior_reused_query_run_cost':costs['E1-06-sonnet-r4'],'prior_question_r1_cost':costs['E1-06-sonnet-question-audit-r1'],'new_run_cost_does_not_include_prior_retrieval':True,'r4_and_two_question_recovery_known_usd':str(sum((Decimal(costs[n]['known_estimated_usd']) for n in ['E1-06-sonnet-r4','E1-06-sonnet-question-audit-r1',name]),Decimal(0))),'old_nine_blocks_unchanged':True,'new_block_ids':sorted(set(actual)-set(oldblocks)),'char_segmentation_reuse':'Only unchanged original9 blocks retain prior exact segmentation; new681 chars independently segmented.'}
workflow={'attempt01_status':feedback['status'],'attempt01_question_coverage':qfirst['question_coverage'],'revision_requests':feedback['assessment']['revision_requests'],'feedback_present_in_attempt02_request':True,'attempt02_question_coverage':qlast['question_coverage'],'attempt02_status':finalreview['status'],'protocol_repair_attempted':{a:read(run/a/'review-01/result.json')['question_protocol_repair_attempted'] for a in ['attempt-01','attempt-02']},'new_definition_check':next(c for c in qlast['checks'] if c['requested_subject']=='Azure' and c['requested_dimension']=='definition'),'conclusion':'原问题审核提出概念定义缺口，反馈传入自主新查询，系统取回定义段，再经双审与独立原件核验通过。不是Codex替运行选段。'}
out=E/'evaluation-only/reviews'/name;out.mkdir()
for fn,value in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit),('recovery-chain.json',workflow)]:
 (out/fn).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':score['status'],'coverage':score['required_coverage'],'characters':score['characters'],'cost':cst['known_estimated_usd'],'packet_bytes':packetpath.stat().st_size},ensure_ascii=False,indent=2))
