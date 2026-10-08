"""Run one explicit Data query -> content review -> limited Analysis experiment."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, _verify_manifest
from uteki.agents.data_query.answer_handoff import (
    AnswerAssessment, REVIEW_PROMPT, prepare_review_packet, review_data_answer,
)
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.data_query.autonomous_model import reasoning_configuration
from uteki.agents.analysis.data_consumer import DataAnalysisAnswer, ANALYSIS_PROMPT, analyze_reviewed_data
from uteki.agents.runtime.run_budget import RunBudget, reserve_request
from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.financial_records import digest


def validate(config, output):
    required = {'request', 'planner', 'worker', 'reviewer', 'analyst', 'credential_root',
                'workspace', 'max_review_packet_bytes'}
    if not required <= set(config) or set(config) - required - {'request_envelope_limits', 'source_delivery'}:
        raise ValueError('explicit handoff configuration fields required; unknown fields rejected')
    if config.get('source_delivery', 'query_evidence_v1') not in {'query_evidence_v1', 'full_indexed_text_v1'}:
        raise ValueError('explicit supported source delivery required')
    if 'request_envelope_limits' in config:
        limits = config['request_envelope_limits']
        if (not isinstance(limits, dict) or set(limits) != {'reviewer', 'analyst'}
                or any(type(value) is not int or value < 1024 for value in limits.values())):
            raise ValueError('explicit positive reviewer and analyst request envelope limits required')
    request = CompanyQueryInput.model_validate(config['request'])
    if not request.dataset or request.scope is None:
        raise ValueError('first handoff adapter requires an explicit frozen dataset and scope')
    if type(config['max_review_packet_bytes']) is not int or config['max_review_packet_bytes'] < 1024:
        raise ValueError('explicit review input capacity required')
    output = Path(output).resolve()
    dataset = Path(request.dataset).resolve()
    if output.is_relative_to(dataset) or output.exists():
        raise ValueError('output must be new and outside frozen data')
    _verify_manifest(dataset)
    port = QueryDataPort(dataset)
    try:
        port.scoped(request.scope).discover_data()
    finally:
        port.close()
    for role in ('planner', 'worker', 'reviewer', 'analyst'):
        model = config[role]
        CompanyDataCoordinator._validate_shared_model_configs(config['planner'], model)
        _, _, native = reasoning_configuration(model['provider'], model['model'], model.get('reasoning_effort'))
        runtime_fields = {'max_tokens', 'request_timeout', 'max_retries', 'reasoning_effort'}
        if not runtime_fields <= set(model):
            raise ValueError(f'{role} requires explicit token, timeout, retry and reasoning settings')
        max_output_tokens = 8192 if role in {'planner', 'worker'} else (16000 if native else 16384)
        if type(model['max_tokens']) is not int or not 256 <= model['max_tokens'] <= max_output_tokens:
            raise ValueError(f'{role} has unsupported max_tokens')
        timeout = model['request_timeout']
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise ValueError(f'{role} has unsupported request_timeout')
        if type(model['max_retries']) is not int or not 0 <= model['max_retries'] <= 3:
            raise ValueError(f'{role} has unsupported max_retries')
        if model['provider'] == 'deepseek' and model['reasoning_effort'] is None:
            raise ValueError(f'{role} requires an explicit DeepSeek reasoning setting')
        if role in {'reviewer', 'analyst'} and model['provider'] != 'deepseek' and not native:
            raise ValueError('review and Analysis require registered DeepSeek or native Claude models')
        if pricing_snapshot(model['provider'], model['model']) is None:
            raise ValueError(f'{role} model has no registered pricing or adapter')
        ledger = Path(model['budget_ledger']).resolve()
        if ledger.is_relative_to(output) or ledger.is_relative_to(dataset):
            raise ValueError('shared ledger must be outside frozen datasets and pipeline output')
    return request


def role_factory(config, name, prompt, schema):
    model = config[name]
    def make(output):
        budget = RunBudget(model['budget_ledger'], model['budget_usd'],
                          enforce=model['budget_policy'] == 'enforced',
                          allow_unknown_reservations=model.get('allow_unknown_reservations', False))
        return SdkRecordReviewer(model['provider'], model['model'], budget=budget,
            max_requests_total=model['max_requests_total'], output=output,
            credentials_root=config['credential_root'], prompt=prompt, output_schema=schema,
            max_tokens=model['max_tokens'], request_timeout=model['request_timeout'],
            max_retries=model['max_retries'], reasoning_effort=model['reasoning_effort'],
            max_request_bytes=config.get('request_envelope_limits', {}).get(name, 400000))
    return make


def prepare_resume(config, request, output, query_run, query_manifest_sha256):
    if query_run is None and query_manifest_sha256 is None:
        return None
    if query_run is None or not query_manifest_sha256:
        raise ValueError('resuming requires a query directory and its externally pinned manifest hash')
    query_run = Path(query_run).resolve()
    if Path(output).resolve().is_relative_to(query_run):
        raise ValueError('resume output cannot modify the frozen query')
    _verify_manifest(query_run, query_manifest_sha256)
    packet = prepare_review_packet(query_run, request.dataset, expected_scope=request.scope,
                                   max_packet_bytes=config['max_review_packet_bytes'],
                                   source_delivery=config.get('source_delivery', 'query_evidence_v1'))
    if packet['question'] != request.question:
        raise ValueError('resumed query question differs from explicit request')
    return packet


async def run(config, output, *, query_run=None, query_manifest_sha256=None):
    request = validate(config, output)
    packet = prepare_resume(config, request, output, query_run, query_manifest_sha256)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'config.json', config)
    components = [Path(__file__), Path(prepare_review_packet.__code__.co_filename),
        Path(analyze_reviewed_data.__code__.co_filename), Path(SdkRecordReviewer.__init__.__code__.co_filename),
        Path(reserve_request.__code__.co_filename), Path(MeteredModel.get_response.__code__.co_filename)]
    write_new(output/'implementation.json', {str(p.resolve()): digest(p.read_bytes()) for p in components})
    summary = {'schema_version': 'data-handoff-experiment-v1', 'status': 'failed',
        'scope': request.scope.model_dump(mode='json'), 'stages': {},
        'publication': 'not_published', 'investment_decision': 'not_evaluated'}
    cancelled = False
    try:
        if packet is None:
            coordinator = CompanyDataCoordinator(config['workspace'])
            query = await coordinator.query(config['request'], output=output/'data-query',
                model_config=config['planner'], worker_model_config=config['worker'],
                credential_root=config['credential_root'])
            summary['stages']['query'] = {'path': 'data-query', 'status': query['status'], 'execution': 'new'}
        else:
            summary['stages']['query'] = {**packet['query_ref'], 'status': packet['query_status'],
                                         'execution': 'reused_frozen'}
        query_status = summary['stages']['query']['status']
        print(json.dumps({'stage': 'query', 'status': query_status,
            'execution': summary['stages']['query']['execution']}, ensure_ascii=False), flush=True)
        if query_status not in {'evidence_ready', 'partial', 'limited'}:
            summary['status'] = 'blocked_by_query'
            return summary
        if packet is None:
            packet = prepare_review_packet(output/'data-query/query', request.dataset,
                expected_scope=request.scope, max_packet_bytes=config['max_review_packet_bytes'],
                source_delivery=config.get('source_delivery', 'query_evidence_v1'))
        review = await review_data_answer(packet, output/'data-review',
            reviewer_factory=role_factory(config, 'reviewer', REVIEW_PROMPT, AnswerAssessment))
        summary['stages']['review'] = {'path': 'data-review', 'status': review['status'],
            'review_ref': review['review_ref'], 'analysis_eligible': review['analysis_eligible']}
        print(json.dumps({'stage': 'review', 'status': review['status']}, ensure_ascii=False), flush=True)
        if not review['analysis_eligible']:
            summary['status'] = 'blocked_by_content_review'
            return summary
        analysis = await analyze_reviewed_data(output/'data-review', output/'analysis',
            expected_scope=request.scope, expected_review_manifest_sha256=review['review_ref']['manifest_sha256'],
            analyst_factory=role_factory(config, 'analyst', ANALYSIS_PROMPT, DataAnalysisAnswer))
        summary['stages']['analysis'] = {'path': 'analysis', 'status': analysis['status']}
        summary['status'] = ('candidate_pending_analysis_review' if analysis['status'] == 'candidate_pending_content_review'
                             else 'analysis_failed')
    except asyncio.CancelledError:
        cancelled = True
        summary['status'] = 'cancelled'
    except Exception as error:
        summary.update(status='failed', error_type=type(error).__name__)
    finally:
        write_new(output/'result.json', summary)
        write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
            for p in sorted(output.rglob('*')) if p.is_file()}})
    if cancelled:
        raise asyncio.CancelledError()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--query-run', type=Path, help='Resume review from a sealed query without new Data calls')
    parser.add_argument('--query-manifest-sha256', help='Required external manifest hash for --query-run')
    parser.add_argument('--check-only', action='store_true', help='Validate local inputs without models or writes')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.check_only:
        request = validate(config, args.output)
        prepare_resume(config, request, args.output, args.query_run, args.query_manifest_sha256)
        print('local_inputs_valid; no model calls or output writes')
        return 0
    result = asyncio.run(run(config, args.output, query_run=args.query_run,
                             query_manifest_sha256=args.query_manifest_sha256))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'candidate_pending_analysis_review' else 1


if __name__ == '__main__':
    raise SystemExit(main())
