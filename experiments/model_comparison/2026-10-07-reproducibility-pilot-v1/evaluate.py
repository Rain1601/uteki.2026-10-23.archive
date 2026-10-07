"""Offline program checks and repeat fingerprints; qualitative review stays pending."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unicodedata

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pilot_preparation', HERE/'prepare_benchmark.py')
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


def text(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip() if isinstance(value, str) else value


def numeric(value):
    if type(value) not in (str, int, float):
        raise ValueError('Expected a finite number')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Expected a finite number') from None
    if not number.is_finite():
        raise ValueError('Expected a finite number')
    return format(number.normalize(), 'f') if number else '0'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def unit(value):
    value = text(value)
    if not isinstance(value, str):
        return value
    aliases = {'usd millions', 'usd million', 'million usd', 'millions usd', 'million', 'millions', '百万美元', '百万'}
    return 'USD millions' if value.casefold() in aliases else value


def normalized_fact(fact, *, include_quote=True):
    if not isinstance(fact, dict):
        return fact
    result = {key: text(value) for key, value in fact.items() if include_quote or key != 'quote'}
    try:
        result['value'] = numeric(result.get('value'))
    except ValueError:
        pass
    if isinstance(result.get('metric'), str):
        result['metric'] = result['metric'].casefold()
    result['unit'] = unit(result.get('unit'))
    return result


def fingerprints(content, parsed):
    result = {'raw_sha256': hashlib.sha256(content.encode()).hexdigest()}
    if parsed is None:
        return result
    result['json_sha256'] = hashlib.sha256(canonical(parsed).encode()).hexdigest()
    if not isinstance(parsed, dict) or any(not isinstance(parsed.get(key), list) for key in ('facts','analysis','gaps')):
        return result
    facts = sorted((normalized_fact(fact) for fact in parsed['facts']), key=canonical)
    claims = []
    for claim in parsed['analysis']:
        if isinstance(claim, dict):
            normalized = {key: text(value) for key, value in claim.items()}
            if isinstance(normalized.get('block_ids'), list):
                normalized['block_ids'] = sorted(normalized['block_ids'], key=canonical)
            claims.append(normalized)
        else:
            claims.append(claim)
    normalized = {'facts': facts, 'analysis': sorted(claims, key=canonical),
                  'gaps': sorted((text(gap) for gap in parsed['gaps']), key=canonical)}
    result['order_normalized_sha256'] = hashlib.sha256(canonical(normalized).encode()).hexdigest()
    fact_values = sorted((normalized_fact(fact, include_quote=False) for fact in parsed['facts']), key=canonical)
    result['fact_values_sha256'] = hashlib.sha256(canonical(fact_values).encode()).hexdigest()
    return result


def evaluate(task_dir, content, *, finish_reason):
    task_dir = Path(task_dir)
    helper = preparation.frozen_helpers()
    packet, _, metadata = helper.load_prepared(task_dir/'prepared')
    manifest = json.loads((task_dir/'prepared/manifest.json').read_bytes())
    reference = json.loads(preparation.pinned(task_dir/'reference-review.json', manifest['reference_sha256']))
    rubric = json.loads(preparation.pinned(task_dir/'rubric.json', manifest['rubric_sha256']))
    contract, parsed = helper.validate_output(content, packet, finish_reason)
    result = {'task_id': packet['task']['id'], 'input_packet_sha256': metadata['packet_sha256'],
        'reference_sha256': manifest['reference_sha256'], 'rubric_sha256': manifest['rubric_sha256'],
        'reference_status': reference['review_status'], 'contract': contract,
        'fingerprints': fingerprints(content, parsed), 'automated_pass': False,
        'blind_qualitative_review': 'not_performed', 'overall_task_pass': 'pending_blind_review',
        'interpretation': 'Program checks do not establish that every analysis claim is supported; matching repeat hashes are agreement, not correctness.'}
    if not isinstance(parsed, dict) or any(not isinstance(parsed.get(key), list) for key in ('facts','analysis','gaps')):
        result['overall_task_pass'] = False
        return result
    expected = {(row['metric'], row['period']): normalized_fact(row) for row in reference['expected_records']}
    counts = Counter()
    incorrect, extra = [], []
    correct = set()
    for index, row in enumerate(parsed['facts']):
        if not isinstance(row, dict):
            incorrect.append({'index': index, 'fields': ['shape']})
            continue
        normalized = normalized_fact(row)
        identity = (normalized.get('metric'), normalized.get('period'))
        if not all(isinstance(value, str) for value in identity):
            incorrect.append({'index': index, 'fields': ['identity']})
            continue
        counts[identity] += 1
        if identity not in expected:
            extra.append({'index': index, 'metric': identity[0], 'period': identity[1]})
            continue
        # Quote support is independently checked against original block/row by the frozen validator.
        fields = ['metric','period','period_end','value','unit','currency','block_id','row','column']
        mismatches = [key for key in fields if normalized.get(key) != expected[identity].get(key)]
        if mismatches:
            incorrect.append({'index': index, 'fields': mismatches})
        else:
            correct.add(identity)
    missing = [list(identity) for identity in expected if counts[identity] == 0]
    duplicates = [list(identity) for identity, count in counts.items() if count > 1]
    result['facts'] = {'expected': len(expected), 'returned': len(parsed['facts']), 'correct_distinct': len(correct),
        'incorrect': incorrect, 'missing': missing, 'extra': extra, 'duplicates': duplicates}
    gates = rubric['automated_gates']
    claims = [claim['claim'] for claim in parsed['analysis'] if isinstance(claim, dict) and isinstance(claim.get('claim'),str)]
    han_count = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', ''.join(claims)))
    distinct_gaps = len({text(gap) for gap in parsed['gaps'] if isinstance(gap,str) and text(gap)})
    result['limits'] = {'analysis_han_characters': han_count, 'maximum': gates['maximum_analysis_han_characters'],
                        'distinct_gaps': distinct_gaps, 'required_gaps': gates['minimum_distinct_gaps']}
    numeric_check = {'required': gates['change_formula_marker_required'], 'pass': True}
    if numeric_check['required']:
        normalized_claims = [text(claim).replace('−','-') for claim in claims]
        pattern = r'经营现金流同比变化\s*:\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*USD\s+millions\s*;\s*变化率\s*:\s*([+-]?\d+(?:\.\d+)?)\s*%\s*;\s*公式\s*:\s*(.+)'
        matches = [match for claim in normalized_claims for match in re.finditer(pattern, claim)]
        numeric_check['matched_markers'] = len(matches)
        numeric_check['pass'] = False
        if len(matches) == 1:
            delta = Decimal(matches[0].group(1).replace(',',''))
            percent = Decimal(matches[0].group(2))
            derived = reference['derived']
            numeric_check.update(reported_amount=str(delta), reported_percent=str(percent),
                amount_matches=abs(delta-Decimal(derived['operating_cash_flow_delta_millions'])) <= Decimal(gates['change_amount_tolerance_usd_millions']),
                percent_matches=abs(percent-Decimal(derived['operating_cash_flow_change_percent'])) <= Decimal(gates['change_percent_tolerance_percentage_points']),
                formula_text_present=bool(matches[0].group(3).strip()))
            numeric_check['pass'] = all(numeric_check[key] for key in ('amount_matches','percent_matches','formula_text_present'))
            numeric_check['formula_semantics'] = 'Requires blind review; the program verifies result numbers, not arbitrary free-text arithmetic.'
    result['change_numbers'] = numeric_check
    result['automated_pass'] = (contract['status'] == 'structure_and_citations_valid'
        and len(correct) == len(expected) and len(parsed['facts']) == len(expected)
        and not incorrect and not missing and not extra and not duplicates
        and distinct_gaps >= gates['minimum_distinct_gaps']
        and han_count <= gates['maximum_analysis_han_characters'] and numeric_check['pass'])
    if not result['automated_pass']:
        result['overall_task_pass'] = False
    return result


def evaluate_benchmark(folder=HERE):
    """Inspect saved trials only. Missing repeats stay pending; no output is generated."""
    folder = Path(folder)
    verification = preparation.verify_benchmark(folder)
    plan = json.loads((folder/'plan.json').read_bytes())
    tasks = {task['id']: task for task in plan['tasks']}
    profiles = {profile['id']: profile for profile in plan['profiles']}
    trials = []
    for case in plan['call_order']:
        task, profile = tasks[case['task_id']], profiles[case['profile_id']]
        output = folder/case['output_path']
        result = {key: case[key] for key in ('id','ordinal','task_id','profile_id','repeat')}
        summary_path = output/'summary.json'
        if not summary_path.is_file():
            result.update(status='not_recorded', automated_pass=None,
                          overall_task_pass='pending_output', blind_qualitative_review='not_performed')
            trials.append(result)
            continue
        summary = json.loads(summary_path.read_bytes())
        arms = summary.get('arms')
        if not isinstance(arms,list) or len(arms)!=1 or not isinstance(arms[0],dict):
            result.update(status='invalid_trial_record', automated_pass=False, overall_task_pass=False)
            trials.append(result)
            continue
        call = arms[0]
        matches = (call.get('profile_sha256') == profile['sha256']
            and call.get('provider') == profile['provider'] and call.get('requested_model') == profile['model']
            and all(call.get('input',{}).get(key)==task[key] for key in
                    ('packet_sha256','manifest_sha256','system_sha256','messages_sha256')))
        result.update(status=summary.get('status'), configuration_and_input_match=matches,
            elapsed_seconds=call.get('elapsed_seconds'), raw_usage=call.get('raw_usage'),
            estimated_usd=call.get('estimated_usd'), actual_billed_usd=None,
            visible_response_received=call.get('status') in ('received','usage_unknown'))
        visible = output/'01-model/visible-output.txt'
        if visible.is_file():
            scoring = evaluate(folder/'tasks'/case['task_id'], visible.read_text(), finish_reason=call.get('finish_reason'))
            result['evaluation'] = scoring
            result['automated_pass'] = bool(scoring['automated_pass'] and matches)
            result['overall_task_pass'] = 'pending_blind_review' if result['automated_pass'] else False
        else:
            result.update(automated_pass=False, overall_task_pass=False,
                          evaluation={'reason':'No visible response artifact; no fabricated output or fact hash.'})
        trials.append(result)
    comparisons = []
    for task_id in tasks:
        for profile_id in profiles:
            group = [trial for trial in trials if trial['task_id']==task_id and trial['profile_id']==profile_id]
            recorded = [trial for trial in group if trial['status']!='not_recorded']
            hashes = [trial.get('evaluation',{}).get('fingerprints',{}) for trial in group]
            comparable = (len(group)==2 and all(trial.get('evaluation',{}).get('contract',{}).get('status')
                == 'structure_and_citations_valid' and trial.get('configuration_and_input_match') for trial in group))
            timing = [trial['elapsed_seconds'] for trial in recorded if type(trial.get('elapsed_seconds')) in (int,float)]
            costs = [Decimal(trial['estimated_usd']) for trial in recorded if trial.get('estimated_usd') is not None]
            comparisons.append({'task_id':task_id, 'profile_id':profile_id, 'planned_repeats':len(group),
                'recorded_trials':len(recorded), 'visible_responses':sum(bool(trial.get('visible_response_received')) for trial in recorded),
                'automated_pass_count':sum(trial.get('automated_pass') is True for trial in recorded),
                'both_repeats_available_and_contract_valid':comparable,
                'exact_output_agreement':hashes[0].get('raw_sha256')==hashes[1].get('raw_sha256') if comparable else None,
                'order_normalized_agreement':hashes[0].get('order_normalized_sha256')==hashes[1].get('order_normalized_sha256') if comparable else None,
                'fact_value_agreement':hashes[0].get('fact_values_sha256')==hashes[1].get('fact_values_sha256') if comparable else None,
                'elapsed_seconds_range':[min(timing),max(timing)] if timing else None,
                'known_estimated_usd':str(sum(costs,Decimal(0))), 'unknown_cost_trials':len(recorded)-len(costs),
                'blind_qualitative_review':'not_performed', 'interpretation':'Agreement does not imply correctness; pending/failed output is not counted as stable.'})
    return {'schema_version':'reproducibility-pilot-program-review-v1', 'verification':verification,
            'trials':trials, 'repeat_comparisons':comparisons,
            'blind_qualitative_review':'not_performed', 'universal_model_rank':None,
            'limits':plan['fairness_limits']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--task', type=Path)
    mode.add_argument('--benchmark', type=Path)
    parser.add_argument('--response', type=Path)
    parser.add_argument('--finish-reason')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.benchmark:
        result = evaluate_benchmark(args.benchmark)
    else:
        if not args.response or not args.finish_reason:
            parser.error('--task requires --response and --finish-reason')
        result = evaluate(args.task, args.response.read_text(), finish_reason=args.finish_reason)
    if args.output:
        with args.output.open('x', encoding='utf-8') as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
