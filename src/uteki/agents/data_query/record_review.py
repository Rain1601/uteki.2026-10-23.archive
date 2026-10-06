"""Bounded semantic review over frozen inputs; original candidate data stays intact."""
from collections import Counter
import json
from pathlib import Path

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.record_review import REVIEW_PROMPT, validate_assessment
from uteki.infrastructure.research_data.query_dataset import contained
from .artifacts import write_new
from .coordinator import _verify_manifest


async def review_records(inputs, output, *, reviewer_factory, notify=None, max_attempts_per_packet=2):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if output.is_relative_to(inputs): raise ValueError('review output must be outside frozen inputs')
    if not 1 <= max_attempts_per_packet <= 2: raise ValueError('at most two attempts per packet')
    _verify_manifest(inputs)
    spec = json.loads((inputs/'input-manifest.json').read_text())
    _verify_manifest(Path(spec['dataset']), spec['dataset_manifest_sha256'])
    if output.is_relative_to(Path(spec['dataset'])): raise ValueError('output is inside frozen dataset')
    packets, all_ids = [], []
    for reference in spec['packets']:
        path = contained(inputs, reference['path'])
        if digest(path.read_bytes()) != reference['sha256']: raise ValueError('packet file hash mismatch')
        packet = json.loads(path.read_text())
        ids = [item['record']['record_id'] for item in packet['records']]
        if ids != reference['record_ids'] or packet['packet_id'] != reference['packet_id']:
            raise ValueError('packet reference identity mismatch')
        if packet['scope'] != spec['scope']:
            raise ValueError('packet scope differs from input manifest')
        if packet['packet_id'] != 'review-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]:
            raise ValueError('review input packet hash mismatch')
        packets.append(packet)
        all_ids.extend(ids)
    if not all_ids or len(set(all_ids)) != len(all_ids) or len(set(spec['record_ids'])) != len(spec['record_ids']) or set(all_ids) != set(spec['record_ids']):
        raise ValueError('input packets must cover each requested record exactly once')
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'request.json', {'inputs': str(inputs), 'manifest_sha256': digest((inputs/'manifest.json').read_bytes()),
        'input_spec': spec, 'prompt': REVIEW_PROMPT, 'prompt_sha256': digest(REVIEW_PROMPT),
        'implementation_sha256': {'runner': digest(Path(__file__).read_bytes()),
            'validator': digest(Path(validate_assessment.__code__.co_filename).read_bytes())},
        'max_attempts_per_packet': max_attempts_per_packet})
    accepted, failures, batch_reviews = [], [], []
    reviewer, usage = None, None
    cancelled = False
    try:
        reviewer = reviewer_factory(output/'model')
        for number, (reference, packet) in enumerate(zip(spec['packets'], packets), 1):
            feedback = None
            for attempt in range(1, max_attempts_per_packet+1):
                request = packet if feedback is None else {**packet, 'host_validation_feedback': feedback}
                try:
                    response = await reviewer.review(request)
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-response.json', response)
                    checked = validate_assessment(packet, response)
                    write_new(output/f'packet-{number:03d}/assessment.json', checked)
                    accepted.extend(checked['records'])
                    batch_reviews.append({'packet_id': packet['packet_id'], 'source_limitations': checked['source_limitations']})
                    if notify: notify({'packet': number, 'status': 'review_recorded', 'records': len(checked['records']),
                                       'verdicts': dict(Counter(r['verdict'] for r in checked['records']))})
                    break
                except Exception as error:
                    # Diagnostic allowlist: no provider exception bodies, headers or credentials.
                    message = str(error)[:1200] if type(error) is ValueError else type(error).__name__
                    feedback = {'error_type': type(error).__name__, 'reason': message,
                                'instruction': 'Correct the response against the ORIGINAL packet. Use exact short source quotes and all record IDs.'}
                    write_new(output/f'packet-{number:03d}/attempt-{attempt}-rejection.json', feedback)
                    if notify: notify({'packet': number, 'attempt': attempt, 'status': 'rejected', **feedback})
                    if type(error).__name__ == 'BudgetExceeded': break
            else:
                pass
            current = {r['record_id'] for r in accepted}
            if not set(reference['record_ids']) <= current:
                failures.append({'packet_id': reference['packet_id'], 'record_ids': reference['record_ids'], 'error': feedback})
                if feedback and feedback['error_type'] == 'BudgetExceeded': break
    except BaseException as error:
        import asyncio
        cancelled = isinstance(error, asyncio.CancelledError)
        failures.append({'stage': 'runtime', 'error_type': type(error).__name__})
        if isinstance(error, (KeyboardInterrupt, SystemExit)): cancelled = True
    finally:
        if reviewer:
            try: await reviewer.aclose()
            except Exception as error: failures.append({'stage': 'close', 'error_type': type(error).__name__})
            try: usage = reviewer.snapshot_usage()
            except Exception as error: failures.append({'stage': 'accounting', 'error_type': type(error).__name__})
    requested = set(spec['record_ids'])
    reviewed = {r['record_id'] for r in accepted}
    result = {'schema_version': 'record-review-result-v1',
        'status': 'cancelled' if cancelled else 'reviewed' if requested == reviewed and not failures else 'partial',
        'plan_origin': getattr(reviewer, 'plan_origin', 'not_started'), 'records_requested': len(requested),
        'records_reviewed': len(reviewed), 'unreviewed_record_ids': sorted(requested-reviewed),
        'verdict_counts': dict(Counter(r['verdict'] for r in accepted)), 'records': accepted,
        'failures': failures, 'batch_reviews': batch_reviews, 'usage': usage, 'adoption': 'unchanged_candidate',
        'scope': spec['scope'], 'limitations': ['LLM opinions require evidence review; supported is not guaranteed truth.',
             'Only selected extracted records reviewed; full-document extraction recall is not evaluated.']}
    write_new(output/'result.json', result)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
                                              for p in sorted(output.rglob('*')) if p.is_file()}})
    return result
