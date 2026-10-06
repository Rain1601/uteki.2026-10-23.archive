"""Offline contract/security tests; examples are synthetic and not logo providers."""

import contextlib
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

import import_company_brand as brand


def png(pixel=b"\x00\x50\x80\xff", width=1, height=1):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\x00" + pixel * width) * height)) + chunk(b"IEND", b"")


class BrandImportTests(unittest.TestCase):
    def test_origin_normalization_without_company_defaults(self):
        self.assertEqual(brand.normalize_website("https://WWW.Example.COM:443/"), ("example.com", "https://www.example.com/"))
        self.assertEqual(brand.normalize_website("https://issuer.example.org"), ("issuer.example.org", "https://issuer.example.org/"))
        for invalid in ("", "example.com", "http://example.com", "https://example.com/path", "https://example.com?q=x", "https://example.com/#x", "https://8.8.8.8"):
            with self.subTest(invalid=invalid), self.assertRaises(brand.BrandImportError):
                brand.normalize_website(invalid)

    def test_reject_credentials_private_ip_localhost_and_non_https(self):
        for value in ("https://user:secret@example.com/logo.png", "https://127.0.0.1/logo.png", "https://10.0.0.1/x", "https://224.0.0.1/x", "https://[::1]/x", "https://localhost/x", "https://example.com:8443/x", "file:///tmp/logo.png", "http://example.com/x", "https://example.com\\@evil.example/x", "https://example.com/\nHost:x"):
            with self.subTest(value=value), self.assertRaises(brand.BrandImportError):
                brand.https_url(value)

    def test_dns_mixed_public_private_is_rejected(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("8.8.8.8", "127.0.0.1")]
        with patch.object(socket, "getaddrinfo", return_value=records), self.assertRaises(brand.BrandImportError):
            brand.public_addresses("cdn.example.com")

    def test_dns_resolution_is_time_bounded(self):
        release = threading.Event()
        def stalled_resolver(*args, **kwargs):
            release.wait(1)
            return []
        try:
            with patch.object(socket, "getaddrinfo", side_effect=stalled_resolver), self.assertRaisesRegex(brand.BrandImportError, "DNS resolution exceeded"):
                brand.public_addresses("cdn.example.com", timeout=0.01)
        finally:
            release.set()

    def test_discovery_prefers_large_icons_resolves_relative_and_ignores_social_image(self):
        html = b'''<meta property="og:image" content="https://example.com/social.png">
          <link rel="shortcut icon" href="/small.ico" sizes="16x16">
          <link rel="apple-touch-icon" href="touch.png" sizes="180x180">
          <link rel="icon" href="//cdn.example.com/logo.png" sizes="192x192">
          <link rel="icon" href="http://example.com/insecure.png" sizes="999x999">'''
        urls = brand.discover_icons(html, "https://example.com/section/")
        self.assertEqual(urls[:2], ["https://cdn.example.com/logo.png", "https://example.com/section/touch.png"])
        self.assertEqual(urls[-1], "https://example.com/favicon.ico")
        self.assertFalse(any("social" in url or "insecure" in url for url in urls))

    def test_image_magic_rejects_html_and_svg_even_with_image_extension(self):
        self.assertEqual(brand.image_type(png()), ("png", "image/png"))
        for data in (b"<html>Not a PNG</html>", b'<svg><script>alert(1)</script></svg>', b"\x89PNG\r\n\x1a\n", png()[:-8]):
            with self.subTest(data=data[:16]), self.assertRaises(brand.BrandImportError):
                brand.image_type(data)

    def test_independent_domains_preserve_other_entries_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            calls = []
            def fetcher(url, limit):
                calls.append(url)
                if url.endswith("/"):
                    return b'<link rel="apple-touch-icon" sizes="180x180" href="/brand.png">', url, "text/html"
                return png(b"\xff\x00\x00\xff" if "second" in url else b"\x00\xff\x00\xff"), url, "image/png"
            first = brand.import_brand("https://www.first.example", registry, fetcher=fetcher)
            second = brand.import_brand("https://second.example", registry, fetcher=fetcher)
            stored = json.loads(registry.read_text())
            self.assertEqual(set(stored["brands"]), {"first.example", "second.example"})
            self.assertEqual(stored["brands"]["first.example"], first)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(second["kind"], "official-site-icon")
            self.assertEqual(second["presentation"], "icon")
            self.assertEqual(second["website"], "https://second.example/")
            self.assertEqual(second["assetUrl"], "https://second.example/brand.png")
            self.assertEqual(second["mimeType"], "image/png")
            self.assertTrue((registry.parent / Path(second["src"]).name).exists())
            self.assertEqual(len(calls), 4)

    def test_failed_download_preserves_existing_registry_and_files(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            original = b'{"version":1,"brands":{"example.com":{"src":"old.png"}}}\n'
            registry.write_bytes(original)
            def fetcher(url, limit):
                raise brand.BrandImportError("Network unavailable")
            with self.assertRaises(brand.BrandImportError):
                brand.import_brand("https://example.com", registry, asset_url="https://example.com/logo.png", source_page="https://example.com/press", fetcher=fetcher)
            self.assertEqual(registry.read_bytes(), original)
            self.assertEqual(list(registry.parent.iterdir()), [registry])

    def test_automatic_discovery_never_downgrades_reviewed_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            reviewed = {"src": "./assets/companies/reviewed.png", "kind": "reviewed-logo"}
            original = json.dumps({"version": 1, "brands": {"example.com": reviewed}}).encode()
            registry.write_bytes(original)
            def forbidden_fetch(*args):
                self.fail("A reviewed logo must be preserved without automatic fetch")
            result = brand.import_brand("https://www.example.com", registry, fetcher=forbidden_fetch)
            self.assertEqual(result, reviewed)
            self.assertEqual(registry.read_bytes(), original)

    def test_html_masquerading_as_image_does_not_mutate_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            with self.assertRaises(brand.BrandImportError):
                brand.import_brand("https://third.example", registry, asset_url="https://third.example/logo.png", source_page="https://third.example/press", fetcher=lambda url, limit: (b"<html>Login required</html>", url, "image/png"))
            self.assertFalse(registry.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_manual_asset_requires_source_and_bypasses_homepage(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            calls = []
            def fetcher(url, limit):
                calls.append(url)
                return png(), url, "application/octet-stream"
            with self.assertRaises(brand.BrandImportError):
                brand.import_brand("https://third.example", registry, asset_url="https://cdn.third.example/logo.png", fetcher=fetcher)
            self.assertEqual(calls, [])
            result = brand.import_brand("https://third.example", registry, asset_url="https://cdn.third.example/logo.png", source_page="https://third.example/press", fetcher=fetcher)
            self.assertEqual(calls, ["https://cdn.third.example/logo.png"])
            self.assertEqual(result["kind"], "reviewed-logo")
            self.assertEqual(result["presentation"], "wordmark")
            self.assertEqual(result["sourcePage"], "https://third.example/press")

    def test_compact_manual_asset_requires_explicit_icon_presentation(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = brand.import_brand("https://compact.example", Path(directory) / "registry.json", asset_url="https://compact.example/icon.png", source_page="https://compact.example/press", presentation="icon", fetcher=lambda url, limit: (png(width=32, height=32), url, "image/png"))
            self.assertEqual(entry["presentation"], "icon")
            self.assertEqual(entry["kind"], "reviewed-logo")

    def test_wide_and_tall_icon_rejected_without_registry_mutation(self):
        for width, height in ((90, 20), (20, 90)):
            with self.subTest(width=width, height=height), tempfile.TemporaryDirectory() as directory:
                registry = Path(directory) / "registry.json"
                original = b'{"version":1,"brands":{"shape.example":{"kind":"reviewed-logo","presentation":"icon","src":"old.png"}}}'
                registry.write_bytes(original)
                with self.assertRaisesRegex(brand.BrandImportError, "Icon aspect ratio rejected"):
                    brand.import_brand("https://shape.example", registry, asset_url="https://shape.example/logo.png", source_page="https://shape.example/press", presentation="icon", fetcher=lambda url, limit: (png(width=width, height=height), url, "image/png"))
                self.assertEqual(registry.read_bytes(), original)
                self.assertEqual(list(registry.parent.iterdir()), [registry])

    def test_wide_reviewed_wordmark_allowed_but_not_promoted_to_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = brand.import_brand("https://wordmark.example", Path(directory) / "registry.json", asset_url="https://wordmark.example/logo.png", source_page="https://wordmark.example/press", fetcher=lambda url, limit: (png(width=90, height=20), url, "image/png"))
            self.assertEqual(entry["presentation"], "wordmark")

    def test_discovered_wide_icon_skipped_for_square_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            def fetcher(url, limit):
                if url.endswith("/"):
                    return b'<link rel="icon" sizes="256x256" href="/wide.png"><link rel="icon" sizes="128x128" href="/square.png">', url, "text/html"
                return png(width=80, height=20) if "wide" in url else png(width=32, height=32), url, "image/png"
            entry = brand.import_brand("https://fallback.example", Path(directory) / "registry.json", fetcher=fetcher)
            self.assertEqual(entry["assetUrl"], "https://fallback.example/square.png")
            self.assertEqual(entry["presentation"], "icon")

    def test_dimensions_read_standard_raster_headers(self):
        # Header fixtures isolate dimension parsing; they do not claim full
        # image decoder verification for synthetic JPEG/WebP payloads.
        jpeg = b"\xff\xd8\xff\xe0\x00\x04xx\xff\xc0\x00\x0b\x08" + struct.pack(">HH", 60, 80) + b"\x01\x01\x11\x00\xff\xd9"
        self.assertEqual(brand.image_dimensions(jpeg, "jpg"), (80, 60))
        payload = png(width=32, height=32)
        ico = b"\x00\x00\x01\x00\x01\x00" + bytes((32, 32, 0, 0)) + struct.pack("<HHII", 1, 32, len(payload), 22) + payload
        self.assertEqual(brand.image_dimensions(ico, "ico"), (32, 32))
        def webp(kind, payload):
            chunk = kind + struct.pack("<I", len(payload)) + payload
            if len(payload) % 2:
                chunk += b"\x00"
            return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
        extended = webp(b"VP8X", b"\x00" * 4 + (79).to_bytes(3, "little") + (59).to_bytes(3, "little"))
        lossless = webp(b"VP8L", b"\x2f" + (79 | (59 << 14)).to_bytes(4, "little"))
        lossy = webp(b"VP8 ", b"\x00" * 3 + b"\x9d\x01\x2a" + struct.pack("<HH", 80, 60))
        for data in (extended, lossless, lossy):
            with self.subTest(kind=data[12:16]):
                self.assertEqual(brand.image_dimensions(data, "webp"), (80, 60))
        self.assertEqual(brand.image_dimensions(png(width=80, height=60), "png"), (80, 60))

    def test_unreadable_icon_dimensions_report_explicit_gap(self):
        unmeasurable_jpeg = b"\xff\xd8\xff\xfe\x00\x0cmissingSOF\xff\xd9"
        self.assertEqual(brand.image_type(unmeasurable_jpeg)[0], "jpg")
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            with self.assertRaisesRegex(brand.BrandImportError, "Cannot reliably read image dimensions"):
                brand.import_brand("https://unknown.example", registry, asset_url="https://unknown.example/logo.jpg", source_page="https://unknown.example/press", presentation="icon", fetcher=lambda url, limit: (unmeasurable_jpeg, url, "image/jpeg"))
            self.assertFalse(registry.exists())

    def test_automatic_wordmark_presentation_and_unknown_value_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for presentation in ("wordmark", "automatic"):
                with self.subTest(presentation=presentation), self.assertRaises(brand.BrandImportError):
                    brand.import_brand("https://unknown.example", Path(directory) / "registry.json", presentation=presentation, fetcher=lambda *args: self.fail("Validation must happen before fetch"))

    def test_invalid_candidate_falls_back_to_next_discovered_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            def fetcher(url, limit):
                if url.endswith("/"):
                    return b'<link rel="icon" sizes="256x256" href="/bad.png"><link rel="icon" sizes="128x128" href="/good.png">', url, "text/html"
                return (b"<html>oops</html>" if "bad" in url else png()), url, "image/png"
            entry = brand.import_brand("https://fourth.example", Path(directory) / "registry.json", fetcher=fetcher)
            self.assertEqual(entry["assetUrl"], "https://fourth.example/good.png")

    def test_redirect_to_private_dns_never_connects_to_it(self):
        class Response:
            status = 302
            def getheader(self, name, default=None):
                return "https://private.example/logo.png" if name == "Location" else default
        class Connection:
            hosts = []
            def __init__(self, host, address, timeout):
                self.hosts.append(host)
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        def resolve(host, *args, **kwargs):
            ip = "127.0.0.1" if host == "private.example" else "8.8.8.8"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
        with patch.object(socket, "getaddrinfo", side_effect=resolve), patch.object(brand, "PinnedHTTPSConnection", Connection), self.assertRaises(brand.BrandImportError):
            brand.fetch_public("https://public.example/logo.png", 1000)
        self.assertEqual(Connection.hosts, ["public.example"])

    def test_missing_cli_website_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            brand.main([])
        self.assertEqual(failure.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
