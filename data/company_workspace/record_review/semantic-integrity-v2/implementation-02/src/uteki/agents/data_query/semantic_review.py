"""Bounded semantic checks with immutable inputs, raw-response capture and accounting."""
import asyncio
import json
from pathlib import Path
from pydantic import ValidationError

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained
from uteki.infrastructure.research_data.semantic_review import (
    SEMANTIC_PROMPT, validate_semantic_packet, validate_semantic_assessment, validate_dataset_binding,
)
from .artifacts import write_new
from .coordinator import _verify_manifest


async def review_semantics(inputs, output, *, reviewer_factory, notify=None, max_attempts_per_packet=1):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if type(max_attempts_per_packet) is not int or max_attempts_per_packet not in (1, 2):
        raise ValueError('at most two attempts per semantic packet')
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
    write_new(output/'request.json', {'input_manifest_sha256': digest((inputs/'manifest.json').read_bytes()),
        'inputs': str(inputs), 'input_spec': spec, 'prompt': SEMANTIC_PROMPT,
        'prompt_sha256': digest(SEMANTIC_PROMPT), 'max_attempts_per_packet': max_attempts_per_packet,
        'implementation_sha256': {'runner': digest(Path(__file__).read_bytes()),
            'validator': digest(Path(validate_semantic_assessment.__code__.co_filename).read_bytes())}})
    reviewer, usage, cancelled = None, None, False
    assessments, failures = [], []
    try:
        reviewer = reviewer_factory(output/'model')
        for number, packet in enumerate(packets, 1):
            feedback, accepted = None, False
            for attempt in range(1, max_attempts_per_packet+1):
                try:
                    request = packet if feedback is None else {**packet, 'host_validation_feedback': feedback}
                    response = await reviewer.review(request)
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-response.json', response)
                    checked = validate_semantic_assessment(packet, response)
                    write_new(output/f'packet-{number:03d}/assessment.json', checked)
                    assessments.append(checked); accepted = True
                    if notify: notify({'packet': number, 'status': 'assessment_recorded',
                        'checks': {c['axis']: c['status'] for c in checked['checks']},
                        'assertions': {a['assertion_id']: a['verdict'] for a in checked['assertions']}})
                    break
                except Exception as error:
                    reason = str(error)[:1200] if type(error) is ValueError else type(error).__name__
                    if isinstance(error, ValidationError):
                        # Preserve actionable schema locations without echoing model input values.
                        reason = json.dumps([{'field': '.'.join(map(str, e['loc'])), 'type': e['type']}
                            for e in error.errors(include_input=False, include_url=False)[:12]])[:1200]
                    feedback = {'error_type': type(error).__name__,
                        'reason': reason,
                        'instruction': 'Correct schema, source offsets, per-record anchor coverage and context claims against the original packet.'}
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-rejection.json', feedback)
                    if notify: notify({'packet': number, 'attempt': attempt, 'status': 'rejected', **feedback})
                    if type(error).__name__ == 'BudgetExceeded': break
            if not accepted:
                failures.append({'packet_id': packet['packet_id'], 'error': feedback})
                if feedback['error_type'] == 'BudgetExceeded': break
    except BaseException as error:
        cancelled = isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit))
        failures.append({'stage': 'runtime', 'error_type': type(error).__name__})
    finally:
        if reviewer:
            try: await reviewer.aclose()
            except Exception as error: failures.append({'stage': 'close', 'error_type': type(error).__name__})
            try: usage = reviewer.snapshot_usage()
            except Exception as error: failures.append({'stage': 'accounting', 'error_type': type(error).__name__})
    completed = {a['packet_id'] for a in assessments}
    result = {'schema_version': 'semantic-review-result-v2' if any(
                  p['schema_version'] == 'semantic-review-input-v2' for p in packets) else 'semantic-review-result-v1',
        'status': 'cancelled' if cancelled else 'assessed' if len(completed) == len(packets) and not failures else 'partial',
        'source_origin': spec['source_origin'], 'plan_origin': getattr(reviewer, 'plan_origin', 'not_started'),
        'packets_requested': len(packets), 'packets_assessed': len(completed),
        'unassessed_packet_ids': [p['packet_id'] for p in packets if p['packet_id'] not in completed],
        'assessments': assessments, 'failures': failures, 'usage': usage, 'adoption': 'unchanged_candidate',
        'semantic_acceptance': 'requires_independent_evaluation',
        'context_request_verification': 'unverified_model_questions',
        'limitations': ['Cited model constraints are review opinions, not proof of complete extraction or truth.',
            'Only explicitly selected records, axes and supplied source context are assessed.']}
    write_new(output/'result.json', result)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return result
