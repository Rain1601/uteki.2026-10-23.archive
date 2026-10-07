"""Download and freeze public data; no model calls or third-party packages."""
import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe-url", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    raw = ROOT / "raw"
    universe = raw / "universe.csv"
    if not universe.exists():
        source_path = raw / "ishares-20251231.csv"
        if not source_path.exists():
            download(args.universe_url, source_path)
        source = list(csv.DictReader(source_path.open()))
        alias = {"BFB": "BF-B", "BRKB": "BRK-B"}
        with universe.open("w") as f:
            writer = csv.DictWriter(f, fieldnames=["Symbol", "Security", "GICS Sector", "ISIN", "CUSIP", "Universe Date"])
            writer.writeheader()
            for r in source:
                if r["asset_class"] == "Equity":
                    if r["date"] != cfg["universe_date"]:
                        raise ValueError("Universe date mismatch")
                    writer.writerow({"Symbol": alias.get(r["symbol"], r["symbol"].replace(".", "-")), "Security": r["name"], "GICS Sector": r["sector"], "ISIN": r["ISIN"], "CUSIP": r["CUSIP"], "Universe Date": r["date"]})
    rows = list(csv.DictReader(universe.open()))
    if not rows or "Symbol" not in rows[0]:
        raise ValueError("Universe requires Symbol column")
    symbols = sorted({x["Symbol"].replace(".", "-") for x in rows} | {cfg["benchmark"], cfg["price_index"]})
    start = dt.datetime.fromisoformat(cfg["ranking_start"]).replace(tzinfo=dt.timezone.utc) - dt.timedelta(days=4)
    end = dt.datetime.fromisoformat(cfg["end_date"]).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
    records = []

    def one(symbol):
        path = raw / "prices" / (symbol.replace("^", "_") + ".json")
        query = urllib.parse.urlencode({"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": "1d", "events": "div,splits"})
        price_symbol = cfg.get("ticker_aliases", {}).get(symbol, symbol)
        url = "https://query2.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(price_symbol) + "?" + query
        try:
            data = path.read_bytes() if path.exists() else download(url, path)
            payload = json.loads(data)
            result = payload["chart"]["result"]
            if not result or not result[0].get("timestamp"):
                raise ValueError(str(payload.get("chart", {}).get("error")))
            r = result[0]
            if r["meta"]["symbol"] != price_symbol:
                raise ValueError("Ticker identity mismatch: " + str(r["meta"]["symbol"]))
            return {"symbol": symbol, "price_symbol": price_symbol, "status": "ok", "url": url, "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(), "bars": len(r["timestamp"])}
        except Exception as exc:
            return {"symbol": symbol, "status": "error", "url": url, "error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, record in enumerate(pool.map(one, symbols), 1):
            records.append(record)
            if n % 50 == 0 or record["status"] != "ok":
                print(json.dumps({"completed": n, "total": len(symbols), "last": record["symbol"], "status": record["status"], "error": record.get("error")}), flush=True)
    manifest = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "universe_url": args.universe_url, "universe_sha256": hashlib.sha256(universe.read_bytes()).hexdigest(), "universe_rows": len(rows), "config_sha256": hashlib.sha256((ROOT / "config.json").read_bytes()).hexdigest(), "prices": records}
    (ROOT / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": sum(x["status"] == "ok" for x in records), "failed": [x["symbol"] for x in records if x["status"] != "ok"]}), flush=True)


if __name__ == "__main__":
    main()
