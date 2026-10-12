import asyncio,json
from budget import TaskBudget,ROOT,BASE
from uteki.agents.figure_materials import run_figure_preparation
async def main():
    budget=TaskBudget()
    for company in ('msft','googl'):
        result=await run_figure_preparation(ROOT/'output/preparation-acceptance-20261012/v5'/company/'dataset',BASE/'acquisition'/company,BASE/'parsed-v2'/company,model='claude-sonnet-5-5',budget=budget,credentials_root=ROOT)
        print(company,json.dumps({'status':result['status'],'figures':len(result['figures']),'gaps':result['gaps']}),flush=True)
asyncio.run(main())
