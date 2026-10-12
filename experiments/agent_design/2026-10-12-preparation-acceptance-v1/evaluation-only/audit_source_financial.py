"""Independent original/submission/iXBRL audit; never used by runtime agent."""
import argparse,json,hashlib,re
from pathlib import Path
from decimal import Decimal
from collections import Counter,defaultdict
from lxml import html
BASE=Path('output/preparation-acceptance-20261012')
OLD=Path('output/revenue-stability-20261012/preparation-v1/dataset')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True, help='Prepared materialization version, e.g. v5 or v6; acquisition remains pinned to v2.')
args=parser.parse_args()
if not re.fullmatch(r'v[0-9]+', args.version):
    parser.error('--version must be a version directory such as v5')
VERSION=args.version
MAP={'RevenueFromContractWithCustomerExcludingAssessedTax':'revenue','RevenueFromContractWithCustomerIncludingAssessedTax':'revenue_including_assessed_tax','Revenues':'revenue','SalesRevenueNet':'revenue','OperatingIncomeLoss':'operating_income','NetIncomeLoss':'net_income','NetCashProvidedByUsedInOperatingActivities':'operating_cash_flow','PaymentsToAcquirePropertyPlantAndEquipment':'capex_cash_payments'}
def read(p):return json.loads(p.read_text())
def local(e):return str(e.tag).split(':')[-1].lower()
def norm(s):return ' '.join(s.split())
def text(e):return norm(''.join(e.itertext()))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def childtext(e,name):return [text(x) for x in e.iter() if local(x)==name]
def visible(t):
 t=html.fromstring(html.tostring(t))
 for x in list(t.iter()):
  if local(x) in ('script','style','header') or re.search(r'display\s*:\s*none',x.get('style',''),re.I):
   if x.getparent() is not None:x.drop_tree()
 return norm(t.text_content())
def facts(t):return sorted([(x.get('name'),x.get('contextref'),x.get('unitref'),x.get('scale'),x.get('sign'),x.get('format'),text(x)) for x in t.iter() if local(x) in ('nonfraction','nonnumeric')],key=str)
results={}
for company in ('msft','googl'):
 p=BASE/VERSION/company/'dataset';acq=read(BASE/'v2'/company/'acquisition.json'); src=read(p/'sources.json')[0];raw=(p/src['raw_file']).read_bytes();tree=html.fromstring(raw,parser=html.HTMLParser(encoding='utf-8'));allnodes=list(tree.iter());ids=defaultdict(list)
 for e in allnodes:
  if e.get('id'):ids[e.get('id')].append(e)
 sub=read(BASE/'workspace'/acq['discovery'][0]['path']);r=sub['filings']['recent'];scope=acq['scope'];expected=[dict(zip(r,vs)) for vs in zip(*r.values()) if dict(zip(r,vs)).get('form') in ('10-K','10-K/A') and dict(zip(r,vs)).get('reportDate')==scope['report_period_end'] and dict(zip(r,vs)).get('filingDate')<=scope['as_of']]
 docs=acq['documents'];errors=[]
 if {x['accessionNumber'] for x in expected}!={x['accession'] for x in acq['selected_filings']}:errors.append('selection_missing_or_extra')
 for x in acq['discovery']:
  b=(BASE/'workspace'/x['path']).read_bytes()
  if sha(b)!=x['content_sha256'] or len(b)!=x['bytes_received']:errors.append('transport_storage_hash_mismatch')
 if raw!=(BASE/'workspace'/docs[0]['path']).read_bytes():errors.append('materialization_original_changed')
 for name,wanted in [('EntityCentralIndexKey',str(int(acq['company']['cik']))),('DocumentType','10-K'),('DocumentPeriodEndDate',scope['report_period_end'])]:
  # Date lexical syntax is retained in evidence; independent context date check below.
  es=[e for e in allnodes if (e.get('name')or'').split(':')[-1]==name]
  if not es:errors.append('missing_dei_'+name)
  if name=='EntityCentralIndexKey' and any(str(int(text(e)))!=wanted for e in es):errors.append('dei_cik_mismatch')
  if name=='DocumentType' and any(text(e)!=wanted for e in es):errors.append('dei_form_mismatch')
 records=read(p/'records.json')['rows'];ev=read(p/'evidence.json');checked=[];record_errors=[];seenfacts=[]
 for row in records:
  e=ev[row['evidence_ids'][0]]; fs=ids[e['fact_id']]
  if len(fs)!=1:record_errors.append([row['record_id'],'nonunique_fact_id']);continue
  f=fs[0];context=ids[f.get('contextref')][0];unit=ids[f.get('unitref')][0];value=text(f).replace(',','').replace(' ',''); fmt=f.get('format','')
  value=Decimal(0) if fmt.endswith('fixed-zero') else Decimal(value)
  value*=Decimal(10)**int(f.get('scale','0'));value*= -1 if f.get('sign')=='-' else 1
  dims={x.get('dimension'):text(x) for x in context.iter() if local(x)=='explicitmember'}
  tests={'value':value==Decimal(row['value_decimal']),'concept':MAP[f.get('name').split(':')[-1]]==row['metric_id'],'currency':childtext(unit,'measure')==['iso4217:USD'] and row['unit']=='USD','start':childtext(context,'startdate')==[row['period']['start']],'end':childtext(context,'enddate')==[row['period']['end']],'company':all(str(int(v))==str(int(acq['company']['cik'])) for v in childtext(context,'identifier')),'dimensions':dims==row['dimensions'],'quote':text(f)==e['quote'],'ordinal':allnodes[row['origin']['record_index']] is f,'source_sha':e['source_sha256']==sha(raw),'fact_path':tree.getroottree().getpath(f)==e['fact_dom_path']}
  checked.append({'record_id':row['record_id'],'fact_id':e['fact_id'],'checks':tests})
  if not all(tests.values()):record_errors.append({'record_id':row['record_id'],'failed':[k for k,v in tests.items() if not v]})
  seenfacts.append(e['fact_id'])
 originalfacts=[e for e in allnodes if local(e)=='nonfraction'];normalized=Counter(x['metric_id'] for x in records); gaps=read(p/'manifest.json')['gaps'];ng=[g for g in gaps if g.get('layer')=='normalization'];gcounts=Counter(g['reason'] for g in ng)
 mapped=[e for e in originalfacts if (e.get('name')or'').split(':')[-1] in MAP]
 if len(mapped)!=len(records)+sum(v for k,v in gcounts.items() if k!='unmapped_concept'):errors.append('mapped_fact_accounting_mismatch')
 oldsrc=next(x for x in read(OLD/'sources.json') if x['company_id']==src['company_id']);oldraw=(OLD/oldsrc['raw_file']).read_bytes();oldt=html.fromstring(oldraw,parser=html.HTMLParser(encoding='utf-8'))
 oldcompare={'old_sha':sha(oldraw),'new_sha':sha(raw),'old_bytes':len(oldraw),'new_bytes':len(raw),'exact_bytes_equal_after_removing_script_elements':re.sub(rb'<script\b[^>]*>.*?</script\s*>',b'',oldraw,flags=re.I|re.S)==re.sub(rb'<script\b[^>]*>.*?</script\s*>',b'',raw,flags=re.I|re.S),'all_inline_facts_equal':facts(oldt)==facts(tree),'visible_body_text_equal':visible(oldt)==visible(tree),'scripts_old':[text(x)[:300] for x in oldt.iter() if local(x)=='script'],'scripts_new':[text(x)[:300] for x in tree.iter() if local(x)=='script']}
 signatures=defaultdict(list)
 for row in records:signatures[json.dumps([row['metric_id'],row['period'],row['dimensions']],sort_keys=True)].append(row)
 repeated=[{'occurrences':len(v),'values':sorted({x['value_decimal'] for x in v}),'fact_ids':[ev[x['evidence_ids'][0]]['fact_id'] for x in v]} for v in signatures.values() if len(v)>1]
 results[company]={'dataset':str(p),'source_url':src['source_url'],'acquisition_errors':errors,'expected_selected_filings':expected,'archives_excluded':sub['filings']['files'],'acquired_count':len(docs),'bytes':len(raw),'transport_content_length':docs[0]['transport']['content_length'],'source_hash_verified':sha(raw)==src['source_sha256'],'closed_html':bool(re.search(rb'</body\s*>\s*</html\s*>\s*$',raw,re.I)),'model_calls':acq['model_calls'],'all_raw_nonfraction_count':len(originalfacts),'mapped_fact_count':len(mapped),'standardized_record_count':len(records),'normalization_gaps':dict(gcounts),'unmapped_unique_concepts':len({x['concept'] for x in ng if x['reason']=='unmapped_concept'}),'metrics':dict(normalized),'record_errors':record_errors,'record_checks':checked,'duplicate_same_fact_emission':len(seenfacts)-len(set(seenfacts)),'source_repeated_metric_period_dimensions':repeated,'source_repeated_conflict_groups':sum(len(x['values'])>1 for x in repeated),'old_vs_fresh':oldcompare,'limits':['Primary 10-K only; linked exhibits/proxy/included-by-reference originals not acquired.','No Content-Length returned; complete HTML envelope, independent identity, manifest hashes and transport byte counts pass, but no independent SEC published checksum.','Standardized financial metrics are a six-metric subset; raw tables preserve other metrics.','Source repeated fact occurrences are retained with separate evidence; they are not parser duplicated DOM facts.']}
out=BASE/'evaluation-only'/f'{VERSION}-source-financial-audit.json';out.write_text(json.dumps(results,ensure_ascii=False,indent=2));print(out)
for c,r in results.items():print(c,{k:r[k] for k in ('acquisition_errors','record_errors','standardized_record_count','normalization_gaps','duplicate_same_fact_emission','source_repeated_conflict_groups')},r['old_vs_fresh'])
