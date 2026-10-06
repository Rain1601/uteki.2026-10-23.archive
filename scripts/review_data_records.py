#!/usr/bin/env python3
"""Prepare source-bound review inputs or execute an explicitly configured reviewer."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.infrastructure.research_data.record_review import build_review_packets, REVIEW_PROMPT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    prepare = actions.add_parser('prepare')
    prepare.add_argument('--request', type=Path, required=True, help='dataset, scope, record_ids JSON')
    prepare.add_argument('--output', type=Path, required=True)
    repack = actions.add_parser('repack', help='Select unreviewed IDs and deduplicate same-source context')
    repack.add_argument('--inputs', type=Path, required=True)
    repack.add_argument('--record-ids', type=Path, required=True, help='JSON array of explicitly selected record IDs')
    repack.add_argument('--output', type=Path, required=True)
    repack.add_argument('--batch-size', type=int, default=24)
    repack.add_argument('--max-packet-bytes', type=int, default=300000)
    run = actions.add_parser('run')
    run.add_argument('--inputs', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--provider', required=True)
    run.add_argument('--model', required=True)
    run.add_argument('--budget-ledger', type=Path, required=True)
    run.add_argument('--max-requests-total', type=int, required=True)
    run.add_argument('--budget-usd', required=True)
    run.add_argument('--budget-policy', choices=('record_only', 'enforced'), required=True)
    run.add_argument('--max-attempts-per-packet', type=int, choices=(1, 2), default=2)
    run.add_argument('--max-output-tokens', type=int, default=8192)
    run.add_argument('--credentials-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.action == 'prepare':
        request = json.loads(args.request.read_text())
        result = build_review_packets(request['dataset'], request['scope'], request['record_ids'], args.output)
        print(json.dumps({'status': result['status'], 'packets': len(result['packets']), 'records': len(result['record_ids'])}))
        return 0
    if args.action == 'repack':
        from uteki.infrastructure.research_data.record_review_repack import repack_review_inputs
        result = repack_review_inputs(args.inputs, json.loads(args.record_ids.read_text()), args.output,
            batch_size=args.batch_size, max_packet_bytes=args.max_packet_bytes)
        print(json.dumps({'status': result['status'], 'packets': len(result['packets']), 'records': len(result['record_ids'])}))
        return 0
    from uteki.agents.data_query.record_review import review_records
    from uteki.agents.data_query.record_review_model import SdkRecordReviewer
    from uteki.agents.runtime.run_budget import RunBudget
    from uteki.agents.data_query.coordinator import _verify_manifest
    _verify_manifest(args.inputs.resolve())
    spec = json.loads((args.inputs/'input-manifest.json').read_text())
    for frozen in (args.inputs.resolve(), args.output.resolve(), Path(spec['dataset']).resolve()):
        if args.budget_ledger.resolve().is_relative_to(frozen): raise ValueError('ledger must be outside frozen inputs and outputs')
    budget = RunBudget(args.budget_ledger, args.budget_usd, enforce=args.budget_policy == 'enforced')
    def factory(output):
        return SdkRecordReviewer(args.provider, args.model, budget=budget, max_requests_total=args.max_requests_total,
            output=output, credentials_root=args.credentials_root, prompt=REVIEW_PROMPT,
            max_tokens=args.max_output_tokens, request_timeout=180, max_retries=0)
    result = asyncio.run(review_records(args.inputs, args.output, reviewer_factory=factory,
        max_attempts_per_packet=args.max_attempts_per_packet,
        notify=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True)))
    print(json.dumps({k: result[k] for k in ('status','records_requested','records_reviewed','verdict_counts')}, ensure_ascii=False))
    return 0 if result['status'] == 'reviewed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
