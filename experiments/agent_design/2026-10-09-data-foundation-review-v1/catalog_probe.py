import json
from pathlib import Path
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.domain.research_data.period_scope import explicit_periods
paths={
'microsoft_selected':'experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset',
'google_selected':'data/company_workspace/extraction_ab_v1/corpus/googl/dataset',
'amd_selected':'experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset',
'google_acquisition_comparison':'experiments/agent_design/2026-10-08-acquisition-reuse-v1/googl/dataset',
'amd_acquisition_comparison':'experiments/agent_design/2026-10-08-acquisition-reuse-v1/amd/preparation/dataset'}
out={'model_calls':0,'network_calls':0,'mode':'read_only_frozen_dataset','checks':[]}
for name,path in paths.items():
 with QueryDataPort(Path(path)) as base:
  src=base.sources;sc=dict(snapshot_id=base.snapshot_id,company_ids=sorted({s['company_id'] for s in src}),source_snapshot_ids=[s['source_snapshot_id'] for s in src],source_policy_id='local-frozen-v1',knowledge_cutoff='2026-10-09',include_candidates=True);p=base.scoped(sc)
  row={'case':name,'dataset':path,'schema_version':base.manifest['schema_version'],'scope':sc,
   'source_metadata':[{k:s.get(k) for k in ('source_snapshot_id','company_id','form','period_end','available_at','fiscal_periods','capabilities')} for s in src],
   'record_count':p._db.execute('select count(*) from observations').fetchone()[0],
   'record_periods':p._db.execute('select distinct period_kind,period_start,period_end from observations order by 3').fetchall(),
   'catalog':{},'period_grounding':{},'scope_checks':{}}
  for k in ['sources','entities','metrics','fiscal_periods','coverage']:
   z=p.discover_catalog({'kind':k,'max_bytes':4000,'limit':8});row['catalog'][k]={key:z[key] for key in ['status','total_count','returned_count','bytes_returned','gaps']}
   if k=='metrics':row['metric_descriptions']=[a['definition'] for a in z['items']]
   if k=='entities':row['entity_examples']=z['items'][:2]
  schema=p.get_schema();row['schema_probe_item_kinds']=[a['kind'] for a in p.probe_schema({})['items']]
  for q in ['FY2023 revenue','FY2024 revenue','FY2025 revenue','2025年度收入','for 2025 revenue']:
   row['period_grounding'][q]=[v.model_dump(mode='json') for v in explicit_periods(q,fiscal_periods=schema['fiscal_periods'],require_fiscal_mapping=True)]
  old=p.scoped({**sc,'knowledge_cutoff':'2000-01-01'});row['scope_checks']['early_cutoff']={'source_count':old.discover_catalog({'kind':'sources'})['total_count'],'outline_status':old.outline_source({'source_snapshot_id':src[0]['source_snapshot_id']})['status']}
  for tag,mutation in [('wrong_company',dict(company_ids=['wrong-company'])),('wrong_source',dict(source_snapshot_ids=['wrong-source']))]:
   try:base.scoped({**sc,**mutation});row['scope_checks'][tag]='NOT REJECTED'
   except ValueError as e:row['scope_checks'][tag]=str(e)
  try:p.scoped({**sc,'knowledge_cutoff':'2027-01-01'});row['scope_checks']['widen_cutoff']='NOT REJECTED'
  except ValueError as e:row['scope_checks']['widen_cutoff']=str(e)
  if len(src)>1:
   narrow=p.scoped({**sc,'source_snapshot_ids':[src[0]['source_snapshot_id']]});row['scope_checks']['narrow_source_catalog']=[x['item_id'] for x in narrow.discover_catalog({'kind':'sources'})['items']]
   try:narrow.outline_source({'source_snapshot_id':src[1]['source_snapshot_id']});row['scope_checks']['excluded_source_body']='NOT REJECTED'
   except ValueError as e:row['scope_checks']['excluded_source_body']=str(e)
  row['full_schema_bytes']=len(json.dumps(schema).encode());out['checks'].append(row)
path=Path('experiments/agent_design/2026-10-09-data-foundation-review-v1/catalog-probes.json');path.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps([{k:r[k] for k in ['case','record_count','record_periods','period_grounding']} for r in out['checks']],ensure_ascii=False,default=str))
