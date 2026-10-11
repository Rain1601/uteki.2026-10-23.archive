"""Aggregate the predeclared nine slots, including failures, without model calls."""
import json,statistics,sqlite3
from decimal import Decimal
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[4];E=Path(__file__).resolve().parents[1];O=ROOT/'output/e6-repeatability-20261010-r1'
def read(p):return json.loads(p.read_bytes())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def summarize():
    rows=read(O/'all-metrics.v1.json');planned=read(E/'execution-matrix.v1.json')['runs'];by_id={r['slot_id']:r for r in rows};items=[]
    progress_path=O/'execution-progress.v3.json';progress=read(progress_path) if progress_path.exists() else {}
    incomplete_slots={progress['runs'][-1]['slot_id']} if progress.get('status')=='stopped' and progress.get('runs') else set()
    for item in planned:
        row=by_id.get(item['slot_id']);assessment_path=E/'evaluation-only'/f"{item['slot_id']}-assessment.v1.json";assessment=read(assessment_path) if assessment_path.exists() else None
        if not row:items.append({'slot_id':item['slot_id'],'tier_id':item['tier_id'],'status':'not_completed'});continue
        passed=(item['slot_id'] not in incomplete_slots and assessment is not None and assessment.get('overall_verdict')=='pass' and row['strict_load_gate']['status']=='passed')
        correct=(assessment or {}).get('mandatory_coverage',{}).get('correct')
        items.append({'slot_id':item['slot_id'],'tier_id':item['tier_id'],'runtime_status':row['runtime_status'],'incomplete_for_sampling':item['slot_id'] in incomplete_slots,'content_assessment':(assessment or {}).get('overall_verdict','pending'),'mandatory_correct':correct,'mandatory_required':4,'final_quality_and_load_pass':passed if assessment and item['slot_id'] not in incomplete_slots else None,'no_recovery_first_pass':passed and row['mechanical_no_recovery'] if assessment and item['slot_id'] not in incomplete_slots else None,'calls':row['calls'],'estimated_usd':row['known_estimated_usd'],'unknown_cost_requests':row['unknown_cost_requests'],'cost_per_correct_mandatory_fact_usd':str(Decimal(row['known_estimated_usd'])/correct) if correct else None,'steps':sum(a['steps'] or 0 for a in row['attempts']),'recovery_counts':{k:len(v) if isinstance(v,list) else v for k,v in row['recovery_events'].items()},'review_ref':row['final_review_ref'],'run':item['run'],'assessment':str(assessment_path.relative_to(ROOT)) if assessment else None})
    tiers=[]
    for tier in ['S1','S2','S3']:
        samples=[r for r in rows if r['tier_id']==tier];judgments=[i for i in items if i['tier_id']==tier and 'content_assessment' in i];costs=[float(r['known_estimated_usd']) for r in samples if r['fee_estimate_complete'] and r['slot_id'] not in incomplete_slots];n=len(costs)
        stdev=statistics.stdev(costs) if n>=2 else None;mean=statistics.mean(costs) if n else None;cv=stdev/mean if stdev is not None and mean and mean>0 else None;ratio=max(costs)/min(costs) if n and min(costs)>0 else None
        complete=len(samples)==3 and len(judgments)==3 and all(i['content_assessment']!='pending' and not i['incomplete_for_sampling'] for i in judgments)
        quality='observed_three_passes' if complete and all(i['final_quality_and_load_pass'] for i in judgments) else ('observed_quality_failure' if any(i['final_quality_and_load_pass'] is False for i in judgments) else 'incomplete')
        fee_complete=len(samples)==3 and n==3
        fee='concentrated_under_predeclared_observation_threshold' if fee_complete and cv is not None and ratio is not None and cv<=.20 and ratio<=1.5 else ('outside_predeclared_observation_threshold' if fee_complete else 'incomplete')
        tiers.append({'tier_id':tier,'planned':3,'completed':len(samples),'quality_passes':sum(i['final_quality_and_load_pass'] is True for i in judgments),'no_recovery_first_passes':sum(i['no_recovery_first_pass'] is True for i in judgments),'quality_flag':quality,'fee_valid_n':n,'fee_estimate_mean_usd':mean,'fee_estimate_median_usd':statistics.median(costs) if n else None,'fee_estimate_min_usd':min(costs) if n else None,'fee_estimate_max_usd':max(costs) if n else None,'sample_stdev_ddof1':stdev,'sample_cv':cv,'max_min_ratio':ratio,'fee_flag':fee,'cached_tokens_reported':[r['reported_tokens'].get('cached_input_tokens') for r in samples]})
    return {'schema_version':'e6-repeatability-comparison-v1','planned_runs':9,'completed_runs':len(rows),'assessed_runs':sum(i.get('content_assessment') not in {None,'pending'} for i in items),'quality_passes':sum(i.get('final_quality_and_load_pass') is True for i in items),'no_recovery_first_passes':sum(i.get('no_recovery_first_pass') is True for i in items),'unknown_cost_requests':sum(r['unknown_cost_requests'] for r in rows),'unknown_or_inflight_reserved_usd':str(sum((Decimal(r['unknown_or_inflight_reserved_usd']) for r in rows),Decimal(0))),'execution_status':progress.get('status'),'stop_reason':progress.get('stop_reason'),'incomplete_slots':sorted(incomplete_slots),'historical_B1_excluded':True,'orchestration_change':'R1-S1 driver v1; remaining slots driver v3; runtime/content/config unchanged, failed v2 draft not executed','total_calls':sum(r['calls'] for r in rows),'total_known_estimated_usd':str(sum((Decimal(r['known_estimated_usd']) for r in rows),Decimal(0))),'actual_billed_usd':None,'tiers':tiers,'runs':items,'limitations':['finite same-question samples, not statistical stability','uncached peak list-price estimates, not supplier bills','history and third-company distractors covary with source volume','prepared_with_gaps, not full financial or new-format coverage']}
if __name__=='__main__':
    d=summarize();write(E/'evaluation-only/comparison.v1.json',d);print(json.dumps({k:d[k] for k in ['completed_runs','assessed_runs','quality_passes','no_recovery_first_passes','total_calls','total_known_estimated_usd','tiers']},ensure_ascii=False))
