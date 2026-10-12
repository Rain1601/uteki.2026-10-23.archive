"""Public coordinator to strict Analysis gate; deterministic fixtures, zero API."""
import asyncio
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.unit import test_query_figures as port_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, _verify_review_feedback
from uteki.agents.data_query.answer_handoff import (
    prepare_review_packet, review_data_answer, load_reviewed_data, QUESTION_REVIEW_POLICY,
)
from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.data_query.question_review_generation import PROJECTION_FIGURES, question_generation_schema
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest


class FixtureReviewer:
    plan_origin = 'scripted_fixture'

    def __init__(self, response):
        self.response = response

    async def review(self, packet):
        return self.response(packet)

    async def aclose(self):
        pass

    def snapshot_usage(self):
        return {'requests': 0, 'business_validation': 'not_evaluated'}


class FigureQueryPipelineTests(unittest.TestCase):
    def setUp(self):
        fixture = port_fixtures.QueryFiguresTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.fixture.fixture.root
        self.port = fixture.first_only()
        self.source = fixture.sources[0]['source_snapshot_id']
        self.figure = self.port.list_figures()['figures'][0]
        self.request = dict(question='Name the chart series.', purpose='analysis_evidence',
            dataset=str(fixture.dataset), scope=self.port.scope.model_dump(mode='json'),
            figure_bundle_ref=fixture.ref,
            limits={'max_steps': 4, 'max_packet_bytes': 128000, 'observation_bytes': 32000, 'page_items': 30})

    def run_query(self):
        def select(packet):
            return dict(action='select_figures', requirement_ids=['chart'],
                figure_delivery={'evidence_ids': packet['observation']['evidence_ids']},
                reason='Explicitly selected chart only.')
        planner = ScriptedPlanner([
            dict(action='plan', reason='Read the reported chart.', requirements=[
                dict(requirement_id='chart', kind='source_evidence', source_id=self.source, description='Chart labels.')]),
            dict(action='read_figure', requirement_ids=['chart'], figure_read={
                'source_snapshot_id': self.source, 'figure_id': self.figure['figure_id']}),
            select, dict(action='finish')])
        coordinator = CompanyDataCoordinator(self.root / 'coordinator-workspace')
        output = self.root / 'coordinator-query'
        result = asyncio.run(coordinator.query(self.request, output=output, planner=planner))
        self.assertEqual(result['status'], 'evidence_ready', result)
        packet = prepare_review_packet(output / 'query', self.fixture.dataset,
            expected_scope=self.request['scope'], max_packet_bytes=128000,
            source_delivery='query_evidence_v1', question_review_policy=QUESTION_REVIEW_POLICY)
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual(packet['source_documents'][0]['blocks'], [])
        return packet

    @staticmethod
    def citation(packet):
        figure = packet['source_figures'][0]
        legend = next(text for text in figure['transcription']['texts'] if text['role'] == 'legend')
        return dict(kind='figure_text', source_snapshot_id=figure['source_snapshot_id'],
            figure_id=figure['figure_id'], text_id=legend['id'], quote=legend['text'])

    def source_response(self, packet, *, complete=True):
        citation = self.citation(packet)
        return dict(packet_id=packet['packet_id'],
            facts=[dict(fact_id=fact['fact_id'], verdict='supported', relevance='necessary',
                rationale='Synthetic exact label.', citations=[citation]) for fact in packet['facts']],
            requirements=[dict(requirement_id=req['requirement_id'],
                verdict='complete' if complete else 'needs_revision', rationale='Synthetic fixture judgment.',
                citations=[citation]) for req in packet['requirements']],
            source_checks=[dict(source_snapshot_id=doc['source_snapshot_id'], verdict='text_sufficient',
                rationale='Selected transcription available.', citations=[citation]) for doc in packet['source_documents']],
            figure_checks=[dict(source_snapshot_id=figure['source_snapshot_id'], figure_id=figure['figure_id'],
                authenticity='source_bound', support='supported', relevance='necessary',
                rationale='Synthetic pinned label.', citations=[citation]) for figure in packet['source_figures']],
            question_coverage='complete', coverage_reason='Synthetic series supplied.',
            missing_information=[], limitations=['Independent visual acceptance remains pending.'], body_checks=[])

    def question_response(self, projected, packet):
        return dict(packet_id=projected['packet_id'], projection_id=projected['projection_id'],
            checks=[dict(question_quote='Name the chart series', requested_subject='chart series',
                requested_dimension='other', source_subject='chart series', relation='same', coverage='complete',
                support_basis='direct', citations=[self.citation(packet)], gap=None, rationale='Synthetic exact legend.')],
            output_constraints=[], uncovered_requests=[], question_coverage='complete', coverage_reason='Fixture label.')

    def review(self, packet, *, complete=True):
        output = self.root / 'review'
        result = asyncio.run(review_data_answer(packet, output,
            reviewer_factory=lambda path: FixtureReviewer(lambda value: self.source_response(value, complete=complete)),
            question_reviewer_factory=lambda path: FixtureReviewer(lambda value: self.question_response(value, packet))))
        return output, result

    def test_public_read_select_dual_review_and_strict_load_preserve_image_identity(self):
        packet = self.run_query()
        output, result = self.review(packet)
        self.assertEqual(result['status'], 'reviewed', result)
        self.assertTrue(result['analysis_eligible'])
        sha = digest((output / 'manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'scripted fixture'):
            load_reviewed_data(output, expected_scope=self.request['scope'], expected_review_manifest_sha256=sha)
        handoff = load_reviewed_data(output, expected_scope=self.request['scope'],
            expected_review_manifest_sha256=sha, allow_fixture=True)
        self.assertEqual(handoff['execution_origin'], 'scripted_fixture')
        self.assertEqual(handoff['source_figures'][0]['figure_id'], self.figure['figure_id'])
        self.assertEqual(handoff['source_figures'][0]['independent_acceptance'], 'pending')
        self.assertEqual(handoff['source_documents'][0]['blocks'], [])
        self.assertEqual(handoff['figure_bundle_ref'], self.fixture.ref)

    def test_feedback_cannot_replace_the_original_supplement(self):
        packet = self.run_query()
        output, result = self.review(packet, complete=False)
        self.assertEqual(result['status'], 'needs_revision', result)
        feedback = dict(prior_query_ref=packet['query_ref'], prior_review_ref=result['review_ref'],
                        assessment=result['assessment'])
        request = CompanyQueryInput.model_validate(self.request)
        _verify_review_feedback(feedback, request, self.port.scope, self.fixture.dataset)
        changed = deepcopy(self.request)
        changed['figure_bundle_ref']['path'] = str(self.root / 'another-bundle')
        with self.assertRaisesRegex(ValueError, 'cannot change the frozen figure'):
            _verify_review_feedback(feedback, CompanyQueryInput.model_validate(changed), self.port.scope, self.fixture.dataset)

    def test_direct_agent_cannot_write_inside_the_frozen_supplement(self):
        from uteki.agents.data_query.autonomous import AutonomousDataAgent
        output = Path(self.fixture.ref['path']) / 'new-agent-run'
        agent = AutonomousDataAgent(self.port, ScriptedPlanner([]), purpose='analysis_evidence')
        with self.assertRaisesRegex(ValueError, 'frozen figure supplement'):
            asyncio.run(agent.run(dict(question=self.request['question'], scope=self.request['scope'],
                figure_bundle_ref=self.fixture.ref), output=output))
        self.assertFalse(output.exists())

    def test_retrieval_requires_both_reviewers_before_materials_or_models(self):
        config = dict(request=self.request, planner={}, worker={}, reviewer={}, credential_root=str(self.root),
            workspace=str(self.root / 'workspace'), max_review_packet_bytes=128000, max_attempts=1)
        with self.assertRaisesRegex(ValueError, 'independent source and question'):
            cycle.validate(config, self.root / 'unreviewed-retrieval')
        self.assertFalse((self.root / 'unreviewed-retrieval').exists())

    def test_orchestrator_uses_the_new_sdk_schema_and_projection_only_for_v5(self):
        packet = self.run_query()
        config = {'question_reviewer': {}, 'question_review_policy': QUESTION_REVIEW_POLICY}
        with patch.object(cycle, '_review_role_factory') as factory:
            cycle.question_reviewer_factory(config, packet)
        args, kwargs = factory.call_args
        self.assertIn(PROJECTION_FIGURES, args[2])
        self.assertIs(args[3], question_generation_schema({'schema_version': 'question-coverage-input-v3'}))
        self.assertEqual(kwargs['output_projection'], PROJECTION_FIGURES)


if __name__ == '__main__':
    unittest.main()
