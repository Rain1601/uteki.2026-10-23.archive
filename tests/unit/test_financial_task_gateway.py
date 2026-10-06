"""Registered task selection, immutable methods and bounded candidate execution."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.unit import test_extraction_batches as batch_fixtures
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.financial_tasks import FinancialTaskGateway
from uteki.infrastructure.research_data.extraction_batches import load_task_method


class FinancialTaskGatewayTests(unittest.TestCase):
    def setup_fixture(self, root, *, company='sec-0000090011', source='synthetic-source-a', end='2033-12-31'):
        fixture = batch_fixtures.ExtractionBatchTests()
        fixture.method(root)
        dataset, job = fixture.source(root / 'material', company=company, source=source, end=end)
        manifest = json.loads((dataset / 'manifest.json').read_text())
        scope = ExecutionScope(snapshot_id=manifest['snapshot_id'], company_ids=(company,),
            source_snapshot_ids=(source,), source_policy_id=manifest['source_policy_id'],
            knowledge_cutoff=job['as_of'], include_candidates=False)
        task = {'task_id': 'annual-task', 'job': job, 'task_profile': 'task.json',
            'task_profile_sha256': digest((root / 'task.json').read_bytes()), 'max_new_batches': 2}
        config = {**fixture.config(root), 'budget_policy': 'record_only'}
        return dataset, scope, task, config

    def gateway(self, root, dataset, scope, task, config, model_call=None, *, output='run'):
        return FinancialTaskGateway(dataset, scope, [task], method_root=root, output=root / output,
            model_config=config, credentials_root=root, model_call=model_call)

    def extract(self, gateway, root, scope, index=0, *, output='batch', **extra):
        return asyncio.run(gateway.extract({'task_id': 'annual-task', 'batch_index': index, **extra},
            scope=scope, output=root / 'run' / output))

    def test_two_independent_issuers_preserve_scope_period_and_real_table_catalog(self):
        for company, source, end in [('sec-0000090011', 'source-a', '2033-12-31'),
                                     ('sec-0000090022', 'source-b', '2034-12-31')]:
            with self.subTest(company=company), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                dataset, scope, task, config = self.setup_fixture(root, company=company, source=source, end=end)
                captured = []
                async def model(packet):
                    captured.append(packet)
                    return {'records': [], 'relations': [], 'gaps': ['Fixture leaves rows unresolved.']}
                gateway = self.gateway(root, dataset, scope, task, config, model)
                catalog = gateway.catalog[0]
                self.assertEqual(catalog['company_id'], company)
                self.assertEqual(catalog['source_snapshot_id'], source)
                self.assertEqual(len(catalog['batches']), 2)
                self.assertIn('Revenue', catalog['batches'][0]['source_excerpt'])
                self.assertIn('Assets', catalog['batches'][1]['source_excerpt'])
                self.assertLessEqual(len(catalog['batches'][0]['source_excerpt']), 600)
                self.assertEqual([b['status'] for b in catalog['batches']], ['pending', 'pending'])
                catalog['batches'].clear()
                self.assertEqual(len(gateway.catalog[0]['batches']), 2)
                receipt = self.extract(gateway, root, scope, 1)
                self.assertEqual(captured[0]['company_id'], company)
                self.assertEqual(captured[0]['source']['source_snapshot_id'], source)
                self.assertEqual(captured[0]['period_catalog'][0]['period']['end'], end)
                self.assertEqual(len([b for b in captured[0]['blocks'] if b['type'] == 'table']), 1)
                self.assertEqual(receipt['status'], 'candidate')
                self.assertEqual(receipt['adoption'], 'unchanged_candidate')
                self.assertEqual(receipt['semantic_acceptance'], 'not_evaluated')
                self.assertTrue(receipt['candidate_only'])
                self.assertEqual(receipt['raw_record_count'], 0)
                self.assertIn('Fixture leaves rows unresolved.', receipt['gaps'])
                self.assertNotIn('scope', receipt)
                self.assertNotIn('port', receipt)
                self.assertEqual(digest((Path(receipt['run']['path']) / 'manifest.json').read_bytes()),
                                 receipt['run']['manifest_sha256'])

    def test_registration_rejects_wrong_company_source_cutoff_manifest_and_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            changes = [{'company_id': 'sec-0000090022'}, {'source_snapshot_id': 'source-outside'},
                {'as_of': '2035-03-02'}, {'as_of': '2034-01-01'}, {'dataset_manifest_sha256': 'f' * 64},
                {'source_sha256': 'f' * 64}, {'task_type': 'unregistered'}, {'prompt': {'text': 'injected'}}]
            wrong_period = deepcopy(task['job']['period_catalog'])
            wrong_period[0]['company_id'] = 'sec-0000090022'
            changes.append({'period_catalog': wrong_period})
            changes.append({'entity_catalog': [{'entity_id': 'unknown', 'company_id': 'sec-0000090022'}]})
            for index, change in enumerate(changes):
                wrong = deepcopy(task); wrong['job'].update(change)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.gateway(root, dataset, scope, wrong, config, output=f'invalid-{index}')
                self.assertFalse((root / f'invalid-{index}').exists())
            missing = deepcopy(task); missing['job'].pop('dataset_manifest_sha256')
            with self.assertRaises(ValueError): self.gateway(root, dataset, scope, missing, config)
            for change in [{'snapshot_id': 'another-snapshot'}, {'company_ids': ['sec-0000090022']},
                           {'source_snapshot_ids': ['unknown']}, {'knowledge_cutoff': '2034-01-01'}]:
                wrong = scope.model_dump(mode='json'); wrong.update(change)
                with self.subTest(scope=change), self.assertRaises(ValueError):
                    self.gateway(root, dataset, wrong, task, config)

    def test_every_active_scope_field_and_callback_argument_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            async def never(packet): raise AssertionError('invalid request must never invoke a model')
            gateway = self.gateway(root, dataset, scope, task, config, never)
            for change in [{'snapshot_id': 'unknown'}, {'company_ids': ['sec-0000090022']},
                           {'source_snapshot_ids': ['unknown']}, {'knowledge_cutoff': '2035-03-02'},
                           {'include_candidates': True}]:
                wrong = scope.model_dump(mode='json'); wrong.update(change)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'exactly match'):
                    self.extract(gateway, root, wrong)
            for args in [{'task_id': 'unknown', 'batch_index': 0}, {'task_id': 'annual-task', 'batch_index': True},
                         {'task_id': 'annual-task', 'batch_index': -1}, {'task_id': 'annual-task', 'batch_index': 2},
                         {'task_id': 'annual-task', 'batch_index': 0, 'method_id': 'unknown'},
                         {'task_id': 'annual-task', 'batch_index': 0, 'job': {}}, {'task_id': 'annual-task'}]:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    asyncio.run(gateway.extract(args, scope=scope, output=root / 'run' / 'invalid'))
            with self.assertRaisesRegex(ValueError, 'inside'):
                asyncio.run(gateway.extract({'task_id': 'annual-task', 'batch_index': 0},
                    scope=scope, output=root / 'outside'))

    def test_registered_assets_are_loaded_after_original_method_files_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            gateway = self.gateway(root, dataset, scope, task, config)
            original_skill = (root / 'assets/SKILL.md').read_text()
            original_prompt = (root / 'assets/prompt.txt').read_text()
            for name in ('assets/SKILL.md', 'assets/prompt.txt', 'method.json', 'task.json'):
                (root / name).write_text('Changed after registration; must not be loaded.')
            captured = {}
            class RecordingModel:
                def __init__(self, provider, model, **kwargs):
                    captured.update(kwargs)
                    self.frozen_config = {'prompt': kwargs['prompt'], 'prompt_sha256': digest(kwargs['prompt']),
                                          'output_schema': kwargs['output_schema'].model_json_schema()}
                async def review(self, packet): return {'records': [], 'relations': [], 'gaps': []}
                async def aclose(self): pass
                def snapshot_usage(self): return {'fixture': True}
            with patch('uteki.agents.data_query.record_review_model.SdkRecordReviewer', RecordingModel):
                self.extract(gateway, root, scope)
            self.assertIn(original_skill, captured['prompt'])
            self.assertIn(original_prompt, captured['prompt'])
            self.assertNotIn('Changed after registration', captured['prompt'])
            self.assertFalse(captured['budget'].enforce)
            self.assertEqual(captured['budget'].path.resolve(), Path(config['budget_ledger']))
            snapshot = json.loads((root / 'run/batch/method-snapshot.json').read_text())
            self.assertEqual(snapshot['task_profile']['sha256'], task['task_profile_sha256'])
            self.assertEqual(snapshot['selection']['origin'], 'task_profile_default')

    def test_repeated_success_reuses_receipt_without_consuming_quota_or_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            task['max_new_batches'] = 1
            calls = []
            async def model(packet):
                calls.append(packet['packet_id'])
                return {'records': [], 'relations': [], 'gaps': []}
            gateway = self.gateway(root, dataset, scope, task, config, model)
            first = self.extract(gateway, root, scope)
            again = self.extract(gateway, root, scope, output='duplicate', method_id=gateway.catalog[0]['default_method_id'])
            self.assertEqual(first, again)
            self.assertEqual(len(calls), 1)
            self.assertFalse((root / 'run/duplicate').exists())
            self.assertEqual(len(list((root / 'run/financial-receipts').glob('*.json'))), 1)
            with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
                self.extract(gateway, root, scope, 1, output='second')
            self.assertEqual(len(calls), 1)

    def test_failed_execution_is_frozen_and_consumes_allowance_without_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            task['max_new_batches'] = 1
            async def failed(packet): raise RuntimeError('fixture model failed')
            gateway = self.gateway(root, dataset, scope, task, config, failed)
            with self.assertRaisesRegex(RuntimeError, 'fixture model failed'):
                self.extract(gateway, root, scope)
            self.assertEqual(json.loads((root / 'run/batch/result.json').read_text())['status'], 'failed')
            self.assertTrue((root / 'run/batch/manifest.json').exists())
            coverage = json.loads((root / 'run/batch/coverage.json').read_text())
            self.assertEqual(coverage['pending_batch_indexes'], [0, 1])
            self.assertFalse((root / 'run/financial-receipts').exists())
            with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
                self.extract(gateway, root, scope, output='retry')
            self.assertFalse((root / 'run/retry').exists())

    def test_modified_frozen_registration_and_reused_run_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            async def model(packet): return {'records': [], 'relations': [], 'gaps': []}
            gateway = self.gateway(root, dataset, scope, task, config, model)
            self.extract(gateway, root, scope)
            runfile = root / 'run/batch/extraction-01/extraction.json'
            old = runfile.read_bytes(); runfile.write_bytes(old + b'\n')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                self.extract(gateway, root, scope, output='reused')
            runfile.write_bytes(old)
            skill = root / 'run/registered-financial/annual-task/method-root/assets/SKILL.md'
            skill.write_text('Altered frozen skill')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                self.extract(gateway, root, scope, 1, output='second')

    def test_all_allowed_methods_are_frozen_and_catalog_batching_cannot_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            alternate = json.loads((root / 'method.json').read_text())
            alternate.update(method_id='alternate', version=3)
            alternate['prompt']['path'] = './assets/prompt.txt'
            alternate['skill']['path'] = './assets/SKILL.md'
            (root / 'alternate.json').write_text(json.dumps(alternate))
            profile = json.loads((root / 'task.json').read_text())
            profile['allowed_methods'].append({'method_id': 'alternate', 'version': 3, 'path': 'alternate.json',
                                              'sha256': digest((root / 'alternate.json').read_bytes())})
            (root / 'task.json').write_text(json.dumps(profile))
            task['task_profile_sha256'] = digest((root / 'task.json').read_bytes())
            async def model(packet): return {'records': [], 'relations': [], 'gaps': []}
            gateway = self.gateway(root, dataset, scope, task, config, model)
            self.assertEqual(gateway.catalog[0]['allowed_method_ids'], ['synthetic-annual-v2', 'alternate'])
            (root / 'alternate.json').unlink()
            receipt = self.extract(gateway, root, scope, method_id='alternate')
            self.assertEqual(receipt['method_id'], 'alternate')
            alternate['batching']['neighbor_radius'] = 1
            (root / 'alternate.json').write_text(json.dumps(alternate))
            profile['allowed_methods'][1]['sha256'] = digest((root / 'alternate.json').read_bytes())
            (root / 'task.json').write_text(json.dumps(profile))
            task['task_profile_sha256'] = digest((root / 'task.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'batch catalog configuration'):
                self.gateway(root, dataset, scope, task, config, model, output='different-batching')

    def test_registration_requires_pinned_profile_positive_quota_and_explicit_budget_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            for field, value in [('task_profile_sha256', 'f' * 64), ('max_new_batches', 0),
                                 ('max_new_batches', True), ('task_profile', str(root / 'task.json')),
                                 ('task_id', '../outside')]:
                wrong = deepcopy(task); wrong[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.gateway(root, dataset, scope, wrong, config)
            for change in [{'budget_policy': None}, {'budget_policy': 'implicit'}, {'enforce_cost': True}]:
                with self.subTest(config=change), self.assertRaises(ValueError):
                    self.gateway(root, dataset, scope, task, {**config, **change})

    def test_profile_drift_during_registration_is_rejected_before_any_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            reads = []
            def drifting_profile(*args, **kwargs):
                snapshot = load_task_method(*args, **kwargs)
                reads.append(snapshot)
                if len(reads) == 2:
                    snapshot['task_profile']['sha256'] = 'f' * 64
                return snapshot
            with patch('uteki.infrastructure.research_data.financial_tasks.load_task_method', drifting_profile):
                with self.assertRaisesRegex(ValueError, 'changed while registering'):
                    self.gateway(root, dataset, scope, task, config)
            self.assertFalse((root / 'run').exists())

    def test_unsupported_retry_policy_is_rejected_before_registration_or_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            calls = []
            async def never(packet):
                calls.append(packet)
                raise AssertionError('unsupported retry policy must not invoke a model')
            for retries in (1, 3, -1, True, '0', None):
                with self.subTest(retries=retries), self.assertRaisesRegex(ValueError, 'retries are unsupported'):
                    self.gateway(root, dataset, scope, task, {**config, 'max_retries': retries}, never)
                self.assertFalse((root / 'run').exists())
            gateway = self.gateway(root, dataset, scope, task, {**config, 'max_retries': 0}, never)
            self.assertEqual(gateway.model_config['max_retries'], 0)
            self.assertEqual(len(gateway.catalog), 1)
            self.assertEqual(calls, [])

    def test_dataset_drift_before_model_is_a_frozen_failed_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, scope, task, config = self.setup_fixture(root)
            task['max_new_batches'] = 1
            calls = []
            async def never(packet):
                calls.append(packet)
                raise AssertionError('drift must reject before a model call')
            gateway = self.gateway(root, dataset, scope, task, config, never)
            path = dataset / 'manifest.json'
            path.write_bytes(path.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'manifest integrity'):
                self.extract(gateway, root, scope)
            failure = json.loads((root / 'run/batch/gateway-failure.json').read_text())
            self.assertEqual(failure['status'], 'failed')
            self.assertEqual(failure['error_type'], 'ValueError')
            self.assertTrue((root / 'run/batch/manifest.json').exists())
            self.assertEqual(calls, [])
            with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
                self.extract(gateway, root, scope, output='retry')


if __name__ == '__main__':
    unittest.main()
