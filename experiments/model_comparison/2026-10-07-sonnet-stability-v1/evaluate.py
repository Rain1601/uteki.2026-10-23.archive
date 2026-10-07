"""Offline review of frozen baseline and additional Sonnet trials; no model calls."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

from uteki.agents.runtime.model_configuration import validate_configuration_snapshot

HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / '2026-10-07-reproducibility-pilot-v1'
HASH_FIELDS = ('request_body_sha256', 'configuration_sha256', 'raw_sha256', 'json_sha256',
               'order_normalized_sha256', 'fact_values_sha256')
INPUT_HASHES = ('packet_sha256', 'manifest_sha256', 'system_sha256', 'messages_sha256')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular recorded artifact required')
    return json.loads(path.read_bytes())


def evaluator():
    spec = importlib.util.spec_from_file_location('frozen_sonnet_pilot_evaluation', BASELINE / 'evaluate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_inputs(folder, plan, prior):
    """Pin the selected task, reference, rubric and profile, without changing them."""
    tasks, profiles = {}, {}
    helper = prior.preparation.frozen_helpers()
    for task in plan['tasks']:
        prepared = folder / task['prepared']
        packet, messages, metadata = helper.load_prepared(prepared)
        if any(metadata[key] != task[key] for key in INPUT_HASHES):
            raise ValueError('Task input identity changed')
        # The frozen evaluator resolves these two files relative to the prepared task.
        for key, name in (('reference', 'reference-review.json'), ('rubric', 'rubric.json')):
            path = folder / task[key]
            if path.resolve() != (prepared.parent / name).resolve():
                raise ValueError('Scoring file does not belong to selected task')
            prior.preparation.pinned(path, task[key + '_sha256'])
        if packet['task']['id'] != task['id'] or task['id'] in tasks:
            raise ValueError('Ambiguous task identity')
        tasks[task['id']] = (task, prepared.parent, messages)
    for profile in plan['profiles']:
        raw = prior.preparation.pinned(folder / profile['path'], profile['sha256'])
        value = json.loads(raw)
        if (value['id'] != profile['id'] or value['provider'] != profile['provider']
                or value['model'] != profile['model'] or profile['id'] in profiles
                or (value['provider'], value['model'], value['api_format'])
                != ('aihubmix', 'claude-sonnet-5-5', 'anthropic_messages')):
            raise ValueError('Unexpected Sonnet profile identity')
        profiles[profile['id']] = (profile, value)
    return tasks, profiles


def inspect_trial(folder, case, cohort, tasks, profiles, prior):
    trial = {key: case[key] for key in ('id', 'ordinal', 'task_id', 'profile_id', 'repeat')}
    trial.update(cohort=cohort, output_path=case['output_path'], status='not_recorded',
        automated_pass=None, overall_task_pass='pending_output',
        blind_qualitative_review='not_performed', fingerprints={})
    output = folder / case['output_path']
    if not (output / 'summary.json').exists():
        trial['status'] = 'incomplete_record' if output.exists() else 'not_recorded'
        return trial
    try:
        task, task_dir, messages = tasks[case['task_id']]
        profile, settings = profiles[case['profile_id']]
        summary = read(output / 'summary.json')
        trial.update(status=summary.get('status', 'invalid_trial_record'),
            started_at=summary.get('started_at'), ended_at=summary.get('ended_at'),
            error_type=summary.get('error_type'), automated_pass=False, overall_task_pass=False)
        arms = summary.get('arms')
        if not isinstance(arms, list) or len(arms) != 1 or not isinstance(arms[0], dict):
            trial['record_issue'] = 'No single completed call record; original status retained.'
            return trial
        call = arms[0]
        trial['receipt'] = {key: call.get(key) for key in ('status', 'provider', 'requested_model',
            'returned_model', 'request_id', 'response_id', 'http_status', 'system_fingerprint',
            'provider_finish_reason', 'finish_reason', 'error_type', 'started_at', 'ended_at',
            'reservation_id', 'reserved_usd', 'usage_source', 'usage_presence')}
        trial.update(elapsed_seconds=call.get('elapsed_seconds'), raw_usage=call.get('raw_usage'),
            estimated_usd=call.get('estimated_usd'), actual_billed_usd=None,
            visible_response_received=call.get('status') in ('received', 'usage_unknown'))
        provenance = call.get('execution_provenance', {})
        trial['execution_provenance'] = provenance
        wire = read(output / 'http-request.json')
        body_hash = digest(wire['body'])
        snapshot = validate_configuration_snapshot(read(output / 'configuration.json'))
        start = read(output / '01-model/start.json')
        response = read(output / '01-model/response-metadata.json')
        expected_body = {'model': settings['model'], 'system': messages[0]['content'],
            'messages': messages[1:], 'thinking': {'type': settings['thinking']},
            'output_config': {'effort': settings['reasoning_effort']},
            'max_tokens': settings['max_tokens'], 'stream': settings['stream']}
        identity_match = (call.get('profile_sha256') == profile['sha256']
            and call.get('provider') == profile['provider'] and call.get('requested_model') == profile['model']
            and all(call.get('input', {}).get(key) == task[key] for key in INPUT_HASHES)
            and wire.get('endpoint') == 'https://aihubmix.com/v1/messages' and wire['body'] == expected_body
            and body_hash == provenance.get('request_body_sha256')
            and all(record.get('configuration_snapshot') == snapshot for record in (call, start, response)))
        trial['configuration_and_input_match'] = identity_match
        trial['fingerprints'].update(request_body_sha256=body_hash, configuration_sha256=snapshot['sha256'])
        visible = output / '01-model/visible-output.txt'
        if visible.is_symlink() or not visible.is_file():
            trial['record_issue'] = 'No regular visible response artifact; no fabricated output hashes.'
            return trial
        content = visible.read_text()
        scoring = prior.evaluate(task_dir, content, finish_reason=call.get('finish_reason'))
        trial['evaluation'] = scoring
        # An empty failure placeholder is not an observed model response.
        if content and trial['visible_response_received']:
            trial['fingerprints'].update(scoring['fingerprints'])
        trial['automated_pass'] = bool(scoring['automated_pass'] and identity_match
                                      and trial['status'] == 'completed')
        trial['overall_task_pass'] = 'pending_blind_review' if trial['automated_pass'] else False
    except (KeyError, TypeError, ValueError, OSError) as error:
        trial.update(record_issue='Recorded artifacts could not be verified.', record_error_type=type(error).__name__,
                     automated_pass=False, overall_task_pass=False, configuration_and_input_match=False)
    return trial


def compare(task_id, profile_id, group):
    recorded = [trial for trial in group if trial['status'] != 'not_recorded']
    valid = all(trial.get('configuration_and_input_match') and trial['status'] == 'completed'
        and trial.get('evaluation', {}).get('contract', {}).get('status') == 'structure_and_citations_valid'
        for trial in group)
    hashes = {}
    for field in HASH_FIELDS:
        values = [trial['fingerprints'][field] for trial in group if field in trial['fingerprints']]
        hashes[field] = {'available_count': len(values), 'missing_count': len(group) - len(values),
            'unique_count': len(set(values)),
            'all_planned_agree': len(set(values)) == 1 if valid and len(values) == len(group) else None}
    costs = [Decimal(trial['estimated_usd']) for trial in recorded if trial.get('estimated_usd') is not None]
    timing = [trial['elapsed_seconds'] for trial in recorded if type(trial.get('elapsed_seconds')) in (int, float)]
    return {'task_id': task_id, 'profile_id': profile_id, 'planned_repeats': len(group),
        'baseline_trials': sum(trial['cohort'] == 'baseline' for trial in group),
        'additional_trials': sum(trial['cohort'] == 'additional' for trial in group),
        'recorded_trials': len(recorded), 'visible_responses': sum(bool(t.get('visible_response_received')) for t in group),
        'automated_pass_count': sum(t.get('automated_pass') is True for t in group),
        'all_planned_completed_and_contract_valid': bool(group) and valid, 'hashes': hashes,
        'elapsed_seconds_range': [min(timing), max(timing)] if timing else None,
        'known_estimated_usd': str(sum(costs, Decimal(0))), 'unknown_cost_trials': len(recorded) - len(costs),
        'interpretation': 'Hash agreement measures repeat agreement, not correctness or deterministic provider behavior.'}


def run(folder=HERE):
    folder = Path(folder)
    plan = read(folder / 'plan.json')
    prior = evaluator()
    tasks, profiles = inspect_inputs(folder, plan, prior)
    trials, seen = [], set()
    for cohort, cases in (('baseline', plan['baseline_cases']), ('additional', plan['call_order'])):
        for case in cases:
            if case['id'] in seen or case['task_id'] not in tasks or case['profile_id'] not in profiles:
                raise ValueError('Invalid or duplicate selected case')
            seen.add(case['id'])
            trials.append(inspect_trial(folder, case, cohort, tasks, profiles, prior))
    comparisons = [compare(task_id, profile_id, [trial for trial in trials
        if trial['task_id'] == task_id and trial['profile_id'] == profile_id])
        for task_id in tasks for profile_id in profiles]
    return {'schema_version': 'sonnet-stability-program-review-v1', 'trials': trials,
        'task_comparisons': comparisons, 'blind_qualitative_review': 'not_performed',
        'evaluator_provenance': {'current_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'baseline_evaluator_sha256': hashlib.sha256((BASELINE / 'evaluate.py').read_bytes()).hexdigest()},
        'limits': ['The original scoring rubric is unchanged. Its percentage tolerance is 0.02 percentage points, '
            'but the model task did not prescribe decimal places; a rounded answer can fail this numeric gate.',
            'Program scoring is not independent human Gold or blind qualitative review.',
            'Two selected tasks on one issuer excerpt do not establish general model reliability.',
            'Public-price costs are estimates, not account bills; missing or failed trials remain visible.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=HERE)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run(args.folder)
    if args.output:
        with args.output.open('x', encoding='utf-8') as file:
            json.dump(result, file, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
