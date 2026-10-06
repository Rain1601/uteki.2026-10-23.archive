"""Formal batch entry: source scope, pinned methods and honest partial coverage."""
import argparse
import asyncio
from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from uteki.agents.runtime.deepseek_model import json_instructions
from uteki.infrastructure.research_data.agent_cli import register_agent_commands, run_agent_command
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet, run_direct_extraction
from uteki.infrastructure.research_data.extraction_batches import (
    load_extraction_method, load_task_method, run_extraction_batch, table_batch_catalog,
)
from uteki.infrastructure.research_data.financial_records import digest


class ExtractionBatchTests(unittest.TestCase):
    def method(self, root):
        (root/'assets').mkdir()
        (root/'assets/prompt.txt').write_text('Preserve exact source values; do not infer missing facts.\n')
        (root/'assets/SKILL.md').write_text('Selected table scope only. Report uncovered comparisons explicitly.\n')
        spec = {'schema_version': 'data-extraction-method-v1', 'method_id': 'synthetic-annual-v2', 'version': 2,
                'supported_forms': ['10-K', '20-F'],
                'prompt': {'path': 'assets/prompt.txt', 'version': 'synthetic-prompt-v2',
                           'sha256': digest((root/'assets/prompt.txt').read_bytes())},
                'skill': {'path': 'assets/SKILL.md', 'sha256': digest((root/'assets/SKILL.md').read_bytes())},
                'batching': {'kind': 'table_with_context', 'neighbor_radius': 2}}
        path = root/'method.json'
        path.write_text(json.dumps(spec))
        (root/'task.json').write_text(json.dumps({'schema_version': 'data-extraction-task-v1',
            'task_type': 'synthetic_annual_extraction', 'default_method_id': spec['method_id'],
            'allowed_methods': [{'method_id': spec['method_id'], 'version': spec['version'],
                                 'path': 'method.json', 'sha256': digest(path.read_bytes())}]}))
        return path, spec

    def source(self, root, *, company='sec-0000090011', source='synthetic-source-a', end='2033-12-31', form='10-K'):
        root.mkdir()
        raw = (f'<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>{company} annual units.</p>'
               '<table><tr><td>Revenue</td><td>13</td></tr></table><p>Comparison context.</p>'
               '<table><tr><td>Assets</td><td>29</td></tr></table>'
               '<p>Note one.</p><p>Note two.</p><p>Unassigned final text.</p></body></html>').encode()
        (root/'filing.html').write_bytes(raw)
        materialize_sources({'company': {'company_id': company, 'cik': company.removeprefix('sec-'),
            'name': company, 'symbol': 'SYN'}, 'as_of': '2035-03-01', 'documents': [{
                'source_id': source, 'company_id': company, 'source_url': 'https://example.invalid/'+source,
                'form': form, 'filed_at': '2035-02-01', 'period_end': end, 'content_sha256': digest(raw),
                'path': 'filing.html', 'mime_type': 'text/html', 'status': 'frozen'}]}, root, root/'dataset')
        saved = json.loads((root/'dataset/sources.json').read_text())[0]
        blocks = [json.loads(line) for line in (root/'dataset'/saved['index_folder']/'blocks.jsonl').read_text().splitlines()]
        job = {'company_id': company, 'source_snapshot_id': source, 'as_of': '2035-03-01',
               'task_type': 'synthetic_annual_extraction',
               'task': 'Extract the explicitly selected annual material.', 'block_ids': [b['block_id'] for b in reversed(blocks)],
               'dataset_manifest_sha256': digest((root/'dataset/manifest.json').read_bytes()),
               'period_catalog': [{'company_id': company, 'source_snapshot_id': source, 'period_id': 'selected-year',
                   'label': end[:4], 'period': {'kind': 'year', 'start': end[:4]+'-01-01', 'end': end, 'basis': 'source'}}]}
        return root/'dataset', job

    def config(self, root):
        return {'provider': 'deepseek', 'model': 'explicit-fixture-model', 'budget_ledger': str(root/'ledger.sqlite'),
                'budget_usd': None, 'max_requests_total': None, 'max_tokens': 16384, 'reasoning_effort': 'low'}

    def test_actual_gateway_uses_frozen_skill_and_prompt_for_two_issuers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            method, spec = self.method(root)
            alternate = deepcopy(spec)
            alternate['method_id'] = 'synthetic-alternate-v3'; alternate['version'] = 3
            (root/'assets/alternate.txt').write_text('Alternate allowed method: preserve exact source evidence.\n')
            alternate['prompt'] = {'path': 'assets/alternate.txt', 'version': 'alternate-prompt-v3',
                                   'sha256': digest((root/'assets/alternate.txt').read_bytes())}
            (root/'alternate.json').write_text(json.dumps(alternate))
            profile = json.loads((root/'task.json').read_text())
            profile['allowed_methods'].append({'method_id': alternate['method_id'], 'version': 3,
                'path': 'alternate.json', 'sha256': digest((root/'alternate.json').read_bytes())})
            (root/'task.json').write_text(json.dumps(profile))
            for suffix, company, end in [('a', 'sec-0000090011', '2033-12-31'), ('b', 'sec-0000090022', '2034-12-31')]:
                dataset, job = self.source(root/suffix, company=company, source='source-'+suffix, end=end)
                captured = {}
                class RecordingGateway:
                    def __init__(self, provider, model, **kwargs):
                        captured.update(kwargs, provider=provider, model=model)
                        self.frozen_config = {'prompt': kwargs['prompt'], 'prompt_sha256': digest(kwargs['prompt']),
                                              'output_schema': kwargs['output_schema'].model_json_schema()}
                    async def review(self, packet):
                        captured['packet'] = packet
                        return {'records': [], 'relations': [], 'gaps': []}
                    async def aclose(self): pass
                    def snapshot_usage(self): return {'fixture': True}
                output = root/('run-'+suffix)
                with patch('uteki.agents.data_query.record_review_model.SdkRecordReviewer', RecordingGateway):
                    result = asyncio.run(run_extraction_batch(dataset, job, output, task_profile=root/'task.json', method_root=root,
                        method_id=None if suffix == 'a' else alternate['method_id'],
                        batch_index=1, model_config=self.config(root), credentials_root=root))
                snapshot = json.loads((output/'method-snapshot.json').read_text())
                self.assertEqual(snapshot['selection']['origin'], 'task_profile_default' if suffix == 'a' else 'explicit_allowed_override')
                self.assertEqual(snapshot['selection']['method_id'], spec['method_id'] if suffix == 'a' else alternate['method_id'])
                self.assertEqual(snapshot['task_profile']['sha256'], digest((root/'task.json').read_bytes()))
                self.assertEqual(snapshot['method_file']['sha256'], profile['allowed_methods'][0 if suffix == 'a' else 1]['sha256'])
                self.assertEqual(captured['prompt'], snapshot['effective_prompt']['text'])
                self.assertIn(snapshot['assets']['prompt']['text'], captured['prompt'])
                self.assertIn(snapshot['assets']['skill']['text'], captured['prompt'])
                effective = json.loads((output/'extraction-01/system-prompt-effective.json').read_text())
                self.assertEqual(effective['text'], json_instructions(captured['prompt'], captured['output_schema'].model_json_schema()))
                self.assertEqual(captured['model'], 'explicit-fixture-model')
                self.assertEqual(captured['packet']['company_id'], company)
                self.assertEqual(captured['packet']['period_catalog'][0]['period']['end'], end)
                tables = [b for b in captured['packet']['blocks'] if b['type'] == 'table']
                self.assertEqual(len(tables), 1)
                self.assertIn('Assets', tables[0]['text'])
                coverage = json.loads((output/'coverage.json').read_text())
                self.assertEqual([b['status'] for b in coverage['batches']], ['not_run', 'candidate'])
                self.assertEqual(coverage['pending_batch_indexes'], [0])
                self.assertFalse(coverage['core_package_complete'])
                self.assertEqual(result['normalized_record_count'], 0)
                self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
                manifest = json.loads((output/'manifest.json').read_text())
                for path, sha in manifest['files'].items():
                    self.assertEqual(digest((output/path).read_bytes()), sha)

    def test_method_drift_invalid_versions_and_symlink_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            method, spec = self.method(root)
            for key, value in [('version', 0), ('version', True), ('schema_version', 'unknown'),
                               ('batching', {'kind': 'table_with_context', 'neighbor_radius': 33})]:
                wrong = deepcopy(spec); wrong[key] = value
                method.write_text(json.dumps(wrong))
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    load_extraction_method(method, root)
            for path in ('../outside.txt', str(root/'assets/prompt.txt'), 'assets/missing.txt'):
                wrong = deepcopy(spec); wrong['prompt']['path'] = path
                method.write_text(json.dumps(wrong))
                with self.subTest(path=path), self.assertRaises(ValueError):
                    load_extraction_method(method, root)
            method.write_text(json.dumps(spec))
            prompt = root/'assets/prompt.txt'
            original = prompt.read_bytes()
            prompt.write_bytes(original+b'changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'): load_extraction_method(method, root)
            prompt.write_bytes(original)
            (root/'linked-assets').symlink_to(root/'assets', target_is_directory=True)
            wrong = deepcopy(spec); wrong['prompt']['path'] = 'linked-assets/prompt.txt'
            method.write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError, 'symlinks'): load_extraction_method(method, root)
            method.write_text(json.dumps(spec))
            prompt.unlink(); prompt.symlink_to(root/'assets/SKILL.md')
            with self.assertRaisesRegex(ValueError, 'symlinks'): load_extraction_method(method, root)
            (root/'linked-root').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                load_extraction_method('prompt.txt', root/'linked-root/assets')

    def test_scope_conflicts_missing_scope_and_inline_prompt_never_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); method, _ = self.method(root)
            dataset, job = self.source(root/'a')
            changes = [{'company_id': 'sec-0000090022'}, {'source_snapshot_id': 'another-source'},
                       {'as_of': '2034-01-01'}, {'block_ids': ['another-source-block']},
                       {'prompt': {'text': 'competing prompt'}}, {'company_id': ''}, {'block_ids': []},
                       {'task_type': None}, {'task_type': ''}, {'task_type': 'another_task'}]
            wrong_period = deepcopy(job['period_catalog']); wrong_period[0]['source_snapshot_id'] = 'another-source'
            changes.append({'period_catalog': wrong_period})
            for index, change in enumerate(changes):
                output = root/f'rejected-{index}'
                with self.subTest(change=change), self.assertRaises(ValueError):
                    asyncio.run(run_extraction_batch(dataset, {**job, **change}, output, task_profile=root/'task.json',
                        method_root=root, batch_index=0, model_config=self.config(root), credentials_root=root))
                self.assertFalse(output.exists())
            for index in (-1, 2, None, True):
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'batch-index'):
                    asyncio.run(run_extraction_batch(dataset, job, root/'invalid-index', task_profile=root/'task.json',
                        method_root=root, batch_index=index, model_config=self.config(root), credentials_root=root))

    def test_form_and_table_contracts_do_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); method, _ = self.method(root)
            dataset, job = self.source(root/'a', form='10-Q')
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                asyncio.run(run_extraction_batch(dataset, job, root/'run', task_profile=root/'task.json', method_root=root,
                    batch_index=0, model_config=self.config(root), credentials_root=root))
            packet = build_extraction_packet(dataset, job)
            packet['blocks'] = [b for b in packet['blocks'] if b['type'] != 'table']
            with self.assertRaisesRegex(ValueError, 'no table'): table_batch_catalog(packet, neighbor_radius=2)
            packet['blocks'][0]['ordinal'] = packet['blocks'][1]['ordinal']
            with self.assertRaisesRegex(ValueError, 'ordinals'): table_batch_catalog(packet, neighbor_radius=2)

    def test_model_failure_is_frozen_and_selected_batch_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); method, _ = self.method(root); dataset, job = self.source(root/'a')
            output = root/'failed'
            async def invalid(packet): return {'not': 'valid extraction'}
            with self.assertRaises(ValueError):
                asyncio.run(run_extraction_batch(dataset, job, output, task_profile=root/'task.json', method_root=root,
                    batch_index=0, model_config=self.config(root), credentials_root=root, model_call=invalid))
            coverage = json.loads((output/'coverage.json').read_text())
            self.assertEqual(coverage['pending_batch_indexes'], [0, 1])
            self.assertEqual([b['status'] for b in coverage['batches']], ['failed', 'not_run'])
            self.assertEqual(coverage['semantic_acceptance'], 'not_evaluated')
            self.assertTrue((output/'manifest.json').exists())
            self.assertTrue((output/'extraction-01/result.json').exists())

    def test_prepared_batch_pins_dataset_even_if_input_job_omits_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); method, _ = self.method(root); dataset, job = self.source(root/'a')
            job.pop('dataset_manifest_sha256')
            output = root/'drift'
            async def changed_dataset(dataset, job, output, **kwargs):
                manifest_path = dataset/'manifest.json'
                manifest = json.loads(manifest_path.read_text())
                manifest['snapshot_id'] = 'different-snapshot'
                manifest_path.write_text(json.dumps(manifest))
                return await run_direct_extraction(dataset, job, output, **kwargs)
            async def never(packet): raise AssertionError('must reject before model call')
            with patch('uteki.infrastructure.research_data.extraction_batches.run_direct_extraction', changed_dataset):
                with self.assertRaisesRegex(ValueError, 'manifest'):
                    asyncio.run(run_extraction_batch(dataset, job, output, task_profile=root/'task.json', method_root=root,
                        batch_index=0, model_config=self.config(root), credentials_root=root, model_call=never))
            self.assertEqual(json.loads((output/'result.json').read_text())['status'], 'failed')
            self.assertEqual(json.loads((output/'coverage.json').read_text())['block_delivery'], {})

    def test_cli_requires_every_explicit_input_and_preserves_extract(self):
        parser = argparse.ArgumentParser()
        register_agent_commands(parser.add_subparsers(dest='tool', required=True))
        pairs = [('dataset', 'dataset'), ('job', 'job.json'), ('task-profile', 'task.json'), ('method-root', 'root'),
                 ('batch-index', '0'), ('model-config', 'config.json'), ('credentials-root', 'credentials'), ('output', 'run')]
        args = ['agent', 'extract-batch'] + [item for key, value in pairs for item in ('--'+key, value)]
        for key, _ in pairs:
            invalid = args.copy(); offset = invalid.index('--'+key); del invalid[offset:offset+2]
            with self.subTest(key=key), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): parser.parse_args(invalid)
        old = parser.parse_args(['agent', 'extract', '--dataset', 'd', '--job', 'j', '--output', 'o',
                                 '--model-config', 'c', '--strategy', 'direct'])
        self.assertEqual(old.agent_action, 'extract')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root/'job.json'; job.write_text('{}'); config = root/'config.json'; config.write_text('{}')
            parsed = parser.parse_args(args)
            parsed.job, parsed.model_config = job, config
            runner = AsyncMock(return_value={'status': 'fixture'})
            with patch('uteki.infrastructure.research_data.extraction_batches.run_extraction_batch', runner):
                self.assertEqual(run_agent_command(parsed), {'status': 'fixture'})
            self.assertEqual(runner.call_args.kwargs['batch_index'], 0)
            self.assertEqual(runner.call_args.kwargs['method_root'], Path('root'))
            self.assertIsNone(runner.call_args.kwargs['method_id'])
            self.assertEqual(runner.call_args.kwargs['task_profile'], Path('task.json'))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(args+['--method', 'arbitrary.json'])

    def test_task_profile_rejects_unknown_choices_drift_and_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); method, _ = self.method(root)
            profile_path = root/'task.json'
            profile = json.loads(profile_path.read_text())
            for task, selected in [('another_task', None), (None, None), ('synthetic_annual_extraction', 'unknown'),
                                   ('synthetic_annual_extraction', '')]:
                with self.subTest(task=task, selected=selected), self.assertRaises(ValueError):
                    load_task_method(profile_path, root, task_type=task, method_id=selected)
            changes = [('sha256', 'f'*64), ('version', 9), ('method_id', 'different-identity')]
            for field, value in changes:
                wrong = deepcopy(profile); wrong['allowed_methods'][0][field] = value
                if field == 'method_id': wrong['default_method_id'] = value
                profile_path.write_text(json.dumps(wrong))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'hash mismatch|identity/version mismatch'):
                    load_task_method(profile_path, root, task_type='synthetic_annual_extraction')
            profile_path.write_text(json.dumps(profile))
            method.write_text(method.read_text()+'\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_task_method(profile_path, root, task_type='synthetic_annual_extraction')
            (root/'linked-task.json').symlink_to(profile_path)
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                load_task_method(root/'linked-task.json', root, task_type='synthetic_annual_extraction')


if __name__ == '__main__':
    unittest.main()
