"""Freeze pre-2026 Yahoo history for explicitly selected top-ten constituents."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    results = json.loads((ROOT.parent / "results.json").read_text())
    symbols = [s["symbol"] for s in results["stocks"] if "top_10" in s["groups"]]
    symbols.append(results["config"]["benchmark"])
    end = int(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp())

    def one(symbol):
        query = urllib.parse.urlencode({"period1": 0, "period2": end, "interval": "1d", "events": "div,splits"})
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
        path = ROOT / "raw" / f"{symbol}.json"
        try:
            if not path.exists():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = response.read()
                json.loads(data)
                path.write_bytes(data)
            r = json.loads(path.read_text())["chart"]["result"][0]
            if r["meta"]["symbol"] != symbol or not r.get("timestamp"):
                raise ValueError("Identity/history invalid")
            return {"symbol": symbol, "status": "ok", "bars": len(r["timestamp"]), "url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        except Exception as exc:
            return {"symbol": symbol, "status": "error", "url": url, "error": str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(one, symbols))
    (ROOT / "history_manifest.json").write_text(json.dumps({"downloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "selection_source": "../results.json top_10", "records": records}, indent=2))
    for record in records:
        print(json.dumps({k: v for k, v in record.items() if k not in ["url", "sha256"]}), flush=True)


if __name__ == "__main__":
    main()
