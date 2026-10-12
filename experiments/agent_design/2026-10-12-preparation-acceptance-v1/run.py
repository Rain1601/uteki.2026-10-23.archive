"""Explicit FY2025 caller scope; the system discovers/downloads/parses full filings."""
import argparse
import json
from pathlib import Path
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'output/preparation-acceptance-20261012'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--replay', type=Path)
    args=parser.parse_args()
    out=BASE/args.version
    out.mkdir(parents=True, exist_ok=False)
    rows=[]
    for symbol,cik,end in [('MSFT','0000789019','2025-06-30'),('GOOGL','0001652044','2025-12-31')]:
        config={'symbol':symbol,'cik':cik,'market':'NASDAQ','as_of':'2026-02-06',
          'filing_selection':{'mode':'filing_period','form_type':'10-K','report_period_end':end},
          'document_validation':'sec_inline_identity_v1','download_policy':'revalidate',
          'source_policy':{'official':[],'third_party':[]},
          'sec_user_agent':'Uteki research rain1104@foxmail.com',
          'limits':{'max_requests':12,'max_documents':4,'timeout_seconds':30,'retries':1},
          'transport':{'mode':'trusted_local_http_proxy','proxy_url':'http://127.0.0.1:7897','destination_hosts':['data.sec.gov','www.sec.gov']}}
        print(symbol, 'system preparation starting',flush=True)
        coordinator=CompanyDataCoordinator(BASE/'workspace')
        if args.replay:
            from uteki.infrastructure.research_data.financial_records import digest
            path=args.replay/symbol.lower()/'acquisition.json'
            acquisition=json.loads(path.read_text())
            result=coordinator.prepare_acquisition(path, acquisition_sha256=digest(path.read_bytes()),
                source_ids=[d['source_id'] for d in acquisition['documents']], output=out/symbol.lower())
        else:
            result=coordinator.prepare(config,output=out/symbol.lower())
        row={'symbol':symbol,'status':result['status'],'dataset':result.get('dataset'),
             'gap_count':len(result.get('gaps',[])),'model_calls':result.get('model_calls')}
        rows.append(row)
        print(json.dumps(row),flush=True)
    (out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
