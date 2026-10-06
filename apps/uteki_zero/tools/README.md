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
service dependencies. Run imports sequentially; the registry update is atomic,
but concurrent CLI writers are not supported.

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
