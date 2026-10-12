"""Zero-API delivery packaging. Evaluation artifacts never enter the runtime."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from apps.review_workbench.pages.data_retrieval_suite import render_data_retrieval_suite
from run_fresh import BASE, ROOT, implementation, ledger, read


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    frozen = read(BASE/'v1/implementation-freeze.json')
    assert implementation() == frozen, 'Runtime changed after the frozen experiment'
    before, after = read(BASE/'budget-baseline.v1.json'), ledger()
    assert before['limit'] == after['limit'] and before['request_cap'] == after['request_cap']
    assert all(after['rows'].get(key) == value for key, value in before['rows'].items())
    assert after['unknown'] == before['unknown']
    new = {key: value for key, value in after['rows'].items() if key not in before['rows']}
    assert all(value['state'] == 'settled' for value in new.values())
    cases, results = [], []
    for slot in ('R1', 'R2', 'R3'):
        audit_file = BASE/f'evaluation-only/v1-{slot}-audit.json'
        assessment = BASE/f'evaluation-only/v1-{slot}-semantic-review.md'
        audit = read(audit_file)
        assert audit['combined_delivery_checks'] and assessment.is_file()
        cycle = BASE/f'v1/{slot}/run'
        results.append({'slot': slot, 'program_and_projection_checks': True,
            'semantic_review': str(assessment.relative_to(ROOT)), 'semantic_review_sha256': sha(assessment),
            'audit_sha256': sha(audit_file), 'no_recovery': audit['no_recovery_first_pass'],
            'api_calls': audit['api_call_count'], 'estimated_usd': audit['known_estimated_usd']})
        cases.append({'case_id': slot.lower(), 'cycle_dir': str(cycle),
            'manifest_sha256': sha(cycle/'manifest.json'),
            'independent_assessment': {'path': str(assessment), 'sha256': sha(assessment),
                'attachments': [{'path': audit_file.name, 'sha256': sha(audit_file)}]}})
    cost = sum((Decimal(row['actual']) for row in new.values()), Decimal(0))
    assert cost == sum((Decimal(row['estimated_usd']) for row in results), Decimal(0))
    assert len(new) == sum(row['api_calls'] for row in results)
    summary = {'schema_version': 'fresh-revenue-final-check-v1', 'results': results,
        'new_requests': len(new), 'new_estimated_usd': str(cost), 'new_unknown': [],
        'historical_rows_unchanged': len(before['rows']), 'runtime_files_unchanged': len(frozen),
        'budget_limit_unchanged': after['limit'], 'request_cap_unchanged': after['request_cap'],
        'remaining_task_allowance_usd': str(Decimal('3')-cost),
        'scope': 'three fresh runs of one fixed question on two complete local FY2025 filings; not statistical stability'}
    save(BASE/'evaluation-only/final-check.v1.json', summary)
    suite = BASE/'suite.v1.json'
    save(suite, {'schema_version': 'data-retrieval-suite-v1', 'cases': cases})
    rendered = render_data_retrieval_suite(suite, BASE/'delivery-v1')
    save(BASE/'evaluation-only/packaging.v1.json', rendered)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
