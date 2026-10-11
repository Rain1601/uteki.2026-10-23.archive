"""Freeze configs and old decision prefixes after a zero-API binding preflight."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import run_real_validation as execution
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.infrastructure.research_data.financial_records import digest

ROOT, EXP, OUTPUT = execution.ROOT, execution.EXPERIMENT, execution.OUTPUT
read = execution.read


def preserve(path, value):
    if path.exists():
        assert read(path) == value, str(path)
    else:
        write_new(path, value)


class PrefixProbe:
    plan_origin = 'scripted_fixture'

    def __init__(self, decisions):
        self.decisions, self.ordinal, self.choice_packet = decisions, 0, None

    async def decide(self, packet, **kwargs):
        self.ordinal += 1
        if self.ordinal <= len(self.decisions):
            return AutonomousDecision.model_validate(self.decisions[self.ordinal - 1])
        if self.choice_packet is None:
            self.choice_packet = deepcopy(packet)
        return AutonomousDecision(action='finish', reason='Zero API binding preflight; no model tail executed.')


async def prepare():
    assert not (EXP / 'evaluation-only/execution-freeze.v1.json').exists()
    cases = []
    for rep, count in (('R2', 15), ('R3', 10)):
        case_id = f'replay-{rep}-S1'
        old = ROOT / f'output/e6-repeatability-20261010-r1/{rep}/S1/run-r1'
        cfg = read(old / 'config.json')
        cfg['workspace'] = str(OUTPUT / case_id / 'runtime-workspace')
        config_path = EXP / f'config/{case_id}.v1.json'
        preserve(config_path, cfg)
        query = old / 'attempt-01/data-query/query'
        decisions = [read(query / f'turn-{n:03d}/decision.json') for n in range(1, count + 1)]
        prefix_path = EXP / f'evaluation-only/{case_id}-prefix.v1.json'
        preserve(prefix_path, {'model_calls': 0, 'original_query_ref': str(query.relative_to(ROOT)),
                               'decisions': decisions})
        probe = PrefixProbe(decisions)
        coordinator = CompanyDataCoordinator(OUTPUT / 'zero-api-preflight-v2' / case_id / 'workspace')
        target = OUTPUT / 'zero-api-preflight-v2' / case_id / 'data-query'
        before = execution.ledger(cfg)
        result = await coordinator.query(cfg['request'], output=target, planner=probe)
        assert execution.ledger(cfg) == before
        assert probe.choice_packet is not None and probe.ordinal >= count + 1
        # Original actions, including rejected actions, retain their original result.
        for n in range(1, count + 1):
            old_feedback = read(query / f'turn-{n:03d}/feedback.json')
            new_feedback = read(target / f'query/turn-{n:03d}/feedback.json')
            assert old_feedback['status'] == new_feedback['status'], (case_id, n)
        old_input = read(query / f'turn-{count + 1:03d}/input.json')
        assert probe.choice_packet['record_selection'] == old_input['record_selection']
        assert digest(probe.choice_packet['retained_body']) == digest(old_input['retained_body'])
        catalog = probe.choice_packet['record_candidate_index']['value']
        assert len(catalog['candidates']) == 18
        assert any(row['evidence_id'] == 'ev-230effd83877e641d55c9cd2'
                   and row['citations'][0]['block_id'] == 'block-000753-53762a3b'
                   for row in catalog['candidates'])
        assert probe.choice_packet['steps_remaining'] == old_input['steps_remaining']
        write_new(EXP / f'evaluation-only/{case_id}-preflight.v1.json',
                  {'case_id': case_id, 'api_calls': 0, 'prefix_decisions': count,
                   'feedback_statuses_same': True, 'selected_records_same': True,
                   'retained_body_same': True, 'steps_remaining_same': True,
                   'all_18_candidates_visible': True, 'query_result': result,
                   'first_real_tail_packet_sha256': digest(probe.choice_packet)})
        cases.append({'id': case_id, 'config': str(config_path.relative_to(ROOT)),
                      'prefix': str(prefix_path.relative_to(ROOT)),
                      'original_query_ref': str(query.relative_to(ROOT)),
                      'operation': 'controlled_original_prefix_real_model_tail'})
    cfg = read(EXP / 'config/replay-R2-S1.v1.json')
    cfg['workspace'] = str(OUTPUT / 'fresh-S1/runtime-workspace')
    fresh = EXP / 'config/fresh-S1.v1.json'
    write_new(fresh, cfg)
    cases.append({'id': 'fresh-S1', 'config': str(fresh.relative_to(ROOT)),
                  'operation': 'fresh_end_to_end_autonomous_agent'})
    write_new(EXP / 'execution-matrix.v1.json', {'cases': cases, 'fixed_order': True})
    write_new(OUTPUT / 'ledger-before.v1.json', execution.ledger(cfg))
    paths = [p for base in (ROOT / 'src', ROOT / 'skills', EXP,
                            ROOT / 'output/e6-material-scale-20261010-r1/S1/preparation/dataset')
             for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts
             and p.suffix not in {'.pyc', '.sqlite', '.sqlite-wal', '.sqlite-shm'}]
    paths += [ROOT / 'tests/unit/test_record_selection_navigation.py',
              ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/standard.v1.json',
              ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v1/evaluation-only/standard.v1.json',
              OUTPUT / 'ledger-before.v1.json']
    sealed = {}
    for rep in ('R2', 'R3'):
        path = ROOT / f'output/e6-repeatability-20261010-r1/{rep}/S1/run-r1'
        execution.cycle._verify_manifest(path)
        sealed[str(path.relative_to(ROOT))] = digest((path / 'manifest.json').read_bytes())
    freeze = {'schema_version': 'e6-r2-execution-freeze-v1', 'api_calls_before_freeze': 0,
              'files': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths},
              'sealed_refs': sealed, 'task_warning_usd': '3', 'shared_hard_limit_usd': '13'}
    write_new(EXP / 'evaluation-only/execution-freeze.v1.json', freeze)
    execution.verify_freeze()
    print(json.dumps({'freeze_files': len(freeze['files']), 'cases': len(cases), 'api_calls': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(prepare())
