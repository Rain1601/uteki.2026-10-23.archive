#!/usr/bin/env python3
"""Prepare source-bound semantic tasks or run the configured metered reviewer."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.infrastructure.research_data.semantic_review import SEMANTIC_PROMPT, prepare_semantic_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    prepare = actions.add_parser('prepare')
    prepare.add_argument('--inputs', type=Path, required=True)
    prepare.add_argument('--tasks', type=Path, required=True, help='Explicit tasks only; no evaluator expectations')
    prepare.add_argument('--output', type=Path, required=True)
    run = actions.add_parser('run')
    run.add_argument('--inputs', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--provider', required=True)
    run.add_argument('--model', required=True)
    run.add_argument('--input-format', choices=('packet_json_v1', 'review_turns_v1'), default='packet_json_v1',
                     help='Optional review-message organization; original JSON envelope remains the default')
    run.add_argument('--budget-ledger', type=Path, required=True)
    run.add_argument('--max-requests-total', type=int, required=True)
    run.add_argument('--budget-usd', required=True)
    run.add_argument('--budget-policy', choices=('record_only', 'enforced'), required=True)
    run.add_argument('--max-attempts-per-packet', type=int, choices=(1, 2, 3), default=1)
    run.add_argument('--semantic-audit', action='store_true',
                     help='Review each valid proposal and feed cited issues into the bounded revision loop')
    run.add_argument('--max-audit-attempts', type=int, choices=(1, 2), default=1,
                     help='Bounded protocol repair attempts per critique, also charged to the same ledger')
    run.add_argument('--credentials-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare_semantic_inputs(args.inputs, json.loads(args.tasks.read_text()), args.output)
        print(json.dumps({'packets': len(result['packets']), 'status': 'prepared_not_reviewed'}))
        return 0
    from uteki.agents.data_query.semantic_review import review_semantics
    from uteki.agents.data_query.record_review_model import SdkRecordReviewer
    from uteki.agents.data_query.coordinator import _verify_manifest
    from uteki.agents.runtime.run_budget import RunBudget
    _verify_manifest(args.inputs.resolve())
    spec = json.loads((args.inputs/'input-manifest.json').read_text())
    frozen = [args.inputs.resolve(), args.output.resolve()]
    if spec.get('dataset'): frozen.append(Path(spec['dataset']).resolve())
    if any(args.budget_ledger.resolve().is_relative_to(path) for path in frozen):
        raise ValueError('ledger must be outside frozen inputs, dataset and output')
    budget = RunBudget(args.budget_ledger, args.budget_usd, enforce=args.budget_policy == 'enforced')
    def factory(output):
        return SdkRecordReviewer(args.provider, args.model, budget=budget,
            max_requests_total=args.max_requests_total, output=output, credentials_root=args.credentials_root,
            prompt=SEMANTIC_PROMPT, max_tokens=16384, request_timeout=180, max_retries=0,
            input_format=args.input_format)
    def audit_factory(output):
        from uteki.infrastructure.research_data.semantic_audit import SEMANTIC_AUDIT_PROMPT
        return SdkRecordReviewer(args.provider, args.model, budget=budget,
            max_requests_total=args.max_requests_total, output=output, credentials_root=args.credentials_root,
            prompt=SEMANTIC_AUDIT_PROMPT, max_tokens=16384, request_timeout=180, max_retries=0,
            input_format=args.input_format)
    result = asyncio.run(review_semantics(args.inputs, args.output, reviewer_factory=factory,
        auditor_factory=audit_factory if args.semantic_audit else None,
        max_audit_attempts=args.max_audit_attempts,
        max_attempts_per_packet=args.max_attempts_per_packet,
        notify=lambda e: print(json.dumps(e, ensure_ascii=False), flush=True)))
    print(json.dumps({k: result[k] for k in ('status', 'packets_requested', 'packets_assessed')}))
    return 0 if result['status'] == 'assessed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
