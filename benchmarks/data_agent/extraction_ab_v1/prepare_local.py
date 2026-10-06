"""Freeze already acquired originals into new datasets; no model calls or gold reads."""
from pathlib import Path
import gzip, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from uteki.infrastructure.research_data.company_materialization import materialize_sources
BASE=ROOT/'data/company_workspace/extraction_ab_v1/corpus'
def freeze(symbol,cik,name,items,folder_name=None):
    folder=BASE/(folder_name or symbol.lower());folder.mkdir(parents=True,exist_ok=True)
    docs=[]
    for item in items:
        origin=ROOT/item.pop('original');raw=gzip.decompress(origin.read_bytes()) if origin.suffix=='.gz' else origin.read_bytes()
        digest=hashlib.sha256(raw).hexdigest();assert digest==item.pop('expected_sha256')
        sid=item['source_id']; path=folder/'originals'/(sid+'.html');path.parent.mkdir(exist_ok=True)
        with path.open('xb') as out:out.write(raw)
        docs.append({**item,'path':str(path.relative_to(folder)),'content_sha256':digest,'mime_type':'text/html','status':'frozen','original_local_path':str(origin.relative_to(ROOT))})
    source_run={'schema_version':'local-original-reuse-v1','company':{'company_id':'sec-'+cik,'symbol':symbol,'cik':cik,'name':name,'market':'NASDAQ'},'as_of':'2026-09-24','documents':docs,'gaps':[]}
    (folder/'acquisition.json').write_text(json.dumps(source_run,indent=2)+'\n')
    result=materialize_sources(source_run,folder,folder/'dataset')
    print(symbol, {k: result[k] for k in ('snapshot_id','source_count','record_count')})
if __name__=='__main__':
    items=[]
    for rel,label in [('data/source_documents/alphabet_2025_10k','googl-2025-10k'),('data/document_library/alphabet/sources/alphabet-000165204425000091','googl-2025q3-10q')]:
        d=json.loads((ROOT/rel/'manifest.json').read_text());items.append({'original':rel+'/source.html.gz','expected_sha256':d['content_sha256'],'source_id':label,'source_url':d['source_url'],'form':d['form'],'period_end':d['period_end'],'filed_at':d['filed_at']})
    freeze('GOOGL','0001652044','Alphabet Inc.',items)
    rel='data/company_workspace/record_review/msft-fy2025/datasets/query-a80aa612c40a8ef6ca17e36a';d=json.loads((ROOT/rel/'sources.json').read_text())[0]
    freeze('MSFT','0000789019','Microsoft Corporation',[{'original':rel+'/'+d['raw_file'],'expected_sha256':d['raw_file_sha256'],'source_id':'msft-2025-10k','source_url':d['source_url'],'form':'10-K','period_end':d['period_end'],'filed_at':d['available_at']}])
