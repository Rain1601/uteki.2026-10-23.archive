"""One explicitly configured retrieval acceptance run; no Analysis or publication."""
import argparse
import asyncio
import json
from pathlib import Path

from scripts.run_data_handoff import validate, role_factory
from uteki.agents.data_query.answer_handoff import (
    AnswerAssessment, REVIEW_PROMPT, prepare_review_packet, review_data_answer,
)
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.infrastructure.research_data.financial_records import digest


async def run(config, output):
    request = validate(config, output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / 'config.json', config)
    summary = {'status': 'started', 'model_evaluation': True,
               'publication': 'not_published', 'analysis': 'not_run'}
    try:
        result = await CompanyDataCoordinator(config['workspace']).query(
            config['request'], output=output / 'data-query',
            model_config=config['planner'], worker_model_config=config['worker'],
            credential_root=config['credential_root'])
        summary['query_status'] = result['status']
        print(json.dumps({'stage': 'query', 'status': result['status']}), flush=True)
        if result['status'] not in {'evidence_ready', 'partial', 'limited'}:
            summary['status'] = 'blocked_by_query'
            return summary
        packet = prepare_review_packet(output / 'data-query/query', request.dataset,
            expected_scope=request.scope, max_packet_bytes=config['max_review_packet_bytes'])
        review = await review_data_answer(packet, output / 'data-review',
            reviewer_factory=role_factory(config, 'reviewer', REVIEW_PROMPT, AnswerAssessment))
        summary.update(status='reviewed' if review['analysis_eligible'] else 'review_not_passed',
                       review_status=review['status'], review_ref=review['review_ref'])
        print(json.dumps({'stage': 'review', 'status': review['status']}), flush=True)
        return summary
    except asyncio.CancelledError:
        summary['status'] = 'cancelled'
        raise
    except Exception as error:
        summary.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        write_new(output / 'result.json', summary)
        write_new(output / 'manifest.json', {'files': {
            str(p.relative_to(output)): digest(p.read_bytes())
            for p in sorted(output.rglob('*')) if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.check_only:
        validate(config, args.output.resolve())
        print('local_inputs_valid; no model calls or writes')
    else:
        result = asyncio.run(run(config, args.output.resolve()))
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['status'] == 'reviewed' else 1)
