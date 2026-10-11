import json,hashlib,importlib.util
from pathlib import Path
R=Path.cwd();E=R/'experiments/agent_design/2026-10-10-e6-repeatability-v1';O=R/'output/e6-repeatability-20261010-r1'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('freeze',E/'evaluation-only/verify_freeze_v3.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);f=v.verify();frozen=read(E/'evaluation-only/freeze.v3.json');matrix=read(E/'execution-matrix.v1.json')['runs'];metrics={m['slot_id']:m for m in read(O/'all-metrics.v1.json')};std=read(E/'evaluation-only/standard.v1.json');checks=[]
assert len(metrics)==9
for item in matrix:
 run=R/item['run'];a=read(E/f"evaluation-only/{item['slot_id']}-assessment.v1.json");m=metrics[item['slot_id']]
 manifest=read(run/'manifest.json')['files']
 for name,expected in manifest.items():assert sha(run/name)==expected,name
 for name,expected in read(run/'implementation.json').items():
  rel=str(Path(name).relative_to(R));assert frozen['implementation_files'][rel]==expected,rel
 result=read(run/'result.json');ref=result['final_review_ref'];packet=read(Path(ref['path'])/'input.json');records=[x['value'] for x in packet['facts'] if x['kind']=='record'];assert len(records)==4
 for requirement in std['mandatory']:
  matches=[x for x in records if x['entity_id']==requirement['company_id'] and x['period']['start']==requirement['period']['start'] and x['period']['end']==requirement['period']['end']]
  assert len(matches)==1 and matches[0]['source_snapshot_id']==requirement['source_snapshot_id'] and matches[0]['value_decimal']==requirement['value_usd'] and matches[0]['unit']=='USD' and matches[0]['accounting_basis']=='reported_consolidated' and not matches[0]['dimensions']
 assert a['mandatory_coverage']['correct']==4
 assert (a['overall_verdict']=='pass')==(m['strict_load_gate']['status']=='passed')
 cfg=read(R/item['config']);old=read(R/f"output/e6-material-scale-20261010-r1/{item['tier_id']}/runtime-config.v1.json");cfg['workspace']=old['workspace']
 for role in ['planner','worker','reviewer','question_reviewer']:cfg[role]['max_requests_total']=500
 assert cfg==old
 checks.append({'slot_id':item['slot_id'],'sealed_run_verified_files':len(manifest),'run_manifest_sha256':sha(run/'manifest.json'),'assessment_sha256':sha(E/f"evaluation-only/{item['slot_id']}-assessment.v1.json"),'mandatory_record_identity_value_period_unit_checks':4,'overall_verdict':a['overall_verdict'],'strict_load_status':m['strict_load_gate']['status'],'execution_origin':result['attempts'][0]['execution'],'analysis_called':result['analysis_called'],'runtime_equal_to_B1_except_workspace_and_guard':True})
c=read(E/'evaluation-only/comparison.v1.json');assert c['completed_runs']==9 and c['assessed_runs']==9 and c['quality_passes']==8 and c['no_recovery_first_passes']==3
out={'schema_version':'e6-repeatability-root-final-verification-v1','freeze':f,'checks':checks,'completed':9,'raw_mandatory_four_of_four':9,'final_delivery_and_load_pass':8,'no_recovery_first_pass':3,'fixed_order_preserved':True,'historical_B1_samples_excluded':True,'content_standards_unchanged':True,'question_standard_sha256':sha(E/'evaluation-only/standard.v1.json'),'no_model_api_calls_for_verification':True,'cost_reconciliation':read(E/'evaluation-only/cost-reconciliation.v1.json'),'limits':'same known question, three repetitions per tier; no statistical confidence or full parsing coverage claim'}
(E/'evaluation-only/final-verification.v1.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':'verified','runs':len(checks),'content4of4':9,'deliverypasses':8,'firstpasses':3}))
