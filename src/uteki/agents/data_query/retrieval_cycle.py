"""Bounded Data retrieval and content review, without an Analysis model stage."""
import asyncio
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import re

from .artifacts import write_new
from . import answer_handoff as handoff_module, coordinator as coordinator_module
from .coordinator import CompanyDataCoordinator, _verify_manifest
from .answer_handoff import AnswerAssessment, REVIEW_PROMPT, prepare_review_packet, review_data_answer
from .autonomous_model import reasoning_configuration
from .record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.runtime.call_costs import pricing_snapshot
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.financial_records import digest


def validate(config, output):
    required = {'request', 'planner', 'worker', 'reviewer', 'credential_root', 'workspace',
                'max_review_packet_bytes', 'max_attempts'}
    if not required <= set(config) or set(config) - required - {'reviewer_max_request_bytes', 'initial_query_ref'}:
        raise ValueError('explicit retrieval configuration required; unknown fields rejected')
    if type(config['max_attempts']) is not int or not 1 <= config['max_attempts'] <= 3:
        raise ValueError('max_attempts must be an explicit integer between 1 and 3')
    request = CompanyQueryInput.model_validate(config['request'])
    if not request.dataset or request.scope is None or request.purpose != 'analysis_evidence':
        raise ValueError('Data retrieval requires frozen dataset, explicit scope and analysis_evidence purpose')
    if request.review_feedback:
        raise ValueError('initial request cannot contain externally supplied review feedback')
    if request.financial_tasks:
        raise ValueError('retrieval cycle does not configure registered financial extraction jobs')
    for field in ('max_review_packet_bytes', 'reviewer_max_request_bytes'):
        value = config.get(field, 400000)
        if type(value) is not int or value < 1024:
            raise ValueError(field + ' must be an explicit byte capacity >= 1024')
    output, dataset = Path(output).resolve(), Path(request.dataset).resolve()
    if output.exists() or output.is_relative_to(dataset):
        raise ValueError('output must be new and outside frozen dataset')
    _verify_manifest(dataset)
    with QueryDataPort(dataset) as port:
        port.scoped(request.scope).discover_data()
    for role in ('planner', 'worker', 'reviewer'):
        model = config[role]
        CompanyDataCoordinator._validate_shared_model_configs(config['planner'], model)
        _, _, native = reasoning_configuration(model['provider'], model['model'], model.get('reasoning_effort'))
        if not {'max_tokens', 'request_timeout', 'max_retries', 'reasoning_effort'} <= model.keys():
            raise ValueError(role + ' requires explicit token, timeout, retry and reasoning settings')
        maximum = (16000 if native else 16384) if role == 'reviewer' else 8192
        if type(model['max_tokens']) is not int or not 256 <= model['max_tokens'] <= maximum:
            raise ValueError(role + ' has unsupported max_tokens')
        timeout = model['request_timeout']
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError(role + ' has unsupported request_timeout')
        if type(model['max_retries']) is not int or not 0 <= model['max_retries'] <= 3:
            raise ValueError(role + ' has unsupported max_retries')
        if model['provider'] == 'deepseek' and model['reasoning_effort'] is None:
            raise ValueError(role + ' requires explicit reasoning settings')
        if role == 'reviewer' and model['provider'] != 'deepseek' and not native:
            raise ValueError('review requires a registered DeepSeek or native Claude model')
        if pricing_snapshot(model['provider'], model['model']) is None:
            raise ValueError(role + ' has no registered pricing')
        ledger = Path(model['budget_ledger']).resolve()
        if ledger.is_relative_to(output) or ledger.is_relative_to(dataset):
            raise ValueError('shared ledger must be outside frozen data and retrieval output')
    prepare_initial_query(config, request, output)
    return request


def prepare_initial_query(config, request, output):
    """Resume only a pinned coordinator root with matching task and query roles."""
    if 'initial_query_ref' not in config:
        return None
    ref = config['initial_query_ref']
    if (not isinstance(ref, dict) or set(ref) != {'path', 'manifest_sha256'}
            or not isinstance(ref['path'], str) or not ref['path'].strip()
            or not re.fullmatch(r'[0-9a-f]{64}', str(ref['manifest_sha256']))):
        raise ValueError('initial query requires a frozen coordinator path and manifest hash')
    root = Path(ref['path']).resolve()
    if Path(output).resolve().is_relative_to(root):
        raise ValueError('resume output cannot modify the frozen coordinator run')
    manifest = _verify_manifest(root, ref['manifest_sha256'])
    required = {'request.json', 'result.json', 'scope.json', 'query/manifest.json',
                'model-config.input.json', 'worker-model-config.input.json'}
    if not required <= set(manifest['files']):
        raise ValueError('initial query reference must point to a complete coordinator root')
    read = lambda name: json.loads((root/name).read_text())
    prior = CompanyQueryInput.model_validate(read('request.json'))
    # A resumed follow-up may have its own earlier review feedback. Keep that
    # history, but never let it replace the newly selected task or scope.
    expected = request.model_dump(mode='json', exclude={'review_feedback'})
    actual = prior.model_dump(mode='json', exclude={'review_feedback'})
    if not prior.dataset or Path(prior.dataset).resolve() != Path(request.dataset).resolve():
        raise ValueError('initial query dataset differs from current request')
    actual['dataset'] = expected['dataset']
    if actual != expected:
        raise ValueError('initial query request differs from current question, purpose, scope or limits')
    for role, name in [('planner','model-config.input.json'), ('worker','worker-model-config.input.json')]:
        if read(name) != config[role]:
            raise ValueError('initial query model configuration differs from current ' + role)
    result = read('result.json')
    scope = request.scope.model_dump(mode='json')
    if (result.get('schema_version') != 'company-agent-result-v1' or result.get('operation') != 'query'
            or result.get('query_run') != 'query' or result.get('status') not in {'evidence_ready','partial','limited'}
            or result.get('active_scope') != scope or read('scope.json') != scope):
        raise ValueError('initial coordinator result does not bind a reviewable same-scope query')
    dataset_ref = result.get('dataset') or {}
    if Path(dataset_ref.get('path', '')).resolve() != Path(request.dataset).resolve():
        raise ValueError('initial coordinator dataset identity differs')
    _verify_manifest(request.dataset, dataset_ref.get('manifest_sha256'))
    if dataset_ref.get('manifest_sha256') != digest((Path(request.dataset)/'manifest.json').read_bytes()):
        raise ValueError('initial coordinator dataset hash differs')
    _verify_manifest(root/'query', manifest['files']['query/manifest.json'])
    child = read('query/result.json')
    if (child.get('schema_version') != 'autonomous-result-v2' or child.get('purpose') != request.purpose
            or child.get('request', {}).get('question') != request.question
            or child.get('request', {}).get('scope') != scope or child.get('active_scope') != scope
            or child.get('status') != result['status']):
        raise ValueError('initial inner query differs from coordinator task')
    return {'query':result, 'coordinator_ref':{'path':str(root), 'manifest_sha256':ref['manifest_sha256']},
            'query_path':root/'query'}


def reviewer_factory(config):
    model = config['reviewer']
    def make(output):
        budget = RunBudget(model['budget_ledger'], model['budget_usd'],
            enforce=model['budget_policy'] == 'enforced',
            allow_unknown_reservations=model.get('allow_unknown_reservations', False))
        return SdkRecordReviewer(model['provider'], model['model'], budget=budget,
            max_requests_total=model['max_requests_total'], output=output,
            credentials_root=config['credential_root'], prompt=REVIEW_PROMPT, output_schema=AnswerAssessment,
            max_tokens=model['max_tokens'], request_timeout=model['request_timeout'],
            max_retries=model['max_retries'], reasoning_effort=model['reasoning_effort'],
            max_request_bytes=config.get('reviewer_max_request_bytes', 400000))
    return make


def _reference(path):
    path = Path(path).resolve()
    _verify_manifest(path)
    return {'path': str(path), 'manifest_sha256': digest((path/'manifest.json').read_bytes())}


def _seal(path):
    write_new(path/'manifest.json', {'files': {str(p.relative_to(path)): digest(p.read_bytes())
        for p in sorted(path.rglob('*')) if p.is_file()}})


async def run_retrieval_cycle(config, output):
    """Every follow-up reuses the original task and a pinned prior assessment.

    SDK retry settings apply within a review call. In addition, a failed review
    stage can run once more in a fresh directory, using the same budget ledger.
    An unreviewed partial response never becomes follow-up instructions.
    """
    config = deepcopy(config)
    request = validate(config, output)
    initial = prepare_initial_query(config, request, output)
    original = request.model_dump(mode='json', exclude_none=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'config.json', config)
    write_new(output/'original-request.json', original)
    component_modules = ('uteki.agents.data_query.autonomous', 'uteki.agents.data_query.autonomous_model',
        'uteki.agents.data_query.decision_protocol', 'uteki.agents.runtime.claude_messages',
        'uteki.infrastructure.research_data.query_service', 'uteki.infrastructure.research_data.record_locator',
        'uteki.agents.reading.reading_groups', 'uteki.infrastructure.research_data.materialization_metadata')
    components = (Path(__file__), Path(handoff_module.__file__),
                  Path(coordinator_module.__file__),
                  Path(SdkRecordReviewer.__init__.__code__.co_filename),
                  *(Path(import_module(name).__file__) for name in component_modules))
    write_new(output/'implementation.json', {str(p.resolve()): digest(p.read_bytes()) for p in components})
    result = {'schema_version':'data-retrieval-cycle-v1', 'status':'failed',
        'question':request.question, 'scope':request.scope.model_dump(mode='json'),
        'purpose':request.purpose, 'source_delivery':'query_evidence_v1', 'attempts':[],
        'max_attempts':config['max_attempts'], 'final_query_ref':None, 'final_review_ref':None,
        'analysis_called':False, 'adoption':'unchanged_candidate', 'failures':[]}
    cancelled, feedback = False, None
    try:
        coordinator = CompanyDataCoordinator(config['workspace'])
        for ordinal in range(1, config['max_attempts'] + 1):
            folder = output/f'attempt-{ordinal:02d}'
            folder.mkdir()
            call = deepcopy(original)
            if feedback is not None:
                call['review_feedback'] = deepcopy(feedback)
            write_new(folder/'request.json', call)
            attempt = {'attempt':ordinal, 'path':folder.name, 'status':'running', 'reviews':[]}
            result['attempts'].append(attempt)
            try:
                if ordinal == 1 and initial is not None:
                    query = initial['query']
                    query_path = initial['query_path']
                    attempt.update(execution='reused_frozen', query_run_ref=initial['coordinator_ref'])
                else:
                    query = await coordinator.query(call, output=folder/'data-query',
                        model_config=deepcopy(config['planner']), worker_model_config=deepcopy(config['worker']),
                        credential_root=config['credential_root'])
                    query_path = folder/'data-query/query'
                    attempt.update(execution='new', query_run_ref=_reference(folder/'data-query'))
                attempt['query_status'] = query['status']
                if query['status'] not in {'evidence_ready', 'partial', 'limited'}:
                    attempt['status'] = result['status'] = 'blocked_by_query'
                    break
                packet = prepare_review_packet(query_path, request.dataset,
                    expected_scope=request.scope, max_packet_bytes=config['max_review_packet_bytes'],
                    source_delivery='query_evidence_v1')
                if packet['question'] != request.question or packet['scope'] != result['scope']:
                    raise ValueError('retrieval packet changed original question or scope')
                write_new(folder/'review-packet.json', packet)
                attempt['query_ref'] = result['final_query_ref'] = packet['query_ref']
                result['final_review_ref'] = None
                review = None
                for review_ordinal in (1, 2):
                    review_path = folder/f'review-{review_ordinal:02d}'
                    try:
                        review = await review_data_answer(packet, review_path,
                            reviewer_factory=reviewer_factory(config))
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        # Preparation errors occur before a paid review stage.
                        # Preserve a separate receipt; never fabricate or replace
                        # a stage manifest that a callee may already have saved.
                        failure = {'status':'failed','analysis_eligible':False,
                                   'error_type':type(error).__name__, 'path':str(review_path)}
                        write_new(folder/f'review-{review_ordinal:02d}-failure.json', failure)
                        attempt['reviews'].append(failure)
                        raise
                    attempt['reviews'].append({'status':review['status'], 'review_ref':review['review_ref'],
                        'analysis_eligible':review['analysis_eligible']})
                    result['final_review_ref'] = review['review_ref']
                    if review['status'] != 'failed':
                        break
                if review['status'] == 'reviewed' and review['analysis_eligible']:
                    attempt['status'] = result['status'] = 'reviewed_data_ready'
                    break
                if review['status'] != 'needs_revision' or not review.get('assessment'):
                    attempt['status'] = result['status'] = 'blocked_by_review_failure'
                    break
                feedback = {'prior_query_ref':packet['query_ref'], 'prior_review_ref':review['review_ref'],
                            'assessment':review['assessment']}
                attempt['status'] = 'needs_revision'
                result['status'] = 'attempts_exhausted'
            except asyncio.CancelledError:
                attempt['status'] = 'cancelled'
                raise
            except Exception as error:
                attempt.update(status='failed', error_type=type(error).__name__)
                raise
            finally:
                write_new(folder/'result.json', attempt)
                _seal(folder)
    except asyncio.CancelledError:
        cancelled = True
        result['status'] = 'cancelled'
    except Exception as error:
        result.update(status='failed')
        result['failures'].append({'error_type':type(error).__name__})
    finally:
        write_new(output/'result.json', result)
        _seal(output)
    if cancelled:
        raise asyncio.CancelledError()
    return result
