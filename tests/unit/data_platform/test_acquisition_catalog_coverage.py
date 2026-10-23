"""Incomplete or conflicting SEC metadata cannot establish complete coverage."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import runpy
import unittest

from uteki.data_platform.connectors.company_acquisition import prepare_sources
# Load the sibling helper by path so both unittest discover and the offline runner can import it.
filing = runpy.run_path(str(Path(__file__).with_name('test_filing_integrity.py')))['filing']


class AcquisitionCatalogCoverageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.workspace = Path(folder.name).resolve() / 'store'
        self.config = {
            'symbol': 'OTHER', 'cik': '0000098765', 'market': 'US', 'as_of': '2025-06-30',
            'sec_user_agent': 'Offline user@example.test', 'document_validation': 'sec_inline_identity_v1',
            'download_policy': 'reuse_verified', 'source_policy': {'official': [], 'third_party': []},
            'filing_selection': {'mode': 'annual_filings_range', 'annual_form': '20-F',
                'report_period_end_from': '2023-01-01', 'report_period_end_to': '2025-06-30'},
            'limits': {'retries': 0},
        }
        self.rows = [
            {'form': '20-F', 'filingDate': '2024-03-01', 'reportDate': '2023-12-31',
             'accessionNumber': '0000098765-24-000001', 'primaryDocument': 'annual.htm'},
            {'form': '20-F', 'filingDate': '2025-03-01', 'reportDate': '2024-12-31',
             'accessionNumber': '0000098765-25-000001', 'primaryDocument': 'annual.htm'},
        ]
        self.metadata = 'https://data.sec.gov/submissions/CIK0000098765.json'
        self.calls = []

    def acquire(self, rows, *, include_archive_index=True, folder='run'):
        columns = {key: [row[key] for row in rows] for key in self.rows[0]}
        data = {'cik': '98765', 'name': 'Other', 'tickers': ['OTHER'], 'exchanges': [],
                'filings': {'recent': columns}}
        if include_archive_index:
            data['filings']['files'] = []
        raw = json.dumps(data).encode()
        self.calls.clear()

        def fetch(url, **kwargs):
            self.calls.append(url)
            if url == self.metadata:
                return raw
            for row in self.rows:
                accession = row['accessionNumber'].replace('-', '')
                if url == f'https://www.sec.gov/Archives/edgar/data/98765/{accession}/annual.htm':
                    return filing(period=row['reportDate'])
            raise AssertionError('unexpected document download')

        return prepare_sources(self.config, self.workspace / folder, fetch=fetch)

    def test_unknown_report_period_cannot_be_silently_excluded_from_range(self):
        for period in (None, ''):
            with self.subTest(period=period):
                rows = deepcopy(self.rows)
                rows[0]['reportDate'] = period
                result = self.acquire(rows, folder='missing-period-' + str(period))
                self.assertEqual(result['status'], 'completed_with_gaps')
                self.assertFalse(result['filing_catalog']['selection_discovery_complete'])
                self.assertTrue(result['gaps'])
                self.assertFalse(any('000009876524000001/' in url for url in self.calls))

    def test_missing_archive_index_is_unknown_coverage_not_an_empty_index(self):
        result = self.acquire(self.rows, include_archive_index=False)
        self.assertEqual(result['status'], 'completed_with_gaps')
        self.assertFalse(result['filing_catalog']['selection_discovery_complete'])
        self.assertTrue(result['gaps'])

    def test_identical_accession_metadata_is_one_task_and_one_download(self):
        result = self.acquire([*self.rows, deepcopy(self.rows[0])])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['documents']), 2)
        self.assertEqual(len(result['selected_filings']), 2)
        self.assertEqual({task['status'] for task in result['selected_filings']}, {'downloaded'})
        self.assertEqual(len(self.calls), 3)

    def test_unrelated_form_dates_do_not_become_annual_coverage_gaps(self):
        unrelated = {'form': 'DEF 14A', 'filingDate': '2025-03-01', 'reportDate': '2025-05-15',
                     'accessionNumber': '0000098765-25-000002', 'primaryDocument': 'meeting.htm'}
        result = self.acquire([*self.rows, unrelated])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['gaps'], [])
        self.assertEqual(len(result['documents']), 2)
        self.assertFalse(any('meeting.htm' in url for url in self.calls))

    def test_conflicting_accession_metadata_cannot_download_an_arbitrary_variant(self):
        changes = [('primaryDocument', 'different.htm'), ('filingDate', '2024-03-02'),
                   ('form', '20-F/A'), ('reportDate', '2023-12-30'),
                   ('form', '10-K'), ('reportDate', '2022-12-31'), ('filingDate', '2026-03-01')]
        for index, (field, changed) in enumerate(changes):
            with self.subTest(field=field, changed=changed):
                conflict = {**self.rows[0], field: changed}
                result = self.acquire([*self.rows, conflict], folder=f'conflict-{index}')
                self.assertEqual(result['status'], 'completed_with_gaps')
                self.assertFalse(result['filing_catalog']['selection_discovery_complete'])
                reasons = [gap['reason'] for gap in [*result['gaps'], *result['filing_catalog']['gaps']]]
                self.assertTrue(any('conflict' in reason for reason in reasons), reasons)
                self.assertFalse(any('000009876524000001/' in url for url in self.calls))
                self.assertFalse(any('000009876524000001/' in doc['source_url'] for doc in result['documents']))


if __name__ == '__main__':
    unittest.main()
