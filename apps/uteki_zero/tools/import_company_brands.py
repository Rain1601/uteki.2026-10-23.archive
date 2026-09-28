#!/usr/bin/env python3
"""Import official website icons for an explicit, versioned company manifest.

Standard library only. Entity IDs and MIC/ticker pairs are caller assertions,
not identities inferred from company names or external logo search. Discovered
icons remain pending brand review. See README.md for the manifest and report.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from import_company_brand import (
    BrandImportError, FetchError, IdentityReviewRequired, MAX_IMAGE_BYTES,
    atomic_write, fetch_public, https_url, image_type, normalize_website,
    prepare_brand, read_registry, validate_icon_shape,
)


STATUSES = ("success", "cached", "invalid", "needs_review", "failed")
MAX_RETRY_WAIT_SECONDS = 60


def utc_now():
    return datetime.now(timezone.utc)


def timestamp():
    return utc_now().isoformat(timespec="seconds")


def write_json(path, value):
    atomic_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path, label):
    def reject_constant(value):
        raise ValueError(f"Non-JSON numeric constant {value}")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field {key}")
            result[key] = value
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant,
                          object_pairs_hook=unique_keys)
    except (OSError, ValueError) as exc:
        raise BrandImportError(f"Cannot read {label}: {exc}") from exc


def required_text(value, label, *, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
        raise BrandImportError(f"{label} must be a nonempty string without control characters (maximum {limit})")
    return value.strip()


def validate_manifest(path):
    value = read_json(path, "manifest")
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise BrandImportError("Manifest must be an object with version: 1")
    scope = value.get("scope")
    if not isinstance(scope, dict):
        raise BrandImportError("Manifest scope with explicit id and markets is required")
    scope_id = required_text(scope.get("id"), "scope.id")
    markets = scope.get("markets")
    if not isinstance(markets, list) or not markets or any(not isinstance(m, str) or not re.fullmatch(r"[A-Z0-9]{4}", m) for m in markets):
        raise BrandImportError("scope.markets must be a nonempty list of uppercase 4-character exchange MICs")
    if len(markets) != len(set(markets)):
        raise BrandImportError("scope.markets must not contain duplicate MICs")
    companies = value.get("companies")
    if not isinstance(companies, list) or not companies:
        raise BrandImportError("Manifest companies must be a nonempty explicit list")
    normalized = dict(value)
    normalized["scope"] = dict(scope, id=scope_id, markets=sorted(markets))
    normalized["companies"] = []
    rows = []
    for index, company in enumerate(companies):
        row = {"inputIndex": index, "entityId": None, "exchange": None, "ticker": None,
               "website": None, "domain": None, "status": None, "error": None,
               "attempts": 0, "requestAttempts": 0, "httpRequests": 0,
               "cache": "none", "brandReview": None}
        errors = []
        canonical = dict(company) if isinstance(company, dict) else company
        if not isinstance(company, dict):
            errors.append("Company must be an object")
        else:
            for key in ("entityId", "exchange", "ticker"):
                row[key] = company.get(key)
                try:
                    row[key] = required_text(company.get(key), key, limit=64 if key == "ticker" else 256)
                    canonical[key] = row[key]
                except BrandImportError as exc:
                    errors.append(str(exc))
            if row["exchange"] not in markets:
                errors.append("exchange must be an explicitly selected MIC in scope.markets")
            row["website"] = company.get("website")
            try:
                row["domain"], row["website"] = normalize_website(company.get("website"))
                canonical["website"] = row["website"]
            except (BrandImportError, TypeError) as exc:
                errors.append(str(exc))
        if errors:
            row.update(status="invalid", error="; ".join(errors))
        normalized["companies"].append(canonical)
        rows.append(row)

    # Check all legible claims, including partially invalid rows, so a malformed
    # listing cannot hide an otherwise visible entity/domain contradiction.
    entities, domains, listings = {}, {}, {}
    for row in rows:
        entity, domain = row["entityId"], row["domain"]
        if isinstance(entity, str) and entity.strip() and domain:
            entities.setdefault(entity, set()).add(domain)
            domains.setdefault(domain, set()).add(entity)
        exchange, ticker = row["exchange"], row["ticker"]
        if isinstance(entity, str) and entity.strip() and isinstance(exchange, str) and isinstance(ticker, str) and ticker.strip():
            listings.setdefault((exchange, ticker), set()).add(entity)
    for row in rows:
        if row["status"]:
            continue
        conflicts = []
        if len(entities.get(row["entityId"], ())) > 1:
            conflicts.append("entityId is associated with more than one canonical domain")
        if len(domains.get(row["domain"], ())) > 1:
            conflicts.append("canonical domain is associated with more than one entityId")
        if len(listings.get((row["exchange"], row["ticker"]), ())) > 1:
            conflicts.append("exchange/ticker is associated with more than one entityId")
        if conflicts:
            row.update(status="needs_review", error="; ".join(conflicts))
    manifest_hash = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return normalized["scope"], rows, manifest_hash


@contextmanager
def locked_paths(*paths):
    """Keep stable lock files: unlinking them would permit two lock inodes."""
    handles = []
    try:
        for path in sorted({Path(p).resolve() for p in paths}, key=str):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = Path(str(path) + ".lock").open("a+b")
            handles.append(handle)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BrandImportError(f"Another batch import holds the lock for {path}") from exc
        yield
    finally:
        for handle in reversed(handles):
            handle.close()


class RateLimiter:
    """Space every actual HTTP start, including redirects, across all workers."""

    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.host_cooldowns = {}
        self.blocked_hosts = set()

    def defer(self, url, seconds):
        host = urlsplit(url).hostname
        with self.lock:
            self.host_cooldowns[host] = max(self.host_cooldowns.get(host, 0), time.monotonic() + seconds)
            if seconds > MAX_RETRY_WAIT_SECONDS:
                self.blocked_hosts.add(host)

    def restore(self, cooldowns):
        if not isinstance(cooldowns, dict):
            raise BrandImportError("State hostCooldowns must be an object")
        for host, until in cooldowns.items():
            if not isinstance(host, str) or not isinstance(until, str):
                raise BrandImportError("Invalid state host cooldown")
            try:
                url = https_url("https://" + host)
                if until == "manual-clear-required":
                    self.defer(url, 1e300)
                    continue
                parsed = datetime.fromisoformat(until.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
                remaining = (parsed - utc_now()).total_seconds()
            except (ValueError, TypeError) as exc:
                raise BrandImportError("Invalid state host cooldown") from exc
            if remaining > 0:
                self.defer(url, remaining)

    def snapshot(self):
        with self.lock:
            now, wall_now = time.monotonic(), utc_now()
            result = {}
            for host, until in self.host_cooldowns.items():
                if until > now:
                    try:
                        result[host] = (wall_now + timedelta(seconds=until - now)).isoformat()
                    except OverflowError:
                        # Never truncate an unrepresentably long server delay
                        # and accidentally permit requests on the next run.
                        result[host] = "manual-clear-required"
            return result

    def before_request(self, url):
        host = urlsplit(url).hostname
        while True:
            with self.lock:
                now = time.monotonic()
                cooldown = self.host_cooldowns.get(host, 0)
                if host in self.blocked_hosts:
                    raise FetchError(f"Host {host} requested a long Retry-After; deferred for this run",
                                     retryable=True, retry_after=max(0, cooldown - now))
                wait = max(self.next_request, cooldown) - now
                if wait <= 0:
                    self.next_request = now + self.interval
                    return
            # Do not hold the mutex while a host cools down: unrelated origins
            # may still proceed, subject to the shared global request interval.
            time.sleep(min(wait, MAX_RETRY_WAIT_SECONDS))


def parse_timestamp(value):
    if not isinstance(value, str):
        raise BrandImportError("fetchedAt must be an ISO timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrandImportError("fetchedAt must be an ISO timestamp with a timezone") from exc
    if parsed.tzinfo is None or parsed > utc_now() + timedelta(minutes=5):
        raise BrandImportError("fetchedAt has no timezone or is in the future")
    return parsed


def entry_identity(entry):
    identity = entry.get("identity")
    if identity is None:
        return None
    if not isinstance(identity, dict):
        raise BrandImportError("Registry identity must be an object")
    entity = required_text(identity.get("entityId"), "registry identity.entityId")
    listings = identity.get("listings")
    if not isinstance(listings, list) or not listings:
        raise BrandImportError("Registry identity.listings must be a nonempty list")
    pairs = set()
    for listing in listings:
        if not isinstance(listing, dict) or not isinstance(listing.get("exchange"), str) or not re.fullmatch(r"[A-Z0-9]{4}", listing["exchange"]):
            raise BrandImportError("Registry listing exchange must be an explicit MIC")
        ticker = required_text(listing.get("ticker"), "registry listing ticker", limit=64)
        pairs.add((listing["exchange"], ticker))
    return entity, pairs


def identity_conflict(domain, entity, pairs, registry):
    for existing_domain, entry in registry["brands"].items():
        if not isinstance(entry, dict):
            continue
        try:
            existing = entry_identity(entry)
        except BrandImportError as exc:
            if existing_domain == domain:
                return str(exc)
            # Broken claims referring to this entity or listing are ambiguous.
            raw = entry.get("identity")
            raw_listings = raw.get("listings") if isinstance(raw, dict) else None
            matches_listing = isinstance(raw_listings, list) and any(
                isinstance(item, dict) and isinstance(item.get("exchange"), str) and isinstance(item.get("ticker"), str)
                and (item["exchange"], item["ticker"]) in pairs for item in raw_listings)
            if isinstance(raw, dict) and (raw.get("entityId") == entity or matches_listing):
                return f"Conflicting malformed identity in registry domain {existing_domain}"
            continue
        if existing is None:
            continue
        old_entity, old_pairs = existing
        if existing_domain == domain and old_entity != entity:
            return f"Registry domain {domain} is already bound to entityId {old_entity}"
        if old_entity == entity and existing_domain != domain:
            return f"Registry entityId {entity} is already bound to domain {existing_domain}"
        if old_entity != entity and pairs.intersection(old_pairs):
            return f"Registry exchange/ticker is already bound to entityId {old_entity}"
    return None


def bind_identity(entry, entity, pairs):
    previous = entry_identity(entry)
    if previous:
        pairs = pairs | previous[1]
    bound = dict(entry)
    bound["identity"] = {"entityId": entity, "listings": [
        {"exchange": exchange, "ticker": ticker} for exchange, ticker in sorted(pairs)]}
    bound["brandReview"] = "reviewed" if entry["kind"] == "reviewed-logo" else "pending"
    return bound


def inspect_cache(entry, domain, registry_path):
    """Return (usable, fetched_at, asset_error); provenance errors need review."""
    if not isinstance(entry, dict) or entry.get("kind") not in ("reviewed-logo", "official-site-icon"):
        raise BrandImportError("Registry entry has an unknown or missing kind")
    if entry["kind"] == "reviewed-logo" and entry.get("presentation") != "icon":
        raise BrandImportError("Reviewed material is not explicitly presentation: icon; preserve it and review a compact icon before batch use")
    if "presentation" in entry and entry["presentation"] != "icon":
        raise BrandImportError("Official site icon has an invalid presentation; compact icon review is required")
    actual_domain, _ = normalize_website(entry.get("website"))
    if actual_domain != domain:
        raise BrandImportError("Registry website does not match its canonical domain")
    source_page = https_url(entry.get("sourcePage"))
    https_url(entry.get("assetUrl"))
    if entry["kind"] == "official-site-icon":
        source_domain, _ = normalize_website("https://" + urlsplit(source_page).netloc)
        if source_domain != domain:
            raise BrandImportError("Automatic icon sourcePage belongs to another canonical domain")
    fetched_at = parse_timestamp(entry.get("fetchedAt"))
    digest = entry.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise BrandImportError("Registry sha256 is missing or invalid")
    source = entry.get("src")
    prefix = "./assets/companies/"
    if not isinstance(source, str) or not source.startswith(prefix):
        raise BrandImportError("Registry src must be a local ./assets/companies/ file")
    filename = source[len(prefix):]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename) or filename in (".", ".."):
        raise BrandImportError("Registry src contains an unsafe or nested asset path")
    if Path(filename).suffix.lower() not in (".png", ".jpg", ".jpeg", ".ico", ".webp"):
        raise BrandImportError("Registry src must name a supported raster asset")
    asset_path = registry_path.parent / filename
    if asset_path.resolve().parent != registry_path.parent.resolve():
        raise BrandImportError("Registry asset resolves outside its local directory")
    if "presentation" not in entry:
        # A legacy favicon may be a wordmark. Reacquire through prepare_brand's
        # current icon contract; never infer or migrate its role from dimensions.
        return False, fetched_at, "Legacy official site icon has no presentation; reacquisition is required"
    try:
        if asset_path.stat().st_size > MAX_IMAGE_BYTES:
            raise BrandImportError("Local asset exceeds byte limit")
        data = asset_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise BrandImportError("Local asset sha256 does not match registry")
        extension, actual_mime = image_type(data)
        if entry.get("mimeType") != actual_mime:
            raise BrandImportError("Local asset mimeType does not match registry")
        validate_icon_shape(data, extension)
    except (OSError, BrandImportError) as exc:
        return False, fetched_at, str(exc)
    return True, fetched_at, None


def process_domain(website, limiter, fetcher, max_attempts):
    result = {"status": "failed", "error": None, "attempts": 0,
              "requestAttempts": 0, "httpRequests": 0, "cache": "none",
              "brandReview": "pending", "retryAt": None}

    def fetch_with_retry(url, max_bytes):
        last_request_url = url

        def before_request(request_url):
            nonlocal last_request_url
            last_request_url = request_url
            limiter.before_request(request_url)
            result["httpRequests"] += 1

        for attempt in range(1, max_attempts + 1):
            result["attempts"] = max(result["attempts"], attempt)
            result["requestAttempts"] += 1
            try:
                return fetcher(url, max_bytes, before_request=before_request)
            except FetchError as exc:
                if not exc.retryable:
                    raise
                retry_after = exc.retry_after
                if retry_after is not None and (not isinstance(retry_after, (int, float)) or not math.isfinite(retry_after) or retry_after < 0):
                    raise BrandImportError("Invalid server Retry-After; manual retry is required") from exc
                delay = max(float(retry_after or 0), float(2 ** (attempt - 1)))
                limiter.defer(last_request_url, delay)
                if retry_after is not None:
                    try:
                        result["retryAt"] = (utc_now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
                    except OverflowError:
                        result["retryAt"] = "beyond supported timestamp range"
                    result["retryAfterSeconds"] = delay
                if delay > MAX_RETRY_WAIT_SECONDS:
                    raise
                if attempt == max_attempts:
                    raise
                time.sleep(delay)
        raise AssertionError("unreachable")

    try:
        domain, entry, data = prepare_brand(website, fetcher=fetch_with_retry)
        result.update(status="success", domain=domain, entry=entry, retryAt=None)
        result.pop("retryAfterSeconds", None)
        return result, data
    except IdentityReviewRequired as exc:
        result.update(status="needs_review", error=str(exc))
    except (BrandImportError, OSError) as exc:
        result["error"] = str(exc)
    return result, None


def validate_options(workers, min_interval, attempts, cache_max_age_hours):
    if type(workers) is not int or not 1 <= workers <= 8:
        raise BrandImportError("workers must be an integer from 1 to 8")
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise BrandImportError("attempts must be an integer from 1 to 5")
    for value, label in ((min_interval, "min_interval"), (cache_max_age_hours, "cache_max_age_hours")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BrandImportError(f"{label} must be a finite nonnegative number")


def run_batch(manifest_path, registry_path, state_path, *, workers=3, min_interval=1,
              attempts=3, cache_max_age_hours=720, refresh=False, retry_failed=False,
              fetcher=None):
    validate_options(workers, min_interval, attempts, cache_max_age_hours)
    scope, rows, manifest_hash = validate_manifest(manifest_path)
    registry_path, state_path = Path(registry_path), Path(state_path)
    if registry_path.resolve() == state_path.resolve() or Path(manifest_path).resolve() in (registry_path.resolve(), state_path.resolve()):
        raise BrandImportError("Manifest, registry and state must be separate files")
    with locked_paths(registry_path, state_path):
        registry = read_registry(registry_path)
        if state_path.exists():
            state = read_json(state_path, "state")
            if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("results"), dict):
                raise BrandImportError("State must have version: 1 and a results object")
            if state.get("manifestHash") != manifest_hash:
                raise BrandImportError("State manifest hash differs from this normalized input; choose a new --state file")
        else:
            state = {"version": 1, "manifestHash": manifest_hash, "scope": scope, "results": {}}
        limiter = RateLimiter(min_interval)
        limiter.restore(state.get("hostCooldowns", {}))
        groups = {}
        for row in rows:
            if not row["status"]:
                groups.setdefault(row["domain"], []).append(row)
        pending, outcomes = {}, {}

        def save_result(domain, outcome):
            outcomes[domain] = outcome
            state["results"][domain] = outcome
            state["updatedAt"] = timestamp()
            state["hostCooldowns"] = limiter.snapshot()
            write_json(state_path, state)

        for domain, group in groups.items():
            entity = group[0]["entityId"]
            pairs = {(row["exchange"], row["ticker"]) for row in group}
            baseline = {"domain": domain, "status": "failed", "error": None,
                        "attempts": 0, "requestAttempts": 0, "httpRequests": 0,
                        "cache": "none", "brandReview": None}
            conflict = identity_conflict(domain, entity, pairs, registry)
            if conflict:
                save_result(domain, dict(baseline, status="needs_review", error=conflict))
                continue
            previous = registry["brands"].get(domain)
            usable, fetched_at, asset_error = False, None, None
            if previous is not None:
                try:
                    usable, fetched_at, asset_error = inspect_cache(previous, domain, registry_path)
                except (BrandImportError, TypeError) as exc:
                    save_result(domain, dict(baseline, status="needs_review", error=str(exc)))
                    continue
                if previous["kind"] == "reviewed-logo" and not usable:
                    save_result(domain, dict(baseline, status="needs_review", cache="reviewed", brandReview="reviewed",
                                             error="Reviewed asset requires manual restoration: " + asset_error))
                    continue
            prior_result = state["results"].get(domain)
            previous_failure = isinstance(prior_result, dict) and prior_result.get("status") in ("failed", "needs_review")
            fresh = usable and (utc_now() - fetched_at).total_seconds() <= cache_max_age_hours * 3600
            reviewed = previous is not None and previous["kind"] == "reviewed-logo"
            # A failed refresh is a failure until explicit retry. An older valid
            # cached icon must not silently turn that failure into a success.
            if previous_failure and not retry_failed:
                held = dict(prior_result, attempts=0, requestAttempts=0, httpRequests=0, resumed=True)
                save_result(domain, held)
                continue
            resumed = isinstance(prior_result, dict) and prior_result.get("status") in ("success", "cached")
            if reviewed or (fresh and (not refresh or resumed) and not previous_failure):
                entry = bind_identity(previous, entity, pairs)
                if entry != previous:
                    registry["brands"][domain] = entry
                    write_json(registry_path, registry)
                save_result(domain, dict(baseline, status="cached", entry=entry,
                                         cache="reviewed" if reviewed else "resumed" if resumed else "fresh",
                                         brandReview=entry["brandReview"]))
                continue
            pending[domain] = (group[0]["website"], entity, pairs, previous, usable, asset_error)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="brand-import") as executor:
            futures = {executor.submit(process_domain, values[0], limiter, fetcher or fetch_public, attempts): domain
                       for domain, values in pending.items()}
            for future in as_completed(futures):
                domain = futures[future]
                _, entity, pairs, previous, usable, asset_error = pending[domain]
                outcome, data = future.result()
                outcome["domain"] = domain
                if outcome["status"] == "success":
                    entry = bind_identity(outcome["entry"], entity, pairs | (entry_identity(previous)[1] if previous and entry_identity(previous) else set()))
                    filename = entry["src"].rsplit("/", 1)[1]
                    # Only this coordinator writes assets, registry and state.
                    atomic_write(registry_path.parent / filename, data)
                    registry["brands"][domain] = entry
                    write_json(registry_path, registry)
                    outcome.update(entry=entry, brandReview="pending")
                elif previous is not None:
                    outcome.update(cache="stale" if usable else "unusable", retainedPrevious=True,
                                   previousAssetUsable=usable)
                    if asset_error:
                        outcome["previousAssetError"] = asset_error
                save_result(domain, outcome)
        # Persist even an entirely invalid manifest report, without network.
        if not state_path.exists():
            state["updatedAt"] = timestamp()
            write_json(state_path, state)
        for domain, group in groups.items():
            first_index = group[0]["inputIndex"]
            for row in group:
                row.update(outcomes[domain])
                if row["inputIndex"] != first_index:
                    row["duplicateOf"] = first_index
        counts = {status: sum(row["status"] == status for row in rows) for status in STATUSES}
        return {"version": 1, "manifestHash": manifest_hash, "scope": scope,
                "generatedAt": timestamp(), "summary": {"inputCount": len(rows),
                    "domainCount": len({row["domain"] for row in rows if row["domain"]}),
                    "scheduledDomains": len(pending),
                    "networkDomains": sum(outcome.get("httpRequests", 0) > 0 for outcome in outcomes.values()),
                    "status": counts}, "results": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Version 1 company manifest with explicit scope")
    parser.add_argument("--registry", type=Path, required=True, help="Compatible local registry; assets are stored beside it")
    parser.add_argument("--state", type=Path, required=True, help="Checkpoint bound to this normalized manifest")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent domains, 1..8 (default: 3)")
    parser.add_argument("--min-interval", type=float, default=1, help="Global minimum seconds between HTTP starts (default: 1)")
    parser.add_argument("--attempts", type=int, default=3, help="Maximum attempts per fetch, 1..5 (default: 3)")
    parser.add_argument("--cache-max-age-hours", type=float, default=720, help="Freshness for ordinary site icons (default: 720)")
    parser.add_argument("--refresh", action="store_true", help="Refresh site icons; reviewed logos remain protected")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry previous failures or review gaps after fixing inputs")
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.manifest, args.registry, args.state, workers=args.workers,
                           min_interval=args.min_interval, attempts=args.attempts,
                           cache_max_age_hours=args.cache_max_age_hours, refresh=args.refresh,
                           retry_failed=args.retry_failed)
    except (BrandImportError, OSError) as exc:
        print(json.dumps({"version": 1, "status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(report["summary"]["status"][status] for status in ("invalid", "needs_review", "failed")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
