"""Prepare nine explicit fresh configs and evaluation policy, without any API."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.retrieval_cycle import validate
from runtime_helpers import ROOT, EXP, OUTPUT, read, ledger


def prepare():
    assert not (EXP / 'execution-matrix.v1.json').exists()
    prior = ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1'
    for source, destination in ((prior / 'question.v1.json', EXP / 'question.v1.json'),
                                (prior / 'gradients.v1.json', EXP / 'gradients.v1.json'),
                                (prior / 'evaluation-only/standard.v1.json', EXP / 'evaluation-only/content-standard.v1.json')):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as target:
            target.write(source.read_bytes())
    runs = []
    for round_number, tiers in ((1, ('S1', 'S2', 'S3')), (2, ('S2', 'S3', 'S1')), (3, ('S3', 'S1', 'S2'))):
        for tier in tiers:
            base = OUTPUT / f'R{round_number}' / tier
            config = deepcopy(read(ROOT / f'output/e6-repeatability-20261010-r1/R1/{tier}/runtime-config.v1.json'))
            config['workspace'] = str(base / 'runtime-workspace')
            assert 'initial_query_ref' not in config and 'review_feedback' not in config['request']
            validate(config, base / 'run-r1')
            config_path = base / 'runtime-config.v1.json'
            write_new(config_path, config)
            runs.append({'slot_id': f'R{round_number}-{tier}', 'round': round_number, 'tier_id': tier,
                         'config': str(config_path.relative_to(ROOT)), 'run': str((base / 'run-r1').relative_to(ROOT))})
    write_new(EXP / 'execution-matrix.v1.json', {'schema_version': 'e6-repeatability-matrix-v2',
              'planned_runs': 9, 'fresh_runs_per_tier': 3, 'runs': runs})
    policy = {'schema_version': 'e6-repeatability-evaluation-policy-v2',
              'frozen_before_model_execution': True, 'priority': ['effect', 'success_rate', 'cost'],
              'planned_runs': 9, 'repeats_per_tier': 3, 'content_standard': 'content-standard.v1.json',
              'required_content_axes': ['mandatory_4_of_4', 'scope_truth_provenance', 'focus', 'actual_full_body_model_exposure'],
              'full_success': 'independent_content_pass AND double_review_pass AND strict_real_load_pass',
              'no_recovery': 'full_success AND one_retrieval_attempt AND no rejected/error tools, decision format repairs, review protocol repairs, review-driven retakes, network failures or retries',
              'success_denominators': {'planned': 9, 'completed': 'report a/b and b/9; never replace samples or hide failures'},
              'first_and_final_content_separate': True, 'cost_can_offset_missing_or_wrong_content': False,
              'cost_concentration_is_content_gate': False,
              'cost_observation_reference': {'n': 3, 'cv_max': 0.2, 'max_min_max': 1.5, 'historical_reference_only': True},
              'task_warning_usd': '3', 'shared_budget_usd': '13', 'shared_request_cap': 1000,
              'expected_task_usd': ['1.5', '2.5'], 'allow_historical_unknown_only': True,
              'first_sample_release': 'Codex independent content and cost/integrity inspection before remaining eight',
              'content_failure_stops_remaining': False, 'statistical_stability_from_three_successes': False,
              'created_at': datetime.now(timezone.utc).isoformat()}
    write_new(EXP / 'evaluation-only/evaluation-policy.v1.json', policy)
    snapshot = ledger(config)
    assert snapshot['requests'] == 525 and snapshot['known_usd'] == '6.4895007'
    assert len(snapshot['unsettled_ids']) == 2
    write_new(OUTPUT / 'ledger-before.v1.json', snapshot)
    print(json.dumps({'configs_validated': 9, 'api_calls': 0, 'ledger_requests': snapshot['requests']}))


if __name__ == '__main__':
    prepare()
