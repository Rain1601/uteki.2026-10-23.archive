"""Execute exactly one pre-registered pilot case under a shared budget and lock."""
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
RUNNER = HERE.parent/'2026-10-07-explicit-single-trial-v1/run_once.py'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular evidence file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pin_execution():
    prep = module(HERE/'prepare_benchmark.py', 'pilot_preparation')
    runner = module(RUNNER, 'pilot_single_request')
    prep.verify_benchmark(HERE)
    plan = json.loads((HERE/'plan.json').read_text())
    profiles = {p['id']: p for p in plan['profiles']}
    total = sum((Decimal(runner.inspect(HERE/profiles[c['profile_id']]['path'], HERE/c['prepared'],
                    plan['limits']['aggregate_estimated_budget_usd'])['conservative_request_reservation_usd'])
                 for c in plan['call_order']), Decimal(0))
    if total > Decimal(plan['limits']['aggregate_estimated_budget_usd']):
        raise ValueError('All planned conservative reservations must fit the pilot budget')
    paths = [HERE/'plan.json', HERE/'prepare_benchmark.py', RUNNER, Path(__file__),
             ROOT/'src/uteki/agents/runtime/model_configuration.py',
             ROOT/'src/uteki/agents/runtime/call_costs.py', ROOT/'src/uteki/agents/runtime/run_budget.py']
    record = {'schema_version': 'pilot-execution-pin-v1',
              'files': {str(p.relative_to(ROOT)): digest(p) for p in paths},
              'maximum_calls': len(plan['call_order']), 'conservative_all_calls_usd': str(total),
              'budget_usd': plan['limits']['aggregate_estimated_budget_usd']}
    if (HERE/'runs').exists() or (HERE/'budget.sqlite').exists():
        raise ValueError('Cannot repin a pilot after execution begins')
    with (HERE/'execution-pin.json').open('x') as file:
        json.dump(record, file, indent=2)
    return record


def verify_previous(folder, cases, ordinal, budget_summary):
    if budget_summary['unknown_requests'] or budget_summary['in_flight_requests']:
        raise ValueError('Resolve previous unknown or in-flight request before continuing')
    if budget_summary['requests'] != ordinal-1:
        raise ValueError('Request count differs from the selected sequential case')
    for case in cases[:ordinal-1]:
        previous = json.loads((folder/case['output_path']/'summary.json').read_text())
        if previous['status'] != 'completed':
            raise ValueError('Previous failed or invalid case requires review; no automatic next request')
        usage = previous['arms'][0]['raw_usage']
        if usage is None or usage['prompt_tokens'] > 6000:
            raise ValueError('Previous input exceeded the bounded pilot input target')


async def execute(ordinal):
    with (HERE/'.execution.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        pin = json.loads((HERE/'execution-pin.json').read_text())
        for path, expected in pin['files'].items():
            if digest(ROOT/path) != expected:
                raise ValueError('Execution code or pre-registered plan changed')
        prep = module(HERE/'prepare_benchmark.py', 'pilot_preparation')
        prep.verify_benchmark(HERE)
        plan = json.loads((HERE/'plan.json').read_text())
        if type(ordinal) is not int or not 1 <= ordinal <= min(8, pin['maximum_calls']):
            raise ValueError('Select one of the eight registered cases')
        case = plan['call_order'][ordinal-1]
        profile = next(p for p in plan['profiles'] if p['id'] == case['profile_id'])
        budget = RunBudget(HERE/'budget.sqlite', pin['budget_usd'])
        verify_previous(HERE, plan['call_order'], ordinal, budget.summary())
        runner = module(RUNNER, 'pilot_single_request')
        result = await runner.run_once(HERE/profile['path'], HERE/case['prepared'],
            HERE/case['output_path'], pin['budget_usd'], budget_path=HERE/'budget.sqlite')
        call = result['arms'][0]
        return {'ordinal': ordinal, 'trial_id': case['trial_id'], 'status': result['status'],
                'http_status': call.get('http_status'), 'finish_reason': call.get('finish_reason'),
                'request_id': call.get('request_id'), 'response_id': call.get('response_id'),
                'usage': call.get('raw_usage'), 'elapsed_seconds': call.get('elapsed_seconds'),
                'estimated_usd': call.get('estimated_usd'), 'budget': result['budget']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--pin-execution', action='store_true')
    group.add_argument('--ordinal', type=int)
    args = parser.parse_args()
    try:
        result = pin_execution() if args.pin_execution else asyncio.run(execute(args.ordinal))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if args.pin_execution or result['status'] == 'completed' else 1
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
