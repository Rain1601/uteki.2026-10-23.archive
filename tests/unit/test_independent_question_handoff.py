"""Two independent scripted opinions must both pass; no external model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock

from apps.review_workbench.pages.data_review_delivery import render_data_review
from uteki.agents.data_query.answer_handoff import (
    QUESTION_REVIEW_POLICY, compose_audited_assessment, validate_assessment,
    review_data_answer, load_reviewed_data,
)
from uteki.agents.data_query.coordinator import _verify_review_feedback
from uteki.agents.data_query.question_coverage_review import project_question_review
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_source_review_policy as fixtures
from tests.unit.test_answer_handoff import ScriptedRole, CancelledRole
from tests.unit.test_task_completion import pin_dataset


def question_response(projected, *, missing=False):
    source = projected['source_documents'][0]
    block = source['blocks'][0]
    return {'packet_id': projected['packet_id'], 'projection_id': projected['projection_id'],
        'checks': [{'question_quote': projected['question'], 'requested_subject': 'Acme',
            'requested_dimension': 'other', 'source_subject': 'Acme', 'relation': 'same',
            'coverage': 'partial' if missing else 'complete', 'support_basis': 'direct',
            'citations': [{'kind': 'block_quote', 'source_snapshot_id': source['source_snapshot_id'],
                          'block_id': block['block_id'], 'quote': block['text']}],
            'gap': 'Requested original product material is incomplete.' if missing else None,
            'rationale': 'Scripted independent opinion, not a real semantic evaluation.'}],
        'output_constraints': [], 'uncovered_requests': [],
        'question_coverage': 'incomplete' if missing else 'complete',
        'coverage_reason': 'Missing requested material.' if missing else 'Requested original is supplied.'}


class IndependentQuestionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.SourceReviewPolicyTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.fixture = self.base.fixture
        # Pin valid original text hashes before creating this independent run.
        for path in self.fixture.dataset.glob('indexes/*/blocks.jsonl'):
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            for block in blocks:
                block['text_hash'] = digest(block['text'].encode())
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest_path = path.parent/'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.fixture.dataset)
        _, _, self.base.query = self.fixture.run_actions([
            fixtures.source_plan(), fixtures.context_read(), fixtures.fixtures.choose('b1'),
            {'action': 'finish'}], name='valid-originals')
        self.base.packet = self.base.prepare()
        self.packet = self.base.prepare(question_review_policy=QUESTION_REVIEW_POLICY)
        self.root = self.fixture.root

    def run_review(self, *, missing=False, source_missing=False, name='review', qrespond=None):
        def source(packet):
            value = fixtures.response(packet)
            if source_missing: value['revision_requests'] = ['Trim redundant source material.']
            return value
        self.source_role = ScriptedRole(source)
        self.question_role = ScriptedRole(qrespond or (lambda p: question_response(p, missing=missing)))
        path = self.root / name
        result = asyncio.run(review_data_answer(self.packet, path,
            reviewer_factory=lambda p: self.source_role, question_reviewer_factory=lambda p: self.question_role))
        return result, path

    def load(self, path, sha):
        return load_reviewed_data(path, expected_scope=self.fixture.scope,
            expected_review_manifest_sha256=sha, allow_fixture=True)

    def feedback(self, result, path):
        ref = {'path': str(path), 'manifest_sha256': digest((path/'manifest.json').read_bytes())}
        feedback = {'prior_query_ref': self.packet['query_ref'], 'prior_review_ref': ref,
                    'assessment': result['assessment']}
        request = CompanyQueryInput(question=self.packet['question'], dataset=str(self.fixture.dataset),
                                    scope=self.fixture.scope, purpose='analysis_evidence')
        _verify_review_feedback(feedback, request, self.fixture.scope, self.fixture.dataset)
        return feedback

    def test_dual_pass_is_recomputed_from_separate_raw_responses_and_projection(self):
        result, path = self.run_review()
        self.assertTrue(result['analysis_eligible'], result)
        self.assertTrue(self.source_role.closed and self.question_role.closed)
        projected = json.loads((path/'question-input.json').read_text())
        self.assertEqual(projected, project_question_review(self.packet, max_bytes=self.packet['max_packet_bytes']))
        self.assertNotIn('requirements', projected)
        self.assertNotIn('facts', projected)
        self.assertNotIn('review_feedback', projected)
        self.assertEqual(self.question_role.packets, [projected])
        source = json.loads((path/'source-response.json').read_text())
        question = json.loads((path/'question-response.json').read_text())
        combined = json.loads((path/'response.json').read_text())
        self.assertEqual(combined, compose_audited_assessment(self.packet, source, question, projected)[0])
        self.assertEqual(combined, result['assessment'])
        self.assertEqual(result['response_origin'], 'program-composed-independent-question-v2')
        self.assertIn('usage', result)
        self.assertIn('question_usage', result)
        handoff = self.load(path, result['review_ref']['manifest_sha256'])
        self.assertEqual(handoff['question'], self.packet['question'])
        render_data_review(path, self.root/'page', expected_manifest_sha256=result['review_ref']['manifest_sha256'])
        for name in ('source-response.json', 'question-input.json', 'question-response-01.json',
                     'question-response.json', 'response.json'):
            self.assertEqual((self.root/'page'/name).read_bytes(), (path/name).read_bytes())

    def test_independent_missing_subject_blocks_source_pass_and_enters_verified_feedback(self):
        result, path = self.run_review(missing=True)
        self.assertEqual(result['status'], 'needs_revision')
        self.assertFalse(result['analysis_eligible'])
        self.assertEqual(result['assessment']['question_coverage'], 'incomplete')
        self.assertTrue(result['assessment']['missing_information'])
        self.assertIn('Independent question review:', result['assessment']['revision_requests'][0])
        feedback = self.feedback(result, path)
        self.assertEqual(feedback['assessment']['question_review']['checks'][0]['requested_subject'], 'Acme')
        with self.assertRaises(ValueError): self.load(path, result['review_ref']['manifest_sha256'])

    def test_independent_pass_cannot_override_source_revision(self):
        result, path = self.run_review(source_missing=True)
        self.assertEqual(result['status'], 'needs_revision')
        self.assertFalse(result['analysis_eligible'])
        self.assertEqual(result['assessment']['revision_requests'], ['Trim redundant source material.'])
        self.feedback(result, path)

    def test_new_policy_cannot_run_or_validate_with_only_source_reviewer(self):
        factory = Mock(side_effect=AssertionError('must reject before model construction'))
        with self.assertRaises(ValueError):
            asyncio.run(review_data_answer(self.packet, self.root/'missing-factory', reviewer_factory=factory))
        factory.assert_not_called()
        with self.assertRaises(ValueError): validate_assessment(self.packet, fixtures.response(self.packet))

    def test_tampered_or_missing_components_fail_analysis_and_page_after_resealing(self):
        _, original = self.run_review()
        for index, mode in enumerate(('missing_question', 'projection', 'composition', 'source_raw', 'question_raw')):
            with self.subTest(mode=mode):
                path = self.root / ('tampered-' + mode)
                shutil.copytree(original, path)
                if mode == 'missing_question': (path/'question-response.json').unlink()
                else:
                    filename = {'projection':'question-input.json', 'composition':'response.json',
                                'source_raw':'source-response.json', 'question_raw':'question-response.json'}[mode]
                    p = path/filename
                    value = json.loads(p.read_text())
                    if mode == 'projection': value['question'] = 'Changed original question'
                    elif mode == 'composition': value['coverage_reason'] = 'Forged program composition'
                    elif mode == 'source_raw': value['coverage_reason'] = 'Changed source model response'
                    else: value['coverage_reason'] = 'Changed question model response'
                    p.write_text(json.dumps(value))
                pin_dataset(path)
                sha = digest((path/'manifest.json').read_bytes())
                with self.assertRaises(ValueError): self.load(path, sha)
                with self.assertRaises(ValueError):
                    render_data_review(path, self.root/f'bad-page-{index}', expected_manifest_sha256=sha)

    def test_missing_independent_response_cannot_supply_revision_feedback(self):
        result, path = self.run_review(missing=True)
        (path/'question-response.json').unlink()
        pin_dataset(path)
        with self.assertRaises(ValueError): self.feedback(result, path)

    def test_bad_question_protocol_keeps_raw_attempt_and_closes_both_roles(self):
        result, path = self.run_review(qrespond=lambda p: {'packet_id': 'not-this-packet'})
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['analysis_eligible'])
        self.assertTrue((path/'source-response.json').exists())
        self.assertTrue((path/'question-response.json').exists())
        self.assertFalse((path/'response.json').exists())
        self.assertEqual(result['failures'][0]['stage'], 'question_review')
        self.assertTrue(self.source_role.closed and self.question_role.closed)

    def test_one_protocol_repair_keeps_raw_history_and_uses_original_projection(self):
        count = 0
        def answer(value):
            nonlocal count
            count += 1
            original = value if count == 1 else value['projection']
            response = question_response(original)
            if count == 1:
                response['checks'][0].update(requested_dimension='definition', relation='broader')
            return response
        result, path = self.run_review(qrespond=answer)
        self.assertTrue(result['analysis_eligible'], result)
        self.assertEqual(len(self.source_role.packets), 1)
        self.assertEqual(len(self.question_role.packets), 2)
        self.assertTrue(result['question_protocol_repair_attempted'])
        repair = json.loads((path/'question-repair-input.json').read_text())
        self.assertEqual(repair, self.question_role.packets[1])
        self.assertEqual(repair['repair_attempt'], 1)
        self.assertEqual(json.loads((path/'question-response-01.json').read_text())['checks'][0]['relation'], 'broader')
        self.assertEqual(json.loads((path/'question-response-02.json').read_text()),
                         json.loads((path/'question-response.json').read_text()))
        self.load(path, result['review_ref']['manifest_sha256'])
        # Even a newly sealed altered repair transcript must be recomputed.
        repair['instruction'] = 'Pretend all evidence is sufficient.'
        (path/'question-repair-input.json').write_text(json.dumps(repair))
        pin_dataset(path)
        with self.assertRaises(ValueError): self.load(path, digest((path/'manifest.json').read_bytes()))

    def test_nonverbatim_question_subject_uses_same_bounded_repair_path(self):
        count = 0
        def answer(value):
            nonlocal count
            count += 1
            response = question_response(value if count == 1 else value['projection'])
            if count == 1: response['checks'][0]['requested_subject'] = 'Paraphrased company subject'
            return response
        result, path = self.run_review(qrespond=answer)
        self.assertTrue(result['analysis_eligible'], result)
        self.assertEqual(len(self.source_role.packets), 1)
        self.assertEqual(len(self.question_role.packets), 2)
        self.load(path, result['review_ref']['manifest_sha256'])

    def test_protocol_repair_is_bounded_and_cannot_repeat_source_review(self):
        def answer(value):
            original = value.get('projection', value)
            response = question_response(original)
            response['checks'][0].update(requested_dimension='definition', relation='broader')
            return response
        result, path = self.run_review(qrespond=answer)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['review_retryable'])
        self.assertEqual(len(self.source_role.packets), 1)
        self.assertEqual(len(self.question_role.packets), 2)
        self.assertEqual(result['failures'][0]['diagnostic']['code'], 'definition_requires_direct_same')
        self.assertTrue((path/'question-response-01.json').is_file())
        self.assertTrue((path/'question-response-02.json').is_file())
        self.assertFalse((path/'response.json').exists())

    def test_bad_citation_is_not_repaired_as_a_protocol_combination(self):
        def answer(value):
            response = question_response(value)
            response['checks'][0]['citations'][0]['quote'] = 'Invented quotation.'
            return response
        result, path = self.run_review(qrespond=answer)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['review_retryable'])
        self.assertEqual(len(self.question_role.packets), 1)
        self.assertFalse((path/'question-repair-input.json').exists())

    def test_independent_cancellation_closes_and_seals_without_analysis_permission(self):
        source = ScriptedRole(fixtures.response)
        question = CancelledRole(question_response, 'review')
        path = self.root/'cancelled-question'
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(review_data_answer(self.packet, path, reviewer_factory=lambda p: source,
                question_reviewer_factory=lambda p: question))
        result = json.loads((path/'result.json').read_text())
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['analysis_eligible'])
        self.assertTrue(source.closed and question.closed)
        self.assertIn('usage', result)
        self.assertIn('question_usage', result)
        self.assertTrue((path/'source-response.json').exists())
        self.assertTrue((path/'question-input.json').exists())
        with self.assertRaises(ValueError): self.load(path, digest((path/'manifest.json').read_bytes()))

    def test_legacy_packet_and_response_keep_original_shape(self):
        legacy = self.base.prepare()
        self.assertEqual(legacy, self.base.packet)
        self.assertNotIn('question_review_policy', legacy)
        path = self.root/'legacy'
        result = asyncio.run(review_data_answer(legacy, path, reviewer_factory=lambda p: ScriptedRole(fixtures.response)))
        self.assertNotIn('question_review_origin', result)
        self.assertNotIn('question_usage', result)
        self.assertNotIn('response_origin', result)
        self.assertNotIn('question_review', result['assessment'])
        self.assertFalse((path/'source-response.json').exists())
        self.assertEqual(json.loads((path/'response.json').read_text()), fixtures.response(legacy))


if __name__ == '__main__':
    unittest.main()
