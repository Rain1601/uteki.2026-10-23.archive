"""The public acquisition command runs the real downloader with offline HTTP bytes."""
from contextlib import redirect_stdout, redirect_stderr
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from uteki.infrastructure.research_data.query_cli import main
from tests.unit.test_company_materialization import filing


class AcquisitionCLITests(unittest.TestCase):
    def test_registered_name_runs_full_prepare_for_two_companies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles, configs = [], []
            for symbol, cik, alias, end in [('ACME', '0000000123', 'Acme Devices', '2024-12-31'),
                                            ('OTHER', '0000000456', 'Other Devices', '2023-12-31')]:
                cfg = {'symbol': symbol, 'cik': cik, 'market': 'US', 'as_of': '2025-06-30',
                       'filing_selection': {'mode': 'annual_filing_period', 'annual_form': '10-K', 'report_period_end': end},
                       'source_policy': {'official': [], 'third_party': []}, 'limits': {'retries': 0}}
                filename = symbol + '.json'
                raw = json.dumps(cfg).encode(); (root/filename).write_bytes(raw)
                configs.append(cfg)
                profiles.append({'company_id': 'sec-'+cik, 'cik': cik, 'symbol': symbol, 'market': 'US',
                    'aliases': [symbol, alias], 'profile': {'filename': filename, 'sha256': hashlib.sha256(raw).hexdigest()}})
            catalog = root/'catalog.json'
            catalog.write_text(json.dumps({'schema_version': 'company-profile-catalog-v1', 'profiles': profiles}))
            for cfg, entry in zip(configs, profiles):
                calls = []
                def fetch(url, **kwargs):
                    calls.append(url)
                    if url == f'https://data.sec.gov/submissions/CIK{cfg["cik"]}.json':
                        return json.dumps({'cik': cfg['cik'], 'name': cfg['symbol'], 'tickers': [cfg['symbol']], 'exchanges': [],
                            'filings': {'recent': {'form': ['10-K'], 'filingDate': ['2025-02-01'],
                                'reportDate': [cfg['filing_selection']['report_period_end']], 'accessionNumber': [cfg['cik']+'-25-000001'],
                                'primaryDocument': ['annual.htm']}, 'files': []}}).encode()
                    self.assertIn('/'+str(int(cfg['cik']))+'/', url)
                    end = cfg['filing_selection']['report_period_end']
                    return filing(cik=str(int(cfg['cik'])), start=end[:4]+'-01-01', end=end)
                def acquire(config, workspace, **kwargs):
                    return prepare_sources(config, workspace, fetch=fetch)
                stdout = io.StringIO()
                with patch.dict(os.environ, {'UTEKI_SEC_USER_AGENT': 'Test user@example.test'}, clear=True), \
                        patch('uteki.agents.data_query.coordinator.prepare_sources', side_effect=acquire), redirect_stdout(stdout):
                    code = main(['agent', 'prepare', '--company', entry['aliases'][1], '--company-catalog', str(catalog),
                        '--workspace', str(root/'store'), '--output', str(root/cfg['symbol'])])
                self.assertEqual(code, 0)
                result = json.loads(stdout.getvalue())
                acquisition = json.loads((root/cfg['symbol']/'acquisition.json').read_text())
                self.assertEqual(acquisition['scope']['sec_contact_origin'], 'environment')
                sources = json.loads((Path(result['dataset']['path'])/'sources.json').read_text())
                self.assertEqual({s['company_id'] for s in sources}, {entry['company_id']})
                self.assertEqual({s['period_end'] for s in sources}, {cfg['filing_selection']['report_period_end']})
                self.assertEqual(len(calls), 2)
                self.assertGreater(result['stage_coverage']['reading']['block_count'], 0)
            for extra in (['--company', 'UNKNOWN', '--company-catalog', str(catalog)],
                          ['--company', 'ACME'], ['--config', str(root/'ACME.json'), '--company-catalog', str(catalog)]):
                with patch('uteki.agents.data_query.coordinator.prepare_sources', side_effect=AssertionError('must not request')), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main(['agent', 'prepare', *extra, '--workspace', str(root/'forbidden-store'),
                                 '--output', str(root/'forbidden-output')])
                self.assertEqual(code, 2)
                self.assertFalse((root/'forbidden-output').exists())
                self.assertFalse((root/'forbidden-store').exists())

    def test_two_issuers_download_without_model_or_ticker_lookup_and_partial_is_nonzero(self):
        for symbol, cik, form in [('ACME', '0000000123', '10-K'), ('OTHER', '0000000456', '20-F')]:
            for blocked in (False, True):
                with self.subTest(symbol=symbol, blocked=blocked), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    cfg = {'symbol': symbol, 'cik': cik, 'market': 'US', 'as_of': '2025-06-30',
                           'filing_selection': {'mode': 'annual_filings_range', 'annual_form': form,
                             'report_period_end_from': '2023-01-01', 'report_period_end_to': '2025-06-30'},
                           'source_policy': {'official': [], 'third_party': []},
                           'limits': {'retries': 0}}
                    path = root/'input.json'; path.write_text(json.dumps(cfg))
                    calls = []
                    def fetch(url, **kwargs):
                        calls.append(url)
                        self.assertEqual(kwargs['headers']['User-Agent'], 'Test user@example.test')
                        if url == f'https://data.sec.gov/submissions/CIK{cik}.json':
                            return json.dumps({'cik': cik, 'name': symbol, 'tickers': [symbol], 'exchanges': [],
                                'filings': {'recent': {'form': [form], 'filingDate': ['2025-02-01'],
                                    'reportDate': ['2024-12-31'], 'accessionNumber': [cik+'-25-000001'],
                                    'primaryDocument': ['annual.htm']}, 'files': []}}).encode()
                        if blocked:
                            raise HTTPError(url, 403, 'Forbidden', {}, None)
                        return f'<html><body>{symbol} annual filing</body></html>'.encode()
                    def acquire(config, workspace):
                        return prepare_sources(config, workspace, fetch=fetch)
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, {'UTEKI_SEC_USER_AGENT': 'Test user@example.test'}, clear=True), \
                            patch('uteki.infrastructure.document_sources.company_acquisition.prepare_sources', side_effect=acquire), \
                            patch('uteki.agents.data_query.coordinator.CompanyDataCoordinator', side_effect=AssertionError('must not invoke research coordinator')), \
                            redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(['agent', 'acquire', '--config', str(path), '--workspace', str(root/'store')])
                    result = json.loads(stdout.getvalue())
                    self.assertEqual(code, 2 if blocked else 0, stderr.getvalue())
                    self.assertEqual(result['company']['company_id'], 'sec-'+cik)
                    self.assertTrue((root/'store'/result['manifest_path']).exists())
                    self.assertEqual(len(result['documents']), 0 if blocked else 1)
                    self.assertEqual(len(calls), 2)
                    self.assertNotIn('company_tickers', ' '.join(calls))
                    self.assertEqual(json.loads(path.read_text()), cfg)

    def test_missing_contact_fails_before_workspace_created(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg = {'symbol': 'ACME', 'market': 'US', 'as_of': '2025-06-30',
                   'filing_selection': {'mode': 'annual_report_period', 'report_period_end': '2024-12-31'},
                   'source_policy': {'official': [], 'third_party': []}, 'limits': {}}
            path = root/'input.json'; path.write_text(json.dumps(cfg))
            with patch.dict(os.environ, {}, clear=True), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                code = main(['agent', 'acquire', '--config', str(path), '--workspace', str(root/'store'), '--settings-root', str(root)])
            self.assertEqual(code, 2)
            self.assertFalse((root/'store').exists())


if __name__ == '__main__':
    unittest.main()
