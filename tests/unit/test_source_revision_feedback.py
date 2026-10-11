"""Source-only diagnostics never replace complete dual review; zero API calls.

The frozen E6-V2 R3-S1 failure is a regression input, not a production answer
fixture. Mutations use private temporary copies and preserve the original run.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from uteki.agents.data_query.answer_handoff import (
    _validate_source_assessment, load_reviewed_data, review_data_answer,
    validate_source_revision_feedback,
)
from uteki.agents.data_query.coordinator import _verify_review_feedback
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit.test_answer_handoff import ScriptedRole
from tests.unit import test_independent_question_handoff as synthetic
from tests.unit import test_source_review_policy as source_fixtures


REPO = Path(__file__).resolve().parents[2]
ORIGINAL = REPO / 'output/e6-repeatability-20261010-r2/R3/S1/run-r1/attempt-01/review-01'


class SourceRevisionFeedbackTests(unittest.TestCase):
    def setUp(self):
        if not ORIGINAL.is_dir():
            self.skipTest('Frozen original E6-V2 R3-S1 run is unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.review = self.root / 'review'
        shutil.copytree(ORIGINAL, self.review)
        self.packet = self.read('input.json')
        self.request = CompanyQueryInput(question=self.packet['question'],
            dataset=self.packet['dataset_ref']['path'], scope=self.packet['scope'],
            purpose=self.packet['purpose'])

    def read(self, name):
        return json.loads((self.review / name).read_text())

    def write(self, name, value):
        (self.review / name).write_text(json.dumps(value, ensure_ascii=False))

    def seal(self):
        self.write('manifest.json', {'files': {
            str(p.relative_to(self.review)): digest(p.read_bytes())
            for p in sorted(self.review.rglob('*')) if p.is_file() and p.name != 'manifest.json'}})

    def feedback(self, payload=None):
        return {'prior_query_ref': self.packet['query_ref'],
                'prior_review_ref': {'path': str(self.review),
                    'manifest_sha256': digest((self.review / 'manifest.json').read_bytes())},
                'source_revision': payload if payload is not None else
                    validate_source_revision_feedback(self.review, self.packet)}

    def verify(self, payload=None, request=None):
        request = request or self.request
        _verify_review_feedback(self.feedback(payload), request, request.scope, Path(request.dataset))

    def assert_rejected(self):
        with self.assertRaises(ValueError):
            validate_source_revision_feedback(self.review, self.packet)

    def test_original_legal_negative_source_feedback_is_recomputed_without_analysis_approval(self):
        source, eligible = _validate_source_assessment(self.packet, self.read('source-response.json'))
        self.assertFalse(eligible)
        partial = validate_source_revision_feedback(self.review, self.packet)
        self.assertEqual(partial['schema_version'], 'source-only-revision-v1')
        self.assertEqual(partial['source_assessment'], source)
        self.assertEqual(partial['question_protocol_failure']['code'],
                         'duplicate_check_requires_distinct_scope')
        self.assertIs(partial['analysis_eligible'], False)
        self.verify(partial)
        with self.assertRaises(ValueError):
            load_reviewed_data(self.review, expected_scope=self.packet['scope'],
                expected_review_manifest_sha256=self.feedback(partial)['prior_review_ref']['manifest_sha256'])

    def test_new_review_retains_negative_feedback_and_both_failed_question_attempts(self):
        source = self.read('source-response.json')
        question = self.read('question-response-01.json')
        source_role = ScriptedRole(lambda _: deepcopy(source))
        question_role = ScriptedRole(lambda _: deepcopy(question))
        output = self.root / 'new-review'
        result = asyncio.run(review_data_answer(self.packet, output,
            reviewer_factory=lambda _: source_role, question_reviewer_factory=lambda _: question_role))
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['assessment'])
        self.assertIs(result['analysis_eligible'], False)
        self.assertEqual(len(source_role.packets), 1)
        self.assertEqual(len(question_role.packets), 2)
        self.assertTrue(source_role.closed and question_role.closed)
        partial = validate_source_revision_feedback(output, self.packet)
        self.assertEqual(result['revision_feedback'], partial)
        self.assertFalse((output / 'response.json').exists())

    def test_changed_question_company_cutoff_and_purpose_cannot_receive_feedback(self):
        partial = validate_source_revision_feedback(self.review, self.packet)
        for name, mutate in (
            ('question', lambda x: x.update(question='A different question')),
            ('company', lambda x: x['scope'].update(company_ids=['unrelated-company'])),
            ('cutoff', lambda x: x['scope'].update(knowledge_cutoff='2026-02-05')),
            ('purpose', lambda x: x.update(purpose='question_answer')),
        ):
            value = self.request.model_dump(mode='json')
            mutate(value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(partial, CompanyQueryInput.model_validate(value))

    def test_external_feedback_content_cannot_be_changed(self):
        partial = validate_source_revision_feedback(self.review, self.packet)
        partial['source_assessment']['revision_requests'] = ['Invented replacement instruction']
        with self.assertRaises(ValueError):
            self.verify(partial)

    def test_wrong_query_manifest_or_dataset_binding_is_rejected(self):
        partial = validate_source_revision_feedback(self.review, self.packet)
        feedback = self.feedback(partial)
        feedback['prior_query_ref'] = {**feedback['prior_query_ref'], 'manifest_sha256': '0' * 64}
        with self.assertRaises(ValueError):
            _verify_review_feedback(feedback, self.request, self.request.scope, Path(self.request.dataset))
        changed = deepcopy(self.packet)
        changed['dataset_ref']['manifest_sha256'] = '0' * 64
        self.write('input.json', changed)
        result = self.read('result.json')
        result['input_sha256'] = digest(changed)
        self.write('result.json', result)
        self.seal()
        with self.assertRaises(ValueError):
            self.verify(partial)

    def test_old_manifest_detects_raw_response_tampering(self):
        source = self.read('source-response.json')
        source['coverage_reason'] = 'Changed after seal'
        self.write('source-response.json', source)
        self.assert_rejected()

    def test_resealed_source_with_invalid_literal_quote_is_rejected(self):
        source = self.read('source-response.json')
        source['facts'][0]['citations'][0]['quote'] = 'Fabricated quotation absent from original'
        self.write('source-response.json', source)
        self.seal()
        self.assert_rejected()

    def test_resealed_projection_or_diagnostic_cannot_change_failure_identity(self):
        original_result = self.read('result.json')
        original_projection = self.read('question-input.json')
        for name in ('diagnostic', 'projection'):
            self.write('result.json', original_result)
            self.write('question-input.json', original_projection)
            if name == 'diagnostic':
                result = deepcopy(original_result)
                result['failures'][0]['diagnostic']['code'] = 'direct_requires_same'
                self.write('result.json', result)
            else:
                projection = deepcopy(original_projection)
                projection['question'] += ' Added request'
                self.write('question-input.json', projection)
            self.seal()
            with self.subTest(name=name):
                self.assert_rejected()

    def test_missing_original_and_repair_artifacts_cannot_claim_exhausted_protocol_repair(self):
        names = ('source-response.json', 'question-input.json', 'question-response.json',
                 'question-response-01.json', 'question-repair-input.json', 'question-response-02.json')
        for name in names:
            original = (self.review / name).read_bytes()
            (self.review / name).unlink()
            self.seal()
            with self.subTest(name=name):
                self.assert_rejected()
            (self.review / name).write_bytes(original)
        # In the original case the final question response equals the first.
        # Deleting BOTH repair artifacts must still fail, rather than treating
        # the first response as a complete recorded exhausted repair history.
        for name in ('question-repair-input.json', 'question-response-02.json'):
            (self.review / name).unlink()
        self.seal()
        self.assert_rejected()

    def test_source_all_pass_cannot_trigger_retrieval_for_question_failure_alone(self):
        source = self.read('source-response.json')
        source['revision_requests'] = []
        for body in source['body_checks']:
            body['relevance'] = 'necessary'
        _, eligible = _validate_source_assessment(self.packet, source)
        self.assertTrue(eligible, 'This negative case must contain no source revision need')
        self.write('source-response.json', source)
        self.seal()
        self.assert_rejected()

    def test_network_accounting_close_and_cancelled_failures_cannot_supply_partial_feedback(self):
        original = self.read('result.json')
        cases = (
            ('network', {'stage': 'question_review', 'error_type': 'TimeoutError'}),
            ('accounting', {'stage': 'question_accounting', 'error_type': 'ValueError'}),
            ('close', {'stage': 'question_close_or_accounting', 'error_type': 'ValueError'}),
            ('source_close', {'stage': 'close_or_accounting', 'error_type': 'ValueError'}),
        )
        for name, failure in cases:
            result = deepcopy(original)
            if name == 'network':
                result['failures'] = [failure]
            else:
                result['failures'].append(failure)
            self.write('result.json', result)
            self.seal()
            with self.subTest(name=name):
                self.assert_rejected()
        result = deepcopy(original)
        result['status'] = 'cancelled'
        self.write('result.json', result)
        self.seal()
        self.assert_rejected()

    def test_actual_review_clears_feedback_when_closing_or_accounting_fails(self):
        source = self.read('source-response.json')
        question = self.read('question-response-01.json')
        class CloseFailure(ScriptedRole):
            async def aclose(self):
                self.closed = True
                raise ValueError('Synthetic close failure')
        class AccountingFailure(ScriptedRole):
            def snapshot_usage(self):
                raise ValueError('Synthetic accounting failure')
        for role_type in (CloseFailure, AccountingFailure):
            for position in ('source', 'question'):
                source_role = (role_type if position == 'source' else ScriptedRole)(lambda _: deepcopy(source))
                question_role = (role_type if position == 'question' else ScriptedRole)(lambda _: deepcopy(question))
                output = self.root / (role_type.__name__ + '-' + position)
                result = asyncio.run(review_data_answer(self.packet, output,
                    reviewer_factory=lambda _: source_role,
                    question_reviewer_factory=lambda _: question_role))
                with self.subTest(role=role_type.__name__, position=position):
                    self.assertEqual(result['status'], 'failed')
                    self.assertNotIn('revision_feedback', result)
                    self.assertIs(result['analysis_eligible'], False)
                    self.assertEqual(len(source_role.packets), 1)
                    self.assertEqual(len(question_role.packets), 2)
                    with self.assertRaises(ValueError):
                        validate_source_revision_feedback(output, self.packet)

    def test_partial_declaration_cannot_be_promoted_to_complete_approval(self):
        original = self.read('result.json')
        for name, mutate in (
            ('eligible', lambda x: x.update(analysis_eligible=True)),
            ('reviewed', lambda x: x.update(status='reviewed')),
            ('assessment', lambda x: x.update(assessment=self.read('source-response.json'))),
            ('payload', lambda x: x.update(revision_feedback={'analysis_eligible': True})),
        ):
            result = deepcopy(original)
            mutate(result)
            self.write('result.json', result)
            self.seal()
            with self.subTest(name=name):
                self.assert_rejected()


class IndependentSyntheticSourceRevisionTests(unittest.TestCase):
    def test_unrelated_acme_material_uses_same_negative_feedback_contract(self):
        # Independent synthetic company, question and source blocks; no real
        # financial answers or E6 block IDs participate in this case.
        base = synthetic.IndependentQuestionHandoffTests()
        base.setUp()
        self.addCleanup(base.doCleanups)
        packet = base.packet
        def source_answer(value):
            response = source_fixtures.response(value)
            response['revision_requests'] = ['Trim redundant source material.']
            return response
        def question_answer(value):
            projected = value.get('projection', value)
            response = synthetic.question_response(projected)
            response['checks'].append(deepcopy(response['checks'][0]))
            return response
        source_role = ScriptedRole(source_answer)
        question_role = ScriptedRole(question_answer)
        output = base.root / 'synthetic-source-only'
        result = asyncio.run(review_data_answer(packet, output,
            reviewer_factory=lambda _: source_role,
            question_reviewer_factory=lambda _: question_role))
        partial = validate_source_revision_feedback(output, packet)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['assessment'])
        self.assertEqual(partial, result['revision_feedback'])
        self.assertEqual(partial['question_protocol_failure']['code'],
                         'duplicate_check_requires_distinct_scope')
        request = CompanyQueryInput(question=packet['question'], dataset=packet['dataset_ref']['path'],
                                    scope=packet['scope'], purpose='analysis_evidence')
        feedback = {'prior_query_ref': packet['query_ref'], 'prior_review_ref': result['review_ref'],
                    'source_revision': partial}
        _verify_review_feedback(feedback, request, request.scope, Path(request.dataset))
        with self.assertRaises(ValueError):
            load_reviewed_data(output, expected_scope=packet['scope'],
                expected_review_manifest_sha256=result['review_ref']['manifest_sha256'], allow_fixture=True)


if __name__ == '__main__':
    unittest.main()
