# Company icon sources — 2026-09-29

The current UI uses compact square symbol icons from TradingView, as requested by the user, displayed in circular slots. These are third-party security-page icons, not assets obtained directly from each company's official media library. The original 600 × 600 PNG bytes, backgrounds and internal clear space are retained.

| Company domain | Security | Verified source page | Local icon |
| --- | --- | --- | --- |
| `abc.xyz` | `NASDAQ:GOOGL` | [NASDAQ:GOOGL](https://www.tradingview.com/symbols/NASDAQ-GOOGL/) | `alphabet-icon.png` |
| `microsoft.com` | `NASDAQ:MSFT` | [NASDAQ:MSFT](https://www.tradingview.com/symbols/NASDAQ-MSFT/) | `microsoft-icon.png` |
| `nvidia.com` | `NASDAQ:NVDA` | [NASDAQ:NVDA](https://www.tradingview.com/symbols/NASDAQ-NVDA/) | `nvidia-icon.png` |
| `costco.com` | `NASDAQ:COST` | [NASDAQ:COST](https://www.tradingview.com/symbols/NASDAQ-COST/) | `costco-icon.png` |
| `arista.com` | `NYSE:ANET` | [NYSE:ANET](https://www.tradingview.com/symbols/NYSE-ANET/) | `arista-icon.png` |
| `eaton.com` | `NYSE:ETN` | [NYSE:ETN](https://www.tradingview.com/symbols/NYSE-ETN/) | `eaton-icon.png` |

`registry.json` records the actual asset URL observed in each source page, SHA-256, retrieval time, provider, explicit security and `presentation: icon`. Alphabet uses the G graphic selected by TradingView for NASDAQ:GOOGL; the company identity remains Alphabet / abc.xyz. Costco, Arista and Eaton use the provider's compact square compositions containing their brand lettering, rather than invented single-letter symbols.

Previously downloaded official wordmarks and provenance are retained in `wordmarks.json`; those files are not used in the icon slots. Images are not redrawn, recolored or internally cropped. Circular clipping affects the background corners only; artwork keeps the provider's built-in safe area.

Future companies must follow the same icon presentation requirement. An available wordmark is not sufficient. Website-icon discovery and batch-provider coverage remain separate from visual/identity verification; current six-company selection does not prove broad provider coverage. See `../../tools/ICON_REQUIREMENTS.md`.
