"""Offline Data-to-Analysis contract checks; synthetic evidence, no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.data_query.answer_handoff import (
    load_reviewed_data, prepare_review_packet, review_data_answer,
)
from uteki.agents.analysis.data_consumer import analyze_reviewed_data
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, read
from tests.unit.test_autonomous_source_answer import ACTUAL, FUTURE, answer_action, answer_plan
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import pin_dataset


class ScriptedRole:
    plan_origin = 'scripted_fixture'

    def __init__(self, respond):
        self.respond = respond
        self.packets = []
        self.closed = False

    async def review(self, packet):
        self.packets.append(deepcopy(packet))
        return self.respond(packet)

    async def aclose(self):
        self.closed = True

    def snapshot_usage(self):
        return {'plan_origin': self.plan_origin, 'model_requests': 0}


class CancelledRole(ScriptedRole):
    def __init__(self, respond, phase):
        super().__init__(respond)
        self.phase = phase

    async def review(self, packet):
        if self.phase == 'review':
            raise asyncio.CancelledError()
        return await super().review(packet)

    async def aclose(self):
        self.closed = True
        if self.phase == 'close':
            raise asyncio.CancelledError()


def assessment(packet, *, omission=False, fake_quote=False, text_insufficient=False):
    def quote(citation):
        return {key: citation[key] for key in ('source_snapshot_id', 'block_id', 'quote')}

    facts = [{'fact_id': fact['fact_id'], 'verdict': 'supported',
              'rationale': 'The supplied original supports this individual statement.',
              'citations': [quote(fact['citations'][0])]}
             for fact in packet['facts']]
    if fake_quote:
        facts[0]['citations'][0]['quote'] = 'Guaranteed cash returns.'
    return {'packet_id': packet['packet_id'], 'facts': facts,
            'source_checks': [{'source_snapshot_id': source['source_snapshot_id'],
                               'verdict': 'requires_more_source_content' if text_insufficient else 'text_sufficient',
                               'rationale': 'Unread source content is needed.' if text_insufficient
                                   else 'The supplied text includes the actual and future disclosures.',
                               'citations': [{'source_snapshot_id': source['source_snapshot_id'],
                                              'block_id': 'b1', 'quote': ACTUAL}]}
                              for source in packet['source_documents']],
            'requirements': [{'requirement_id': row['requirement_id'],
                              'verdict': 'needs_revision' if omission else 'complete',
                              'rationale': 'The future part of the question is missing.' if omission
                                  else 'Actual and future disclosures are separately represented.',
                              'citations': [{'source_snapshot_id': 'acme-annual', 'block_id': 'b2',
                                             'quote': FUTURE}]}
                             for row in packet['requirements']],
            'question_coverage': 'incomplete' if omission else 'complete',
            'coverage_reason': 'Future plans are omitted.' if omission else 'The question is covered.',
            'missing_information': ['Include disclosed future expectations.'] if omission else [],
            'limitations': ['Synthetic scripted review validates wiring, not model research quality.']}


def analysis_answer(handoff):
    return {'handoff_id': handoff['handoff_id'], 'interpretations': [{
        'statement': 'The reviewed disclosures distinguish actual investments from expectations.',
        'basis': 'source_summary', 'fact_ids': [fact['fact_id'] for fact in handoff['facts']],
        'limitations': ['These disclosures do not establish investment returns.']}],
        'missing_data_requests': ['Evidence of resulting incremental cash generation.'],
        'limitations': ['Limited synthetic task; not a company report or investment judgment.']}


class AnswerHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.review_hashes = {}
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        index = self.dataset / 'indexes/acme-annual'
        path = index / 'blocks.jsonl'
        blocks = [json.loads(line) for line in path.read_text().splitlines()]
        blocks[1]['text'], blocks[2]['text'] = ACTUAL, FUTURE
        path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
        manifest_path = index / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.dataset)
        self.scope = ExecutionScope(snapshot_id='synthetic-scoped-v1', company_ids=('acme',),
            source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Describe actual investment uses in 2031 and expectations for 2032.',
                        'scope': self.scope.model_dump(mode='json')}

    def query(self, *, partial=False, omit_future=False, fake_quote=False, name='query'):
        def answer(packet):
            action = answer_action(packet['observation']['evidence_ids'][0],
                                   partial=partial, include_future=not omit_future)
            if fake_quote:
                action['answer']['claims'][0]['citations'][0]['quote'] = 'Guaranteed cash returns.'
            return action

        actions = [answer_plan(), read(), answer, {'action': 'finish'}]
        with QueryDataPort(self.dataset) as port:
            agent = AutonomousDataAgent(port, ScriptedPlanner(actions),
                limits={'max_steps': len(actions), 'max_packet_bytes': 64000})
            output = self.root / name
            result = asyncio.run(agent.run(self.request, output=output))
        return result, output

    def prepare(self, query_run, *, expected_scope=None, max_packet_bytes=1_000_000):
        return prepare_review_packet(query_run, self.dataset,
            expected_scope=expected_scope or self.scope, max_packet_bytes=max_packet_bytes)

    def review(self, packet, *, omission=False, fake_quote=False, text_insufficient=False, name='review'):
        reviewer = ScriptedRole(lambda value: assessment(value, omission=omission,
            fake_quote=fake_quote, text_insufficient=text_insufficient))
        output = self.root / name
        result = asyncio.run(review_data_answer(packet, output, reviewer_factory=lambda path: reviewer))
        self.assertTrue(reviewer.closed)
        self.assertEqual(len(reviewer.packets), 1)
        self.review_hashes[output] = result['review_ref']['manifest_sha256']
        return result, output, reviewer

    def assert_analysis_blocked(self, review_run, *, expected_scope=None, allow_fixture=True, name='blocked'):
        calls = []

        def factory(path):
            calls.append(path)
            return ScriptedRole(analysis_answer)

        output = self.root / name
        with self.assertRaises(ValueError):
            asyncio.run(analyze_reviewed_data(review_run, output,
                expected_scope=expected_scope or self.scope, analyst_factory=factory,
                expected_review_manifest_sha256=self.review_hashes.get(
                    review_run, digest((review_run / 'manifest.json').read_bytes())),
                allow_fixture=allow_fixture))
        self.assertEqual(calls, [], 'Invalid handoff must be rejected before constructing an analyst.')
        self.assertFalse(output.exists(), 'Invalid handoff must not create an Analysis run.')

    def test_source_answer_review_and_analysis_are_connected_in_explicit_fixture_mode(self):
        query_result, query_run = self.query()
        self.assertEqual(query_result['status'], 'evidence_ready')
        self.assertEqual(query_result['semantic_completeness'], 'not_evaluated')
        packet = self.prepare(query_run)
        self.assertEqual(packet['question'], self.request['question'])
        self.assertEqual(packet['scope'], self.scope.model_dump(mode='json'))
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual(len(packet['facts']), 2)
        self.assertEqual(packet['source_documents'][0]['coverage'], 'full_indexed_text')
        self.assertEqual(len(packet['source_documents'][0]['blocks']), 10)
        reviewed, review_run, reviewer = self.review(packet)
        self.assertEqual(reviewed['status'], 'reviewed', reviewed)
        self.assertTrue(reviewed['analysis_eligible'])
        self.assertEqual(reviewed['adoption'], 'unchanged_candidate')
        review_hash = reviewed['review_ref']['manifest_sha256']
        handoff = load_reviewed_data(review_run, expected_scope=self.scope,
            expected_review_manifest_sha256=review_hash, allow_fixture=True)
        self.assertEqual(handoff['execution_origin'], 'scripted_fixture')
        analyst = ScriptedRole(analysis_answer)
        analyzed = asyncio.run(analyze_reviewed_data(review_run, self.root / 'analysis',
            expected_scope=self.scope, expected_review_manifest_sha256=review_hash,
            analyst_factory=lambda path: analyst, allow_fixture=True))
        self.assertEqual(analyzed['status'], 'candidate_pending_content_review', analyzed)
        self.assertEqual(analyst.packets, [{key: value for key, value in handoff.items() if key != 'input_refs'}])
        self.assertNotIn('input_refs', analyst.packets[0])
        self.assertTrue(analyst.closed)
        self.assertEqual(analyzed['semantic_review'], 'pending')
        self.assertEqual(analyzed['publication'], 'not_published')
        self.assertTrue(analyzed['answer']['interpretations'][0]['source_citations'])
        report = (self.root / 'analysis' / 'report.md').read_text()
        self.assertIn(analyzed['answer']['interpretations'][0]['statement'], report)
        self.assertIn(ACTUAL, report)
        self.assertIn('acme-annual', report)
        self.assertEqual(analyzed['report_path'], 'report.md')
        manifest = json.loads((self.root / 'analysis' / 'manifest.json').read_text())
        self.assertEqual(manifest['files']['report.md'], digest(report.encode()))
        self.assertEqual(reviewer.snapshot_usage()['model_requests'] + analyst.snapshot_usage()['model_requests'], 0)

    def test_fixture_review_cannot_be_used_as_formal_analysis_by_default(self):
        _, query_run = self.query()
        _, review_run, _ = self.review(self.prepare(query_run))
        with self.assertRaisesRegex(ValueError, 'fixture'):
            load_reviewed_data(review_run, expected_scope=self.scope,
                expected_review_manifest_sha256=self.review_hashes[review_run])
        self.assert_analysis_blocked(review_run, allow_fixture=False)

    def test_partial_answer_cannot_be_promoted_by_a_reviewer_complete_claim(self):
        result, query_run = self.query(partial=True)
        self.assertEqual(result['status'], 'partial')
        packet = self.prepare(query_run)
        self.assertIn('partial_answer:business', packet['program_gaps'])
        reviewed, review_run, _ = self.review(packet)
        self.assertEqual(reviewed['status'], 'needs_revision')
        self.assertFalse(reviewed['analysis_eligible'])
        self.assert_analysis_blocked(review_run)

    def test_unreviewed_query_cannot_call_analysis(self):
        _, query_run = self.query()
        self.assert_analysis_blocked(query_run)

    def test_company_and_cutoff_changes_are_rejected_before_analysis(self):
        _, query_run = self.query()
        _, review_run, _ = self.review(self.prepare(query_run))
        for index, change in enumerate(({'company_ids': ['other'], 'source_snapshot_ids': ['other-annual']},
                                        {'knowledge_cutoff': '2032-04-30'})):
            changed = {**self.scope.model_dump(mode='json'), **change}
            with self.subTest(scope=change):
                with self.assertRaisesRegex(ValueError, 'scope'):
                    self.prepare(query_run, expected_scope=changed)
                self.assert_analysis_blocked(review_run, expected_scope=changed, name=f'blocked-{index}')

    def test_original_source_change_after_review_is_rejected_before_analysis(self):
        _, query_run = self.query()
        _, review_run, _ = self.review(self.prepare(query_run))
        original = self.dataset / 'indexes/acme-annual/blocks.jsonl'
        original.write_text(original.read_text().replace(ACTUAL, 'The source was changed.'))
        self.assert_analysis_blocked(review_run)

    def test_resealed_upstream_query_does_not_match_the_reviewed_input(self):
        _, query_run = self.query()
        _, review_run, _ = self.review(self.prepare(query_run))
        result_path = query_run / 'result.json'
        result = json.loads(result_path.read_text())
        result['request']['question'] = 'A different research question after review.'
        result_path.write_text(json.dumps(result))
        # A new valid manifest is still a different input from the review's pin.
        pin_dataset(query_run)
        self.assert_analysis_blocked(review_run)

    def test_resealed_review_is_rejected_against_independently_held_manifest_hash(self):
        _, query_run = self.query()
        _, review_run, _ = self.review(self.prepare(query_run))
        original_hash = self.review_hashes[review_run]
        result_path = review_run / 'result.json'
        result = json.loads(result_path.read_text())
        result['usage'] = {'model_requests': 999, 'replacement': True}
        result_path.write_text(json.dumps(result))
        pin_dataset(review_run)
        self.assertNotEqual(digest((review_run / 'manifest.json').read_bytes()), original_hash)
        self.assert_analysis_blocked(review_run)

    def test_unread_content_needed_by_reviewer_blocks_analysis_even_when_facts_pass(self):
        _, query_run = self.query()
        reviewed, review_run, _ = self.review(self.prepare(query_run), text_insufficient=True)
        self.assertEqual(reviewed['status'], 'needs_revision')
        self.assertFalse(reviewed['analysis_eligible'])
        self.assert_analysis_blocked(review_run)

    def test_analysis_output_cannot_be_created_inside_any_frozen_input(self):
        _, query_run = self.query()
        reviewed, review_run, _ = self.review(self.prepare(query_run))
        calls = []

        def factory(path):
            calls.append(path)
            return ScriptedRole(analysis_answer)

        for parent in (self.dataset, query_run, review_run):
            output = parent / 'analysis-must-not-exist'
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                asyncio.run(analyze_reviewed_data(review_run, output, expected_scope=self.scope,
                    expected_review_manifest_sha256=reviewed['review_ref']['manifest_sha256'],
                    analyst_factory=factory, allow_fixture=True))
            self.assertFalse(output.exists())
        self.assertEqual(calls, [])

    def assert_cancelled_artifacts(self, output):
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['status'], 'cancelled')
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['files']['result.json'], digest((output / 'result.json').read_bytes()))
        self.assertEqual(result['usage']['model_requests'], 0)
        return result

    def test_review_cancellation_during_call_or_close_is_sealed_then_reraised(self):
        _, query_run = self.query()
        packet = self.prepare(query_run)
        for phase in ('review', 'close'):
            role = CancelledRole(assessment, phase)
            output = self.root / f'cancelled-review-{phase}'
            with self.subTest(phase=phase), self.assertRaises(asyncio.CancelledError):
                asyncio.run(review_data_answer(packet, output, reviewer_factory=lambda path: role))
            self.assertTrue(role.closed)
            result = self.assert_cancelled_artifacts(output)
            self.assertFalse(result['analysis_eligible'])

    def test_analysis_cancellation_during_call_or_close_is_sealed_then_reraised(self):
        _, query_run = self.query()
        reviewed, review_run, _ = self.review(self.prepare(query_run))
        for phase in ('review', 'close'):
            role = CancelledRole(analysis_answer, phase)
            output = self.root / f'cancelled-analysis-{phase}'
            with self.subTest(phase=phase), self.assertRaises(asyncio.CancelledError):
                asyncio.run(analyze_reviewed_data(review_run, output, expected_scope=self.scope,
                    expected_review_manifest_sha256=reviewed['review_ref']['manifest_sha256'],
                    analyst_factory=lambda path: role, allow_fixture=True))
            self.assertTrue(role.closed)
            self.assert_cancelled_artifacts(output)

    def test_reviewer_can_block_a_program_complete_answer_that_omits_part_of_question(self):
        result, query_run = self.query(omit_future=True)
        self.assertEqual(result['status'], 'evidence_ready')
        packet = self.prepare(query_run)
        self.assertEqual(len(packet['facts']), 1)
        self.assertEqual(packet['program_gaps'], [])
        self.assertTrue(any(block['text'] == FUTURE
                            for block in packet['source_documents'][0]['blocks']))
        reviewed, review_run, _ = self.review(packet, omission=True)
        self.assertEqual(reviewed['status'], 'needs_revision')
        self.assertFalse(reviewed['analysis_eligible'])
        self.assertEqual(reviewed['assessment']['question_coverage'], 'incomplete')
        self.assert_analysis_blocked(review_run)

    def test_same_context_fake_author_quote_never_becomes_a_reviewed_fact(self):
        result, query_run = self.query(fake_quote=True)
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        packet = self.prepare(query_run)
        self.assertEqual(packet['facts'], [])
        self.assertIn('missing_active_answer:business', packet['program_gaps'])
        reviewed, review_run, _ = self.review(packet)
        self.assertFalse(reviewed['analysis_eligible'])
        self.assert_analysis_blocked(review_run)

    def test_reviewer_fake_quote_is_rejected_even_with_a_real_source_and_block(self):
        _, query_run = self.query()
        reviewed, review_run, _ = self.review(self.prepare(query_run), fake_quote=True)
        self.assertEqual(reviewed['status'], 'failed')
        self.assertFalse(reviewed['analysis_eligible'])
        self.assertTrue(reviewed['failures'])
        self.assert_analysis_blocked(review_run)

    def test_full_source_packet_limit_fails_without_silently_truncating(self):
        _, query_run = self.query()
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.prepare(query_run, max_packet_bytes=1024)
