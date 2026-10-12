from pathlib import Path
import json
from uteki.infrastructure.document_sources.figure_acquisition import acquire_figures
ROOT=Path(__file__).resolve().parents[3]
for company in ('msft','googl'):
    result=acquire_figures(ROOT/'output/preparation-acceptance-20261012/v5'/company/'dataset',
        ROOT/'output/figure-materials-20261012/acquisition'/company,
        user_agent='Uteki research rain1104@foxmail.com',
        transport={'mode':'trusted_local_http_proxy','proxy_url':'http://127.0.0.1:7897','destination_hosts':['www.sec.gov','data.sec.gov']},
        limits={'max_images':10,'max_requests':12,'max_bytes_per_image':5000000,'max_total_bytes':20000000})
    print(company,json.dumps({'status':result['status'],'figures':[{k:f.get(k) for k in ('figure_id','status','artifact_path','width','height','bytes')} for f in result['figures']],'gaps':result['gaps']}),flush=True)
