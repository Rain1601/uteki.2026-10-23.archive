"""Offline independent evaluation of reused evidence and failed dual review."""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
from decimal import Decimal
import json
import sys
from lxml import html
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(E))
from compare_configs import verify_manifest
from summarize_runs import summarize

def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def stable(v):return sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
name='E1-06-sonnet-question-audit-r1';run=E/'runs'/name
runhash=verify_manifest(run);result=read(run/'result.json')
assert result['status']=='blocked_by_review_failure' and not result['analysis_called']
assert len(result['attempts'])==1 and result['attempts'][0]['execution']=='reused_frozen'
fp=E/'evaluation-only/frozen/E1-06-v1.json';frozen=read(fp)
reference=E/frozen['reference_path'];assert h(reference)==frozen['reference_sha256']
packetpath=run/'attempt-01/review-packet.json';packet=read(packetpath)
assert packet['question']==frozen['case']['query_zh']
query=Path(result['final_query_ref']['path']);verify_manifest(query,result['final_query_ref']['manifest_sha256'])
oldrun=E/'runs/E1-06-sonnet-r4';verify_manifest(oldrun)
oldpacketpath=oldrun/'attempt-02/review-packet.json';oldpacket=read(oldpacketpath)
same={k:packet[k]==oldpacket[k] for k in ['facts','source_documents','query_ref','scope','requirements']};assert all(same.values())
dataset=Path(packet['dataset_ref']['path']);verify_manifest(dataset,frozen['dataset_manifest_sha256'])
sources=read(dataset/'sources.json');assert len(sources)==1
source=sources[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']
tree=html.fromstring(raw.read_bytes());rt=tree.getroottree();nodes={rt.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
actual=packet['source_documents'][0]['blocks'];assert len(actual)==9
for b in actual:assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split())
missing=next(b for b in blocks.values() if b['block_id'].startswith('block-000127-'))
assert missing['text']==' '.join(nodes[missing['dom_path']].text_content().split())
assert missing['block_id'] not in {b['block_id'] for b in actual}
# Exact body equality permits reuse of already frozen character segmentation, not run bindings.
oldreviewdir=E/'evaluation-only/reviews/E1-06-sonnet-r4'
oldaudit=read(oldreviewdir/'original-check.json');assert oldaudit['gold_freeze_sha256']==h(fp)
gold=read(oldreviewdir/'gold-projection.json');assert [r['id'] for r in gold['required']]==[r['id'] for r in frozen['case']['requirements']]
review=deepcopy(read(oldreviewdir/'review.json'))
review['reviewer']='Codex e1_gold_reading; frozen seven-requirement review; reused evidence identity checked against original DOM; inherited prior context'
review['workflow_status']=result['status']
review['checks']['provenance']['reason']='本运行清单、原冻结标准、数据集、复用Query及原件hash均已核验；9块逐一回原始DOM复查。新packet与r4的facts/source_documents/scope/requirements完全相同，复用已验证字符分段，不复用旧run绑定。'
review['checks']['focus']['reason']='本轮没有补取或删减。9块均支撑已覆盖口径与指标，整表附带按冻结粒度允许；C7平台定义缺失，且仍非最小充分材料。'
review['limitations']=['本次是复用旧取材的双审恢复，并非全新独立取材。','所有7项按同一冻结语义复核，源内容未变；Azure自身平台定义仍缺失。','模型新审核识别缺口不等于已补足材料，协议错误使后续补取未发生。']
costs={r['run']:r for r in summarize(E/'runs')['runs']};cst=costs[name]
assert cst['calls']==2 and Decimal(cst['known_estimated_usd'])==Decimal('0.196590')
review['cost']={'known_usd':cst['known_estimated_usd'],'unknown_reserved_usd':cst['unknown_reserved_usd']}
review['run_binding']={'run_path':str(run),'manifest_sha256':runhash,'packet_sha256':h(packetpath),'query_ref':packet['query_ref']}
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}}
score=evaluate(gold,review,corpus);assert score['status']=='fail' and score['required_coverage']['numerator']==6
score['workflow_status']=result['status'];score['independent_overall_acceptance']=False
reviewpath=Path(result['final_review_ref']['path']);verify_manifest(reviewpath,result['final_review_ref']['manifest_sha256'])
finalreview=read(reviewpath/'result.json');assert not finalreview['analysis_eligible'] and finalreview['status']=='failed'
q=read(reviewpath/'question-response.json');s=read(reviewpath/'source-response.json')
assert q['question_coverage']=='incomplete' and s['question_coverage']=='complete'
azure=next(c for c in q['checks'] if c['requested_subject']=='Azure' and c['requested_dimension']=='definition')
assert azure['coverage']=='partial' and azure['relation']=='broader'
invalid=[{'requested_subject':c['requested_subject'],'question_quote':c['question_quote'],'dimension':c['requested_dimension']} for c in q['checks'] if c['requested_subject'] not in c['question_quote']]
assert len(invalid)==3 and invalid[-1]['dimension']=='relationship'
# Recheck original amount context, scale and currency rather than infer them from the new reviewer.
num=next(n for n in tree.iter() if n.get('name')=='us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax' and ''.join(n.itertext()).strip()=='106,265')
ctx=next(n for n in tree.iter() if n.get('id')==num.get('contextref'))
xml=html.tostring(ctx,encoding='unicode');assert 'IntelligentCloud' in xml and '2024-07-01' in xml and '2025-06-30' in xml and num.get('scale')=='6'
unit=next(n for n in tree.iter() if n.get('id')==num.get('unitref'));assert ''.join(unit.itertext()).strip()=='iso4217:USD'
audit={'gold_freeze_sha256':h(fp),'reference_sha256':h(reference),'dataset_manifest_sha256':h(dataset/'manifest.json'),'source_sha256':h(raw),'run_manifest_sha256':runhash,'query_manifest_sha256':h(query/'manifest.json'),'packet_sha256':h(packetpath),'packet_bytes':packetpath.stat().st_size,'final_body_characters':sum(len(b['text']) for b in actual),'original_dom_delivery_matches':len(actual),'missing_definition_original':missing,'ic_original_context_xml':xml,'system_final_status':result['status'],'system_analysis_eligible':False,'analysis_called':False,'cost':cst,'prior_reused_query_run_cost':costs['E1-06-sonnet-r4'],'reused_query_ref':packet['query_ref'],'identity_checks_vs_r4':same,'identity_hashes':{k:stable(packet[k]) for k in same},'prior_packet_sha256':h(oldpacketpath),'new_run_cost_does_not_include_prior_retrieval':True,'r4_plus_this_recovery_known_usd':str(Decimal(cst['known_estimated_usd'])+Decimal(costs['E1-06-sonnet-r4']['known_estimated_usd']))}
workflow={'source_reviewer_coverage':s['question_coverage'],'question_reviewer_coverage':q['question_coverage'],'question_reviewer_azure_definition_check':azure,'invalid_subject_substrings':invalid,'recorded_failure':finalreview['failures'],'interpretation_zh':'原来源审核仍误判完整；独立原问题审核识别Azure产品定义缺口。三个requested_subject不在各自question_quote连续摘录内，其中关系项还改写了原问题，协议被拒；系统无补取，不能计作缺口已修复。'}
out=E/'evaluation-only/reviews'/name;out.mkdir()
for fn,value in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit),('workflow-diagnosis.json',workflow)]:
 (out/fn).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'coverage':score['required_coverage'],'characters':score['characters'],'cost':cst['known_estimated_usd'],'packet_bytes':packetpath.stat().st_size},ensure_ascii=False,indent=2))
