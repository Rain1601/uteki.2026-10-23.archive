"""Frozen E6-R4 real runs; private gold is hashed, never passed to a model."""
import argparse
import asyncio
from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, _verify_manifest
from uteki.agents.data_query.retrieval_cycle import run_retrieval_cycle, validate
from uteki.agents.runtime.output_limit import ModelOutputLimitExceeded
from uteki.agents.runtime.run_budget import RunBudget

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
LEDGER = ROOT/'output/m3-rebuild-20261012-r2/costs.sqlite'

def read(p): return json.loads(p.read_bytes())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def implementation():
    paths = [p for b in (ROOT/'src/uteki',ROOT/'skills/data-agent') for p in b.rglob('*')
             if p.is_file() and p.suffix in {'.py','.md','.json'}]
    paths += [HERE/'run.py', HERE/'prepare.py', HERE/'question.v1.json', HERE/'PLAN.zh-CN.md']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}

def model_for(slot):
    m = {'provider':'deepseek','model':'deepseek-flash','reasoning_effort':'low',
         'max_tokens':8192 if slot=='C1' else 256,'request_timeout':180,'max_retries':1,
         'budget_ledger':str(LEDGER),'budget_usd':'3','budget_policy':'enforced',
         'max_requests_total':200,'allow_unknown_reservations':False}
    if not slot.startswith('B'):
        m['output_capacity_recovery']={'version':'output-capacity-recovery-v1',
            'max_tokens':16384 if slot=='C1' else 8192,'max_recoveries':1}
    return m

def config_for(base,slot):
    planner=model_for(slot)
    worker={k:v for k,v in planner.items() if k!='output_capacity_recovery'}
    worker['max_tokens']=8192
    review={**worker,'reasoning_effort':'none','max_tokens':16384}
    return {'request':{'question':read(HERE/'question.v1.json')['question'],
        'purpose':'analysis_evidence','dataset':str(base/'dataset'),'scope':read(base/'scope.json'),
        'limits':{'max_steps':64,'max_packet_bytes':160000,'observation_bytes':24000,
                  'page_items':12,'turn_timeout':240}},
        'planner':planner,'worker':worker,'reviewer':deepcopy(review),
        'question_reviewer':deepcopy(review),'question_review_policy':'independent-question-v2',
        'credential_root':str(ROOT),'workspace':str(base/slot/'workspace'),
        'max_review_packet_bytes':400000,'reviewer_max_request_bytes':600000,'max_attempts':2}

def freeze(base):
    value={'schema':'e6-r4-execution-freeze-v1','implementation':implementation(),
        'dataset_manifest_sha256':sha(base/'dataset/manifest.json'),
        'scope_sha256':sha(base/'scope.json'),'preparation_sha256':sha(base/'preparation.v1.json'),
        'withheld_standard_sha256':sha(base/'evaluation-only/expected.v1.json'),
        'independent_original_review_sha256':sha(base/'evaluation-only/root-original-review.v1.json'),
        'repetitions':3,'control_runs':1,'diagnostic_baselines':3,
        'ledger':str(LEDGER),'usd_cap':'3','request_cap':200,
        'configs':{slot:config_for(base,slot) for slot in ['R1','R2','R3','C1']},
        'baseline_configs':{slot:model_for(slot) for slot in ['B1','B2','B3']}}
    path=base/'execution-freeze.v1.json'
    if path.exists():
        if read(path)!=value:raise ValueError('Frozen experiment changed; preserve results and create a new version')
    else:
        write_new(path,value)
        dest=base/'implementation-source'
        for rel,s in value['implementation'].items():
            raw=(ROOT/rel).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=s:raise ValueError('Implementation changed during freeze')
            p=dest/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    return value

async def baseline(base,slot,budget):
    origin=base/('R'+slot[1:])/'run'
    _verify_manifest(origin)
    _verify_manifest(origin/'attempt-01/data-query')
    source=origin/'attempt-01/data-query/query/turn-001/input.json'
    raw=source.read_bytes();packet=json.loads(raw)
    input_sha256=hashlib.sha256(raw).hexdigest()
    folder=base/slot;folder.mkdir(mode=0o700)
    write_new(folder/'input.json',packet)
    config=model_for(slot);write_new(folder/'runtime-config.json',config)
    write_new(folder/'budget-before.json',budget.summary())
    planner=CompanyDataCoordinator._planner(config,folder/'model',ROOT,purpose='analysis_evidence')
    try:
        result=await planner.decide(packet)
        report={'status':'complete_decision_unexpected','action':result.action,'action_executed':False}
    except ModelOutputLimitExceeded as error:
        report={'status':'output_limited','diagnostic':error.diagnostic,'action_executed':False}
    except Exception as error:
        report={'status':'failed','error_type':type(error).__name__,'action_executed':False}
    finally:
        await planner.aclose()
        write_new(folder/'usage.json',planner.snapshot_usage())
        write_new(folder/'budget-after.json',budget.summary())
    write_new(folder/'result.json',{**report,'source_input':str(source),'source_input_sha256':input_sha256,
        'origin_manifest_sha256':sha(origin/'manifest.json'),
        'scope':'One isolated real decision using the matched fresh-run first packet, never a complete business run'})
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--slot',choices=['B1','B2','B3','R1','R2','R3','C1'],required=True)
    parser.add_argument('--check-only',action='store_true')
    a=parser.parse_args();base=a.batch.resolve()
    if not LEDGER.is_file():raise ValueError('Existing shared ledger required; no fork')
    folder=base/a.slot
    if folder.exists():raise ValueError('Slot already exists; failed runs are never replaced')
    budget=RunBudget(LEDGER,'3')
    if budget.summary()['unknown_requests'] or budget.summary()['in_flight_requests']:
        raise ValueError('Unresolved current cost; no blind new call')
    prepared=read(base/'preparation.v1.json')
    if (not prepared['passed'] or prepared['dataset_manifest_sha256']!=sha(base/'dataset/manifest.json')
            or prepared['scope_sha256']!=sha(base/'scope.json')
            or Path(prepared['ledger']).resolve()!=LEDGER.resolve()):
        raise ValueError('Preparation receipt must bind the exact full dataset')
    gold=read(base/'evaluation-only/expected.v1.json')
    if (gold['dataset_manifest_sha256']!=sha(base/'dataset/manifest.json')
            or gold['scope_sha256']!=sha(base/'scope.json')
            or gold['question_sha256']!=sha(HERE/'question.v1.json')):
        raise ValueError('Withheld standard must bind the exact dataset, scope and question')
    original=read(base/'evaluation-only/root-original-review.v1.json')
    if not original['passed'] or original['expected_sha256']!=sha(base/'evaluation-only/expected.v1.json'):
        raise ValueError('Independent original review must bind the frozen withheld standard')
    if not a.slot.startswith('B'):validate(config_for(base,a.slot),folder/'run')
    if a.check_only:print('Inputs checked; no dispatch or freeze writes');return
    with (base/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        freeze(base)
        if a.slot.startswith('B'):
            report=asyncio.run(baseline(base,a.slot,budget))
        else:
            config=config_for(base,a.slot);write_new(folder/'runtime-config.json',config)
            write_new(folder/'budget-before.json',budget.summary())
            try:report=asyncio.run(run_retrieval_cycle(config,folder/'run'))
            finally:write_new(folder/'budget-after.json',budget.summary())
        print(json.dumps({'slot':a.slot,'status':report['status'],'budget':budget.summary()},ensure_ascii=False))

if __name__=='__main__':main()
