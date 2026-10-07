"""Offline preparation and verification for one named, source-pinned small pilot.

No execution loop, credentials, network, or model imports. Expected answers are
derived from frozen source cells and inline XBRL and written outside model packets.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PRIOR = ROOT / 'experiments/model_comparison/2026-10-06-sonnet-deepseek-small-v1'
PACKET_SHA256 = '7bcdfbf11422bf8eaf7bf452f63009302a29a749632027835bbc401b1f610e7e'
RUNNER_SHA256 = 'ca7c5ad62eecda125acef97cc53aa7c91443908fe90098ff23eb5485113a4d62'
DATASET = ROOT / 'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/amd-fy2023-cash-flow-main-agent-v2/query/turn-003/financial_extract/extraction-01/dataset'
SOURCE_ID = 'source-291485b98a75d8cfabe47571'
TABLE_ID = 'block-000686-a6e8806b'
SOURCE_FILES = {
    'raw': {'path': f'raw/{SOURCE_ID}.html', 'sha256': '47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808'},
    'index': {'path': f'indexes/{SOURCE_ID}/index.json', 'sha256': '65d205ba587928e595e72a858215d46f561d0e4807fa9299ec24987b4c0ef864'},
    'blocks': {'path': f'indexes/{SOURCE_ID}/blocks.jsonl', 'sha256': 'c60436e60d4aad9cd08aeeab1136d975d84963e4381f3106598686c2d44b14cd'},
}
PROFILES = {'S': 'sonnet55-high-8k-repro', 'D': 'deepseek-low-16k-repro'}
TASKS = ('cashflow-facts', 'cashflow-change')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def pinned(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Pinned inputs must be regular files')
    value = path.read_bytes()
    if digest(value) != expected:
        raise ValueError('Pinned source hash mismatch')
    return value


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as file:
        file.write(encoded(value))


def frozen_helpers():
    path = PRIOR / 'run_comparison.py'
    pinned(path, RUNNER_SHA256)
    spec = importlib.util.spec_from_file_location('pilot_frozen_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def number(text):
    text = text.strip().replace(',', '')
    return -Decimal(text[1:-1]) if text.startswith('(') and text.endswith(')') else Decimal(text)


def project_table(block):
    rows = defaultdict(list)
    for cell in block['table']['cells']:
        if cell['text'].strip():
            column, span = cell['column'], cell['colspan']
            marker = f'c{column}' if span == 1 else f'c{column}..{column + span - 1}'
            rows[cell['row']].append(f"{marker}: {cell['text']}")
    return '\n'.join(f"r{row}: " + ' | '.join(cells) for row, cells in sorted(rows.items()))


def verify_source():
    packet = json.loads(pinned(PRIOR / 'prepared/packet.json', PACKET_SHA256))
    raw = {name: pinned(DATASET / ref['path'], ref['sha256']) for name, ref in SOURCE_FILES.items()}
    blocks = {b['block_id']: b for b in map(json.loads, raw['blocks'].decode().splitlines())}
    for selected in packet['blocks']:
        original = blocks[selected['block_id']]
        if digest(original['text'].encode()) != original['text_hash'] or selected['source_text_hash'] != original['text_hash']:
            raise ValueError('Source block identity mismatch')
        expected = project_table(original) if original['type'] == 'table' else original['text']
        if selected['text'] != expected or selected['text_hash'] != digest(expected.encode()):
            raise ValueError('Packet is not an exact mechanical source projection')
    tree = html.fromstring(raw['raw'])
    table = blocks[TABLE_ID]
    if len(tree.xpath(table['dom_path'])) != 1:
        raise ValueError('Original table location is ambiguous')
    def one(identifier):
        found = tree.xpath('//*[@id=$identifier]', identifier=identifier)
        if len(found) != 1:
            raise ValueError('Inline fact/context identity is ambiguous')
        return found[0]
    if one('usd').text_content().strip() != 'iso4217:USD':
        raise ValueError('Unexpected reporting currency')
    cells = {(c['row'], c['column']): c for c in table['table']['cells']}
    periods = {item['fiscal_year']: item for item in packet['scope']['comparison_periods']}
    identities = [('operating_cash_flow', 25, 'f-313', 'f-314', 'NetCashProvidedByUsedInOperatingActivities'),
                  ('investing_cash_flow', 34, 'f-337', 'f-338', 'NetCashProvidedByUsedInInvestingActivities'),
                  ('financing_cash_flow', 42, 'f-358', 'f-359', 'NetCashProvidedByUsedInFinancingActivities')]
    records, inline_checks = [], []
    for metric, row, current_id, prior_id, concept in identities:
        for year, column, fact_id in ((2023, 3, current_id), (2022, 9, prior_id)):
            inline = one(fact_id)
            context = one(inline.attrib['contextref'])
            context_values = {node.tag.split(':')[-1]: node.text for node in context.iter() if node.text}
            if (context_values.get('identifier') != '0000002488'
                    or context_values.get('startdate') != periods[year]['period_start']
                    or context_values.get('enddate') != periods[year]['period_end']
                    or inline.attrib.get('unitref') != 'usd' or inline.attrib.get('scale') != '6'
                    or inline.attrib.get('name') != 'us-gaap:' + concept):
                raise ValueError('Inline fact scope, unit, or concept mismatch')
            value = number(inline.text_content()) * (-1 if inline.attrib.get('sign') == '-' else 1)
            cell = cells[(row, column)]
            if number(cell['text']) != value or cell['colspan'] != 2:
                raise ValueError('Indexed amount disagrees with raw inline fact')
            quote = next(line for line in project_table(table).splitlines() if line.startswith(f'r{row}: '))
            records.append({'metric': metric, 'period': str(year), 'period_end': periods[year]['period_end'],
                'value': int(value), 'unit': 'USD millions', 'currency': 'USD', 'block_id': TABLE_ID,
                'row': row, 'column': f'c{column}..{column + 1}', 'quote': quote})
            inline_checks.append({'fact_id': fact_id, 'context_id': inline.attrib['contextref'],
                                  'metric': metric, 'period': year, 'value': int(value)})
    delta = number(cells[(25, 3)]['text']) - number(cells[(25, 9)]['text'])
    percent = delta / number(cells[(25, 9)]['text']) * 100
    bridge = {str(row): int(number(cells[(row, 3)]['text']) - number(cells[(row, 9)]['text']))
              for row in (19, 21, 23, 24)}
    checks = {'source_files': {name: {'path': str((DATASET / ref['path']).relative_to(ROOT)), 'sha256': ref['sha256']}
                              for name, ref in SOURCE_FILES.items()},
        'selected_blocks_verified': len(packet['blocks']), 'raw_inline_facts_verified': inline_checks,
        'verification_method': 'Pinned raw HTML + inline context/concept/unit/sign checks + complete indexed cell projection; no historical candidate used.',
        'hidden_derived_checks': {'operating_cash_flow_delta_millions': str(delta),
                                'operating_cash_flow_change_percent': str(percent), 'selected_row_changes_millions': bridge}}
    return packet, records, checks


def task_definition(task):
    shape = {'facts': 'Objects with metric, period, period_end, signed value, unit, currency, block_id, row, column, quote; unit must be USD millions and currency USD. Quote the original table row verbatim.',
             'analysis': 'List of {claim, block_ids}; concise Chinese claims cite only selected blocks.',
             'gaps': 'At least two distinct, specific limitations of this excerpt; no outside facts.'}
    if task == 'cashflow-facts':
        instruction = ('仅依据给定片段核对2023、2022财年经营、投资、融资活动净现金流。facts恰好六条，'
            'metric分别使用operating_cash_flow、investing_cash_flow、financing_cash_flow。保留财年、期末、'
            '正负号、原展示单位及准确行列。analysis总计不超过100个中文字，说明表格与文字叙述的口径或精度差异；'
            '不要将四舍五入的文字金额当作精确值。gaps至少两条具体资料局限。不要推测未来或给投资建议。')
    else:
        instruction = ('仅依据给定片段写一则经营现金流变动说明。facts恰好两条：2023及2022的经营活动净现金流，'
            'metric使用operating_cash_flow。analysis总计不超过250个中文字。至少一条claim按以下文字格式给出计算，'
            '数字由你计算：经营现金流同比变化：<有符号金额> USD millions；变化率：<有符号百分数>%；公式：<算式>。'
            '再解释资料支持的同比变化，区分当年资金使用构成、同比变化方向和管理层说明；不要把表格变化直接当作完整商业因果。'
            '引用支撑各claim的block。gaps至少两条具体无法从节选判断的内容。不要加入外部事实、预测或投资建议。')
    return {'id': task, 'language': 'zh-CN', 'instruction': instruction, 'output_format': shape}


def rubric(task):
    return {'schema_version': 'pilot-preregistered-rubric-v1', 'task_id': task,
        'not_for_model_input': True, 'status': 'preregistered_before_pilot_calls',
        'automated_gates': {'complete_finish_required': True, 'strict_contract_and_exact_citations': True,
            'expected_fact_count': 6 if task == 'cashflow-facts' else 2,
            'all_expected_metric_period_values_signs_currency_units_dates_locations_required': True,
            'no_duplicate_missing_or_extra_facts': True, 'minimum_distinct_gaps': 2,
            'maximum_analysis_han_characters': 100 if task == 'cashflow-facts' else 250,
            'change_formula_marker_required': task == 'cashflow-change',
            'change_amount_tolerance_usd_millions': '0', 'change_percent_tolerance_percentage_points': '0.02'},
        'blind_review': {'status': 'not_performed', 'show_to_reviewer': ['task_packet', 'anonymized_answer', 'rubric', 'source_reference'],
            'hide_from_reviewer': ['provider', 'model', 'trial_order', 'repeat_number', 'latency', 'usage', 'cost'],
            'dimensions': [
                {'id': 'evidence_faithfulness', 'range': [0, 2], 'anchors': {'0': 'Material invented or contradictory claim', '1': 'Mostly supported but ambiguous', '2': 'Every substantive claim supported and correctly scoped'}},
                {'id': 'task_answer', 'range': [0, 2], 'anchors': {'0': 'Misses the question', '1': 'Partial explanation', '2': 'Answers the assigned question clearly'}},
                {'id': 'causal_and_period_discipline', 'range': [0, 2], 'anchors': {'0': 'Confuses period, rounding, or cause', '1': 'Weak distinction', '2': 'Separates exact/rounded numbers and current-year composition from year-on-year drivers'}},
                {'id': 'material_limits', 'range': [0, 2], 'anchors': {'0': 'No meaningful gaps or unsupported forecast', '1': 'Only one specific gap', '2': 'At least two distinct material gaps tied to excerpt scope'}},
                {'id': 'readability', 'range': [0, 2], 'anchors': {'0': 'Hard to understand or excessive', '1': 'Understandable with clutter', '2': 'Concise, clear, and useful'}}],
            'pass': 'Automated gates pass, blind total at least 8/10, evidence_faithfulness=2, causal_and_period_discipline>=1; unsupported forecast/recommendation is a critical failure.',
            'reviewer_type': 'Record human or agent explicitly; a parent agent source check is not independent human Gold.'},
        'pilot_aggregation': 'Keep per-trial successes and failures; report per-task/profile 0/2,1/2,2/2 repeat consistency plus ranges; no universal model rank or significance claim.'}


def prepare_benchmark(output=HERE):
    output = Path(output)
    old_packet, expected, source_checks = verify_source()
    helper = frozen_helpers()
    task_entries = []
    for task in TASKS:
        base = output / 'tasks' / task
        packet = deepcopy(old_packet)
        packet['schema_version'] = 'reproducibility-pilot-packet-v1'
        packet['task'] = task_definition(task)
        packet_bytes = encoded(packet)
        reference = {'schema_version': 'pilot-hidden-reference-v1', 'task_id': task, 'not_for_model_input': True,
            'review_status': 'source_verified_by_agent_not_human_gold', 'expected_records': [r for r in expected
                if task == 'cashflow-facts' or r['metric'] == 'operating_cash_flow'],
            'derived': source_checks['hidden_derived_checks'],
            'qualitative_checks': [
                'MD&A describes 2023 receivables and inventory cash use; it does not alone identify the largest adverse year-on-year driver.',
                'Inventory cash drag improved year on year; claiming worsening inventory drag as the reason for the overall decline is incorrect.',
                'Accounts payable and accrued/other liabilities had adverse year-on-year changes; inventories and prepaid/other assets offset part of the decline.',
                'Use exact table figures for arithmetic; MD&A billions are rounded.',
                'The excerpt cannot establish future sustainability, full business causes, valuation, or investment advice.'],
            'source_verification_sha256': digest(encoded(source_checks))}
        scoring = rubric(task)
        manifest = {'schema_version': 'bounded-model-comparison-prepared-manifest-v1',
            'status': 'frozen_before_pilot_requests', 'task_id': task, 'packet_file': 'packet.json',
            'packet_sha256': digest(packet_bytes), 'scope': packet['scope'],
            'input_block_ids': [block['block_id'] for block in packet['blocks']],
            'source_dataset_relative_path': str(DATASET.relative_to(ROOT)), 'source_sha256': SOURCE_FILES['raw']['sha256'],
            'index_id': packet['source']['index_id'], 'source_files': source_checks['source_files'],
            'reference_file': '../reference-review.json', 'reference_sha256': digest(encoded(reference)),
            'rubric_file': '../rubric.json', 'rubric_sha256': digest(encoded(scoring)),
            'reference_must_not_enter_model_request': True,
            'input_measurements': {'packet_bytes': len(packet_bytes), 'block_count': len(packet['blocks']),
                'target_input_tokens': [2000, 6000], 'token_count': 'Not measured for this new prompt; provider-specific tokenization is unverified.',
                'calibration': 'Earlier same five blocks and frozen system: Sonnet gateway reported 5131 prompt tokens; DeepSeek 4028. Current compact packet has revised task text; these are calibration, not this request counts.'}}
        for path, value in ((base/'prepared/packet.json', packet), (base/'prepared/manifest.json', manifest),
                            (base/'reference-review.json', reference), (base/'rubric.json', scoring)):
            write_new(path, value)
        _, _, metadata = helper.load_prepared(base/'prepared')
        task_entries.append({'id': task, 'prepared': f'tasks/{task}/prepared', **metadata,
            'reference': f'tasks/{task}/reference-review.json', 'reference_sha256': manifest['reference_sha256'],
            'rubric': f'tasks/{task}/rubric.json', 'rubric_sha256': manifest['rubric_sha256']})
    profiles = []
    for letter, identity in PROFILES.items():
        path = output / 'profiles' / (identity + '.json')
        raw = path.read_bytes()
        profile = json.loads(raw)
        if profile['id'] != identity or profile['max_retries'] != 0 or profile['stream'] is not False:
            raise ValueError('Profile identity or single-call controls do not match')
        profiles.append({'label': letter, 'id': identity, 'path': 'profiles/' + path.name, 'sha256': digest(raw),
                         'provider': profile['provider'], 'model': profile['model']})
    order = []
    for task, sequence in zip(TASKS, ('SDDS', 'DSSD')):
        counts = defaultdict(int)
        for label in sequence:
            counts[label] += 1
            trial_id = f'{task}-{label.lower()}-r{counts[label]}'
            order.append({'ordinal': len(order)+1, 'trial_id': trial_id, 'id': trial_id,
                'task_id': task, 'profile_id': PROFILES[label], 'repeat': counts[label],
                'prepared': f'tasks/{task}/prepared', 'prepared_path': f'tasks/{task}/prepared',
                'output_path': f'runs/{trial_id}'})
    plan = {'schema_version': 'preregistered-reproducibility-pilot-v1', 'id': '2026-10-07-reproducibility-pilot-v1',
        'status': 'prepared_no_model_calls', 'interpretation': 'Small pilot for two service configurations on one issuer excerpt, not a model ranking or equal-compute comparison.',
        'tasks': task_entries, 'profiles': profiles, 'call_order': order,
        'limits': {'tasks': 2, 'profiles': 2, 'repeats_per_task_profile': 2, 'maximum_model_calls': 8,
            'parallel_calls': 1, 'automatic_retries': 0, 'continuations_or_repairs': 0,
            'aggregate_estimated_budget_usd': '1.50', 'actual_billed_budget_guarantee': False,
            'input_token_target': [2000,6000], 'provider_input_count_validation': 'Use returned provider counts; report any excess and stop further calls pending review, never silently trim evidence.'},
        'budget_control': 'Root execution layer must verify all 8 conservative reservations fit <=1.50 USD and use one shared budget ledger. Unknown usage, prior in-flight reservations, exhaustion, or HTTP failure stops further dispatch. This preparation helper does not execute or enforce dispatch.',
        'shared_process': ['source acquisition and independent source verification', 'packet and rubric preparation', 'one frozen system prompt per task', 'profile and plan hash pinning', 'aggregate budget and single-call sequencing', 'blind review after all intended trials or a stop'],
        'per_call_process': ['verify task/profile/input hashes', 'reserve against shared remaining budget', 'save actual request configuration', 'one isolated model request with no prior answers/history', 'settle reported usage or retain unknown', 'save visible output and program checks'],
        'fairness_limits': ['Task order is blocked; only model order within tasks is counterbalanced.', 'Only two repeats: no significance or population variance claims.', 'Both tasks share the same five AMD source blocks; this is not company/task generalization.', 'Sonnet high and DeepSeek low are not equal inference compute or equivalent setting names.', 'Cache behavior, provider routing, non-determinism, different output caps and supported sampling differ; record them rather than infer determinism.'],
        'normalization': {'raw_hash': 'sha256 of exact visible UTF-8 output bytes', 'json_hash': 'Canonical JSON preserving list order',
            'order_normalized_hash': 'Sort fact, claim and gap collections; normalize Unicode/whitespace, numeric value representation and cited block order; keep duplicates.',
            'fact_hash': 'Sort normalized fact fields, excluding quote wording; separate from citation checks. Same hash is agreement, not correctness.'},
        'blind_review': {'status': 'not_performed', 'instruction': 'Assign output-only blind IDs and hide model/profile/order/repeat/cost before qualitative scoring. Keep the mapping outside reviewer material.'},
        'frozen_validation_runner_sha256': RUNNER_SHA256, 'source_verification_sha256': digest(encoded(source_checks))}
    write_new(output/'source-verification.json', source_checks)
    write_new(output/'plan.json', plan)
    return plan


def verify_benchmark(folder=HERE):
    folder = Path(folder)
    plan = json.loads((folder/'plan.json').read_bytes())
    if len(plan['call_order']) != 8 or [c['ordinal'] for c in plan['call_order']] != list(range(1,9)):
        raise ValueError('Unexpected pilot call count or ordering')
    helper = frozen_helpers()
    source = pinned(folder/'source-verification.json', plan['source_verification_sha256'])
    for ref in json.loads(source)['source_files'].values():
        pinned(ROOT/ref['path'], ref['sha256'])
    for task in plan['tasks']:
        _, _, metadata = helper.load_prepared(folder/task['prepared'])
        for key in ('packet_sha256','manifest_sha256','system_sha256','messages_sha256'):
            if metadata[key] != task[key]:
                raise ValueError('Frozen task input changed')
        pinned(folder/task['reference'], task['reference_sha256'])
        pinned(folder/task['rubric'], task['rubric_sha256'])
    for profile in plan['profiles']:
        pinned(folder/profile['path'], profile['sha256'])
    return {'status': 'verified_offline', 'tasks': len(plan['tasks']), 'calls_planned': len(plan['call_order']),
            'model_calls_made_by_helper': 0, 'plan_sha256': digest((folder/'plan.json').read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    result = verify_benchmark(args.output) if args.verify else prepare_benchmark(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
