# Batch company icon acceptance — latest user correction

The user explicitly requests icon-style company marks like the supplied TradingView stock list, including future companies. Full horizontal corporate wordmarks are not acceptable substitutes in these compact slots.

- Obtain compact symbol artwork with a square canvas/safe area suitable for a circular slot. Keep the provider's colors and internal spacing; the company name remains adjacent text.
- Store `presentation: icon` explicitly. Preserve `wordmark` separately for report/document contexts; UI resolution must not silently display a wordmark when an icon is missing.
- Prefer a real compact mark (e.g. NVIDIA eye, Microsoft squares). When a brand/provider uses lettering inside its icon composition, retain the genuine compact composition rather than inventing a letter or cropping an official wordmark.
- A square file alone cannot prove it is a valid icon. Aspect ratio is a coarse input check; provider semantics, legal entity/security match and sampled visual review remain necessary.
- Current prototype uses six reviewed TradingView security-page PNGs, with `provider`, `symbol`, `sourcePage`, `assetUrl`, `sha256` and local cache. This is a limited selection, not proof of batch access, an official asset distribution API, licensing or total-market coverage.
- The background batch task must evaluate eligible providers, support explicit entity/exchange/ticker/domain inputs, preserve source distinctions, and report missing/ambiguous icons. Do not expand a hand-coded list as the general solution.


## Required new-company workflow (confirmed 2026-09-29)

For every newly added company, icon acquisition and local caching are part of onboarding, not an optional six-company demo step. Resolve explicit entity/security/domain identity, obtain a compact icon, validate and save the image locally, record provenance, then link the local asset to the company record. Reuse an existing verified local icon before fetching again.

The visible UI must load the local asset so a remote provider outage does not remove previously obtained icons. A failed/mismatched acquisition stays pending and is retried or routed to another reviewed source; do not mark icon onboarding complete with a letter placeholder. Company research may still remain accessible while icon acquisition is pending, with the gap explicitly recorded.

Acceptance: a company outside the initial six receives a correct, locally cached icon without adding company-specific rendering code; after the provider is unavailable, the cached icon still loads; failure and retry cannot replace another entity's icon or downgrade a verified asset. Current single-company importer and six cached icons are implemented; automatic new-company backend wiring and broader batch coverage remain pending.
