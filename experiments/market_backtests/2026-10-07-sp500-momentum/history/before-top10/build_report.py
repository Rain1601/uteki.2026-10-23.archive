#!/usr/bin/env python3
"""Render the frozen backtest results as a self-contained, read-only HTML report."""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path


COLORS = ["#235ba8", "#008575", "#cc7430", "#9b55a3", "#64748b", "#262626", "#ce4150"]


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def pct(value, signed=False):
    return f"{value:+.2%}" if number(value) and signed else f"{value:.2%}" if number(value) else "缺数据"


def pp(value):
    return f"{value * 100:+.2f} 个百分点" if number(value) else "缺数据"


def cell(value):
    return esc(value) if value is not None else "缺数据"


def chart_svg(body, title, width, height):
    return f'<svg role="img" aria-label="{esc(title)}" viewBox="0 0 {width} {height}"><title>{esc(title)}</title>{body}</svg>'


def return_chart(groups):
    valid = [g for g in groups if number(g.get("return_total"))]
    if not valid:
        return '<p class="empty">尚无可计算的期末收益。</p>'
    width, left, right, step = 1080, 340, 108, 48
    low = min(0, min(g["return_total"] for g in valid))
    high = max(0, max(g["return_total"] for g in valid))
    span = high - low or 0.01
    low, high = low - span * .08, high + span * .08
    xpos = lambda v: left + (v - low) / (high - low) * (width - left - right)
    zero = xpos(0)
    height = len(groups) * step + 48
    parts = [f'<line x1="{zero:.1f}" y1="12" x2="{zero:.1f}" y2="{height - 30}" stroke="#b6c0ca"/>']
    for i, g in enumerate(groups):
        y, val = 16 + i * step, g.get("return_total")
        parts.append(f'<text x="{left - 12}" y="{y + 20}" text-anchor="end">{esc(g.get("label", g.get("id", "")))}</text>')
        if not number(val):
            parts.append(f'<text x="{zero + 10:.1f}" y="{y + 20}" fill="#6b7280">缺数据</text>')
            continue
        end = xpos(val)
        parts.append(f'<rect x="{min(zero, end):.1f}" y="{y}" width="{max(abs(end - zero), .6):.1f}" height="29" rx="3" fill="{COLORS[i % len(COLORS)]}"/>')
        label_x, anchor = (end + 8, "start") if val >= 0 else (end - 8, "end")
        parts.append(f'<text x="{label_x:.1f}" y="{y + 20}" text-anchor="{anchor}">{pct(val, True)}</text>')
    parts.append(f'<text x="{zero:.1f}" y="{height - 8}" text-anchor="middle">0%</text>')
    return chart_svg("".join(parts), "期末累计收益率，各组合按结果原值展示", width, height)


def nav_chart(groups):
    # An entry at the open precedes the same day's close, despite lexical order.
    dates = sorted({p["date"] for g in groups for p in g.get("nav", []) if p.get("date")}, key=lambda d: (d[:10], 0 if d.endswith(" open") else 1, d))
    values = [p["value"] for g in groups for p in g.get("nav", []) if number(p.get("value"))]
    if not values or not dates:
        return '<p class="empty">尚无可绘制的净值数据。</p>'
    width, height, left, right, top, bottom = 960, 350, 72, 24, 24, 44
    low, high = min(values + [1]), max(values + [1])
    span = high - low or .02
    low, high = low - .08 * span, high + .08 * span
    dx = {d: i for i, d in enumerate(dates)}
    xpos = lambda d: left + dx[d] / max(len(dates) - 1, 1) * (width - left - right)
    ypos = lambda v: top + (high - v) / (high - low) * (height - top - bottom)
    parts = []
    for i in range(5):
        v = low + (high - low) * i / 4
        y = ypos(v)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e1e6eb"/><text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{v:.3f}</text>')
    parts.append(f'<line x1="{left}" y1="{ypos(1):.1f}" x2="{width - right}" y2="{ypos(1):.1f}" stroke="#9aa7b5" stroke-dasharray="4 5"/>')
    for i, g in enumerate(groups):
        points = {p["date"]: p.get("value") for p in g.get("nav", []) if p.get("date")}
        segments, segment = [], []
        for date in dates:
            value = points.get(date)
            if number(value):
                segment.append(f"{xpos(date):.1f},{ypos(value):.1f}")
            elif segment:
                segments.append(segment)
                segment = []
        if segment:
            segments.append(segment)
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0].split(",")
                parts.append(f'<circle cx="{x}" cy="{y}" r="2" fill="{COLORS[i % len(COLORS)]}"/>')
            else:
                parts.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{COLORS[i % len(COLORS)]}" stroke-width="2.4"/>')
    for n in sorted({0, len(dates) // 2, len(dates) - 1}):
        anchor = "start" if n == 0 else "end" if n == len(dates) - 1 else "middle"
        parts.append(f'<text x="{xpos(dates[n]):.1f}" y="{height - 12}" text-anchor="{anchor}">{esc(dates[n])}</text>')
    legend = "".join(f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{esc(g.get("label", g.get("id", "")))}</span>' for i, g in enumerate(groups))
    return chart_svg("".join(parts), "买入持有净值，买入时为1，缺失值处断线", width, height) + f'<div class="legend">{legend}</div>'


def table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def row(values, attrs=""):
    return f'<tr {attrs}>' + "".join(f"<td>{v}</td>" for v in values) + "</tr>"


def sensitivity_section(sensitivity, main_groups):
    if not sensitivity:
        return "", ""
    main = {g["id"]: g for g in main_groups}
    rows, summaries = [], []
    for g in sensitivity.get("groups", []):
        base = main.get(g.get("id"), {}).get("return_total")
        value = g.get("return_total")
        change = value - base if number(value) and number(base) else None
        rows.append(row([esc(g.get("label", g.get("id"))), cell(g.get("count")), pct(base, True), pct(value, True), pp(change), pp(g.get("excess_spy"))]))
        if g.get("id") in ("top_n", "top_half") and number(value):
            summaries.append(f'{esc(g.get("label", g.get("id")))}收益为 <strong>{pct(value, True)}</strong>')
    comparison = table(["组合", "敏感性证券数", "主口径收益", "敏感性收益", "较主口径变化", "敏感性较 SPY"], rows)
    additions = table(["纳入证券", "排名收益起点", "起点至年末收益", "敏感性排名"], [row([esc(x.get("symbol")), esc(x.get("start_date")), pct(x.get("ranking_return"), True), cell(x.get("rank"))]) for x in sensitivity.get("additions", [])])
    changes = table(["组合", "新增证券", "移出证券"], [row([esc(main.get(x.get("group"), {}).get("label", x.get("group"))), esc("、".join(x.get("added", [])) or "无"), esc("、".join(x.get("removed", [])) or "无")]) for x in sensitivity.get("changes", [])])
    summary = (' 若将年内新上市等证券按其可用期间纳入排名，' + "，".join(summaries) + '。这与主口径不是同一组全年可比样本。') if summaries else ""
    section = f'<section id="sensitivity"><h2>敏感性：{esc(sensitivity.get("label", "纳入年内新增证券"))}</h2><p>{esc(sensitivity.get("description", ""))}</p><p><strong>主结果保留全年可比排名口径。</strong>本节把排名范围扩大到 {cell(sensitivity.get("universe_count"))} 只证券；新上市证券从正式上市首日收盘起计算排名期间收益，不能称为完整 2025 全年收益。由此产生的组合差异单独展示，不覆盖主结果。</p>{comparison}<h3>新增排名证券与起点</h3>{additions}<h3>组合成员变化</h3>{changes}</section>'
    return section, summary


def build_report(data):
    config, groups = data.get("config", {}), data.get("groups", [])
    stocks, sectors = data.get("stocks", []), data.get("sectors", [])
    status = data.get("status", "blocked")
    status_text = {"complete": "本次计算已完成", "limited": "计算完成，含明确口径限制", "blocked": "数据不足，尚不能完成回测"}.get(status, "状态未识别")
    gmap = {g["id"]: g for g in groups}
    benchmark = data.get("benchmark_label") or "SPY（标普 500 ETF）"
    summaries = []
    for gid in ("top_n", "top_half"):
        g = gmap.get(gid, {})
        if number(g.get("return_total")):
            sentence = f'{esc(g.get("label", gid))}收益为 <strong>{pct(g["return_total"], True)}</strong>'
            if number(g.get("excess_spy")):
                delta = g["excess_spy"]
                sentence += f'，比 {esc(benchmark)} {"高" if delta >= 0 else "低"} <strong>{abs(delta) * 100:.2f} 个百分点</strong>'
            summaries.append(sentence + "。")
    conclusion = " ".join(summaries) or "目前没有足够的真实结果支持收益比较。"
    if status == "blocked" and summaries:
        conclusion = "以下为当前可用数据的局部计算结果。" + conclusion + " 请结合下方缺口判断可比性。"
    sensitivity, sensitivity_summary = sensitivity_section(data.get("sensitivity"), groups)
    conclusion += sensitivity_summary
    metric_rows = [row([esc(g.get("label", g.get("id"))), cell(g.get("count")), pct(g.get("return_total"), True), pp(g.get("excess_spy")), pp(g.get("excess_all")), pct(g.get("max_drawdown"))]) for g in groups]
    metrics = table(["组合", "证券数量", "累计收益", "较 SPY", "较可排名全体等权", "最大回撤"], metric_rows) if groups else '<p class="empty">暂无组合结果。</p>'
    cvr_groups = [g for g in groups if "cvr_max_additional_return" in g]
    cvr = table(["组合", "或有支付权最高额外收益"], [row([esc(g.get("label", g.get("id"))), f'{g["cvr_max_additional_return"] * 100:+.4f} 个百分点' if number(g.get("cvr_max_additional_return")) else "缺数据"]) for g in cvr_groups]) if cvr_groups else ""
    if cvr:
        cvr = '<details><summary>HOLX 或有支付权：对各组合收益的最大额外影响</summary><p>主结果未计入不可交易或有支付权（CVR）的价值。下表是假设获得最高约定支付额时，组合累计收益最多额外增加的百分点，不表示实际会收到该金额，也未调整支付时间价值。</p>' + cvr + '</details>'
    sector_rows = [row([esc(s.get("sector")), cell(s.get("universe_count")), cell(s.get("bottom_count")), pct(s.get("bottom_share")), pct(s.get("hit_rate")), f'{s["lift"]:.2f} 倍' if number(s.get("lift")) else "缺数据"]) for s in sectors]
    sector_table = table(["行业", "可排名数量", "后半组数量", "占后半组比例", "行业内后半比例", "相对整体倍数"], sector_rows) if sectors else '<p class="empty">暂无行业统计。</p>'
    stock_rows = []
    for s in stocks:
        gids = s.get("groups", [])
        labels = [gmap.get(gid, {}).get("label", gid) for gid in gids]
        search = " ".join(str(s.get(k) or "") for k in ("symbol", "name", "sector"))
        attrs = f'data-search="{esc(search.lower())}" data-groups="{esc("|".join(gids))}" data-sector="{esc(s.get("sector"))}"'
        stock_rows.append(row([cell(s.get("rank")), esc(s.get("symbol")), esc(s.get("name")), esc(s.get("sector")), pct(s.get("ranking_return"), True), pct(s.get("holding_return"), True), esc("、".join(labels))], attrs))
    stock_table = table(["2025 排名", "代码", "名称", "行业", "2025 收益", "2026 持有收益", "所属组合"], stock_rows)
    group_options = "".join(f'<option value="{esc(g["id"])}">{esc(g.get("label", g["id"]))}</option>' for g in groups if g["id"] not in ("spy", "index"))
    sector_options = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sorted({s.get("sector") for s in stocks if s.get("sector")}))
    gaps = [("排名排除", x) for x in data.get("excluded", [])] + [("数据缺口", x) for x in data.get("gaps", [])]
    gap_table = table(["类别", "证券", "原因"], [row([kind, esc(x.get("symbol")), esc(x.get("reason"))]) for kind, x in gaps]) if gaps else "<p>结果文件未报告排除或数据缺口。</p>"
    required_limits = [
        "复权价格用于近似包含股息和拆股影响的总回报；数据商复权规则、股息再投资时点及价格修订会影响结果。",
        "标普 500 指数的公司数与证券数不同：名单可能含 503 只证券，其中部分公司有多个股票类别。本报告按证券等额投入，多个类别分别计入。",
        "历史成分名单来自第三方存档，并非获得授权的指数历史档案；完整性与生效日期仍受该来源限制。",
        "收益未扣除交易费用、税费与滑点；不模拟交易量、成交约束和实际资金规模。",
        "只观察一个选股年度及随后一段持有期，不能据此证明长期稳定超额收益。行业统计为描述结果，未自动形成额外行业排除策略。",
    ]
    limits = list(dict.fromkeys(data.get("limitations") or required_limits))
    limits_html = "".join(f"<li>{esc(x)}</li>" for x in limits)
    config_text = esc(json.dumps(config, ensure_ascii=False, indent=2))
    period = f'{esc(config.get("entry_date", "未知"))} → {esc(config.get("end_date", "未知"))}'
    ranking = f'{esc(config.get("ranking_start", "未知"))} 收盘 → {esc(config.get("ranking_end", "未知"))} 收盘'
    top_n = esc(config.get("top_n", 50))
    fraction = pct(config.get("top_fraction", .5))
    return TEMPLATE.replace("@@BODY@@", f"""
<header><p class="eyebrow">工程化回测 · 冻结输入 · 等权买入持有</p><h1>2025 年强势股，2026 年表现如何？</h1>
<p>按 2025 全年复权收益排名，比较前 {top_n} 名、前 {fraction} 与整体。持有区间：{period}。</p></header>
<main><section class="summary"><p class="status {esc(status)}">{esc(status_text)}</p><p class="conclusion">{conclusion}</p>
<p class="muted">名单：{cell(data.get("universe_count"))} 只证券；可排名：{cell(data.get("rankable_count"))} 只。以下超额收益为累计收益之差，单位为百分点。</p></section>
<section><h2>主口径：收益对比</h2>{return_chart(groups)}{metrics}<p class="note">“较可排名全体等权”以 {cell(gmap.get("all_rankable", {}).get("count"))} 只可排名证券的等权组合为基准。全体等权与 SPY 的权重方法不同。SPY 为市值加权指数的 ETF 近似；S&amp;P 500 价格指数不含股息，与复权收益的口径不同。</p>{cvr}</section>
{sensitivity}
<section><h2>持有过程</h2>{nav_chart(groups)}<p class="note">起始净值为 1。缺失值不会按 0 处理，曲线在缺失处断开。最大回撤衡量持有期间从此前最高净值到随后最低净值的最大跌幅。</p></section>
<section><h2>2025 年后半组集中在哪些行业？</h2><p>“占后半组比例”看后半组的行业构成；“行业内后半比例”看该行业有多少证券进入后半组；“相对整体倍数”用行业内后半比例除以整体后半比例。</p>{sector_table}</section>
<section id="stock-section"><h2>股票明细</h2><div class="filters"><label>搜索代码、名称、行业<input id="search" type="search" placeholder="例如 AAPL / Technology"></label><label>组合<select id="group"><option value="">全部证券</option>{group_options}</select></label><label>行业<select id="sector"><option value="">全部行业</option>{sector_options}</select></label><button id="reset" type="button">重置</button></div>
<p id="count" class="muted" aria-live="polite">共 {len(stocks)} 只证券</p>{stock_table}</section>
<section><h2>回测方法</h2><ol><li>使用明确选定的历史名单。2025 年排名区间：{ranking}。</li><li>按各证券的复权总回报近似值从高到低排名；前 {top_n} 名和前 {fraction} 构成独立组合。排名排除与持有缺失单独列示。</li><li>2026 年的模拟买入日期为 {esc(config.get("entry_date", "未知"))}。当配置为首个交易日开盘买入时，使用开盘价按同日复权比例调整，避免假定能够在排名结束的收盘价成交。</li><li>每只证券初始投入相同金额，随后买入持有，不做每日等权再平衡。期末为 {esc(config.get("end_date", "未知"))}。</li><li>同时比较全体成分证券等权组合与 {esc(benchmark)}。本实验不进行 2024 年选股回测。</li></ol><details><summary>查看本次冻结配置</summary><pre>{config_text}</pre></details></section>
<section id="gaps"><h2>排除与数据缺口</h2>{gap_table}</section>
<section><h2>结果边界</h2><ul>{limits_html}</ul></section>
<section><h2>来源与可复查明细</h2><p><a href="data_manifest.json">数据来源清单</a> · <a href="reproduction_manifest.json">复现与输入记录</a> · <a href="stocks.csv">股票明细 CSV</a> · <a href="sector_distribution.csv">行业统计 CSV</a> · <a href="summary.csv">组合汇总 CSV</a> · <a href="results.json">完整计算结果 JSON</a></p></section>
<footer>本页由同目录 results.json 自动生成，表格与图形共用同一结果。复跑入口：build_report.py；计算与来源以本次实验目录中的记录为准。</footer></main>
""")


TEMPLATE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>标普 500 · 2025 选股 → 2026 持有</title>
<style>:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:#202c39;background:#f6f8fa}*{box-sizing:border-box}body{margin:0;line-height:1.65}header,main{max-width:1120px;margin:auto;padding:28px 24px}header{padding-bottom:8px}h1{font-size:30px;line-height:1.3;margin:10px 0 14px}h2{font-size:21px;line-height:1.4;margin:0 0 16px}p{margin:10px 0}section{background:#fff;border:1px solid #e0e5ea;border-radius:8px;padding:24px;margin-bottom:22px}.eyebrow,.muted,.note,footer{color:#5e6c7b;font-size:14px}.eyebrow{letter-spacing:.06em}.conclusion{font-size:20px;line-height:1.8}.status{font-size:14px;font-weight:600;color:#216447}.limited,.blocked{color:#9b5011}.summary{border-left:4px solid #54708b}.table-wrap{overflow:auto;margin-top:18px}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:11px 12px;border-bottom:1px solid #e5e9ed;text-align:right;white-space:nowrap}th{background:#f5f7f9;font-weight:600}th:first-child,td:first-child{text-align:left}#stock-section td:nth-child(2),#stock-section td:nth-child(3),#stock-section td:nth-child(4){text-align:left}#stock-section td:last-child{white-space:normal;min-width:170px;font-size:12px}td:last-child{max-width:560px}#gaps td:last-child{white-space:normal;text-align:left;min-width:260px}svg{width:100%;height:auto;display:block;overflow:visible}svg text{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#445364}.legend{display:flex;flex-wrap:wrap;gap:10px 20px;font-size:13px}.legend span{display:flex;align-items:center;gap:7px}.legend i{width:18px;height:3px;display:inline-block}.filters{display:flex;gap:14px;flex-wrap:wrap;align-items:end}.filters label{display:flex;flex-direction:column;font-size:13px;gap:5px}.filters label:first-child{flex:1;min-width:220px}input,select,button{font:inherit;color:inherit;background:white;border:1px solid #b9c5d0;border-radius:5px;padding:9px 11px;min-height:42px}button{cursor:pointer}button:hover{background:#eef2f6}input:focus,select:focus,button:focus{outline:2px solid #235ba8;outline-offset:2px}li{margin:8px 0}pre{overflow:auto;white-space:pre-wrap;background:#f6f8fa;padding:14px;font-size:13px}summary{cursor:pointer;color:#235ba8}.empty{padding:16px;background:#f6f8fa;color:#5e6c7b}footer{padding:0 4px 24px}[hidden]{display:none!important}@media(max-width:640px){header,main{padding:18px 12px}h1{font-size:25px}section{padding:18px 14px}.conclusion{font-size:18px}svg text{font-size:15px}.filters label{flex:1}th,td{padding:9px}}@media print{body{background:white}header,main{max-width:none;padding:10px}section{break-inside:avoid}.filters{display:none}.table-wrap{overflow:visible}#stock-section{break-inside:auto}details{display:none}}</style></head><body>@@BODY@@
<script>
(() => {
  const search = document.getElementById('search');
  const group = document.getElementById('group');
  const sector = document.getElementById('sector');
  const rows = [...document.querySelectorAll('#stock-section tbody tr')];
  function filter() {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    rows.forEach(row => {
      const matches = (!query || row.dataset.search.includes(query)) &&
        (!group.value || row.dataset.groups.split('|').includes(group.value)) &&
        (!sector.value || row.dataset.sector === sector.value);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    document.getElementById('count').textContent = `显示 ${visible} / ${rows.length} 只证券`;
  }
  search.addEventListener('input', filter);
  group.addEventListener('change', filter);
  sector.addEventListener('change', filter);
  document.getElementById('reset').addEventListener('click', () => {
    search.value = ''; group.value = ''; sector.value = ''; filter();
  });
  filter();
})();
</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("results.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("report.html"))
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.write_text(build_report(data), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
