"""Independent issuer fixtures test discovery and integrity, not model quality."""
from copy import deepcopy
import json
import hashlib
import io
import socket
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from uteki.infrastructure.document_sources.annual_package import acquire_annual_package
from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from tests.unit.data_platform.test_filing_integrity import filing


class AnnualPackageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls = []

    def fixture(self, *, symbol='OTHER', cik='0000098765', period='2024-12-31', year=2024):
        profile = {'schema_version': 'annual-material-profile-v1',
            'company': {'symbol': symbol, 'cik': cik, 'market': 'US', 'aliases': [symbol, symbol+' Corporation']},
            'annual_form': '20-F', 'fiscal_year_label': 'period_end_year',
            'required_roles': ['filing', 'filing_index', 'filing_xbrl', 'full_report'],
            'directories': [{'url': 'https://issuer.example/annuals', 'allowed_hosts': ['issuer.example'],
                'selectors': [{'role': 'full_report', 'section': 'Consolidated',
                    'text_pattern': '^{year} Annual$', 'url_pattern': '/reports/{year}.*\\.pdf$'}]}]}
        accession = cik+'-25-000001'
        base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
        recent = {'form': ['20-F'], 'filingDate': ['2025-03-01'], 'reportDate': [period],
                  'accessionNumber': [accession], 'primaryDocument': ['annual.htm']}
        responses = {
            'https://data.sec.gov/submissions/CIK'+cik+'.json': json.dumps({'cik': cik, 'name': symbol,
                'tickers': [symbol], 'exchanges': [], 'filings': {'recent': recent, 'files': []}}).encode(),
            base+'annual.htm': filing(cik=cik, period=period),
            base+accession+'-index.html': b'<html><table><tr><td>XBRL SCHEMA</td><td><a href="issuer.xsd">Schema</a></td></tr>'
                b'<tr><td>EX-99.1</td><td><a href="exhibit.htm">Exhibit</a></td></tr></table></html>',
            base+'issuer.xsd': b'<?xml version="1.0"?><xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>',
            base+'exhibit.htm': b'<html><body>Independent supplementary disclosure</body></html>',
            'https://issuer.example/annuals': f'<html><h2>Consolidated</h2><a href="/reports/{year}.pdf">{year} Annual</a>'
                f'<a href="/reports/{year}-mirror.pdf">{year} Annual</a><h2>Parent</h2>'
                f'<a href="/reports/{year}-parent.pdf">{year} Annual</a></html>'.encode(),
            f'https://issuer.example/reports/{year}.pdf': b'%PDF-1.7\nIndependent fixture original\n%%EOF',
            f'https://issuer.example/reports/{year}-mirror.pdf': b'%PDF-1.7\nIndependent fixture original\n%%EOF'}
        return profile, responses, base

    def run_package(self, profile, responses, *, company=None, period='2024-12-31', year=2024, change=None, folder='run'):
        counts = {}
        def fetch(url, **kwargs):
            self.calls.append(url)
            self.assertNotIn('If-None-Match', kwargs['headers'])
            self.assertNotIn('If-Modified-Since', kwargs['headers'])
            counts[url] = counts.get(url, 0)+1
            return change(url, counts[url], responses[url]) if change else responses[url]
        return acquire_annual_package(profile, company=company or profile['company']['symbol'],
            fiscal_year=year, report_period_end=period, as_of='2025-06-30', workspace=self.root/'store',
            output=self.root/folder, sec_user_agent='Offline fixture@example.test', fetch=fetch)

    def test_two_companies_and_fiscal_calendars_three_fetches_and_source_preserving_duplicates(self):
        for symbol, cik, period in [('OTHER', '0000098765', '2024-12-31'), ('ACME', '0000001234', '2024-09-28')]:
            profile, responses, base = self.fixture(symbol=symbol, cik=cik, period=period)
            result = self.run_package(profile, responses, company=symbol+' Corporation', period=period, folder=symbol)
            self.assertEqual(result['completed_rounds'], 3)
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual(result['parsing_acceptance'], 'not_run')
            self.assertTrue(result['inventory_consistent'])
            self.assertTrue(all(m['repeat_complete'] for m in result['materials']))
            self.assertFalse(any(m['remote_repeat_complete'] for m in result['materials']))  # fixture != remote proof
            self.assertEqual(self.calls.count(base+'annual.htm'), 3)
            self.assertFalse(any('-parent.pdf' in u for u in self.calls))
            self.assertEqual(len(result['byte_duplicate_groups']), 3)
            self.assertTrue(all(len(d['source_urls']) == 2 for d in result['byte_duplicate_groups']))
            self.assertNotIn('fixture@example.test', (self.root/symbol/'input.json').read_text())

    def test_unknown_company_and_invalid_scope_make_no_requests_or_output(self):
        profile, responses, _ = self.fixture()
        for company, period in [('TSM', '2024-12-31'), ('', '2024-12-31'), ('OTHER', '')]:
            with self.subTest(company=company, period=period), self.assertRaises(ValueError):
                acquire_annual_package(profile, company=company, fiscal_year=2024, report_period_end=period,
                    as_of='2025-06-30', workspace=self.root/'store', output=self.root/'bad',
                    sec_user_agent='Offline fixture@example.test', fetch=lambda *_a, **_k: self.fail('must not request'))
            self.assertFalse((self.root/'bad').exists())

    def test_wrong_company_body_is_rejected_and_cannot_supply_required_filing(self):
        profile, responses, base = self.fixture()
        responses[base+'annual.htm'] = filing(cik='0000000111', period='2024-12-31')
        result = self.run_package(profile, responses)
        self.assertTrue(any(g['reason'] == 'annual_required_role_missing' and g['role'] == 'filing' for g in result['gaps']))
        self.assertFalse(any('filing' in m['roles'] and m['observations'] for m in result['materials']))

    def test_changed_content_preserves_three_versions_and_does_not_claim_stability(self):
        profile, responses, base = self.fixture()
        def change(url, count, raw):
            return raw.replace(b'</body>', f'<p>Revision {count}</p></body>'.encode()) if url == base+'annual.htm' else raw
        result = self.run_package(profile, responses, change=change)
        main = next(m for m in result['materials'] if m['source_url'] == base+'annual.htm')
        self.assertEqual(main['byte_consistency'], 'changed')
        self.assertEqual(len({o['path'] for o in main['observations']}), 3)
        self.assertTrue(all((self.root/'store'/o['path']).is_file() for o in main['observations']))

    def test_disappeared_directory_link_remains_in_expected_inventory(self):
        profile, responses, _ = self.fixture()
        def change(url, count, raw):
            return raw.replace(b'<a href="/reports/2024-mirror.pdf">2024 Annual</a>', b'') if url.endswith('/annuals') and count > 1 else raw
        result = self.run_package(profile, responses, change=change)
        mirror = next(m for m in result['materials'] if m['source_url'].endswith('-mirror.pdf'))
        self.assertEqual(mirror['byte_consistency'], 'incomplete')
        self.assertFalse(result['inventory_consistent'])

    def test_403_stops_new_rounds_and_keeps_the_failure(self):
        profile, responses, base = self.fixture()
        def change(url, count, raw):
            if url == base+'annual.htm':
                raise HTTPError(url, 403, 'Denied', {}, None)
            return raw
        result = self.run_package(profile, responses, change=change)
        self.assertEqual(result['completed_rounds'], 1)
        self.assertEqual(self.calls.count(base+'annual.htm'), 1)
        self.assertTrue(any(g['reason'] == 'repeat_rounds_incomplete' for g in result['gaps']))

    def test_html_error_page_cannot_be_a_pdf_and_wrong_period_cannot_select_latest(self):
        profile, responses, _ = self.fixture()
        responses['https://issuer.example/reports/2024.pdf'] = b'<html>Access denied</html>'
        result = self.run_package(profile, responses)
        material = next(m for m in result['materials'] if m['source_url'].endswith('/2024.pdf'))
        self.assertFalse(material['repeat_complete'])
        # Another period has no original; it must not fall back to this annual.
        self.calls.clear()
        result = self.run_package(profile, responses, period='2023-12-31', year=2023, folder='other-period')
        self.assertTrue(any(g['reason'] == 'annual_report_period_not_found' for g in result['gaps']))
        self.assertFalse(any('/Archives/' in u for u in self.calls))

    def test_denied_auxiliary_does_not_block_independent_repeats_and_error_body_is_quarantined(self):
        profile, responses, _ = self.fixture()
        url = 'https://issuer.example/reports/2024.pdf'
        body = b'<html>synthetic edge denial</html>'
        def change(source, count, raw):
            if source == url:
                raise HTTPError(url, 403, 'Denied', {'Server': 'fixture-edge',
                    'Set-Cookie': 'must not enter log'}, io.BytesIO(body))
            return raw
        result = self.run_package(profile, responses, change=change)
        self.assertEqual(result['completed_rounds'], 3)
        self.assertEqual(self.calls.count(url), 1)
        self.assertTrue(all(m['repeat_complete'] for m in result['materials'] if m['source_url'] != url))
        report = json.loads((self.root/'run/round-1.json').read_text())
        failure = next(e for e in report['discovery'] if e.get('http_status') == 403)
        self.assertEqual(failure['response_headers']['Server'], 'fixture-edge')
        self.assertNotIn('Set-Cookie', failure['response_headers'])
        self.assertFalse(failure['eligible_original'])
        self.assertEqual((self.root/'store'/failure['partial_path']).read_bytes(), body)
        self.assertFalse(any(d['content_sha256'] == hashlib.sha256(body).hexdigest() for d in report['documents']))

    def test_partial_http_observations_resume_only_remaining_two_without_fourth_get(self):
        profile, responses, _ = self.fixture()
        calls = []
        class Response:
            status = 200
            def __init__(self, url):
                self.url, self.raw, self.headers = url, responses[url], {}
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, cap): return self.raw[:cap]
        class Opener:
            def open(self, req, timeout):
                calls.append(req.full_url)
                return Response(req.full_url)
        def cancelled_after_round(*args, **kwargs):
            report = prepare_sources(*args, **kwargs)
            report['status'] = 'cancelled'  # Host cancellation between complete rounds.
            return report
        kwargs = dict(company='OTHER', fiscal_year=2024, report_period_end='2024-12-31',
                      as_of='2025-06-30', workspace=self.root/'store', sec_user_agent='Fixture fixture@example.test')
        with patch('uteki.infrastructure.document_sources.company_acquisition.socket.getaddrinfo',
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
             patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener', return_value=Opener()), \
             patch('uteki.infrastructure.document_sources.company_acquisition.time.sleep'):
            with patch('uteki.infrastructure.document_sources.annual_package.prepare_sources', side_effect=cancelled_after_round):
                first = acquire_annual_package(profile, output=self.root/'partial', **kwargs)
            parent = self.root/'partial/verification.json'
            second = acquire_annual_package(profile, output=self.root/'resumed', resume_verification=parent,
                                           resume_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(), **kwargs)
        self.assertEqual(second['inherited_partial_materials'], first['expected_materials'])
        self.assertTrue(all(m['remote_repeat_complete'] for m in second['materials']))
        for old, new in zip(first['materials'], second['materials']):
            self.assertEqual(new['observations'][0], old['observations'][0])
            self.assertEqual(len(new['observations']), 3)
            self.assertEqual(calls.count(new['source_url']), 3)
        # A caller must not hide a removed material by changing the denominator.
        responses['https://issuer.example/annuals'] = b'<html><h2>Consolidated</h2><a href="/reports/2024.pdf">2024 Annual</a></html>'
        with patch('uteki.infrastructure.document_sources.company_acquisition.socket.getaddrinfo',
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
             patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener', return_value=Opener()), \
             patch('uteki.infrastructure.document_sources.company_acquisition.time.sleep'):
            third = acquire_annual_package(profile, output=self.root/'removed', resume_verification=parent,
                                          resume_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(), **kwargs)
        self.assertEqual(third['expected_materials'], first['expected_materials'])
        self.assertTrue(any(g['reason'] == 'prior_material_missing_from_current_inventory' for g in third['gaps']))
        # Frozen discovery is explicit, hash bound, and cannot establish current
        # directory exhaustiveness, even though originals can finish their GETs.
        before = calls.count('https://issuer.example/annuals')
        with patch('uteki.infrastructure.document_sources.company_acquisition.socket.getaddrinfo',
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
             patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener', return_value=Opener()), \
             patch('uteki.infrastructure.document_sources.company_acquisition.time.sleep'):
            fourth = acquire_annual_package(profile, output=self.root/'frozen', resume_verification=parent,
                                           resume_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
                                           use_frozen_directories=True, **kwargs)
        self.assertEqual(calls.count('https://issuer.example/annuals'), before)
        self.assertTrue(all(m['remote_repeat_complete'] for m in fourth['materials']))
        self.assertFalse(fourth['current_directory_discovery_complete'])
        self.assertTrue(any(g['reason'] == 'current_directory_discovery_unverified' for g in fourth['gaps']))

    def test_resume_inherits_original_http_observations_without_refetching_unchanged_files(self):
        profile, responses, base = self.fixture()
        calls = []
        class Response:
            status = 200
            def __init__(self, url):
                self.url, self.raw = url, responses[url]
                self.headers = {'Content-Length': str(len(self.raw)), 'Content-Type': 'application/octet-stream'}
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, cap): return self.raw[:cap]
        class Opener:
            def open(self, req, timeout):
                calls.append(req.full_url)
                return Response(req.full_url)
        # A mocked transport exercises HTTP metadata contracts; no network is used.
        patches = [patch('uteki.infrastructure.document_sources.company_acquisition.socket.getaddrinfo',
                         return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]),
                   patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener', return_value=Opener()),
                   patch('uteki.infrastructure.document_sources.company_acquisition.time.sleep')]
        with patches[0], patches[1], patches[2]:
            first = acquire_annual_package(profile, company='OTHER', fiscal_year=2024,
                report_period_end='2024-12-31', as_of='2025-06-30', workspace=self.root/'store',
                output=self.root/'first', sec_user_agent='Offline fixture@example.test')
            parent = self.root/'first/verification.json'
            pin = hashlib.sha256(parent.read_bytes()).hexdigest()
            second = acquire_annual_package(profile, company='OTHER', fiscal_year=2024,
                report_period_end='2024-12-31', as_of='2025-06-30', workspace=self.root/'store',
                output=self.root/'second', sec_user_agent='Offline fixture@example.test',
                resume_verification=parent, resume_sha256=pin)
        self.assertEqual(second['reused_prior_materials'], first['expected_materials'])
        self.assertEqual(calls.count(base+'annual.htm'), 3)
        self.assertTrue(all(m['remote_repeat_complete'] for m in second['materials']))
        for old, new in zip(first['materials'], second['materials']):
            self.assertEqual(old['observations'], new['observations'])
            self.assertEqual(len(new['reuse_checks']), 3)
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            acquire_annual_package(profile, company='OTHER', fiscal_year=2024,
                report_period_end='2024-12-31', as_of='2025-06-30', workspace=self.root/'store',
                output=self.root/'bad-resume', sec_user_agent='Offline fixture@example.test',
                resume_verification=parent, resume_sha256='0'*64)
        self.assertFalse((self.root/'bad-resume').exists())


if __name__ == '__main__':
    unittest.main()
