#!/usr/bin/env python3
"""Offline transport/identity checks using fake HTTP connections, never sockets."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import io
import socket
import unittest
from unittest.mock import Mock, patch

import import_company_brand as brand


class FakeResponse:
    def __init__(self, status=200, data=b"ok", headers=None):
        self.status = status
        self._data = io.BytesIO(data)
        self._headers = {key.lower(): value for key, value in (headers or {}).items()}
        self.fp = None

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read1(self, count):
        return self._data.read(count)


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.sock = None
        self.closed = False

    def request(self, method, path, headers):
        self.requests.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class TransportContractTests(unittest.TestCase):
    def download(self, response, *, before_request=None):
        connection = FakeConnection(response)
        with patch.object(brand, "public_addresses", return_value=["93.184.216.34"]), \
             patch.object(brand, "PinnedHTTPSConnection", return_value=connection):
            try:
                return brand.fetch_public("https://a.example/", 1024, before_request=before_request)
            finally:
                self.assertTrue(connection.closed)

    def test_retryable_http_statuses_remain_machine_readable(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status), self.assertRaises(brand.FetchError) as caught:
                self.download(FakeResponse(status=status))
            self.assertTrue(caught.exception.retryable)
            self.assertIn(str(status), str(caught.exception))

    def test_nonretryable_http_statuses_do_not_become_transient_failures(self):
        for status in (400, 401, 403, 404, 410):
            with self.subTest(status=status), self.assertRaises(brand.FetchError) as caught:
                self.download(FakeResponse(status=status))
            self.assertFalse(caught.exception.retryable)

    def test_429_numeric_retry_after_is_preserved_as_seconds(self):
        with self.assertRaises(brand.FetchError) as caught:
            self.download(FakeResponse(status=429, headers={"Retry-After": "17"}))
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, 17)

    def test_http_date_retry_after_is_parsed_and_invalid_values_are_absent(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        seconds = brand.retry_after_seconds(format_datetime(future, usegmt=True))
        self.assertGreater(seconds, 3595)
        self.assertLessEqual(seconds, 3600)
        self.assertEqual(brand.retry_after_seconds("Mon, 01 Jan 1990 00:00:00 GMT"), 0)
        self.assertIsNone(brand.retry_after_seconds("not-a-delay"))
        self.assertIsNone(brand.retry_after_seconds(None))

    def test_request_hook_is_called_for_each_redirect_hop(self):
        first = FakeConnection(FakeResponse(status=302, headers={"Location": "https://www.a.example/icon.png"}))
        second = FakeConnection(FakeResponse(data=b"image", headers={"Content-Type": "image/png", "Content-Length": "5"}))
        hook = Mock()
        with patch.object(brand, "public_addresses", return_value=["93.184.216.34"]) as addresses, \
             patch.object(brand, "PinnedHTTPSConnection", side_effect=[first, second]):
            data, final_url, mime = brand.fetch_public("https://a.example/", 1024, before_request=hook)
        self.assertEqual([call.args[0] for call in hook.call_args_list],
                         ["https://a.example/", "https://www.a.example/icon.png"])
        self.assertEqual([call.args[0] for call in addresses.call_args_list], ["a.example", "www.a.example"])
        self.assertEqual((data, final_url, mime), (b"image", "https://www.a.example/icon.png", "image/png"))
        self.assertTrue(first.closed and second.closed)

    def test_private_ip_redirect_is_rejected_before_another_connection(self):
        first = FakeConnection(FakeResponse(status=302, headers={"Location": "https://127.0.0.1/icon.png"}))
        with patch.object(brand, "public_addresses", return_value=["93.184.216.34"]) as addresses, \
             patch.object(brand, "PinnedHTTPSConnection", return_value=first) as connection, \
             self.assertRaises(brand.BrandImportError):
            brand.fetch_public("https://a.example/", 1024)
        self.assertEqual(addresses.call_count, 1)
        self.assertEqual(connection.call_count, 1)
        self.assertTrue(first.closed)

    def test_redirect_target_dns_is_revalidated_and_private_answer_is_rejected(self):
        first = FakeConnection(FakeResponse(status=302, headers={"Location": "https://internal.example/icon.png"}))
        def resolve(host, *args, **kwargs):
            address = "93.184.216.34" if host == "a.example" else "10.0.0.5"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
        with patch.object(brand.socket, "getaddrinfo", side_effect=resolve) as resolver, \
             patch.object(brand, "PinnedHTTPSConnection", return_value=first) as connection, \
             self.assertRaises(brand.BrandImportError):
            brand.fetch_public("https://a.example/", 1024)
        self.assertEqual([call.args[0] for call in resolver.call_args_list], ["a.example", "internal.example"])
        self.assertEqual(connection.call_count, 1)
        self.assertTrue(first.closed)

    def test_mixed_public_private_dns_answers_are_rejected(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 443))]
        with patch.object(brand.socket, "getaddrinfo", return_value=answers), \
             self.assertRaises(brand.BrandImportError):
            brand.public_addresses("mixed.example")

    def test_transport_error_is_retryable_and_connection_is_closed(self):
        connection = FakeConnection(FakeResponse())
        connection.request = Mock(side_effect=TimeoutError("synthetic timeout"))
        with patch.object(brand, "public_addresses", return_value=["93.184.216.34"]), \
             patch.object(brand, "PinnedHTTPSConnection", return_value=connection), \
             self.assertRaises(brand.FetchError) as caught:
            brand.fetch_public("https://a.example/", 1024)
        self.assertTrue(caught.exception.retryable)
        self.assertTrue(connection.closed)

    def test_truncated_response_is_retryable(self):
        with self.assertRaises(brand.FetchError) as caught:
            self.download(FakeResponse(data=b"small", headers={"Content-Length": "10"}))
        self.assertTrue(caught.exception.retryable)

    def test_download_byte_cap_is_enforced_with_or_without_content_length(self):
        for headers in ({}, {"Content-Length": "1025"}):
            with self.subTest(headers=headers), self.assertRaises(brand.BrandImportError):
                self.download(FakeResponse(data=b"x" * 1025, headers=headers))

    def test_cross_domain_homepage_redirect_requires_review_before_icon_download(self):
        fetcher = Mock(return_value=(b'<link rel="icon" href="/icon.png">',
                                     "https://different.example/", "text/html"))
        with self.assertRaises(brand.IdentityReviewRequired):
            brand.prepare_brand("https://a.example", fetcher=fetcher)
        self.assertEqual(fetcher.call_count, 1)

    def test_subdomain_homepage_redirect_is_not_implicitly_the_same_company(self):
        fetcher = Mock(return_value=(b'<link rel="icon" href="/icon.png">',
                                     "https://investors.a.example/", "text/html"))
        with self.assertRaises(brand.IdentityReviewRequired):
            brand.prepare_brand("https://a.example", fetcher=fetcher)
        self.assertEqual(fetcher.call_count, 1)


if __name__ == "__main__":
    unittest.main()
