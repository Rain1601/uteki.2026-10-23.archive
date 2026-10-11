"""One controlled historical failure replay, then fresh S1/S3; gold is never dispatched."""
import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import json

from uteki.agents.data_query import retrieval_cycle as cycle, answer_handoff as handoff
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest
from runtime_helpers import ROOT, EXP, OUTPUT, read, ledger, check_ledger, verify_freeze, task_guard, metrics, terminal_reason


class FrozenRole:
    plan_origin = 'scripted_fixture'

    def __init__(self, output, original, names):
        self.output, self.original, self.names, self.ordinal = output, original, names, 0
        output.mkdir()

    async def review(self, packet):
        name = self.names[self.ordinal]
        self.ordinal += 1
        write_new(self.output / f'controlled-input-{self.ordinal}.json', packet)
        response = read(self.original / name)
        write_new(self.output / f'controlled-output-{self.ordinal}.json', response)
        write_new(self.output / f'controlled-origin-{self.ordinal}.json',
                  {'operation': 'original-failed-review-replay', 'model_call': False,
                   'original': str(self.original / name),
                   'original_sha256': digest((self.original / name).read_bytes())})
        return deepcopy(response)

    async def aclose(self):
        pass

    def snapshot_usage(self):
        return {'plan_origin': self.plan_origin, 'model_requests': 0}


async def execute(case_id):
    cases = read(EXP / 'execution-matrix.v1.json')['cases']
    case = next(c for c in cases if c['id'] == case_id)
    for previous in cases[:cases.index(case)]:
        release = read(EXP / 'evaluation-only' / (previous['id'] + '-release.v1.json'))
        receipt_path = (ROOT / previous['run']).parent / 'execution-receipt.v1.json'
        assert release['continue'] and release['receipt_sha256'] == digest(receipt_path.read_bytes())
    verify_freeze()
    config = read(ROOT / case['config'])
    before = check_ledger(config)
    target = ROOT / case['run']
    assert not target.exists() and not Path(config['workspace']).exists()
    print('START ' + case_id, flush=True)
    if case['operation'].startswith('controlled'):
        original = ROOT / 'output/e6-repeatability-20261010-r2/R3/S1/run-r1/attempt-01/review-01'
        source_factory, question_factory = cycle.reviewer_factory, cycle.question_reviewer_factory

        def role_factory(role, inner, names):
            def factory(*args, **kwargs):
                actual = inner(*args, **kwargs)
                def make(output):
                    if output.parent.parent.name == 'attempt-01':
                        return FrozenRole(output, original, names)
                    return actual(output)
                return make
            return factory

        with task_guard(config), patch.object(cycle, 'reviewer_factory',
                role_factory('source', source_factory, ['source-response.json'])), patch.object(
                cycle, 'question_reviewer_factory', role_factory('question', question_factory,
                ['question-response-01.json', 'question-response-02.json'])):
            result = await cycle.run_retrieval_cycle(config, target)
    else:
        with task_guard(config):
            result = await cycle.run_retrieval_cycle(config, target)
    cycle._verify_manifest(target)
    after = check_ledger(config)
    value = metrics({'slot_id': case_id, 'tier_id': case_id, 'round': 1, 'run': case['run']})
    strict = {'status': 'not_passed'}
    if result['status'] == 'reviewed_data_ready':
        ref = result['final_review_ref']
        loaded = handoff.load_reviewed_data(ref['path'], expected_scope=config['request']['scope'],
            expected_review_manifest_sha256=ref['manifest_sha256'])
        strict = {'status': 'passed', 'handoff_id': loaded['handoff_id'],
                  'boundary': 'Final fresh query and complete dual review only; controlled historical prefix is disclosed.'}
    receipt = {'case_id': case_id, 'operation': case['operation'], 'result': result,
               'metrics': value, 'strict_load': strict, 'ledger_before': before, 'ledger_after': after,
               'stop_reason': terminal_reason(result, target, after)}
    write_new(target.parent / 'execution-receipt.v1.json', receipt)
    verify_freeze()
    print(json.dumps({'case': case_id, 'status': result['status'], 'strict': strict['status'],
                      'calls': after['requests'] - before['requests'],
                      'known_usd': str(Decimal(after['known_usd']) - Decimal(before['known_usd'])),
                      'stop_reason': receipt['stop_reason']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    asyncio.run(execute(parser.parse_args().case))
