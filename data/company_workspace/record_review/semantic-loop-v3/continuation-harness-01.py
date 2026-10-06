"""Continue an authentic rejected model draft; distinguish replay from new calls.

This evaluation harness never reads expected answers. It preserves the complete
prior run and uses its rejected response as the first proposal in the existing
runtime so the host, rather than this script, derives all repair feedback.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.data_query.semantic_review import review_semantics
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained
from uteki.infrastructure.research_data.semantic_review import SEMANTIC_PROMPT
from uteki.infrastructure.research_data.semantic_audit import SEMANTIC_AUDIT_PROMPT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'prior-run', 'output', 'budget-ledger', 'credentials-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--packet-number', type=int, required=True)
    parser.add_argument('--attempt-number', type=int, required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--max-requests-total', type=int, required=True)
    parser.add_argument('--budget-usd', required=True)
    args = parser.parse_args()
    if args.packet_number < 1 or args.attempt_number < 1:
        raise ValueError('positive explicit packet and attempt numbers required')
    inputs, prior, output = args.inputs.resolve(), args.prior_run.resolve(), args.output.resolve()
    if any(args.budget_ledger.resolve().is_relative_to(root) for root in (inputs, prior, output)):
        raise ValueError('shared ledger must be outside frozen input/run directories')
    _verify_manifest(inputs); _verify_manifest(prior)
    if output.is_relative_to(inputs) or output.is_relative_to(prior):
        raise ValueError('continuation must be outside frozen artifacts')
    prior_request = json.loads((prior/'request.json').read_text())
    if prior_request['input_manifest_sha256'] != digest((inputs/'manifest.json').read_bytes()):
        raise ValueError('prior run does not match inputs')
    spec = json.loads((inputs/'input-manifest.json').read_text())
    if spec['source_origin'] != 'synthetic_fixture':
        raise ValueError('this evaluation harness supports explicit synthetic packets only')
    ref = spec['packets'][args.packet_number-1]
    packet = json.loads(contained(inputs, ref['path']).read_text())
    prefix = prior/f'packet-{args.packet_number:03d}/attempt-{args.attempt_number}'
    draft_path = Path(str(prefix)+'-response.json')
    rejection_path = Path(str(prefix)+'-rejection.json')
    rejection = json.loads(rejection_path.read_text())
    draft = json.loads(draft_path.read_text())
    if rejection['stage'] != 'proposal' or draft['packet_id'] != packet['packet_id']:
        raise ValueError('an authentic proposal rejection for this packet is required')
    if output.exists():
        raise FileExistsError('continuation output already exists')
    output.mkdir(parents=True)
    write_new(output/'continuation.json', {
        'method': 'historical_model_draft_replay_then_new_model_revision_and_audit',
        'evaluation_role': 'development_regression_not_new_heldout',
        'prior_inputs': str(inputs), 'prior_manifest_sha256': digest((prior/'manifest.json').read_bytes()),
        'prior_response': str(draft_path), 'prior_response_sha256': digest(draft_path.read_bytes()),
        'prior_rejection_sha256': digest(rejection_path.read_bytes()),
        'historical_replays': 1, 'maximum_new_requests': 2,
        'expected_answers_provided': False})
    selected = output/'inputs'
    write_new(selected/'packets/001.json', packet)
    new_ref = {**ref, 'path': 'packets/001.json', 'sha256': digest((selected/'packets/001.json').read_bytes())}
    write_new(selected/'input-manifest.json', {**spec, 'packets': [new_ref]})
    write_new(selected/'manifest.json', {'files': {str(p.relative_to(selected)): digest(p.read_bytes())
        for p in selected.rglob('*') if p.is_file()}})
    budget = RunBudget(args.budget_ledger, args.budget_usd, enforce=False)

    def actor(path, prompt):
        return SdkRecordReviewer(args.provider, args.model, budget=budget,
            max_requests_total=args.max_requests_total, output=path, credentials_root=args.credentials_root,
            prompt=prompt, max_tokens=16384, request_timeout=180, max_retries=0)

    class ContinueReviewer:
        plan_origin = 'recorded_model_replay_then_model'

        def __init__(self, path):
            self.model, self.replayed = actor(path, SEMANTIC_PROMPT), False

        async def review(self, request):
            if not self.replayed:
                if request != packet:
                    raise ValueError('historical replay must receive the identical packet')
                self.replayed = True
                return deepcopy(draft)
            return await self.model.review(request)

        async def aclose(self):
            await self.model.aclose()

        def snapshot_usage(self):
            return {**self.model.snapshot_usage(), 'historical_replays': int(self.replayed)}

    result = asyncio.run(review_semantics(selected, output/'run', reviewer_factory=ContinueReviewer,
        auditor_factory=lambda path: actor(path, SEMANTIC_AUDIT_PROMPT),
        max_attempts_per_packet=2, max_audit_attempts=1))
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in output.rglob('*') if p.is_file()}})
    print(json.dumps({k: result[k] for k in ('status', 'plan_origin', 'packets_assessed')}))


if __name__ == '__main__':
    main()
