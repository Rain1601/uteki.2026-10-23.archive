"""Public acquisition through urllib, with all network and waiting mocked."""
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import count
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError, URLError

from uteki.data_platform.cli import parse_args, run_acquire as cli_acquire


MODULE = 'uteki.data_platform.connectors.company_acquisition'
AUTO_LENGTH = object()


def synthetic_filing():
    """Independent transport fixture; no actual issuer or financial answer."""
    return b'''<!DOCTYPE html>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:dei="http://xbrl.sec.gov/dei/2024"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
<head><title>Transport Fixture Ltd - Annual report</title></head><body>
<ix:header><ix:resources><xbrli:context id="annual">
<xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000765432</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
</xbrli:context></ix:resources></ix:header>
<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="annual">0000765432</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentType" contextRef="annual">10-K</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="annual">2024-09-28</ix:nonNumeric>
<p>Synthetic transport example; no financial values.</p>
</body></html>'''


class Response:
    """Context-managed subset of a urllib HTTP response, including bounded read."""
    def __init__(self, raw, url, *, status=200, content_type='text/html; charset=utf-8',
                 content_length=AUTO_LENGTH):
        self.raw, self.url, self.status = raw, url, status
        self.headers = {'Content-Type': content_type}
        if content_length is not None:
            self.headers['Content-Length'] = str(len(raw) if content_length is AUTO_LENGTH else content_length)
        self.read_sizes, self.closed = [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.read_sizes.append(size)
        return self.raw[:size]


class AcquisitionTransportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.workspace = self.directory / 'workspace'
        self.config = {
            'symbol': 'TRNS', 'cik': '0000765432', 'market': 'NYSE', 'as_of': '2025-02-01',
            'sec_user_agent': 'TransportFixture contact@example.test',
            'filing_selection': {'mode': 'annual_filing_period', 'annual_form': '10-K',
                                 'report_period_end': '2024-09-28'},
            'source_policy': {'official': [], 'third_party': []},
            'document_validation': 'sec_inline_identity_v1', 'download_policy': 'revalidate',
            'limits': {'retries': 2, 'backoff_seconds': .25, 'timeout_seconds': 7},
        }
        self.submission_url = 'https://data.sec.gov/submissions/CIK0000765432.json'
        self.filing_url = 'https://www.sec.gov/Archives/edgar/data/765432/000076543224000037/transport-20240928.htm'
        self.raw = synthetic_filing()
        self.metadata = json.dumps({
            'cik': 765432, 'name': 'Transport Fixture Ltd', 'tickers': ['TRNS'], 'exchanges': ['NYSE'],
            'filings': {'recent': {'form': ['10-K'], 'filingDate': ['2024-11-18'],
                'reportDate': ['2024-09-28'], 'accessionNumber': ['0000765432-24-000037'],
                'primaryDocument': ['transport-20240928.htm']}, 'files': []},
        }).encode()

    def run_acquire(self, *, filing_outcomes=None, metadata_outcomes=None):
        routes = {
            self.submission_url: deque(metadata_outcomes if metadata_outcomes is not None else [
                Response(self.metadata, self.submission_url, content_type='application/json')]),
            self.filing_url: deque(filing_outcomes if filing_outcomes is not None else [
                Response(self.raw, self.filing_url)]),
        }
        self.calls = []

        def open_request(request, *, timeout):
            self.calls.append(request.full_url)
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(timeout, self.config['limits']['timeout_seconds'])
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers['user-agent'], self.config['sec_user_agent'])
            self.assertEqual(headers['accept-encoding'], 'identity')
            self.assertIn(request.full_url, routes, 'Unexpected discovery or download URL')
            self.assertTrue(routes[request.full_url], 'Unexpected retry after the scripted outcome')
            outcome = routes[request.full_url].popleft()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        opener = Mock()
        opener.open.side_effect = open_request
        config_path = self.directory / 'source-config.json'
        config_path.write_text(json.dumps(self.config))
        args = parse_args(['acquire', '--config', str(config_path), '--workspace', str(self.workspace),
                           '--sec-user-agent', self.config['sec_user_agent']])
        with ExitStack() as stack:
            # Even accidental unmocked HTTP may not establish a real connection.
            guard = stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('Real network forbidden')))
            dns = stack.enter_context(patch(MODULE + '.socket.getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 443))]))
            stack.enter_context(patch(MODULE + '.urllib.request.build_opener', return_value=opener))
            stack.enter_context(patch(MODULE + '.time.monotonic', side_effect=count(100., 1.)))
            current = [datetime(2026, 10, 4, tzinfo=timezone.utc)]
            stack.enter_context(patch(MODULE + '._utc_now', side_effect=lambda: current[0]))
            def advance(seconds):
                current[0] += timedelta(seconds=seconds)
            self.sleep = stack.enter_context(patch(MODULE + '.time.sleep', side_effect=advance))
            result = cli_acquire(args)  # No injected fetch: exercise the urllib branch.
            guard.assert_not_called()
            self.assertGreater(dns.call_count, 0)
        return result

    def filing_events(self, report):
        return [entry for entry in report['discovery'] if entry['source_url'] == self.filing_url]

    def assert_no_published_filing(self, report):
        self.assertEqual(report['documents'], [])
        self.assertEqual(report['status'], 'completed_with_gaps')
        self.assertFalse(list((self.workspace / 'source-runs').glob('*/receipts/*.json')))
        object_path = self.workspace / 'sources/objects' / (hashlib.sha256(self.raw).hexdigest() + '.bin')
        self.assertFalse(object_path.exists())

    def test_success_records_http_metadata_received_bytes_and_immutable_receipt(self):
        final_url = self.filing_url + '?delivery=fixture'
        response = Response(self.raw, final_url)
        result = self.run_acquire(filing_outcomes=[response])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(self.calls, [self.submission_url, self.filing_url])
        doc = result['documents'][0]
        expected = {'transport': 'http', 'http_status': 200, 'final_url': final_url,
                    'content_type': 'text/html; charset=utf-8', 'content_length': str(len(self.raw)),
                    'bytes_received': len(self.raw)}
        for key, value in expected.items():
            self.assertEqual(doc['transport'][key], value)
            self.assertEqual(self.filing_events(result)[0][key], value)
        self.assertTrue(doc['transport']['retrieved_at'])
        self.assertEqual(doc['validation']['status'], 'identity_validated')
        self.assertEqual((self.workspace / doc['path']).read_bytes(), self.raw)
        receipts = list((self.workspace / 'source-runs').glob('*/receipts/*.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['document']['transport'], doc['transport'])
        self.assertTrue(response.closed)
        self.assertEqual(len(response.read_sizes), 1)
        self.assertGreater(response.read_sizes[0], len(self.raw))

    def test_complete_response_without_content_length_is_accepted(self):
        response = Response(self.raw, self.filing_url, content_length=None)
        result = self.run_acquire(filing_outcomes=[response])
        self.assertEqual(result['status'], 'completed')
        self.assertIsNone(result['documents'][0]['transport']['content_length'])
        self.assertEqual(result['documents'][0]['transport']['bytes_received'], len(self.raw))
        self.assertTrue(response.closed)

    def test_http_206_is_rejected_without_reading_publishing_or_retrying(self):
        response = Response(self.raw, self.filing_url, status=206)
        result = self.run_acquire(filing_outcomes=[response])
        self.assert_no_published_filing(result)
        self.assertEqual(self.calls.count(self.filing_url), 1)
        self.assertEqual(self.filing_events(result)[0]['http_status'], 206)
        self.assertEqual(self.filing_events(result)[0]['reason'], 'unexpected_http_status')
        self.assertEqual(response.read_sizes, [])
        self.assertTrue(response.closed)
        self.sleep.assert_not_called()

    def test_content_length_larger_or_smaller_than_received_body_is_rejected(self):
        for length in (len(self.raw) - 1, len(self.raw) + 1):
            with self.subTest(content_length=length):
                response = Response(self.raw, self.filing_url, content_length=length)
                result = self.run_acquire(filing_outcomes=[response])
                self.assert_no_published_filing(result)
                self.assertEqual(self.calls.count(self.filing_url), 1)
                self.assertEqual(self.filing_events(result)[0]['reason'], 'content_length_mismatch')
                self.assertTrue(response.closed)
                self.sleep.assert_not_called()

    def test_http_403_retains_discovery_and_marks_download_blocked_without_retry(self):
        denied = HTTPError(self.filing_url, 403, 'Forbidden', {}, None)
        result = self.run_acquire(filing_outcomes=[denied])
        self.assert_no_published_filing(result)
        self.assertEqual(self.calls, [self.submission_url, self.filing_url])
        self.assertTrue(result['filing_catalog']['selection_discovery_complete'])
        self.assertEqual(result['selected_filings'][0]['status'], 'access_blocked')
        self.assertEqual(result['selected_filings'][0]['http_status'], 403)
        self.assertEqual(self.filing_events(result)[0]['http_status'], 403)
        self.sleep.assert_not_called()

    def test_http_429_retries_are_bounded_and_do_not_publish_after_exhaustion(self):
        errors = [HTTPError(self.filing_url, 429, 'Too Many Requests', {}, None) for _ in range(3)]
        result = self.run_acquire(filing_outcomes=errors)
        self.assert_no_published_filing(result)
        self.assertEqual(result['requests'], 4)
        self.assertEqual(self.calls.count(self.filing_url), 3)
        self.assertEqual([row['attempt'] for row in self.filing_events(result)], [1, 2, 3])
        self.assertTrue(all(row['http_status'] == 429 for row in self.filing_events(result)))
        self.assertEqual(self.sleep.call_args_list, [call(.25), call(.5)])

    def test_retry_after_seconds_takes_precedence_over_shorter_backoff(self):
        limited = HTTPError(self.filing_url, 429, 'Too Many Requests', {'Retry-After': '2'}, None)
        result = self.run_acquire(filing_outcomes=[limited, Response(self.raw, self.filing_url)])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.calls.count(self.filing_url), 2)
        self.assertEqual(result['requests'], 3)
        events = self.filing_events(result)
        self.assertEqual([event['status'] for event in events], ['failed', 'fetched'])
        self.assertEqual(events[0]['http_status'], 429)
        self.assertEqual(events[0]['retry_after_seconds'], 2)
        self.assertFalse(events[0].get('retry_deferred', False))
        self.sleep.assert_called_once_with(2)

    def test_retry_after_over_sixty_seconds_defers_without_waiting_or_repeating_request(self):
        limited = HTTPError(self.filing_url, 429, 'Too Many Requests', {'Retry-After': '61'}, None)
        result = self.run_acquire(filing_outcomes=[limited])
        self.assert_no_published_filing(result)
        self.assertEqual(self.calls, [self.submission_url, self.filing_url])
        self.assertEqual(result['requests'], 2)
        events = self.filing_events(result)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['http_status'], 429)
        self.assertEqual(events[0]['attempt'], 1)
        self.assertEqual(events[0]['retry_after_seconds'], 61)
        self.assertTrue(events[0]['retry_deferred'])
        self.sleep.assert_not_called()

    def test_network_timeouts_are_bounded_including_urllib_wrapped_timeout(self):
        for error_type in ('direct', 'wrapped'):
            with self.subTest(error_type=error_type):
                errors = [TimeoutError('synthetic timeout') for _ in range(3)]
                if error_type == 'wrapped':
                    errors = [URLError(error) for error in errors]
                result = self.run_acquire(filing_outcomes=errors)
                self.assert_no_published_filing(result)
                self.assertEqual(self.calls.count(self.filing_url), 3)
                self.assertEqual(result['requests'], 4)
                self.assertEqual(self.sleep.call_args_list, [call(.25), call(.5)])

    def test_transient_429_then_timeout_then_success_records_each_attempt(self):
        outcomes = [HTTPError(self.filing_url, 429, 'Too Many Requests', {}, None),
                    TimeoutError('synthetic timeout'), Response(self.raw, self.filing_url)]
        result = self.run_acquire(filing_outcomes=outcomes)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([row['status'] for row in self.filing_events(result)], ['failed', 'failed', 'fetched'])
        self.assertEqual(self.filing_events(result)[-1]['attempt'], 3)
        self.assertEqual(result['documents'][0]['transport']['http_status'], 200)
        self.assertEqual(result['documents'][0]['transport']['bytes_received'], len(self.raw))
        self.assertEqual(self.sleep.call_args_list, [call(.25), call(.5)])

    def test_shared_request_budget_limits_retries_before_another_http_call(self):
        self.config['limits']['max_requests'] = 2
        result = self.run_acquire(filing_outcomes=[TimeoutError('synthetic timeout')])
        self.assert_no_published_filing(result)
        self.assertEqual(self.calls, [self.submission_url, self.filing_url])
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['selected_filings'][0]['reason'], 'request_limit')


if __name__ == '__main__':
    unittest.main()
