"""Crash/retry and validation through the downloader; synthetic HTTP, no model."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from tests.unit.test_filing_integrity import filing


class AcquisitionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()/'store'
        self.config = {'symbol': 'OTHER', 'cik': '0000098765', 'market': 'US', 'as_of': '2025-06-30',
            'sec_user_agent': 'Offline user@example.test', 'document_validation': 'sec_inline_identity_v1',
            'download_policy': 'reuse_verified', 'source_policy': {'official': [], 'third_party': []},
            'filing_selection': {'mode': 'annual_filings_range', 'annual_form': '20-F',
                'report_period_end_from': '2023-01-01', 'report_period_end_to': '2025-06-30'},
            'limits': {'retries': 0}}
        self.metadata = 'https://data.sec.gov/submissions/CIK0000098765.json'
        self.urls = [f'https://www.sec.gov/Archives/edgar/data/98765/0000098765{year}000001/annual.htm' for year in (24, 25)]
        self.responses = {self.metadata: json.dumps({'cik': '98765', 'name': 'Other', 'tickers': ['OTHER'],
            'exchanges': [], 'filings': {'recent': {'form': ['20-F', '20-F'],
                'filingDate': ['2024-03-01', '2025-03-01'], 'reportDate': ['2023-12-31', '2024-12-31'],
                'accessionNumber': ['0000098765-24-000001', '0000098765-25-000001'],
                'primaryDocument': ['annual.htm', 'annual.htm']}, 'files': []}}).encode(),
            self.urls[0]: filing(period='2023-12-31'), self.urls[1]: filing(period='2024-12-31')}
        self.calls = []
        self.current = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        return value

    def run_sources(self):
        return prepare_sources(self.config, self.root, fetch=self.fetch, clock=lambda: self.current)

    def test_retry_after_survives_new_invocation_and_only_defers_its_url(self):
        self.responses[self.urls[0]] = HTTPError(self.urls[0], 429, 'Too Many Requests', {'Retry-After': '61'}, None)
        first = self.run_sources()
        self.assertEqual([task['status'] for task in first['selected_filings']], ['deferred', 'downloaded'])
        deadlines = list(self.root.glob('request-cooldowns/*/*.json'))
        self.assertEqual(len(deadlines), 1)
        entry = json.loads(deadlines[0].read_text())
        self.assertEqual(entry['source_url'], self.urls[0])
        self.assertEqual(entry['next_retry_at'], (self.current+timedelta(seconds=61)).isoformat())
        before = deadlines[0].read_bytes()
        self.responses[self.urls[0]] = filing(period='2023-12-31')
        self.current += timedelta(seconds=1)
        self.calls.clear()
        second = self.run_sources()
        self.assertEqual(self.calls, [self.metadata])
        self.assertEqual(second['requests'], 1)
        self.assertEqual([task['status'] for task in second['selected_filings']], ['deferred', 'reused_verified'])
        self.assertEqual(second['selected_filings'][0]['next_retry_at'], entry['next_retry_at'])
        self.assertEqual(second['status'], 'completed_with_gaps')
        self.assertEqual(deadlines[0].read_bytes(), before)
        self.current += timedelta(seconds=60)
        self.calls.clear()
        third = self.run_sources()
        self.assertEqual(third['status'], 'completed')
        self.assertEqual(self.calls, [self.metadata, self.urls[0]])

    def test_http_date_cooldown_prevents_metadata_io_until_exact_deadline(self):
        original = self.responses[self.metadata]
        deadline = self.current + timedelta(seconds=45)
        self.responses[self.metadata] = HTTPError(self.metadata, 503, 'Unavailable',
                                                   {'Retry-After': format_datetime(deadline, usegmt=True)}, None)
        self.run_sources()
        self.responses[self.metadata] = original
        self.calls.clear()
        result = self.run_sources()
        self.assertEqual(self.calls, [])
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['status'], 'identity_unresolved')
        self.assertEqual(result['discovery'][0]['status'], 'deferred')
        self.assertEqual(result['gaps'][0]['next_retry_at'], deadline.isoformat())
        self.current = deadline
        self.assertEqual(self.run_sources()['status'], 'completed')

    def test_corrupt_cooldown_identity_fails_closed_without_using_other_url(self):
        key = hashlib.sha256(self.urls[0].encode()).hexdigest()
        path = self.root/'request-cooldowns'/key/'receipt.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema_version': 'request-cooldown-v1',
            'source_url': self.urls[1], 'next_retry_at': self.current.isoformat(), 'http_status': 429}))
        result = self.run_sources()
        self.assertEqual(self.calls, [self.metadata, self.urls[1]])
        self.assertEqual(result['selected_filings'][0]['reason'], 'invalid_request_cooldown_record')
        self.assertEqual([d['source_url'] for d in result['documents']], [self.urls[1]])

    def test_corrupt_object_recovers_new_copy_and_reuses_it_without_rewriting_history(self):
        first = self.run_sources()
        history = {path: path.read_bytes() for path in self.root.glob('source-runs/**/*') if path.is_file()}
        original = first['documents'][0]
        damaged_path = self.root/original['path']
        damaged_path.write_bytes(b'damaged historical bytes')
        self.calls.clear()
        second = self.run_sources()
        recovered = second['documents'][0]
        self.assertEqual(second['status'], 'completed_with_gaps')
        self.assertEqual(self.calls, [self.metadata, self.urls[0]])
        self.assertEqual(recovered['content_sha256'], original['content_sha256'])
        self.assertNotEqual(recovered['path'], original['path'])
        self.assertTrue(recovered['path'].startswith('sources/objects/recovered/'+second['run_id']+'/'))
        self.assertEqual((self.root/recovered['path']).read_bytes(), self.responses[self.urls[0]])
        self.assertEqual(damaged_path.read_bytes(), b'damaged historical bytes')
        self.assertEqual(second['storage_integrity']['status'], 'damaged_history_preserved')
        finding = recovered['storage_recovery'][0]
        self.assertEqual(finding['damaged_path'], original['path'])
        self.assertEqual(finding['observed_sha256'], hashlib.sha256(b'damaged historical bytes').hexdigest())
        for path, raw in history.items():
            self.assertEqual(path.read_bytes(), raw)
        self.calls.clear()
        third = self.run_sources()
        self.assertEqual(self.calls, [self.metadata])
        self.assertEqual(third['documents'][0]['path'], recovered['path'])
        self.assertEqual(third['status'], 'completed_with_gaps')
        self.assertEqual(third['storage_integrity'], second['storage_integrity'])
        self.assertEqual(len(list(self.root.glob('sources/objects/recovered/*/*.bin'))), 1)
        # Even a second damaged copy cannot cause a fallback to another issuer
        # or overwrite either historical byte sequence.
        (self.root/recovered['path']).write_bytes(b'damaged recovery bytes')
        fourth = self.run_sources()
        newest = fourth['documents'][0]
        self.assertNotEqual(newest['path'], recovered['path'])
        self.assertEqual(len(newest['storage_recovery']), 2)
        self.assertEqual((self.root/recovered['path']).read_bytes(), b'damaged recovery bytes')
        self.calls.clear()
        fifth = self.run_sources()
        self.assertEqual(self.calls, [self.metadata])
        self.assertEqual(fifth['documents'][0]['path'], newest['path'])

    def test_missing_object_can_be_downloaded_again_without_substituting_other_period(self):
        first = self.run_sources()
        (self.root/first['documents'][0]['path']).unlink()
        self.calls.clear()
        second = self.run_sources()
        self.assertEqual(self.calls, [self.metadata, self.urls[0]])
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(second['documents'][0]['path'], first['documents'][0]['path'])

    def test_corrupt_cached_object_cannot_recover_with_wrong_issuer_or_period(self):
        first = self.run_sources()
        original_path = self.root/first['documents'][0]['path']
        original_path.write_bytes(b'damaged')
        for raw in [filing(cik='11111', period='2023-12-31'), filing(period='2024-12-31')]:
            with self.subTest(raw=raw):
                self.responses[self.urls[0]] = raw
                result = self.run_sources()
                self.assertEqual(result['selected_filings'][0]['status'], 'failed')
                self.assertEqual([doc['source_url'] for doc in result['documents']], [self.urls[1]])
                self.assertEqual(original_path.read_bytes(), b'damaged')
                self.assertEqual(result['storage_integrity']['status'], 'damaged_history_preserved')

    def test_failed_download_retries_only_missing_original_and_preserves_history(self):
        self.responses[self.urls[1]] = HTTPError(self.urls[1], 403, 'Forbidden', {}, None)
        first = self.run_sources()
        before = (self.root/first['manifest_path']).read_bytes()
        self.assertEqual([t['status'] for t in first['selected_filings']], ['downloaded', 'access_blocked'])
        self.responses[self.urls[1]] = filing(period='2024-12-31')
        self.calls.clear()
        second = self.run_sources()
        self.assertEqual(second['status'], 'completed')
        self.assertEqual([t['status'] for t in second['selected_filings']], ['reused_verified', 'downloaded'])
        self.assertEqual(self.calls, [self.metadata, self.urls[1]])
        self.assertEqual(second['model_calls'], 0)
        self.assertEqual((self.root/first['manifest_path']).read_bytes(), before)

    def test_crash_before_final_manifest_recovers_from_per_document_receipt(self):
        self.responses[self.urls[1]] = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_sources()
        self.assertEqual(len(list(self.root.glob('source-runs/*/receipts/*.json'))), 1)
        self.assertEqual(list(self.root.glob('source-runs/*/manifest.json')), [])
        self.responses[self.urls[1]] = filing(period='2024-12-31')
        self.calls.clear()
        second = self.run_sources()
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(self.calls, [self.metadata, self.urls[1]])

    def test_wrong_company_period_form_or_error_page_cannot_be_a_frozen_filing(self):
        for raw in [filing(cik='11111', period='2023-12-31'), filing(period='2022-12-31'),
                    filing(form='10-K', period='2023-12-31'),
                    b'<html><head><title>Access Denied</title></head><body>Error</body></html>']:
            with self.subTest(raw=raw):
                self.responses[self.urls[0]] = raw
                result = self.run_sources()
                self.assertEqual(result['status'], 'completed_with_gaps')
                self.assertEqual([d['source_url'] for d in result['documents']], [self.urls[1]])
                self.assertEqual(result['selected_filings'][0]['status'], 'failed')
                self.assertIn('filing_content_invalid', result['selected_filings'][0]['reason'])

    def test_revalidate_policy_retains_changed_bytes_as_a_new_version(self):
        self.config['download_policy'] = 'revalidate'
        first = self.run_sources()
        self.responses[self.urls[0]] = self.responses[self.urls[0]].replace(b'</body>', b'<p>New source edition</p></body>')
        second = self.run_sources()
        self.assertEqual(second['documents'][0]['change'], 'revised')
        self.assertNotEqual(first['documents'][0]['content_sha256'], second['documents'][0]['content_sha256'])
        self.assertTrue((self.root/first['documents'][0]['path']).exists())

    def test_unsupported_policy_fails_before_io(self):
        for field, value in [('document_validation', 'unknown'), ('download_policy', 'unknown')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare_sources({**self.config, field: value}, self.root, fetch=self.fetch)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.calls)


if __name__ == '__main__':
    unittest.main()
