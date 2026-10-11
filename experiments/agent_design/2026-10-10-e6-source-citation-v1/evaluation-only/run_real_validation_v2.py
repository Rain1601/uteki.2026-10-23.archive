"""Fixed failed-draft repair replays, then one fresh autonomous run; no gold input."""
import asyncio,hashlib,json,sqlite3
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uteki.agents.data_query import answer_handoff as h, retrieval_cycle as cycle
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from uteki.agents.data_query.artifacts import write_new

ROOT=Path.cwd();E=ROOT/'experiments/agent_design/2026-10-10-e6-source-citation-v1';O=ROOT/'output/e6-source-citation-20261010-r1'
OLD=ROOT/'output/e6-repeatability-20261010-r1/R3/S3'
read=lambda p:json.loads(p.read_bytes())
CFG=read(O/'runtime-config.v1.json')
def verify():
 f=read(E/'evaluation-only/execution-freeze.v2.json')
 for path,expected in f['files'].items():assert digest((ROOT/path).read_bytes())==expected,path
 for path,expected in f['sealed_refs'].items():cycle._verify_manifest(ROOT/path,expected)
def ledger():
 db=sqlite3.connect(Path(CFG['planner']['budget_ledger']).as_uri()+'?mode=ro',uri=True)
 rows=db.execute('SELECT id,reserved,actual,state FROM reservations').fetchall();db.close()
 return {'ids':[x[0] for x in rows],'requests':len(rows),'estimated_usd':str(sum((Decimal(x[2]) for x in rows if x[3]=='settled'),Decimal(0))),
         'unsettled':sum(x[3]!='settled' for x in rows),'unsettled_ids':[x[0] for x in rows if x[3]!='settled'],'held_usd':str(sum((Decimal(x[1]) for x in rows if x[3]!='settled'),Decimal(0)))}
def check_budget():
 s=ledger();base=read(O/'ledger-before.v1.json');assert sorted(s['unsettled_ids'])==sorted(read(E/'evaluation-only/network-recovery.v1.json')['retained_unknown_ids']),'new unknown/inflight stop'
 assert Decimal(s['estimated_usd'])+Decimal(s['held_usd'])-Decimal(base['estimated_usd'])<Decimal('3'),'task warning boundary reached'
 return s
class RealRepairRole:
 """The one real source call receives the canonical mechanical repair envelope."""
 plan_origin='model'
 def __init__(self,inner,packet,bad,seed):self.inner=inner;self.packet=packet;self.bad=bad;self.seed=seed;self.calls=0
 async def review(self,packet):
  assert packet==self.packet;assert self.calls==0;self.calls+=1
  repair=h.source_review_repair_input(packet,self.bad,max_bytes=packet['max_packet_bytes'])
  write_new(self.inner.output/'replay-origin.json',self.seed)
  write_new(self.inner.output/'replay-repair-input.json',repair)
  return await self.inner.review(repair)
 async def aclose(self):return await self.inner.aclose()
 def snapshot_usage(self):return self.inner.snapshot_usage()
async def main():
 verify();assert not (O/'progress.v2.json').exists()
 progress={'schema_version':'e6-source-citation-real-validation-v1','steps':[],'status':'running'}
 def save(): (O/'progress.v2.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n')
 save()
 for ordinal in (1,2):
  verify();check_budget();old=OLD/f'run-r1/attempt-01/review-{ordinal:02d}';manifest=cycle._verify_manifest(old)
  packet=read(old/'input.json');bad=read(old/'source-response.json')
  seed={'operation':'real_source_citation_repair_replay','old_review_ref':cycle._reference(old),
        'old_packet_sha256':digest(packet),'old_response_sha256':digest(bad),'old_response_is_rejected_not_gold':True,
        'not_a_fresh_query':True,'logical_source_review_call_bound':1,'network_retry_bound':1,'model_output_not_substituted':True}
  name='repair-01-network-recovery' if ordinal==1 else 'repair-02'
  path=O/name
  factory=cycle.reviewer_factory(CFG,packet)
  result=await h.review_data_answer(packet,path,
    reviewer_factory=lambda out:RealRepairRole(factory(out),packet,bad,seed),
    question_reviewer_factory=cycle.question_reviewer_factory(CFG),allow_source_protocol_repair=False)
  entry={'id':name,'operation':seed['operation'],'result':result,'strict_load':'not_passed'}
  if result['status']=='reviewed' and result['analysis_eligible']:
   loaded=h.load_reviewed_data(path,expected_scope=CFG['request']['scope'],expected_review_manifest_sha256=result['review_ref']['manifest_sha256'])
   entry.update(strict_load='passed',handoff_id=loaded['handoff_id'])
  progress['steps'].append(entry);save();print('END',entry['id'],result['status'],entry['strict_load'],flush=True)
  check_budget()
 verify();check_budget()
 result=await cycle.run_retrieval_cycle(CFG,O/'fresh-S3/run-r1')
 entry={'id':'fresh-S3','operation':'fresh_autonomous_same_question','result':result,'strict_load':'not_passed'}
 ref=result.get('final_review_ref')
 if result['status']=='reviewed_data_ready':
  loaded=h.load_reviewed_data(ref['path'],expected_scope=CFG['request']['scope'],expected_review_manifest_sha256=ref['manifest_sha256'])
  entry.update(strict_load='passed',handoff_id=loaded['handoff_id'])
 progress['steps'].append(entry);progress.update(status='completed',ledger_after=check_budget());save();verify()
 print('ALL_FIXED_STEPS_COMPLETED',flush=True)
if __name__=='__main__':asyncio.run(main())
