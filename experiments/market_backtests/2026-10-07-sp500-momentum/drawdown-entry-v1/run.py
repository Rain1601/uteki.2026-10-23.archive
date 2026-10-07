"""Frozen pre-2026 calibration; single-entry 2026 pullback comparison."""
from collections import OrderedDict
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import backtest


def maximum_drawdown(prices):
    peak = -math.inf
    best = {"depth": 0.0, "peak_date": None, "trough_date": None}
    peak_date = None
    for date, price in sorted(prices.items(), key=lambda item: (item[0][:10], 0 if item[0].endswith(" open") else 1)):
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid price")
        if price >= peak:
            peak, peak_date = price, date
        depth = 1 - price / peak
        if depth > best["depth"]:
            best = {"depth": depth, "peak_date": peak_date, "trough_date": date}
    return best


def drawdown_episodes(prices):
    peak, peak_date, active = -math.inf, None, None
    episodes = []
    for date, price in sorted(prices.items()):
        if price >= peak:
            if active is not None:
                active.update(recovery_date=date, recovered=True)
                episodes.append(active)
                active = None
            peak, peak_date = price, date
        else:
            depth = 1 - price / peak
            if active is None:
                active = {"peak_date": peak_date, "trough_date": date, "depth": depth, "recovery_date": None, "recovered": False}
            elif depth > active["depth"]:
                active.update(depth=depth, trough_date=date)
    if active is not None:
        episodes.append(active)
    return episodes


def load_history(symbol):
    payload = json.loads((ROOT / "raw" / f"{symbol}.json").read_text())
    result = payload["chart"]["result"][0]
    if result["meta"]["symbol"] != symbol or result["meta"].get("currency") != "USD":
        raise ValueError(f"History identity/currency mismatch {symbol}")
    prices = {}
    for stamp, price in zip(result["timestamp"], result["indicators"]["adjclose"][0]["adjclose"]):
        date = dt.datetime.fromtimestamp(stamp, ZoneInfo("America/New_York")).date().isoformat()
        if price is not None and math.isfinite(price) and price > 0:
            prices[date] = price
    return prices


def historical_stats(symbol, prices, calendar, cfg):
    identity_start = cfg.get("identity_starts", {}).get(symbol, {}).get("date", min(prices))
    start = max(cfg["history_start"], identity_start, min(prices))
    window = {d: p for d, p in prices.items() if start <= d <= cfg["history_end"]}
    if not window or max(window) != cfg["history_end"]:
        raise ValueError(f"Incomplete historical endpoint {symbol}")
    missing = sorted(set(d for d in calendar if min(window) <= d <= cfg["history_end"]) - set(window))
    if missing:
        raise ValueError(f"Missing historical trading dates for {symbol}: {missing[:5]}")
    annual = []
    for year in range(int(cfg["history_start"][:4]) + 1, int(cfg["history_end"][:4]) + 1):
        days = sorted(d for d in calendar if d.startswith(str(year)))
        if not days:
            continue
        anchor = max(d for d in calendar if d < days[0])
        complete = anchor >= start and all(d in prices for d in [anchor] + days)
        if complete:
            values = {d: prices[d] for d in [anchor] + days}
            annual.append({"year": year, **maximum_drawdown(values)})
    if not annual:
        raise ValueError(f"No full calendar years for {symbol}")
    episodes = drawdown_episodes(window)
    completed = [e["depth"] for e in episodes if e["recovered"]]
    maxdd = maximum_drawdown(window)
    return {"symbol": symbol, "start": min(window), "end": max(window), "bars": len(window), "full_years": [a["year"] for a in annual], "max_drawdown": maxdd["depth"], "max_peak_date": maxdd["peak_date"], "max_trough_date": maxdd["trough_date"], "half_max": maxdd["depth"] / 2, "mean_annual": math.fsum(a["depth"] for a in annual) / len(annual), "mean_episode": math.fsum(e["depth"] for e in episodes) / len(episodes) if episodes else 0, "episode_count": len(episodes), "unrecovered_episode_count": sum(not e["recovered"] for e in episodes), "completed_episode_mean": math.fsum(completed) / len(completed) if completed else None, "annual": annual, "episodes": episodes}


def simulate_entry(bars, dates, threshold, reference, cash_event_date=None):
    if not 0 < threshold < 1 or reference not in ["year_open", "running_peak"]:
        raise ValueError("Invalid threshold/reference")
    start_open = backtest.adjusted_open(bars[dates[0]])
    rolling_peak = start_open
    signal, fill = None, None
    for i, date in enumerate(dates):
        if cash_event_date is not None and date >= cash_event_date:
            break
        close = bars[date]["adjclose"]
        rolling_peak = max(rolling_peak, close)
        anchor = start_open if reference == "year_open" else rolling_peak
        trigger = anchor * (1 - threshold)
        if close <= trigger:
            signal = {"date": date, "anchor": anchor, "threshold_level": trigger, "signal_close": close, "drawdown": 1 - close / anchor}
            if i + 1 < len(dates):
                candidate = dates[i + 1]
                if cash_event_date is None or candidate < cash_event_date:
                    fill = {"date": candidate, "adjusted_open": backtest.adjusted_open(bars[candidate]), "raw_open": bars[candidate]["open"]}
            break
    nav = {d: (bars[d]["adjclose"] / fill["adjusted_open"] if fill and d >= fill["date"] else 1.0) for d in dates}
    bought = fill is not None
    return {"threshold": threshold, "reference": reference, "signal": signal, "fill": fill, "status": "bought" if bought else "signal_unfilled" if signal else "no_signal", "return_total": nav[dates[-1]] - 1, "nav": nav, "entry_vs_year_open": fill["adjusted_open"] / start_open - 1 if bought else None, "peak_before_entry_vs_year_open": signal["anchor"] / start_open - 1 if signal else None, "wait_sessions": dates.index(fill["date"]) if bought else len(dates), "holding_sessions": sum(d >= fill["date"] for d in dates) if bought else 0}


def export_csv(name, rows):
    with (ROOT / name).open("w", newline="", encoding="utf-8-sig") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    parent = json.loads((ROOT.parent / "results.json").read_text())
    pcfg = parent["config"]
    if not cfg["history_end"] < cfg["entry_date"] <= cfg["end_date"] or cfg["cash_interest"] != 0 or cfg["cost_bps"] != 0 or cfg["buys_per_security"] != 1:
        raise ValueError("Unsupported calibration/execution policy")
    if any(cfg[k] != pcfg[k] for k in ["entry_date", "end_date"]):
        raise ValueError("Comparison dates must match frozen baseline")
    securities = [s for s in parent["stocks"] if cfg["selection_group"] in s["groups"]]
    symbols = [s["symbol"] for s in securities]
    if len(symbols) != 10:
        raise ValueError("Expected explicitly selected ten securities")
    historical_calendar = load_history(pcfg["benchmark"])
    stats = [historical_stats(s, load_history(s), historical_calendar, cfg) for s in symbols]
    by_symbol = {s["symbol"]: s for s in stats}
    bars = {s: backtest.yahoo_bars(s, pcfg) for s in symbols}
    benchmark = backtest.yahoo_bars(pcfg["benchmark"], pcfg)
    dates = sorted(d for d in benchmark if cfg["entry_date"] <= d <= cfg["end_date"])
    if dates[0] != cfg["entry_date"] or dates[-1] != cfg["end_date"]:
        raise ValueError("Missing execution endpoints")
    local_actions = {**pcfg, "cash_events": {s: e for s, e in pcfg["cash_events"].items() if s in symbols}, "stock_events": {s: e for s, e in pcfg["stock_events"].items() if s in symbols}}
    backtest.apply_actions(bars, local_actions, dates)
    if any(any(d not in bars[s] for d in dates) for s in symbols):
        raise ValueError("Incomplete holding calendar")
    baseline = next(g for g in parent["groups"] if g["id"] == cfg["selection_group"])
    reconstructed = math.fsum(bars[s][dates[-1]]["adjclose"] / backtest.adjusted_open(bars[s][dates[0]]) - 1 for s in symbols) / len(symbols)
    if abs(reconstructed - baseline["return_total"]) > 1e-12:
        raise ValueError("Baseline drift")
    baseline_cash = math.fsum(bars[s][dates[-1]]["adjclose"] / backtest.adjusted_open(bars[s][dates[0]]) for s in local_actions["cash_events"] if local_actions["cash_events"][s]["date"] <= dates[-1]) / 10 / (1 + baseline["return_total"])
    groups = [{"id": "buy_at_start", "label": "年初直接买入", "return_total": baseline["return_total"], "max_drawdown": -baseline["max_drawdown"], "bought_count": 10, "unspent_initial_weight": 0.0, "ending_cash_weight": baseline_cash, "nav": baseline["nav"], "excess_baseline": 0.0}]
    all_entries = []
    thresholds = {"half_max": "历史最大回撤的一半", "mean_annual": "平均年度最大回撤", "mean_episode": "平均每次回撤"}
    refs = {"year_open": "从年初价下跌", "running_peak": "从过程新高回撤"}
    for ref in cfg["references"]:
        for threshold in cfg["thresholds"]:
            name = f"{ref}__{threshold}"
            entries = []
            for security in securities:
                s = security["symbol"]
                event = pcfg["cash_events"].get(s)
                result = simulate_entry(bars[s], dates, by_symbol[s][threshold], ref, event["date"] if event else None)
                entries.append({"symbol": s, "name": security["name"], "scenario": name, "baseline_return": security["holding_return"], **result})
            nav = {d: math.fsum(r["nav"][d] for r in entries) / len(symbols) for d in dates}
            bought = sum(r["status"] == "bought" for r in entries)
            total = nav[dates[-1]] - 1
            mdd = maximum_drawdown({dates[0] + " open": 1, **nav})["depth"]
            # cash acquisitions are distinct from capital never deployed.
            ending_cash_value = math.fsum((1.0 if r["status"] != "bought" else r["nav"][dates[-1]] if r["symbol"] in local_actions["cash_events"] and local_actions["cash_events"][r["symbol"]]["date"] <= dates[-1] else 0.0) for r in entries) / len(symbols)
            groups.append({"id": name, "label": refs[ref] + " · " + thresholds[threshold], "reference": ref, "threshold_type": threshold, "return_total": total, "excess_baseline": total - baseline["return_total"], "max_drawdown": mdd, "bought_count": bought, "unspent_initial_weight": (len(symbols) - bought) / len(symbols), "ending_cash_weight": ending_cash_value / nav[dates[-1]], "nav": [{"date": dates[0] + " open", "value": 1}] + [{"date": d, "value": v} for d, v in nav.items()]})
            all_entries += entries
    checks = {"history_cutoff_before_signal_period": True, "history_endpoints_complete": True, "holding_calendar_complete": True, "baseline_matches_previous_top10": True, "signals_execute_later": all(e["fill"] is None or e["signal"]["date"] < e["fill"]["date"] for e in all_entries), "ten_fixed_cash_sleeves_each_scenario": len(all_entries) == len(symbols) * len(cfg["references"]) * len(cfg["thresholds"]), "returns_include_unspent_cash": all(abs(g["return_total"] - math.fsum(e["return_total"] for e in all_entries if e["scenario"] == g["id"]) / 10) < 1e-12 for g in groups[1:])}
    if not all(checks.values()):
        raise ValueError(str(checks))
    output = {"config": cfg, "symbols": symbols, "securities": securities, "historical": stats, "groups": groups, "entries": all_entries, "validation": checks, "benchmark": next(g for g in parent["groups"] if g["id"] == "spy"), "limitations": ["5 年指 2021—2025 的观察窗口，最大回撤可以跨年；不足窗口长度的股票从上市或已指定身份起点开始，实际起止逐只列明。", "平均年度最大回撤每年重置高点，并包括前一年末收盘作为起点；上市残年不纳入完整年度均值。", "平均每次回撤：从一个收盘新高下跌到恢复该高点算一次，取各次最深跌幅均值；截至 2025 年末尚未恢复的一次也按已观察深度计入，可能低估最终深度；微小波动也算一次。", "最大和平均回撤阈值全部在 2025 年末冻结。只选 2025 强势的这 10 只做事后样本研究，不证明规则适用于所有股票或未来年份。", "价格信号用含股息调整的收盘序列，避免把分红或拆分当跌幅；不是盘中最高/最低价，也不是触价限价单。", "首次收盘满足条件后，下一交易日开盘买入；跳空后成交价可以不同于触发价，触发后的反弹不取消订单。期末无可交易成交日则保持现金。", "每只预留初始资金 10%，未触发资金保持零息现金，不重新分给已买入股票；各股只买一次，无止损、重复补仓或再平衡。", "从新高回撤后买入仍可能贵于年初价格；必须把等待中的现金及错过的上涨计入比较。", "继续采用前轮股息调整和 WBD 现金收购处理；未计税费、滑点和交易费。未逐只重新审计数据商的历史分拆与分派调整。", "WBD 只用 2022-04-11 合并后的历史，不将供应商回填的 Discovery 前身行情直接混入。"]}
    (ROOT / "results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    export_csv("historical_drawdowns.csv", [{k: v for k, v in s.items() if k not in ["annual", "episodes"]} for s in stats])
    export_csv("scenario_summary.csv", [{k: v for k, v in g.items() if k != "nav"} for g in groups])
    export_csv("entries.csv", [{k: v for k, v in e.items() if k != "nav"} for e in all_entries])
    export_csv("historical_episodes.csv", [{"symbol": s["symbol"], **e} for s in stats for e in s["episodes"]])
    export_csv("annual_drawdowns.csv", [{"symbol": s["symbol"], **a} for s in stats for a in s["annual"]])
    files = [ROOT / "config.json", ROOT / "run.py", ROOT.parent / "results.json", ROOT.parent / "backtest.py"] + sorted((ROOT / "raw").glob("*.json")) + [ROOT.parent / "raw/prices" / (s + ".json") for s in symbols]
    (ROOT / "run_manifest.json").write_text(json.dumps({"files": {str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, "validated": checks}, indent=2))
    print(json.dumps({"historical": [{k: s[k] for k in ["symbol", "start", "max_drawdown", "mean_annual", "mean_episode", "full_years"]} for s in stats], "groups": [{k: g[k] for k in ["id", "return_total", "max_drawdown", "bought_count", "excess_baseline"]} for g in groups]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
