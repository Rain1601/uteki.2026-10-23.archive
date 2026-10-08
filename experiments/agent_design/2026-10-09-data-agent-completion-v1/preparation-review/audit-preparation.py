import json,hashlib,re
from pathlib import Path
from collections import Counter,defaultdict
from decimal import Decimal
from dataclasses import asdict
from lxml import html
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _visible_text,_table_structure
from uteki.infrastructure.research_data.financial_records import dom_path_query
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.domain.research_data.query_contract import ResearchRecord
r=Path('experiments/agent_design/2026-10-09-data-agent-completion-v1');sha=lambda x:hashlib.sha256(x).hexdigest()
result={'schema_version':'offline-preparation-review-v1','scope':'Two frozen annual HTML datasets, whole-block structural audit and all materialized standard financial records; not semantic full-report completeness.','model_calls':0,'network_calls':0,'dataset_mutations':False,'datasets':{}}
concepts={'RevenueFromContractWithCustomerExcludingAssessedTax':'revenue','RevenueFromContractWithCustomerIncludingAssessedTax':'revenue_including_assessed_tax','Revenues':'revenue','SalesRevenueNet':'revenue','OperatingIncomeLoss':'operating_income','NetIncomeLoss':'net_income','NetCashProvidedByUsedInOperatingActivities':'operating_cash_flow','PaymentsToAcquirePropertyPlantAndEquipment':'capex_cash_payments'}
for sym in ['msft','googl']:
 p=r/'datasets'/sym;before={str(x.relative_to(p)):sha(x.read_bytes()) for x in p.rglob('*') if x.is_file()}
 s=json.loads((p/'sources.json').read_text())[0];m=json.loads((p/'manifest.json').read_text());raw=(p/s['raw_file']).read_bytes();tree=html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8',no_network=True));byid={el.get('id'):el for el in tree.iter() if isinstance(el.tag,str) and el.get('id')}
 bpath=p/s['index_folder']/'blocks.jsonl';blocks=[json.loads(l) for l in bpath.read_text().splitlines()];lookup={b['block_id']:b for b in blocks};index=json.loads((p/s['index_folder']/'index.json').read_text())
 failures=[];tablefail=[];overlap=[];within=[];dups=defaultdict(list);schemaval=[]
 for b in blocks:
  if sha(b['text'].encode())!=b['text_hash']:failures.append({'block_id':b['block_id'],'reason':'text_hash'})
  matches=tree.xpath(dom_path_query(b['dom_path']))
  if len(matches)!=1:failures.append({'block_id':b['block_id'],'reason':'dom_not_unique','count':len(matches)});continue
  original=normalize_text(matches[0].get('alt','')) if b['type']=='image' else normalize_text(_visible_text(matches[0]))
  if original!=b['text']:failures.append({'block_id':b['block_id'],'reason':'original_text_differs','original_preview':original[:100],'parsed_preview':b['text'][:100]})
  if b['table']:
   cells=[asdict(c) for c in _table_structure(matches[0],visible_only=True,nearest_table=True).cells]
   if cells!=b['table']['cells']:tablefail.append({'block_id':b['block_id'],'reason':'original_table_cells_differ','original_count':len(cells),'parsed_count':len(b['table']['cells'])})
  dups[b['text']].append(b)
  # Repeated substantial sentences are a review heuristic only; common cells/headers are not prose duplication.
  if not b['table']:
   parts=re.split(r'(?<=[.;])\s+',b['text']);c=Counter(x for x in parts if len(x)>80)
   if any(v>1 for v in c.values()):within.append({'block_id':b['block_id'],'repeated_sentences':[{ 'text':k,'count':v} for k,v in c.items() if v>1]})
 # Ancestor blocks can double-deliver contents. Only flag substantial whole-child text in parent, not shared numeric values.
 for a in blocks:
  if len(a['text'])<100:continue
  for b in blocks:
   if a['block_id']!=b['block_id'] and a['dom_path'].startswith(b['dom_path']+'/') and a['text'] in b['text']:
    overlap.append({'inner':a['block_id'],'outer':b['block_id'],'chars':len(a['text'])})
 valid_ranges=[];invalid_ranges=[]
 for n in index['nodes']:
  a=lookup.get(n.get('start_block_id'));z=lookup.get(n.get('end_block_id'))
  if not a or not z or a['ordinal']>z['ordinal']:invalid_ranges.append(n)
  else:valid_ranges.append({'node_id':n['node_id'],'kind':n['kind'],'block_count':z['ordinal']-a['ordinal']+1})
 records=json.loads((p/'records.json').read_text())['rows'];evidence=json.loads((p/'evidence.json').read_text());record_fail=[];signatures=defaultdict(list)
 for rec in records:
  errs=[]
  try:ResearchRecord.model_validate(rec)
  except Exception as e:errs.append('schema:'+type(e).__name__)
  for eid in rec['evidence_ids']:
   ev=evidence[eid];els=tree.xpath(dom_path_query(ev['fact_dom_path']))
   if len(els)!=1:errs.append('fact_dom_not_unique');continue
   f=els[0];ctx=byid[f.get('contextref')];unit=byid[f.get('unitref')]
   def texts(node,name):return [normalize_text(x.text_content()) for x in node.iter() if isinstance(x.tag,str) and x.tag.split(':')[-1].lower()==name]
   rawtext=normalize_text(f.text_content());amount=Decimal(rawtext.replace(',','').replace('$','').replace('(','').replace(')',''))*(Decimal(10)**int(f.get('scale','0')))
   if f.get('sign')=='-' or rawtext.startswith('('):amount=-amount
   if amount!=Decimal(rec['value_decimal']):errs.append('numeric_scale_or_sign')
   if 'iso4217:USD' not in texts(unit,'measure') or rec['unit']!='USD':errs.append('unit')
   if texts(ctx,'startdate')!=[rec['period']['start']] or texts(ctx,'enddate')!=[rec['period']['end']]:errs.append('period')
   if texts(ctx,'identifier')!=[m['company']['cik']]:errs.append('issuer')
   dims={x.get('dimension'):normalize_text(x.text_content()) for x in ctx.iter() if isinstance(x.tag,str) and x.tag.split(':')[-1].lower()=='explicitmember'}
   if dims!=(rec.get('dimensions') or {}):errs.append('dimensions')
   concept=f.get('name').split(':')[-1]
   if concepts.get(concept)!=rec['metric_id']:errs.append('metric_concept:'+concept)
   if rawtext!=ev['quote'] or ev['source_sha256']!=s['source_sha256'] or ev['source_snapshot_id']!=s['source_snapshot_id']:errs.append('evidence_identity_or_quote')
   if ev['block_id'] not in lookup or ev['quote'] not in lookup[ev['block_id']]['text']:errs.append('evidence_block')
  if errs:record_fail.append({'record_id':rec['record_id'],'errors':errs})
  signature=json.dumps({k:rec.get(k) for k in ['entity_id','metric_id','period','unit','dimensions','accounting_basis']},sort_keys=True)
  signatures[signature].append(rec)
 conflicts=[{'semantic_key':json.loads(k),'record_ids':[x['record_id'] for x in v],'values':sorted({x['value_decimal'] for x in v})} for k,v in signatures.items() if len({x['value_decimal'] for x in v})>1]
 owner=QueryDataPort(p);scope={'snapshot_id':owner.snapshot_id,'company_ids':[s['company_id']],'source_snapshot_ids':[s['source_snapshot_id']],'source_policy_id':m['source_policy_id'],'knowledge_cutoff':s['available_at'],'include_candidates':True};port=owner.scoped(scope);schema=port.get_schema()
 catalog={}
 for kind in ['sources','entities','metrics','fiscal_periods']:
  items=[];request={'kind':kind,'limit':20,'max_bytes':20000};steps=0
  while True:
   page=port.discover_catalog(request);items+=page['items'];steps+=1
   if page.get('gaps') or not page.get('next_cursor'):break
   request={**request,'cursor':page['next_cursor']}
   assert steps<100
  catalog[kind]={'status':page['status'],'count':len(items),'pages':steps,'gaps':page.get('gaps'), 'items':items if kind=='fiscal_periods' else None}
 probe_request={'limit':20,'max_bytes':20000};probe_items=[];probe_pages=0
 while True:
  probe=port.probe_schema(probe_request);probe_items+=probe['items'];probe_pages+=1
  if probe.get('gaps') or not probe.get('next_cursor'):break
  probe_request={**probe_request,'cursor':probe['next_cursor']}
  assert probe_pages<100
 query_checks=[]
 for fy in [2025,2024]:
  period=next(x['period'] for x in schema['fiscal_periods'] if x['fiscal_year']==fy)
  q={'query_id':'offline-preparation-total-'+str(fy),'snapshot_id':owner.snapshot_id,'source_policy_id':m['source_policy_id'],'knowledge_cutoff':s['available_at'],'include_candidates':True,'records':[{'entity_id':s['company_id'],'metric_id':'revenue','period':period}]}
  qr=port.query_data(q);query_checks.append({'fiscal_year':fy,'period':period,'status':qr['status'],'records':[{'record_id':x['record_id'],'value_decimal':x['value_decimal'],'unit':x['unit'],'entity_id':x['entity_id'],'accounting_basis':x['accounting_basis']} for x in qr['records']],'gaps':qr.get('gaps')})
 owner.close()
 substantial=[{'block_ids':[b['block_id'] for b in v],'reported_pages':[b.get('reported_page') for b in v],'chars':len(t),'text_preview':t[:180]} for t,v in dups.items() if len(v)>1 and len(t)>=100]
 result['datasets'][sym]={'dataset_path':str(p),'source_snapshot_id':s['source_snapshot_id'],'source_sha256':sha(raw),'raw_hash_matches':sha(raw)==s['source_sha256'],'company_identity_matches':m['company']['company_id']==s['company_id'],'file_hashes':before,'block_count':len(blocks),'block_ids_unique':len(lookup)==len(blocks),'ordinal_contiguous':[b['ordinal'] for b in blocks]==list(range(1,len(blocks)+1)),'original_dom_text_failures':failures,'original_table_structure_failures':tablefail,'substantial_same_source_duplicate_groups':substantial,'within_block_repeated_prose':within,'substantial_dom_ancestor_overlap':overlap,'image_assets':json.loads((p/s['index_folder']/'assets.json').read_text()),'navigation_noise':dict(Counter((b.get('layout_role') or b['type']) for b in blocks if b.get('layout_role') or b['type']=='page_marker' or b['text']=='•')),'valid_index_ranges':valid_ranges,'invalid_index_ranges':invalid_ranges,'materialized_record_count':len(records),'all_record_original_verification_failures':record_fail,'conflicting_semantic_record_values':conflicts,'repeated_same_value_record_groups':sum(len(v)>1 for v in signatures.values()),'catalog':catalog,'schema_probe':{'status':probe['status'],'count':len(probe_items),'pages':probe_pages,'has_more':bool(probe['next_cursor']),'gaps':probe.get('gaps')},'company_total_revenue_query_checks':query_checks,'frozen_dataset_unchanged':before=={str(x.relative_to(p)):sha(x.read_bytes()) for x in p.rglob('*') if x.is_file()}}
 print(sym,'dom errors',len(failures),'table errors',len(tablefail),'record errors',len(record_fail),'dup groups',len(substantial),'overlap',len(overlap),flush=True)
(r/'preparation-review'/'checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
