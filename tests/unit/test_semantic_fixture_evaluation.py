"""Fixed fixture scoring rejects verdict-only and record-set-only successes."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('fixture_evaluation', ROOT/'experiments/data_agent_query/semantic-review-v3/evaluate_fixtures.py')
evaluation = importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluation)


def gold_response(packet, gold):
    citations = [{'source_snapshot_id': b['source_snapshot_id'], 'block_id': b['block_id'],
                  'quote': b['text'], 'source_start': 0} for b in packet['source_blocks']]
    checks = []
    for axis, rule in gold['checks'].items():
        status = rule['allowed_statuses'][0]
        groups = [list(packet['record_anchors'])]
        if axis == 'comparability':
            groups = ([gold['comparability_recast_record_ids']] if 'comparability_recast_record_ids' in gold else
                      [r['record_ids'] for r in gold.get('comparability_constraints', {}).values()])
        checks.append({'axis': axis, 'status': status, 'reason': 'Test oracle only.',
            'constraints': [{'record_ids': list(ids), 'statement': 'Test oracle only.', 'citations': deepcopy(citations)}
                for ids in groups] if status == 'constraints_found' else [],
            'unresolved_questions': ['Which definition applies?'] if status == 'insufficient_evidence' else []})
    return {'packet_id': packet['packet_id'], 'checks': checks,
        'assertions': [{'assertion_id': aid, 'verdict': verdict, 'reason': 'Test oracle only.',
                       'citations': deepcopy(citations) if verdict != 'insufficient_evidence' else []}
                      for aid, verdict in gold['assertions'].items()],
        'context_claims': [{'object_id': o['object_id'], 'status': o['status']} for o in packet['context_inventory']['objects']],
        'context_requests': []}


class SemanticFixtureEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases = {}
        for version in ('v2', 'v3'):
            root = ROOT/'benchmarks/data_agent/semantic_review'/version
            expected = json.loads((root/'expected.json').read_text())['cases']
            for case in json.loads((root/'cases.json').read_text())['cases']:
                self.cases[case['case_id']] = (case['packet'], expected[case['case_id']])

    def test_all_frozen_requirement_shapes_are_supported_without_changing_expected(self):
        for cid, (packet, gold) in self.cases.items():
            with self.subTest(case=cid):
                result = evaluation.score_response(packet, gold_response(packet, gold), gold)
                self.assertTrue(result['mechanical_pass'], result)
                self.assertNotIn('semantic_pass', result)

    def test_incorrect_verdict_does_not_pass_even_with_correct_source_quotes(self):
        packet, gold = self.cases['sv3-001']; response = gold_response(packet, gold)
        response['assertions'][-1]['verdict'] = 'supported'
        result = evaluation.score_response(packet, response, gold)
        self.assertFalse(result['mechanical_pass'])
        self.assertEqual(result['assertions_correct'], 3)

    def test_recast_current_period_scope_is_rejected_by_fixed_record_sets(self):
        packet, gold = self.cases['sv3-002']; response = gold_response(packet, gold)
        group = next(c for c in response['checks'] if c['axis'] == 'comparability')['constraints'][0]
        group['record_ids'].append('northstar-disclosure-b-seg24')
        result = evaluation.score_response(packet, response, gold)
        self.assertTrue(result['host_valid'])
        self.assertFalse(result['mechanical_pass'])
        self.assertTrue(any(r['requirement'] == 'comparability_constraint:historical_segment_recast' and not r['passed']
                            for r in result['requirements']))

    def test_correct_record_set_with_irrelevant_quote_does_not_satisfy_expected_qualifier(self):
        packet, gold = self.cases['sv3-002']; response = gold_response(packet, gold)
        group = next(c for c in response['checks'] if c['axis'] == 'comparability')['constraints'][1]
        group['citations'] = [group['citations'][0]]
        result = evaluation.score_response(packet, response, gold)
        self.assertTrue(result['host_valid'])
        self.assertFalse(result['mechanical_pass'])

    def test_omitted_required_context_claim_is_not_inferred_from_other_correct_fields(self):
        packet, gold = self.cases['sv2-002']; response = gold_response(packet, gold)
        response['context_claims'] = []
        result = evaluation.score_response(packet, response, gold)
        self.assertTrue(result['host_valid'])
        self.assertFalse(result['mechanical_pass'])

    def test_raw_assertion_diagnostics_do_not_turn_host_rejection_into_pass(self):
        packet, gold = self.cases['sv2-001']; response = gold_response(packet, gold)
        response['checks'][0]['constraints'][0]['record_ids'] = []
        result = evaluation.score_response(packet, response, gold)
        self.assertEqual(result['assertions_correct'], 1)
        self.assertFalse(result['host_valid']); self.assertFalse(result['mechanical_pass'])

    def test_final_pass_requires_acceptance_bound_audit_and_independent_note(self):
        packet, gold = self.cases['sv3-001']; response = gold_response(packet, gold)
        canonical = evaluation.validate_semantic_assessment(packet, response)
        for accepted, audit_pass, note_pass, expected_status in (
                (False, True, True, 'not_accepted'), (True, False, True, 'fail'),
                (True, True, False, 'pending_independent_review'), (True, True, True, 'pass')):
            with self.subTest(accepted=accepted, audit=audit_pass, note=note_pass), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); inputs = root/'inputs'; run = root/'run'
                def write(path, value): evaluation.write_new(path, value)
                def seal(folder):
                    write(folder/'manifest.json', {'files': {str(p.relative_to(folder)): evaluation.digest(p.read_bytes())
                        for p in folder.rglob('*') if p.is_file()}})
                write(inputs/'packet.json', packet)
                write(inputs/'input-manifest.json', {'packets': [{'case_id': 'sv3-001', 'packet_id': packet['packet_id'],
                    'path': 'packet.json', 'sha256': evaluation.digest((inputs/'packet.json').read_bytes())}]})
                seal(inputs)
                write(root/'expected.json', {'cases': {'sv3-001': gold}})
                write(run/'request.json', {'input_manifest_sha256': evaluation.digest((inputs/'manifest.json').read_bytes())})
                write(run/'packet-001/attempt-1-response.json', response)
                write(run/'result.json', {'audit_enabled': True, 'assessments': [canonical] if accepted else [],
                    'audits': [{'packet_id': packet['packet_id'], 'status': 'pass' if audit_pass else 'revise',
                                'assessment_sha256': evaluation.digest(canonical)}]})
                seal(run)
                notes = None
                if note_pass:
                    notes = root/'notes.json'
                    write(notes, {'run_result_sha256': evaluation.digest((run/'result.json').read_bytes()),
                        'expected_sha256': evaluation.digest((root/'expected.json').read_bytes()),
                        'cases': {'sv3-001': {'final': {'status': 'pass', 'explanation': 'Test-only independent review.'}}}})
                report = evaluation.evaluate(inputs, run, root/'expected.json', root/'report.json', notes_path=notes)
                self.assertEqual(report['cases'][0]['status'], expected_status)


if __name__ == '__main__': unittest.main()
