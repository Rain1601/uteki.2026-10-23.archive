"""Source-bound experiment preparation; independent synthetic issuers, no network."""
import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT/'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/run_extraction_v2.py'
spec = importlib.util.spec_from_file_location('annual_runner_v2', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def context(identifier='current', cik='9017', start='2031-01-05', end='2032-01-03'):
    return f'''<xbrli:context id="{identifier}"><xbrli:entity><xbrli:identifier
    scheme="http://www.sec.gov/CIK">{cik}</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>
    </xbrli:period></xbrli:context>'''


class AnnualRunnerV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, contexts=None, name='base'):
        root = self.root/name
        root.mkdir()
        source = 'synthetic-annual'
        raw = ('<html xmlns:xbrli="http://www.xbrl.org/2003/instance"><body>'
               '<div style="display:none">' + (context() if contexts is None else contexts) + '</div>'
               '<h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>Independent annual source.</p></body></html>').encode()
        (root/'source.html').write_bytes(raw)
        company = {'company_id': 'sec-0000009017', 'cik': '0000009017', 'name': 'Synthetic Foundry', 'symbol': 'SYN'}
        manifest = materialize_sources({'company': company, 'as_of': '2032-03-02', 'documents': [{
            'source_id': source, 'source_url': 'https://example.invalid/filing', 'form': '20-F',
            'period_end': '2032-01-03', 'filed_at': '2032-03-01', 'mime_type': 'text/html',
            'content_sha256': digest(raw), 'path': 'source.html', 'status': 'frozen'}]}, root, root/'dataset')
        selected = {'as_of': '2032-03-02', 'coverage': 'annual_core_financial_package', 'task_type': 'initialization',
            'sources': [{'source_id': source, 'company_id': company['company_id'], 'cik': company['cik'],
                'company_name': company['name'], 'symbol': company['symbol'], 'form': '20-F',
                'period_end': '2032-01-03', 'source_sha256': digest(raw),
                'dataset_manifest_sha256': digest((root/'dataset/manifest.json').read_bytes()),
                'dataset_snapshot_id': manifest['snapshot_id'], 'role': 'annual_financial_primary',
                'presentation_currency': 'TWD'}]}
        return root, selected, source

    def test_contexts_bind_source_hash_and_exclude_other_issuer(self):
        root, selected, source = self.fixture(context() + context('foreign', cik='9018', start='2034-01-01', end='2034-12-31'))
        before = (root/'dataset/manifest.json').read_bytes()
        _, _, _, _, metadata = runner.prepare_source_inputs(root/'dataset', selected, source)
        self.assertEqual(metadata['periods'], [{'startdate': '2031-01-05', 'enddate': '2032-01-03'}])
        self.assertEqual(metadata['company_id'], 'sec-0000009017')
        self.assertEqual(metadata['source_snapshot_id'], source)
        self.assertEqual(metadata['source_sha256'], selected['sources'][0]['source_sha256'])
        self.assertEqual(metadata['dataset_manifest_sha256'], digest(before))
        self.assertEqual(metadata['excluded_contexts'], [{'context_id': 'foreign', 'reason': 'another_issuer_context'}])
        self.assertEqual(metadata['contexts'][0]['context_id'], 'current')
        self.assertNotIn('kind', metadata['periods'][0])
        self.assertEqual((root/'dataset/manifest.json').read_bytes(), before)

    def test_unknown_company_source_period_currency_hash_and_amendment_fail(self):
        root, selected, source = self.fixture()
        for key, value in [('company_id', 'sec-0000009018'), ('cik', '0000009018'),
                           ('period_end', '2031-12-31'), ('source_sha256', '0'*64),
                           ('dataset_manifest_sha256', '0'*64), ('dataset_snapshot_id', 'other'),
                           ('presentation_currency', None), ('form', '20-F/A'),
                           ('role', 'amendment_not_annual_financial_primary')]:
            changed = deepcopy(selected)
            changed['sources'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.prepare_source_inputs(root/'dataset', changed, source)
        with self.assertRaises(ValueError):
            runner.prepare_source_inputs(root/'dataset', selected, 'other-source')
        with self.assertRaisesRegex(ValueError, 'cutoff'):
            runner.prepare_source_inputs(root/'dataset', {**selected, 'as_of': '2032-02-01'}, source)

    def test_corrupt_raw_source_is_rejected_before_contexts(self):
        root, selected, source = self.fixture()
        raw = next((root/'dataset/raw').glob('*.html'))
        raw.write_bytes(raw.read_bytes().replace(b'2032-01-03', b'2032-01-04'))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            runner.prepare_source_inputs(root/'dataset', selected, source)

    def test_invalid_dates_and_ambiguous_contexts_fail_without_guessing(self):
        invalid = [context(start='2031-02-29'), context(start='2032-03-01'),
                   context(start='2031-01-05T00:00:00'), context()+context(),
                   context(cik='9018'), context().replace('www.sec.gov/CIK', 'example.invalid/CIK'),
                   context().replace('</xbrli:period>', '<xbrli:instant>2032-01-03</xbrli:instant></xbrli:period>'),
                   context().replace('<xbrli:startDate>2031-01-05</xbrli:startDate>', '')]
        for index, contents in enumerate(invalid):
            root, selected, source = self.fixture(contents, name=str(index))
            with self.subTest(index=index), self.assertRaises(ValueError):
                runner.prepare_source_inputs(root/'dataset', selected, source)

    def test_explicit_planner_output_limit_is_mandatory(self):
        for invalid in ({}, {'planner_max_tokens': None}, {'planner_max_tokens': True},
                        {'planner_max_tokens': 255}, {'planner_max_tokens': 16385}, {'planner_max_tokens': '16384'}):
            with self.subTest(config=invalid), self.assertRaises(ValueError):
                runner.planner_output_limit(invalid)
        self.assertEqual(runner.planner_output_limit({'planner_max_tokens': 16384}), 16384)

    def test_effective_planner_config_and_source_bound_artifacts_without_model(self):
        root, selected, source = self.fixture()
        (root/'selection.json').write_text(json.dumps(selected))
        config = {'provider': 'deepseek', 'planner_model': 'deepseek-v4-pro', 'planner_reasoning_effort': 'high',
                  'extractor_model': 'deepseek-flash', 'extractor_reasoning_effort': 'low',
                  'planner_max_tokens': 16384, 'budget_usd': None, 'max_requests_total': None,
                  'enforce_cost': False, 'budget_ledger': str(root/'costs.json'), 'max_request_bytes': 2500000}
        (root/'config.json').write_text(json.dumps(config))
        (root/'prompt.txt').write_text('Synthetic source-only extraction prompt.')
        captured = {}
        class NoNetworkPlanner:
            def __init__(self, provider, model, **kwargs):
                captured['planner'] = {'provider': provider, 'model': model, **kwargs}
            async def review(self, value):
                captured['discovery'] = value
                return {'selected_block_ids': [value['catalog'][-1]['block_id']],
                        'period_catalog': [{'period_id': 'source-year', 'label': 'Reporting year', 'aliases': [],
                            'period': {'kind': 'year', 'start': '2031-01-05', 'end': '2032-01-03', 'basis': 'source'}}],
                        'scope_note': 'Synthetic validation only', 'gaps': []}
            async def aclose(self):
                pass
            def snapshot_usage(self):
                return {'model_calls': 0, 'test_double': True}
        async def no_network_extraction(dataset, job, output, **kwargs):
            captured['job'] = job
            captured['extractor'] = kwargs
            return {'status': 'scripted_fixture'}
        args = argparse.Namespace(dataset=root/'dataset', selection=root/'selection.json',
            source=source, model_config=root/'config.json', credentials_root=root,
            prompt=root/'prompt.txt', output=root/'run')
        with patch.object(runner, 'SdkRecordReviewer', NoNetworkPlanner), patch.object(runner, 'run_direct_extraction', no_network_extraction):
            asyncio.run(runner.run(args))
        self.assertEqual(captured['planner']['max_tokens'], 16384)
        self.assertEqual(captured['planner']['reasoning_effort'], 'high')
        self.assertEqual(captured['extractor']['model_config']['model'], 'deepseek-flash')
        self.assertEqual(captured['extractor']['model_config']['reasoning_effort'], 'low')
        metadata = json.loads((root/'run/source-period-contexts.json').read_text())
        reference = captured['job']['source_period_contexts_ref']
        self.assertEqual(reference['sha256'], digest((root/'run/source-period-contexts.json').read_bytes()))
        self.assertEqual(reference['source_sha256'], metadata['source_sha256'])
        self.assertEqual(captured['discovery']['source_period_contexts'], metadata['periods'])
        self.assertEqual(captured['job']['record_schema_version'], 'research-query-v0.5')


if __name__ == '__main__':
    unittest.main()
