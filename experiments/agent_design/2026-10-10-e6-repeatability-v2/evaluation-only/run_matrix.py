"""Frozen fresh runs, first-sample release, serial execution; no outer retries."""
import argparse
import asyncio
from decimal import Decimal
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest
from runtime_helpers import ROOT, EXP, OUTPUT, read, ledger, check_ledger, verify_freeze, task_guard, metrics, terminal_reason


async def execute(item):
    verify_freeze()
    config = read(ROOT / item['config'])
    before = check_ledger(config)
    assert not (ROOT / item['run']).exists() and not Path(config['workspace']).exists(), 'no overwrite/replay or workspace reuse'
    baseline = read(OUTPUT / 'ledger-before.v1.json')
    if Decimal(before['occupied_usd']) - Decimal(baseline['occupied_usd']) >= Decimal('3'):
        raise RuntimeError('Task warning boundary; stop without changing sample count')
    print('START ' + item['slot_id'], flush=True)
    with task_guard(config):
        result = await cycle.run_retrieval_cycle(config, ROOT / item['run'])
    cycle._verify_manifest(ROOT / item['run'])
    after = check_ledger(config)
    value = metrics(item)
    receipt = {'slot_id': item['slot_id'], 'runtime_status': result['status'], 'fresh_autonomous_run': True,
               'result': result, 'metrics': value, 'ledger_before': before, 'ledger_after': after,
               'stop_reason': terminal_reason(result, ROOT / item['run'], after)}
    write_new((ROOT / item['run']).parent / 'execution-receipt.v1.json', receipt)
    verify_freeze()
    print(json.dumps({'slot': item['slot_id'], 'status': result['status'], 'calls': value['calls'],
                      'known_usd': value['known_estimated_usd'], 'mechanical_no_recovery': value['mechanical_no_recovery'],
                      'strict_load': value['strict_load_gate']['status'], 'stop_reason': receipt['stop_reason']}), flush=True)
    return receipt


async def main(args):
    matrix = read(EXP / 'execution-matrix.v1.json')['runs']
    if args.slot:
        selected = [next(row for row in matrix if row['slot_id'] == args.slot)]
    else:
        release = read(EXP / 'evaluation-only/first-sample-release.v1.json')
        first = ROOT / matrix[0]['run']
        assert release['continue_fixed_matrix'] and release['first_manifest_sha256'] == digest((first / 'manifest.json').read_bytes())
        selected = matrix[1:]
    for item in selected:
        position = matrix.index(item)
        if position > 0:
            release = read(EXP / 'evaluation-only/first-sample-release.v1.json')
            first = ROOT / matrix[0]['run']
            assert release['continue_fixed_matrix'] and release['first_manifest_sha256'] == digest((first / 'manifest.json').read_bytes())
        for previous in matrix[:position]:
            receipt = read((ROOT / previous['run']).parent / 'execution-receipt.v1.json')
            assert receipt['stop_reason'] is None, 'preceding slot has terminal stop'
        receipt = await execute(item)
        if receipt['stop_reason']:
            print('STOP ' + receipt['stop_reason'], flush=True)
            break


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--slot')
    choice.add_argument('--remaining', action='store_true')
    asyncio.run(main(parser.parse_args()))
