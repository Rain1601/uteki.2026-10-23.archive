"""One serial, source-pinned Sonnet repeat; reuse the existing request implementation."""
import argparse
import asyncio
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path

from uteki.agents.runtime.run_budget import RunBudget

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / '2026-10-07-reproducibility-pilot-v1'
RUNNER = HERE.parent / '2026-10-07-explicit-single-trial-v1/run_once.py'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular evidence file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_plan():
    plan = json.loads((HERE / 'plan.json').read_text())
    cases = plan['call_order']
    if len(cases) != 6 or [c['ordinal'] for c in cases] != list(range(1, 7)):
        raise ValueError('Expected six registered sequential calls')
    prep = module(BASE / 'prepare_benchmark.py', 'stability_preparation')
    prep.verify_benchmark(BASE)
    runner = module(RUNNER, 'stability_request')
    profiles = {p['id']: p for p in plan['profiles']}
    tasks = {t['id']: t for t in plan['tasks']}
    for case in cases:
        task, profile = tasks[case['task_id']], profiles[case['profile_id']]
        if case['prepared'] != task['prepared'] or digest((HERE/profile['path']).resolve()) != profile['sha256']:
            raise ValueError('Task/profile selection changed')
        prepared = runner.prepare(HERE/profile['path'], HERE/case['prepared'])
        meta, body, snapshot = prepared[4], prepared[5], prepared[7]
        if any(meta[key] != task[key] for key in ('packet_sha256','manifest_sha256','system_sha256','messages_sha256')):
            raise ValueError('Task evidence changed')
        baseline = next(c for c in plan['baseline_cases'] if c['task_id'] == task['id'])
        previous = HERE/baseline['output_path']
        if body != json.loads((previous/'http-request.json').read_text())['body']:
            raise ValueError('Request must exactly match baseline body')
        if snapshot != json.loads((previous/'configuration.json').read_text()):
            raise ValueError('Configuration must match baseline snapshot')
    return plan, runner


def pin_execution():
    if (HERE/'runs').exists() or (HERE/'budget.sqlite').exists():
        raise ValueError('Cannot repin after execution begins')
    plan, runner = read_plan()
    budget = plan['limits']['aggregate_estimated_budget_usd']
    profile = plan['profiles'][0]
    reservations = [Decimal(runner.inspect(HERE/profile['path'], HERE/c['prepared'], budget)
                            ['conservative_request_reservation_usd']) for c in plan['call_order']]
    if max(reservations) > Decimal(budget):
        raise ValueError('A request reservation exceeds total cap')
    dependencies = [HERE/'plan.json', Path(__file__), HERE/'evaluate.py', RUNNER,
                    BASE/'prepare_benchmark.py', BASE/'evaluate.py', BASE/'run_case.py',
                    BASE/'plan.json', BASE/'execution-pin.json', BASE/'source-verification.json',
                    ROOT/'src/uteki/agents/runtime/model_configuration.py',
                    ROOT/'src/uteki/agents/runtime/call_costs.py',
                    ROOT/'src/uteki/agents/runtime/run_budget.py',
                    runner.PRIOR, HERE/profile['path']]
    for task in plan['tasks']:
        dependencies.extend((HERE/task['prepared']).glob('*'))
        dependencies.extend([HERE/task['reference'], HERE/task['rubric']])
    for case in plan['baseline_cases']:
        dependencies.extend(p for p in (HERE/case['output_path']).rglob('*') if p.is_file())
    record = {'schema_version':'sonnet-stability-execution-pin-v1', 'budget_usd':budget,
              'maximum_calls':6, 'conservative_all_calls_usd':str(sum(reservations)),
              'budget_rule':'Reserve each next request against one shared ledger; stop if it cannot fit.',
              'files':{str(p.resolve().relative_to(ROOT)):digest(p.resolve()) for p in dependencies}}
    with (HERE/'execution-pin.json').open('x') as f:
        json.dump(record, f, indent=2)
    return {key:value for key,value in record.items() if key != 'files'}


def verify_pin():
    pin = json.loads((HERE/'execution-pin.json').read_text())
    for name, expected in pin['files'].items():
        if digest(ROOT/name) != expected:
            raise ValueError('Pinned code, input, evaluation or baseline changed: '+name)
    return pin


async def execute(ordinal):
    with (HERE/'.execution.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        pin = verify_pin()
        plan, runner = read_plan()
        if type(ordinal) is not int or not 1 <= ordinal <= pin['maximum_calls']:
            raise ValueError('Select one registered ordinal')
        budget = RunBudget(HERE/'budget.sqlite', pin['budget_usd'])
        old_dispatch = module(BASE/'run_case.py', 'stability_sequence_guard')
        old_dispatch.verify_previous(HERE, plan['call_order'], ordinal, budget.summary())
        case = plan['call_order'][ordinal-1]
        profile = next(p for p in plan['profiles'] if p['id'] == case['profile_id'])
        result = await runner.run_once(HERE/profile['path'], HERE/case['prepared'],
                                      HERE/case['output_path'], pin['budget_usd'],
                                      budget_path=HERE/'budget.sqlite')
        call = result['arms'][0]
        return {'ordinal':ordinal, 'trial_id':case['trial_id'], 'status':result['status'],
                **{key:call.get(key) for key in ('http_status','finish_reason','response_id','raw_usage',
                                                'elapsed_seconds','estimated_usd')},
                'budget':result['budget']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--pin-execution', action='store_true')
    group.add_argument('--verify', action='store_true')
    group.add_argument('--ordinal', type=int)
    args = parser.parse_args()
    try:
        result = (pin_execution() if args.pin_execution else
                  {'status':'verified', 'pinned_files':len(verify_pin()['files'])} if args.verify else
                  asyncio.run(execute(args.ordinal)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if args.pin_execution or args.verify or result['status']=='completed' else 1
    except Exception as error:
        print(json.dumps({'error_type':type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
