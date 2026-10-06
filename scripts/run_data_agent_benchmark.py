#!/usr/bin/env python3
"""Offline regression + independent human-review rollup. Never invokes a model."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'benchmarks/data_agent/v0.1'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_input(case):
    """The sole exported model-facing data; rubric/reviews are never merged."""
    return json.loads(json.dumps(case['input']))


def verify_dataset(root, files, binding, scope):
    from uteki.domain.research_data.execution_scope import ExecutionScope
    required = {'snapshot_id', 'source_policy_id', 'include_candidates', 'company_ids', 'source_snapshot_ids', 'knowledge_cutoff'}
    if not required <= set(scope) or not binding.get('dataset_manifest'):
        return 'not_ready', 'Complete execution scope or frozen dataset binding absent'
    ExecutionScope.model_validate(scope)
    name = binding['dataset_manifest']
    if name not in files:
        return 'not_ready', 'Dataset manifest is not pinned in run manifest'
    manifest = load(root/name)
    if manifest['snapshot_id'] != scope['snapshot_id'] or manifest['source_policy_id'] != scope['source_policy_id']:
        return 'invalid', 'Dataset identity differs from execution scope'
    folder = Path(name).parent
    dataset_files = manifest['files']
    if 'sources.json' not in dataset_files:
        return 'not_ready', 'Frozen dataset sources absent'
    for relative, expected in dataset_files.items():
        if files.get(str(folder/relative)) != expected:
            return 'invalid', 'Dataset file is not bound to the verified run files'
    sources = load(root/folder/'sources.json')
    selected = [s for s in sources if s['source_snapshot_id'] in scope['source_snapshot_ids']]
    if len(selected) != len(scope['source_snapshot_ids']) or len({s['source_snapshot_id'] for s in selected}) != len(selected):
        return 'invalid', 'Selected source IDs do not resolve uniquely in the frozen dataset'
    if set(scope['company_ids']) - {s['company_id'] for s in selected}:
        return 'not_ready', 'At least one requested company has no selected source in the frozen dataset'
    for source in selected:
        if source['company_id'] not in scope['company_ids'] or source['available_at'][:10] > scope['knowledge_cutoff']:
            return 'invalid', 'Selected source company or availability exceeds scope'
        raw = source.get('raw_file')
        if not raw or not source.get('source_sha256'):
            return 'not_ready', 'Selected source has no frozen original-byte binding'
        if dataset_files.get(raw) != source['source_sha256'] or source.get('raw_file_sha256') != source['source_sha256']:
            return 'invalid', 'Selected source raw bytes hash differs from dataset manifest'
    return 'verified', 'Dataset, selected sources and raw bytes bound'


def verify_artifacts(review, case):
    """Verify local integrity and question binding, not proof a remote model ran."""
    if not review.get('run_dir') or not review.get('manifest_sha256'):
        return 'missing', 'run_dir/manifest_sha256 missing'
    root = Path(review['run_dir']).resolve()
    manifest = root / 'manifest.json'
    if not manifest.is_file():
        return 'missing', 'run manifest absent'
    try:
        if sha(manifest) != review['manifest_sha256']:
            return 'invalid', 'manifest hash mismatch'
        files = load(manifest)['files']
        if not {'request.json', 'config.json', 'result.json'} <= set(files):
            return 'missing', 'request/config/result are not pinned in manifest'
        for name, expected in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or sha(path) != expected:
                return 'invalid', 'manifest entry invalid: ' + name
        request, config = load(root / 'request.json'), load(root / 'config.json')
        if request.get('question') != case['input']['question']:
            return 'invalid', 'run question differs from versioned benchmark question'
        if config.get('plan_origin') != 'model':
            return 'invalid', 'run is not declared as model-origin'
        required = {'benchmark-input.json', 'benchmark-sources.json', 'model-usage.json'}
        if not required <= set(files):
            return 'not_ready', 'T3 frozen benchmark input/source binding or model usage is absent'
        if load(root/'benchmark-input.json') != model_input(case):
            return 'invalid', 'frozen benchmark input differs in scope, cutoff, source policy or limits'
        binding = load(root/'benchmark-sources.json')
        expected_configs = load(CONFIG/'questions.json')['source_configuration_hashes']
        config_files = case['input']['source_policy']['configuration_files']
        if set(binding.get('configuration_artifacts', {})) != set(config_files):
            return 'invalid', 'frozen source configuration set differs from the benchmark'
        for name, artifact in binding['configuration_artifacts'].items():
            if artifact not in files or files[artifact] != expected_configs[name]:
                return 'invalid', 'frozen source configuration hash differs from the benchmark'
        scope = request.get('scope', {})
        companies = binding.get('companies', [])
        expected_companies = {(c['symbol'], c['market']) for c in case['input']['companies']}
        if ({(c['symbol'], c['market']) for c in companies} != expected_companies
                or len(companies) != len(expected_companies)
                or {c['company_id'] for c in companies} != set(scope.get('company_ids', []))
                or binding.get('execution_scope') != scope
                or scope.get('knowledge_cutoff') != case['input']['as_of']):
            return 'invalid', 'frozen resolved company/scope binding differs from caller scope'
        dataset_status, dataset_reason = verify_dataset(root, files, binding, scope)
        if dataset_status != 'verified': return dataset_status, dataset_reason
        questions = load(CONFIG/'questions.json')
        budget = questions['model_budget']
        if (questions.get('execution_authorized') is not True
                or any(budget.get(key) is None for key in ('provider', 'model', 'aggregate_request_limit', 'currency'))
                or budget.get('cost_policy') not in {'record_only', 'block_at_limit'}):
            return 'not_ready', 'Versioned benchmark has no explicit model execution authorization/budget'
        if not config.get('provider') or not config.get('model'):
            return 'not_ready', 'Frozen model configuration absent'
        if config['provider'] != budget['provider'] or config['model'] != budget['model']:
            return 'invalid', 'Frozen provider/model differs from authorized benchmark configuration'
        result_status = load(root / 'result.json').get('status')
        if result_status == 'failed':
            return 'invalid', 'recorded run failed'
        if result_status not in {'evidence_ready', 'partial'}:
            return 'missing', 'recorded run has no accepted finish; actual status: ' + str(result_status)
        refs = review.get('model_call_evidence', [])
        if not refs or any(ref not in files for ref in refs):
            return 'missing', 'model call evidence must reference pinned run files'
        if review.get('model_calls_human_verified') is not True:
            return 'missing', 'independent verification of actual model calls pending'
    except (OSError, ValueError, KeyError, TypeError) as error:
        return 'invalid', type(error).__name__ + ': invalid run artifacts'
    return 'human_reviewed_artifacts_verified', 'File integrity checked; actual model execution was human-reviewed, not programmatically proven.'


def verified_usage(review, case):
    """Read pinned accounting; never substitute reviewer-entered consumption."""
    usage = load(Path(review['run_dir'])/'model-usage.json')
    calls, limits = usage.get('attempts', []), case['input']['limits']
    questions = load(CONFIG/'questions.json'); budget = questions['model_budget']
    expected_authorization = {'benchmark_id': questions['benchmark_id'], 'questions_sha256': sha(CONFIG/'questions.json'), 'model_budget': budget}
    if usage.get('authorization') != expected_authorization:
        return 'partial', {}, 'Frozen authorization binding absent or differs from versioned benchmark'
    if not calls or usage.get('limits') != limits:
        return 'partial', {}, 'Missing attempts or mismatched frozen resource limits'
    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    record_only = budget.get('cost_policy') == 'record_only'
    if (not isinstance(budget.get('aggregate_request_limit'), int) or isinstance(budget['aggregate_request_limit'], bool)
            or budget['aggregate_request_limit'] < 1 or budget.get('count_retries_and_timeouts') is not True
            or (not record_only and (not number(budget.get('aggregate_cost_limit')) or budget['aggregate_cost_limit'] <= 0))):
        return 'partial', {}, 'Authorized cumulative request/cost limits incomplete'
    cumulative = usage.get('cumulative_attempts')
    if not cumulative:
        return 'partial', {}, 'Frozen cumulative request ledger absent'
    unique = {}
    files = load(Path(review['run_dir'])/'manifest.json')['files']
    for c in [*cumulative, *calls]:
        if not c.get('request_id') or c.get('case_id') not in {row['case_id'] for row in questions['cases']} or c.get('evidence_path') not in files:
            return 'partial', {}, 'Request identity, case or pinned call evidence absent'
        if c['provider'] != budget['provider'] or c['model'] != budget['model']:
            return 'fail', {}, 'Attempt provider/model differs from frozen authorization'
        if c.get('cost') is not None and not number(c['cost']):
            return 'fail', {}, 'Invalid recorded request cost'
        rid = c['request_id']
        if rid in unique and unique[rid] != c:
            return 'fail', {}, 'Conflicting payloads for one request ID'
        unique[rid] = c
    if any(c['case_id'] != case['case_id'] for c in calls):
        return 'fail', {}, 'Per-case usage contains a different benchmark case'
    if not {c['request_id'] for c in calls} <= {c['request_id'] for c in cumulative}:
        return 'partial', {}, 'Current requests absent from cumulative ledger'
    calls = list({c['request_id']: c for c in calls}.values())
    if usage.get('cost_currency') != budget['currency']:
        return 'fail', {}, 'Usage currency differs from authorized budget'
    for c in calls:
        if (c.get('status') not in {'succeeded', 'failed', 'timed_out'} or not c.get('provider') or not c.get('model')
                or not isinstance(c.get('retry'), bool)):
            return 'partial', {}, 'Incomplete per-attempt provider/status/retry record'
    metrics = {'requests_attempted': len(calls), 'requests_succeeded': sum(c['status'] == 'succeeded' for c in calls),
               'requests_failed': sum(c['status'] == 'failed' for c in calls),
               'requests_timed_out': sum(c['status'] == 'timed_out' for c in calls),
               'retry_requests': sum(c['retry'] for c in calls), 'input_tokens': None, 'output_tokens': None,
               'cost': None, 'cost_currency': usage.get('cost_currency'), 'elapsed_seconds': usage.get('elapsed_seconds'),
               'steps': usage.get('steps'), 'unknown_cost_reason': usage.get('unknown_cost_reason')}
    metrics['budget_requests'] = {rid: {'sha256': hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest(), 'cost': c.get('cost')}
                                  for rid, c in unique.items()}
    if not metrics['requests_succeeded']:
        return 'fail', metrics, 'No successful model request; failed attempts cannot satisfy a model case'
    tokens_known = all(isinstance(c.get(k), int) and not isinstance(c[k], bool) and c[k] >= 0
                       for c in calls for k in ('input_tokens', 'output_tokens'))
    if tokens_known:
        for key in ('input_tokens', 'output_tokens'): metrics[key] = sum(c[key] for c in calls)
    cost_known = all(number(c.get('cost')) for c in calls) and bool(usage.get('cost_currency'))
    if cost_known: metrics['cost'] = sum(c['cost'] for c in calls)
    metrics['cost_completeness'] = 'known' if cost_known else 'unknown'
    metrics['cost_policy'] = budget['cost_policy']
    resource_known = number(usage.get('elapsed_seconds')) and isinstance(usage.get('steps'), int) and not isinstance(usage['steps'], bool) and usage['steps'] >= 0
    over = len(calls) > limits['max_model_requests']
    if tokens_known:
        over |= metrics['input_tokens'] + metrics['output_tokens'] > limits['max_total_tokens'] or any(c['output_tokens'] > limits['max_output_tokens_per_request'] for c in calls)
    if resource_known:
        over |= usage['elapsed_seconds'] > limits['max_wall_seconds'] or usage['steps'] > limits['max_steps']
    budget_known = number(usage.get('authorized_cost_limit'))
    if not record_only and budget_known and cost_known: over |= metrics['cost'] > usage['authorized_cost_limit']
    cumulative_known = all(number(c.get('cost')) for c in unique.values())
    over |= len(unique) > budget['aggregate_request_limit']
    if not record_only and cumulative_known: over |= sum(c['cost'] for c in unique.values()) > budget['aggregate_cost_limit']
    if over: return 'fail', metrics, 'Pinned usage exceeds a request/token/time/step/cost limit'
    if not (tokens_known and resource_known and (record_only or (cost_known and cumulative_known))):
        return 'partial', metrics, 'Pinned token/cost/resource accounting or authorized cost cap incomplete'
    return 'pass', metrics, 'Pinned usage is within declared limits; authorization and call authenticity remain human-reviewed'


def evaluate_review(case, review, rubric):
    base = {'case_id': case['case_id'], 'category': case['category'], 'kind': 'real_model_case',
            'status': 'not_run', 'underlying_verdict': 'not_run', 'metrics': {},
            'verification': 'not_run', 'reason': 'No executed run submitted; offline tests are not this model case.'}
    if not review or review.get('executed') is not True:
        return base
    verification, reason = verify_artifacts(review, case)
    checks = review.get('checks', {})
    required = rubric['required_checks'][case['category']]
    states = [checks.get(key, {}).get('status', 'not_reviewed') for key in required]
    usage_status, usage_metrics, usage_reason = 'partial', {}, 'Pinned accounting not verified'
    if verification == 'human_reviewed_artifacts_verified':
        try:
            usage_status, usage_metrics, usage_reason = verified_usage(review, case)
        except (OSError, ValueError, KeyError, TypeError):
            usage_status, usage_reason = 'fail', 'Invalid pinned accounting payload'
    review_metric_keys = {'citations_checked', 'citations_supported', 'numeric_claims_checked', 'numeric_claims_correct',
                         'required_body_blocks', 'read_body_blocks', 'unread_body_blocks', 'omitted_requirements'}
    metrics = {**{k: v for k, v in review.get('metrics', {}).items() if k in review_metric_keys}, **usage_metrics}
    counts = [metrics.get(key) for key in ('requests_attempted', 'requests_succeeded',
              'requests_failed', 'requests_timed_out', 'retry_requests')]
    cost_known = (isinstance(metrics.get('cost'), (int, float)) and not isinstance(metrics.get('cost'), bool)
                  and metrics['cost'] >= 0 and bool(metrics.get('cost_currency')))
    count_valid = all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts)
    accounting_complete = count_valid and counts[0] > 0 and counts[0] == sum(counts[1:4]) and counts[4] <= counts[0]
    accounting_complete = accounting_complete and (cost_known or metrics.get('cost_policy') == 'record_only' or bool(metrics.get('unknown_cost_reason')))
    over_limit = count_valid and counts[0] > case['input']['limits']['max_model_requests']
    verdict = 'partial'
    if verification == 'invalid' or 'fail' in states or over_limit or usage_status == 'fail':
        verdict = 'fail'
        if usage_status == 'fail': reason = usage_reason
        if over_limit: reason = 'Actual request count exceeds per-case limit (including retries/timeouts).'
    elif verification == 'human_reviewed_artifacts_verified' and review.get('reviewer') and review.get('reviewed_at'):
        if usage_status == 'pass' and accounting_complete and all(state == 'pass' and checks[key].get('evidence') for key, state in zip(required, states)):
            verdict = 'pass'
            reason = 'Required rubric checks passed in independent human review; local artifacts verified.'
        else:
            reason = 'Required rubric checks, supporting evidence or request/cost accounting incomplete.'
    assisted = bool(review.get('assistance'))
    if verdict == 'pass':
        frozen_result = load(Path(review['run_dir'])/'result.json')
        if frozen_result['status'] == 'partial':
            missing_gap_complete = (case['category'] == 'missing'
                and frozen_result.get('stop_reason') == 'host_reference_checks_passed'
                and bool(frozen_result.get('gaps'))
                and all(g.get('reason') == 'not_yet_occurred' for g in frozen_result['gaps'])
                and checks.get('gap_accuracy', {}).get('status') == 'pass')
            if not missing_gap_complete:
                verdict, reason = 'partial', 'Partial run cannot satisfy this case; human checks cannot upgrade incomplete execution'
    return {**base, 'status': 'assisted' if assisted else verdict, 'underlying_verdict': verdict,
            'verification': verification, 'reason': reason, 'required_checks': required,
            'reviewer': review.get('reviewer'), 'assistance': review.get('assistance', []),
            'metrics': metrics, 'accounting_verification': usage_status, 'accounting_reason': usage_reason, 'checks': checks}


def enforce_cumulative_budget(results, questions):
    """Union pinned request IDs across imported cases, including repeated ledgers."""
    requests, conflicts = {}, False
    for row in results:
        for rid, value in row.get('metrics', {}).get('budget_requests', {}).items():
            conflicts |= rid in requests and requests[rid] != value
            requests[rid] = value
    budget = questions['model_budget']
    known = bool(requests) and all(isinstance(r.get('cost'), (int, float)) and not isinstance(r['cost'], bool)
                                 and math.isfinite(r['cost']) and r['cost'] >= 0 for r in requests.values())
    over = isinstance(budget.get('aggregate_request_limit'), int) and len(requests) > budget['aggregate_request_limit']
    if budget.get('cost_policy') == 'block_at_limit' and known and isinstance(budget.get('aggregate_cost_limit'), (int, float)):
        over |= sum(r['cost'] for r in requests.values()) > budget['aggregate_cost_limit']
    if conflicts or over:
        for row in results:
            if row.get('metrics', {}).get('budget_requests'):
                row['underlying_verdict'] = 'fail'
                if row['status'] != 'assisted': row['status'] = 'fail'
                row['reason'] = 'Imported cumulative request ledgers conflict or exceed the shared authorized budget'
    return {'unique_requests': len(requests), 'cost': sum(r['cost'] for r in requests.values()) if known else None,
            'status': 'fail' if conflicts or over else 'verified' if known else 'cost_unknown' if requests and budget.get('cost_policy') == 'record_only' else 'not_ready'}


def check_available(target):
    # Module targets permit T2 integration without inventing test method names.
    parts = target.split('.')
    module = '.'.join(parts[:3])
    if len(parts) < 3 or not module.startswith('tests.unit.test_'):
        return False, 'Not an allowlisted offline unittest target'
    try:
        spec = importlib.util.find_spec(module)
    except (ModuleNotFoundError, ValueError):
        spec = None
    return (bool(spec), '' if spec else 'Test module not implemented: ' + module)


def run_check(target, timeout):
    command = [sys.executable, '-m', 'unittest', target]
    available, reason = check_available(target)
    row = {'target': target, 'command': command, 'cwd': str(ROOT), 'exit_code': None,
           'status': 'not_run', 'elapsed_seconds': 0, 'reason': reason}
    if not available:
        return row
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        output = (result.stdout + result.stderr).strip()
        row.update(exit_code=result.returncode, status='pass' if result.returncode == 0 else 'fail',
                   reason='Offline assertion(s) passed' if result.returncode == 0 else 'Offline assertion(s) failed',
                   output_tail=output[-3000:])
    except subprocess.TimeoutExpired:
        row.update(status='fail', reason='Offline command timed out', output_tail='timeout')
    row['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return row


def suite_status(checks, complete):
    statuses = [row['status'] for row in checks]
    if 'fail' in statuses:
        return 'fail'
    if not statuses or all(s == 'not_run' for s in statuses):
        return 'not_run'
    return 'pass' if complete and all(s == 'pass' for s in statuses) else 'partial'


def render(report):
    lines = ['# Data Agent benchmark ' + report['benchmark_id'], '',
             '离线工程断言与真实模型题分开报告；单测数不构成模型分数。', '',
             '| 离线套件 | 状态 | 范围 |', '|---|---|---|']
    for row in report['offline_suites']:
        lines.append(f"| {row['suite_id']} | {row['status']} | {row['scope_note']} |")
    lines += ['', '| 真实题 | 状态 | 原因 |', '|---|---|---|']
    for row in report['real_model_cases']:
        lines.append(f"| {row['case_id']} | {row['status']} | {row['reason']} |")
    lines += ['', '本 runner 模型调用：0。外部运行的成本按独立复核记录保留，未知不作零。',
              '逐项命令、退出状态、错误摘要及复核维度见 report.json。', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwrite a prior report')
    parser.add_argument('--suite', action='append', help='E1..E8, repeatable; default all')
    parser.add_argument('--case', action='append', help='Real case ID, repeatable; default all')
    parser.add_argument('--reviews', type=Path, help='Independent review JSON, not model input')
    parser.add_argument('--skip-offline', action='store_true')
    parser.add_argument('--timeout', type=float, default=60, help='Seconds per offline command')
    args = parser.parse_args(argv)
    questions, rubric, suites = load(CONFIG/'questions.json'), load(CONFIG/'rubric.json'), load(CONFIG/'offline_suites.json')['suites']
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if set(args.suite or []) - {s['suite_id'] for s in suites}:
        parser.error('unknown --suite')
    if set(args.case or []) - {c['case_id'] for c in questions['cases']}:
        parser.error('unknown --case')
    for name, expected in questions['source_configuration_hashes'].items():
        if not (ROOT/name).is_file() or sha(ROOT/name) != expected:
            parser.error('source configuration changed; create/review a new benchmark version: ' + name)
    reviews = load(args.reviews)['reviews'] if args.reviews else []
    if len({r['case_id'] for r in reviews}) != len(reviews) or set(r['case_id'] for r in reviews) - {c['case_id'] for c in questions['cases']}:
        parser.error('duplicate or unknown review case_id')
    by_id = {r['case_id']: r for r in reviews}
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 'data-agent-benchmark-report-v0.1', 'benchmark_id': questions['benchmark_id'],
              'created_at': datetime.now(timezone.utc).isoformat(), 'model_calls_by_runner': 0,
              'configuration_hashes': {p.name: sha(p) for p in sorted(CONFIG.glob('*.json'))},
              'source_configuration_hashes': questions['source_configuration_hashes'],
              'offline_suites': [], 'real_model_cases': [], 'selected_suites': args.suite, 'selected_cases': args.case}
    for suite in suites:
        if args.suite and suite['suite_id'] not in args.suite:
            continue
        checks = [] if args.skip_offline else [run_check(target, args.timeout) for target in suite['checks']]
        report['offline_suites'].append({**suite, 'kind': 'scripted_engineering_regression', 'checks': checks,
            'status': suite_status(checks, suite['acceptance_mapping_complete']),
            'not_run_reason': 'Explicit --skip-offline' if args.skip_offline else None})
    all_cases = [evaluate_review(case, by_id.get(case['case_id']), rubric) for case in questions['cases']]
    report['cumulative_budget'] = enforce_cumulative_budget(all_cases, questions)
    report['real_model_cases'] = [row for row in all_cases if not args.case or row['case_id'] in args.case]
    report['real_model_status_counts'] = dict(Counter(r['status'] for r in report['real_model_cases']))
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (args.output/'report.md').write_text(render(report), encoding='utf-8')
    print(args.output/'report.md')
    return int(any(s['status'] == 'fail' for s in report['offline_suites']) or any(r['underlying_verdict'] == 'fail' for r in report['real_model_cases']))


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
