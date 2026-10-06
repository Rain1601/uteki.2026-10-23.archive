"""Bounded semantic checks with immutable inputs, raw-response capture and accounting."""
import asyncio
import json
import inspect
from pathlib import Path
from pydantic import ValidationError

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained
from uteki.infrastructure.research_data.semantic_review import (
    SEMANTIC_PROMPT, validate_semantic_packet, validate_semantic_assessment, validate_dataset_binding,
)
from uteki.infrastructure.research_data.semantic_anchors import build_record_anchors_v3, SemanticEvidenceError
from uteki.infrastructure.research_data.semantic_audit import (
    SEMANTIC_AUDIT_PROMPT, build_semantic_audit_input, validate_semantic_audit,
)
from uteki.domain.research_data.semantic_audit import SemanticAuditResult
from uteki.domain.research_data.semantic_review import SemanticAssessmentV2
from .artifacts import write_new
from .coordinator import _verify_manifest
from .record_review_model import review_model_input


def _validation_feedback(error, phase):
    reason = str(error)[:1200] if type(error) is ValueError or isinstance(error, SemanticEvidenceError) else type(error).__name__
    if isinstance(error, ValidationError):
        reason = json.dumps([{'field': '.'.join(map(str, e['loc'])), 'type': e['type']}
            for e in error.errors(include_input=False, include_url=False)[:12]])[:1200]
    feedback = {'error_type': type(error).__name__, 'reason': reason, 'stage': phase,
        'instruction': 'Correct schema, source offsets, per-record anchor coverage and context claims against the original packet.'}
    if isinstance(error, SemanticEvidenceError): feedback['details'] = error.details
    return feedback


async def review_semantics(inputs, output, *, reviewer_factory, auditor_factory=None,
                           notify=None, max_attempts_per_packet=1, max_audit_attempts=1):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if type(max_attempts_per_packet) is not int or max_attempts_per_packet not in (1, 2, 3):
        raise ValueError('at most three attempts per semantic packet')
    if type(max_audit_attempts) is not int or max_audit_attempts not in (1, 2):
        raise ValueError('at most two attempts per semantic audit')
    if auditor_factory is None and max_audit_attempts != 1:
        raise ValueError('audit retries require an auditor')
    if output.is_relative_to(inputs): raise ValueError('output inside frozen semantic inputs')
    manifest = _verify_manifest(inputs)
    if 'input-manifest.json' not in manifest['files']: raise ValueError('semantic input spec not sealed')
    spec = json.loads((inputs/'input-manifest.json').read_text())
    if spec['source_origin'] == 'frozen_dataset':
        dataset = Path(spec['dataset']).resolve()
        _verify_manifest(dataset, spec['dataset_manifest_sha256'])
        if output.is_relative_to(dataset): raise ValueError('output inside frozen dataset')
    elif spec['source_origin'] != 'synthetic_fixture' or spec.get('dataset') is not None:
        raise ValueError('explicit supported source origin required')
    packets = []
    for ref in spec['packets']:
        path = contained(inputs, ref['path'])
        if manifest['files'].get(ref['path']) != ref['sha256'] or digest(path.read_bytes()) != ref['sha256']:
            raise ValueError('semantic packet file hash mismatch')
        packet = json.loads(path.read_text())
        validate_semantic_packet(packet)
        if packet['packet_id'] != ref['packet_id'] or [r['record']['record_id'] for r in packet['records']] != ref['record_ids']:
            raise ValueError('semantic packet reference mismatch')
        if packet['source_origin'] != spec['source_origin']:
            raise ValueError('semantic source origin mismatch')
        if spec['source_origin'] == 'frozen_dataset' and packet['scope'] != spec['scope']:
            raise ValueError('semantic scope mismatch')
        if spec['source_origin'] == 'frozen_dataset': validate_dataset_binding(packet, dataset, artifact_root=inputs)
        packets.append(packet)
    if not packets or len({p['packet_id'] for p in packets}) != len(packets):
        raise ValueError('nonempty unique semantic packets required')
    output.mkdir(parents=True, exist_ok=False)
    implementation = {}
    package_root = Path(__file__).resolve().parents[2]
    for obj in (review_semantics, validate_semantic_assessment, build_record_anchors_v3,
                validate_semantic_audit, SemanticAuditResult, SemanticAssessmentV2, review_model_input):
        source = Path(inspect.getfile(obj)).resolve()
        name = str(source.relative_to(package_root))
        if name in implementation: continue
        raw = source.read_bytes()
        target = output/'implementation'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream: stream.write(raw)
        implementation[name] = digest(raw)
    write_new(output/'request.json', {'input_manifest_sha256': digest((inputs/'manifest.json').read_bytes()),
        'inputs': str(inputs), 'input_spec': spec, 'prompt': SEMANTIC_PROMPT,
        'prompt_sha256': digest(SEMANTIC_PROMPT), 'max_attempts_per_packet': max_attempts_per_packet,
        'audit_enabled': auditor_factory is not None,
        'max_audit_attempts': max_audit_attempts,
        'audit_prompt': SEMANTIC_AUDIT_PROMPT if auditor_factory is not None else None,
        'implementation_files': implementation,
        'implementation_sha256': {'runner': digest(Path(__file__).read_bytes()),
            'validator': digest(Path(validate_semantic_assessment.__code__.co_filename).read_bytes())}})
    reviewer, auditor, usage, audit_usage, cancelled = None, None, None, None, False
    assessments, failures, audits = [], [], []
    try:
        reviewer = reviewer_factory(output/'model')
        if auditor_factory is not None: auditor = auditor_factory(output/'audit-model')
        for number, packet in enumerate(packets, 1):
            feedback, accepted = None, False
            for attempt in range(1, max_attempts_per_packet+1):
                phase = 'proposal'
                response = None
                try:
                    request = packet if feedback is None else {**packet, 'host_validation_feedback': feedback}
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-input.json', request)
                    response = await reviewer.review(request)
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-response.json', response)
                    checked = validate_semantic_assessment(packet, response)
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-assessment.json', checked)
                    if auditor is not None:
                        phase = 'audit'
                        audit_input = build_semantic_audit_input(packet, checked)
                        write_new(output/f'packet-{number:03d}/attempt-{attempt}-audit-input.json', audit_input)
                        audit_feedback = None
                        for audit_attempt in range(1, max_audit_attempts+1):
                            audit_request = audit_input if audit_feedback is None else {
                                **audit_input, 'host_validation_feedback': audit_feedback}
                            audit_prefix = output/f'packet-{number:03d}/attempt-{attempt}-audit-try-{audit_attempt}'
                            write_new(Path(str(audit_prefix)+'-input.json'), audit_request)
                            try:
                                audit_response = await auditor.review(audit_request)
                                write_new(Path(str(audit_prefix)+'-response.json'), audit_response)
                                if audit_attempt == 1:
                                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-audit-response.json', audit_response)
                                audit = validate_semantic_audit(packet, checked, audit_response)
                                break
                            except (ValueError, ValidationError) as error:
                                audit_feedback = _validation_feedback(error, 'audit')
                                audit_feedback['instruction'] = 'Correct your critique against the same original assessment and source packet. Do not change their identities.'
                                write_new(Path(str(audit_prefix)+'-rejection.json'), audit_feedback)
                                if audit_attempt == max_audit_attempts: raise
                        write_new(output/f'packet-{number:03d}/attempt-{attempt}-audit.json', audit)
                        audits.append({'packet_id': packet['packet_id'], 'attempt': attempt, **audit})
                        if audit['status'] == 'revise':
                            feedback = {'stage': 'semantic_audit', 'error_type': 'SemanticRevisionRequired',
                                'reason': 'Cited review issues require examination against the original sources.',
                                'previous_assessment': checked, 'audit': audit,
                                'instruction': 'Verify these review opinions against the original packet, then return a complete revised assessment.'}
                            write_new(output/f'packet-{number:03d}/attempt-{attempt}-rejection.json', feedback)
                            if notify: notify({'packet': number, 'attempt': attempt, 'status': 'revision_requested',
                                               'issue_count': len(audit['issues'])})
                            continue
                    write_new(output/f'packet-{number:03d}/assessment.json', checked)
                    assessments.append(checked); accepted = True
                    if notify: notify({'packet': number, 'status': 'assessment_recorded',
                        'checks': {c['axis']: c['status'] for c in checked['checks']},
                        'assertions': {a['assertion_id']: a['verdict'] for a in checked['assertions']}})
                    break
                except Exception as error:
                    feedback = _validation_feedback(error, phase)
                    if not isinstance(error, (ValueError, ValidationError)) and type(error).__name__ != 'BudgetExceeded':
                        feedback['stop_run'] = True
                        feedback['instruction'] = 'Runtime failure: stop this run without model revision or further packet requests.'
                    if phase == 'proposal' and isinstance(error, SemanticEvidenceError) and isinstance(response, dict):
                        feedback['previous_assessment'] = response
                        feedback['previous_assessment_status'] = 'unvalidated'
                        feedback['instruction'] = ('Review every reported field against the original packet and return a complete assessment. '
                            'The previous assessment is an unvalidated model draft, not source evidence. '
                            'Required spans identify provenance only; retain qualifying citations and verify meaning. '
                            'An unavailable anchor cannot be fixed by inventing a quote.')
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-rejection.json', feedback)
                    if notify: notify({'packet': number, 'attempt': attempt, 'status': 'rejected', **feedback})
                    # An invalid critic is not reliable feedback for changing the proposal.
                    if phase == 'audit' or feedback.get('stop_run') or type(error).__name__ == 'BudgetExceeded': break
            if not accepted:
                failures.append({'packet_id': packet['packet_id'], 'error': feedback})
                if feedback.get('stop_run') or feedback['error_type'] == 'BudgetExceeded': break
    except BaseException as error:
        cancelled = isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit))
        failures.append({'stage': 'runtime', 'error_type': type(error).__name__})
    finally:
        if reviewer:
            try: await reviewer.aclose()
            except Exception as error: failures.append({'stage': 'close', 'error_type': type(error).__name__})
            try: usage = reviewer.snapshot_usage()
            except Exception as error: failures.append({'stage': 'accounting', 'error_type': type(error).__name__})
        if auditor:
            try: await auditor.aclose()
            except Exception as error: failures.append({'stage': 'audit_close', 'error_type': type(error).__name__})
            try: audit_usage = auditor.snapshot_usage()
            except Exception as error: failures.append({'stage': 'audit_accounting', 'error_type': type(error).__name__})
    completed = {a['packet_id'] for a in assessments}
    result = {'schema_version': 'semantic-review-result-v3' if auditor_factory is not None or any(
                  p['schema_version'] == 'semantic-review-input-v3' for p in packets) else 'semantic-review-result-v2' if any(
                  p['schema_version'] == 'semantic-review-input-v2' for p in packets) else 'semantic-review-result-v1',
        'status': 'cancelled' if cancelled else 'assessed' if len(completed) == len(packets) and not failures else 'partial',
        'source_origin': spec['source_origin'], 'plan_origin': getattr(reviewer, 'plan_origin', 'not_started'),
        'packets_requested': len(packets), 'packets_assessed': len(completed),
        'unassessed_packet_ids': [p['packet_id'] for p in packets if p['packet_id'] not in completed],
        'assessments': assessments, 'failures': failures, 'usage': usage, 'adoption': 'unchanged_candidate',
        'audits': audits, 'audit_usage': audit_usage, 'audit_enabled': auditor_factory is not None,
        'semantic_acceptance': 'model_audited_requires_independent_evaluation' if auditor_factory is not None else 'requires_independent_evaluation',
        'context_request_verification': 'unverified_model_questions',
        'limitations': ['Cited model constraints are review opinions, not proof of complete extraction or truth.',
            'Only explicitly selected records, axes and supplied source context are assessed.']}
    write_new(output/'result.json', result)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return result
