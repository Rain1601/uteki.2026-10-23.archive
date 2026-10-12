"""New material batch after original transfer loss; never claims old manifest identity."""
import argparse
import hashlib
import json
from pathlib import Path
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact
from uteki.infrastructure.document_sources.figure_acquisition import acquire_figures

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = {'mode':'trusted_local_http_proxy','proxy_url':'http://127.0.0.1:7897',
             'destination_hosts':['data.sec.gov','www.sec.gov']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--transport',choices=['public_dns_http','trusted_local_http_proxy'],required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists(): raise ValueError('New immutable batch requires a new output directory')
    contact,origin=resolve_sec_contact(settings_root=ROOT)
    if contact is None: raise ValueError('Private SEC identity required')
    output.mkdir(parents=True,mode=0o700)
    coordinator=CompanyDataCoordinator(output/'workspace')
    rows=[]
    for symbol,cik,end in [('MSFT','0000789019','2025-06-30'),('GOOGL','0001652044','2025-12-31')]:
        config={'symbol':symbol,'cik':cik,'market':'NASDAQ','as_of':'2026-02-06',
            'filing_selection':{'mode':'filing_period','form_type':'10-K','report_period_end':end},
            'document_validation':'sec_inline_identity_v1','download_policy':'revalidate',
            'source_policy':{'official':[],'third_party':[]},
            'limits':{'max_requests':12,'max_documents':4,'timeout_seconds':30,'retries':1},
            'sec_user_agent':contact}
        transport=TRANSPORT if args.transport=='trusted_local_http_proxy' else None
        if transport is not None: config['transport']=transport
        print(symbol,'new system preparation',flush=True)
        folder=output/'preparation'/symbol.lower()
        result=coordinator.prepare(config,output=folder)
        if not result.get('dataset'): raise ValueError('Preparation unavailable: '+symbol)
        dataset=Path(result['dataset']['path'])
        pictures=acquire_figures(dataset,output/'image-acquisition'/symbol.lower(),
            user_agent=contact,transport=transport)
        row={'symbol':symbol,'status':result['status'],'dataset':result['dataset'],
            'image_acquisition_status':pictures['status'],'images':len(pictures['figures']),
            'gaps':pictures['gaps'],'model_calls':0}
        rows.append(row)
        print(json.dumps({'symbol':symbol,'status':result['status'],'images':row['images'],
                          'acquisition_status':pictures['status']},ensure_ascii=False),flush=True)
    (output/'rebuild-summary.json').write_text(json.dumps({'schema':'m3-new-material-batch-v1',
        'reason':'original 2026-10-12 M2/v5 private package lost across machines; user confirmed',
        'original_package_restored':False,'transport':args.transport,'sec_identity_origin':origin,'rows':rows,
        'model_calls':0},indent=2)+'\n')

if __name__=='__main__': main()
