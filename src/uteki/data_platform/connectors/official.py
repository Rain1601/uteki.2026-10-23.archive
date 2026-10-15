"""Bounded explicit-URL acquisition through the existing source transport."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit

from uteki.infrastructure.document_sources.company_acquisition import AcquisitionError, AcquisitionCancelled, prepare_sources
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact

from ..content.store import ContentStore, ContentStoreError
from ..contracts.common import CatalogError, digest
from ..contracts.content import InputManifest, MissingResource, PresentResource
from ..build.dom import SourceDOM, excluded, srcset_key


def image_key(url):
    return "image-" + digest(url.encode("utf-8"))


def acquire_html(*, config: dict, workspace: Path, settings_root: Path, main_url: str,
                 allowed_urls: tuple[str, ...], max_seconds: float, fetch=None, should_cancel=None,
                 on_progress=None):
    """Return verified acquisition bytes/receipts, never a published asset.

    `fetch` is solely the transport injection point for deterministic tests.
    The caller explicitly supplies the complete main/resource/redirect allowlist.
    Credentials are resolved locally and are never returned in the receipt.
    """
    ContentStore(workspace)  # Enforce the same explicit, existing absolute root.
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 120:
        raise CatalogError("INVALID_ARGUMENT", "bounded positive acquisition deadline required")
    if not isinstance(allowed_urls, tuple) or not allowed_urls or len(set(allowed_urls)) != len(allowed_urls):
        raise CatalogError("INVALID_ARGUMENT", "explicit unique URL tuple required")
    for url in allowed_urls:
        if not isinstance(url, str):
            raise CatalogError("INVALID_ARGUMENT", "URL must be text")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise CatalogError("INVALID_ARGUMENT", "public HTTPS URL without credentials/fragment required")
    approved = frozenset(allowed_urls)
    if main_url not in approved:
        raise CatalogError("INVALID_ARGUMENT", "main URL must be explicitly approved")
    copied = deepcopy(config)
    contact, origin = resolve_sec_contact(configured=copied.pop("sec_user_agent", None), settings_root=settings_root)
    if contact is None:
        raise CatalogError("INVALID_ARGUMENT", "SEC contact is not configured")
    copied.update(sec_user_agent=contact, sec_contact_origin=origin)
    # Do not silently inherit large legacy defaults for a new bounded task.
    required = {"max_requests", "max_documents", "max_total_bytes", "max_bytes_per_document",
                "timeout_seconds", "retries", "min_request_interval_seconds"}
    limits = copied.get("limits", {})
    if not required <= limits.keys() or limits["retries"] != 0:
        raise CatalogError("INVALID_ARGUMENT", "explicit acquisition limits and retries=0 required")
    deadline = time.monotonic() + max_seconds

    def guard(url):
        if url not in approved:
            raise AcquisitionError("URL outside frozen exact allowlist")

    session = prepare_sources(copied, workspace, fetch=fetch, _session_only=True,
                              request_guard=guard, should_stop=lambda: time.monotonic() >= deadline or bool(should_cancel and should_cancel()),
                              remaining_seconds=lambda: deadline-time.monotonic())
    report = session["report"]
    report["company"] = {"symbol": copied["symbol"], "cik": copied.get("cik"), "market": copied["market"]}
    report["scope"]["exact_allowed_urls"] = list(allowed_urls)
    report["scope"]["max_seconds"] = max_seconds
    report['transport_journal_version'] = 'uteki-acquisition-transport-v1'
    report['transport_state'] = None
    hosts = {urlsplit(url).hostname for url in allowed_urls}
    result = {"main": None, "resources": {}, "missing": {}, "unsupported": {}, "excluded": [], "report": report}
    def record_progress():
        if on_progress is not None:
            try:
                on_progress(deepcopy(report))
            except (OSError,ContentStoreError) as error:
                raise CatalogError('RECOVERY_REQUIRED','acquisition receipt persistence failed') from error

    def request(url):
        report['transport_state'] = dict(status='dispatched',url=url,ordinal=report['requests']+1)
        record_progress()
        try:
            raw = session['request'](url,hosts)
        except Exception:
            report['transport_state']['status'] = 'returned_error'
            record_progress()
            raise
        report['transport_state']['status'] = 'returned'
        record_progress()
        return raw

    # Persist the source-run identity before transport, and completed receipts
    # before another request. An in-flight request can still be unconfirmed.
    record_progress()
    try:
        raw = request(main_url)
        result["main"] = raw
        receipt = next(r for r in reversed(report["discovery"]) if r.get("source_url") == main_url and r["status"] == "fetched")
        result["final_url"] = receipt["final_url"]
        if copied.get("document_validation") == "sec_inline_identity_v1":
            selection = copied["filing_selection"]
            result["identity_validation"] = validate_sec_filing(raw, expected_cik=copied["cik"],
                expected_form=selection.get("form_type", selection.get("annual_form", "10-K")),
                expected_period_end=selection["report_period_end"])
        dom = SourceDOM(raw, encoding="utf-8")
        for node in dom.root.iter("img"):
            session["check_stop"]()
            src = node.get("src")
            path = dom.path(node)
            if node.get("srcset") and not excluded(node):
                result["unsupported"][srcset_key(path)] = "unsupported_srcset:" + path
                session["gap"]("unsupported_srcset", dom_path=path)
            if not src:
                result["excluded"].append({"dom_path": path, "reason": "image_without_src"})
                continue
            url = urljoin(result["final_url"], src)
            reason = excluded(node)
            if reason:
                result["excluded"].append({"dom_path": path, "url": url, "reason": reason})
                continue
            if url in result["resources"] or url in result["missing"]:
                continue
            if url not in approved:
                result["missing"][url] = "not_allowed_by_frozen_source_policy"
                session["gap"]("resource_not_allowed", url)
                continue
            if sum(r["status"] in {"fetched", "failed"} for r in report["discovery"]) >= limits["max_documents"]:
                result["missing"][url] = "document_limit"
                session["gap"]("document_limit", url)
                continue
            try:
                result["resources"][url] = request(url)
            except CatalogError:
                # Journal failures are not missing remote resources.
                raise
            except AcquisitionCancelled:
                raise
            except Exception as error:
                result["missing"][url] = type(error).__name__
                session["gap"]("resource_acquisition_failed", url, error_type=type(error).__name__)
        report["input_resources"] = {"present": sorted(result["resources"]), "missing": result["missing"],
                                     "unsupported": result["unsupported"], "excluded": result["excluded"]}
    except Exception as error:
        session["gap"]("main_acquisition_failed", main_url, error_type=type(error).__name__)
        session["finish"]()
        if isinstance(error,CatalogError) and error.code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'}:
            raise
        raise CatalogError("ACQUISITION_FAILED", "official main acquisition failed; source-run receipt retained") from error
    session["finish"]()
    if report["status"] == "cancelled":
        raise CatalogError("ACQUISITION_FAILED", "acquisition deadline exceeded; receipt retained")
    return result


def store_acquisition(store: ContentStore, acquired: dict, *, main_url: str):
    """Import only obtained bytes; preserve explicitly absent resource reasons."""
    if not isinstance(acquired.get("main"), bytes):
        raise CatalogError("ACQUISITION_FAILED", "no acquired main document")
    resources = tuple(PresentResource(status="present", resource_key=image_key(url), source_url=url,
                                     object_ref=store.put_object(raw)) for url, raw in sorted(acquired["resources"].items()))
    resources += tuple(MissingResource(status="missing", resource_key=image_key(url), source_url=url, reason=reason)
                       for url, reason in sorted(acquired["missing"].items()))
    resources += tuple(MissingResource(status="missing", resource_key=key, source_url=None, reason=reason)
                       for key, reason in sorted(acquired.get("unsupported", {}).items()))
    manifest = InputManifest(schema_version="uteki-input-manifest-v1", main=store.put_object(acquired["main"]),
                             main_source_url=acquired.get("final_url", main_url), resources=resources)
    return store.put_manifest(manifest)
