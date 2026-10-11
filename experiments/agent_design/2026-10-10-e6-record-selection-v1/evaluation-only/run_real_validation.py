"""Fixed original-prefix/model-tail replays and one fresh run; no gold input."""
import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.data_query import answer_handoff as handoff
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path.cwd()
EXPERIMENT = ROOT / 'experiments/agent_design/2026-10-10-e6-record-selection-v1'
OUTPUT = ROOT / 'output/e6-record-selection-20261010-r1'
read = lambda path: json.loads(path.read_bytes())


def verify_freeze():
    freeze = read(EXPERIMENT / 'evaluation-only/execution-freeze.v1.json')
    for relative, expected in freeze['files'].items():
        assert digest((ROOT / relative).read_bytes()) == expected, relative
    for relative, expected in freeze['sealed_refs'].items():
        cycle._verify_manifest(ROOT / relative, expected)


def ledger(config):
    connection = sqlite3.connect(Path(config['planner']['budget_ledger']).as_uri() + '?mode=ro', uri=True)
    rows = connection.execute('SELECT id,reserved,actual,state FROM reservations').fetchall()
    connection.close()
    return {'ids': [row[0] for row in rows], 'requests': len(rows),
            'known_usd': str(sum((Decimal(row[2]) for row in rows if row[3] == 'settled'), Decimal(0))),
            'held_usd': str(sum((Decimal(row[1]) for row in rows if row[3] != 'settled'), Decimal(0))),
            'unsettled_ids': sorted(row[0] for row in rows if row[3] != 'settled')}


def check_budget(config):
    current = ledger(config)
    before = read(OUTPUT / 'ledger-before.v1.json')
    assert current['unsettled_ids'] == before['unsettled_ids'], 'new unknown/inflight: stop and investigate'
    assert set(before['ids']) <= set(current['ids']), 'shared historical ledger changed'
    assert Decimal(current['known_usd']) + Decimal(current['held_usd']) - Decimal(before['known_usd']) - Decimal(before['held_usd']) < Decimal('3'), 'task warning boundary reached'
    return current


class PrefixThenModel:
    # A mixed run deliberately cannot masquerade as an all-model baseline.
    plan_origin = 'scripted_fixture'

    def __init__(self, inner, prefix, seed):
        self.inner, self.prefix, self.ordinal = inner, prefix, 0
        write_new(inner.output / 'controlled-prefix-origin.json', seed)

    async def decide(self, packet, *, observation_context=None):
        self.ordinal += 1
        if self.ordinal <= len(self.prefix):
            decision = self.prefix[self.ordinal - 1]
            write_new(self.inner.output / f'controlled-prefix-{self.ordinal:04d}.json',
                      {'origin': 'frozen_original_decision_replay', 'model_call': False,
                       'decision': decision, 'current_packet_sha256': digest(packet)})
            return AutonomousDecision.model_validate(decision)
        if self.ordinal == len(self.prefix) + 1:
            write_new(self.inner.output / 'first-real-tail-input.json', packet)
        return await self.inner.decide(packet, observation_context=observation_context)

    def snapshot_usage(self):
        return self.inner.snapshot_usage()

    async def aclose(self):
        return await self.inner.aclose()


async def execute(case_id):
    verify_freeze()
    matrix = read(EXPERIMENT / 'execution-matrix.v1.json')['cases']
    case = next(row for row in matrix if row['id'] == case_id)
    position = matrix.index(case)
    for previous in matrix[:position]:
        receipt = read(OUTPUT / previous['id'] / 'execution-receipt.v1.json')
        assert receipt['strict_load'] == 'passed', 'previous case not complete'
        release = read(EXPERIMENT / 'evaluation-only' / (previous['id'] + '-release.v1.json'))
        assert release['next_case_allowed'] and release['execution_receipt_sha256'] == digest((OUTPUT / previous['id'] / 'execution-receipt.v1.json').read_bytes())
    config = read(ROOT / case['config'])
    check_budget(config)
    target = OUTPUT / case_id
    assert not (target / 'run-r1').exists(), 'no replacement or duplicate execution'
    before = ledger(config)
    if case.get('prefix'):
        prefix = read(ROOT / case['prefix'])['decisions']
        seed = {'operation': 'controlled_original_prefix_real_model_tail', 'not_fresh_autonomous_run': True,
                'original_query_ref': case['original_query_ref'], 'prefix_decisions': len(prefix),
                'original_failed_decision_ordinal': len(prefix) + 1, 'gold_or_review_feedback_supplied': False,
                'original_max_steps_preserved': config['request']['limits']['max_steps'],
                'prefix_sha256': digest((ROOT / case['prefix']).read_bytes())}

        class ControlledCoordinator(CompanyDataCoordinator):
            @staticmethod
            def _planner(model_config, output, credential_root, *, role='planner', purpose='question_answer'):
                inner = CompanyDataCoordinator._planner(model_config, output, credential_root, role=role, purpose=purpose)
                if output.parent.parent.name == 'attempt-01':
                    # Both managed adapters must declare the mixed query origin.
                    # The worker still executes every decision through its real adapter.
                    return PrefixThenModel(inner, prefix if role == 'planner' else [],
                                           {**seed, 'role': role, 'prefix_decisions': len(prefix) if role == 'planner' else 0})
                return inner

        with patch.object(cycle, 'CompanyDataCoordinator', ControlledCoordinator):
            result = await cycle.run_retrieval_cycle(config, target / 'run-r1')
    else:
        result = await cycle.run_retrieval_cycle(config, target / 'run-r1')
    receipt = {'case_id': case_id, 'operation': case['operation'], 'result': result,
               'strict_load': 'not_passed', 'ledger_before': before, 'ledger_after': ledger(config)}
    if result['status'] == 'reviewed_data_ready':
        ref = result['final_review_ref']
        loaded = handoff.load_reviewed_data(ref['path'], expected_scope=config['request']['scope'],
            expected_review_manifest_sha256=ref['manifest_sha256'])
        receipt.update(strict_load='passed', handoff_id=loaded['handoff_id'])
    write_new(target / 'execution-receipt.v1.json', receipt)
    check_budget(config)
    verify_freeze()
    print(json.dumps({'case': case_id, 'status': result['status'], 'strict_load': receipt['strict_load'],
                      'new_requests': receipt['ledger_after']['requests'] - before['requests'],
                      'new_known_usd': str(Decimal(receipt['ledger_after']['known_usd']) - Decimal(before['known_usd']))}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    asyncio.run(execute(parser.parse_args().case))
