"""Semantic runner integration with synthetic sources and scripted reviewers only."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.unit import test_semantic_review_benchmark as fixtures
from tests.unit import test_record_review_run as record_fixture
from uteki.agents.data_query.semantic_review import review_semantics
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import prepare_semantic_inputs


class Reviewer:
    plan_origin = 'scripted_fixture'

    def __init__(self, behavior):
        self.behavior, self.requests, self.closed = behavior, [], False

    async def review(self, packet):
        self.requests.append(deepcopy(packet))
        return self.behavior(packet, len(self.requests))

    async def aclose(self): self.closed = True

    def snapshot_usage(self):
        if not self.closed: raise AssertionError('usage snapshot before close')
        return {'summary': {'requests': len(self.requests), 'plan_origin': self.plan_origin}}


class SemanticReviewRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.inputs = self.root/'inputs'
        self.spec = fixtures.benchmark.prepare(fixtures.FIXTURES/'cases.json', self.inputs,
                                              case_ids=['sr-001', 'sr-005'])
        expected = json.loads((fixtures.FIXTURES/'expected.json').read_text())['cases']
        self.expected = {ref['packet_id']: expected[ref['case_id']] for ref in self.spec['packets']}
        self.original = self.hashes(self.inputs)

    def hashes(self, root):
        return {str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}

    def correct(self, packet, number):
        return fixtures.response_for(packet, self.expected[packet['packet_id']])

    def execute(self, behavior=None, **kwargs):
        reviewer = Reviewer(behavior or self.correct)
        events = []
        result = asyncio.run(review_semantics(self.inputs, self.root/'output',
            reviewer_factory=lambda path: reviewer, notify=events.append, **kwargs))
        self.assertTrue(reviewer.closed)
        self.assertEqual(self.hashes(self.inputs), self.original)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['adoption'], 'unchanged_candidate')
        self.assertEqual(result['semantic_acceptance'], 'requires_independent_evaluation')
        _verify_manifest(self.root/'output')
        return result, reviewer, events

    def test_complete_fixture_run_keeps_scopes_separate_and_needs_independent_evaluation(self):
        result, reviewer, events = self.execute()
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(result['packets_assessed'], 2)
        self.assertEqual(result['unassessed_packet_ids'], [])
        self.assertEqual([e['status'] for e in events], ['assessment_recorded']*2)
        self.assertNotEqual(reviewer.requests[0]['scope'], reviewer.requests[1]['scope'])
        request = json.loads((self.root/'output/request.json').read_text())
        self.assertEqual(request['input_manifest_sha256'], digest((self.inputs/'manifest.json').read_bytes()))
        self.assertEqual(request['max_attempts_per_packet'], 1)
        self.assertIn('validator', request['implementation_sha256'])

    def test_invalid_quote_retries_once_against_original_packet(self):
        def behavior(packet, number):
            response = self.correct(packet, number)
            if number == 1: response['assertions'][0]['citations'][0]['quote'] = 'invented evidence'
            return response
        result, reviewer, events = self.execute(behavior, max_attempts_per_packet=2)
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 3)
        self.assertIn('host_validation_feedback', reviewer.requests[1])
        self.assertEqual({k: v for k, v in reviewer.requests[1].items() if k != 'host_validation_feedback'},
                         reviewer.requests[0])
        self.assertEqual(events[0]['status'], 'rejected')

    def test_schema_feedback_has_field_and_type_without_input_values_and_stops_after_two_attempts(self):
        secret = 'synthetic-sensitive-model-value-do-not-echo'
        rejected_responses = []
        first_packet_id = self.spec['packets'][0]['packet_id']
        def behavior(packet, number):
            response = self.correct(packet, number)
            if packet['packet_id'] == first_packet_id:
                response['checks'][0]['constraints'][0]['record_ids'] = []
                response['assertions'][0]['verdict'] = secret
                rejected_responses.append(deepcopy(response))
            return response
        result, reviewer, events = self.execute(behavior, max_attempts_per_packet=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['packets_assessed'], 1)
        self.assertEqual([r['packet_id'] for r in reviewer.requests],
                         [first_packet_id, first_packet_id, self.spec['packets'][1]['packet_id']])
        feedback = reviewer.requests[1]['host_validation_feedback']
        self.assertEqual(feedback['error_type'], 'ValidationError')
        details = json.loads(feedback['reason'])
        self.assertIn({'field': 'checks.0.constraints.0.record_ids', 'type': 'too_short'}, details)
        self.assertIn({'field': 'assertions.0.verdict', 'type': 'literal_error'}, details)
        self.assertTrue(all(set(detail) == {'field', 'type'} for detail in details))
        self.assertNotIn(secret, json.dumps(feedback))
        self.assertNotIn(secret, json.dumps(events))
        for attempt, original in enumerate(rejected_responses, 1):
            folder = self.root/'output/packet-001'
            self.assertEqual(json.loads((folder/f'attempt-{attempt}-response.json').read_text()), original)
            self.assertNotIn(secret, (folder/f'attempt-{attempt}-rejection.json').read_text())
        self.assertEqual(len(rejected_responses), 2)
        self.assertFalse((self.root/'output/packet-001/attempt-3-response.json').exists())
        self.assertEqual(json.loads((self.root/'output/request.json').read_text())['max_attempts_per_packet'], 2)

    def test_default_one_attempt_keeps_bad_case_unassessed_and_continues_next(self):
        def behavior(packet, number):
            response = self.correct(packet, number)
            if number == 1: response['assertions'][0]['citations'][0]['source_snapshot_id'] = 'foreign-source'
            return response
        result, reviewer, events = self.execute(behavior)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 2)
        self.assertEqual(result['packets_assessed'], 1)
        self.assertEqual(result['unassessed_packet_ids'], [self.spec['packets'][0]['packet_id']])
        self.assertEqual(events[0]['status'], 'rejected')

    def test_budget_failure_stops_remaining_packets_without_extra_attempt(self):
        class BudgetExceeded(RuntimeError): pass
        def fail(packet, number): raise BudgetExceeded('budget exhausted')
        result, reviewer, events = self.execute(fail, max_attempts_per_packet=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1)
        self.assertEqual(len(result['unassessed_packet_ids']), 2)
        self.assertEqual(events[0]['error_type'], 'BudgetExceeded')

    def test_cancellation_saves_partial_artifacts_and_closes_client(self):
        def cancel(packet, number):
            if number == 2: raise asyncio.CancelledError()
            return self.correct(packet, number)
        result, reviewer, events = self.execute(cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['packets_assessed'], 1)
        self.assertEqual(result['failures'][-1]['error_type'], 'CancelledError')
        self.assertEqual(result['usage']['summary']['requests'], 2)

    def test_provider_failure_closes_client_and_sanitizes_diagnostic(self):
        def fail(packet, number): raise RuntimeError('Authorization: do-not-persist-secret')
        result, reviewer, events = self.execute(fail)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['packets_assessed'], 0)
        self.assertTrue(all(event['reason'] == 'RuntimeError' for event in events))
        self.assertNotIn('do-not-persist-secret', '\n'.join(p.read_text() for p in (self.root/'output').rglob('*.json')))

    def test_factory_failure_is_recorded_with_no_false_usage(self):
        def factory(path): raise RuntimeError('client initialization failed')
        result = asyncio.run(review_semantics(self.inputs, self.root/'output', reviewer_factory=factory))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['plan_origin'], 'not_started')
        self.assertIsNone(result['usage'])
        self.assertEqual(result['packets_assessed'], 0)
        _verify_manifest(self.root/'output')

    def test_unsealed_input_mutation_is_rejected_before_factory(self):
        packet = self.inputs/self.spec['packets'][0]['path']
        packet.write_text(packet.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            asyncio.run(review_semantics(self.inputs, self.root/'output',
                reviewer_factory=lambda path: self.fail('reviewer initialized')))
        self.assertFalse((self.root/'output').exists())

    def test_sealed_scope_and_origin_spoofing_are_rejected_before_factory(self):
        for mode in ('scope', 'origin', 'reference'):
            inputs = self.root/mode; shutil.copytree(self.inputs, inputs)
            spec = deepcopy(self.spec); ref = spec['packets'][0]
            packet_path = inputs/ref['path']; packet = json.loads(packet_path.read_text())
            if mode == 'scope': packet['scope']['source_snapshot_ids'] = ['foreign-source']
            elif mode == 'origin': packet['source_origin'] = 'frozen_dataset'
            packet['packet_id'] = 'semantic-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]
            packet_path.write_text(json.dumps(packet))
            ref['packet_id'] = packet['packet_id'] if mode != 'reference' else 'semantic-wrong'
            ref['sha256'] = digest(packet_path.read_bytes())
            (inputs/'input-manifest.json').write_text(json.dumps(spec))
            (inputs/'manifest.json').write_text(json.dumps({'files': {str(p.relative_to(inputs)): digest(p.read_bytes())
                for p in inputs.rglob('*') if p.is_file() and p.name != 'manifest.json'}}))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                asyncio.run(review_semantics(inputs, self.root/(mode+'-output'),
                    reviewer_factory=lambda path: self.fail('reviewer initialized')))

    def test_limits_and_existing_or_nested_output_are_rejected_before_factory(self):
        for limit in (0, 4, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                asyncio.run(review_semantics(self.inputs, self.root/'output', max_attempts_per_packet=limit,
                    reviewer_factory=lambda path: self.fail('reviewer initialized')))
        for output in (self.inputs, self.inputs/'nested'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                asyncio.run(review_semantics(self.inputs, output, reviewer_factory=lambda path: self.fail('called')))
        existing = self.root/'output'; existing.mkdir(); (existing/'keep').write_text('intact')
        with self.assertRaises(FileExistsError):
            asyncio.run(review_semantics(self.inputs, existing, reviewer_factory=lambda path: self.fail('called')))
        self.assertEqual((existing/'keep').read_text(), 'intact')

    def test_frozen_dataset_review_cannot_modify_or_write_inside_dataset(self):
        fixture = record_fixture.RecordReviewRunTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        inputs = self.root/'frozen-inputs'
        prepare_semantic_inputs(fixture.inputs,
            [{'task_id': 'frozen-case', 'record_ids': fixture.ids, 'axes': ['value'], 'assertions': []}], inputs)
        original_dataset = self.hashes(fixture.dataset)
        reviewer = Reviewer(lambda packet, number: {'packet_id': packet['packet_id'],
            'checks': [{'axis': 'value', 'status': 'none_found_in_context', 'reason': 'Scripted numeric check.',
                        'constraints': [], 'unresolved_questions': []}], 'assertions': [], 'context_requests': []})
        result = asyncio.run(review_semantics(inputs, self.root/'frozen-output', reviewer_factory=lambda path: reviewer))
        self.assertEqual(result['status'], 'assessed')
        self.assertTrue(reviewer.closed)
        self.assertEqual(self.hashes(fixture.dataset), original_dataset)
        with self.assertRaisesRegex(ValueError, 'inside frozen dataset'):
            asyncio.run(review_semantics(inputs, fixture.dataset/'review', reviewer_factory=lambda path: self.fail('called')))
        self.assertEqual(self.hashes(fixture.dataset), original_dataset)

    def test_resealed_candidate_mutation_cannot_escape_frozen_dataset_binding(self):
        fixture = record_fixture.RecordReviewRunTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        inputs = self.root/'frozen-inputs'
        spec = prepare_semantic_inputs(fixture.inputs,
            [{'task_id': 'frozen-case', 'record_ids': fixture.ids, 'axes': ['value'], 'assertions': []}], inputs)
        ref = spec['packets'][0]; packet_path = inputs/ref['path']
        packet = json.loads(packet_path.read_text())
        packet['records'][0]['record']['value_decimal'] = '999999'
        packet['records'][0]['record_sha256'] = digest(packet['records'][0]['record'])
        packet['packet_id'] = 'semantic-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]
        packet_path.write_text(json.dumps(packet))
        ref.update(packet_id=packet['packet_id'], sha256=digest(packet_path.read_bytes()))
        (inputs/'input-manifest.json').write_text(json.dumps(spec))
        manifest_path = inputs/'manifest.json'; manifest = json.loads(manifest_path.read_text())
        for name in (ref['path'], 'input-manifest.json'):
            manifest['files'][name] = digest((inputs/name).read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        original_dataset = self.hashes(fixture.dataset)
        with self.assertRaises(ValueError):
            asyncio.run(review_semantics(inputs, self.root/'output', reviewer_factory=lambda path: self.fail('called')))
        self.assertEqual(self.hashes(fixture.dataset), original_dataset)
        self.assertFalse((self.root/'output').exists())


if __name__ == '__main__': unittest.main()
