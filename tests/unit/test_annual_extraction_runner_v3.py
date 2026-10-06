"""Exact source-local reference protocol; no model calls or prefix repair."""
import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.unit import test_annual_extraction_runner_v2 as v2
from uteki.infrastructure.research_data.financial_records import digest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('annual_runner_v3',
    ROOT/'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/run_extraction_v3.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AnnualRunnerV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared, self.selected, self.source_id = v2.AnnualRunnerV2Tests.fixture(self)
        self.manifest, _, self.source, self.blocks, periods = runner.prepare_source_inputs(
            self.prepared/'dataset', self.selected, self.source_id)
        self.manifest_sha = periods['dataset_manifest_sha256']
        self.mapping = runner.build_source_reference_map(self.manifest, self.source, self.blocks, self.manifest_sha)

    def resolve(self, refs, mapping=None, **changes):
        return runner.resolve_selected_refs(refs, self.mapping if mapping is None else mapping,
            changes.get('manifest', self.manifest), changes.get('source', self.source),
            changes.get('blocks', self.blocks), changes.get('manifest_sha', self.manifest_sha))

    def test_refs_restore_complete_ids_from_verified_current_source(self):
        refs = [entry['ref'] for entry in self.mapping['entries']]
        self.assertEqual(refs, ['R000001', 'R000002', 'R000003'])
        self.assertEqual(self.resolve(refs), [b['block_id'] for b in self.blocks])
        self.assertEqual(self.resolve([refs[-1], refs[0]]), [self.blocks[-1]['block_id'], self.blocks[0]['block_id']])
        self.assertEqual(self.mapping['source_sha256'], self.source['source_sha256'])
        self.assertEqual(self.mapping['dataset_manifest_sha256'], self.manifest_sha)
        self.assertEqual([e['text_hash'] for e in self.mapping['entries']], [b['text_hash'] for b in self.blocks])

    def test_unknown_duplicate_legacy_and_modified_refs_are_rejected(self):
        shortened = self.blocks[0]['block_id'].rsplit('-', 1)[0]
        for refs in ([], ['R999999'], ['R000001', 'R000001'], [shortened],
                     [self.blocks[0]['block_id']], ['R1'], ['r000001'], [' R000001'], [None]):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.resolve(refs)
        with self.assertRaises(ValueError):
            runner.Discovery.model_validate({'selected_block_ids': [shortened],
                'period_catalog': [], 'scope_note': '', 'gaps': []})

    def test_mapping_cannot_be_reused_for_other_source_hash_or_manifest(self):
        for changes in ({'source': {**self.source, 'source_snapshot_id': 'different-filing'}},
                        {'source': {**self.source, 'source_sha256': 'a'*64}},
                        {'source': {**self.source, 'index_id': 'different-index'}},
                        {'manifest_sha': 'b'*64},
                        {'manifest': {**self.manifest, 'snapshot_id': 'different-snapshot'}}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'reference map'):
                self.resolve(['R000001'], **changes)
        other_company = {'company_id': 'sec-0000009018', 'cik': '0000009018'}
        with self.assertRaisesRegex(ValueError, 'reference map'):
            self.resolve(['R000001'], source={**self.source, 'company_id': other_company['company_id']},
                         manifest={**self.manifest, 'company': other_company})

    def test_tampered_mapping_is_rejected_even_if_requested_ref_exists(self):
        changed = deepcopy(self.mapping)
        changed['entries'][0]['block_id'] = self.blocks[1]['block_id']
        with self.assertRaisesRegex(ValueError, 'reference map'):
            self.resolve(['R000001'], changed)
        altered = deepcopy(self.blocks)
        altered[0]['text_hash'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'reference map'):
            self.resolve(['R000001'], blocks=altered)

    def test_frozen_reference_trace_reaches_extraction_with_full_ids(self):
        root = self.prepared
        (root/'selection.json').write_text(json.dumps(self.selected))
        config = {'provider': 'deepseek', 'planner_model': 'deepseek-v4-pro', 'planner_reasoning_effort': 'high',
                  'extractor_model': 'deepseek-flash', 'extractor_reasoning_effort': 'low',
                  'planner_max_tokens': 16384, 'budget_usd': None, 'max_requests_total': None,
                  'enforce_cost': False, 'budget_ledger': str(root/'costs.json'), 'max_request_bytes': 2500000}
        (root/'config.json').write_text(json.dumps(config))
        (root/'prompt.txt').write_text('Synthetic source-only extraction prompt.')
        captured = {}
        class NoNetworkPlanner:
            def __init__(self, *args, **kwargs):
                pass
            async def review(self, value):
                captured['input'] = value
                return {'selected_refs': [value['catalog'][-1]['ref']],
                    'period_catalog': [{'period_id': 'source-year', 'label': 'Reporting year', 'aliases': [],
                        'period': {'kind': 'year', 'start': '2031-01-05', 'end': '2032-01-03', 'basis': 'source'}}],
                    'scope_note': 'Synthetic protocol validation', 'gaps': []}
            async def aclose(self):
                pass
            def snapshot_usage(self):
                return {'model_calls': 0, 'test_double': True}
        async def no_network_extraction(dataset, job, output, **kwargs):
            captured['job'] = job
            return {'status': 'scripted_fixture'}
        args = argparse.Namespace(dataset=root/'dataset', selection=root/'selection.json', source=self.source_id,
            model_config=root/'config.json', credentials_root=root, prompt=root/'prompt.txt', output=root/'run')
        with patch.object(runner, 'SdkRecordReviewer', NoNetworkPlanner), patch.object(runner, 'run_direct_extraction', no_network_extraction):
            asyncio.run(runner.run(args))
        self.assertTrue(all('ref' in entry and 'block_id' not in entry for entry in captured['input']['catalog']))
        self.assertEqual(json.loads((root/'run/source-block-references.json').read_text()), self.mapping)
        resolved = json.loads((root/'run/resolved-selection.json').read_text())
        self.assertEqual(resolved['selected_refs'], ['R000003'])
        self.assertEqual(resolved['selected_block_ids'], [self.blocks[-1]['block_id']])
        reference = captured['job']['source_block_references_ref']
        self.assertEqual(reference['sha256'], digest((root/'run/source-block-references.json').read_bytes()))
        self.assertEqual(reference['reference_map_id'], self.mapping['reference_map_id'])
        self.assertEqual(set(captured['job']['block_ids']), {b['block_id'] for b in self.blocks})
        self.assertEqual(captured['job']['record_schema_version'], 'research-query-v0.5')


if __name__ == '__main__':
    unittest.main()
