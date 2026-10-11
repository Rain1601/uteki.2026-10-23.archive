"""Independent zero-API checks; historical failures remain failures.

This is an evaluation-only harness, not a production answer repair. Synthetic
responses test the strict protocol; they do not measure model reasoning quality.
"""
from copy import deepcopy
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from uteki.agents.data_query import answer_handoff as handoff
from uteki.infrastructure.research_data.financial_records import digest


ROOT = Path(__file__).resolve().parents[4]
HISTORY = ROOT / 'output/e6-repeatability-20261010-r1'
DEST = Path(__file__).with_name('independent-citation-acceptance.v1.json')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def errors(packet, response):
    blocks = {(d['source_snapshot_id'], b['block_id']): b
              for d in packet['source_documents'] for b in d['blocks']}
    result = []
    for field in ('facts', 'requirements', 'source_checks'):
        for i, row in enumerate(response[field]):
            for j, citation in enumerate(row['citations']):
                block = blocks.get((citation['source_snapshot_id'], citation['block_id']))
                if block is None or block.get('type') == 'image' or citation['quote'] not in block['text']:
                    result.append({'field_pointer': f'/{field}/{i}/citations/{j}',
                                   'citation': deepcopy(citation),
                                   'exact_same_source_elsewhere': [bid for (sid, bid), b in blocks.items()
                                       if sid == citation['source_snapshot_id'] and b.get('type') != 'image'
                                       and citation['quote'] in b['text']]})
    return result


def rejected(packet, response, *, require_diagnostic=False):
    before = deepcopy((packet, response))
    try:
        handoff._validate_source_assessment(packet, response)
    except ValueError as exc:
        record = {'error_type': type(exc).__name__, 'error': str(exc),
                  'diagnostic': getattr(exc, 'diagnostic', None)}
        assert (packet, response) == before, 'Validator mutated the evidence or response'
        if require_diagnostic:
            assert record['diagnostic']['code'] == 'source_citation_mismatch'
            actual = record['diagnostic']['errors']
            assert [item['field_pointer'] for item in actual] == [item['field_pointer'] for item in errors(packet, response)]
        return record
    raise AssertionError('An invalid citation was accepted')


def synthetic():
    packet = {'packet_id': 'independent-synthetic-citation-v1', 'facts': [{'fact_id': 'fact'}],
              'requirements': [{'requirement_id': 'requirement'}],
              'source_documents': [
                  {'source_snapshot_id': 'issuer-a-2039', 'index_id': 'index-a', 'source_sha256': 'a' * 64,
                   'blocks': [{'block_id': 'heading', 'type': 'paragraph', 'text': '(in thousands)'},
                              {'block_id': 'table', 'type': 'table',
                               'text': 'Year203820392040 Revenue 7 9',
                               'table': {'cells': [[1, 0, False, 0, 1, 'Year'],
                                                   [1, 1, False, 0, 1, '2038'],
                                                   [1, 2, False, 0, 1, '2039']]}},
                              {'block_id': 'image', 'type': 'image', 'text': 'Image alt text'}]},
                  {'source_snapshot_id': 'issuer-b-2040', 'index_id': 'index-b', 'source_sha256': 'b' * 64,
                   'blocks': [{'block_id': 'table', 'type': 'paragraph', 'text': 'Foreign-only revenue 11'}]}],
              'query_status': 'evidence_ready', 'query_gaps': [], 'program_gaps': [],
              'delivery_schema_version': 'selected-originals-v3'}
    cite = {'source_snapshot_id': 'issuer-a-2039', 'block_id': 'table', 'quote': 'Revenue 7 9'}
    response = {'packet_id': packet['packet_id'],
                'facts': [{'fact_id': 'fact', 'verdict': 'supported', 'relevance': 'necessary',
                           'rationale': 'Independent synthetic protocol fixture.', 'citations': [cite]}],
                'requirements': [{'requirement_id': 'requirement', 'verdict': 'complete',
                                  'rationale': 'Independent fixture requirement.', 'citations': [cite]}],
                'source_checks': [{'source_snapshot_id': d['source_snapshot_id'], 'verdict': 'text_sufficient',
                                  'rationale': 'Independent fixture scope.',
                                  'citations': [{'source_snapshot_id': d['source_snapshot_id'],
                                                 'block_id': 'table', 'quote': d['blocks'][-1]['text']
                                                     if d['source_snapshot_id'] == 'issuer-b-2040' else 'Revenue 7 9'}]}
                                 for d in packet['source_documents']],
                'body_checks': [{'source_snapshot_id': d['source_snapshot_id'], 'block_id': b['block_id'],
                                 'relevance': 'necessary', 'rationale': 'Protocol coverage only.'}
                                for d in packet['source_documents'] for b in d['blocks']],
                'question_coverage': 'complete', 'coverage_reason': 'Synthetic fixture only.',
                'missing_information': [], 'limitations': ['No model or business-content evaluation.']}
    return packet, response


class OfflineRole:
    plan_origin = 'scripted_fixture'

    def __init__(self, responses):
        self.responses = list(responses)
        self.inputs = []
        self.closed = False

    async def review(self, packet):
        self.inputs.append(deepcopy(packet))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value(packet) if callable(value) else value)

    async def aclose(self):
        self.closed = True

    def snapshot_usage(self):
        return {'plan_origin': self.plan_origin, 'model_requests': 0}


def offline_handler_checks(packet, bad, results):
    """Scripted plumbing only; corrected output is never fed to a real run."""
    repaired = deepcopy(bad)
    # Explicit evaluation-only expected correction for the preserved wrong-block
    # draft; the production handler must neither make nor receive this correction.
    for field in ('facts', 'requirements', 'source_checks'):
        for row in repaired[field]:
            for citation in row['citations']:
                if citation['quote'] == '(in millions, except per share amounts)':
                    citation['block_id'] = 'block-000752-dfe26017'
    assert handoff._validate_source_assessment(packet, repaired)[1]
    question_template = read(HISTORY / 'R3/S2/run-r1/attempt-01/review-01/question-response.json')

    def question_response(projected):
        response = deepcopy(question_template)
        response.update(packet_id=projected['packet_id'], projection_id=projected['projection_id'])
        return response

    with tempfile.TemporaryDirectory(prefix='e6-r1-independent-offline-') as temporary:
        root = Path(temporary)
        for name, source_responses, allowed, expected_source_calls in [
            ('legal_second_draft', [bad, repaired], True, 2),
            ('still_invalid_second_draft', [bad, bad], True, 2),
            ('repair_transport_failure', [bad, TimeoutError('Synthetic timeout')], True, 2),
            ('outer_second_disables_inner_repair', [bad], False, 1),
        ]:
            source_role = OfflineRole(source_responses)
            question_role = OfflineRole([question_response])
            output = root / name
            result = asyncio.run(handoff.review_data_answer(packet, output,
                reviewer_factory=lambda _: source_role, question_reviewer_factory=lambda _: question_role,
                allow_source_protocol_repair=allowed))
            assert len(source_role.inputs) == expected_source_calls
            assert source_role.closed and (not question_role.inputs or question_role.closed)
            assert source_role.inputs[0] == packet
            assert read(output / 'source-response.json') == (repaired if name == 'legal_second_draft' else bad)
            if allowed:
                repair = source_role.inputs[1]
                assert repair['packet'] == packet and repair['previous_assessment'] == bad
                assert repair['previous_assessment_sha256'] == digest(bad)
                assert repair == handoff.source_review_repair_input(packet, bad, max_bytes=packet['max_packet_bytes'])
                assert len(repair['host_protocol_diagnostics']) == 3
                assert set(repair['host_protocol_diagnostics'][0]) == {'field_pointer', 'code', 'constraint_pointer'}
                assert read(output / 'source-response-01.json') == bad
                assert result['review_retryable'] is False
            if name == 'legal_second_draft':
                assert result['status'] == 'reviewed' and result['analysis_eligible']
                assert len(question_role.inputs) == 1
                handoff.load_reviewed_data(output, expected_scope=packet['scope'],
                    expected_review_manifest_sha256=result['review_ref']['manifest_sha256'], allow_fixture=True)
                for tamper in ('changed_repair_packet', 'missing_second_draft', 'different_final_draft'):
                    copied = root / tamper
                    shutil.copytree(output, copied)
                    if tamper == 'changed_repair_packet':
                        value = read(copied / 'source-repair-input.json')
                        value['packet']['question'] += ' Changed after execution.'
                        (copied / 'source-repair-input.json').write_text(json.dumps(value))
                    elif tamper == 'missing_second_draft':
                        (copied / 'source-response-02.json').unlink()
                    else:
                        value = read(copied / 'source-response-02.json')
                        value['coverage_reason'] += ' Changed after execution.'
                        (copied / 'source-response-02.json').write_text(json.dumps(value))
                    # Re-sealing malicious changes must not bypass semantic binding.
                    manifest = {'files': {str(p.relative_to(copied)): digest(p.read_bytes())
                        for p in sorted(copied.rglob('*')) if p.is_file() and p.name != 'manifest.json'}}
                    (copied / 'manifest.json').write_text(json.dumps(manifest))
                    try:
                        handoff.load_reviewed_data(copied, expected_scope=packet['scope'],
                            expected_review_manifest_sha256=digest((copied / 'manifest.json').read_bytes()),
                            allow_fixture=True)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('Resealed repair tampering accepted: ' + tamper)
                    results['offline_handler'].append({'case': tamper, 'rejected_after_reseal': True})
            else:
                assert result['status'] == 'failed' and not result['analysis_eligible']
                assert not question_role.inputs and not (output / 'response.json').exists()
            results['offline_handler'].append({'case': name, 'source_calls': len(source_role.inputs),
                'question_calls': len(question_role.inputs), 'status': result['status'], 'api_calls': 0})
    try:
        handoff.source_review_repair_input(packet, bad, max_bytes=1)
    except ValueError:
        results['offline_handler'].append({'case': 'oversized_repair_fails_explicitly', 'rejected': True})
    else:
        raise AssertionError('Oversized repair did not fail')


def main():
    tracked = []
    results = {'schema_version': 'independent-citation-acceptance-v1', 'model_calls': 0,
               'historical_failures': [], 'historical_final_successes': [], 'synthetic': [],
               'offline_handler': []}
    diagnostic_available = hasattr(handoff, 'SourceCitationProtocolError')
    failing_root = HISTORY / 'R3/S3/run-r1/attempt-01'
    for revision, count in [('review-01', 3), ('review-02', 5)]:
        input_path = failing_root / revision / 'model/review-0001-input.json'
        response_path = failing_root / revision / 'source-response.json'
        tracked.extend([input_path, response_path])
        saved_input = read(input_path)
        packet, response = saved_input['packet'], read(response_path)
        assert json.loads(saved_input['model_input']) == packet
        independent_errors = errors(packet, response)
        assert len(independent_errors) == count
        results['historical_failures'].append({'revision': revision, 'expected_invalid_citations': count,
                                              'errors': independent_errors,
                                              'validation': rejected(packet, response,
                                                  require_diagnostic=diagnostic_available)})
    for run in sorted(HISTORY.glob('R*/S*/run-r1')):
        result = read(run / 'result.json')
        if result['status'] != 'reviewed_data_ready':
            continue
        review = Path(result['final_review_ref']['path'])
        input_path, response_path = review / 'model/review-0001-input.json', review / 'source-response.json'
        tracked.extend([input_path, response_path])
        packet, response = read(input_path)['packet'], read(response_path)
        normalized, eligible = handoff._validate_source_assessment(packet, response)
        assert eligible and not errors(packet, response)
        assert normalized == response, 'Historical successful source response serialization changed'
        results['historical_final_successes'].append({'slot': f'{run.parent.parent.name}-{run.parent.name}',
                                                    'eligible': eligible, 'response_unchanged': True})
    assert len(results['historical_final_successes']) == 8
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in tracked}
    packet, response = synthetic()
    assert handoff._validate_source_assessment(packet, response)[1]
    results['synthetic'].append({'case': 'exact_literal_valid', 'accepted': True})
    response['facts'][0]['citations'] = [
        {'source_snapshot_id': 'issuer-a-2039', 'block_id': 'heading', 'quote': '(in thousands)'},
        {'source_snapshot_id': 'issuer-a-2039', 'block_id': 'table', 'quote': 'Year203820392040'}]
    assert handoff._validate_source_assessment(packet, response)[1]
    results['synthetic'].append({'case': 'separate_exact_block_quotes_valid', 'accepted': True})
    for name, change in [
        ('same_source_wrong_block', {'block_id': 'table', 'quote': '(in thousands)'}),
        ('inserted_spaces_from_cells', {'block_id': 'table', 'quote': 'Year2038 2039 2040'}),
        ('cross_source_text', {'block_id': 'table', 'quote': 'Foreign-only revenue 11'}),
        ('undelivered_body', {'block_id': 'undelivered', 'quote': 'Revenue 7 9'}),
        ('unknown_source', {'source_snapshot_id': 'unknown', 'block_id': 'table', 'quote': 'Revenue 7 9'}),
        ('image_not_quoteable', {'block_id': 'image', 'quote': 'Image alt text'}),
        ('combined_noncontiguous_text', {'block_id': 'table', 'quote': 'Year203820392040 7 9'}),
    ]:
        candidate = deepcopy(response)
        candidate['facts'][0]['citations'] = [{'source_snapshot_id': 'issuer-a-2039', **change}]
        results['synthetic'].append({'case': name, 'validation': rejected(packet, candidate,
            require_diagnostic=diagnostic_available)})
    legacy_packet, legacy_response = synthetic()
    legacy_packet.pop('delivery_schema_version')
    legacy_response.pop('body_checks')
    normalized, eligible = handoff._validate_source_assessment(legacy_packet, legacy_response)
    assert eligible and normalized == legacy_response and 'body_checks' not in normalized and 'revision_requests' not in normalized
    results['synthetic'].append({'case': 'legacy_optional_fields_absence_preserved', 'accepted': True})
    if diagnostic_available:
        original_input = read(failing_root / 'review-01/model/review-0001-input.json')
        original_bad = read(failing_root / 'review-01/source-response.json')
        offline_handler_checks(original_input['packet'], original_bad, results)
    assert all(sha(ROOT / path) == value for path, value in hashes_before.items())
    results.update(diagnostic_available=diagnostic_available,
                   historical_files_sha256=hashes_before, historical_files_unchanged=True, status='passed')
    DEST.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': results['status'], 'original_failed_drafts': 2,
                      'historical_successes': 8, 'synthetic_cases': len(results['synthetic']),
                      'offline_handler_cases': len(results['offline_handler']),
                      'diagnostic_available': diagnostic_available, 'model_calls': 0}))


if __name__ == '__main__':
    main()
