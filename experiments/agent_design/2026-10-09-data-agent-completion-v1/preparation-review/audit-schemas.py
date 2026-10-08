import json,hashlib
from pathlib import Path
from jsonschema import Draft202012Validator
r=Path('experiments/agent_design/2026-10-09-data-agent-completion-v1');out={}
for sym in ['msft','googl']:
 p=r/'datasets'/sym;s=json.loads((p/'sources.json').read_text())[0];ip=p/s['index_folder'];checks=[]
 for path in sorted((p/'schemas').glob('*.json'))+sorted((ip/'schemas').glob('*.json')):
  sc=json.loads(path.read_text());Draft202012Validator.check_schema(sc)
  objects=[]
  if path.name=='record.schema.json':objects=json.loads((p/'records.json').read_text())['rows']
  elif path.name=='blocks.schema.json':objects=[json.loads(l) for l in (ip/'blocks.jsonl').read_text().splitlines()]
  elif path.parent==ip/'schemas':objects=[json.loads((ip/path.name.replace('.schema','')).read_text())]
  failures=[];v=Draft202012Validator(sc)
  for i,x in enumerate(objects):
   failures.extend({'object':i,'path':str(e.json_path),'message':e.message[:160]} for e in v.iter_errors(x))
  checks.append({'schema':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'schema_valid':True,'objects_checked':len(objects),'instance_failures':failures[:20],'instance_failure_count':len(failures)})
 out[sym]=checks
(r/'preparation-review'/'schema-validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print({sym:{'schemas':len(v),'failures':sum(x['instance_failure_count'] for x in v)} for sym,v in out.items()})
