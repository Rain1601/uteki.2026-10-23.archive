"""The experimental driver must reject invalid roles before any model work."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

from scripts import run_data_handoff as driver
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import attach_synthetic_quotes
from tests.unit import test_answer_handoff_records as record_fixtures
from uteki.infrastructure.research_data.financial_records import digest


class DataHandoffDriverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / 'dataset'
        dataset.mkdir()
        make_scoped_dataset(dataset)
        attach_synthetic_quotes(dataset)
        model = dict(provider='deepseek', model='deepseek-flash',
            budget_ledger=str(self.root / 'costs.sqlite'), budget_usd=None,
            budget_policy='record_only', max_requests_total=None,
            max_tokens=1024, request_timeout=90, max_retries=0, reasoning_effort='low')
        self.config = dict(request=dict(question='Retrieve Acme revenue in 2031.',
            dataset=str(dataset), scope=dict(snapshot_id='synthetic-scoped-v1',
                company_ids=['acme'], source_snapshot_ids=['acme-annual'],
                source_policy_id='local-frozen-v1', knowledge_cutoff='2032-05-01',
                include_candidates=True)),
            credential_root=str(self.root / 'no-credentials'), workspace=str(self.root / 'workspace'),
            max_review_packet_bytes=1000000,
            **{role: deepcopy(model) for role in ('planner', 'worker', 'reviewer', 'analyst')})
        self.output = self.root / 'output'

    def reject_before_run(self, config):
        with patch.object(driver.CompanyDataCoordinator, 'query') as query:
            with self.assertRaises(ValueError):
                asyncio.run(driver.run(config, self.output))
            query.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / 'costs.sqlite').exists())

    def test_check_only_accepts_explicit_scope_without_credentials_or_writes(self):
        request = driver.validate(self.config, self.output)
        self.assertEqual(request.scope.company_ids, ('acme',))
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / 'costs.sqlite').exists())

    def test_native_claude_review_and_analysis_validate_without_calls_or_credentials(self):
        for model in ('claude-sonnet-5-5', 'claude-opus-5-5'):
            with self.subTest(model=model):
                config = deepcopy(self.config)
                for role in ('reviewer', 'analyst'):
                    config[role].update(provider='aihubmix', model=model,
                                        reasoning_effort='high', max_tokens=16000)
                driver.validate(config, self.output)
                self.assertFalse(self.output.exists())
                self.assertFalse((self.root / 'costs.sqlite').exists())

    def test_native_claude_invalid_modes_fail_before_data_calls(self):
        for role in ('reviewer', 'analyst'):
            for changes in ({'max_tokens': 16384}, {'max_retries': 1},
                            {'reasoning_effort': None}, {'reasoning_effort': 'max'}):
                with self.subTest(role=role, changes=changes):
                    config = deepcopy(self.config)
                    config[role].update(provider='aihubmix', model='claude-sonnet-5-5',
                                        reasoning_effort='high')
                    config[role].update(changes)
                    self.reject_before_run(config)

    def test_role_factory_preserves_claude_budget_envelope_and_configuration(self):
        config = deepcopy(self.config)
        config['analyst'].update(provider='aihubmix', model='claude-sonnet-5-5',
                                reasoning_effort='high', allow_unknown_reservations=True)
        config['request_envelope_limits'] = {'reviewer': 200000, 'analyst': 120000}
        with patch.object(driver, 'SdkRecordReviewer') as reviewer:
            driver.role_factory(config, 'analyst', 'Analyze facts', dict)(self.output)
            args, options = reviewer.call_args
            self.assertEqual(args, ('aihubmix', 'claude-sonnet-5-5'))
            self.assertEqual(options['max_request_bytes'], 120000)
            self.assertEqual(options['reasoning_effort'], 'high')
            self.assertEqual(options['budget'].path.resolve(), (self.root/'costs.sqlite').resolve())
            self.assertTrue(options['budget'].allow_unknown_reservations)
            self.assertEqual(options['budget'].summary()['requests'], 0)

    def test_unsupported_source_delivery_fails_before_query(self):
        config = deepcopy(self.config)
        config['source_delivery'] = 'silent_full_report_fallback'
        self.reject_before_run(config)

    def test_missing_role_setting_fails_before_query_and_output(self):
        for role in ('planner', 'worker', 'reviewer', 'analyst'):
            for field in ('max_tokens', 'request_timeout', 'max_retries', 'reasoning_effort'):
                with self.subTest(role=role, field=field):
                    config = deepcopy(self.config)
                    del config[role][field]
                    self.reject_before_run(config)

    def test_unsupported_runtime_setting_or_model_fails_before_query(self):
        for role in ('planner', 'worker', 'reviewer', 'analyst'):
            for field, value in [('max_tokens', True), ('max_tokens', 20000),
                    ('request_timeout', float('nan')), ('request_timeout', True),
                    ('max_retries', 4), ('reasoning_effort', None),
                    ('reasoning_effort', 'unsupported'), ('model', 'unregistered-model')]:
                with self.subTest(role=role, field=field, value=value):
                    config = deepcopy(self.config)
                    config[role][field] = value
                    self.reject_before_run(config)

    def test_analysis_cannot_silently_use_a_different_budget_policy(self):
        config = deepcopy(self.config)
        config['analyst']['max_requests_total'] = 4
        self.reject_before_run(config)

    def test_invalid_explicit_review_envelope_config_fails_before_query(self):
        for limits in ({'reviewer': 2500000}, {'reviewer': True, 'analyst': 400000},
                       {'reviewer': 2500000, 'analyst': 0}, ['reviewer']):
            with self.subTest(limits=limits):
                config = deepcopy(self.config)
                config['request_envelope_limits'] = limits
                self.reject_before_run(config)

    def frozen_query(self):
        fixture = record_fixtures.AnswerHandoffRecordTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        query, scope = fixture.query()
        config = deepcopy(self.config)
        config['request'].update(dataset=str(fixture.dataset), scope=scope.model_dump(mode='json'),
            question=json.loads((query/'result.json').read_text())['request']['question'])
        return config, query, digest((query/'manifest.json').read_bytes())

    def test_resume_checks_hash_and_original_question_before_output_or_models(self):
        config, query, sha = self.frozen_query()
        for changes, pin in [({}, '0'*64), ({'question': 'A different research question'}, sha)]:
            candidate = deepcopy(config)
            candidate['request'].update(changes)
            with patch.object(driver.CompanyDataCoordinator, 'query') as call, \
                    patch.object(driver, 'role_factory') as factory:
                with self.assertRaises(ValueError):
                    asyncio.run(driver.run(candidate, self.output, query_run=query,
                                           query_manifest_sha256=pin))
                call.assert_not_called()
                factory.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_resume_requires_both_query_and_pin(self):
        for query, sha in [(self.root/'query', None), (None, '0'*64)]:
            with self.assertRaises(ValueError):
                asyncio.run(driver.run(self.config, self.output, query_run=query,
                                       query_manifest_sha256=sha))
            self.assertFalse(self.output.exists())

    def test_resume_reuses_verified_query_and_still_blocks_failed_review(self):
        config, query, sha = self.frozen_query()
        config['request_envelope_limits'] = {'reviewer': 2500000, 'analyst': 400000}
        async def review(packet, output, *, reviewer_factory):
            self.assertEqual(packet['query_ref']['manifest_sha256'], sha)
            self.assertEqual(packet['question'], config['request']['question'])
            self.assertEqual(packet['source_delivery'], 'query_evidence_v1')
            return {'status': 'needs_revision', 'analysis_eligible': False,
                    'review_ref': {'path': str(output), 'manifest_sha256': 'f'*64}}
        analysis_calls = []
        async def unexpected_analysis(*args, **kwargs):
            analysis_calls.append(True)
            raise AssertionError('failed review must not reach Analysis')
        with patch.object(driver.CompanyDataCoordinator, 'query') as call, \
                patch.object(driver, 'review_data_answer', side_effect=review), \
                patch.object(driver, 'analyze_reviewed_data', unexpected_analysis):
            result = asyncio.run(driver.run(config, self.output, query_run=query,
                                            query_manifest_sha256=sha))
            call.assert_not_called()
            self.assertEqual(analysis_calls, [])
        self.assertEqual(result['status'], 'blocked_by_content_review')
        self.assertEqual(result['stages']['query']['execution'], 'reused_frozen')
        self.assertEqual(result['stages']['query']['manifest_sha256'], sha)
        self.assertEqual(digest((query/'manifest.json').read_bytes()), sha)
