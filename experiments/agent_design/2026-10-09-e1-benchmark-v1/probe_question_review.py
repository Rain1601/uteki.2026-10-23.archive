"""Metered independent question audit of an existing packet; never reads gold."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.question_coverage_review import (
    project_question_review, QuestionCoverageAssessment, QUESTION_REVIEW_PROMPT,
    validate_question_review, question_review_repair_input,
)
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(args):
    config = json.loads(args.config.read_text())
    packet = json.loads(args.packet.read_text())
    _verify_manifest(args.packet.parent)
    fresh = prepare_review_packet(packet['query_ref']['path'], packet['dataset_ref']['path'],
        expected_scope=packet['scope'], max_packet_bytes=packet['max_packet_bytes'],
        source_delivery=packet.get('source_delivery', 'full_indexed_text_v1'),
        source_review_policy=packet.get('source_review_policy'))
    if fresh != packet:
        raise ValueError('Original frozen packet no longer matches canonical sources')
    projected = project_question_review(packet, expected_scope=config['request']['scope'])
    request = projected
    repair_binding = None
    if args.repair_response is not None:
        _verify_manifest(args.repair_response.parent)
        prior_input = json.loads((args.repair_response.parent/'input.json').read_text())
        if prior_input != projected:
            raise ValueError('Repair must use exactly the same frozen projection')
        prior_response = json.loads(args.repair_response.read_text())
        request = question_review_repair_input(projected, prior_response, max_bytes=100000)
        repair_binding = {'response_path': str(args.repair_response.resolve()),
                         'response_sha256': sha(args.repair_response), 'max_repairs': 1}
    model = config['reviewer']
    budget = RunBudget(model['budget_ledger'], model['budget_usd'], enforce=True,
                       allow_unknown_reservations=model.get('allow_unknown_reservations', False))
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output/'input.json', projected)
    if repair_binding is not None:
        write_new(args.output/'repair-input.json', request)
    write_new(args.output/'binding.json', {
        'packet_path': str(args.packet.resolve()), 'packet_sha256': sha(args.packet),
        'projection_policy': 'original_question_and_selected_original_bodies_only',
        'evaluation_answers_used': False,
        'protocol_repair': repair_binding,
    })
    reviewer = None
    result = {'status': 'failed', 'kind': 'independent_question_review_probe',
              'analysis_called': False, 'source_selection_modified': False,
              'not_a_complete_retrieval_run': True}
    try:
        reviewer = SdkRecordReviewer(model['provider'], model['model'], budget=budget,
            max_requests_total=model['max_requests_total'], output=args.output/'model',
            credentials_root=config['credential_root'], prompt=QUESTION_REVIEW_PROMPT,
            output_schema=QuestionCoverageAssessment, max_tokens=8192,
            request_timeout=180, max_retries=1, reasoning_effort=model['reasoning_effort'],
            max_request_bytes=100000)
        raw = await reviewer.review(request)
        write_new(args.output/'response.json', raw)
        normalized, eligible = validate_question_review(projected, raw)
        result.update(status='complete' if eligible else 'needs_more_evidence',
                      assessment=normalized, independent_coverage_eligible=eligible)
    except Exception as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        if reviewer is not None:
            await reviewer.aclose()
            result['usage'] = reviewer.snapshot_usage()
        result['shared_budget'] = budget.summary()
        write_new(args.output/'result.json', result)
        write_new(args.output/'manifest.json', {'files': {
            str(p.relative_to(args.output)): sha(p)
            for p in sorted(args.output.rglob('*')) if p.is_file()}})
    return result['status']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repair-response', type=Path)
    args = parser.parse_args()
    print(asyncio.run(run(args)))
