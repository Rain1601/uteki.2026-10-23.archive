"""Resume a completed prefix only; no API call or failed sample is replayed."""
import json,subprocess,os,sys,sqlite3,importlib.util
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from stop_policy_v3 import terminal_stop_reason, transport_failure
R=Path.cwd();E=R/'experiments/agent_design/2026-10-10-e6-repeatability-v1';O=R/'output/e6-repeatability-20261010-r1'
sp=importlib.util.spec_from_file_location('v',E/'evaluation-only/verify_freeze_v3.py');v=importlib.util.module_from_spec(sp);sp.loader.exec_module(v)
m=json.loads((E/'execution-matrix.v1.json').read_bytes());p=O/'execution-progress.v3.json'
def now():return datetime.now(timezone.utc).isoformat()
def save(d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def read(path):return json.loads(path.read_bytes())
def ledger(cfg):
    c=sqlite3.connect(cfg['planner']['budget_ledger']);rows=c.execute('SELECT reserved,actual,state FROM reservations').fetchall();limit=c.execute('SELECT usd FROM config').fetchone()[0];cap=c.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0];c.close()
    return {'unsettled':sum(s!='settled' for _,_,s in rows),'requests':len(rows),'request_cap':cap,'committed_usd':sum((Decimal(a if s=='settled' else r) for r,a,s in rows),Decimal(0)),'usd_limit':Decimal(limit)}
def errors(run):
    output=[]
    def walk(x):
        if isinstance(x,dict):
            if any(k in x for k in ['error_type','http_status','transport_error_type','stream_error_type','provider_error_type']):output.append(x)
            for y in x.values():walk(y)
        elif isinstance(x,list):
            for y in x:walk(y)
    for pattern in ['result.json','*-end.json']:
        for path in run.rglob(pattern):walk(read(path))
    # Each role's final model attempt supersedes earlier recovered transport errors.
    roles={}
    for pattern in ['decision-*-attempt-*.json','review-*-attempt-*.json']:
        for path in run.rglob(pattern):
            rec=read(path);walk(rec)
            role=(rec.get('role') or ('question_reviewer' if path.parent.name=='question-model' else 'source_reviewer'))
            key=(rec.get('ended_at',''),str(path))
            if role not in roles or key>roles[role][0]:roles[role]=(key,rec)
    for _,rec in roles.values():
        if rec.get('status') not in {'decision_returned','json_returned'} and not rec.get('retry_scheduled') and transport_failure(rec):
            output.append({'terminal_transport_failure':True,'error_type':rec.get('error_type')})
    return output
def stop(d,reason):
    d.update(status='stopped',stop_reason=reason,ended_at=now(),unexecuted=[{**x,'status':'not_executed','reason':reason} for x in m['runs'][len(d['runs']):]]);save(d);print('STOP',reason,flush=True);sys.exit(2)
assert not p.exists()
v.verify()
prior=read(O/'execution-progress.v1.json');assert len(prior['runs'])==1 and prior['runs'][0]['slot_id']=='R1-S1'
first=prior['runs'][0];assert (R/first['run']/'manifest.json').exists();result=read(R/first['run']/'result.json')
manifest=read(R/first['run']/'manifest.json')
import hashlib
for relative,expected in manifest['files'].items():
    assert hashlib.sha256((R/first['run']/relative).read_bytes()).hexdigest()==expected,relative
first.update(status='completed' if result['status']=='reviewed_data_ready' else 'failed',runtime_status=result['status'],ended_at=now(),orchestrator_version='v1',closure='existing sealed first sample; no replay')
d={'started_at':prior['started_at'],'continued_at':now(),'planned_runs':9,'runs':[first],'status':'running','orchestrator_change':'v1 external scheduler suspended during R1-S1; sample preserved. v3 closes missing infrastructure stop classification; runtime/config/standard unchanged.'};save(d)
reason=terminal_stop_reason(result,errors(R/first['run']),ledger(read(R/first['config'])))
if reason:stop(d,reason)
for item in m['runs'][1:]:
    v.verify();cfg=read(R/item['config']);assert not (R/item['run']).exists();assert not Path(cfg['workspace']).exists()
    reason=terminal_stop_reason({'status':'reviewed_data_ready'},[],ledger(cfg))
    if reason:stop(d,reason)
    entry={**item,'started_at':now(),'status':'running','orchestrator_version':'v3'};d['runs'].append(entry);save(d);print('START',item['slot_id'],flush=True)
    with (R/item['log']).open('w') as log:
        done=subprocess.run([str(R/'.venv/bin/python'),'-u','scripts/run_data_retrieval.py','--config',str(R/item['config']),'--output',str(R/item['run'])],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':'src:.'})
    entry.update(ended_at=now(),exit_code=done.returncode,status='completed' if done.returncode==0 else 'failed');save(d);print('END',item['slot_id'],done.returncode,flush=True)
    v.verify()
    if not (R/item['run']/'manifest.json').exists():stop(d,'unsealed_or_infrastructure_failure')
    result=read(R/item['run']/'result.json');entry['runtime_status']=result['status'];save(d)
    reason=terminal_stop_reason(result,errors(R/item['run']),ledger(cfg))
    if reason:stop(d,reason)
d.update(status='completed',ended_at=now());save(d);print('ALL_NINE_COMPLETED',flush=True)
