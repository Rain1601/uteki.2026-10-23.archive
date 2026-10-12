"""One authorized company at a time; same existing ledger, no reset or fork."""
import asyncio
import argparse
import hashlib
import json
from pathlib import Path
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.runtime.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
LEDGER=ROOT/'output/m3-rebuild-20261012-r2/costs.sqlite'
BASE=ROOT/'output/ds03-a01-20261012'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

async def main():
    parser=argparse.ArgumentParser();parser.add_argument("--attempt",choices=["r1","r2"],default="r1")
    parser.add_argument("--company",choices=["TSM","MSFT"],default="TSM")
    args=parser.parse_args();attempt=args.attempt;company=args.company
    runbase=BASE/(attempt if company=="TSM" else "msft-"+attempt)
    runbase.mkdir(parents=True,exist_ok=False)
    if not LEDGER.is_file():raise ValueError('Existing shared ledger required')
    budget=RunBudget(LEDGER,'3')
    config={'symbol':'TSM','cik':'0001046179','market':'NYSE','as_of':'2026-10-12',
        'sec_user_agent':'Uteki official material research',
        'filing_selection':{'mode':'annual_filing_period','annual_form':'20-F','report_period_end':'2025-12-31'},
        'source_policy':{'official':[{'kind':'ir','url':'https://investor.tsmc.com/',
            'allowed_hosts':['investor.tsmc.com','investor.cld.tsmc.com','www.tsmc.com']}],
            'third_party':[],'updates_window':{'trailing_calendar_days':365}},
        'limits':{'max_requests':16,'max_documents':1,'max_bytes_per_document':4000000,
                  'max_total_bytes':16000000,'timeout_seconds':20,'retries':1,'backoff_seconds':1}}
    task={'company':{'company_id':'sec-0001046179','symbol':'TSM','cik':'0001046179','market':'NYSE',
            'name':'Taiwan Semiconductor Manufacturing Company Limited','aliases':['TSMC','Taiwan Semiconductor Manufacturing Company']},
        'fiscal_year':2025,'period_end':'2025-12-31','material_type':'annual_report',
        'task':'Find and archive one official HTML FY2025 annual report or a substantive HTML part of that annual report for TSMC. A generic list of reports or navigation landing page is insufficient. Start at the official root and follow observed links only.',
        'roots':['https://investor.tsmc.com/'],'allowed_hosts':['investor.tsmc.com','investor.cld.tsmc.com','www.tsmc.com'],
        'max_steps':16,'page_chars':14000,'links_per_page':60}
    if company == 'MSFT':
        config.update(symbol='MSFT',cik='0000789019',market='NASDAQ',
            filing_selection={'mode':'annual_filing_period','annual_form':'10-K','report_period_end':'2025-06-30'})
        config['source_policy']['official']=[{'kind':'ir','url':'https://www.microsoft.com/',
                                               'allowed_hosts':['www.microsoft.com']}]
        task.update(company={'company_id':'sec-0000789019','symbol':'MSFT','cik':'0000789019','market':'NASDAQ',
            'name':'Microsoft Corporation','aliases':['Microsoft','Microsoft Corporation']},period_end='2025-06-30',
            task='Find and archive one official HTML FY2025 annual report or a substantive HTML part of that annual report for Microsoft. Generic report lists or navigation pages are insufficient. Start at the official root and follow observed links only.',
            roots=['https://www.microsoft.com/'],allowed_hosts=['www.microsoft.com'])
    model={'provider':'deepseek','model':'deepseek-flash','reasoning_effort':'none','max_tokens':4096,
        'request_timeout':90,'max_retries':1 if attempt=='r1' else 0,'budget_ledger':str(LEDGER),'budget_usd':'3',
        'budget_policy':'enforced','max_requests_total':200,'allow_unknown_reservations':attempt=='r2'}
    BASE.mkdir(parents=True,exist_ok=True)
    files=['src/uteki/infrastructure/document_sources/official_discovery.py','src/uteki/infrastructure/document_sources/company_acquisition.py',
        'src/uteki/agents/data_query/official_acquisition.py','src/uteki/agents/data_query/autonomous.py',
        'src/uteki/agents/data_query/coordinator.py','docs/research/2026-10-12-ds03-a01-contract.v1.zh-CN.md']
    write_new(runbase/'freeze.json',{'config':config,'task':task,'model':model,'implementation':{f:sha(ROOT/f) for f in files},
        'runner_sha256':sha(Path(__file__)),'budget_before':budget.summary(),'independent_acceptance':'Not supplied to model; inspect original report and discovery chain separately'})
    coordinator=CompanyDataCoordinator(BASE/'workspace')
    try:
        report=await coordinator.acquire_official(config,task,output=runbase/company.lower(),model_config=model,credential_root=ROOT)
        print(json.dumps({'status':report['status'],'stop_reason':report['stop_reason'],'documents':len(report['documents']),
            'requests':report['requests'],'gaps':report['gaps']},ensure_ascii=False))
    finally:
        write_new(runbase/'budget-after.json',budget.summary())
        print(json.dumps(budget.summary()))

if __name__=='__main__':asyncio.run(main())
