"""Read-only post-execution metrics; does not call models or supply feedback."""
import importlib.util,json,sys,hashlib,sqlite3,statistics
from pathlib import Path
from decimal import Decimal
from collections import Counter
ROOT=Path(__file__).resolve().parents[4]; E=Path(__file__).resolve().parents[1]; O=ROOT/'output/e6-repeatability-20261010-r1'
spec=importlib.util.spec_from_file_location('historical_metrics',ROOT/'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/collect_metrics.py')
historical=importlib.util.module_from_spec(spec);spec.loader.exec_module(historical)
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def collect(item):
    run=ROOT/item['run'];result=read(run/'result.json');historical.OUTPUT=run.parents[1]
    out=historical.collect(item['tier_id']);out.update(slot_id=item['slot_id'],round=item['round'],run=item['run'],run_manifest_sha256=sha(run/'manifest.json'))
    receipts=[]
    for p in run.rglob('turn-*/receipt.json'):
        r=read(p)
        if r.get('status') in {'rejected','failed','error'}:receipts.append({'path':str(p.relative_to(ROOT)),'status':r.get('status'),'step':r.get('step'),'action':r.get('action'),'requirement_ids':r.get('requirement_ids'),'error_code':r.get('error_code'),'error':r.get('error')})
    decisions=[(p,read(p)) for p in run.rglob('decision-*-attempt-*.json')]
    repairs=[{'path':str(p.relative_to(ROOT)),'attempt':r.get('attempt'),'status':r.get('status'),'retry':r.get('retry')} for p,r in decisions if r.get('attempt',1)>1 or r.get('retry') or r.get('status')!='decision_returned']
    callends=[read(p) for p in run.rglob('*-end.json')]
    failedcalls=[{'call_id':r['call_id'],'status':r['status'],'stage':r['stage'],'estimated_usd':r.get('estimated_usd'),'error_type':r.get('error_type'),'http_status':r.get('http_status'),'transport_error_type':r.get('transport_error_type'),'dispatch_status':r.get('dispatch_status')} for r in callends if r.get('status')!='succeeded']
    review_attempts=[(p,read(p)) for p in run.rglob('review-*-attempt-*.json')]
    review_recovery=[{'path':str(p.relative_to(ROOT)),'attempt':r.get('attempt'),'status':r.get('status'),'retry':r.get('retry'),'error_type':r.get('error_type'),'retry_scheduled':r.get('retry_scheduled',False)} for p,r in review_attempts if r.get('attempt',1)>1 or r.get('retry') or r.get('status')!='json_returned']
    db=sqlite3.connect(ROOT/'experiments/agent_design/2026-10-09-e2-msft-10q-v1/costs.sqlite')
    ledger_rows={row[0]:row[1:] for row in db.execute('SELECT id,reserved,actual,state FROM reservations')};db.close()
    held=Decimal(0)
    for rec in callends:
        reservation=ledger_rows.get(rec.get('budget_reservation_id'))
        if reservation and reservation[2]!='settled':held+=Decimal(reservation[0])
    out['unknown_or_inflight_reserved_usd']=str(held)
    out['fee_estimate_complete']=out['unknown_cost_requests']==0 and held==0
    for stage,summary in out['by_stage'].items():
        summary['known_estimated_usd']=summary.pop('estimated_usd')
        rs=[r for r in callends if r['stage']==stage]
        summary['unknown_cost_requests']=sum(r.get('estimated_usd') is None for r in rs)
        summary['unknown_or_inflight_reserved_usd']=str(sum((Decimal(ledger_rows[r['budget_reservation_id']][0]) for r in rs if r.get('budget_reservation_id') in ledger_rows and ledger_rows[r['budget_reservation_id']][2]!='settled'),Decimal(0)))
    protocol=[str(p.relative_to(ROOT)) for p in run.rglob('question-repair-input.json')]
    review_program_failures=[]
    for attempt in result.get('attempts',[]):
        for index,review_entry in enumerate(attempt.get('reviews',[]),1):
            if review_entry.get('status')=='failed':
                ref=review_entry.get('review_ref');detail=read(Path(ref['path'])/'result.json') if ref else review_entry
                review_program_failures.append({'retrieval_attempt':attempt['attempt'],'review_ordinal':index,'review_ref':ref,'failures':detail.get('failures',[]),'error_type':detail.get('error_type')})
    out['recovery_events']={'rejected_or_error_tool_decisions':receipts,'decision_repair_events':repairs,'review_model_repair_events':review_recovery,'review_program_validation_failures':review_program_failures,'question_protocol_repair_inputs':protocol,'failed_network_or_provider_calls':failedcalls,'retrieval_attempt_count':len(result.get('attempts',[])), 'review_execution_counts':[len(a.get('reviews',[])) for a in result.get('attempts',[])]}
    out['mechanical_no_recovery']=len(result.get('attempts',[]))==1 and not(receipts or repairs or review_recovery or review_program_failures or protocol or failedcalls) and all(len(a.get('reviews',[]))==1 for a in result.get('attempts',[]))
    ref=result.get('final_review_ref');load={'status':'not_available'}
    if ref:
        from uteki.agents.data_query.answer_handoff import load_reviewed_data
        cfg=read(ROOT/item['config'])
        try:
            handoff=load_reviewed_data(ref['path'],expected_scope=cfg['request']['scope'],expected_review_manifest_sha256=ref['manifest_sha256'])
            load={'status':'passed','handoff_id':handoff['handoff_id'],'numeric_records':sum(f.get('kind')=='record' for f in handoff['facts']),'analysis_called':False}
        except Exception as ex:load={'status':'failed','error_type':type(ex).__name__,'error':str(ex)}
    out['strict_load_gate']=load
    return out
if __name__=='__main__':
    rows=[]
    for item in read(E/'execution-matrix.v1.json')['runs']:
        if (ROOT/item['run']/'result.json').exists():rows.append(collect(item))
    (O/'all-metrics.v1.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{'slot':r['slot_id'],'status':r['runtime_status'],'calls':r['calls'],'usd':r['known_estimated_usd'],'mechanical_no_recovery':r['mechanical_no_recovery'],'load':r['strict_load_gate']} for r in rows],ensure_ascii=False))
