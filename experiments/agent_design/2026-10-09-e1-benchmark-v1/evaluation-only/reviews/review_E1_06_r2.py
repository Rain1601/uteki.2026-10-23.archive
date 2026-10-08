"""Failure accounting and original-source diagnosis; never runtime input."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from collections import Counter
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate
E=Path(__file__).resolve().parents[2];run=E/'runs/E1-06-sonnet-r2';fp=E/'evaluation-only/frozen/E1-06-v1.json'
def read(p):return json.loads(p.read_text())
def h(p):return sha256(p.read_bytes()).hexdigest()
def cost(r):
 calls=[read(p) for p in r.rglob('*-end.json')];usage=Counter()
 for c in calls:
  for k,v in (c.get('usage') or {}).items():
   if type(v)is int:usage[k]+=v
 return {'calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'known_estimated_usd':str(sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0))),'unknown_reserved_usd':str(sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0))),'usage':dict(usage)}
_verify_manifest(run);freeze=read(fp);ref=E/freeze['reference_path'];assert h(ref)==freeze['reference_sha256'];dataset=E/freeze['dataset_path'];_verify_manifest(dataset,freeze['dataset_manifest_sha256']);source=read(dataset/'sources.json')[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];assert h(raw)==source['source_sha256']
bs=list(map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines()));blocks={b['block_id']:b for b in bs};numbers={int(b['block_id'].split('-')[1]):b for b in bs};tree=html.fromstring(raw.read_bytes());et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
runresult=read(run/'result.json');assert runresult['status']=='attempts_exhausted';assert runresult['question']==freeze['case']['query_zh']
attempts=[];snapshots=[]
for a in sorted(run.glob('attempt-*')):
 q=a/'data-query/query';_verify_manifest(q);result=read(q/'result.json');packet=read(a/'review-packet.json');assert result['status']=='limited' and result['stop_reason']=='no_progress_limit';assert not packet['facts'] and not packet['source_documents'] and not result['delivery_selection']
 bundle=read(q/'evidence-bundle.json');readblocks={};contexts=[]
 for item in bundle['items']:
  ap=q/item['artifact']['path'];assert h(ap)==item['artifact']['sha256'];context=read(ap)
  for b in context.get('blocks',[]):
   assert b['text']==blocks[b['block_id']]['text']==' '.join(nodes[b['dom_path']].text_content().split());readblocks[b['block_id']]=b
  contexts.append({'artifact_path':item['artifact']['path'],'sha256':h(ap),'block_ids':[b['block_id'] for b in context.get('blocks',[])]})
 turns=[]
 for p in sorted(q.glob('turn-*/decision.json')):
  d=read(p);fb=read(p.with_name('feedback.json')) if p.with_name('feedback.json').exists() else {};rc=fb.get('receipt') or {};turns.append({'turn':p.parent.name,'action':d['action'],'reason':d.get('reason'),'artifact_read':d.get('artifact_read'),'read':d.get('read'),'status':fb.get('status'),'error_reason':fb.get('reason'),'progress_delta':rc.get('progress_delta')})
 assert not any(x['action']=='select_evidence' for x in turns)
 nb={int(k.split('-')[1]) for k in readblocks};mapping={'C1':{'read_support':all(n in nb for n in [517,561]),'reason':'Cloud amount in E0517 plus definition in E0561'},'C2':{'read_support':all(n in nb for n in [117,118,120,122]),'reason':'IC definition and both principal groups'},'C3':{'read_support':587 in nb or 1217 in nb,'reason':'IC amount table only appeared as search preview, no full table read'},'C4':{'read_support':120 in nb,'reason':'Azure and other cloud services group definition'},'C5':{'read_support':527 in nb,'reason':'E0527 explicitly states Azure and other cloud services revenue growth of34%; source original verified as equivalent semantic support'},'C7':{'read_support':127 in nb,'reason':'Azure product/platform definition not read'},'C6':{'read_support':all(n in nb for n in [561,120,122]),'reason':'Components permit overlap inference, not a delivered judgement'}}
 attempts.append({'attempt':a.name,'status':result['status'],'stop_reason':result['stop_reason'],'query_manifest_sha256':h(q/'manifest.json'),'final_selected_blocks':[],'final_facts_count':0,'final_source_documents_count':0,'packet_file_bytes':(a/'review-packet.json').stat().st_size,'body_read_blocks':len(readblocks),'body_read_characters':sum(len(b['text']) for b in readblocks.values()),'read_block_ids':sorted(readblocks),'original_dom_body_matches':len(readblocks),'contexts':contexts,'read_but_not_delivered_requirement_diagnostic':mapping,'plans':result['plans'],'turns':turns,'cost':cost(a)})
 for k,b in readblocks.items():snapshots.append({'attempt':a.name,'block_id':k,'dom_path':b['dom_path'],'text':b['text']})
# The diagnostic is not a score: no context read above was selected for final delivery.
costs=cost(run);corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':{}}};gold={'schema_version':'evidence-gold-v1','case_id':'E1-06','question':freeze['case']['query_zh'],'company_ids':[source['company_id']],'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],'required':[{'id':r['id'],'description':r['meaning_zh'],'kind':'text'} for r in freeze['case']['requirements']],'optional':[]}
review={'schema_version':'evidence-review-v1','case_id':'E1-06','question':freeze['case']['query_zh'],'reviewer':'Codex e1_gold_reading; independently checked frozen criteria, original and run snapshots; inherited history, not fully blind','requirements':[{'id':r['id'],'status':'missing','reason':'最终交付为空；过程曾读到或搜索预览出现均不算交付。'+r['meaning_zh'],'citations':[]} for r in freeze['case']['requirements']],'checks':{'scope':{'status':'pass','reason':'固定Microsoft FY2025单来源，核对数据集与运行绑定；这不等于有交付。'},'truth':{'status':'unassessed','reason':'无最终内容可核验，不能空集冒充内容真实通过。'},'provenance':{'status':'unassessed','reason':'原件与过程绑定可验证，但没有最终证据或定位可交付。'},'focus':{'status':'fail','reason':'零facts/零正文，无法回答问题；零冗余不是最小充分材料。'}},'deliveries':[],'metadata_deliveries':[],'cost':{'known_usd':costs['known_estimated_usd'],'unknown_reserved_usd':costs['unknown_reserved_usd']},'workflow_status':'attempts_exhausted','minimum_sufficient_delivery':{'status':'fail','reason':'没有形成任何可供分析Agent消费的证据集。'},'evaluation_boundary':'Only final delivery counts; process-read diagnostic is separate and never injected to runtime.'}
score=evaluate(gold,review,corpus);assert score['required_coverage']=={'numerator':0,'denominator':7,'ratio':0.0} and score['status']=='fail'
r1=E/'runs/E1-06-sonnet-r1';_verify_manifest(r1);r1calls=[read(p) for p in r1.rglob('*-end.json')];assert len(r1calls)==2
for c in r1calls:assert c['dispatch_status']=='not_sent' and Decimal(c['estimated_usd'])==0
network={'run':str(r1.relative_to(E)),'cost':cost(r1),'calls':[{'call_id':c['call_id'],'status':c['status'],'dispatch_status':c['dispatch_status'],'error_type':c.get('error_type'),'estimated_usd':c['estimated_usd'],'transport_phase':c.get('transport_phase')} for c in r1calls],'note':'Recorded connection attempts not sent; separate from r2 paid failure. Zero is supported by dispatch log, not inferred from empty output.'}
rootcause={'observed':['两次合法plan都把不推算Azure未披露收入扩成寻找未披露的原文声明，第二次使用the statement而非any statement。','attempt-01 turn-014 read_source使用未知块被unknown read block拒绝；之后又回outline/search。','attempt-02反复读取同catalog offset36；turn16/18/20等重复读取无新进展，未执行select_evidence。','两轮都已有Cloud金额/定义、IC范围和Azure组合增长，IC金额只见搜索预览，Azure平台定义未读。','no_progress_limit触发后交付为空；外层启动第二轮又从头查找，没有保留可交付选择。'],'causal_limits':['负面证明目标膨胀是明确观察到的规划偏差，但日志不能证明它是唯一停止原因。','no_progress_limit是记录终态；该机制/计数是否存在实现缺陷应由工程另行检验。','不能用本评估列出的标准块代替系统未来独立选材。'],'negative_evidence_rule':'不推算是一项行为约束；有范围检索未找到应写检索范围与gap，不能要求财报必须存在一句未披露声明。','read_only_not_delivery':True}
audit={'source_sha256':h(raw),'gold_freeze_sha256':h(fp),'reference_sha256':h(ref),'dataset_manifest_sha256':h(dataset/'manifest.json'),'run_manifest_sha256':h(run/'manifest.json'),'attempts':attempts,'cost':costs,'r1_network_not_sent':network,'final_body_characters':0,'final_facts_count':0,'analysis_called':runresult['analysis_called'],'adoption':runresult['adoption']}
out=E/'evaluation-only/reviews/E1-06-sonnet-r2';out.mkdir()
for name,data in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',audit),('root-cause-observations.json',rootcause),('read-not-delivered.json',snapshots)]:
 with (out/name).open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'cost':costs,'attempts':[{'attempt':a['attempt'],'cost':a['cost'],'readblocks':a['body_read_blocks'],'readchars':a['body_read_characters'],'packetbytes':a['packet_file_bytes']} for a in attempts],'score':score['required_coverage'],'r1':network['cost']},ensure_ascii=False,indent=2))
