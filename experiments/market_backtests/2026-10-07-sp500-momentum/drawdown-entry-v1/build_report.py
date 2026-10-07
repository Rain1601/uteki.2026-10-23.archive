"""Self-contained explanation of historical thresholds and actual entry traces."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def h(value):
    return html.escape(str(value))


def pct(value, signed=False):
    if value is None:
        return "—"
    return f"{value:+.2%}" if signed else f"{value:.2%}"


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + h(x) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + str(x) + '</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def build(data):
    groups = data["groups"]
    base = groups[0]
    best = max(groups[1:], key=lambda g: g["return_total"])
    summary = table(["买入规则", "2026 组合收益", "比年初直接买入", "期间最大回撤", "买到几只", "从未投入的本金"], [[h(g["label"]), '<strong>' + pct(g["return_total"], True) + '</strong>', f'{g["excess_baseline"]*100:+.2f} 个百分点', pct(g["max_drawdown"]), str(g["bought_count"]) + ' / 10', pct(g["unspent_initial_weight"])] for g in groups])
    historical = table(["股票", "历史起点", "最大回撤", "最大回撤的一半", "平均年度最大回撤", "完整年度数"], [[h(s["symbol"]), s["start"], pct(s["max_drawdown"]), pct(s["half_max"]), pct(s["mean_annual"]), f'{len(s["full_years"])} 年'] for s in data["historical"]])
    history_details = ''
    for s in data["historical"]:
        history_details += '<details><summary>' + h(s["symbol"]) + '：年度回撤及最大回撤日期</summary><p>窗口内最大回撤从 ' + h(s["max_peak_date"]) + ' 的高点至 ' + h(s["max_trough_date"]) + ' 的低点。期间未恢复的回撤段：' + str(s["unrecovered_episode_count"]) + ' 次。</p>' + table(["年度", "最大回撤", "高点日期", "低点日期"], [[a['year'], pct(a['depth']), a['peak_date'], a['trough_date']] for a in s['annual']]) + '</details>'
    options = ''.join(f'<option value="{h(g["id"])}">{h(g["label"])}</option>' for g in groups[1:])
    limitations = ''.join('<li>' + h(x) + '</li>' for x in data['limitations'] if not x.startswith('平均每次回撤：'))
    main = f'''<header><a href="../report.html#top10">← 前 10 名买入持有报告</a><p class="eyebrow">BT-05 · 冻结历史阈值 · 程序化回测</p><h1>等回撤再买，真的会更好吗？</h1><p>同一组 2025 年前 10 名；2026-01-02 至 2026-10-06。每只预留 10% 本金，触发后只买一次。</p></header>
<main><section class="lead"><h2>本次样本：等待降低了部分回撤，也错过了上涨</h2><p class="big">年初直接买入：<strong>{pct(base['return_total'],True)}</strong>。这 {len(groups)-1} 种等待规则的最高收益为 <strong>{pct(best['return_total'],True)}</strong>，来自“{h(best['label'])}”。</p><p>所以，以这段期间的收益衡量，等待没有更好；部分等待规则的最大回撤更小，但其中也有较多资金一直未投入。两种目标需要分别看。</p><p>当前窗口：2021—2025；用户已确认“平均回撤”采用各年最大回撤的平均值。使用主口径 10 只股票，不纳入上一轮 Sandisk 敏感性组合。所有阈值在 2025 年末冻结。</p></section>
<section><h2>先分清两个买入参照</h2><div class="two"><div><h3>① 从年初价格下跌</h3><p>假设年初为 100、阈值 30%，始终等到复权价格跌至 70；即使先涨到 150，参照也不变。</p></div><div><h3>② 从过程中的新高回撤</h3><p>假设先从 100 涨到 150，回撤 30% 的触发点就是 105。虽然出现回撤，仍可能比年初贵。</p></div></div><p class="process">2025 年末冻结阈值 → 2026 每日收盘判断 → 次一交易日开盘成交 → 持有到 10 月 6 日</p><p>这是“收盘信号、次日开盘”的模拟。触发价与成交价可能不同，不能解读为必然在阈值价买到。</p></section>
<section><h2>2026 年组合结果：未买入的现金也算进去</h2>{summary}<p>收益分母始终是全部初始本金，不只计算成功买到的股票。“从未投入的本金”是未触发部分，不含后来因 WBD 被现金收购而收回的资金。</p><p><strong>例子：</strong>从年初价等待“最大回撤一半”，仅 APP 触发；90% 本金留在现金。APP 买入后仍下跌，使组合收益为 −2.36%。</p></section>
<section><h2>每只股票具体什么时候买？</h2><label for="scenario">选择买入规则</label><select id="scenario">{options}</select><p id="scenario-note" aria-live="polite"></p><div id="chart"></div><div id="entries"></div><p>“买价较年初”按相同复权尺度比较；正数代表等回撤之后，仍比年初买得贵。股息调整后价格用于保持可比性，不是当年的原始报价标签。</p></section>
<section><h2>历史回撤阈值：只用 2026 年以前的数据</h2><p><strong>最大回撤：</strong>窗口中从某个此前高点至随后低点的最深跌幅，允许跨年。<strong>平均年度最大回撤：</strong>各完整年度最深跌幅的平均值。</p>{historical}<p>这些是有限历史窗口内的统计，不是上市以来的永久上限。HOOD、APP 的上市残年不计入完整年度均值；WBD 仅从 2022-04-11 合并后起算。主比较不使用逐次小回撤的平均值。</p>{history_details}</section>
<section><h2>本轮核验与边界</h2><p>已重现此前前 10 名的 72.31% 基准；全部持有日期完整；信号早于成交；每个规则保留 10 份独立本金；组合收益与逐股收益均值一致。</p><ul>{limitations}</ul></section>
<section><h2>可复查数据</h2><p><a href="historical_drawdowns.csv">历史回撤 CSV</a> · <a href="annual_drawdowns.csv">逐年回撤</a> · <a href="historical_episodes.csv">逐次回撤</a> · <a href="scenario_summary.csv">规则比较</a> · <a href="entries.csv">触发与成交明细</a> · <a href="results.json">全部计算结果</a> · <a href="run_manifest.json">冻结输入哈希</a></p><p>历史数据：<a href="history_manifest.json">Yahoo 原始响应与来源</a>；复权定义：<a href="https://in.help.yahoo.com/kb/adjusted-close-sln28256.html">Yahoo 官方说明</a>；回撤定义：<a href="https://www.fidelity.com/research/backtesting/glossary.html">Fidelity 说明</a>；WBD 身份起点：<a href="https://www.wbd.com/discovery-and-att-close-warnermedia-transaction/">公司合并公告</a>。</p></section></main>'''
    payload = {"groups": groups, "entries": data['entries'], "benchmark": data['benchmark']}
    return TEMPLATE.replace('@@MAIN@@', main).replace('@@DATA@@', json.dumps(payload, ensure_ascii=False).replace('</', '<\\/'))


TEMPLATE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>前 10 名：等回撤再买的验证</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#223143;background:#f4f6f8}*{box-sizing:border-box}body{margin:0;line-height:1.65}header,main{max-width:1200px;margin:auto;padding:24px}h1{font-size:30px}h2{font-size:21px}h3{font-size:17px}p{margin:12px 0}section{background:#fff;padding:24px;margin-bottom:22px;border:1px solid #dfe5ec;border-radius:8px}.lead{border-left:4px solid #255dad}.big{font-size:21px}.eyebrow{color:#53657a}.two{display:grid;grid-template-columns:1fr 1fr;gap:24px}.process{font-weight:600;color:#234f82}a{color:#215ba7}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:11px;border-bottom:1px solid #e0e6ed;white-space:nowrap}th{background:#f0f3f7}th:first-child,td:first-child{text-align:left}.scroll{overflow-x:auto}details{margin-top:12px}summary{cursor:pointer;font-weight:600}select{display:block;font:inherit;padding:10px;margin-top:8px;max-width:100%;background:white;border:1px solid #a3b3c5;border-radius:4px}svg{width:100%;height:auto}svg text{font:13px sans-serif;fill:#36495f}.legend{display:flex;gap:20px;flex-wrap:wrap}.legend span{display:flex;gap:8px;align-items:center}.legend i{display:inline-block;width:20px;height:3px}li{margin:8px 0}@media(max-width:700px){header,main{padding:12px}section{padding:16px}.two{grid-template-columns:1fr}h1{font-size:25px}.big{font-size:18px}}
</style></head><body>@@MAIN@@<script>
const DATA=@@DATA@@;
const pct=(v)=>v===null||v===undefined?'—':(v>=0?'+':'')+(v*100).toFixed(2)+'%';
const esc=(s)=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ord=(d)=>d.slice(0,10)+(d.endsWith(' open')?'0':'1');
function draw(selected){
 const series=[DATA.groups[0],selected,{...DATA.benchmark,label:'SPY'}];
 const dates=[...new Set(series.flatMap(g=>g.nav.map(p=>p.date)))].sort((a,b)=>ord(a).localeCompare(ord(b)));
 const values=series.flatMap(g=>g.nav.map(p=>p.value));let lo=Math.min(...values,1),hi=Math.max(...values,1);const pad=(hi-lo)*.08||.02;lo-=pad;hi+=pad;
 const W=1000,H=330,L=64,R=20,T=20,B=42;const X=i=>L+i/(dates.length-1)*(W-L-R);const Y=v=>T+(hi-v)/(hi-lo)*(H-T-B);let out='<svg viewBox="0 0 1000 330" role="img" aria-label="年初买入、所选等待规则及SPY的2026年净值对比"><title>起始净值为1；等待期间现金净值不变</title>';
 for(let i=0;i<5;i++){let v=lo+(hi-lo)*i/4,y=Y(v);out+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#dce3eb"/><text x="${L-10}" y="${y+4}" text-anchor="end">${v.toFixed(2)}</text>`;}
 const colors=['#6c7887','#215cae','#1a8274'];series.forEach((g,k)=>{const by=Object.fromEntries(g.nav.map(p=>[p.date,p.value]));let points=dates.map((d,i)=>`${X(i)},${Y(by[d])}`).join(' ');out+=`<polyline fill="none" stroke="${colors[k]}" stroke-width="2.2" points="${points}"/>`;});
 [0,Math.floor(dates.length/2),dates.length-1].forEach((i,j)=>{out+=`<text x="${X(i)}" y="${H-12}" text-anchor="${j===0?'start':j===2?'end':'middle'}">${esc(dates[i].slice(0,10))}</text>`;});out+='</svg><div class="legend">'+series.map((g,i)=>`<span><i style="background:${colors[i]}"></i>${esc(g.label)}</span>`).join('')+'</div>';document.getElementById('chart').innerHTML=out;
}
function render(){
 const id=document.getElementById('scenario').value;const group=DATA.groups.find(g=>g.id===id);const entries=DATA.entries.filter(e=>e.scenario===id);
 document.getElementById('scenario-note').textContent=`组合收益 ${pct(group.return_total)}；买到 ${group.bought_count}/10 只；未投入本金 ${(group.unspent_initial_weight*100).toFixed(0)}%；期间最大回撤 ${(group.max_drawdown*100).toFixed(2)}%。`;
 const headers=['股票','等待跌幅','首次收盘触发','实际模拟买入日','买价较年初','买入后收益','对全部本金贡献'];
 let t='<div class="scroll"><table><thead><tr>'+headers.map(s=>'<th>'+s+'</th>').join('')+'</tr></thead><tbody>';
 entries.forEach(e=>{const cells=[e.symbol,(e.threshold*100).toFixed(2)+'%',e.signal?.date??'未触发',e.fill?.date??(e.signal?'期末未成交':'未买入'),pct(e.entry_vs_year_open),e.fill?pct(e.return_total):'现金：0%',pct(e.return_total/10)];t+='<tr>'+cells.map(s=>'<td>'+esc(s)+'</td>').join('')+'</tr>';});document.getElementById('entries').innerHTML=t+'</tbody></table></div>';draw(group);
}
document.getElementById('scenario').addEventListener('change',render);document.getElementById('scenario').value='running_peak__half_max';render();
</script></body></html>'''


if __name__ == '__main__':
    data = json.loads((ROOT / 'results.json').read_text())
    (ROOT / 'report.html').write_text(build(data))
    print(ROOT / 'report.html')
