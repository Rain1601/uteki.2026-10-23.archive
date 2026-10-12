"""Official DeepSeek complete-inventory preparation in the one M3 task budget."""
import argparse,asyncio,hashlib,json,os
from pathlib import Path
from uteki.agents.figure_materials import run_figure_preparation
from uteki.agents.runtime.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--ocr-bin',type=Path,required=True)
    parser.add_argument('--material-version',choices=['v1','v2','v3'],required=True)
    parser.add_argument('--reasoning',choices=['high','none'],required=True)
    args=parser.parse_args();base=args.batch.resolve();ocr=args.ocr_bin.resolve()
    if not (ocr/'tesseract').is_file(): raise ValueError('Explicit Tesseract executable missing')
    os.environ['PATH']=str(ocr)+os.pathsep+os.environ.get('PATH','')
    ledger=base/'costs.sqlite'
    authorization=base/'task-budget.json'
    if not authorization.exists():
        authorization.write_text(json.dumps({'schema':'m3-task-budget-v1','authorized_by':'user',
            'instruction':'continue 03-M3, rebuild after original cross-machine package loss, freeze and execute',
            'basis':'AGENTS independent task USD 3 boundary; all material and Query failures/revisions share one budget',
            'limit_usd':'3','prior_api_calls_in_this_m3_task':0,
            'legacy_E1_ledger_restored':False,'historical_costs_not_cleared':True},indent=2)+'\n')
    budget=RunBudget(ledger,'3')
    version=args.material_version
    if (version,args.reasoning) not in [('v1','high'),('v2','none'),('v3','none')]:
        raise ValueError('Version must identify the explicit frozen thinking configuration')
    target=base/('transcribed-'+version)
    if target.exists(): raise ValueError('Preserve prior material preparation; output must be new')
    files=[p for p in (ROOT/'src/uteki').rglob('*.py')]
    files += [Path(__file__).resolve()]
    freeze={'schema':'m3-material-configuration-v2','version':version,
        'provider':'deepseek','model':'deepseek-flash','reasoning_effort':args.reasoning,
        'max_tokens':8192,'all_inventory':True,
        'coordinate_policy':'host_ocr_v1' if version=='v3' else 'model_proposal','budget_before':budget.summary(),
        'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
        'ocr_binary_sha256':hashlib.sha256((ocr/'tesseract').read_bytes()).hexdigest(),
        'ocr_eng_sha256':hashlib.sha256((ocr.parent/'share/tessdata/eng.traineddata').read_bytes()).hexdigest()}
    with (base/('material-configuration-freeze.'+version+'.json')).open('x') as f:
        json.dump(freeze,f,indent=2)

    async def run():
        for c in ('msft','googl'):
            r=await run_figure_preparation(base/'preparation'/c/'dataset',base/'image-acquisition'/c,
                target/c,provider='deepseek',model='deepseek-flash',
                reasoning_effort=args.reasoning,budget=budget,credentials_root=ROOT,
                coordinate_policy='host_ocr_v1' if version=='v3' else 'model_proposal')
            print(json.dumps({'company':c,'status':r['status'],'figures':len(r['figures']),
                'gaps':r['gaps'],'task_budget':budget.summary()},ensure_ascii=False),flush=True)
    asyncio.run(run())

if __name__=='__main__': main()
