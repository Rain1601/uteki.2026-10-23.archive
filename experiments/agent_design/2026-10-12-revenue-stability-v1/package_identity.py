"""Read-only experiment comparison and existing evidence-view renderer; no API calls."""
import hashlib
import json
from decimal import Decimal

from apps.review_workbench.pages.data_retrieval_suite import render_data_retrieval_suite
from run_fresh import BASE, ROOT, implementation, ledger, read
from uteki.agents.data_query.question_review_generation import project_question_generation
from uteki.infrastructure.research_data.financial_records import digest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    current = read(BASE/'v4/implementation-freeze.json')
    previous = read(BASE/'v3/implementation-freeze.json')
    actual = implementation()
    runner = ROOT/'experiments/agent_design/2026-10-12-revenue-stability-v1/run_identity.py'
    actual[str(runner.relative_to(ROOT))] = sha(runner)
    assert current == actual
    changes = sorted(k for k in current.keys() | previous.keys() if current.get(k) != previous.get(k))
    assert set(changes) == {'src/uteki/agents/data_query/question_review_generation.py',
        'src/uteki/agents/data_query/record_review_model.py', 'src/uteki/agents/data_query/retrieval_cycle.py',
        'experiments/agent_design/2026-10-12-revenue-stability-v1/run_identity.py'}
    results, cases = [], []
    for version in ('v3', 'v4'):
        for slot in ('R1', 'R2', 'R3'):
            folder = BASE/version/slot
            config = read(folder/'runtime-config.json')
            baseline = read(BASE/'v3'/slot/'runtime-config.json')
            config.pop('workspace'); baseline.pop('workspace')
            if version == 'v4':
                for role in ('planner', 'worker', 'reviewer', 'question_reviewer'):
                    assert config[role]['max_requests_total'] == 600
                    config[role]['max_requests_total'] = baseline[role]['max_requests_total']
            assert config == baseline
            audit_file = BASE/f'evaluation-only/{version}-{slot}-audit.json'
            audit = read(audit_file)
            repairs = sorted(folder.glob('run/attempt-*/review-*/question-repair-input.json'))
            review_paths = sorted(folder.glob('run/attempt-*/review-*/question-response-01.json'))
            rejected = []
            for path in sorted(folder.glob('run/attempt-*/data-query/query/turn-*/feedback.json')):
                feedback = read(path)
                if feedback.get('status') == 'rejected':
                    rejected.append({'path': str(path.relative_to(ROOT)),
                                     'action': feedback.get('receipt', {}).get('action')})
            assessment = BASE/f'evaluation-only/{version}-{slot}-semantic-review.md'
            assert assessment.is_file()
            generated_checks = []
            if version == 'v4':
                for path in sorted(folder.glob('run/attempt-*/review-*/question-model/review-*-generated.json')):
                    generated = read(path)
                    canonical = read(path.with_name(path.name.replace('-generated', '-parsed')))
                    receipt = read(path.with_name(path.name.replace('-generated', '-projection')))
                    assert project_question_generation(generated) == canonical
                    assert receipt['generated_sha256'] == digest(generated)
                    assert receipt['canonical_sha256'] == digest(canonical)
                    generated_checks.append({'path': str(path.relative_to(ROOT)),
                        'requests': [c['request'] for c in generated['checks']],
                        'projection_verified': True})
                assert generated_checks
            results.append({'version': version, 'slot': slot,
                'final_delivery_checks': audit['combined_delivery_checks'],
                'no_recovery': audit['no_recovery_first_pass'],
                'question_review_attempts': len(review_paths),
                'question_protocol_repairs': len(repairs),
                'question_first_pass': bool(review_paths) and not repairs and len(review_paths) == 1
                    and audit['combined_delivery_checks'],
                'all_recovery_events': audit['recovery_events'],
                'rejected_actions': rejected,
                'generation_requests': generated_checks,
                'api_calls': audit['api_call_count'], 'estimated_usd': audit['known_estimated_usd'],
                'manual_review': str(assessment.relative_to(ROOT)), 'manual_review_sha256': sha(assessment),
                'audit_sha256': sha(audit_file)})
            if version == 'v4':
                cases.append({'case_id': slot.lower(), 'cycle_dir': str(folder/'run'),
                    'manifest_sha256': sha(folder/'run/manifest.json'),
                    'independent_assessment': {'path': str(assessment), 'sha256': sha(assessment),
                        'attachments': [{'path': audit_file.name, 'sha256': sha(audit_file)}]}})
    before, after = read(BASE/'budget-baseline.v1.json'), ledger()
    assert before['unknown'] == after['unknown']
    assert before['limit'] == after['limit']
    assert before['request_cap'] == 500 and after['request_cap'] == 600
    assert all(after['rows'].get(k) == v for k, v in before['rows'].items())
    new = [v for k, v in after['rows'].items() if k not in before['rows']]
    assert all(v['state'] == 'settled' for v in new)
    total = sum((Decimal(v['actual']) for v in new), Decimal(0))
    prior = read(BASE/'evaluation-only/question-contract-comparison.v1.json')
    v4 = [r for r in results if r['version'] == 'v4']
    added = sum((Decimal(r['estimated_usd']) for r in v4), Decimal(0))
    assert total == Decimal(prior['total_task_estimated_usd']) + added
    assert len(new) == prior['total_task_calls'] + sum(r['api_calls'] for r in v4)
    summary = {'schema_version': 'question-identity-comparison-v1', 'results': results,
        'runtime_changes_only': changes, 'other_configuration_identical_except_request_count_guard': True,
        'v4_estimated_usd': str(added), 'total_task_estimated_usd': str(total),
        'total_task_calls': len(new), 'new_unknown': [],
        'remaining_original_task_allowance_usd': str(Decimal('3')-total),
        'historical_reservations_unchanged': len(before['rows']),
        'limitation': 'Three fresh runs per version, one query; no statistical or unseen-query stability claim.'}
    save(BASE/'evaluation-only/question-identity-comparison.v1.json', summary)
    suite = BASE/'suite.v4.json'
    save(suite, {'schema_version': 'data-retrieval-suite-v1', 'cases': cases})
    save(BASE/'evaluation-only/packaging.v4.json', render_data_retrieval_suite(suite, BASE/'delivery-v4'))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
