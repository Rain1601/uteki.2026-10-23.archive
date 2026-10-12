"""Three fixed, independent M3 runs. Runtime receives question and scope, never gold."""
import argparse,asyncio,hashlib,json
from copy import deepcopy
from pathlib import Path
from uteki.agents.data_query.retrieval_cycle import run_retrieval_cycle,validate
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.runtime.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent

def read(path):return json.loads(path.read_bytes())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def implementation():
    files=[p for base in (ROOT/'src/uteki',ROOT/'skills/data-agent') for p in base.rglob('*')
           if p.is_file() and p.suffix in ('.py','.md','.json')]
    files += [HERE/'run.py',HERE/'question.v1.json']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(files)}

def config_for(base,slot,material_version,query_version):
    dataset=base/'preparation/googl/dataset';bundle=base/('transcribed-'+material_version)/'googl'
    manifest=read(dataset/'manifest.json');sources=read(dataset/'sources.json')
    model={'provider':'deepseek','model':'deepseek-flash','reasoning_effort':'low',
        'max_tokens':8192,'request_timeout':180,'max_retries':1,
        'budget_ledger':str(base/'costs.sqlite'),'budget_usd':'3','budget_policy':'enforced',
        'max_requests_total':200,'allow_unknown_reservations':False}
    review={**model,'reasoning_effort':'none','max_tokens':16384}
    return {'request':{'question':read(HERE/'question.v1.json')['question'],'purpose':'analysis_evidence',
        'dataset':str(dataset),'scope':{'snapshot_id':manifest['snapshot_id'],
            'company_ids':sorted({s['company_id'] for s in sources}),
            'source_snapshot_ids':[s['source_snapshot_id'] for s in sources],
            'source_policy_id':'local-frozen-v1','knowledge_cutoff':'2026-02-06','include_candidates':True},
        'figure_bundle_ref':{'path':str(bundle),'manifest_sha256':sha(bundle/'manifest.json')},
        'limits':{'max_steps':64,'max_packet_bytes':160000,'observation_bytes':24000,
                  'page_items':12,'turn_timeout':240}},
        'planner':deepcopy(model),'worker':deepcopy(model),'reviewer':deepcopy(review),
        'question_reviewer':deepcopy(review),'question_review_policy':'independent-question-v2',
        'credential_root':str(ROOT),'workspace':str(base/('query-'+query_version)/slot/'workspace'),
        'max_review_packet_bytes':400000,'reviewer_max_request_bytes':600000,'max_attempts':2}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--material-version',choices=['v1','v2','v3'],required=True)
    p.add_argument('--query-version',choices=['v1','v2'],required=True)
    p.add_argument('--slot',choices=['R1','R2','R3'],required=True);p.add_argument('--check-only',action='store_true')
    args=p.parse_args();base=args.batch.resolve()
    acceptance_path=base/('evaluation-only/material-acceptance.'+args.material_version+'.json')
    accepted=read(acceptance_path)
    if not accepted['passed']:raise ValueError('Independent image material acceptance required before Query')
    if not (base/'costs.sqlite').is_file():raise ValueError('Material task ledger must already exist; no fork')
    config=config_for(base,args.slot,args.material_version,args.query_version);folder=base/('query-'+args.query_version)/args.slot
    current={'dataset_manifest_sha256':sha(base/'preparation/googl/dataset/manifest.json'),
        'figure_manifest_sha256':config['request']['figure_bundle_ref']['manifest_sha256']}
    if accepted.get('material_version')!=args.material_version or accepted.get('bindings',{}).get('googl')!=current:
        raise ValueError('Independent receipt does not bind the exact current dataset and figure package')
    validate(config,folder/'run')
    if args.check_only:print('M3 input checked; no model dispatch or writes');return 0
    pin={'question_sha256':sha(HERE/'question.v1.json'),'plan_sha256':sha(HERE/('QUERY-v2.zh-CN.md' if args.query_version=='v2' else 'PLAN.zh-CN.md')),
        'dataset_manifest_sha256':sha(base/'preparation/googl/dataset/manifest.json'),
        'figure_manifest_sha256':config['request']['figure_bundle_ref']['manifest_sha256'],
        'independent_acceptance_sha256':sha(acceptance_path),
        'question_standard_sha256':sha(base/'evaluation-only/question-expected.v1.json'),
        'material_version':args.material_version,'repetitions':3,'implementation':implementation()}
    freeze=base/('query-'+args.query_version)/('input-freeze.'+args.query_version+'.json')
    if freeze.exists():
        if read(freeze)!=pin:raise ValueError('Input/implementation changed; create a new version, preserve old runs')
    else:write_new(freeze,pin)
    write_new(folder/'runtime-config.json',config)
    budget=RunBudget(base/'costs.sqlite','3')
    write_new(folder/'budget-before.json',budget.summary())
    try:
        result=asyncio.run(run_retrieval_cycle(config,folder/'run'))
        print(json.dumps({'slot':args.slot,'status':result['status'],'failures':result.get('failures'),
            'task_budget':budget.summary()},ensure_ascii=False))
        return 0 if result['status']=='reviewed_data_ready' else 1
    finally:write_new(folder/'budget-after.json',budget.summary())

if __name__=='__main__':raise SystemExit(main())
