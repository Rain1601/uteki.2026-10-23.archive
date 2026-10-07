"""A frozen-input, standard-library-only research backtest (no model/API calls)."""
from collections import Counter
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def total_return(start_adjusted, end_adjusted):
    if not all(math.isfinite(x) and x > 0 for x in [start_adjusted, end_adjusted]):
        raise ValueError("Prices must be positive finite values")
    return end_adjusted / start_adjusted - 1


def adjusted_open(bar):
    return bar["open"] * bar["adjclose"] / bar["close"]


def portfolio_nav(price_paths, entry_prices):
    if not price_paths or set(price_paths) != set(entry_prices):
        raise ValueError("Holdings and entries must match")
    dates = set(next(iter(price_paths.values())))
    if not dates or any(set(p) != dates for p in price_paths.values()):
        raise ValueError("Every holding must have every valuation date")
    n = len(price_paths)
    return {d: math.fsum(price_paths[s][d] / entry_prices[s] for s in price_paths) / n for d in sorted(dates)}


def select_groups(ranked_symbols, top_n=50, fraction=0.5):
    if len(set(ranked_symbols)) != len(ranked_symbols) or not 0 < fraction < 1 or top_n < 1:
        raise ValueError("Invalid ranking or group scope")
    k = math.ceil(len(ranked_symbols) * fraction)
    return {"top_n": ranked_symbols[:top_n], "top_half": ranked_symbols[:k], "bottom_half": ranked_symbols[k:], "all_rankable": ranked_symbols[:]}


def yahoo_bars(symbol, cfg):
    p = ROOT / "raw" / "prices" / (symbol.replace("^", "_") + ".json")
    r = json.loads(p.read_text())["chart"]["result"][0]
    expected = cfg.get("ticker_aliases", {}).get(symbol, symbol)
    if r["meta"]["symbol"] != expected or r["meta"].get("currency") != "USD":
        raise ValueError(f"Identity/currency mismatch: {symbol}")
    q = r["indicators"]["quote"][0]
    a = r["indicators"]["adjclose"][0]["adjclose"]
    bars = {}
    for i, stamp in enumerate(r["timestamp"]):
        date = dt.datetime.fromtimestamp(stamp, ZoneInfo("America/New_York")).date().isoformat()
        values = [q["open"][i], q["close"][i], a[i]]
        if not all(v is not None and math.isfinite(v) and v > 0 for v in values):
            continue
        if date in bars:
            raise ValueError(f"Duplicate date {symbol} {date}")
        bars[date] = dict(zip(["open", "close", "adjclose"], values))
    return bars


def historical_bars(symbol, cfg, dividends, supplements):
    """HTML table parsing for delisted issuers, with explicit dividend ledger."""
    p = ROOT / "raw" / f"{symbol.lower()}-chartexchange.html"
    rows = re.findall(r'<tr id="([0-9-]+)">(.*?)</tr>', p.read_text(), re.S)
    bars = {}
    for date, row in rows:
        cells = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 5 or cells[0] != date:
            raise ValueError(f"Historical table layout changed: {symbol}")
        bars[date] = {"open": float(cells[1].replace(",", "")), "close": float(cells[4].replace(",", ""))}
    if symbol in supplements:
        s = supplements[symbol]
        bars[s["date"]] = {"open": s["close"], "close": s["close"]}
    if cfg["ranking_start"] not in bars:
        raise ValueError(f"Missing ranking anchor for {symbol}")
    # Reinvest dividend receivables at each ex-date closing price. No payments
    # on/before the ranking anchor enter the subsequent year's return.
    shares = 1.0
    ledger = dividends[symbol]["events"]
    for d in ledger:
        if cfg["ranking_start"] < d < cfg["end_date"] and d not in bars:
            raise ValueError(f"Missing ex-dividend close {symbol} {d}")
    for date in sorted(bars):
        if date > cfg["ranking_start"]:
            shares *= 1 + ledger.get(date, 0) / bars[date]["close"]
        bars[date]["adjclose"] = bars[date]["close"] * shares
    return bars


def apply_actions(all_bars, cfg, dates):
    actions = []
    for symbol, event in cfg.get("cash_events", {}).items():
        if event["date"] > cfg["end_date"]:
            continue
        bars = all_bars[symbol]
        last = max(d for d in bars if d < event["date"])
        units = bars[last]["adjclose"] / bars[last]["close"]
        for date in dates:
            if date >= event["date"]:
                bars[date] = {"open": event["cash"], "close": event["cash"], "adjclose": event["cash"] * units}
        actions.append({"symbol": symbol, "kind": "cash", "date": event["date"], "units": units, **event})
    for symbol, event in cfg.get("stock_events", {}).items():
        if event["date"] > cfg["end_date"]:
            continue
        bars = all_bars[symbol]
        last = max(d for d in bars if d < event["date"])
        units = bars[last]["adjclose"] / bars[last]["close"]
        successor = all_bars[event["successor"]]
        first = next(d for d in dates if d >= event["date"])
        factor = successor[first]["adjclose"] / successor[first]["close"]
        for date in dates:
            if date >= first:
                value = units * event["ratio"] * successor[date]["adjclose"] / factor
                bars[date] = {"open": value, "close": value, "adjclose": value}
        actions.append({"symbol": symbol, "kind": "stock", "units": units, **event})
    return actions


def maximum_drawdown(nav):
    peak, worst = 1.0, 0.0
    for value in nav.values():
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def write_csv(name, rows):
    if not rows:
        return
    with (ROOT / name).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    if not cfg["ranking_start"] < cfg["ranking_end"] < cfg["entry_date"] <= cfg["end_date"]:
        raise ValueError("Signal must precede execution")
    if cfg["weighting"] != "equal_initial_dollars_buy_and_hold" or cfg["transaction_cost_bps_per_side"] != 0:
        raise ValueError("Unsupported weighting/cost policy")
    universe = list(csv.DictReader((ROOT / "raw/universe.csv").open()))
    if any(r["Universe Date"] != cfg["universe_date"] for r in universe):
        raise ValueError("Universe date mismatch")
    dividends = json.loads((ROOT / "supplemental_dividends.json").read_text())
    supplements = json.loads((ROOT / "supplemental_prices.json").read_text())
    symbols = [r["Symbol"] for r in universe]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Duplicate constituent")
    bars, gaps = {}, []
    for s in symbols + [cfg["benchmark"], cfg["price_index"]]:
        try:
            bars[s] = historical_bars(s, cfg, dividends, supplements) if s in dividends else yahoo_bars(s, cfg)
        except Exception as exc:
            gaps.append({"symbol": s, "reason": str(exc)})
    if gaps:
        (ROOT / "data_gaps.json").write_text(json.dumps(gaps, indent=2, ensure_ascii=False))
        raise ValueError(f"Unresolved data gaps: {gaps}")
    dates = sorted(d for d in bars[cfg["benchmark"]] if cfg["entry_date"] <= d <= cfg["end_date"])
    if dates[0] != cfg["entry_date"] or dates[-1] != cfg["end_date"]:
        raise ValueError("Benchmark endpoints unavailable")
    actions = apply_actions(bars, cfg, dates)
    excluded, ranking = [], {}
    for s in symbols:
        reason = cfg.get("ranking_exclusions", {}).get(s)
        if reason:
            excluded.append({"symbol": s, "reason": reason})
        elif not all(d in bars[s] for d in [cfg["ranking_start"], cfg["ranking_end"]]):
            raise ValueError(f"Unexpected ranking gap for {s}; define eligibility explicitly")
        else:
            ranking[s] = total_return(bars[s][cfg["ranking_start"]]["adjclose"], bars[s][cfg["ranking_end"]]["adjclose"])
    ranked = sorted(ranking, key=lambda s: (-ranking[s], s))
    selection = select_groups(ranked, cfg["top_n"], cfg["top_fraction"])
    selection.update({"all": symbols, "spy": [cfg["benchmark"]], "index": [cfg["price_index"]]})
    labels = {"top_n": f"2025 前 {cfg['top_n']} 名", "top_half": f"2025 前 50%（{len(selection['top_half'])} 只）", "bottom_half": "2025 后 50%", "all_rankable": f"可排名全体等权（{len(ranked)} 只）", "all": f"年末全体等权（{len(symbols)} 只）", "spy": "标普 500 ETF（SPY，含股息）", "index": "标普 500 价格指数（不含股息）"}
    entries, paths = {}, {}
    for s in set(symbols + [cfg["benchmark"], cfg["price_index"]]):
        missing = [d for d in dates if d not in bars[s]]
        if missing:
            gaps.append({"symbol": s, "reason": f"Missing {len(missing)} holding dates: {missing[:6]}"})
            continue
        entries[s] = adjusted_open(bars[s][cfg["entry_date"]])
        paths[s] = {d: bars[s][d]["adjclose"] for d in dates}
    if gaps:
        (ROOT / "data_gaps.json").write_text(json.dumps(gaps, indent=2))
        raise ValueError(str(gaps))
    groups = []
    for key, members in selection.items():
        nav = portfolio_nav({s: paths[s] for s in members}, {s: entries[s] for s in members})
        # A non-trading, explicit opening point keeps first-day gains visible.
        groups.append({"id": key, "label": labels[key], "count": len(members), "return_total": nav[dates[-1]] - 1, "excess_spy": None, "excess_all": None, "max_drawdown": maximum_drawdown(nav), "nav": [{"date": cfg["entry_date"] + " open", "value": 1.0}] + [{"date": d, "value": v} for d, v in nav.items()]})
    returns = {g["id"]: g["return_total"] for g in groups}
    for g in groups:
        g["excess_spy"] = g["return_total"] - returns["spy"]
        g["excess_all"] = g["return_total"] - returns["all_rankable"]
        g["cvr_max_additional_return"] = math.fsum(cfg["cash_events"].get(s, {}).get("unpriced_cvr_max", 0) / bars[s][cfg["entry_date"]]["open"] / len(selection[g["id"]]) for s in selection[g["id"]])
    stocks = []
    for r in universe:
        s = r["Symbol"]
        stocks.append({"symbol": s, "name": r["Security"], "sector": r["GICS Sector"], "rank": ranked.index(s) + 1 if s in ranking else None, "ranking_return": ranking.get(s), "holding_return": total_return(entries[s], paths[s][dates[-1]]), "groups": [key for key, m in selection.items() if s in m], "entry_open": bars[s][cfg["entry_date"]]["open"], "adjusted_entry": entries[s], "adjusted_end": paths[s][dates[-1]], "ranking_start_adjusted": bars[s].get(cfg["ranking_start"], {}).get("adjclose"), "ranking_end_adjusted": bars[s].get(cfg["ranking_end"], {}).get("adjclose")})
    stocks.sort(key=lambda r: r["rank"] or 100000)
    sector_all = Counter(r["sector"] for r in stocks if r["rank"])
    sector_bottom = Counter(r["sector"] for r in stocks if r["symbol"] in selection["bottom_half"])
    nb = len(selection["bottom_half"])
    sectors = [{"sector": sector, "universe_count": count, "bottom_count": sector_bottom[sector], "bottom_share": sector_bottom[sector] / nb, "hit_rate": sector_bottom[sector] / count, "lift": (sector_bottom[sector] / count) / (nb / len(ranked))} for sector, count in sector_all.items()]
    sectors.sort(key=lambda r: (-r["hit_rate"], -r["bottom_count"], r["sector"]))
    extended_ranking = dict(ranking)
    additions = []
    for s, rule in cfg.get("partial_year_ranking", {}).items():
        if s not in symbols or s in ranking or not cfg["ranking_start"] < rule["start_date"] < cfg["ranking_end"]:
            raise ValueError("Invalid partial-year ranking scope")
        ret = total_return(bars[s][rule["start_date"]]["adjclose"], bars[s][cfg["ranking_end"]]["adjclose"])
        extended_ranking[s] = ret
        additions.append({"symbol": s, "start_date": rule["start_date"], "ranking_return": ret, "source": rule["source"]})
    extended_order = sorted(extended_ranking, key=lambda s: (-extended_ranking[s], s))
    extended = select_groups(extended_order, cfg["top_n"], cfg["top_fraction"])
    sensitivity_groups, changes = [], []
    for gid in ["top_n", "top_half", "bottom_half", "all_rankable"]:
        members = extended[gid]
        nav = portfolio_nav({s: paths[s] for s in members}, {s: entries[s] for s in members})
        ret = nav[dates[-1]] - 1
        label = {"top_n": "前 50 名 · 含上市后收益", "top_half": "前 50% · 含上市后收益", "bottom_half": "后半组 · 含上市后收益", "all_rankable": "全体 503 只等权"}[gid]
        sensitivity_groups.append({"id": gid, "label": label, "count": len(members), "return_total": ret, "excess_spy": ret - returns["spy"], "excess_all": ret - returns["all"], "max_drawdown": maximum_drawdown(nav), "nav": [{"date": cfg["entry_date"] + " open", "value": 1.0}] + [{"date": d, "value": v} for d, v in nav.items()]})
        changes.append({"group": gid, "added": [s for s in members if s not in selection[gid]], "removed": [s for s in selection[gid] if s not in members]})
    for row in additions:
        row["rank"] = extended_order.index(row["symbol"]) + 1
    sensitivity = {"label": "纳入 2025 年新上市证券的敏感性对照", "description": "503 只全部排名；其中 SNDK、Q、PSKY 从正式上市首日收盘计算至 2025 年末，其余仍计算全年收益。这是另一条可在年末执行的选股规则，但把不同长度的排名区间混用，不应称为严格全年排名。", "universe_count": len(extended_order), "groups": sensitivity_groups, "additions": additions, "changes": changes}
    limitations = [
        "这是一个持有期的历史验证，不能据此证明策略未来稳定有效。",
        "历史名单为第三方保存的 iShares / tidyquant 快照，两份证券集合一致；快照内价格可能滞后，本实验未将其用于收益计算。不是授权指数历史数据库。",
        "503 只是证券数，包含同一公司的不同股类；等权按证券分配。排名池按年末名单固定，不在年中随指数调整换股。",
        "SNDK、Q 于 2025 年分拆上市；PSKY 的 2025 合并前权益续接未完整核验。三者保留在 503 只全体持有对照，排除全年排名，因此前半组来自 500 只可排名证券。",
        "主体使用 Yahoo 调整收盘价近似股息再投资总收益。CTRA、AVB、EA 的退市前历史用公开价格及已核对股息表重建，股息按除息日收盘再投资。不同供应商的调整规则和价格精度可能造成小幅差异。",
        "现金收购款从完成日计为现金并保持零利息；换股后持有换得的股票，不重新等权。HOLX 另有最高每原股 3 美元的不可交易或有支付权，主表按零估值，报告提供最高额敏感性；未声称其真实价值为零。",
        "未逐只独立审计 Yahoo 对拆分、分拆及其他分派的历史调整；PSKY 前身权益因此未用于排名。",
        "允许碎股；未计交易费用、买卖价差、滑点和税费。开盘价是历史行情模拟，未真实下单。",
        "SPY 是可投资的标普跟踪 ETF，其复权收益含股息并已受基金费用影响；价格指数不含股息，两者分别标注。所有组均从 2026-01-02 开盘比较，故不等同于从 2025-12-31 收盘计算的新闻 YTD。",
        "行业统计仅描述后半组分布，并未据此另设行业排除策略。命中率=该行业落入后半组数量/该行业可排名数量；lift=命中率/全体后半组比例。",
    ]
    result = {"config": cfg, "universe_count": len(symbols), "rankable_count": len(ranked), "excluded": excluded, "gaps": gaps, "groups": groups, "stocks": stocks, "sectors": sectors, "benchmark_label": labels["spy"], "limitations": limitations, "status": "limited", "corporate_actions": actions, "holding_trading_days": len(dates), "price_index_conventional_ytd": total_return(bars[cfg["price_index"]][cfg["ranking_end"]]["close"], bars[cfg["price_index"]][cfg["end_date"]]["close"]), "validation": {"no_unresolved_price_gaps": not gaps, "all_nav_calendars_equal": True, "signal_before_entry": True, "top_half_plus_bottom_equals_ranking": selection["top_half"] + selection["bottom_half"] == ranked, "independent_mean_check": all(abs(g["return_total"] - math.fsum(total_return(entries[s], paths[s][dates[-1]]) for s in selection[g["id"]]) / g["count"]) < 1e-12 for g in groups)}}
    result["sensitivity"] = sensitivity
    result["validation"]["sensitivity_covers_all_constituents"] = set(extended_order) == set(symbols)
    (ROOT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    write_csv("stocks.csv", stocks)
    write_csv("sector_distribution.csv", sectors)
    write_csv("summary.csv", [{k: v for k, v in g.items() if k != "nav"} for g in groups])
    write_csv("sensitivity_summary.csv", [{k: v for k, v in g.items() if k != "nav"} for g in sensitivity_groups])
    write_csv("ranking_503_sensitivity.csv", [{"rank": i + 1, "symbol": s, "ranking_start": cfg.get("partial_year_ranking", {}).get(s, {}).get("start_date", cfg["ranking_start"]), "ranking_return": extended_ranking[s], "holding_return": total_return(entries[s], paths[s][dates[-1]]), "groups": [gid for gid, members in extended.items() if s in members]} for i, s in enumerate(extended_order)])
    write_csv("daily_nav.csv", [{"date": row["date"], **{g["id"]: g["nav"][i]["value"] for g in groups}} for i, row in enumerate(groups[0]["nav"])])
    audited = [p for p in ROOT.rglob("*") if p.is_file() and (p.parent.name == "raw" or p.parent.name == "prices" or p.name in ["config.json", "supplemental_dividends.json", "supplemental_prices.json", "backtest.py"])]
    (ROOT / "reproduction_manifest.json").write_text(json.dumps({"files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(audited)}, "inputs": "Frozen local files; no model inference", "computed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2))
    print(json.dumps({"universe": len(symbols), "rankable": len(ranked), "groups": [{k: g[k] for k in ["id", "count", "return_total", "excess_spy", "excess_all"]} for g in groups], "gaps": gaps, "validation": result["validation"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
