"""Frozen-standard adjudication of E1-05 recovery; evaluation only."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];name='E1-05-sonnet-focus-recovery-r1';run=E/'runs'/name;previous=E/'runs/E1-05-sonnet-r1';oldreview=E/'evaluation-only/reviews/E1-05-sonnet-r1'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def cost(r):
 cs=[read(p) for p in r.rglob('*-end.json')];usage=Counter()
 for c in cs:
  for k,v in (c.get('usage') or {}).items():
   if type(v)is int:usage[k]+=v
 return {'calls':len(cs),'known_estimated_usd':str(sum((Decimal(c['estimated_usd']) for c in cs if c.get('estimated_usd') is not None),Decimal(0))),'unknown_reserved_usd':str(sum((Decimal(c['reserved_usd']) for c in cs if c.get('estimated_usd') is None),Decimal(0))),'call_statuses':dict(Counter(c['status'] for c in cs)),'usage':dict(usage)}
_verify_manifest(run);_verify_manifest(previous);fp=E/'evaluation-only/frozen/E1-05-v1.json';f=read(fp);assert h(E/f['reference_path'])==f['reference_sha256'];dataset=E/f['dataset_path'];_verify_manifest(dataset,f['dataset_manifest_sha256']);source=read(dataset/'sources.json')[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256'];tree=html.fromstring(raw.read_bytes());rt=tree.getroottree();nodes={rt.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)};blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
packetpath=run/'attempt-02/review-packet.json';packet=read(packetpath);assert packet['question']==f['case']['query_zh'];_verify_manifest(Path(packet['query_ref']['path']),packet['query_ref']['manifest_sha256']);old=read(previous/'attempt-01/review-packet.json');first=read(run/'attempt-01/review-packet.json')
assert first['source_documents']==old['source_documents'] and first['facts']==old['facts'];assert packet['scope']==old['scope'];assert len(packet['source_documents'])==1;doc=packet['source_documents'][0];assert doc['source_snapshot_id']==sid
newbs={b['block_id']:b for b in doc['blocks']};oldbs={b['block_id']:b for b in old['source_documents'][0]['blocks']};removed=set(oldbs)-set(newbs);assert removed=={'block-000087-44aabdcd'} and not set(newbs)-set(oldbs)
for bid,b in newbs.items():assert b==oldbs[bid] and b['text']==blocks[bid]['text']==' '.join(nodes[b['dom_path']].text_content().split())
assert all(x in newbs for x in ['block-000090-94a2e06c','block-000093-7018adaa','block-000095-61bd513b','block-000097-13124fb7','block-000099-da3d48eb','block-000117-925ee601','block-000120-c34f7245','block-000122-c07a987e','block-000143-c67f142f','block-000146-c641cfcd','block-000148-2f215a60','block-000150-9577a591'])
gold=read(oldreview/'gold-projection.json');review=read(oldreview/'review.json');review['reviewer']='Codex e1_gold_reading; recovery independently compared to raw and frozen E1-05-v1; prior review known';review['deliveries']=[x for x in review['deliveries'] if x['block_id'] not in removed]
review['checks']['focus']={'status':'pass','reason':'无触发条件的490字符历史段已整块删掉；仅保留本题分部介绍及核心列表。44字符过渡句是原章节的短阅读引导，按原冻结段落粒度可保留，也可删除，不据后一次模型自审把它升级为必删硬门槛。含必需首句的原段落后部管理文字及细产品说明可继续精简，但本轮未引入新阈值。'}
review['minimum_sufficient_delivery']={'status':'not_proven_minimal','optional_removable_transition':{'block_id':'block-000089-352d4c96','source_characters':44,'display_trimmed_characters':len(newbs['block-000089-352d4c96']['text'].strip()),'reason':'阅读引导没有独立业务事实；删除不影响四项必需覆盖，保留不造成题目范围扩展。'},'compressible_management_tail_characters':320,'note':'冻结验收focus通过不等于严格最少字符。没有把短过渡句规定为必须保留或必须删除。'}
review['conditional_context_assessment']['reorganization_paragraph_delivered']=False;review['workflow_status']='attempts_exhausted';review['workflow_accepted']=False
rcost=cost(run);ocost=cost(previous);review['cost']={'known_usd':rcost['known_estimated_usd'],'unknown_reserved_usd':rcost['unknown_reserved_usd']};review['cost_scope']='new recovery run only; original run separately in recovery-chain.json'
review['checks']['truth']['reason']='17个保留块逐一重新核对原件DOM文本，且与前次回读相邻业务段/Note18的原件结果一致；三个分部九个顶层业务组合齐全。'
review['category_interpretation']['irrelevant']='仍在含必需首句的E0086原段落中的320字符管理目的说明，可进一步压缩；重组历史已删除。'
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}};score=evaluate(gold,review,corpus);assert score['status']=='pass' and score['required_coverage']['numerator']==4;score['evaluation_scope']='independent_frozen_content_review_only';score['workflow_status']='attempts_exhausted';score['workflow_accepted']=False
result=read(run/'result.json');assert result['status']=='attempts_exhausted' and result['attempts'][0]['execution']=='reused_frozen' and result['attempts'][1]['execution']=='new'
reviews=[]
for a in sorted(run.glob('attempt-*')):
 rr=read(a/'review-01/result.json');assert rr['status']=='needs_revision' and not rr['analysis_eligible'];reviews.append({'attempt':a.name,'status':rr['status'],'analysis_eligible':rr['analysis_eligible'],'revision_requests':rr['assessment']['revision_requests'],'cost':cost(a)})
query=Path(packet['query_ref']['path']);decisions=[]
for p in sorted(query.glob('turn-*/decision.json')):
 d=read(p)
 if d['action']=='select_evidence':decisions.append({'path':str(p.relative_to(E)),'sha256':h(p),'decision':d})
assert decisions
chain={'original_run':str(previous.relative_to(E)),'original_independent_verdict':'fail_focus_untriggered_history','original_cost':ocost,'recovery_run':str(run.relative_to(E)),'recovery_cost':rcost,'combined_known_estimated_usd':str(Decimal(ocost['known_estimated_usd'])+Decimal(rcost['known_estimated_usd'])),'attempt01_original_packet_facts_and_body_identical':True,'attempt02_removed_blocks':sorted(removed),'attempt02_added_blocks':[],'remaining_block_bodies_identical':True,'new_system_select_evidence_decisions':decisions,'frozen_gold_unchanged':True,'reviews':reviews,'independent_content_verdict':'pass','workflow_status':result['status'],'analysis_called':result['analysis_called'],'adoption':result['adoption'],'interpretation':'系统已独立删除E87，审核模型又把原可选短过渡句判为redundant而拒绝放行。独立按原标准判focus通过，不回写系统状态。'}
audit={'source_sha256':h(raw),'dataset_manifest_sha256':h(dataset/'manifest.json'),'gold_freeze_sha256':h(fp),'reference_sha256':h(E/f['reference_path']),'run_manifest_sha256':h(run/'manifest.json'),'query_manifest_sha256':h(query/'manifest.json'),'packet_sha256':h(packetpath),'original_dom_matches':len(newbs),'source_characters':sum(len(b['text']) for b in newbs.values()),'packet_file_bytes':packetpath.stat().st_size,'required_coverage':'4/4 and nine core business groups','transition_text_repr':repr(newbs['block-000089-352d4c96']['text']),'limitation':'Full remaining original blocks match prior original-read review; no evidence standard changed to match current model review. This pass is not a workflow release or mathematical minimum claim.'}
out=E/'evaluation-only/reviews'/name;out.mkdir()
for fn,obj in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit),('recovery-chain.json',chain)]:
 with (out/fn).open('x') as o:json.dump(obj,o,ensure_ascii=False,indent=2);o.write('\n')
print(json.dumps({'score':score,'cost':rcost,'combined':chain['combined_known_estimated_usd'],'audit':audit},ensure_ascii=False,indent=2))
