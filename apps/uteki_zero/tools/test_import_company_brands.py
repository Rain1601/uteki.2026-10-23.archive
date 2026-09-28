#!/usr/bin/env python3
"""Offline contract tests for the explicit-scope batch company icon importer.

The companies, markets and domains below are deliberately synthetic. Passing
these tests establishes import/control behavior, never corporate brand review.
Run: python3 -m unittest discover -s apps/uteki_zero/tools -p 'test_*.py' -v
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

import import_company_brand as single
import import_company_brands as batch


def png(red: int = 37, *, width: int = 1, height: int = 1) -> bytes:
    """Produce an actual tiny PNG, including CRCs; no network/file fixtures."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + bytes([red, 71, 109]) * width) * height))
            + chunk(b"IEND", b""))


PNG = png()
OTHER_PNG = png(199)


def company(entity="issuer-a", exchange="XAAA", ticker="AAA", website="https://a.example"):
    return {"entityId": entity, "exchange": exchange, "ticker": ticker, "website": website}


class FixtureFetcher:
    """A request-aware fetch double, including redirect and retry fixtures.

    Every simulated HTTP hop calls the same hook as fetch_public. This matters:
    limiting only prepare_brand calls would not limit homepage/icon/redirect
    requests and must not satisfy the rate-limit tests.
    """

    def __init__(self, *, payload=PNG, delay=0.0):
        self.payload = payload
        self.delay = delay
        self.routes = {}
        self.calls = []
        self.events = []
        self.active = 0
        self.peak_active = 0
        self._lock = threading.Lock()

    def add(self, url, *responses):
        self.routes[url] = list(responses)
        return self

    def __call__(self, url, max_bytes, *, before_request=None):
        if before_request is not None:
            before_request(url)
        with self._lock:
            self.calls.append(url)
            self.events.append((url, time.monotonic()))
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            responses = self.routes.get(url)
            response = responses.pop(0) if responses and len(responses) > 1 else (responses[0] if responses else None)
        try:
            if self.delay:
                time.sleep(self.delay)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response(url, max_bytes, before_request)
            if response is not None:
                data, final_url, mime = response
                if len(data) > max_bytes:
                    raise single.BrandImportError("Synthetic response exceeds byte limit")
                return data, final_url, mime
            if url.endswith("/"):
                return b'<html><link rel="icon" href="/icon.png"></html>', url, "text/html"
            if url.endswith(("/icon.png", "/favicon.ico")):
                return self.payload, url, "image/png"
            raise AssertionError(f"Unexpected synthetic request: {url}")
        finally:
            with self._lock:
                self.active -= 1


class FakeClock:
    """Advance scheduling time on sleep without waiting or spinning."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []
        self.lock = threading.Lock()

    def monotonic(self):
        with self.lock:
            return self.now

    def sleep(self, seconds):
        with self.lock:
            self.sleeps.append(seconds)
            self.now += seconds


class BatchContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uteki-brands-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "companies.json"
        self.registry = self.root / "assets" / "companies" / "registry.json"
        self.state = self.root / "checkpoint.json"
        self.fetcher = FixtureFetcher()

    def write_manifest(self, companies=None, *, scope=None):
        value = {"version": 1,
                 "scope": scope if scope is not None else {"id": "synthetic-v1", "markets": ["XAAA", "XBBB"]},
                 "companies": companies if companies is not None else [company()]}
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        return value

    def run_batch(self, *, fetcher=None, **kwargs):
        kwargs.setdefault("min_interval", 0)
        kwargs.setdefault("attempts", 1)
        return batch.run_batch(self.manifest, self.registry, self.state,
                               fetcher=fetcher if fetcher is not None else self.fetcher, **kwargs)

    def load_registry(self):
        return json.loads(self.registry.read_text(encoding="utf-8"))

    def store_entry(self, *, domain="a.example", kind="official-site-icon", data=PNG,
                    age_hours=0, write_asset=True, identity=None, presentation="icon"):
        digest = hashlib.sha256(data).hexdigest()
        entry = {"src": f"./assets/companies/{digest}.png",
                 "website": f"https://{domain}/", "sourcePage": f"https://{domain}/",
                 "assetUrl": f"https://{domain}/icon.png", "kind": kind,
                 "fetchedAt": (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat(),
                 "sha256": digest, "mimeType": "image/png"}
        if presentation is not None:
            entry["presentation"] = presentation
        if identity is not None:
            entry["identity"] = identity
        registry = self.load_registry() if self.registry.exists() else {"version": 1, "brands": {}}
        registry["brands"][domain] = entry
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        if write_asset:
            (self.registry.parent / f"{digest}.png").write_bytes(data)
        return entry

    def assert_statuses(self, report, statuses):
        self.assertEqual([r["status"] for r in report["results"]], statuses)
        self.assertEqual(report["summary"]["inputCount"], len(statuses))
        for status in set(statuses):
            self.assertEqual(report["summary"]["status"][status], statuses.count(status))

    def assert_no_network(self):
        self.assertEqual(self.fetcher.calls, [])

    def test_two_markets_same_ticker_do_not_merge_distinct_issuers(self):
        self.write_manifest([company(ticker="SHARED"),
                             company("issuer-b", "XBBB", "SHARED", "https://b.example")])
        report = self.run_batch()
        self.assert_statuses(report, ["success", "success"])
        self.assertEqual(report["summary"]["domainCount"], 2)
        self.assertEqual(set(self.load_registry()["brands"]), {"a.example", "b.example"})
        self.assertEqual(set(self.fetcher.calls), {"https://a.example/", "https://a.example/icon.png",
                                                 "https://b.example/", "https://b.example/icon.png"})
        self.assertTrue(all(r["brandReview"] == "pending" for r in report["results"]))
        self.assertTrue(all(entry["presentation"] == "icon" for entry in self.load_registry()["brands"].values()))

    def test_www_aliases_deduplicate_a_domain_and_preserve_listing_identity(self):
        self.write_manifest([company(), company(website="https://www.a.example"),
                             company(exchange="XBBB", ticker="AA", website="https://a.example")])
        report = self.run_batch()
        self.assert_statuses(report, ["success", "success", "success"])
        self.assertEqual(report["summary"]["domainCount"], 1)
        self.assertEqual(len(self.fetcher.calls), 2)
        self.assertEqual(report["results"][1]["duplicateOf"], 0)
        self.assertEqual(report["results"][2]["duplicateOf"], 0)
        identity = self.load_registry()["brands"]["a.example"]["identity"]
        self.assertEqual(identity["entityId"], "issuer-a")
        self.assertEqual({(x["exchange"], x["ticker"]) for x in identity["listings"]},
                         {("XAAA", "AAA"), ("XBBB", "AA")})

    def test_non_www_subdomain_remains_a_separate_identity(self):
        self.write_manifest([company(), company("issuer-ir", "XBBB", "IR", "https://ir.a.example")])
        report = self.run_batch()
        self.assert_statuses(report, ["success", "success"])
        self.assertEqual(set(self.load_registry()["brands"]), {"a.example", "ir.a.example"})
        self.assertEqual(len(self.fetcher.calls), 4)

    def test_missing_or_blank_required_identity_fields_are_reported_without_network(self):
        entries = []
        for key in ("entityId", "exchange", "ticker", "website"):
            missing = company()
            del missing[key]
            entries.append(missing)
            blank = company()
            blank[key] = "   "
            entries.append(blank)
        self.write_manifest(entries)
        report = self.run_batch()
        self.assert_statuses(report, ["invalid"] * len(entries))
        self.assertTrue(all(row["error"] for row in report["results"]))
        self.assert_no_network()

    def test_market_outside_explicit_scope_is_invalid(self):
        self.write_manifest([company(exchange="XOUT")])
        self.assert_statuses(self.run_batch(), ["invalid"])
        self.assert_no_network()

    def test_missing_scope_is_rejected_instead_of_selecting_a_market(self):
        value = self.write_manifest()
        del value["scope"]
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(single.BrandImportError):
            self.run_batch()
        self.assert_no_network()

    def test_invalid_website_is_not_replaced_by_another_company(self):
        entries = [company("bad-http", ticker="BAD1", website="http://bad.example"),
                   company("bad-path", ticker="BAD2", website="https://bad.example/investors"),
                   company("private", ticker="BAD3", website="https://127.0.0.1"),
                   company("good", ticker="OK", website="https://good.example")]
        self.write_manifest(entries)
        self.assert_statuses(self.run_batch(), ["invalid", "invalid", "invalid", "success"])
        self.assertEqual(set(self.load_registry()["brands"]), {"good.example"})
        self.assertTrue(all(url.startswith("https://good.example/") for url in self.fetcher.calls))

    def test_identity_conflicts_require_review_without_fetching(self):
        cases = {
            "one_entity_two_domains": [company(), company(website="https://other.example")],
            "one_listing_two_entities": [company(), company("other", website="https://other.example")],
            "one_domain_two_entities": [company(), company("other", "XBBB", "OTHER")],
        }
        for label, entries in cases.items():
            with self.subTest(label=label):
                self.state = self.root / f"{label}.json"
                self.write_manifest(entries)
                self.assert_statuses(self.run_batch(), ["needs_review", "needs_review"])
                self.assert_no_network()

    def test_existing_registry_identity_conflict_does_not_overwrite_asset(self):
        prior = self.store_entry(identity={"entityId": "different-issuer", "listings": [{"exchange": "XBBB", "ticker": "DIFF"}]})
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
        self.assert_no_network()

    def test_unrelated_malformed_registry_identity_does_not_crash_other_imports(self):
        prior = self.store_entry(domain="unrelated.example",
                                 identity={"entityId": "unrelated-issuer", "listings": None})
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["success"])
        self.assertEqual(self.load_registry()["brands"]["unrelated.example"], prior)
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_malformed_registry_identity_for_requested_entity_requires_review(self):
        prior = self.store_entry(domain="other.example",
                                 identity={"entityId": "issuer-a", "listings": None})
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["other.example"], prior)
        self.assert_no_network()

    def test_fresh_cache_requires_an_existing_file_with_matching_hash(self):
        self.store_entry()
        self.write_manifest()
        report = self.run_batch()
        self.assert_statuses(report, ["cached"])
        self.assertEqual(report["results"][0]["cache"], "fresh")
        self.assertEqual(report["results"][0]["brandReview"], "pending")
        self.assert_no_network()

    def test_tampered_cached_icon_is_refetched_and_saved_with_its_actual_hash(self):
        previous = self.store_entry()
        (self.registry.parent / Path(previous["src"]).name).write_bytes(b"tampered")
        self.write_manifest()
        self.fetcher.payload = OTHER_PNG
        self.assert_statuses(self.run_batch(), ["success"])
        entry = self.load_registry()["brands"]["a.example"]
        self.assertEqual(entry["sha256"], hashlib.sha256(OTHER_PNG).hexdigest())
        self.assertEqual((self.registry.parent / Path(entry["src"]).name).read_bytes(), OTHER_PNG)
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_missing_cached_icon_is_refetched(self):
        self.store_entry(write_asset=False)
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["success"])
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_legacy_automatic_icon_without_presentation_is_fetched_again(self):
        self.store_entry(presentation=None)
        self.write_manifest()
        self.fetcher.payload = OTHER_PNG
        self.assert_statuses(self.run_batch(), ["success"])
        entry = self.load_registry()["brands"]["a.example"]
        self.assertEqual(entry["presentation"], "icon")
        self.assertEqual(entry["sha256"], hashlib.sha256(OTHER_PNG).hexdigest())
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_png_bytes_with_unsupported_local_extension_are_not_accepted_as_cache(self):
        prior = self.store_entry()
        value = self.load_registry()
        invalid_src = f'./assets/companies/{prior["sha256"]}.txt'
        value["brands"]["a.example"]["src"] = invalid_src
        self.registry.write_text(json.dumps(value), encoding="utf-8")
        (self.registry.parent / Path(invalid_src).name).write_bytes(PNG)
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry(), value)
        self.assert_no_network()

    def test_completed_checkpoint_resumes_without_http_requests(self):
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["success"])
        second_fetcher = FixtureFetcher()
        report = self.run_batch(fetcher=second_fetcher)
        self.assert_statuses(report, ["cached"])
        self.assertEqual(report["results"][0]["cache"], "resumed")
        self.assertEqual(second_fetcher.calls, [])

    def test_resumed_checkpoint_does_not_hide_a_missing_local_asset(self):
        self.write_manifest()
        self.run_batch()
        entry = self.load_registry()["brands"]["a.example"]
        (self.registry.parent / Path(entry["src"]).name).unlink()
        second_fetcher = FixtureFetcher()
        self.assert_statuses(self.run_batch(fetcher=second_fetcher), ["success"])
        self.assertEqual(len(second_fetcher.calls), 2)

    def test_failed_checkpoint_is_visible_and_retry_failed_explicitly_retries(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 403", retryable=False))
        self.assert_statuses(self.run_batch(), ["failed"])
        second_fetcher = FixtureFetcher()
        self.assert_statuses(self.run_batch(fetcher=second_fetcher), ["failed"])
        self.assertEqual(second_fetcher.calls, [])
        self.assert_statuses(self.run_batch(fetcher=second_fetcher, retry_failed=True), ["success"])
        self.assertEqual(len(second_fetcher.calls), 2)

    def test_retry_failed_refresh_does_not_disguise_older_fresh_icon_as_success(self):
        self.store_entry()
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 403", retryable=False))
        self.assert_statuses(self.run_batch(refresh=True), ["failed"])
        second_fetcher = FixtureFetcher(payload=OTHER_PNG)
        self.assert_statuses(self.run_batch(fetcher=second_fetcher, retry_failed=True), ["success"])
        self.assertEqual(len(second_fetcher.calls), 2)
        self.assertEqual(self.load_registry()["brands"]["a.example"]["sha256"],
                         hashlib.sha256(OTHER_PNG).hexdigest())

    def test_changed_manifest_cannot_reuse_checkpoint_for_a_different_input(self):
        self.write_manifest()
        self.run_batch()
        previous = copy.deepcopy(self.load_registry())
        self.write_manifest([company(), company("issuer-b", "XBBB", "B", "https://b.example")])
        second_fetcher = FixtureFetcher()
        with self.assertRaises(single.BrandImportError):
            self.run_batch(fetcher=second_fetcher)
        self.assertEqual(second_fetcher.calls, [])
        self.assertEqual(self.load_registry(), previous)
        self.state = self.root / "new-input-checkpoint.json"
        self.assert_statuses(self.run_batch(fetcher=second_fetcher), ["cached", "success"])
        self.assertTrue(all("b.example" in url for url in second_fetcher.calls))

    def test_expired_cache_refresh_failure_remains_failure_and_preserves_previous_entry(self):
        prior = self.store_entry(age_hours=48)
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 403", retryable=False))
        report = self.run_batch(cache_max_age_hours=24)
        self.assert_statuses(report, ["failed"])
        self.assertEqual(report["results"][0]["cache"], "stale")
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)

    def test_reviewed_logo_never_downgrades_to_favicon_even_on_refresh(self):
        prior = self.store_entry(kind="reviewed-logo", age_hours=9999)
        self.write_manifest()
        report = self.run_batch(refresh=True, cache_max_age_hours=1)
        self.assert_statuses(report, ["cached"])
        self.assertEqual(report["results"][0]["cache"], "reviewed")
        self.assertEqual(report["results"][0]["brandReview"], "reviewed")
        current = self.load_registry()["brands"]["a.example"]
        for key, value in prior.items():
            self.assertEqual(current[key], value)
        self.assert_no_network()

    def test_reviewed_wordmark_requires_review_without_replacement_or_network(self):
        prior = self.store_entry(kind="reviewed-logo", presentation="wordmark", data=png(width=8, height=1))
        self.write_manifest()
        self.assert_statuses(self.run_batch(refresh=True), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
        self.assert_no_network()

    def test_reviewed_logo_without_presentation_cannot_be_inferred_from_square_ratio(self):
        prior = self.store_entry(kind="reviewed-logo", presentation=None)
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
        self.assert_no_network()

    def test_single_automatic_import_records_icon_presentation(self):
        result = single.import_brand("https://a.example", self.registry, fetcher=self.fetcher)
        self.assertEqual(result["kind"], "official-site-icon")
        self.assertEqual(result["presentation"], "icon")
        self.assertEqual(self.load_registry()["brands"]["a.example"]["presentation"], "icon")

    def test_single_reviewed_import_defaults_to_wordmark_and_accepts_wide_asset(self):
        data = png(width=8, height=1)
        self.fetcher.add("https://a.example/wordmark.png", (data, "https://a.example/wordmark.png", "image/png"))
        result = single.import_brand("https://a.example", self.registry,
                                     asset_url="https://a.example/wordmark.png",
                                     source_page="https://a.example/brand", fetcher=self.fetcher)
        self.assertEqual(result["kind"], "reviewed-logo")
        self.assertEqual(result["presentation"], "wordmark")
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())

    def test_single_explicit_icon_rejects_wide_or_tall_shape_without_changing_registry(self):
        prior = self.store_entry(kind="reviewed-logo")
        for width, height in ((8, 1), (1, 8)):
            with self.subTest(width=width, height=height):
                data = png(width=width, height=height)
                fetcher = FixtureFetcher()
                fetcher.add("https://a.example/replacement.png", (data, "https://a.example/replacement.png", "image/png"))
                with self.assertRaises(single.BrandImportError):
                    single.import_brand("https://a.example", self.registry,
                                        asset_url="https://a.example/replacement.png",
                                        source_page="https://a.example/brand", presentation="icon", fetcher=fetcher)
                self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
                self.assertFalse((self.registry.parent / (hashlib.sha256(data).hexdigest() + ".png")).exists())

    def test_missing_reviewed_logo_requires_review_and_is_not_counted_as_success(self):
        prior = self.store_entry(kind="reviewed-logo", write_asset=False)
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
        self.assert_no_network()

    def test_tampered_reviewed_logo_requires_review_without_favicon_replacement(self):
        prior = self.store_entry(kind="reviewed-logo")
        (self.registry.parent / Path(prior["src"]).name).write_bytes(OTHER_PNG)
        self.write_manifest()
        self.assert_statuses(self.run_batch(), ["needs_review"])
        self.assertEqual(self.load_registry()["brands"]["a.example"], prior)
        self.assert_no_network()

    def test_429_retry_after_is_observed_and_then_import_succeeds(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/",
                         single.FetchError("HTTP 429", retryable=True, retry_after=2),
                         (b'<link rel="icon" href="/icon.png">', "https://a.example/", "text/html"))
        clock = FakeClock()
        with patch.object(batch.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(batch.time, "sleep", side_effect=clock.sleep):
            report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["success"])
        self.assertEqual(report["results"][0]["attempts"], 2)
        self.assertEqual(self.fetcher.calls.count("https://a.example/"), 2)
        self.assertGreaterEqual(sum(clock.sleeps), 2)

    def test_asset_retry_does_not_repeat_homepage_or_cycle_to_other_icon_urls(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/icon.png",
                         single.FetchError("HTTP 429", retryable=True, retry_after=1),
                         (PNG, "https://a.example/icon.png", "image/png"))
        clock = FakeClock()
        with patch.object(batch.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(batch.time, "sleep", side_effect=clock.sleep):
            report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["success"])
        self.assertEqual(self.fetcher.calls, ["https://a.example/", "https://a.example/icon.png",
                                             "https://a.example/icon.png"])
        self.assertEqual(report["results"][0]["attempts"], 2)

    def test_excessive_retry_after_is_reported_without_early_retry(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 429", retryable=True, retry_after=3600))
        with patch.object(batch.time, "sleep") as sleep:
            report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["failed"])
        self.assertEqual(self.fetcher.calls, ["https://a.example/"])
        self.assertTrue(report["results"][0].get("retryAt"))
        self.assertEqual(sum(call.args[0] for call in sleep.call_args_list), 0)

    def test_checkpoint_retry_failed_still_respects_unexpired_server_retry_after(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 429", retryable=True, retry_after=3600))
        self.assert_statuses(self.run_batch(attempts=3), ["failed"])
        second_fetcher = FixtureFetcher()
        with patch.object(batch.time, "sleep") as sleep:
            report = self.run_batch(fetcher=second_fetcher, retry_failed=True, attempts=3)
        self.assert_statuses(report, ["failed"])
        self.assertTrue(report["results"][0].get("retryAt"))
        self.assertEqual(second_fetcher.calls, [])
        self.assertEqual(sleep.call_count, 0)

    def test_extreme_finite_retry_after_can_be_saved_and_resumed_without_overflow(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 429", retryable=True, retry_after=1e30))
        report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["failed"])
        report_path = self.root / "report.json"
        report_path.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["hostCooldowns"]["a.example"], "manual-clear-required")
        second_fetcher = FixtureFetcher()
        with patch.object(batch.time, "sleep") as sleep:
            resumed = self.run_batch(fetcher=second_fetcher, retry_failed=True, attempts=3)
        self.assert_statuses(resumed, ["failed"])
        self.assertEqual(resumed["summary"]["networkDomains"], 0)
        self.assertEqual(second_fetcher.calls, [])
        self.assertEqual(sleep.call_count, 0)
        report_path.write_text(json.dumps(resumed, allow_nan=False), encoding="utf-8")
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["hostCooldowns"]["a.example"], "manual-clear-required")

    def test_403_is_not_retried(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 403", retryable=False))
        report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["failed"])
        self.assertEqual(report["results"][0]["attempts"], 1)
        self.assertEqual(self.fetcher.calls, ["https://a.example/"])

    def test_transient_failure_retries_are_bounded(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/", single.FetchError("HTTP 503", retryable=True))
        clock = FakeClock()
        with patch.object(batch.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(batch.time, "sleep", side_effect=clock.sleep):
            report = self.run_batch(attempts=3)
        self.assert_statuses(report, ["failed"])
        self.assertEqual(report["results"][0]["attempts"], 3)
        self.assertEqual(self.fetcher.calls, ["https://a.example/"] * 3)

    def test_rate_limiter_applies_retry_after_to_shared_host_without_blocking_other_hosts(self):
        clock = FakeClock()
        with patch.object(batch.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(batch.time, "sleep", side_effect=clock.sleep):
            limiter = batch.RateLimiter(0)
            limiter.defer("https://shared.example/first.png", 3)
            limiter.before_request("https://unrelated.example/other.png")
            self.assertEqual(clock.now, 1000)
            limiter.before_request("https://shared.example/second.png")
        self.assertGreaterEqual(clock.now, 1003)
        self.assertGreaterEqual(sum(clock.sleeps), 3)

    def test_long_retry_after_stops_other_companies_requesting_same_asset_host(self):
        self.write_manifest([company(), company("issuer-b", "XBBB", "B", "https://b.example")])
        self.fetcher.add("https://a.example/",
                         (b'<link rel="icon" href="https://shared.example/a.png">',
                          "https://a.example/", "text/html"))
        self.fetcher.add("https://b.example/",
                         (b'<link rel="icon" href="https://shared.example/b.png">',
                          "https://b.example/", "text/html"))
        self.fetcher.add("https://shared.example/a.png",
                         single.FetchError("HTTP 429", retryable=True, retry_after=3600))
        self.fetcher.add("https://shared.example/b.png", (PNG, "https://shared.example/b.png", "image/png"))
        with patch.object(batch.time, "sleep") as sleep:
            report = self.run_batch(workers=1, attempts=3)
        self.assert_statuses(report, ["failed", "failed"])
        self.assertIn("https://b.example/", self.fetcher.calls)
        self.assertNotIn("https://shared.example/b.png", self.fetcher.calls)
        self.assertFalse(any("favicon.ico" in url for url in self.fetcher.calls))
        self.assertTrue(all(row.get("retryAt") for row in report["results"]))
        self.assertEqual(sleep.call_count, 0)

    def test_http_requests_respect_global_spacing_and_worker_limit(self):
        self.write_manifest([company(f"issuer-{n}", "XAAA", f"T{n}", f"https://d{n}.example")
                             for n in range(5)])
        fetcher = FixtureFetcher(delay=0.025)
        report = self.run_batch(fetcher=fetcher, workers=2, min_interval=0.01)
        self.assert_statuses(report, ["success"] * 5)
        self.assertEqual(len(fetcher.events), 10)  # Homepages AND images are paced.
        timestamps = sorted(at for _, at in fetcher.events)
        self.assertTrue(all(later - earlier >= 0.008 for earlier, later in zip(timestamps, timestamps[1:])),
                        f"HTTP requests were not globally spaced: {timestamps}")
        self.assertLessEqual(fetcher.peak_active, 2)
        self.assertGreaterEqual(fetcher.peak_active, 2)  # Exercise actual independent work.

    def test_redirect_hops_also_pass_through_http_rate_limiter(self):
        self.write_manifest()
        def redirect(url, max_bytes, before_request):
            final = "https://www.a.example/"
            self.assertIsNotNone(before_request)
            before_request(final)
            self.fetcher.events.append((final, time.monotonic()))
            return b'<link rel="icon" href="/icon.png">', final, "text/html"
        self.fetcher.add("https://a.example/", redirect)
        report = self.run_batch(min_interval=0.01)
        self.assert_statuses(report, ["success"])
        timestamps = sorted(at for _, at in self.fetcher.events)
        self.assertEqual(len(timestamps), 3)
        self.assertTrue(all(later - earlier >= 0.008 for earlier, later in zip(timestamps, timestamps[1:])))

    def test_homepage_redirect_to_another_domain_requires_identity_review(self):
        self.write_manifest()
        self.fetcher.add("https://a.example/",
                         (b'<link rel="icon" href="/icon.png">', "https://unrelated.example/", "text/html"))
        report = self.run_batch()
        self.assert_statuses(report, ["needs_review"])
        self.assertEqual(self.fetcher.calls, ["https://a.example/"])
        self.assertFalse(self.registry.exists() and self.load_registry()["brands"].get("a.example"))

    def test_both_registry_and_checkpoint_locks_prevent_concurrent_writers(self):
        self.write_manifest()
        for target in (self.registry, self.state):
            with self.subTest(target=target.name):
                lock_path = Path(str(target) + ".lock")
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                with lock_path.open("a+") as held:
                    fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(single.BrandImportError):
                        self.run_batch()
                self.assert_no_network()
        # Releasing a lock must restore normal operation.
        self.assert_statuses(self.run_batch(), ["success"])

    def test_single_import_refresh_preserves_identity_bound_by_batch(self):
        self.write_manifest()
        self.run_batch()
        previous = self.load_registry()["brands"]["a.example"]
        result = single.import_brand("https://a.example", self.registry,
                                     fetcher=FixtureFetcher(payload=OTHER_PNG))
        self.assertEqual(result["identity"], previous["identity"])
        self.assertEqual(result["sha256"], hashlib.sha256(OTHER_PNG).hexdigest())
        self.assertEqual(self.load_registry()["brands"]["a.example"]["identity"], previous["identity"])

    def test_single_import_obeys_the_same_registry_lock_as_batch(self):
        previous = self.store_entry(kind="reviewed-logo")
        lock_path = Path(str(self.registry) + ".lock")
        with lock_path.open("a+") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(single.BrandImportError):
                single.import_brand("https://a.example", self.registry, fetcher=self.fetcher)
        self.assertEqual(self.load_registry()["brands"]["a.example"], previous)
        self.assert_no_network()

    def test_malformed_existing_registry_is_not_reset(self):
        self.registry.parent.mkdir(parents=True)
        corrupt = '{"version":1,"brands":'
        self.registry.write_text(corrupt, encoding="utf-8")
        self.write_manifest()
        with self.assertRaises(single.BrandImportError):
            self.run_batch()
        self.assertEqual(self.registry.read_text(encoding="utf-8"), corrupt)
        self.assert_no_network()

    def test_malformed_checkpoint_is_not_silently_discarded(self):
        corrupt = '{"version":1,"results":'
        self.state.write_text(corrupt, encoding="utf-8")
        self.write_manifest()
        with self.assertRaises(single.BrandImportError):
            self.run_batch()
        self.assertEqual(self.state.read_text(encoding="utf-8"), corrupt)
        self.assert_no_network()

    def test_non_json_nan_in_manifest_or_checkpoint_is_rejected_before_network(self):
        for target in ("manifest", "checkpoint"):
            with self.subTest(target=target):
                value = self.write_manifest()
                if target == "manifest":
                    invalid = json.dumps(value)[:-1] + ', "extra": NaN}'
                    path = self.manifest
                else:
                    self.store_entry()
                    self.run_batch()
                    valid_state = json.loads(self.state.read_text(encoding="utf-8"))
                    invalid = json.dumps(valid_state)[:-1] + ', "extra": NaN}'
                    path = self.state
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaises(single.BrandImportError):
                    self.run_batch()
                self.assertEqual(path.read_text(encoding="utf-8"), invalid)
                self.assert_no_network()

    def test_duplicate_json_fields_in_manifest_or_checkpoint_are_rejected(self):
        for target in ("manifest", "checkpoint"):
            with self.subTest(target=target):
                value = self.write_manifest()
                if target == "manifest":
                    invalid = json.dumps(value)[:-1] + ', "version": 1}'
                    path = self.manifest
                else:
                    self.store_entry()
                    self.run_batch()
                    valid_state = json.loads(self.state.read_text(encoding="utf-8"))
                    invalid = json.dumps(valid_state)[:-1] + ', "version": 1}'
                    path = self.state
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaises(single.BrandImportError):
                    self.run_batch()
                self.assertEqual(path.read_text(encoding="utf-8"), invalid)
                self.assert_no_network()


if __name__ == "__main__":
    unittest.main()
