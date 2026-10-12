"""Bounded Data retrieval and content review, without an Analysis model stage."""
import asyncio
from copy import deepcopy
from contextlib import closing
from decimal import Decimal, InvalidOperation
from importlib import import_module
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .artifacts import write_new
from . import answer_handoff as handoff_module, coordinator as coordinator_module
from .coordinator import CompanyDataCoordinator, _verify_manifest
from .answer_handoff import AnswerAssessment, QUESTION_REVIEW_POLICY, review_prompt, source_assessment_schema, prepare_review_packet, review_data_answer, validate_source_revision_feedback
from .autonomous_model import reasoning_configuration
from .record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.runtime.call_costs import pricing_snapshot
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.financial_records import digest


def review_roles(config):
    """Do not inject optional fields into historical configurations."""
    present = ('question_reviewer' in config, 'question_review_policy' in config)
    if present[0] != present[1]:
        raise ValueError('question_reviewer and question_review_policy must be supplied together')
    if present[0] and (config['question_review_policy'] != QUESTION_REVIEW_POLICY
                       or not isinstance(config['question_reviewer'], dict)):
        raise ValueError('unsupported independent question review configuration')
    return ('planner', 'worker', 'reviewer') + (('question_reviewer',) if present[0] else ())


def validate(config, output):
    required = {'request', 'planner', 'worker', 'reviewer', 'credential_root', 'workspace',
                'max_review_packet_bytes', 'max_attempts'}
    if not required <= set(config) or set(config) - required - {'reviewer_max_request_bytes', 'initial_query_ref', 'question_reviewer', 'question_review_policy'}:
        raise ValueError('explicit retrieval configuration required; unknown fields rejected')
    if type(config['max_attempts']) is not int or not 1 <= config['max_attempts'] <= 3:
        raise ValueError('max_attempts must be an explicit integer between 1 and 3')
    request = CompanyQueryInput.model_validate(config['request'])
    if not request.dataset or request.scope is None or request.purpose != 'analysis_evidence':
        raise ValueError('Data retrieval requires frozen dataset, explicit scope and analysis_evidence purpose')
    if request.figure_bundle_ref is not None and 'question_reviewer' not in review_roles(config):
        raise ValueError('figure retrieval requires independent source and question review')
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
    if request.figure_bundle_ref is not None:
        bundle = Path(request.figure_bundle_ref.path).resolve()
        if output.is_relative_to(bundle) or Path(config['workspace']).resolve().is_relative_to(bundle):
            raise ValueError('output and workspace must be outside the frozen figure supplement')
    _verify_manifest(dataset)
    with QueryDataPort(dataset) as port:
        if request.figure_bundle_ref is not None:
            port.bind_figures(request.figure_bundle_ref)
        port.scoped(request.scope).discover_data()
    for role in review_roles(config):
        model = config[role]
        CompanyDataCoordinator._validate_shared_model_configs(config['planner'], model)
        _, _, native = reasoning_configuration(model['provider'], model['model'], model.get('reasoning_effort'))
        if not {'max_tokens', 'request_timeout', 'max_retries', 'reasoning_effort'} <= model.keys():
            raise ValueError(role + ' requires explicit token, timeout, retry and reasoning settings')
        maximum = (16000 if native else 16384) if role in {'reviewer', 'question_reviewer'} else 8192
        if type(model['max_tokens']) is not int or not 256 <= model['max_tokens'] <= maximum:
            raise ValueError(role + ' has unsupported max_tokens')
        timeout = model['request_timeout']
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError(role + ' has unsupported request_timeout')
        if type(model['max_retries']) is not int or not 0 <= model['max_retries'] <= 3:
            raise ValueError(role + ' has unsupported max_retries')
        if model['provider'] == 'deepseek' and model['reasoning_effort'] is None:
            raise ValueError(role + ' requires explicit reasoning settings')
        if role in {'reviewer', 'question_reviewer'} and model['provider'] != 'deepseek' and not native:
            raise ValueError('review requires a registered DeepSeek or native Claude model')
        if pricing_snapshot(model['provider'], model['model']) is None:
            raise ValueError(role + ' has no registered pricing')
        ledger = Path(model['budget_ledger']).resolve()
        if (ledger.is_relative_to(output) or ledger.is_relative_to(dataset)
                or (request.figure_bundle_ref is not None and ledger.is_relative_to(bundle))):
            raise ValueError('shared ledger must be outside frozen data and retrieval output')
    prepare_initial_query(config, request, output)
    return request


def _resume_budget_increase(prior, current):
    """Read an already-authorized increase; never create or change an allowance."""
    error = 'initial query budget increase requires the same ledger and a complete recorded authorization chain'
    if ({k:v for k,v in prior.items() if k != 'budget_usd'}
            != {k:v for k,v in current.items() if k != 'budget_usd'}
            or prior.get('budget_policy') != 'enforced'):
        raise ValueError(error)
    try:
        old, new = Decimal(str(prior['budget_usd'])), Decimal(str(current['budget_usd']))
        if not old.is_finite() or not new.is_finite() or not 0 < old < new:
            raise ValueError(error)
        ledger = Path(current['budget_ledger']).resolve()
        if not ledger.is_file():
            raise ValueError(error)
        # mode=ro honors a live WAL and cannot initialize a missing database.
        with closing(sqlite3.connect(ledger.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            limit = db.execute('SELECT usd FROM config WHERE id=1').fetchone()
            rows = db.execute('SELECT id, record FROM limit_authorizations').fetchall()
        if not limit or Decimal(limit[0]) != new:
            raise ValueError(error)
        transitions = {}
        for identity, raw in rows:
            record = json.loads(raw)
            if (not isinstance(record, dict) or not isinstance(record.get('authorization'), dict)
                    or any(not isinstance(record.get(k), str) or not record[k].strip()
                           for k in ('old_limit_usd', 'new_limit_usd', 'applied_at', 'authorization_sha256'))):
                raise ValueError(error)
            auth = record['authorization']
            body = json.dumps(auth, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            before, after = Decimal(record['old_limit_usd']), Decimal(record['new_limit_usd'])
            if (not before.is_finite() or not after.is_finite() or not 0 < before < after
                    or auth.get('authorized_by') != 'user' or auth.get('authorization_id') != identity
                    or any(not isinstance(auth.get(k), str) or not auth[k].strip()
                           for k in ('authorization_id', 'confirmation', 'scope'))
                    or auth.get('old_limit_usd') != record['old_limit_usd']
                    or auth.get('new_limit_usd') != record['new_limit_usd']
                    or hashlib.sha256(body.encode()).hexdigest() != record['authorization_sha256']
                    or before in transitions):
                raise ValueError(error)
            transitions[before] = (after, record)
        cursor, chain = old, []
        while cursor < new:
            if cursor not in transitions:
                raise ValueError(error)
            cursor, record = transitions[cursor]
            chain.append(record)
        if cursor != new:
            raise ValueError(error)
        return {'ledger_path': str(ledger), 'old_limit_usd': str(old), 'new_limit_usd': str(new),
                'authorization_records': chain}
    except (sqlite3.Error, InvalidOperation, TypeError, KeyError, OverflowError) as exc:
        raise ValueError(error) from exc


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
    budget_changes = {}
    for role, name in [('planner','model-config.input.json'), ('worker','worker-model-config.input.json')]:
        previous = read(name)
        if previous != config[role]:
            budget_changes[role] = _resume_budget_increase(previous, config[role])
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
            'query_path':root/'query', 'budget_changes': budget_changes}


def _review_role_factory(config, role, prompt, output_schema, *, output_projection=None):
    model = config[role]
    def make(output):
        budget = RunBudget(model['budget_ledger'], model['budget_usd'],
            enforce=model['budget_policy'] == 'enforced',
            allow_unknown_reservations=model.get('allow_unknown_reservations', False))
        return SdkRecordReviewer(model['provider'], model['model'], budget=budget,
            max_requests_total=model['max_requests_total'], output=output,
            credentials_root=config['credential_root'], prompt=prompt, output_schema=output_schema,
            max_tokens=model['max_tokens'], request_timeout=model['request_timeout'],
            max_retries=model['max_retries'], reasoning_effort=model['reasoning_effort'],
            max_request_bytes=config.get('reviewer_max_request_bytes', 400000),
            **({'output_projection': output_projection} if output_projection is not None else {}))
    return make



_SOURCE_REVIEW_FAILURE_TYPES = frozenset({
    'ValidationError', 'ModelBehaviorError', 'ReviewProtocolError', 'StrictJSONError',
    'ValueError', 'APIConnectionError', 'APITimeoutError', 'RateLimitError',
    'InternalServerError', 'ClaudeTransientTransportError', 'TimeoutError',
})
_SOURCE_REVIEW_FAILURE_CODES = frozenset({
    'source_checks_identity_mismatch', 'body_checks_identity_mismatch',
})
_SOURCE_REVIEW_RETRY_INSTRUCTIONS = (
    '\nHost-authored source-review retry feedback (protocol codes only):\n'
    'Re-evaluate the SAME supplied packet and return a complete assessment using only '
    'the fields in its JSON schema. Use literal contiguous quotes copied from each '
    'cited delivered source block. Do not insert ellipses or other text into quotes. '
    'For separated source spans, use separate citations. These failure codes establish '
    'no financial facts and supply no preferred verdict or answer.\n'
)


def reviewer_factory(config, packet=None, *, prior_failures=None):
    prompt = review_prompt(packet if packet is not None else {})
    failures = []
    for failure in prior_failures[:8] if isinstance(prior_failures, list) else ():
        if not isinstance(failure, dict):
            continue
        stage, kind = failure.get('stage'), failure.get('error_type')
        if (not isinstance(stage, str) or stage not in {'source_review', 'review'}
                or not isinstance(kind, str) or kind not in _SOURCE_REVIEW_FAILURE_TYPES):
            continue
        safe = {'stage': stage, 'error_type': kind}
        diagnostic = failure.get('diagnostic')
        code = diagnostic.get('code') if isinstance(diagnostic, dict) else None
        if isinstance(code, str) and code in _SOURCE_REVIEW_FAILURE_CODES:
            safe['code'] = code
        if safe not in failures:
            failures.append(safe)
    if failures:
        prompt += _SOURCE_REVIEW_RETRY_INSTRUCTIONS + json.dumps(failures, sort_keys=True)
    return _review_role_factory(config, 'reviewer', prompt, source_assessment_schema(packet or {}))


def question_reviewer_factory(config, packet=None):
    from .question_review_generation import PROJECTION, PROJECTION_FIGURES, question_generation_prompt
    if 'question_reviewer' not in review_roles(config):
        raise ValueError('independent question reviewer is not configured')
    from .question_review_generation import question_generation_schema
    projected = handoff_module._question_projection(packet) if packet else {}
    projection = PROJECTION_FIGURES if projected.get('schema_version') == 'question-coverage-input-v3' else PROJECTION
    return _review_role_factory(config, 'question_reviewer', question_generation_prompt(projected),
                                question_generation_schema(projected), output_projection=projection)


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
    Validated source-only negative feedback can request bounded retrieval after
    question protocol failure; it never grants Analysis approval.
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
        'uteki.agents.data_query.record_selection_navigation',
        'uteki.infrastructure.research_data.query_completion',
        'uteki.agents.data_query.question_coverage_review',
        'uteki.agents.data_query.question_review_generation',
        'uteki.agents.data_query.selection_contract', 'uteki.agents.runtime.output_limit',
        'uteki.agents.data_query.figure_selection',
        'uteki.domain.research_data.figure_evidence',
        'uteki.domain.research_data.scoped_agent_query',
        'uteki.domain.research_data.company_agent',
        'uteki.infrastructure.document_sources.figure_reader',
        'uteki.infrastructure.document_sources.figure_grounding',
        'uteki.infrastructure.document_sources.figure_acquisition',
        'uteki.agents.figure_materials',
        'uteki.agents.data_query.decision_protocol', 'uteki.agents.runtime.claude_messages',
        'uteki.domain.research_data.period_scope', 'uteki.agents.runtime.qwen_model',
        'uteki.agents.runtime.deepseek_model', 'uteki.agents.runtime.model_factory',
        'uteki.agents.runtime.run_budget', 'uteki.agents.runtime.strict_json',
        'uteki.agents.runtime.call_costs', 'uteki.agents.runtime.model_configuration',
        'uteki.infrastructure.research_data.run_artifacts',
        'uteki.infrastructure.research_data.query_service', 'uteki.infrastructure.research_data.record_locator',
        'uteki.agents.reading.reading_groups', 'uteki.infrastructure.research_data.materialization_metadata')
    components = (Path(__file__), Path(handoff_module.__file__),
                  Path(coordinator_module.__file__),
                  Path(SdkRecordReviewer.__init__.__code__.co_filename),
                  *(Path(import_module(name).__file__) for name in component_modules))
    write_new(output/'implementation.json', {str(p.resolve()): digest(p.read_bytes()) for p in components})
    from importlib.metadata import version
    write_new(output/'dependencies.json', {name: version(name)
        for name in ('openai-agents', 'openai', 'pydantic')})
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
                    if initial['budget_changes']:
                        attempt['resume_budget_changes'] = initial['budget_changes']
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
                    source_delivery='query_evidence_v1',
                    **({'question_review_policy': config['question_review_policy']}
                       if 'question_review_policy' in config else {}))
                if packet['question'] != request.question or packet['scope'] != result['scope']:
                    raise ValueError('retrieval packet changed original question or scope')
                write_new(folder/'review-packet.json', packet)
                attempt['query_ref'] = result['final_query_ref'] = packet['query_ref']
                result['final_review_ref'] = None
                review = None
                for review_ordinal in (1, 2):
                    review_path = folder/f'review-{review_ordinal:02d}'
                    prior_failures = review.get('failures') if review is not None else None
                    try:
                        review = await review_data_answer(packet, review_path,
                            reviewer_factory=reviewer_factory(config, packet, prior_failures=prior_failures),
                            allow_source_protocol_repair=review_ordinal == 1,
                            **({'question_reviewer_factory': question_reviewer_factory(config, packet)}
                               if 'question_reviewer' in config else {}))
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
                    if review['status'] != 'failed' or review.get('review_retryable') is False:
                        break
                if review['status'] == 'reviewed' and review['analysis_eligible']:
                    attempt['status'] = result['status'] = 'reviewed_data_ready'
                    break
                if review['status'] == 'failed' and review.get('revision_feedback'):
                    partial = validate_source_revision_feedback(review_path, packet)
                    feedback = {'prior_query_ref': packet['query_ref'], 'prior_review_ref': review['review_ref'],
                                'source_revision': partial}
                    attempt['status'] = 'needs_revision_from_source_only'
                    result['status'] = 'attempts_exhausted'
                    continue
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
