"""Offline adversarial checks of accounting and comparison provenance; no model calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import compare_configs as comparison
import render_comparison as rendering
from summarize_runs import summarize, money, request_timing


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(path):
    write(path / 'manifest.json', {'files': {str(p.relative_to(path)): digest(p)
        for p in sorted(path.rglob('*')) if p.is_file() and p != path / 'manifest.json'}})
    return digest(path / 'manifest.json')


class Reporting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / 'dataset'
        write(self.dataset / 'source.json', {'source': 'independent synthetic example'})
        self.gold = self.root / 'evaluation-only/frozen/E1-04-v1.json'
        write(self.gold, {'case': {'query_zh': 'Synthetic cutoff question'},
             'dataset_manifest_sha256': freeze(self.dataset)})
        self.names = ['config-a', 'config-b']
        for name in self.names:
            self.make_run(name)
        self.addCleanup(patch.stopall)
        patch.object(comparison, 'ROOT', self.root).start()
        patch.object(rendering, 'ROOT', self.root).start()

    def receipt(self, name, suffix, amount='0.2', status='succeeded', end=True):
        run = self.root / 'runs' / name
        write(run / 'calls' / (suffix + ('-end.json' if end else '-start.json')),
            {'call_id': name + '-' + suffix, 'stage': 'query', 'provider': 'provider-' + name,
             'requested_model': name, 'cost_basis': 'fixture-estimate', 'status': status,
             'estimated_usd': amount, 'reserved_usd': '0.7',
             'raw_usage': {'prompt_tokens': 10, 'prompt_tokens_details': {'cached_tokens': 7},
                           'completion_tokens': 4, 'completion_tokens_details': {'reasoning_tokens': 2}}})

    def make_run(self, name):
        run = self.root / 'runs' / name
        request = {'question': 'Synthetic cutoff question', 'dataset': str(self.dataset),
                   'scope': {'knowledge_cutoff': '2024-08-01'}}
        config = {'request': request, 'reviewer': {'model': 'fixed-reviewer'}}
        for role in ['planner', 'worker']:
            config[role] = {'provider': 'provider-' + name, 'model': name,
                            'reasoning_effort': None if name == 'config-b' else 'high', 'max_tokens': 100}
        for file, value in [('config', config), ('original-request', request),
                            ('implementation', {'code.py': 'fixed-hash'}), ('dependencies', {'python': '3'})]:
            write(run / (file + '.json'), value)
        query = run / 'attempt-01/query'
        write(query / 'config.json', {'protocol': 'same', 'prompt_sha256': 'same'})
        write(query / 'result.json', {'plans': [{'skill_hashes': {'query': 'same'}}]})
        queryhash = freeze(query)
        write(run / 'result.json', {'status': 'reviewed_data_ready', 'attempts': [
            {'execution': 'new', 'query_ref': {'path': str(query), 'manifest_sha256': queryhash}}]})
        self.receipt(name, 'success')
        self.receipt(name, 'failed', '0.1', 'failed')
        self.bind_review(name)

    def bind_review(self, name):
        run = self.root / 'runs' / name
        review = self.root / 'evaluation-only/reviews' / name
        write(review / 'review.json', {'case_id': 'E1-04', 'question': 'Synthetic cutoff question'})
        write(review / 'score.json', {'case_id': 'E1-04', 'status': 'pass',
            'workflow_status': 'reviewed_data_ready', 'required_coverage': {'numerator': 3, 'denominator': 3},
            'characters': {'delivered_character_occurrences': 100, 'categories': {
                k: {'numerator': v} for k, v in [('table_structure', 30), ('duplicate', 0), ('irrelevant', 0)]}}})
        write(review / 'original-check.json', {'gold_freeze_sha256': digest(self.gold),
                                             'run_manifest_sha256': freeze(run)})
        (review / 'README.zh-CN.md').write_text('Synthetic independent review')

    def test_failure_cost_and_raw_usage_preserved(self):
        value = summarize(self.root / 'runs')
        self.assertEqual(value['known_estimated_usd'], '0.6')
        group = value['runs'][0]['by_provider_model_stage_cost_basis'][0]
        self.assertEqual(group['usage_by_provider_field']['prompt_tokens'], 20)
        self.assertEqual(group['usage_by_provider_field']['prompt_tokens_details.cached_tokens'], 14)
        self.assertNotIn('total_tokens', group['usage_by_provider_field'])

    def test_request_timing_counts_failures_and_distinguishes_overlap_from_window(self):
        for suffix, start, end in [('success', '00:00:00', '00:00:10'), ('failed', '00:00:05', '00:00:15')]:
            path=self.root/'runs/config-a/calls'/f'{suffix}-end.json'
            call=json.loads(path.read_text())
            call.update(started_at='2030-01-01T'+start+'Z', ended_at='2030-01-01T'+end+'Z', elapsed_seconds=10)
            write(path,call)
        timing=summarize(self.root/'runs')['runs'][0]['request_timing']
        self.assertEqual(timing['cumulative_request_seconds'],20)
        self.assertEqual(timing['request_window_seconds'],15)
        self.assertEqual(timing['measured_elapsed_calls'],2)
        self.assertEqual(timing['last_request_ended_at'],'2030-01-01T00:00:15+00:00')
        self.bind_review('config-a')
        output=self.root/'timed-page'
        rendering.render(comparison.compare(self.names),output)
        html=(output/'index.html').read_text()
        self.assertIn('20.00 秒',html)
        self.assertIn('请求跨度 15.00 秒',html)
        self.assertIn('未完整记录',html)
        self.assertIn('不是完整任务的端到端耗时',html)

    def test_partial_invalid_and_pending_timing_is_not_inferred_from_files(self):
        good={'started_at':'2030-01-01T00:00:00Z','ended_at':'2030-01-01T00:00:02Z','elapsed_seconds':2}
        timing=request_timing([good,{}])
        self.assertEqual(timing['known_cumulative_request_seconds'],2)
        self.assertIsNone(timing['cumulative_request_seconds'])
        self.assertIsNone(timing['request_window_seconds'])
        for elapsed in (None,True,-1,float('nan'),float('inf')):
            with self.subTest(elapsed=elapsed):
                value=request_timing([{**good,'elapsed_seconds':elapsed}])
                self.assertIsNone(value['cumulative_request_seconds'])
                self.assertEqual(value['request_window_seconds'],2)
        for start,end in [('invalid','2030-01-01T00:00:02Z'),
                          ('2030-01-01T00:00:03Z','2030-01-01T00:00:02Z'),
                          ('2030-01-01T00:00:00','2030-01-01T00:00:02')]:
            self.assertIsNone(request_timing([{**good,'started_at':start,'ended_at':end}])['request_window_seconds'])
        pending=request_timing([good],1)
        self.assertIsNone(pending['cumulative_request_seconds'])
        self.assertIsNone(pending['request_window_seconds'])
        self.assertEqual(pending['known_cumulative_request_seconds'],2)
        self.assertIsNone(request_timing([])['cumulative_request_seconds'])
        row=summarize(self.root/'runs')['runs'][0]
        self.assertIsNone(row['request_timing']['request_window_seconds'])
        self.assertIsNone(row['request_timing']['cumulative_request_seconds'])

    def test_pending_and_unknown_are_not_free(self):
        self.receipt('config-a', 'uncertain', None, 'failed')
        self.receipt('config-a', 'pending', end=False)
        value = summarize(self.root / 'runs')
        self.assertEqual(value['unknown_reserved_usd'], '0.7')
        self.assertEqual(value['unmatched_started_reserved_usd'], '0.7')
        self.assertEqual(value['receipt_upper_bound_usd'], '2.0')
        self.bind_review('config-a')
        with self.assertRaisesRegex(ValueError, 'unmatched started'):
            comparison.compare(self.names)

    def test_invalid_money_rejected(self):
        for amount in ['NaN', 'Infinity', '-0.1']:
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                money(amount)

    def test_fresh_comparison_render_and_unknown_visible(self):
        self.receipt('config-a', 'uncertain', None, 'failed')
        self.bind_review('config-a')
        value = comparison.compare(self.names)
        self.assertTrue(value['verification']['fresh_retrieval_only'])
        output = self.root / 'page'
        rendering.render(value, output)
        html = (output / 'index.html').read_text()
        self.assertIn('未知费用预留 $0.7', html)
        self.assertIn('不能推导模型排名或稳定性', html)
        self.assertIn('未设置', html)

    def test_reuse_rejected(self):
        run = self.root / 'runs/config-b'
        result = json.loads((run / 'result.json').read_text())
        result['attempts'][0]['execution'] = 'reused_frozen'
        write(run / 'result.json', result)
        self.bind_review('config-b')
        with self.assertRaisesRegex(ValueError, 'Reused retrieval'):
            comparison.compare(self.names)

    def test_initial_ref_rejected_even_when_execution_says_new(self):
        run = self.root / 'runs/config-b'
        config = json.loads((run / 'config.json').read_text())
        config['initial_query_ref'] = {'path': 'old-query'}
        write(run / 'config.json', config)
        self.bind_review('config-b')
        with self.assertRaisesRegex(ValueError, 'Initial query reuse'):
            comparison.compare(self.names)

    def test_non_model_change_rejected(self):
        run = self.root / 'runs/config-b'
        config = json.loads((run / 'config.json').read_text())
        config['reviewer']['model'] = 'different-reviewer'
        write(run / 'config.json', config)
        self.bind_review('config-b')
        with self.assertRaisesRegex(ValueError, 'non-model settings differ'):
            comparison.compare(self.names)

    def test_tampered_data_rejected(self):
        write(self.dataset / 'source.json', {'source': 'modified after freeze'})
        with self.assertRaisesRegex(ValueError, 'Frozen artifact differs'):
            comparison.compare(self.names)

    def test_unlisted_receipt_rejected(self):
        self.receipt('config-b', 'unfrozen')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            comparison.compare(self.names)

    def test_skill_difference_rejected(self):
        run = self.root / 'runs/config-b'
        query = run / 'attempt-01/query'
        write(query / 'result.json', {'plans': [{'skill_hashes': {'query': 'changed'}}]})
        result = json.loads((run / 'result.json').read_text())
        result['attempts'][0]['query_ref']['manifest_sha256'] = freeze(query)
        write(run / 'result.json', result)
        self.bind_review('config-b')
        with self.assertRaisesRegex(ValueError, 'non-model settings differ'):
            comparison.compare(self.names)

    def test_duplicate_call_cannot_be_double_counted(self):
        path = self.root / 'runs/config-b/calls/success-end.json'
        value = json.loads(path.read_text()); value['call_id'] = 'config-a-success'
        write(path, value)
        with self.assertRaisesRegex(ValueError, 'duplicate call receipt'):
            summarize(self.root / 'runs')

    def test_wrong_review_binding_rejected(self):
        review = self.root / 'evaluation-only/reviews/config-b/original-check.json'
        value = json.loads(review.read_text()); value['run_manifest_sha256'] = 'wrong'
        write(review, value)
        with self.assertRaisesRegex(ValueError, 'not bound'):
            comparison.compare(self.names)

    def test_distinct_names_required_and_renderer_requires_verification(self):
        for names in [['config-a'], ['config-a', 'config-a']]:
            with self.assertRaises(ValueError):
                comparison.compare(names)
        with self.assertRaisesRegex(ValueError, 'bindings'):
            rendering.render({'schema_version': 'e1-config-comparison-v1',
                'controlled_fields_equal': True}, self.root / 'page')


if __name__ == '__main__':
    unittest.main()
