"""Exercise the bounded orchestration with fixtures, never paid model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import attach_synthetic_quotes


class RetrievalCycleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        dataset = self.root/'dataset'
        dataset.mkdir()
        make_scoped_dataset(dataset)
        attach_synthetic_quotes(dataset)
        model = dict(provider='deepseek', model='deepseek-flash',
            budget_ledger=str(self.root/'costs.sqlite'), budget_usd=None, budget_policy='record_only',
            max_requests_total=None, max_tokens=1024, request_timeout=90, max_retries=0, reasoning_effort='low')
        self.config = dict(request=dict(question='Retrieve Acme revenue in 2031.', purpose='analysis_evidence',
            dataset=str(dataset), scope=dict(snapshot_id='synthetic-scoped-v1', company_ids=['acme'],
                source_snapshot_ids=['acme-annual'], source_policy_id='local-frozen-v1',
                knowledge_cutoff='2032-05-01', include_candidates=True)),
            credential_root=str(self.root/'no-credentials'), workspace=str(self.root/'workspace'),
            max_review_packet_bytes=1000000, max_attempts=3,
            **{role:deepcopy(model) for role in ('planner','worker','reviewer')})
        self.output = self.root/'output'
        self.calls, self.reviews = [], []

    def run_fixture(self, statuses, *, query_status='evidence_ready', cancel=False):
        async def query(request, *, output, **kwargs):
            self.calls.append((deepcopy(request), deepcopy(kwargs)))
            output.mkdir()
            (output/'query').mkdir()
            write_new(output/'query/input.json', request)
            cycle._seal(output/'query')
            write_new(output/'result.json', {'status':query_status})
            cycle._seal(output)
            return {'status':query_status}
        def packet(query_run, dataset, **kwargs):
            request = json.loads((query_run/'input.json').read_text())
            self.assertEqual(kwargs['source_delivery'], 'query_evidence_v1')
            return {'query_ref':cycle._reference(query_run), 'dataset_ref':cycle._reference(dataset),
                    'question':request['question'], 'scope':request['scope'], 'packet_id':'fixture'}
        async def review(packet, output, **kwargs):
            self.reviews.append(output)
            output.mkdir()
            write_new(output/'input.json', packet)
            if cancel:
                write_new(output/'result.json', {'status':'cancelled'})
                cycle._seal(output)
                raise asyncio.CancelledError()
            status = statuses[len(self.reviews)-1]
            result = {'status':status, 'analysis_eligible':status=='reviewed',
                      'assessment':{'missing_information':['missing independent detail']} if status=='needs_revision' else {}}
            write_new(output/'result.json', result)
            cycle._seal(output)
            return {**result, 'review_ref':cycle._reference(output)}
        with patch.object(cycle.CompanyDataCoordinator, 'query', side_effect=query), \
             patch.object(cycle, 'prepare_review_packet', side_effect=packet), \
             patch.object(cycle, 'review_data_answer', side_effect=review):
            return asyncio.run(cycle.run_retrieval_cycle(self.config, self.output))

    def test_first_pass_stops_and_records_pinned_artifacts_without_analysis(self):
        before = deepcopy(self.config)
        result = self.run_fixture(['reviewed'])
        self.assertEqual(result['status'], 'reviewed_data_ready')
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(result['analysis_called'])
        self.assertEqual(self.config, before)
        cycle._reference(self.output)
        self.assertEqual(result['final_review_ref'], cycle._reference(self.reviews[0]))

    def test_reviewer_factory_preserves_shared_unknown_reservations(self):
        budget = cycle.RunBudget(self.config['reviewer']['budget_ledger'], None, enforce=False)
        reservation = budget.reserve('0.75')
        budget.settle(reservation, None)
        before = budget.summary()
        with patch.object(cycle, 'SdkRecordReviewer') as reviewer:
            for ordinal in (1,2):
                cycle.reviewer_factory(self.config)(self.root/f'review-{ordinal}')
                arguments = reviewer.call_args.kwargs
                self.assertEqual(arguments['budget'].path, budget.path)
                self.assertFalse(arguments['budget'].enforce)
                self.assertEqual(arguments['budget'].summary(), before)
        self.assertEqual(budget.summary()['held_usd'],'0.75')
        self.assertEqual(budget.summary()['unknown_requests'],1)

    def test_missing_content_triggers_new_query_with_original_question_scope_and_pinned_feedback(self):
        result = self.run_fixture(['needs_revision','reviewed'])
        self.assertEqual(result['status'], 'reviewed_data_ready')
        self.assertEqual(len(self.calls), 2)
        first, second = (entry[0] for entry in self.calls)
        self.assertEqual({k:v for k,v in second.items() if k!='review_feedback'}, first)
        self.assertEqual(second['purpose'], 'analysis_evidence')
        feedback = second['review_feedback']
        self.assertEqual(feedback['prior_review_ref'], cycle._reference(self.reviews[0]))
        self.assertEqual(feedback['prior_query_ref'], cycle._reference(self.output/'attempt-01/data-query/query'))
        self.assertEqual(feedback['assessment']['missing_information'], ['missing independent detail'])
        self.assertEqual(self.calls[0][1]['model_config']['budget_ledger'], self.calls[1][1]['model_config']['budget_ledger'])
        self.assertEqual(json.loads((self.output/'attempt-01/request.json').read_text()), first)
        cycle._reference(self.output/'attempt-01')

    def test_exhaustion_stops_at_explicit_bound(self):
        self.config['max_attempts'] = 2
        result = self.run_fixture(['needs_revision','needs_revision'])
        self.assertEqual(result['status'], 'attempts_exhausted')
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.output/'attempt-03').exists())

    def test_failed_review_retains_attempt_and_retries_once_in_fresh_directory(self):
        result = self.run_fixture(['failed','reviewed'])
        self.assertEqual(result['status'], 'reviewed_data_ready')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([p.name for p in self.reviews], ['review-01','review-02'])
        self.assertEqual(json.loads((self.reviews[0]/'result.json').read_text())['status'], 'failed')
        cycle._reference(self.reviews[0])

    def test_repeated_review_failure_does_not_restart_query_or_erase_failures(self):
        result = self.run_fixture(['failed','failed'])
        self.assertEqual(result['status'], 'blocked_by_review_failure')
        self.assertEqual((len(self.calls),len(self.reviews)), (1,2))
        self.assertEqual([r['status'] for r in result['attempts'][0]['reviews']], ['failed','failed'])

    def test_failed_query_never_calls_review(self):
        result = self.run_fixture([], query_status='failed')
        self.assertEqual(result['status'], 'blocked_by_query')
        self.assertFalse(self.reviews)

    def test_cancellation_seals_available_artifacts_without_retry(self):
        with self.assertRaises(asyncio.CancelledError):
            self.run_fixture([], cancel=True)
        self.assertEqual(len(self.reviews), 1)
        self.assertEqual(json.loads((self.output/'result.json').read_text())['status'], 'cancelled')
        cycle._reference(self.output)

    def test_existing_output_and_invalid_bounds_rejected_before_models(self):
        for value in (0,4,True,None):
            with self.subTest(value=value):
                config = deepcopy(self.config)
                config['max_attempts'] = value
                with self.assertRaises(ValueError):
                    cycle.validate(config,self.output)
        self.output.mkdir()
        sentinel = self.output/'history.txt'
        sentinel.write_text('immutable')
        with self.assertRaises(ValueError):
            cycle.validate(self.config,self.output)
        self.assertEqual(sentinel.read_text(),'immutable')

    def test_analysis_or_external_feedback_configuration_rejected(self):
        for change in ({'purpose':'question_answer'}, {'review_feedback':{'assessment':{}}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                config = deepcopy(self.config)
                config['request'].update(change)
                cycle.validate(config,self.output)
        config = deepcopy(self.config)
        config['analyst'] = deepcopy(config['reviewer'])
        with self.assertRaises(ValueError):
            cycle.validate(config,self.output)


if __name__ == '__main__':
    unittest.main()
