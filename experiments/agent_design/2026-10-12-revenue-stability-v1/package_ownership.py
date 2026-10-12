"""Compare frozen v1/v2 runs; no model calls or runtime feedback."""
import hashlib
import json
from decimal import Decimal

from apps.review_workbench.pages.data_retrieval_suite import render_data_retrieval_suite
from run_fresh import BASE, ROOT, implementation, ledger, read


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    current = read(BASE/'v2/implementation-freeze.json')
    old = read(BASE/'v1/implementation-freeze.json')
    assert current == implementation()
    changed = sorted(p for p in current.keys() | old.keys() if current.get(p) != old.get(p))
    assert set(changed) == {'src/uteki/agents/data_query/autonomous.py',
        'src/uteki/agents/data_query/decision_protocol.py',
        'src/uteki/agents/data_query/selection_contract.py', 'skills/data-agent/query/SKILL.md'}
    results, cases = [], []
    for version in ('v1', 'v2'):
        for slot in ('R1', 'R2', 'R3'):
            folder = BASE/version/slot
            config = read(folder/'runtime-config.json')
            comparison = read(BASE/'v1'/slot/'runtime-config.json')
            config.pop('workspace'); comparison.pop('workspace')
            assert config == comparison, 'Non-code experiment settings changed'
            audit_file = BASE/f'evaluation-only/{version}-{slot}-audit.json'
            assessment = BASE/f'evaluation-only/{version}-{slot}-semantic-review.md'
            audit = read(audit_file)
            assert assessment.is_file() and audit['combined_delivery_checks']
            cycle = folder/'run'
            rejected = []
            source_selection_actions = []
            for path in sorted(cycle.glob('attempt-*/data-query/query/turn-*/feedback.json')):
                feedback = read(path)
                if feedback.get('receipt', {}).get('action') == 'select_evidence':
                    source_selection_actions.append({'path': str(path.relative_to(ROOT)),
                        'status': feedback['status']})
                if feedback.get('status') == 'rejected':
                    rejected.append({'path': str(path.relative_to(ROOT)),
                        'action': feedback['receipt']['action'], 'reason': feedback.get('reason'),
                        'diagnostic': feedback.get('selection_diagnostic')})
            results.append({'version': version, 'slot': slot,
                'final_delivery_checks': audit['combined_delivery_checks'],
                'manual_review': str(assessment.relative_to(ROOT)), 'manual_review_sha256': sha(assessment),
                'audit_sha256': sha(audit_file), 'no_recovery': audit['no_recovery_first_pass'],
                'source_selection_actions': source_selection_actions,
                'rejected_actions': rejected, 'protocol_repairs': audit['recovery_events']['protocol_repair_flags'],
                'api_calls': audit['api_call_count'], 'estimated_usd': audit['known_estimated_usd']})
            if version == 'v2':
                cases.append({'case_id': slot.lower(), 'cycle_dir': str(cycle),
                    'manifest_sha256': sha(cycle/'manifest.json'),
                    'independent_assessment': {'path': str(assessment), 'sha256': sha(assessment),
                        'attachments': [{'path': audit_file.name, 'sha256': sha(audit_file)}]}})
    before, after = read(BASE/'budget-baseline.v1.json'), ledger()
    assert before['unknown'] == after['unknown']
    assert before['limit'] == after['limit'] and before['request_cap'] == after['request_cap']
    assert all(after['rows'].get(key) == value for key, value in before['rows'].items())
    new = [value for key, value in after['rows'].items() if key not in before['rows']]
    assert all(value['state'] == 'settled' for value in new)
    total = sum((Decimal(row['actual']) for row in new), Decimal(0))
    assert total == sum((Decimal(row['estimated_usd']) for row in results), Decimal(0))
    assert len(new) == sum(row['api_calls'] for row in results)
    summary = {'schema_version': 'ownership-repair-comparison-v1', 'results': results,
        'runtime_changes_only': changed, 'other_configuration_identical': True,
        'runtime_files_unchanged': len(current), 'total_calls_including_v1': len(new),
        'estimated_usd_including_v1': str(total), 'new_unknown': [],
        'remaining_original_task_allowance_usd': str(Decimal('3')-total),
        'historical_reservations_unchanged': len(before['rows']),
        'limitation': 'Three independent runs per version; descriptive comparison, not statistical causation'}
    save(BASE/'evaluation-only/ownership-comparison.v1.json', summary)
    suite = BASE/'suite.v2.json'
    save(suite, {'schema_version': 'data-retrieval-suite-v1', 'cases': cases})
    rendered = render_data_retrieval_suite(suite, BASE/'delivery-v2')
    save(BASE/'evaluation-only/packaging.v2.json', rendered)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
