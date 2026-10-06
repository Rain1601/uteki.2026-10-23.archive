"""Benchmark reporting contracts; no provider/network and no model score."""
from copy import deepcopy
import importlib.util
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/run_data_agent_benchmark.py'
spec = importlib.util.spec_from_file_location('data_agent_benchmark', SCRIPT)
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)


class DataAgentBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(bm.CONFIG, self.root/'config')
        config_patch = patch.object(bm, 'CONFIG', self.root/'config'); config_patch.start(); self.addCleanup(config_patch.stop)
        self.questions = bm.load(bm.CONFIG/'questions.json')
        self.rubric = bm.load(bm.CONFIG/'rubric.json')
        self.case = self.questions['cases'][0]

    def review(self, authorized=True):
        questions = deepcopy(self.questions)
        if authorized:
            questions['execution_authorized'] = True
            questions['model_budget'].update(provider='fixture', model='fixture', aggregate_request_limit=100,
                                             aggregate_cost_limit=10, currency='USD', cost_policy='block_at_limit')
        (bm.CONFIG/'questions.json').write_text(json.dumps(questions))
        folder = self.root/'run'; folder.mkdir()
        scope = {'snapshot_id': 'benchmark-fixture', 'source_policy_id': 'local-frozen-v1', 'include_candidates': True, 'company_ids': ['sec-googl'], 'source_snapshot_ids': ['frozen-annual'], 'knowledge_cutoff': self.case['input']['as_of']}
        for name, value in {'request.json': {'question': self.case['input']['question'], 'scope': scope},
                            'config.json': {'plan_origin': 'model', 'provider': 'fixture', 'model': 'fixture'}, 'result.json': {'status': 'evidence_ready'},
                            'calls.json': {'fixture_only': True},
                            'benchmark-input.json': bm.model_input(self.case),
                            'benchmark-sources.json': {'execution_scope': scope, 'dataset_manifest': 'dataset/manifest.json',
                                'companies': [{'symbol': 'GOOGL', 'market': 'NASDAQ', 'company_id': 'sec-googl'}],
                                'configuration_artifacts': {name: 'source-config.json' for name in self.case['input']['source_policy']['configuration_files']}},
                            'model-usage.json': {'limits': self.case['input']['limits'], 'steps': 4, 'elapsed_seconds': 10,
                                'authorized_cost_limit': 1, 'cost_currency': 'USD',
                                'authorization': {'benchmark_id': questions['benchmark_id'], 'questions_sha256': bm.sha(bm.CONFIG/'questions.json'), 'model_budget': questions['model_budget']},
                                'attempts': [{'request_id': 'fixture-'+str(i), 'case_id': self.case['case_id'], 'evidence_path': 'calls.json', 'status': status, 'provider': 'fixture', 'model': 'fixture', 'retry': i > 0,
                                              'input_tokens': 100, 'output_tokens': 20, 'cost': 0.01}
                                             for i, status in enumerate(('failed', 'timed_out', 'succeeded'))]}}.items():
            (folder/name).write_text(json.dumps(value))
        (folder/'source-config.json').write_bytes((bm.ROOT/self.case['input']['source_policy']['configuration_files'][0]).read_bytes())
        dataset = folder/'dataset'; dataset.mkdir()
        (dataset/'raw.html').write_text('Synthetic source bytes for benchmark validation only')
        raw_sha = bm.sha(dataset/'raw.html')
        (dataset/'sources.json').write_text(json.dumps([{'source_snapshot_id': 'frozen-annual', 'company_id': 'sec-googl',
            'available_at': '2026-02-01', 'raw_file': 'raw.html', 'source_sha256': raw_sha, 'raw_file_sha256': raw_sha}]))
        (dataset/'manifest.json').write_text(json.dumps({'snapshot_id': scope['snapshot_id'], 'source_policy_id': scope['source_policy_id'],
            'files': {p.name: bm.sha(p) for p in dataset.iterdir()}}))
        usage = bm.load(folder/'model-usage.json'); usage['cumulative_attempts'] = deepcopy(usage['attempts'])
        (folder/'model-usage.json').write_text(json.dumps(usage))
        (folder/'manifest.json').write_text(json.dumps({'files': {str(p.relative_to(folder)): bm.sha(p) for p in folder.rglob('*') if p.is_file()}}))
        return {'case_id': self.case['case_id'], 'executed': True, 'reviewer': 'unit-test-reviewer',
                'reviewed_at': '2026-09-24', 'run_dir': str(folder), 'manifest_sha256': bm.sha(folder/'manifest.json'),
                'model_call_evidence': ['calls.json'], 'model_calls_human_verified': True, 'assistance': [],
                'checks': {k: {'status': 'pass', 'evidence': ['independent-review-note']} for k in self.rubric['required_checks'][self.case['category']]},
                'metrics': {'requests_attempted': 3, 'requests_succeeded': 1, 'requests_failed': 1,
                            'requests_timed_out': 1, 'retry_requests': 2, 'cost': None, 'unknown_cost_reason': 'provider ledger unavailable'}}

    def repin(self, review, name, value):
        folder = Path(review['run_dir']); (folder/name).write_text(json.dumps(value))
        manifest = bm.load(folder/'manifest.json'); manifest['files'][name] = bm.sha(folder/name)
        (folder/'manifest.json').write_text(json.dumps(manifest))
        review['manifest_sha256'] = bm.sha(folder/'manifest.json')

    def test_frozen_benchmark_scope_and_source_binding_are_required(self):
        review = self.review(); folder = Path(review['run_dir'])
        binding = bm.load(folder/'benchmark-sources.json')
        binding['companies'][0]['symbol'] = 'MSFT'
        self.repin(review, 'benchmark-sources.json', binding)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        binding['companies'][0]['symbol'] = 'GOOGL'
        self.repin(review, 'benchmark-sources.json', binding)
        data = bm.model_input(self.case); data['as_of'] = '2025-01-01'
        self.repin(review, 'benchmark-input.json', data)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        self.repin(review, 'benchmark-input.json', bm.model_input(self.case))
        manifest = bm.load(folder/'manifest.json'); del manifest['files']['benchmark-input.json']
        (folder/'manifest.json').write_text(json.dumps(manifest))
        review['manifest_sha256'] = bm.sha(folder/'manifest.json')
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual((result['status'], result['verification']), ('partial', 'not_ready'))

    def test_pinned_token_time_step_and_cost_limits_control_verdict(self):
        review = self.review(); folder = Path(review['run_dir'])
        original = bm.load(folder/'model-usage.json')
        for field, value in [('steps', 25), ('elapsed_seconds', 901), ('authorized_cost_limit', 0.001)]:
            with self.subTest(field=field):
                usage = deepcopy(original); usage[field] = value
                self.repin(review, 'model-usage.json', usage)
                self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        usage = deepcopy(original); usage['attempts'][0]['input_tokens'] = 100001
        usage['cumulative_attempts'] = deepcopy(usage['attempts'])
        self.repin(review, 'model-usage.json', usage)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        usage = deepcopy(original); usage['attempts'][0]['cost'] = None
        usage['cumulative_attempts'] = deepcopy(usage['attempts'])
        self.repin(review, 'model-usage.json', usage)
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['metrics']['cost'])

    def test_thirteen_questions_keep_evaluation_data_out_of_model_input(self):
        cases = self.questions['cases']
        self.assertEqual(len(cases), 13)
        self.assertEqual(len({c['case_id'] for c in cases}), 13)
        self.assertFalse(self.questions['execution_authorized'])
        for name, expected in self.questions['source_configuration_hashes'].items():
            self.assertEqual(bm.sha(bm.ROOT/name), expected)
        forbidden = {'source_id', 'source_snapshot_id', 'node_id', 'answer', 'expected_answer', 'rubric', 'checks'}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & value.keys())
                for child in value.values(): inspect(child)
            elif isinstance(value, list):
                for child in value: inspect(child)
        for case in cases:
            inspect(bm.model_input(case))
            self.assertIn(case['category'], self.rubric['required_checks'])
        case = deepcopy(cases[0]); case['rubric'] = 'DO NOT LEAK'
        self.assertNotIn('DO NOT LEAK', json.dumps(bm.model_input(case)))

    def test_unauthorized_version_cannot_pass_even_with_all_review_checks(self):
        review = self.review(authorized=False)
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual((result['status'], result['verification']), ('partial', 'not_ready'))
        review['assistance'] = ['provided source location']
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual((result['status'], result['underlying_verdict']), ('assisted', 'partial'))

    def test_partial_numeric_chapter_mixed_and_comparison_never_upgrade(self):
        review = self.review(); self.repin(review, 'result.json', {'status': 'partial'})
        for category in ('numeric', 'chapter', 'mixed', 'comparison'):
            with self.subTest(category=category):
                case = {**self.case, 'category': category}
                review['checks'] = {k: {'status': 'pass', 'evidence': ['review']} for k in self.rubric['required_checks'][category]}
                self.assertEqual(bm.evaluate_review(case, review, self.rubric)['status'], 'partial')

    def test_missing_case_passes_only_explicit_expected_gap_completion(self):
        self.case = next(c for c in self.questions['cases'] if c['case_id'] == 'googl-missing')
        review = self.review()
        result = {'status': 'partial', 'stop_reason': 'host_reference_checks_passed', 'gaps': [{'reason': 'not_yet_occurred'}]}
        self.repin(review, 'result.json', result)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'pass')
        result['gaps'].append({'reason': 'source_unavailable'})
        self.repin(review, 'result.json', result)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'partial')

    def test_provider_model_and_all_failed_attempts_are_rejected(self):
        review = self.review(); folder = Path(review['run_dir'])
        self.repin(review, 'config.json', {'plan_origin': 'model', 'provider': 'other', 'model': 'fixture'})
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        self.repin(review, 'config.json', {'plan_origin': 'model', 'provider': 'fixture', 'model': 'fixture'})
        original = bm.load(folder/'model-usage.json')
        for change in ({'model': 'another-model'}, {'status': 'failed'}):
            usage = deepcopy(original)
            for c in usage['attempts']: c.update(change)
            usage['cumulative_attempts'] = deepcopy(usage['attempts'])
            self.repin(review, 'model-usage.json', usage)
            self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_frozen_authorization_and_cumulative_request_limits(self):
        review = self.review(); folder = Path(review['run_dir']); original = bm.load(folder/'model-usage.json')
        usage = deepcopy(original); usage['authorization']['questions_sha256'] = 'wrong'
        self.repin(review, 'model-usage.json', usage)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'partial')
        usage = deepcopy(original)
        usage['cumulative_attempts'] += [dict(usage['attempts'][0], request_id='prior-'+str(i), case_id='msft-numeric') for i in range(100)]
        self.repin(review, 'model-usage.json', usage)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_imported_case_ledgers_share_budget_and_deduplicate_requests(self):
        requests = {'r1': {'sha256': 'one', 'cost': 0.1}, 'r2': {'sha256': 'two', 'cost': 0.2}}
        rows = [{'status': 'pass', 'underlying_verdict': 'pass', 'metrics': {'budget_requests': deepcopy(requests)}} for _ in range(2)]
        questions = {'model_budget': {'aggregate_request_limit': 2, 'aggregate_cost_limit': 1}}
        self.assertEqual(bm.enforce_cumulative_budget(rows, questions)['unique_requests'], 2)
        self.assertEqual(rows[0]['status'], 'pass')
        rows[1]['metrics']['budget_requests']['r3'] = {'sha256': 'three', 'cost': 0.1}
        self.assertEqual(bm.enforce_cumulative_budget(rows, questions)['status'], 'fail')
        self.assertTrue(all(row['status'] == 'fail' for row in rows))

    def test_record_only_cost_policy_does_not_require_monetary_cap(self):
        review = self.review(); folder = Path(review['run_dir'])
        questions = bm.load(bm.CONFIG/'questions.json')
        questions['model_budget'].update(cost_policy='record_only', aggregate_cost_limit=None)
        (bm.CONFIG/'questions.json').write_text(json.dumps(questions))
        usage = bm.load(folder/'model-usage.json')
        usage['authorization'].update(questions_sha256=bm.sha(bm.CONFIG/'questions.json'), model_budget=questions['model_budget'])
        usage.pop('authorized_cost_limit')
        for c in usage['attempts']: c['cost'] = None
        usage['cumulative_attempts'] = deepcopy(usage['attempts'])
        self.repin(review, 'model-usage.json', usage)
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual(result['status'], 'pass')
        self.assertIsNone(result['metrics']['cost'])
        self.assertEqual(result['metrics']['cost_completeness'], 'unknown')
        self.assertEqual(bm.enforce_cumulative_budget([result], questions)['status'], 'cost_unknown')

    def test_incomplete_scope_and_unresolved_dataset_source_cannot_pass(self):
        review = self.review(); folder = Path(review['run_dir'])
        request = bm.load(folder/'request.json'); binding = bm.load(folder/'benchmark-sources.json')
        del request['scope']['snapshot_id']; binding['execution_scope'] = deepcopy(request['scope'])
        self.repin(review, 'request.json', request); self.repin(review, 'benchmark-sources.json', binding)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['verification'], 'not_ready')
        request['scope']['snapshot_id'] = 'benchmark-fixture'; request['scope']['source_snapshot_ids'] = ['not-in-dataset']
        binding['execution_scope'] = deepcopy(request['scope'])
        self.repin(review, 'request.json', request); self.repin(review, 'benchmark-sources.json', binding)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_comparison_scope_requires_selected_sources_for_every_company(self):
        review = self.review(); folder = Path(review['run_dir'])
        binding = bm.load(folder/'benchmark-sources.json')
        scope = deepcopy(binding['execution_scope']); scope['company_ids'].append('missing-company')
        status, reason = bm.verify_dataset(folder, bm.load(folder/'manifest.json')['files'], binding, scope)
        self.assertEqual(status, 'not_ready')
        self.assertIn('no selected source', reason)

    def test_no_runs_and_self_declared_pass_without_artifacts_do_not_pass(self):
        self.assertEqual(bm.evaluate_review(self.case, None, self.rubric)['status'], 'not_run')
        review = {'executed': True, 'origin': 'model', 'status': 'pass', 'checks': {}}
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'partial')

    def test_review_requires_integrity_call_evidence_and_all_rubric_checks(self):
        review = self.review()
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['verification'], 'human_reviewed_artifacts_verified')
        review['checks']['numeric']['status'] = 'not_reviewed'
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'partial')
        review['checks']['numeric']['status'] = 'fail'
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
        review['checks']['numeric']['status'] = 'pass'
        review['model_calls_human_verified'] = False
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'partial')
        review['model_calls_human_verified'] = True
        (Path(review['run_dir'])/'calls.json').write_text('tampered')
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_assistance_and_request_accounting_are_not_independent_pass(self):
        review = self.review(); review['assistance'] = ['operator supplied source ID']
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual((result['status'], result['underlying_verdict']), ('assisted', 'pass'))
        review['assistance'] = []; review['metrics']['requests_attempted'] = 2
        result = bm.evaluate_review(self.case, review, self.rubric)
        self.assertEqual(result['metrics']['requests_attempted'], 3)
        self.assertEqual(result['status'], 'pass')
        folder = Path(review['run_dir']); usage = bm.load(folder/'model-usage.json')
        usage['attempts'] = [dict(c, request_id='many-'+str(i)) for i,c in enumerate(usage['attempts'] * 9)]
        usage['cumulative_attempts'] = deepcopy(usage['attempts'])
        self.repin(review, 'model-usage.json', usage)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_engineering_partial_mapping_and_missing_t2_are_not_pass(self):
        self.assertEqual(bm.suite_status([{'status': 'pass'}], False), 'partial')
        self.assertEqual(bm.suite_status([{'status': 'pass'}, {'status': 'not_run'}], True), 'partial')
        self.assertEqual(bm.suite_status([{'status': 'not_run'}], False), 'not_run')
        self.assertEqual(bm.suite_status([{'status': 'fail'}], True), 'fail')
        with patch.object(bm, 'check_available', return_value=(False, 'not implemented')):
            result = bm.run_check('tests.unit.test_future_feature', 1)
        self.assertIsNone(result['exit_code']); self.assertEqual(result['status'], 'not_run')
        self.assertIn('command', result)

    def test_failed_command_is_reported_with_exact_exit_and_error(self):
        process = bm.subprocess.CompletedProcess(['unused'], 7, '', 'specific failure')
        with patch.object(bm, 'check_available', return_value=(True, '')), patch.object(bm.subprocess, 'run', return_value=process):
            result = bm.run_check('tests.unit.test_data_agent_benchmark', 1)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['output_tail'], 'specific failure')

    def test_failed_run_cannot_be_overruled_by_human_pass(self):
        review = self.review(); folder = Path(review['run_dir'])
        (folder/'result.json').write_text(json.dumps({'status': 'failed'}))
        manifest = bm.load(folder/'manifest.json'); manifest['files']['result.json'] = bm.sha(folder/'result.json')
        (folder/'manifest.json').write_text(json.dumps(manifest))
        review['manifest_sha256'] = bm.sha(folder/'manifest.json')
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')

    def test_scope_selection_report_and_immutable_output(self):
        output = self.root/'report'
        with patch.object(bm, 'run_check', return_value={'status': 'pass', 'exit_code': 0}) as run:
            self.assertEqual(bm.main(['--output', str(output), '--suite', 'E4', '--case', 'msft-mixed']), 0)
        report = bm.load(output/'report.json')
        self.assertEqual([s['suite_id'] for s in report['offline_suites']], ['E4'])
        self.assertEqual(report['real_model_status_counts'], {'not_run': 1})
        self.assertEqual(report['model_calls_by_runner'], 0)
        self.assertTrue(run.called); self.assertTrue((output/'report.md').is_file())
        with self.assertRaises(FileExistsError):
            bm.main(['--output', str(output), '--skip-offline'])

    def test_different_question_and_escaping_artifact_are_rejected(self):
        review = self.review(); case = deepcopy(self.case); case['input']['question'] = 'Different question'
        self.assertEqual(bm.evaluate_review(case, review, self.rubric)['status'], 'fail')
        folder = Path(review['run_dir']); manifest = folder/'manifest.json'
        data = bm.load(manifest); data['files']['../outside'] = 'not-a-hash'
        manifest.write_text(json.dumps(data)); review['manifest_sha256'] = bm.sha(manifest)
        self.assertEqual(bm.evaluate_review(self.case, review, self.rubric)['status'], 'fail')
