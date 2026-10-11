import json,subprocess,os,sys,sqlite3,importlib.util
from pathlib import Path
from datetime import datetime,timezone
R=Path.cwd();E=R/'experiments/agent_design/2026-10-10-e6-repeatability-v1';O=R/'output/e6-repeatability-20261010-r1'
sp=importlib.util.spec_from_file_location('v',E/'evaluation-only/verify_freeze.py');v=importlib.util.module_from_spec(sp);sp.loader.exec_module(v)
m=json.loads((E/'execution-matrix.v1.json').read_bytes());p=O/'execution-progress.v1.json'
def now():return datetime.now(timezone.utc).isoformat()
def save(d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
d={'started_at':now(),'planned_runs':9,'runs':[],'status':'running'};assert not p.exists();save(d)
for item in m['runs']:
 v.verify();cfg=json.loads((R/item['config']).read_bytes());assert not (R/item['run']).exists();assert not Path(cfg['workspace']).exists()
 c=sqlite3.connect(cfg['planner']['budget_ledger']);states=c.execute('SELECT state,COUNT(*) FROM reservations GROUP BY state').fetchall();c.close()
 if any(state!='settled' for state,n in states):d['status']='stopped_unresolved_ledger';save(d);sys.exit(2)
 entry={**item,'started_at':now(),'status':'running'};d['runs'].append(entry);save(d);print('START',item['slot_id'],flush=True)
 with (R/item['log']).open('w') as log:
  done=subprocess.run([str(R/'.venv/bin/python'),'-u','scripts/run_data_retrieval.py','--config',str(R/item['config']),'--output',str(R/item['run'])],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':'src:.'})
 entry.update(ended_at=now(),exit_code=done.returncode,status='completed' if done.returncode==0 else 'failed');save(d);print('END',item['slot_id'],done.returncode,flush=True)
 v.verify()
 if not (R/item['run']/'result.json').exists():d['status']='stopped_unsealed_or_infrastructure_failure';save(d);sys.exit(2)
 # USD remains enforced by the original ledger. Outer driver never retries a run.
d.update(status='completed',ended_at=now());save(d);print('ALL_NINE_COMPLETED',flush=True)
