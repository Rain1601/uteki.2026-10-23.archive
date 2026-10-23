"""Offline source acquisition contracts with deterministic HTTP fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from uteki.data_platform.connectors.company_acquisition import prepare_sources, TICKERS, _mime


class CompanyAcquisitionTests(unittest.TestCase):
    def test_mime_uses_root_element_after_xml_declaration_and_comments(self):
        for raw in (
            b'<?xml version="1.0"?>' + b'<!-- a long producer comment -->' * 20 + b'<html xmlns="http://www.w3.org/1999/xhtml"><body>Filing</body></html>',
            b'\xef\xbb\xbf<?xml version="1.0"?><html><body>Filing</body></html>',
            b'<?xml version="1.0"?><x:html xmlns:x="http://www.w3.org/1999/xhtml"><x:body>Filing</x:body></x:html>',
            b'<!DOCTYPE html><HTML><BODY>Filing</BODY></HTML>',
        ):
            with self.subTest(raw=raw[:70]):
                self.assertEqual(_mime(raw), 'text/html')
        for raw in (
            b'<?xml version="1.0"?><root><html>Nested element, not root</html></root>',
            b'<?xml version="1.0"?><rss><channel/></rss>',
            b'<!-- feed comment --><feed xmlns="http://www.w3.org/2005/Atom"><entry/></feed>',
            b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>',
            b'<?xml version="1.0"?><root><![CDATA[<html>not markup</html>]]></root>',
        ):
            with self.subTest(raw=raw[:70]):
                self.assertEqual(_mime(raw), 'application/xml')
        self.assertEqual(_mime(b'%PDF-1.7\n'), 'application/pdf')
        self.assertEqual(_mime(b'\xef\xbb\xbf {"value": 1}'), 'application/json')
        self.assertEqual(_mime(b'plain bytes'), 'application/octet-stream')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.config = {'symbol': 'ACME', 'market': 'NASDAQ', 'as_of': '2025-06-30',
                       'sec_user_agent': 'Fixture fixture@example.test',
                       'filing_selection': {'mode': 'latest_10k_and_subsequent_filings'},
                       'source_policy': {'official': [], 'third_party': [],
                                         'updates_window': {'trailing_calendar_days': 90}},
                       'limits': {'retries': 0, 'backoff_seconds': 0}}
        self.submission = 'https://data.sec.gov/submissions/CIK0000000123.json'
        self.filings = [
            ('10-K', '2025-02-01', '2024-12-31', '0000000123-25-000001', 'annual.htm'),
            ('10-Q', '2025-05-01', '2025-03-31', '0000000123-25-000002', 'quarter.htm'),
            ('10-K/A', '2025-06-01', '2024-12-31', '0000000123-25-000003', 'amended.htm'),
            ('8-K', '2025-06-02', '2025-06-01', '0000000123-25-000004', 'event.htm'),
            ('10-Q', '2025-08-01', '2025-06-30', '0000000123-25-000005', 'future.htm')]
        self.responses = {TICKERS: self.encoded({'0': {'ticker': 'ACME', 'cik_str': 123, 'title': 'Acme'}})}
        self.set_submissions()
        for form, filed, period, acc, filename in self.filings:
            self.responses[self.base(acc) + filename] = f'<html><body>{form} original {acc}</body></html>'.encode()
        acc = self.filings[3][3]
        self.responses[self.base(acc) + acc + '-index.html'] = b'<table><tr><td>EX-99.1</td><td><a href="exhibit.htm">Release</a></td></tr></table>'
        self.responses[self.base(acc) + 'exhibit.htm'] = b'<html><body>Official exhibit</body></html>'
        self.called = []

    def encoded(self, value):
        return json.dumps(value).encode()

    def base(self, acc):
        return 'https://www.sec.gov/Archives/edgar/data/123/' + acc.replace('-', '') + '/'

    def set_submissions(self, files=None):
        keys = ['form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument']
        recent = {key: [row[i] for row in self.filings] for i, key in enumerate(keys)}
        self.responses[self.submission] = self.encoded({'cik': '123', 'name': 'Acme Inc',
            'tickers': ['ACME'], 'exchanges': ['Nasdaq'], 'filings': {'recent': recent, 'files': files or []}})

    def fetch(self, url, *, headers, timeout):
        self.called.append(url)
        self.assertEqual(headers['User-Agent'], self.config['sec_user_agent'])
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    def run_sources(self):
        return prepare_sources(self.config, self.root, fetch=self.fetch)

    def test_company_resolution_filing_scope_exhibit_and_immutable_repeat(self):
        first = self.run_sources()
        self.assertEqual(first['company']['company_id'], 'sec-0000000123')
        self.assertEqual(first['company']['symbol'], 'ACME')
        self.assertEqual({d['form'] for d in first['documents']}, {'10-K', '10-Q', '8-K', '10-K/A', 'EXHIBIT'})
        self.assertFalse(any('future.htm' in url for url in self.called))
        for document in first['documents']:
            self.assertEqual(document['status'], 'frozen')
            self.assertEqual(hashlib.sha256((self.root / document['path']).read_bytes()).hexdigest(), document['content_sha256'])
        old = (self.root / first['manifest_path']).read_bytes()
        second = self.run_sources()
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual({d['change'] for d in second['documents']}, {'unchanged'})
        self.assertEqual((self.root / first['manifest_path']).read_bytes(), old)
        url = first['documents'][0]['source_url']
        self.responses[url] += b' changed'
        third = self.run_sources()
        revised = next(d for d in third['documents'] if d['source_url'] == url)
        self.assertEqual(revised['change'], 'revised')
        self.assertEqual(revised['previous_content_sha256'], first['documents'][0]['content_sha256'])
        self.assertTrue((self.root / first['documents'][0]['path']).exists())

    def test_unknown_or_conflicting_company_does_not_use_first_ticker(self):
        self.config['symbol'] = 'UNKNOWN'
        report = self.run_sources()
        self.assertIsNone(report['company'])
        self.assertEqual(report['documents'], [])
        self.assertEqual(report['gaps'][0]['reason'], 'symbol_unknown_or_ambiguous')
        self.assertEqual(self.called, [TICKERS])
        self.config['symbol'] = 'ACME'
        data = json.loads(self.responses[self.submission]); data['cik'] = '456'
        self.responses[self.submission] = self.encoded(data)
        self.assertIsNone(self.run_sources()['company'])

    def test_explicit_report_period_selects_archived_annual_for_two_companies(self):
        keys = ['form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument']
        for symbol, cik, end in [('ACME', 123, '2023-12-31'), ('OTHER', 987, '2023-06-30')]:
            with self.subTest(symbol=symbol):
                old_acc, new_acc = f'{cik:010d}-24-000001', f'{cik:010d}-25-000001'
                amended_acc = f'{cik:010d}-24-000002'
                recent = [('10-K', '2025-02-01', '2024-12-31', new_acc, 'new.htm')]
                archived = [('10-K', '2024-02-01', end, old_acc, 'old.htm'),
                            ('10-K/A', '2024-03-01', end, amended_acc, 'amended.htm')]
                archive_url = f'https://data.sec.gov/submissions/history-{cik}.json'
                responses = {
                    TICKERS: self.encoded({'0': {'ticker': symbol, 'cik_str': cik, 'title': symbol}}),
                    f'https://data.sec.gov/submissions/CIK{cik:010d}.json': self.encoded({
                        'cik': str(cik), 'name': symbol, 'tickers': [symbol], 'exchanges': ['Nasdaq'],
                        'filings': {'recent': {k: [r[i] for r in recent] for i, k in enumerate(keys)},
                                    'files': [{'name': f'history-{cik}.json', 'filingFrom': '2024-01-01', 'filingTo': '2024-12-31'}]}}),
                    archive_url: self.encoded({k: [r[i] for r in archived] for i, k in enumerate(keys)})}
                for row in [*recent, *archived]:
                    url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{row[3].replace("-", "")}/{row[4]}'
                    responses[url] = f'<html>{symbol} {row[2]} {row[0]}</html>'.encode()
                called = []
                def fetch(url, **kwargs):
                    called.append(url)
                    return responses[url]
                config = {**self.config, 'symbol': symbol,
                          'filing_selection': {'mode': 'annual_report_period', 'report_period_end': end}}
                workspace = self.root/symbol
                report = prepare_sources(config, workspace, fetch=fetch)
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['company']['company_id'], f'sec-{cik:010d}')
                self.assertEqual([d['form'] for d in report['documents']], ['10-K', '10-K/A'])
                self.assertEqual({d['period_end'] for d in report['documents']}, {end})
                self.assertEqual(report['scope']['report_period_end'], end)
                self.assertIn(archive_url, called)
                self.assertTrue(report['filing_catalog']['discovery_complete'])
                self.assertEqual({r['report_period_end'] for r in report['filing_catalog']['items']}, {end, '2024-12-31'})
                self.assertFalse(any(url.endswith('/new.htm') for url in called))
                old_manifest = (workspace/report['manifest_path']).read_bytes()
                config['filing_selection']['report_period_end'] = '2024-12-31'
                newer = prepare_sources(config, workspace, fetch=fetch)
                self.assertEqual([d['period_end'] for d in newer['documents']], ['2024-12-31'])
                self.assertTrue(newer['filing_catalog']['discovery_complete'])
                baseline = prepare_sources({**config, 'filing_selection': {'mode': 'latest_10k_and_subsequent_filings'}}, workspace, fetch=fetch)
                self.assertFalse(baseline['filing_catalog']['discovery_complete'])
                self.assertEqual(baseline['filing_catalog']['gaps'][0]['reason'], 'archive_not_inspected')
                self.assertEqual((workspace/report['manifest_path']).read_bytes(), old_manifest)
                self.assertTrue(all((workspace/d['path']).is_file() for d in report['documents']))

    def test_explicit_report_period_rejects_invalid_scope_before_fetch(self):
        for selection in (None, {}, {'mode': 'unknown'}, {'mode': 'annual_report_period'},
                          {'mode': 'annual_report_period', 'report_period_end': None},
                          {'mode': 'annual_report_period', 'report_period_end': 'FY2024'},
                          {'mode': 'annual_report_period', 'report_period_end': '2024-02-30'},
                          {'mode': 'annual_report_period', 'report_period_end': '2026-01-01'},
                          {'mode': 'annual_report_period', 'report_period_end': '2024-12-31', 'cik': 123}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                prepare_sources({**self.config, 'filing_selection': selection}, self.root, fetch=self.fetch)
        self.assertEqual(self.called, [])
        self.assertFalse(self.root.exists())

    def test_explicit_annual_form_uses_issuer_archives_and_retains_amendments(self):
        keys = ('form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument')
        cases = [('ACME', 123, '10-K', '2023-12-30'), ('BETA', 456, '20-F', '2023-09-30')]
        responses = {TICKERS: self.encoded({str(i): {'ticker': symbol, 'cik_str': cik}
                                           for i, (symbol, cik, _, _) in enumerate(cases)})}
        for symbol, cik, form, end in cases:
            recent = [(form, '2025-02-01', '2024-12-31', f'{cik:010d}-25-000001', 'new.htm')]
            alternate_form = '20-F' if form == '10-K' else '10-K'
            archived = [(form, '2024-02-01', end, f'{cik:010d}-24-000001', 'annual.htm'),
                        (form + '/A', '2024-03-01', end, f'{cik:010d}-24-000002', 'amendment.htm'),
                        (alternate_form, '2024-04-01', end, f'{cik:010d}-24-000003', 'other-form.htm'),
                        (form + '/A', '2025-07-01', end, f'{cik:010d}-25-000002', 'future.htm')]
            responses[f'https://data.sec.gov/submissions/CIK{cik:010d}.json'] = self.encoded({
                'cik': cik, 'name': symbol, 'tickers': [symbol], 'exchanges': ['Nasdaq'],
                'filings': {'recent': {k: [r[i] for r in recent] for i, k in enumerate(keys)},
                            'files': [{'name': f'history-{cik}.json', 'filingFrom': '2024-01-01',
                                       'filingTo': '2025-07-01'}]}})
            responses[f'https://data.sec.gov/submissions/history-{cik}.json'] = self.encoded({
                k: [r[i] for r in archived] for i, k in enumerate(keys)})
            for row in [*recent, *archived]:
                url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{row[3].replace("-", "")}/{row[4]}'
                responses[url] = f'<html>{symbol} {row[0]} {row[2]}</html>'.encode()
        called = []
        def fetch(url, **kwargs):
            called.append(url)
            return responses[url]
        frozen = []
        for symbol, cik, form, end in cases:
            with self.subTest(symbol=symbol, form=form):
                called.clear()
                selection = {'mode': 'annual_filing_period', 'annual_form': form, 'report_period_end': end}
                config = {**self.config, 'symbol': symbol, 'filing_selection': selection}
                report = prepare_sources(config, self.root, fetch=fetch)
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['company']['company_id'], f'sec-{cik:010d}')
                self.assertEqual([d['form'] for d in report['documents']], [form, form + '/A'])
                self.assertEqual({d['period_end'] for d in report['documents']}, {end})
                self.assertTrue(all(f'/data/{cik}/' in d['source_url'] for d in report['documents']))
                self.assertEqual(report['scope']['filing_selection'], selection)
                self.assertEqual(report['scope']['annual_form'], form)
                self.assertTrue(report['filing_catalog']['discovery_complete'])
                self.assertEqual({item['form'] for item in report['filing_catalog']['items']}, {form, form + '/A'})
                self.assertEqual(len(called), 5)
                self.assertIn(f'https://data.sec.gov/submissions/history-{cik}.json', called)
                self.assertFalse(any(url.endswith(('/new.htm', '/other-form.htm', '/future.htm')) for url in called))
                path = self.root / report['manifest_path']
                frozen.append((path, path.read_bytes()))
        # ACME's matching original already exists in the same storage; BETA may not use it.
        for form, end in [('20-F', cases[0][3]), ('10-K', '2024-12-31')]:
            called.clear()
            missing = prepare_sources({**self.config, 'symbol': 'BETA', 'filing_selection': {
                'mode': 'annual_filing_period', 'annual_form': form, 'report_period_end': end}}, self.root, fetch=fetch)
            self.assertEqual(missing['documents'], [])
            self.assertIn({'reason': 'annual_report_period_not_found', 'annual_form': form,
                           'report_period_end': end}, missing['gaps'])
            self.assertFalse(any('/Archives/' in url or 'CIK0000000123' in url for url in called))
        for path, raw in frozen:
            self.assertEqual(path.read_bytes(), raw)

    def test_new_annual_policy_rejects_missing_unsupported_or_conflicting_scope_before_io(self):
        valid = {'mode': 'annual_filing_period', 'annual_form': '20-F', 'report_period_end': '2024-12-31'}
        bad = [{k: v for k, v in valid.items() if k != field} for field in valid]
        bad += [{**valid, 'annual_form': form} for form in ('', None, '6-K', '20-F/A', '40-F')]
        bad += [{**valid, 'report_period_end': end} for end in ('', None, '2024-02-30', '2026-01-01')]
        bad += [{**valid, 'symbol': 'OTHER'}, {**valid, 'mode': 'annual_report_period'}]
        for selection in bad:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                prepare_sources({**self.config, 'filing_selection': selection}, self.root, fetch=self.fetch)
        self.assertEqual(self.called, [])
        self.assertFalse(self.root.exists())

    def test_missing_filing_policy_rejected_before_workspace_resolution_or_fetch(self):
        class UnusablePath:
            def __fspath__(self):
                raise AssertionError('workspace must not be accessed')
        config = {k: v for k, v in self.config.items() if k != 'filing_selection'}
        with self.assertRaisesRegex(ValueError, 'filing_selection'):
            prepare_sources(config, UnusablePath(), fetch=self.fetch)
        self.assertEqual(self.called, [])

    def test_20f_source_identity_mismatch_never_downloads_filing(self):
        self.config['filing_selection'] = {'mode': 'annual_filing_period', 'annual_form': '20-F',
                                           'report_period_end': '2024-12-31'}
        data = json.loads(self.responses[self.submission])
        data['cik'] = '456'
        data['filings']['recent']['form'] = ['20-F'] * len(self.filings)
        self.responses[self.submission] = self.encoded(data)
        report = self.run_sources()
        self.assertEqual(report['documents'], [])
        self.assertIsNone(report['company'])
        self.assertIn('submission_company_identity_mismatch', {gap['reason'] for gap in report['gaps']})
        self.assertEqual(self.called, [TICKERS, self.submission])

    def test_explicit_cik_skips_ticker_directory_and_verifies_submissions(self):
        self.config['cik'] = '0000000123'
        self.config['filing_selection'] = {'mode': 'annual_filing_period', 'annual_form': '10-K',
                                          'report_period_end': '2024-12-31'}
        self.responses[TICKERS] = AssertionError('ticker lookup must not run')
        report = self.run_sources()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['company']['cik'], '0000000123')
        self.assertEqual(report['scope']['requested_cik'], '0000000123')
        self.assertEqual(report['scope']['identity_resolution'], 'explicit_cik')
        self.assertNotIn(TICKERS, self.called)
        original = json.loads(self.responses[self.submission])
        for field, value, expected in [('cik', 456, 'submission_company_identity_mismatch'),
                                       ('tickers', ['OTHER'], 'submission_company_identity_mismatch'),
                                       ('exchanges', ['NYSE'], 'submission_market_mismatch')]:
            self.called.clear()
            self.responses[self.submission] = self.encoded({**original, field: value})
            failed = self.run_sources()
            self.assertIsNone(failed['company'])
            self.assertEqual(failed['documents'], [])
            self.assertIn(expected, {gap['reason'] for gap in failed['gaps']})
            self.assertEqual(self.called, [self.submission])

    def test_invalid_explicit_cik_never_falls_back_to_ticker_lookup(self):
        for cik in ('', None, 123, 123.0, True, '123', '0000000000', '00000001234', ' 0000000123', 'abcdefghij'):
            with self.subTest(cik=cik), self.assertRaisesRegex(ValueError, 'cik'):
                prepare_sources({**self.config, 'cik': cik}, self.root, fetch=self.fetch)
        self.assertFalse(self.called)
        self.assertFalse(self.root.exists())

    def test_annual_range_selects_all_periods_and_amendments_without_assuming_fiscal_calendar(self):
        keys = ('form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument')
        for form in ('10-K', '20-F'):
            with self.subTest(form=form):
                self.called.clear()
                self.config['cik'] = '0000000123'
                self.config['filing_selection'] = {'mode': 'annual_filings_range', 'annual_form': form,
                    'report_period_end_from': '2023-01-01', 'report_period_end_to': '2024-12-31'}
                self.filings = [(form, '2025-02-01', '2024-12-28', '0000000123-25-000011', 'current.htm')]
                archived = [(form, '2024-02-01', '2023-12-30', '0000000123-24-000011', 'previous.htm'),
                            (form + '/A', '2025-03-01', '2023-12-30', '0000000123-25-000012', 'amended-range.htm'),
                            (form, '2023-02-01', '2022-12-31', '0000000123-23-000011', 'outside.htm'),
                            (form + '/A', '2025-07-01', '2024-12-28', '0000000123-25-000013', 'future-range.htm')]
                self.set_submissions(files=[{'name': 'relevant.json', 'filingFrom': '2023-02-01', 'filingTo': '2025-07-01'},
                                            {'name': 'outside.json', 'filingFrom': '2020-01-01', 'filingTo': '2022-12-31'}])
                archive = 'https://data.sec.gov/submissions/relevant.json'
                self.responses[archive] = self.encoded({k: [r[i] for r in archived] for i, k in enumerate(keys)})
                for row in [*self.filings, *archived]:
                    self.responses[self.base(row[3]) + row[4]] = f'<html>{form} {row[2]}</html>'.encode()
                report = self.run_sources()
                self.assertEqual(report['status'], 'completed')
                self.assertEqual([(d['period_end'], d['form']) for d in report['documents']], [
                    ('2023-12-30', form), ('2023-12-30', form + '/A'), ('2024-12-28', form)])
                self.assertEqual(report['scope']['report_period_end_from'], '2023-01-01')
                self.assertEqual(report['scope']['report_period_end_to'], '2024-12-31')
                self.assertFalse(report['filing_catalog']['discovery_complete'])
                self.assertTrue(report['filing_catalog']['selection_discovery_complete'])
                self.assertEqual(report['gaps'], [])
                self.assertIn(archive, self.called)
                self.assertNotIn(TICKERS, self.called)
                self.assertFalse(any(url.endswith(('outside.json', 'outside.htm', 'future-range.htm')) for url in self.called))
                # Failed relevant discovery makes the range incomplete even when a recent annual exists.
                self.responses[archive] = TimeoutError('offline fixture')
                incomplete = self.run_sources()
                self.assertFalse(incomplete['filing_catalog']['selection_discovery_complete'])
                self.assertEqual(incomplete['status'], 'completed_with_gaps')
                self.assertIn('submission_archive_unavailable', {gap['reason'] for gap in incomplete['gaps']})

    def test_annual_range_rejects_missing_dates_order_and_extra_scope_before_io(self):
        valid = {'mode': 'annual_filings_range', 'annual_form': '20-F',
                 'report_period_end_from': '2023-01-01', 'report_period_end_to': '2024-12-31'}
        bad = [{key: value for key, value in valid.items() if key != field} for field in valid]
        bad += [{**valid, 'report_period_end_from': value} for value in ('', None, '2024-02-30', '2025-01-01')]
        bad += [{**valid, 'report_period_end_to': value} for value in ('', None, '2022-12-31', '2025-07-01')]
        bad += [{**valid, 'annual_form': '20-F/A'}, {**valid, 'report_period_end': '2024-12-31'}]
        for selection in bad:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                prepare_sources({**self.config, 'filing_selection': selection}, self.root, fetch=self.fetch)
        self.assertFalse(self.called)
        self.assertFalse(self.root.exists())

    def test_range_amendment_without_original_is_gap_not_latest_period_fallback(self):
        self.config['filing_selection'] = {'mode': 'annual_filings_range', 'annual_form': '10-K',
            'report_period_end_from': '2023-01-01', 'report_period_end_to': '2023-12-31'}
        self.filings[2] = ('10-K/A', '2025-06-01', '2023-12-31', '0000000123-25-000003', 'amended.htm')
        self.set_submissions()
        report = self.run_sources()
        self.assertEqual(report['documents'], [])
        self.assertIn('annual_original_not_found_for_amendment', {gap['reason'] for gap in report['gaps']})
        self.assertIn('annual_filing_range_not_found', {gap['reason'] for gap in report['gaps']})
        self.assertEqual(self.called, [TICKERS, self.submission])

    def test_unmatched_annual_period_never_falls_back_to_latest(self):
        self.config['filing_selection'] = {'mode': 'annual_report_period', 'report_period_end': '2023-12-31'}
        result = self.run_sources()
        self.assertEqual(result['documents'], [])
        self.assertEqual(result['status'], 'completed_with_gaps')
        self.assertIn('annual_report_period_not_found', {g['reason'] for g in result['gaps']})
        self.assertEqual(self.called, [TICKERS, self.submission])

    def test_targeted_annual_preserves_retry_limits_without_extra_source_discovery(self):
        self.config['filing_selection'] = {'mode': 'annual_report_period', 'report_period_end': '2024-12-31'}
        self.config['limits']['retries'] = 1
        self.config['source_policy']['official'] = [{'kind': 'ir', 'url': 'https://issuer.example/ir',
                                                    'allowed_hosts': ['issuer.example']}]
        annual_url = self.base(self.filings[0][3]) + 'annual.htm'
        self.responses[annual_url] = TimeoutError('fixture timeout')
        result = self.run_sources()
        self.assertEqual(self.called.count(annual_url), 2)
        self.assertEqual([d['form'] for d in result['documents']], ['10-K/A'])
        self.assertIn('filing_acquisition_failed', {g['reason'] for g in result['gaps']})
        self.assertFalse(any('issuer.example' in url for url in self.called))
        self.config['limits']['max_requests'] = 2
        self.called.clear()
        limited = self.run_sources()
        self.assertEqual(limited['requests'], 2)
        self.assertEqual(limited['documents'], [])
        self.assertIn('request_limit', {g['reason'] for g in limited['gaps']})
        self.assertTrue(limited['filing_catalog']['items'])

    def test_cancel_before_fetch_and_late_response_never_publish_success(self):
        cancelled = prepare_sources(self.config, self.root, fetch=self.fetch, should_stop=lambda: True)
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(cancelled['requests'], 0)
        self.assertEqual(self.called, [])
        self.config['filing_selection'] = {'mode': 'annual_report_period', 'report_period_end': '2024-12-31'}
        stopping = False
        def late_response(url, **kwargs):
            nonlocal stopping
            raw = self.fetch(url, **kwargs)
            if url.endswith('amended.htm'):
                stopping = True
            return raw
        result = prepare_sources(self.config, self.root, fetch=late_response, should_stop=lambda: stopping)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['requests'], 4)
        self.assertEqual([d['form'] for d in result['documents']], ['10-K'])
        self.assertTrue((self.root/result['documents'][0]['path']).is_file())
        self.assertTrue(any(d.get('error_type') == 'AcquisitionCancelled' for d in result['discovery']))
        late_raw = self.responses[self.base(self.filings[2][3])+'amended.htm']
        self.assertFalse((self.root/'sources/objects'/f'{hashlib.sha256(late_raw).hexdigest()}.bin').exists())
        self.assertEqual(json.loads((self.root/result['manifest_path']).read_text())['status'], 'cancelled')

    def test_missing_scope_unapproved_sources_and_private_addresses_rejected_before_fetch(self):
        for field in ('symbol', 'market', 'as_of', 'sec_user_agent', 'source_policy', 'limits', 'filing_selection'):
            config = copy.deepcopy(self.config); del config[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare_sources(config, self.root, fetch=self.fetch)
        for url in ('http://public.test/', 'https://127.0.0.1/', 'https://localhost/', 'https://u:p@public.test/'):
            config = copy.deepcopy(self.config)
            from urllib.parse import urlsplit
            config['source_policy']['official'] = [{'url': url, 'kind': 'ir', 'allowed_hosts': [urlsplit(url).hostname]}]
            with self.subTest(url=url), self.assertRaises(ValueError):
                prepare_sources(config, self.root, fetch=self.fetch)
        config = copy.deepcopy(self.config)
        config['source_policy']['third_party'] = [{'url': 'https://public.test/', 'kind': 'events', 'allowed_hosts': ['public.test']}]
        with self.assertRaisesRegex(ValueError, 'not approved'):
            prepare_sources(config, self.root, fetch=self.fetch)
        self.assertEqual(self.called, [])
        self.assertFalse(self.root.exists())

    def test_official_feed_dates_unknown_dates_and_offsite_links_remain_explicit(self):
        self.config['source_policy']['official'] = [{'url': 'https://official.test/feed', 'kind': 'blog', 'allowed_hosts': ['official.test']}]
        self.responses['https://official.test/feed'] = b'''<rss><channel>
          <item><link>https://official.test/past</link><pubDate>Mon, 02 Jun 2025 10:00:00 GMT</pubDate></item>
          <item><link>https://official.test/future</link><pubDate>2025-07-01</pubDate></item>
          <item><link>https://official.test/unknown</link></item>
          <item><link>https://elsewhere.test/item</link></item>
        </channel></rss>'''
        self.responses['https://official.test/past'] = b'<html>Past update</html>'
        self.responses['https://official.test/unknown'] = b'<html>Unknown publication time</html>'
        report = self.run_sources()
        updates = {d['source_url']: d for d in report['documents'] if d['role'] == 'blog'}
        self.assertTrue(updates['https://official.test/past']['as_of_eligible'])
        self.assertFalse(updates['https://official.test/unknown']['as_of_eligible'])
        self.assertNotIn('https://official.test/future', self.called)
        self.assertNotIn('https://elsewhere.test/item', self.called)
        self.assertIn('official_source_coverage_not_exhaustive', {g['reason'] for g in report['gaps']})

    def test_update_window_boundaries_from_feed_and_page_metadata(self):
        for mode in ('feed', 'html'):
            for group in ('official', 'third_party'):
                with self.subTest(mode=mode, group=group):
                    self.called.clear()
                    self.config['source_policy']['official'] = []
                    self.config['source_policy']['third_party'] = []
                    host = 'https://official.test/'
                    self.config['source_policy'][group] = [{
                        'url': host + 'index', 'kind': 'blog',
                        'allowed_hosts': ['official.test'], 'approved': True}]
                    dates = {'early': '2025-04-01', 'start': '2025-04-02',
                             'end': '2025-06-30', 'late': '2025-07-01', 'unknown': None}
                    links = []
                    for name, day in dates.items():
                        if mode == 'feed':
                            published = f'<pubDate>{day}</pubDate>' if day else ''
                            links.append(f'<item><link>{host}{name}</link>{published}</item>')
                        else:
                            links.append(f'<a href="{host}{name}">{name}</a>')
                        meta = f'<meta property="article:published_time" content="{day}">' if day else ''
                        self.responses[host + name] = f'<html><head>{meta}</head><body>Update</body></html>'.encode()
                    markup = '<rss><channel>' + ''.join(links) + '</channel></rss>' if mode == 'feed' else '<html>' + ''.join(links) + '</html>'
                    self.responses[host + 'index'] = markup.encode()
                    report = self.run_sources()
                    expected = {'start': '2025-04-02', 'end': '2025-06-30',
                                'calendar_days': 90, 'bounds': 'inclusive'}
                    self.assertEqual(report['scope']['updates_window'], expected)
                    saved = json.loads((self.root / report['manifest_path']).read_text())
                    self.assertEqual(saved['scope']['updates_window'], expected)
                    updates = {d['source_url']: d for d in report['documents'] if d['role'] == 'blog'}
                    self.assertEqual(set(updates), {host + name for name in ('start', 'end', 'unknown')})
                    self.assertTrue(updates[host + 'start']['as_of_eligible'])
                    self.assertTrue(updates[host + 'end']['as_of_eligible'])
                    self.assertFalse(updates[host + 'unknown']['as_of_eligible'])
                    self.assertEqual(updates[host + 'unknown']['status'], 'frozen_date_unverified')
                    reasons = {g['reason'] for g in report['gaps']}
                    self.assertTrue({'before_updates_window', 'after_as_of', 'publication_date_unverified'} <= reasons)
                    self.assertTrue(any(d['form'] == '10-K' and d['filed_at'] == '2025-02-01' for d in report['documents']))
                    for name in ('early', 'late'):
                        self.assertEqual(host + name in self.called, mode == 'html')

    def test_update_window_config_required_with_legacy_filing_only_compatibility(self):
        self.config['source_policy']['official'] = [{
            'url': 'https://official.test/feed', 'kind': 'blog', 'allowed_hosts': ['official.test']}]
        for window in (None, {}, {'trailing_calendar_days': 0}, {'trailing_calendar_days': True},
                       {'trailing_calendar_days': 1.5}, {'trailing_calendar_days': 1000000000},
                       {'trailing_calendar_days': 90, 'extra': 1}):
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.config['source_policy']['updates_window'] = window
                self.run_sources()
        del self.config['source_policy']['updates_window']
        with self.assertRaisesRegex(ValueError, 'explicit updates_window'):
            self.run_sources()
        self.assertEqual(self.called, [])
        self.assertFalse(self.root.exists())
        self.config['source_policy']['official'] = []
        report = self.run_sources()
        self.assertIsNone(report['scope']['updates_window'])
        self.assertTrue(any(d['form'] == '10-K' for d in report['documents']))

    def test_failures_and_limits_are_saved_without_claiming_completeness(self):
        self.config['limits']['max_documents'] = 1
        report = self.run_sources()
        self.assertEqual(len(report['documents']), 1)
        self.assertIn('document_limit', {g['reason'] for g in report['gaps']})
        self.config['limits'] = {'max_requests': 1, 'retries': 0}
        report = self.run_sources()
        self.assertEqual(report['requests'], 1)
        self.assertEqual(report['status'], 'identity_unresolved')
        self.assertIn('request_limit', {g['reason'] for g in report['gaps']})
        self.config['limits'] = {'max_bytes_per_document': 10, 'retries': 0}
        self.assertEqual(self.run_sources()['documents'], [])

    def test_archived_filings_are_date_scoped_and_retries_are_bounded(self):
        self.set_submissions(files=[{'name': 'older.json', 'filingFrom': '2020-01-01', 'filingTo': '2024-12-31'}])
        self.run_sources()
        self.assertFalse(any('older.json' in url for url in self.called))
        self.called.clear(); self.config['limits'].update(retries=1)
        attempts = []
        def flaky(url, *, headers, timeout):
            attempts.append(url)
            if len(attempts) == 1:
                raise TimeoutError('private request details must not be saved')
            return self.fetch(url, headers=headers, timeout=timeout)
        report = prepare_sources(self.config, self.root, fetch=flaky)
        self.assertEqual(attempts.count(TICKERS), 2)
        self.assertNotIn('private request details', json.dumps(report))
        self.assertTrue(any(row['status'] == 'failed' for row in report['discovery']))

    def test_future_or_malformed_dates_and_bad_limits_rejected(self):
        for value in ('2025-02-30', 'yesterday', '2999-01-01', ''):
            config = copy.deepcopy(self.config); config['as_of'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_sources(config, self.root, fetch=self.fetch)
        for value in (0, -1, True, 1000):
            config = copy.deepcopy(self.config); config['limits']['max_requests'] = value
            with self.subTest(limit=value), self.assertRaises(ValueError):
                prepare_sources(config, self.root, fetch=self.fetch)

    def test_storage_symlink_cannot_write_outside_workspace(self):
        self.root.mkdir(); external = Path(self.temp.name) / 'external'; external.mkdir()
        (self.root / 'sources').symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_sources()
        self.assertEqual(list(external.iterdir()), [])

    def test_another_company_uses_its_own_cik_source_and_period(self):
        self.config['symbol'] = 'BETA'
        self.responses[TICKERS] = self.encoded({
            '0': {'ticker': 'ACME', 'cik_str': 123}, '1': {'ticker': 'BETA', 'cik_str': 456}})
        acc = '0000000456-25-000001'
        url = 'https://www.sec.gov/Archives/edgar/data/456/' + acc.replace('-', '') + '/beta.htm'
        self.responses['https://data.sec.gov/submissions/CIK0000000456.json'] = self.encoded({
            'cik': 456, 'name': 'Beta Systems', 'tickers': ['BETA'], 'exchanges': ['Nasdaq'],
            'filings': {'recent': {'form': ['10-K'], 'filingDate': ['2025-01-15'],
                'reportDate': ['2024-09-30'], 'accessionNumber': [acc], 'primaryDocument': ['beta.htm']}, 'files': []}})
        self.responses[url] = b'<html>Beta September fiscal year</html>'
        report = self.run_sources()
        self.assertEqual(report['company']['company_id'], 'sec-0000000456')
        self.assertEqual([d['source_url'] for d in report['documents']], [url])
        self.assertEqual(report['documents'][0]['period_end'], '2024-09-30')
        self.assertNotIn(self.submission, self.called)

    def test_single_filing_failure_does_not_hide_other_documents(self):
        annual = self.base(self.filings[0][3]) + self.filings[0][4]
        self.responses[annual] = TimeoutError('do not expose request headers')
        report = self.run_sources()
        self.assertEqual(report['status'], 'completed_with_gaps')
        self.assertTrue(any(d['form'] == '10-Q' for d in report['documents']))
        self.assertTrue(any(g.get('source_url') == annual and g['reason'] == 'filing_acquisition_failed'
                            for g in report['gaps']))
        self.assertNotIn('request headers', json.dumps(report))

    def test_source_date_after_filing_is_rejected_and_history_can_supply_annual(self):
        self.filings = [('8-K', '2025-05-01', '2025-07-01', '0000000123-25-000006', 'invalid.htm')]
        self.set_submissions(files=[{'name': 'older.json', 'filingFrom': '2024-01-01', 'filingTo': '2025-02-01'}])
        acc = '0000000123-25-000001'
        self.responses['https://data.sec.gov/submissions/older.json'] = self.encoded({
            'form': ['10-K'], 'filingDate': ['2025-02-01'], 'reportDate': ['2024-12-31'],
            'accessionNumber': [acc], 'primaryDocument': ['annual.htm']})
        report = self.run_sources()
        self.assertEqual([d['form'] for d in report['documents']], ['10-K'])
        self.assertIn('invalid_filing_date', {g['reason'] for g in report['gaps']})
        self.assertIn('https://data.sec.gov/submissions/older.json', self.called)

    def test_failed_official_link_does_not_stop_later_link_and_unknown_kind_is_gap(self):
        self.config['source_policy']['official'] = [{'url': 'https://official.test/events', 'kind': 'events', 'allowed_hosts': ['official.test']}]
        self.responses['https://official.test/events'] = b'<html><a href="/event-broken">broken</a><a href="/event-good">good</a></html>'
        self.responses['https://official.test/event-broken'] = TimeoutError()
        self.responses['https://official.test/event-good'] = b'<html><meta property="article:published_time" content="2025-06-01"/>Good event</html>'
        report = self.run_sources()
        self.assertTrue(any(d['source_url'] == 'https://official.test/event-good' and d['as_of_eligible'] for d in report['documents']))
        self.assertTrue(any(g.get('source_url') == 'https://official.test/event-broken' for g in report['gaps']))
        self.assertEqual({g['kind'] for g in report['gaps'] if g['reason'] == 'official_source_kind_not_configured'}, {'ir', 'blog'})
