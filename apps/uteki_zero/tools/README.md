# Company brand import

Import a local company mark using an explicitly supplied website identity:

```sh
python3 apps/uteki_zero/tools/import_company_brand.py --website https://example.com
```

The importer reads that site's `rel="apple-touch-icon"` / `rel="icon"` links,
prefers known sizes of at least 128 pixels, and finally tries `/favicon.ico`.
It never guesses a website from a ticker/name and never treats `og:image` as a
logo. A website icon is classified as `kind: official-site-icon` with
`presentation: icon`, not a reviewed corporate logo. Homepage icon discovery is a useful fallback, not proof of legal
entity ownership or brand correctness; domain selection remains explicit.

When an official brand/press page provides a better raster asset, review the
association and import both URLs explicitly:

```sh
python3 apps/uteki_zero/tools/import_company_brand.py \
  --website https://example.com \
  --asset-url https://example.com/media/company-logo.png \
  --source-page https://example.com/press \
  --presentation icon
```

`--presentation icon` explicitly selects a compact, avatar-style mark for the
company list. Reviewed manual assets default to `presentation: wordmark` when
the flag is omitted; a square canvas alone does not turn a full corporate logo
into an icon. The company-list renderer should accept only `presentation: icon`.
Other uses can deliberately select wordmarks. Existing entries without the
field must not be silently treated as icons or migrated based on aspect ratio.

An icon import reads PNG, JPEG SOF, ICO directory, or WebP VP8/VP8L/VP8X header
dimensions and requires width/height between 2/3 and 1.5 inclusive. Unreadable
dimensions fail with an explicit gap; mixed-aspect ICO frames are also rejected.
An unsuitable discovered candidate is skipped for the next site icon. A failed
manual icon import preserves the registry. This ratio gate catches elongated
wordmarks; it does not prove brand correctness, appropriate crop, or legibility.
Source/entity matching and whether the image actually represents the desired
company icon still require review. Pixels are never cropped into a fabricated
icon by this importer; circular framing belongs to the UI.

These illustrative `example.com` URLs are not a configured provider or a
working asset. There are no default companies, external API keys, or paid logo
service dependencies. Both CLIs take the same nonblocking `registry.json.lock`;
a competing writer exits with a lock error. The stable lock file may remain
after the process exits; do not delete it while an importer is running.

Automatic discovery preserves an existing `reviewed-logo` entry without making
network requests; it never downgrades that asset to a favicon. To replace a
reviewed entry, explicitly provide a newly reviewed asset URL and source page.
This is a local preparation CLI, not an integrated production add-company UI.

## Registry contract

Default output is `apps/uteki_zero/assets/companies/registry.json`:

```json
{"version":1,"brands":{"example.com":{"src":"./assets/companies/<sha256>.png","website":"https://example.com/","sourcePage":"https://example.com/press","assetUrl":"https://example.com/media/company-logo.png","kind":"reviewed-logo","presentation":"icon","fetchedAt":"<UTC ISO timestamp>","sha256":"<sha256>","mimeType":"image/png"}}}
```

Keys use lowercase IDNA domain names and remove one leading `www.`. Other
subdomains remain separate; different entities are not implicitly merged.
The UI's company website should use the same normalization. File bytes are
preserved under their full SHA-256 filename. Provenance records the final
download URL, source page, source type, timestamp, and byte hash. Other entries
are preserved. Download/format errors produce a nonzero exit and do not change
the previous registry entry. Existing assets are not automatically deleted.

`--registry` supports another registry path (useful for testing/export); assets
are written beside that file. `src` still assumes the registry/assets will be
served at the page's `./assets/companies/` path, so place exported files there
when integrating them.

## Network / format bounds

Only public HTTPS on port 443 is supported, without credentials. Each redirect
is validated; private/loopback/reserved DNS results are rejected, and the checked
IP is pinned while TLS validates the original hostname. Limits: 5 redirects,
8 image candidates, 2 MiB homepage, 8 MiB image, 12 seconds per fetch. Proxy
environment variables are not used. PNG/JPEG/ICO/WebP are detected from bytes;
HTML error pages are rejected even if named `.png`. SVG is intentionally
rejected, including official SVG, to avoid importing active/external content;
choose an official raster asset. No image is regenerated, recolored, or cropped.

## Offline verification

```sh
python3 -m unittest discover -s apps/uteki_zero/tools -p 'test_*.py' -v
```

Tests use independent synthetic domains and in-memory images; they exercise
scope, discovery, identity isolation, provenance, failed-import preservation,
format rejection, icon/wordmark separation, raster-header dimensions, wide/tall
icon rejection without mutation, and private redirect blocking. They make no network requests
and do not establish that a particular real company's brand has been approved.

## Batch import

The batch CLI is an offline asset-preparation interface. It does not edit the UI
company list or infer a website from a name/ticker. Input and output paths are
required so a research sample cannot silently become a production company pool.
Python 3.9+ and a POSIX system with `fcntl` are supported; validation in this
worktree used Python 3.13. The library entry point is `run_batch(...)` in
`import_company_brands.py`, with the same explicit paths and options as the CLI.

Provide a versioned manifest:

```json
{
  "version": 1,
  "scope": {"id": "caller-selected-universe-v1", "markets": ["XNAS", "XLON"]},
  "companies": [
    {"entityId": "caller-issuer-id", "exchange": "XNAS", "ticker": "CALLER", "website": "https://issuer.example"}
  ]
}
```

The issuer and domain above are synthetic and will not download a real logo.
`entityId`, `exchange`, `ticker`, and HTTPS origin `website` must be explicit.
`scope.markets` is a nonempty list of uppercase four-character MIC codes; every
row's exchange must belong to it. The importer validates structure and internal
consistency, not the existence of each exchange/listing or legal issuer ownership.
Ticker case and punctuation are kept: there is no automatic exchange suffix,
ADR, share-class, parent/subsidiary, or region conversion.

```sh
python3.13 apps/uteki_zero/tools/import_company_brands.py \
  --manifest /path/to/companies-v1.json \
  --registry /path/to/assets/companies/registry.json \
  --state /path/to/run-v1.state.json \
  --workers 3 --min-interval 1 --attempts 3 \
  > /path/to/run-v1.report.json
```

`--workers` bounds concurrent domains (1–8, default 3). `--min-interval` spaces
**HTTP starts**, including homepage, icon, redirects, and retries, globally
(default one second). The bound is per process; use one run for one workload.
`--attempts` bounds each fetch (1–5, default 3); only transport/timeouts, HTTP 408,
429 and selected 5xx responses are retryable. Backoff and `Retry-After` are
respected. A retry delay over 60 seconds ends that domain with `retryAt` instead
of sleeping early and trying again. Host cooldowns apply to shared CDNs and are
persisted in `state.hostCooldowns`, including across `--retry-failed` restarts.
Keep that state while the server's cooldown is active; do not start a new state
to evade it. An unrepresentably large delay is kept as `manual-clear-required`.
HTTP 403 is a coverage failure; no browser,
cookie, proxy or user-agent bypass is attempted. Homepage redirects to a different
canonical domain require identity review; an image CDN is allowed when discovered
from the supplied website. Other subdomains never become aliases implicitly.

### Cache, identity, and continuation

- Domain groups share one discovery/download. Repeated rows keep individual
  results with `duplicateOf`; one issuer may explicitly have several listings.
  Entity → conflicting domains, domain → conflicting entities, or the same
  exchange/ticker → conflicting entities all require review before requests.
  Legible conflicts in partially invalid rows also block the affected valid rows.
- Saved entries preserve the version 1 renderer contract. Optional
  `identity: {entityId, listings: [{exchange, ticker}]}` and
  `brandReview: "pending" | "reviewed"` record the supplied association. Existing
  entries without this metadata can be bound by a valid manifest; this is a
  caller assertion, not independent identity verification. Later runs check the
  bindings across the registry. Single-company refresh preserves them.
- The default cache age is 720 hours (`--cache-max-age-hours`). Cache hits require
  valid website/provenance, safe local path, existing raster bytes, SHA-256, MIME
  and timestamp. A missing/corrupt site icon is fetched again. An expired icon
  whose refresh fails stays on disk but the result remains `failed`.
- `reviewed-logo` always wins, even with `--refresh`. A missing/corrupt reviewed
  asset, reviewed `wordmark`, or reviewed asset without an explicit
  `presentation: icon` becomes `needs_review`; restore or explicitly re-import
  a reviewed compact icon through the single-company interface. It is never
  replaced with a favicon merely to make the batch succeed. Legacy automatic
  entries without `presentation` are reacquired through discovery; their shape
  alone never silently classifies them as icons. Explicit icon caches also pass
  the shared raster dimension/aspect-ratio checks.
- One coordinator atomically writes files, registry, and a per-domain checkpoint.
  Registry and state each have an exclusive advisory lock. No concurrent worker
  rewrites the whole registry. A crash between registry and checkpoint writes
  leaves usable content-addressed assets that are checked on restart.
- Repeat the command with the same `--state` to continue. The checkpoint binds
  the normalized full manifest hash; a changed list/scope requires a new state.
  A completed result is still checked against current local asset bytes. Failures
  remain visible and are retried only with `--retry-failed`; fixing an input means
  creating a new versioned manifest/state, not editing the old checkpoint.
- `--refresh` requests site-icon refresh; within that run its already completed,
  still fresh domains are reused on restart. To start a separate refresh run,
  select a new state path. Keep prior reports for comparison. Successfully
  downloaded icons remain pending brand review.

### Report and exit status

Stdout is JSON. `summary.status` counts **all input rows**, including duplicates,
invalid rows and review gaps. `domainCount` counts distinct parsed domains;
`scheduledDomains` counts domains scheduled for work, and `networkDomains` counts
domains that actually started HTTP in this run (a persisted cooldown can prevent
a scheduled domain from starting). Do not sum copied per-row request counts as
unique downloads.

| `status` | Meaning |
| --- | --- |
| `success` | New website icon downloaded and committed; brand review is pending. |
| `cached` | Existing local bytes and provenance verified; `cache` explains fresh/resumed/reviewed. |
| `invalid` | A required row field or selected market is invalid; no inferred replacement. |
| `needs_review` | Identity/provenance conflict, cross-domain homepage, or protected asset requiring restoration. |
| `failed` | Fetch/format failure; any retained prior asset is identified separately. |

Rows retain their input identity, canonical domain, error, asset provenance,
`attempts` (maximum attempts for any one fetch), `requestAttempts` (fetch calls),
and `httpRequests` (HTTP starts including redirects). `retainedPrevious` does not
mean the refresh succeeded. Exit 0 means all rows are `success` or `cached`;
exit 1 means at least one row is invalid, failed or needs review; exit 2 means
manifest/options/state/registry/lock-level failure. Save stdout even on exit 1.
Technical completion does not mean all returned images are audited company logos.

The frozen [public evaluation](../../../experiments/company-brand-import/2026-09-29-v1/README.md)
contains companies outside the original six. It is optional test input, with
separate output assets, not a fallback configuration. The
[provider comparison](../../../docs/COMPANY_LOGO_PROVIDERS_2026-09-29.zh-CN.md)
records authentication and storage-permission gaps for third-party services.

Limits: raster formats only; static homepage declarations only; some sites need
JavaScript, block automation, change regional domains, or have no usable icon.
An explicit but wrong website can still return a technically valid wrong brand:
the importer cannot establish corporate ownership from a successful HTTP response.
No supplier key, market-wide coverage, production add-company backend, or new
company UI is included in this change.
