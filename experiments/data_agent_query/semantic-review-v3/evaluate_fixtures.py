"""Offline frozen-fixture scoring; independent semantic notes never enter model inputs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import validate_semantic_assessment


def _covered(packet, ids, citations):
    missing = []
    for rid in ids:
        anchor = packet['record_anchors'][rid]
        if anchor.get('status') != 'located' or not any(
            c['source_snapshot_id'] == anchor['source_snapshot_id'] and c['block_id'] == anchor['block_id']
            and isinstance(c.get('source_start'), int) and c['source_start'] <= anchor['start']
            and c['source_start']+len(c['quote']) >= anchor['end'] for c in citations): missing.append(rid)
    return missing


def score_response(packet, response, expected):
    """Mechanical fixed requirements only. A separate semantic review remains mandatory."""
    rows = response.get('assertions', []) if isinstance(response, dict) else []
    observed = {r.get('assertion_id'): r.get('verdict') for r in rows if isinstance(r, dict)}
    correctness = {aid: {'expected': verdict, 'actual': observed.get(aid),
                        'correct': observed.get(aid) == verdict} for aid, verdict in expected['assertions'].items()}
    result = {'assertion_correctness': correctness, 'assertions_correct': sum(x['correct'] for x in correctness.values()),
              'assertions_total': len(correctness), 'requirements': []}
    try: checked = validate_semantic_assessment(packet, response)
    except Exception as error:
        return {**result, 'host_valid': False, 'mechanical_pass': False, 'error_type': type(error).__name__}
    def check(name, passed, **details):
        result['requirements'].append({'requirement': name, 'passed': bool(passed), **details})
    check('assertion_verdicts', all(x['correct'] for x in correctness.values()))
    axes = {c['axis']: c for c in checked['checks']}
    check('axis_statuses', set(axes) == set(expected['checks']) and all(
        axes.get(axis, {}).get('status') in rule['allowed_statuses'] for axis, rule in expected['checks'].items()),
        actual={axis: c['status'] for axis, c in axes.items()})
    assertions = {a['assertion_id']: a for a in checked['assertions']}
    for axis, required in expected.get('constraint_record_coverage', {}).items():
        actual = {rid for c in axes.get(axis, {}).get('constraints', []) for rid in c['record_ids']}
        check('constraint_record_coverage:'+axis, actual == set(required), actual=sorted(actual), expected=sorted(required))
    if 'required_assertion_anchor_record_ids' in expected:
        # The v2 requirement has one assertion; keep evidence attached to that assertion.
        if len(assertions) != 1: raise ValueError('unscoped assertion-anchor rule requires exactly one assertion')
        missing = _covered(packet, expected['required_assertion_anchor_record_ids'], next(iter(assertions.values()))['citations'])
        check('required_assertion_anchors', not missing, missing_record_ids=missing)
    for aid, rule in expected.get('assertion_evidence', {}).items():
        citations = assertions.get(aid, {}).get('citations', [])
        missing = _covered(packet, rule.get('record_ids', []), citations)
        absent = [anchor for anchor in rule.get('quote_anchors', []) if not any(anchor in c['quote'] for c in citations)]
        check('assertion_evidence:'+aid, not missing and not absent, missing_record_ids=missing, missing_quote_anchors=absent)
        if rule.get('definition_not_established_by_supplied_source'):
            check('definition_unestablished:'+aid, assertions.get(aid, {}).get('verdict') == 'insufficient_evidence')
    constraints = axes.get('comparability', {}).get('constraints', [])
    if 'comparability_recast_record_ids' in expected:
        required = set(expected['comparability_recast_record_ids'])
        check('comparability_recast_record_ids', any(set(c['record_ids']) == required for c in constraints),
              candidate_record_sets=[sorted(c['record_ids']) for c in constraints], expected=sorted(required))
    for name, rule in expected.get('comparability_constraints', {}).items():
        matches = [c for c in constraints if set(c['record_ids']) == set(rule['record_ids']) and all(
            any(anchor in cite['quote'] for cite in c['citations']) for anchor in rule.get('quote_anchors', []))]
        check('comparability_constraint:'+name, bool(matches), expected_record_ids=sorted(rule['record_ids']),
              candidate_record_sets=[sorted(c['record_ids']) for c in constraints])
    claims = {c['object_id']: c['status'] for c in checked.get('context_claims', [])}
    for object_id, status in expected.get('required_context_claims', {}).items():
        check('context_claim:'+object_id, claims.get(object_id) == status, expected=status, actual=claims.get(object_id))
    result.update(host_valid=True, mechanical_pass=all(r['passed'] for r in result['requirements']))
    return result


def _read(path): return json.loads(Path(path).read_text())


def evaluate(inputs, run, expected_path, output, *, notes_path=None):
    inputs, run, expected_path, output = map(lambda p: Path(p).resolve(), (inputs, run, expected_path, output))
    _verify_manifest(inputs)
    if not (run/'result.json').exists(): raise ValueError('run has not completed; no result.json')
    _verify_manifest(run)
    manifest = _read(inputs/'input-manifest.json')
    result = _read(run/'result.json'); expected = _read(expected_path)['cases']
    request = _read(run/'request.json')
    if request['input_manifest_sha256'] != digest((inputs/'manifest.json').read_bytes()):
        raise ValueError('run does not reference selected frozen inputs')
    notes = _read(notes_path) if notes_path else {'cases': {}}
    if notes_path:
        if notes.get('run_result_sha256') != digest((run/'result.json').read_bytes()) or notes.get('expected_sha256') != digest(expected_path.read_bytes()):
            raise ValueError('independent notes must bind the exact run and expected snapshot')
    accepted = {a['packet_id']: a for a in result.get('assessments', [])}
    reports = []
    for number, ref in enumerate(manifest['packets'], 1):
        case_id = ref['case_id']; gold = expected[case_id]
        packet = _read(inputs/ref['path']); folder = run/f'packet-{number:03d}'
        case_notes = notes.get('cases', {}).get(case_id, {})
        attempts = []
        for path in sorted(folder.glob('attempt-*-response.json')):
            # Only proposal responses; critic responses have an extra suffix.
            parts = path.name.split('-')
            if len(parts) != 3: continue
            attempt = int(parts[1]); response = _read(path)
            score = score_response(packet, response, gold)
            note = case_notes.get('attempts', {}).get(str(attempt))
            audit_path = folder/f'attempt-{attempt}-audit.json'
            audit = _read(audit_path) if audit_path.exists() else None
            audit_note = case_notes.get('critics', {}).get(str(attempt))
            audit_tries = []
            for audit_input in sorted(folder.glob(f'attempt-{attempt}-audit-try-*-input.json')):
                prefix = audit_input.name.removesuffix('-input.json')
                audit_response = folder/(prefix+'-response.json'); rejection = folder/(prefix+'-rejection.json')
                audit_tries.append({'try': int(prefix.rsplit('-', 1)[1]),
                    'input_sha256': digest(audit_input.read_bytes()),
                    'response_sha256': digest(audit_response.read_bytes()) if audit_response.exists() else None,
                    'protocol_rejection': _read(rejection) if rejection.exists() else None})
            mechanical_failures = [r['requirement'] for r in score['requirements'] if not r['passed']]
            attempts.append({'attempt': attempt, 'response_sha256': digest(path.read_bytes()), **score,
                'independent_semantic_note': note, 'critic': {'status': audit['status'] if audit else 'not_validated',
                    'issues': audit['issues'] if audit else [], 'independent_note': audit_note,
                    'protocol_attempts': audit_tries,
                    'mechanical_misses_on_pass': mechanical_failures if audit and audit['status'] == 'pass' else [],
                    'semantic_classification': 'reviewed' if audit_note else 'pending_independent_review'}})
        final = accepted.get(ref['packet_id'])
        final_score = score_response(packet, final, gold) if final else None
        critic_pass = bool(final is not None and result.get('audit_enabled') and any(
            a.get('packet_id') == ref['packet_id'] and a.get('status') == 'pass'
            and a.get('assessment_sha256') == digest(final) for a in result.get('audits', [])))
        final_note = case_notes.get('final')
        semantic_pass = bool(final_note and final_note.get('status') == 'pass' and final_note.get('explanation'))
        status = ('not_accepted' if final is None else 'fail' if not critic_pass or not final_score['mechanical_pass']
                  or (final_note and final_note.get('status') == 'fail') else 'pass' if semantic_pass else 'pending_independent_review')
        reports.append({'case_id': case_id, 'packet_id': ref['packet_id'], 'status': status,
            'accepted': final is not None, 'critic_pass_for_final': critic_pass,
            'initial': attempts[0] if attempts else None, 'attempts': attempts,
            'final': final_score, 'independent_final_note': final_note,
            'required_semantic_review': {'forbidden_missing_material_inference': gold.get('forbidden_missing_material_inference', False),
                'negative_cases': gold.get('negative_cases', []), 'notes': gold.get('notes'),
                'additional_requirement': 'Verify every constraint meaning and exact record scope; matching sets/quotes alone is not semantic truth.'}})
    report = {'schema_version': 'semantic-fixture-independent-evaluation-v3', 'evaluation_only': True,
        'run_result_path': str(run/'result.json'), 'run_result_sha256': digest((run/'result.json').read_bytes()),
        'expected_path': str(expected_path), 'expected_sha256': digest(expected_path.read_bytes()),
        'inputs_manifest_sha256': digest((inputs/'manifest.json').read_bytes()),
        'reviewer_usage': result.get('usage'), 'critic_usage': result.get('audit_usage'),
        'independent_notes_path': str(Path(notes_path).resolve()) if notes_path else None,
        'independent_notes_sha256': digest(Path(notes_path).read_bytes()) if notes_path else None,
        'execution_context': notes.get('execution_context'),
        'statuses': dict(Counter(c['status'] for c in reports)), 'cases': reports,
        'limitations': ['The critic is another model opinion, not ground truth.',
            'Initial verdict counts are diagnostic even when the proposal is rejected; they are not accepted case passes.',
            'Free-text absence claims, semantic scope and critic false positives/misses require independent source review.',
            'Mechanical checks use the current validator; frozen run artifacts and implementation snapshots remain the historical record.']}
    write_new(output, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'run', 'expected', 'output'): parser.add_argument('--'+name, required=True)
    parser.add_argument('--notes')
    args = parser.parse_args()
    report = evaluate(args.inputs, args.run, args.expected, args.output, notes_path=args.notes)
    print(json.dumps({'statuses': report['statuses'], 'output': str(args.output)}, ensure_ascii=False))
