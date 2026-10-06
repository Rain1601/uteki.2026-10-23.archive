"""Scripted reviewer/critic integration; no model calls or heldout answer access."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit import test_semantic_review_v2 as birch_fixture
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.semantic_review import review_semantics
from uteki.infrastructure.research_data.financial_records import digest


class ScriptedActor:
    plan_origin = 'scripted_fixture'

    def __init__(self, behavior): self.behavior, self.requests, self.closed = behavior, [], False

    async def review(self, packet):
        self.requests.append(deepcopy(packet))
        return self.behavior(packet, len(self.requests))

    async def aclose(self): self.closed = True

    def snapshot_usage(self):
        if not self.closed: raise AssertionError('snapshot before close')
        return {'summary': {'requests': len(self.requests), 'plan_origin': self.plan_origin}}


def audit_reply(request, status='pass'):
    return {'packet_id': request['packet_id'], 'assessment_sha256': request['assessment_sha256'],
        'status': status, 'issues': [] if status == 'pass' else [{
            'issue_id': 'review-item-1', 'kind': 'unsupported_claim', 'location': 'checks.0.reason',
            'record_ids': [], 'explanation': 'Clarify the bounded scope of this reason against the supplied source.',
            'citations': []}]}


class SemanticReviewLoopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.inputs = self.root/'inputs'
        self.factory = birch_fixture.SemanticReviewV2Tests()
        self.packet = self.factory.packet()
        self.packet['schema_version'] = 'semantic-review-input-v3'; self.factory.seal(self.packet)
        write_new(self.inputs/'packets/001.json', self.packet)
        ref = {'case_id': 'scripted-loop', 'path': 'packets/001.json',
               'packet_id': self.packet['packet_id'], 'sha256': digest((self.inputs/'packets/001.json').read_bytes()),
               'record_ids': list(self.packet['record_anchors'])}
        write_new(self.inputs/'input-manifest.json', {'schema_version': 'semantic-review-input-manifest-v1',
            'source_origin': 'synthetic_fixture', 'dataset': None, 'scope': None, 'packets': [ref]})
        write_new(self.inputs/'manifest.json', {'files': {str(p.relative_to(self.inputs)): digest(p.read_bytes())
            for p in self.inputs.rglob('*') if p.is_file()}})
        self.original = (self.inputs/'packets/001.json').read_bytes()

    def propose(self, packet, number):
        result = self.factory.response(self.packet)
        result['checks'][0]['reason'] = f'Scripted bounded proposal {number}.'
        return result

    def run_loop(self, reviewer=None, auditor=None, maximum=2, audit_maximum=1):
        reviewer = ScriptedActor(reviewer or self.propose)
        auditor = ScriptedActor(auditor or (lambda request, number: audit_reply(request)))
        events = []
        result = asyncio.run(review_semantics(self.inputs, self.root/'run',
            reviewer_factory=lambda path: reviewer, auditor_factory=lambda path: auditor,
            max_attempts_per_packet=maximum, max_audit_attempts=audit_maximum, notify=events.append))
        self.assertTrue(reviewer.closed); self.assertTrue(auditor.closed)
        self.assertEqual((self.inputs/'packets/001.json').read_bytes(), self.original)
        _verify_manifest(self.inputs); _verify_manifest(self.root/'run')
        self.assertEqual(result['semantic_acceptance'], 'model_audited_requires_independent_evaluation')
        return result, reviewer, auditor, events

    def test_valid_proposal_requires_audit_pass_and_accounts_for_both_actors(self):
        result, reviewer, auditor, events = self.run_loop()
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 1)
        self.assertEqual(result['usage']['summary']['requests'], 1)
        self.assertEqual(result['audit_usage']['summary']['requests'], 1)
        self.assertEqual(result['audits'][0]['status'], 'pass')
        self.assertEqual(auditor.requests[0]['packet'], self.packet)
        self.assertNotIn('expected', auditor.requests[0])

    def test_revise_then_pass_preserves_every_proposal_audit_and_feedback(self):
        result, reviewer, auditor, events = self.run_loop(auditor=lambda request, number:
            audit_reply(request, 'revise' if number == 1 else 'pass'))
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 2); self.assertEqual(len(auditor.requests), 2)
        feedback = reviewer.requests[1]['host_validation_feedback']
        self.assertEqual(feedback['stage'], 'semantic_audit')
        self.assertEqual(feedback['previous_assessment'], auditor.requests[0]['assessment'])
        self.assertEqual(feedback['audit']['status'], 'revise')
        self.assertNotEqual(auditor.requests[0]['assessment_sha256'], auditor.requests[1]['assessment_sha256'])
        folder = self.root/'run/packet-001'
        for attempt in (1, 2):
            for kind in ('response', 'assessment', 'audit-input', 'audit-response', 'audit'):
                self.assertTrue((folder/f'attempt-{attempt}-{kind}.json').exists())
        self.assertTrue((folder/'attempt-1-rejection.json').exists())
        self.assertEqual(json.loads((folder/'assessment.json').read_text()), result['assessments'][0])
        self.assertEqual([e['status'] for e in events], ['revision_requested', 'assessment_recorded'])

    def test_two_revisions_exhaust_cap_without_adopting_last_valid_proposal(self):
        result, reviewer, auditor, events = self.run_loop(auditor=lambda request, number: audit_reply(request, 'revise'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['assessments'], [])
        self.assertEqual(len(reviewer.requests), 2); self.assertEqual(len(auditor.requests), 2)
        self.assertFalse((self.root/'run/packet-001/assessment.json').exists())
        self.assertFalse((self.root/'run/packet-001/attempt-3-response.json').exists())

    def test_schema_retry_and_semantic_revision_share_same_two_proposal_limit(self):
        def propose(packet, number):
            response = self.propose(packet, number)
            if number == 1: response['checks'][0]['constraints'][0]['record_ids'] = []
            return response
        result, reviewer, auditor, events = self.run_loop(propose, lambda request, number: audit_reply(request, 'revise'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 2); self.assertEqual(len(auditor.requests), 1)
        self.assertNotIn('audit', reviewer.requests[1]['host_validation_feedback'])
        self.assertFalse((self.root/'run/packet-001/attempt-1-audit-input.json').exists())
        self.assertFalse((self.root/'run/packet-001/attempt-3-response.json').exists())

    def test_three_proposal_cap_allows_schema_repair_then_audited_semantic_revision(self):
        def propose(packet, number):
            response = self.propose(packet, number)
            if number == 1: response['checks'][0]['constraints'][0]['record_ids'] = []
            return response
        def audit(request, number): return audit_reply(request, 'revise' if number == 1 else 'pass')
        result, reviewer, auditor, events = self.run_loop(propose, audit, maximum=3)
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 3); self.assertEqual(len(auditor.requests), 2)
        self.assertEqual(reviewer.requests[1]['host_validation_feedback']['stage'], 'proposal')
        self.assertNotIn('audit', reviewer.requests[1]['host_validation_feedback'])
        self.assertEqual(reviewer.requests[2]['host_validation_feedback']['stage'], 'semantic_audit')
        self.assertEqual(reviewer.requests[2]['host_validation_feedback']['previous_assessment'], auditor.requests[0]['assessment'])
        self.assertEqual([audit['attempt'] for audit in result['audits']], [2, 3])
        self.assertEqual(result['usage']['summary']['requests'], 3)
        self.assertEqual(result['audit_usage']['summary']['requests'], 2)
        folder = self.root/'run/packet-001'
        self.assertTrue((folder/'attempt-1-rejection.json').exists())
        self.assertTrue((folder/'attempt-2-rejection.json').exists())
        self.assertFalse((folder/'attempt-1-audit-input.json').exists())
        self.assertFalse((folder/'attempt-4-response.json').exists())
        self.assertEqual(json.loads((self.root/'run/request.json').read_text())['max_attempts_per_packet'], 3)

    def test_invalid_critic_is_preserved_but_never_used_as_revision_feedback(self):
        def wrong(request, number):
            response = audit_reply(request, 'revise'); response['assessment_sha256'] = '0'*64
            return response
        result, reviewer, auditor, events = self.run_loop(auditor=wrong)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 1)
        self.assertEqual(result['audits'], [])
        self.assertEqual(result['failures'][0]['error']['stage'], 'audit')
        self.assertTrue((self.root/'run/packet-001/attempt-1-audit-response.json').exists())
        self.assertFalse((self.root/'run/packet-001/assessment.json').exists())

    def test_critic_protocol_retry_fixes_offset_on_same_assessment_without_new_proposal(self):
        def audit(request, number):
            response = audit_reply(request, 'revise' if number == 1 else 'pass')
            if number == 1:
                citation = self.factory.citation(self.packet, 'Operating income 20 20')
                citation['source_start'] += 1
                response['issues'][0]['citations'] = [citation]
            return response
        result, reviewer, auditor, events = self.run_loop(auditor=audit, audit_maximum=2)
        self.assertEqual(result['status'], 'assessed')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 2)
        self.assertNotIn('host_validation_feedback', reviewer.requests[0])
        feedback = auditor.requests[1]['host_validation_feedback']
        self.assertEqual(feedback['stage'], 'audit')
        self.assertIn('source_start', feedback['reason'])
        self.assertEqual({k: v for k, v in auditor.requests[1].items() if k != 'host_validation_feedback'},
                         auditor.requests[0])
        self.assertEqual(auditor.requests[0]['assessment_sha256'], auditor.requests[1]['assessment_sha256'])
        folder = self.root/'run/packet-001'
        for attempt in (1, 2):
            for kind in ('input', 'response'):
                self.assertTrue((folder/f'attempt-1-audit-try-{attempt}-{kind}.json').exists())
        self.assertTrue((folder/'attempt-1-audit-try-1-rejection.json').exists())
        self.assertFalse((folder/'attempt-1-audit-try-2-rejection.json').exists())
        self.assertEqual(result['audits'][0]['status'], 'pass')
        self.assertEqual(result['audit_usage']['summary']['requests'], 2)

    def test_two_invalid_critic_attempts_do_not_adopt_or_feed_back_to_proposal(self):
        def audit(request, number):
            response = audit_reply(request, 'revise')
            citation = self.factory.citation(self.packet, 'Operating income 20 20')
            citation['source_start'] += 1
            response['issues'][0]['citations'] = [citation]
            return response
        result, reviewer, auditor, events = self.run_loop(auditor=audit, audit_maximum=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 2)
        self.assertEqual(result['audits'], []); self.assertEqual(result['assessments'], [])
        self.assertEqual(auditor.requests[0]['assessment_sha256'], auditor.requests[1]['assessment_sha256'])
        folder = self.root/'run/packet-001'
        self.assertTrue((folder/'attempt-1-audit-try-2-rejection.json').exists())
        self.assertFalse((folder/'attempt-1-audit-try-3-input.json').exists())
        self.assertFalse((folder/'attempt-2-response.json').exists())
        self.assertEqual(json.loads((self.root/'run/request.json').read_text())['max_audit_attempts'], 2)

    def test_invalid_critic_attempt_limit_is_rejected_before_any_actor_initializes(self):
        for limit in (0, 3, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                asyncio.run(review_semantics(self.inputs, self.root/'run', max_audit_attempts=limit,
                    reviewer_factory=lambda path: self.fail('reviewer initialized'),
                    auditor_factory=lambda path: self.fail('auditor initialized')))
        self.assertFalse((self.root/'run').exists())

    def test_critic_exception_closes_both_clients_and_does_not_echo_provider_body(self):
        def fail(request, number): raise RuntimeError('secret-provider-header')
        result, reviewer, auditor, events = self.run_loop(auditor=fail, audit_maximum=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1)
        self.assertEqual(result['failures'][0]['error']['stage'], 'audit')
        self.assertNotIn('secret-provider-header', json.dumps(result)+json.dumps(events))

    def test_audit_budget_failure_does_not_allow_a_new_proposal(self):
        class BudgetExceeded(RuntimeError): pass
        def fail(request, number): raise BudgetExceeded('budget exhausted')
        result, reviewer, auditor, events = self.run_loop(auditor=fail, audit_maximum=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 1)
        self.assertEqual(result['failures'][0]['error']['error_type'], 'BudgetExceeded')

    def test_proposal_budget_failure_never_calls_auditor(self):
        class BudgetExceeded(RuntimeError): pass
        def fail(request, number): raise BudgetExceeded('budget exhausted')
        result, reviewer, auditor, events = self.run_loop(reviewer=fail)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 1); self.assertEqual(len(auditor.requests), 0)

    def test_network_and_runtime_failure_stop_run_without_retrying_or_requesting_other_packets(self):
        second = self.factory.packet(source='birch-annual-b')
        second['schema_version'] = 'semantic-review-input-v3'; self.factory.seal(second)
        write_new(self.inputs/'packets/002.json', second)
        spec = json.loads((self.inputs/'input-manifest.json').read_text())
        spec['packets'].append({'case_id': 'second-packet', 'path': 'packets/002.json',
            'packet_id': second['packet_id'], 'sha256': digest((self.inputs/'packets/002.json').read_bytes()),
            'record_ids': [r['record']['record_id'] for r in second['records']]})
        (self.inputs/'input-manifest.json').write_text(json.dumps(spec))
        (self.inputs/'manifest.json').write_text(json.dumps({'files': {
            str(p.relative_to(self.inputs)): digest(p.read_bytes())
            for p in self.inputs.rglob('*') if p.is_file() and p.name != 'manifest.json'}}))
        for phase in ('proposal', 'audit'):
            for error_type in (ConnectionError, TimeoutError, RuntimeError):
                with self.subTest(phase=phase, error=error_type.__name__):
                    def fail(request, number): raise error_type('private provider diagnostic')
                    reviewer = ScriptedActor(fail if phase == 'proposal' else self.propose)
                    auditor = ScriptedActor(fail if phase == 'audit' else lambda r, n: audit_reply(r))
                    output = self.root/f'run-{phase}-{error_type.__name__}'
                    events = []
                    result = asyncio.run(review_semantics(self.inputs, output,
                        reviewer_factory=lambda path: reviewer, auditor_factory=lambda path: auditor,
                        max_attempts_per_packet=3, max_audit_attempts=2, notify=events.append))
                    self.assertEqual(result['status'], 'partial')
                    self.assertEqual(result['packets_requested'], 2)
                    self.assertEqual(result['packets_assessed'], 0)
                    self.assertEqual(result['unassessed_packet_ids'], [self.packet['packet_id'], second['packet_id']])
                    self.assertEqual(len(reviewer.requests), 1)
                    self.assertEqual(len(auditor.requests), 0 if phase == 'proposal' else 1)
                    self.assertTrue(reviewer.closed); self.assertTrue(auditor.closed)
                    self.assertEqual(result['usage']['summary']['requests'], 1)
                    self.assertEqual(result['failures'][0]['error']['error_type'], error_type.__name__)
                    self.assertTrue(result['failures'][0]['error']['stop_run'])
                    self.assertNotIn('private provider diagnostic', json.dumps(result)+json.dumps(events))
                    self.assertTrue((output/'packet-001/attempt-1-rejection.json').exists())
                    self.assertFalse((output/'packet-001/attempt-2-response.json').exists())
                    self.assertFalse((output/'packet-002').exists())
                    _verify_manifest(output)

    def test_cancellation_during_audit_persists_proposal_and_closes_both(self):
        def cancel(request, number): raise asyncio.CancelledError()
        result, reviewer, auditor, events = self.run_loop(auditor=cancel, audit_maximum=2)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['assessments'], [])
        self.assertTrue((self.root/'run/packet-001/attempt-1-assessment.json').exists())
        self.assertTrue((self.root/'run/packet-001/attempt-1-audit-input.json').exists())
        self.assertEqual(result['audit_usage']['summary']['requests'], 1)


if __name__ == '__main__': unittest.main()
