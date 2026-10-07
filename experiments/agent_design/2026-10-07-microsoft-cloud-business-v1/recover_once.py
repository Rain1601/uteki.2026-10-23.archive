#!/usr/bin/env python3
"""Explicit experiment recovery: same request except output limit, within shared cap."""
import argparse
import asyncio
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from scripts.run_business_revenue_agent import save_preflight
from uteki.agents.business_map.product_run import prepare, execute
from uteki.agents.runtime.local_credentials import load_provider_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    prior = HERE / 'run-01'
    read = lambda name: json.loads((prior / name).read_text())
    result, response = read('result.json'), read('response_metadata.json')
    budget = result['budget']
    if (result['status'] != 'failed' or response['stop_reason'] != 'max_tokens'
            or response['transport_phase'] != 'body_complete'
            or response['usage_presence'] != 'reported' or not response['stream_complete']
            or budget['unknown_requests'] or budget['in_flight_requests']
            or Decimal(budget['held_usd']) != 0 or budget['requests'] != 1
            or result['costs']['unknown_cost_requests']):
        raise ValueError('prior_terminal_failure_and_known_cost_required')
    spent = Decimal(budget['estimated_spent_usd'])
    if spent != Decimal(result['costs']['known_estimated_usd']):
        raise ValueError('prior_cost_mismatch')
    cap = Decimal('0.60')
    remaining = cap - spent
    coverage_path = HERE / 'evaluation/source-coverage-inventory.json'
    coverage_sha = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    if coverage_sha != 'd135c93d6eb35ebcfc13d1ea9859129273972482d0b7876164f862cc05d9bf8e':
        raise ValueError('frozen_evaluation_changed')
    prepared = prepare(root=ROOT, packet_path=HERE / 'input/source_packet.json',
        skill_path=HERE / 'input/skill-v0.5.md', company_id='sec-0000789019',
        document_id='msft-2025-10k', period_end='2025-06-30', model='claude-sonnet-5-5',
        effort='high', max_tokens=24000, timeout_seconds=600, stream=True,
        contract_version='business-draft-v1', wire_mode='full')
    old_request, new_request = read('request.json'), json.loads(prepared['request'])
    if old_request['max_tokens'] != 16000 or new_request['max_tokens'] != 24000:
        raise ValueError('unexpected_output_limits')
    old_request['max_tokens'] = 24000
    if old_request != new_request:
        raise ValueError('recovery_must_only_change_max_tokens')
    for field in ('source_packet_sha256', 'source_sha256', 'skill_sha256',
                  'output_schema_sha256', 'source_wire_sha256'):
        if result[field] != prepared['manifest'][field]:
            raise ValueError('frozen_input_changed')
    reserved = Decimal(prepared['manifest']['reserved_estimated_usd'])
    if remaining <= 0 or reserved > remaining:
        raise ValueError('shared_experiment_budget_insufficient')
    output = HERE / 'run-02'
    if output.exists():
        raise ValueError('recovery_already_started_do_not_resubmit')
    save_preflight(prepared, HERE / 'preflight-v2.json')
    record = dict(schema_version='bounded-recovery-v1', prior_trace_id=result['trace_id'],
        prior_result_sha256=hashlib.sha256((prior / 'result.json').read_bytes()).hexdigest(),
        prior_status='failed', prior_provider_stop_reason='max_tokens',
        changes={'max_tokens': {'before': 16000, 'after': 24000}},
        unchanged=['source_packet', 'skill', 'schema', 'system', 'messages', 'model', 'thinking', 'effort', 'stream'],
        total_budget_usd=str(cap), prior_estimated_spent_usd=str(spent),
        recovery_budget_usd=str(remaining), recovery_reservation_usd=str(reserved),
        max_new_calls=1, automatic_retries=0, actual_billed_usd=None,
        frozen_evaluation_sha256=coverage_sha,
        stop_rule='No run-03 output-limit increase. If max_tokens repeats, redesign output size or bounded stages first.',
        request_sha256=prepared['manifest']['request_sha256'])
    raw = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode()
    path = HERE / 'recovery-decision.json'
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('recovery_decision_changed')
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(raw)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if args.execute:
        load_provider_key(ROOT, 'aihubmix')
        recovered = asyncio.run(execute(prepared, root=ROOT, output=output,
            observation_root=ROOT / 'data/agent_observability/local', budget_limit_usd=str(remaining)))
        print(json.dumps({k: recovered.get(k) for k in ('status', 'trace_id', 'counts', 'budget')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
