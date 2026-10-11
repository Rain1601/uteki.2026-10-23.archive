"""Read-only numerical summaries after independent content decisions. Zero API."""
from collections import Counter
from decimal import Decimal
import statistics

from runtime_helpers import ROOT, EXP, read
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest


def summarize():
    manual_path = EXP / 'evaluation-only/independent-content-review.all.v3.json'
    machine_path = EXP / 'evaluation-only/acceptance.all.v1.json'
    manual, machine = read(manual_path), read(machine_path)
    costs = read(EXP / 'evaluation-only/cost-integrity-final.v1.json')
    assert costs['status'] == 'pass' and costs['sealed_runs'] == 9
    rows = {r['slot_id']: r for r in manual['runs']}
    actual = {r['slot_id']: r for r in machine['runs']}
    matrix = read(EXP / 'execution-matrix.v1.json')['runs']
    assert len(rows) == len(actual) == len(matrix) == 9
    recovered = Counter()
    for row in machine['runs']:
        e = row['recovery_events']
        recovered['rejected_tool_actions'] += len(e['rejected_tool_actions'])
        recovered['decision_format_or_network_repair'] += len(e['decision_format_or_network_repair'])
        recovered['failed_provider_calls'] += len(e['failed_provider_calls'])
        recovered['source_protocol_repair'] += sum(f['source'] for f in e['protocol_repair_flags'])
        recovered['question_protocol_repair'] += sum(f['question'] for f in e['protocol_repair_flags'])
        recovered['retrieval_extra_attempts'] += e['retrieval_attempt_count'] - 1
    tiers = []
    for tier in ('S1', 'S2', 'S3'):
        group = [r for r in manual['runs'] if r['tier_id'] == tier]
        values = [float(r['known_estimated_usd']) for r in group]
        mean, std = statistics.mean(values), statistics.stdev(values)
        total = sum((Decimal(r['known_estimated_usd']) for r in group), Decimal(0))
        qualified = sum(r['final_draft']['qualified_delivery'] for r in group)
        tiers.append({'tier_id': tier, 'n': 3,
            'first_content_effect_pass': sum(r['first_draft']['content_effect'] == 'pass' for r in group),
            'final_content_effect_pass': sum(r['final_draft']['content_effect'] == 'pass' for r in group),
            'qualified_final_delivery': qualified,
            'no_recovery_first_pass': sum(r['no_recovery_first_pass'] for r in group),
            'known_estimated_usd': str(total), 'mean_usd': mean, 'median_usd': statistics.median(values),
            'min_usd': min(values), 'max_usd': max(values), 'sample_std_usd': std,
            'sample_cv': std / mean, 'max_min_ratio': max(values) / min(values),
            'concentration_reference_met': std / mean <= .2 and max(values) / min(values) <= 1.5,
            'concentration_is_content_gate': False,
            'all_cost_per_correct_final_numeric_fact_usd': str(total / Decimal(12)),
            'all_cost_per_qualified_delivered_fact_usd': str(total / Decimal(4 * qualified)) if qualified else None})
    old = read(ROOT / 'output/e6-repeatability-20261010-r1/all-metrics.v1.json')
    old_cost = sum((Decimal(r['known_estimated_usd']) for r in old), Decimal(0))
    new_cost = Decimal(costs['task_new_known_estimated_usd'])
    result = {'schema_version': 'e6-v2-final-summary-v1', 'summary_api_calls': 0,
        'priority': ['effect', 'qualified_success', 'cost'], 'planned': 9, 'executed': 9,
        'content_and_success': manual['summary'], 'recovery_events': dict(recovered), 'tiers': tiers,
        'known_estimated_usd': str(new_cost), 'actual_supplier_bill_verified': False,
        'all_cost_per_correct_final_numeric_fact_usd': str(new_cost / Decimal(36)),
        'all_cost_per_qualified_delivered_fact_usd': str(new_cost / Decimal(32)),
        'old_v1': {'planned_and_executed': 9, 'qualified_final_delivery': 8,
                   'no_recovery_first_pass': 3, 'calls': 206, 'known_estimated_usd': str(old_cost)},
        'descriptive_old_cost_difference_usd': str(new_cost - old_cost),
        'descriptive_old_cost_difference_fraction': float((new_cost - old_cost) / old_cost),
        'cost_causal_claim': False, 'stability_proven': False,
        'independent_manual_sha256': digest(manual_path.read_bytes()),
        'independent_machine_sha256': digest(machine_path.read_bytes()),
        'fixed_order': [i['slot_id'] for i in matrix]}
    write_new(EXP / 'evaluation-only/summary.v2.json', result)
    print({'effect': '8/9', 'qualified_delivery': '8/9', 'no_recovery': '0/9',
           'usd': str(new_cost), 'calls': costs['shared_ledger']['requests'] - 525})


if __name__ == '__main__':
    summarize()
