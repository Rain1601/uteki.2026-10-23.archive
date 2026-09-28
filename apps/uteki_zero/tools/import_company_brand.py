#!/usr/bin/env python3
"""Import an explicitly identified website's icon, or a reviewed logo, locally.

Standard library only. No ticker guesses, company defaults, og:image selection,
or logo-service credentials. SVG is intentionally unsupported: supply a reviewed
PNG/JPEG/WebP/ICO raster, or let the site's icon be discovered. See README.md.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import socket
import ssl
import struct
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit


DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "assets/companies/registry.json"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 12
MAX_REDIRECTS = 5
MAX_CANDIDATES = 8


class BrandImportError(ValueError):
    """Explicit coverage/validation failure; callers must not substitute a brand."""


class IdentityReviewRequired(BrandImportError):
    """The supplied website redirects to a different identity; review it first."""


class FetchError(BrandImportError):
    """Transport failure with explicit retry policy, shared by the batch runner."""

    def __init__(self, message, *, retryable=False, retry_after=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def retry_after_seconds(value):
    if not value:
        return None
    try:
        if value.strip().isdigit():
            return float(value.strip())
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_unspecified)


def https_url(value: str) -> str:
    """Validate URL shape without a network request; canonicalize its hostname."""
    if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f\\]", value):
        raise BrandImportError("A nonempty public HTTPS URL is required")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise BrandImportError("Only absolute HTTPS URLs are supported")
        if parsed.username is not None or parsed.password is not None:
            raise BrandImportError("URL credentials are not supported")
        if parsed.port not in (None, 443):
            raise BrandImportError("Only the default HTTPS port is supported")
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            ):
                raise BrandImportError("A valid public hostname is required")
        else:
            if not is_public_address(str(address)):
                raise BrandImportError("Private, loopback and reserved addresses are forbidden")
        authority = f"[{host}]" if ":" in host else host
        result = urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))
        result.encode("ascii")
        return result
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, BrandImportError):
            raise
        raise BrandImportError("Invalid HTTPS URL; percent-encode non-ASCII paths") from exc


def normalize_website(value: str) -> tuple[str, str]:
    """Website identity is an explicit origin; www is normalized for registry keys."""
    url = https_url(value)
    parsed = urlsplit(url)
    if parsed.path != "/" or parsed.query or urlsplit(value).fragment:
        raise BrandImportError("--website must be a company website origin, without path/query/fragment")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BrandImportError("--website must identify a domain, not an IP address")
    key = host[4:] if host.startswith("www.") else host
    if "." not in key:
        raise BrandImportError("--website must identify a public domain")
    return key, url


def public_addresses(host: str, timeout: float = TIMEOUT_SECONDS) -> list[str]:
    """Reject the entire resolution if any address is not public."""
    resolved = queue.Queue(maxsize=1)
    def resolve():
        try:
            resolved.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError as exc:
            resolved.put(exc)
    # getaddrinfo has no timeout argument. A daemon prevents a stalled resolver
    # from blocking the CLI after its bounded queue wait expires.
    threading.Thread(target=resolve, daemon=True).start()
    try:
        results = resolved.get(timeout=max(0, timeout))
        if isinstance(results, OSError):
            raise results
        addresses = list(dict.fromkeys(result[4][0] for result in results))
        if not addresses or any(not is_public_address(ip) for ip in addresses):
            raise BrandImportError(f"Refusing non-public address for {host}")
        return addresses
    except queue.Empty as exc:
        raise FetchError(f"DNS resolution exceeded time limit for {host}", retryable=True) from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, BrandImportError):
            raise
        raise FetchError(f"Cannot resolve public HTTPS host {host}: {exc}", retryable=True) from exc


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the checked address while validating TLS against the hostname."""

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def fetch_public(url: str, max_bytes: int, *, before_request=None) -> tuple[bytes, str, str]:
    """Bounded download; revalidate and pin DNS for every redirect hop."""
    current = https_url(url)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    for redirect_count in range(MAX_REDIRECTS + 1):
        # Scheduling is outside the network deadline. Each redirect and retry
        # goes through the same batch-wide limiter before sending a request.
        if before_request:
            start = time.monotonic()
            before_request(current)
            deadline += time.monotonic() - start
        parsed = urlsplit(current)
        addresses = public_addresses(parsed.hostname, deadline - time.monotonic())
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("Download exceeded time limit", retryable=True)
        connection = PinnedHTTPSConnection(parsed.hostname, addresses[0], remaining)
        try:
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            connection.request("GET", path, headers={
                "User-Agent": "Uteki-BrandImporter/1.0",
                "Accept": "*/*", "Accept-Encoding": "identity",
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect_count == MAX_REDIRECTS:
                    raise BrandImportError("Missing redirect target or too many redirects")
                current = https_url(urljoin(current, location))
                continue
            if response.status != 200:
                raise FetchError(f"HTTP {response.status} for {current}",
                                 retryable=response.status in (408, 429, 500, 502, 503, 504),
                                 retry_after=retry_after_seconds(response.getheader("Retry-After")))
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise BrandImportError("Compressed HTTP responses are not supported")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise BrandImportError("Invalid or excessive Content-Length")
            chunks, count = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("Download exceeded time limit", retryable=True)
                # HTTPConnection clears its socket on Connection: close even
                # while the response still owns that socket through its file.
                response_socket = connection.sock or getattr(getattr(response.fp, "raw", None), "_sock", None)
                if response_socket:
                    response_socket.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - count))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                if count > max_bytes:
                    raise BrandImportError("Download exceeded byte limit")
            if length is not None and count != int(length):
                raise FetchError("Truncated response", retryable=True)
            return b"".join(chunks), current, response.getheader("Content-Type", "").split(";")[0].lower()
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError(f"HTTPS download failed for {current}: {exc}", retryable=True) from exc
        finally:
            connection.close()
    raise BrandImportError("Too many redirects")


class IconParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.icons = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        attrs = dict(attrs)
        rel = set((attrs.get("rel") or "").lower().split())
        if not rel.intersection({"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}):
            return
        href = attrs.get("href")
        if not href:
            return
        sizes = [min(int(a), int(b)) for a, b in re.findall(r"(\d+)x(\d+)", (attrs.get("sizes") or "").lower())]
        size = max(sizes, default=0)
        apple = bool(rel.intersection({"apple-touch-icon", "apple-touch-icon-precomposed"}))
        # Known large icons first; size-less Apple icons are usually useful raster marks.
        priority = (2 if size >= 128 else 1 if apple else 0, size, apple)
        self.icons.append((priority, href))


def discover_icons(html: bytes, homepage: str) -> list[str]:
    parser = IconParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    found = []
    for _, href in sorted(parser.icons, key=lambda item: item[0], reverse=True):
        try:
            url = https_url(urljoin(homepage, href))
        except BrandImportError:
            continue
        if url not in found:
            found.append(url)
    # Keep the fallback even when a site contains many irrelevant icon links.
    fallback = urljoin(homepage, "/favicon.ico")
    return [u for u in found[:MAX_CANDIDATES - 1] if u != fallback] + [fallback]


def image_type(data: bytes) -> tuple[str, str]:
    """Identify raster bytes, never trust HTTP MIME or filename extensions."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 45 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        if width and height and data[-8:] == b"IEND\xaeB`\x82":
            return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff") and len(data) >= 16 and data.endswith(b"\xff\xd9"):
        return "jpg", "image/jpeg"
    if len(data) >= 22 and data[:4] == b"\x00\x00\x01\x00":
        count = int.from_bytes(data[4:6], "little")
        if count and len(data) >= 6 + 16 * count:
            for index in range(count):
                offset = 6 + index * 16
                size, start = struct.unpack("<II", data[offset + 8:offset + 16])
                if not size or start < 6 + 16 * count or start + size > len(data):
                    break
            else:
                return "ico", "image/x-icon"
    if len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X"):
        if int.from_bytes(data[4:8], "little") + 8 == len(data):
            return "webp", "image/webp"
    raise BrandImportError("Unsupported or invalid image bytes; expected PNG, JPEG, ICO or WebP (SVG is intentionally rejected)")


def image_dimensions(data: bytes, extension: str) -> tuple[int, int]:
    """Read raster header dimensions; no pixel decoding or brand recognition."""
    width = height = 0
    if extension == "png":
        width, height = struct.unpack(">II", data[16:24])
    elif extension == "ico":
        count = int.from_bytes(data[4:6], "little")
        sizes = [(data[6 + index * 16] or 256, data[7 + index * 16] or 256) for index in range(count)]
        # ICO can contain multiple resolutions; reject mixed-aspect frames so a
        # different browser-selected frame cannot bypass the icon ratio gate.
        if len({w / h for w, h in sizes}) != 1:
            raise BrandImportError("ICO frames have inconsistent aspect ratios; provide a single raster icon")
        width, height = max(sizes, key=lambda size: size[0] * size[1])
    elif extension == "jpg":
        offset = 2
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while offset + 1 < len(data) and data[offset] == 0xFF:
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD9, 0xDA):
                break
            if marker in {0xD8, 0x01, *range(0xD0, 0xD8)}:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker in sof and length >= 8:
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                break
            offset += length
    elif extension == "webp":
        chunk = data[12:16]
        chunk_size = int.from_bytes(data[16:20], "little")
        if 20 + chunk_size <= len(data):
            if chunk == b"VP8X" and chunk_size >= 10:
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
            elif chunk == b"VP8L" and chunk_size >= 5 and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            elif chunk == b"VP8 " and chunk_size >= 10 and not data[20] & 1 and data[23:26] == b"\x9d\x01\x2a":
                width, height = (value & 0x3FFF for value in struct.unpack("<HH", data[26:30]))
    if not width or not height:
        raise BrandImportError("Cannot reliably read image dimensions for icon validation; provide another PNG/JPEG/ICO/WebP asset")
    return width, height


def validate_icon_shape(data: bytes, extension: str):
    width, height = image_dimensions(data, extension)
    if not 2 / 3 <= width / height <= 1.5:
        raise BrandImportError(f"Icon aspect ratio rejected ({width}x{height}); use a reviewed compact icon, not a wide/tall wordmark")


def read_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "brands": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrandImportError(f"Cannot read registry: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("brands"), dict):
        raise BrandImportError("Registry must have version: 1 and a brands object")
    return value


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".brand-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


@contextmanager
def registry_lock(path: Path):
    """Both CLIs share this advisory lock; keep the lock inode after release."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BrandImportError(f"Registry is locked by another importer: {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def prepare_brand(website: str, *, asset_url: str | None = None,
                  source_page: str | None = None, presentation: str | None = None,
                  fetcher=fetch_public) -> tuple[str, dict, bytes]:
    """Fetch and validate one asset without writes; the batch coordinator commits it."""
    key, website = normalize_website(website)
    if bool(asset_url) != bool(source_page):
        raise BrandImportError("A reviewed logo requires both --asset-url and --source-page")
    if presentation not in (None, "icon", "wordmark"):
        raise BrandImportError("presentation must be icon or wordmark")
    if not asset_url and presentation not in (None, "icon"):
        raise BrandImportError("Automatic site icon discovery only supports presentation icon")
    if asset_url:
        candidates = [https_url(asset_url)]
        source_page = https_url(source_page)
        kind = "reviewed-logo"
        presentation = presentation or "wordmark"
    else:
        html, source_page, mime = fetcher(website, MAX_HTML_BYTES)
        source_page = https_url(source_page)
        source_origin = urlsplit(source_page)
        source_domain, _ = normalize_website(f"https://{source_origin.netloc}/")
        if source_domain != key:
            raise IdentityReviewRequired(
                f"Website redirects from {key} to {source_domain}; verify the entity/domain association before importing")
        if mime not in ("text/html", "application/xhtml+xml"):
            raise BrandImportError("Website did not return HTML; provide a reviewed asset explicitly")
        candidates = discover_icons(html, source_page)
        kind = "official-site-icon"
        presentation = "icon"
    errors = []
    for candidate in candidates:
        try:
            data, final_url, _ = fetcher(candidate, MAX_IMAGE_BYTES)
            extension, mime = image_type(data)
            if presentation == "icon":
                validate_icon_shape(data, extension)
            break
        except BrandImportError as exc:
            # A rate limit or exhausted transient retry must stop this domain;
            # cycling through other icon URLs could evade the server's limit.
            if isinstance(exc, FetchError) and exc.retryable:
                raise
            errors.append(f"{candidate}: {exc}")
    else:
        raise BrandImportError("No usable company image found; registry was not changed.\n" + "\n".join(errors))
    digest = hashlib.sha256(data).hexdigest()
    filename = f"{digest}.{extension}"
    entry = {
        "src": f"./assets/companies/{filename}", "website": website,
        "sourcePage": source_page, "assetUrl": final_url, "kind": kind,
        "presentation": presentation,
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": digest, "mimeType": mime,
    }
    return key, entry, data


def import_brand(website: str, registry: Path = DEFAULT_REGISTRY, *, asset_url: str | None = None,
                 source_page: str | None = None, presentation: str | None = None, fetcher=fetch_public) -> dict:
    with registry_lock(registry):
        return _import_brand_locked(website, registry, asset_url=asset_url,
                                    source_page=source_page, presentation=presentation, fetcher=fetcher)


def _import_brand_locked(website, registry, *, asset_url, source_page, presentation, fetcher):
    key, website = normalize_website(website)
    registry = Path(registry)
    existing = read_registry(registry)
    if bool(asset_url) != bool(source_page):
        raise BrandImportError("A reviewed logo requires both --asset-url and --source-page")
    if presentation not in (None, "icon", "wordmark"):
        raise BrandImportError("presentation must be icon or wordmark")
    if not asset_url and presentation not in (None, "icon"):
        raise BrandImportError("Automatic site icon discovery only supports presentation icon")
    previous = existing["brands"].get(key)
    if not asset_url and isinstance(previous, dict) and previous.get("kind") == "reviewed-logo":
        return previous
    key, entry, data = prepare_brand(website, asset_url=asset_url, source_page=source_page,
                                   presentation=presentation, fetcher=fetcher)
    if isinstance(previous, dict) and "identity" in previous:
        # The domain remains the same; a single-site refresh must not erase the
        # issuer/listing binding established by a validated batch manifest.
        if normalize_website(previous.get("website"))[0] != key:
            raise BrandImportError("Existing registry identity does not match its domain")
        entry["identity"] = previous["identity"]
        entry["brandReview"] = "reviewed" if asset_url else "pending"
    filename = entry["src"].rsplit("/", 1)[1]
    # Re-read immediately before update to preserve intervening additions.
    current = read_registry(registry)
    if not asset_url and current["brands"].get(key, {}).get("kind") == "reviewed-logo":
        return current["brands"][key]
    atomic_write(registry.parent / filename, data)
    current["brands"][key] = entry
    atomic_write(registry, (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return entry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--website", required=True, help="Explicit company website origin, e.g. https://example.com")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Registry JSON path; assets are saved beside it")
    parser.add_argument("--asset-url", help="Reviewed official raster logo URL; skips homepage discovery")
    parser.add_argument("--source-page", help="Official page documenting the reviewed logo")
    parser.add_argument("--presentation", choices=("icon", "wordmark"), help="Reviewed asset role (default wordmark); automatic discovery always uses icon")
    args = parser.parse_args(argv)
    try:
        entry = import_brand(args.website, args.registry, asset_url=args.asset_url, source_page=args.source_page, presentation=args.presentation)
    except (BrandImportError, OSError) as exc:
        parser.exit(1, f"Brand import failed: {exc}\n")
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
