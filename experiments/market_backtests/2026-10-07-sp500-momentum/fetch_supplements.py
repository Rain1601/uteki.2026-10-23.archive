"""Freeze explicitly selected exception sources. Never solves a CAPTCHA."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "raw/ctra-chartexchange.html": "https://chartexchange.com/symbol/nyse-ctra/historical/",
    "raw/day-chartexchange.html": "https://chartexchange.com/symbol/nyse-day/historical/",
    "raw/holx-chartexchange.html": "https://chartexchange.com/symbol/nasdaq-holx/historical/",
    "raw/avb-chartexchange.html": "https://chartexchange.com/symbol/nyse-avb/historical/",
    "raw/ea-chartexchange.html": "https://chartexchange.com/symbol/nasdaq-ea/historical/",
    "raw/tidyquant-20251231.csv": "https://raw.githubusercontent.com/riazarbi/sp500-scraper/main/tidyquant/sp500/csv/20251231.csv",
    "raw/actions-bny.html": "https://www.bny.com/corporate/global/en/about-us/newsroom/press-release/bny-announces-planned-change-of-stock-ticker-symbol-to-bny-130465.html",
    "raw/actions-marsh.html": "https://www.marsh.com/en/corp/about/news/marsh-mclennan-to-change-nyse-symbol-to-mrsh.html",
    "raw/actions-wbd.html": "https://www.sec.gov/Archives/edgar/data/1437107/000119312526415055/d200872d8k.htm",
    "raw/actions-paramount.html": "https://ir.paramount.com/node/73436/html",
    "raw/actions-avb.html": "https://www.sec.gov/Archives/edgar/data/915912/000110465926097833/tm2623381d1_ex99-1.htm",
}


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    for kind in ["cash_events", "stock_events", "partial_year_ranking"]:
        for symbol, rule in cfg.get(kind, {}).items():
            SOURCES.setdefault(f"raw/action-{kind}-{symbol}.html", rule["source"])
    ledger = []
    for filename, url in SOURCES.items():
        path = ROOT / filename
        try:
            if not path.exists():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read()
                if any(x in data.lower() for x in [b"captcha challenge", b"request rate threshold exceeded", b"just a moment..."]):
                    raise ValueError("Provider served challenge; source remains web-reviewed only")
                path.write_bytes(data)
            ledger.append({"path": filename, "url": url, "status": "saved", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        except Exception as exc:
            ledger.append({"path": filename, "url": url, "status": "not_saved", "reason": str(exc)})
    (ROOT / "supplement_sources.json").write_text(json.dumps(ledger, indent=2))
    print(json.dumps({"saved": sum(x["status"] == "saved" for x in ledger), "not_saved": [x["url"] for x in ledger if x["status"] != "saved"]}))


if __name__ == "__main__":
    main()
