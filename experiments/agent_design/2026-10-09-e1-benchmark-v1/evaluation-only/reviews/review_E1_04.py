"""Independent review of original failed cutoff run; evaluation only."""
import json
from pathlib import Path
from hashlib import sha256
from collections import Counter
from decimal import Decimal
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
ROOT=Path(__file__).resolve().parents[2]
def read(p): return json.loads(p.read_text())
def digest(p): return sha256(p.read_bytes()).hexdigest()
def save(p,v):
    with p.open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2)
run=ROOT/'runs/E1-04-sonnet-r1';_verify_manifest(run)
result=read(run/'result.json'); assert result['status']=='attempts_exhausted'
ref=result['final_review_ref']; final=Path(ref['path']);_verify_manifest(final,ref['manifest_sha256'])
packet=read(final/'input.json');assert packet['source_documents']==packet['facts']==packet['requirements']==[]
freeze_path=ROOT/'evaluation-only/frozen/E1-04-v1.json';freeze=read(freeze_path)
reference=ROOT/freeze['reference_path'];assert digest(reference)==freeze['reference_sha256']
assert packet['question']==freeze['case']['query_zh'];cutoff='2024-08-01'
dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256'])
sources=read(dataset/'sources.json'); source=next(s for s in sources if s['period_end']=='2024-06-30');future=next(s for s in sources if s['period_end']=='2025-06-30')
sid=source['source_snapshot_id'];future_id=future['source_snapshot_id'];assert source['available_at']=='2024-07-30' and future['available_at']=='2025-07-30'
raw=dataset/source['raw_file'];assert digest(raw)==source['source_sha256']
tree=html.fromstring(raw.read_bytes()); et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
original_checks=[]
for key in ['F24-0865','F24-1337','F24-1338','F24-1339','F24-1345','F24-1346']:
    expected=read(reference)['evidence_catalog'][key]; text=' '.join(nodes[expected['dom_path']].text_content().split())
    assert text==expected['original_text']==blocks[expected['candidate_block_id']]['text']
    original_checks.append({'evidence_id':key,'block_id':expected['candidate_block_id'],'text_sha256':sha256(text.encode()).hexdigest(),'dom_matches':True})
ctx=next(n for n in tree.iter() if n.get('id')=='C_6dbdb3a2-9baf-41b4-922d-f59879124337')
values={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)}
assert values['startdate']=='2023-07-01' and values['enddate']=='2024-06-30' and values['identifier']=='0000789019'
amount=next(n for n in tree.iter() if n.get('id')=='F_3c083f9d-9cbe-4037-b6c1-310e199227a1')
assert ' '.join(amount.itertext())=='245,122' and amount.get('unitref')=='U_USD' and amount.get('scale')=='6'
# Review every model-visible packet and every action/feedback from both attempts.
inputs=sorted(set(run.glob('attempt-*/data-query/query/turn-*/input.json'))|set(run.glob('attempt-*/review-*/input.json'))|set(run.glob('attempt-*/review-*/model/*-input.json')))
def walk(v,path=''):
    if isinstance(v,dict):
        for k,x in v.items():yield from walk(x,path+'/'+k)
    elif isinstance(v,list):
        for i,x in enumerate(v):yield from walk(x,path+'/'+str(i))
    else:yield path,v
future_blocks=list(map(json.loads,(dataset/future['index_folder']/'blocks.jsonl').read_text().splitlines()))
old_texts={b['text'] for b in blocks.values()}; unique_future=[b for b in future_blocks if len(b['text'])>=80 and b['text'] not in old_texts]
audit=[]
for p in inputs:
    obj=read(p);strings=[v for _,v in walk(obj) if isinstance(v,str)]
    future_paths=[k for k,v in walk(obj) if v==future_id]
    assert all('/source_snapshot_ids/' in k or k == '/review_feedback/assessment/source_checks/1/source_snapshot_id' for k in future_paths),(p,future_paths)
    assert not any(b['text'] in s for b in unique_future for s in strings),(p,'future body')
    if '/data-query/query/' in str(p):
        assert obj['retained_body']['items']==[] and not obj['source_leads'] and not obj['requirements']
        for s in obj['catalog']['discovery']['sources']:assert s['available_at']<=cutoff
    audit.append({'path':str(p.relative_to(run)),'sha256':digest(p),'future_id_paths':future_paths,'future_body_matches':0})
actions=[]
for p in sorted(run.glob('attempt-*/data-query/query/turn-*')):
    decision=read(p/'decision.json');feedback=read(p/'feedback.json');action=decision['action']
    assert action in {'load_skill','plan'}
    assert feedback['status']==('skill_loaded' if action=='load_skill' else 'rejected')
    actions.append({'path':str(p.relative_to(run)),'action':action,'status':feedback['status'],'reason':feedback.get('reason')})
assert Counter(a['action'] for a in actions)=={'load_skill':2,'plan':6}
# There were no worker calls, successful plans, query actions or source reads.
assert not list(run.glob('attempt-*/data-query/worker-model/calls/*-end.json'))
calls=[read(p) for p in run.rglob('*-end.json')]
known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0))
unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0))
gold={'schema_version':'evidence-gold-v1','case_id':'E1-04','question':packet['question'],'company_ids':[source['company_id']],
'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],
'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'metadata' if r['id'] in {'A2','T1'} else 'text'} for r in freeze['case']['requirements']], 'optional':[]}
review={'schema_version':'evidence-review-v1','case_id':'E1-04','question':packet['question'],'reviewer':'Codex e1_acquisition; frozen-standard original-source independent review',
'requirements':[{'id':r['id'],'status':'missing','reason':'最终交付为空，没有该项事实、正文或来源日期。过程截止日隔离通过不能代替交付证据。','citations':[]} for r in freeze['case']['requirements']],
'checks':{'scope':{'status':'pass','reason':'两次尝试共8个动作只有加载Skill和被拒绝的计划；12份模型可见输入中未来source ID仅作为不可变范围标识及前轮审阅反馈的来源标识，未交付未来正文。'},
 'truth':{'status':'unassessed','reason':'无事实交付，不将空结果当作正确答案。'},
 'provenance':{'status':'unassessed','reason':'运行与原件hash已核对，但最终没有可审查的出处交付。'},
 'focus':{'status':'fail','reason':'空交付缺失全部必要材料，无法回答；零多余字符不是聚焦成功。'}},
'deliveries':[],'metadata_deliveries':[],'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)}}
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}}
score=evaluate(gold,review,corpus)
out=ROOT/'evaluation-only/reviews/E1-04-sonnet-r1';out.mkdir()
check={'run_manifest_sha256':digest(run/'manifest.json'),'final_review_ref':ref,'packet_sha256':digest(final/'input.json'),'frozen_gold_sha256':digest(freeze_path),'source_sha256':digest(raw),'original_checks':original_checks,'xbrl_context_and_amount_verified':True,'future_source_id':future_id,'future_source_available_at':future['available_at'],'model_input_audit':audit,'actions':actions,'cutoff_body_isolation':'pass','semantic_delivery':'fail_empty','model_calls':len(calls),'runtime_status':result['status'],'failure_path':'Both attempts reject correct FY2024 period because explicit_periods treats ISO knowledge-cutoff date in question as unsupported observation-period syntax. Repeating equivalent plans never establishes requirements; no-progress limit seals empty packets; two reviewers correctly request materials, max_attempts exhausted.','projection_note':'All original A1/A2/T1 requirements preserved. T1 missing final publication metadata; separate audit confirms no future-body exposure. Source isolation is vacuously safe here; this run does not demonstrate successful cutoff-constrained retrieval.'}
for name,value in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',check)]:save(out/name,value)
print(json.dumps({'status':score['status'],'coverage':score['required_coverage'],'cost':score['cost'],'input_packets':len(inputs),'actions':len(actions)},ensure_ascii=False))
