"""Frozen-data sector context, no model calls or new price requests."""
import csv, hashlib, html, json, math, statistics, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
P=ROOT.parent
sys.path.insert(0,str(P))
import backtest as bt

def mean(xs): return math.fsum(xs)/len(xs)
def corr(x,y):
    a,b=mean(x),mean(y)
    xx=math.fsum((v-a)**2 for v in x); yy=math.fsum((v-b)**2 for v in y)
    return math.fsum((u-a)*(v-b) for u,v in zip(x,y))/math.sqrt(xx*yy) if xx and yy else None

def writecsv(name,rows):
    with (ROOT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    raw=(P/'results.json').read_bytes(); data=json.loads(raw); cfg=data['config']; stocks=data['stocks']
    top=[s for s in stocks if s['rank'] is not None and s['rank']<=50]
    sectors=sorted({s['sector'] for s in top})
    expanded=[s for s in stocks if s['sector'] in sectors]
    eligible=[s for s in expanded if s['ranking_return'] is not None]
    div=json.loads((P/'supplemental_dividends.json').read_text()); sup=json.loads((P/'supplemental_prices.json').read_text())
    bars={s['symbol']:(bt.historical_bars(s['symbol'],cfg,div,sup) if s['symbol'] in div else bt.yahoo_bars(s['symbol'],cfg)) for s in eligible}
    dates=sorted(d for d in bt.yahoo_bars('SPY',cfg) if cfg['ranking_start']<=d<=cfg['ranking_end'])
    members={sec:[s for s in eligible if s['sector']==sec] for sec in sectors}
    summaries=[]; gaps=[]
    for s in eligible:
        missing=sorted(set(dates)-bars[s['symbol']].keys())
        if missing:gaps.append({'symbol':s['symbol'],'missing_2025_dates':missing})
    details=[]
    for sec,ss in members.items():
        winners=[s for s in top if s['sector']==sec]; rest=[s for s in ss if s not in winners]
        summaries.append({'sector':sec,'all_count':sum(s['sector']==sec for s in expanded),'eligible_count':len(ss),'top50_count':len(winners),'top50_rate':len(winners)/len(ss),'sector_return_2025':mean([s['ranking_return'] for s in ss]),'median_return_2025':statistics.median(s['ranking_return'] for s in ss),'positive_fraction_2025':mean([s['ranking_return']>0 for s in ss]),'top50_return_2025':mean([s['ranking_return'] for s in winners]),'non_top50_return_2025':mean([s['ranking_return'] for s in rest]),'sector_return_2026':mean([s['holding_return'] for s in ss]),'top50_return_2026':mean([s['holding_return'] for s in winners]),'non_top50_return_2026':mean([s['holding_return'] for s in rest])})
        # Fixed membership, equal initial dollars at ranking anchor; weights drift.
        nav={d:mean([bars[s['symbol']][d]['adjclose']/bars[s['symbol']][dates[0]]['adjclose'] for s in ss]) for d in dates if all(d in bars[s['symbol']] for s in ss)}
        pairs=[(a,b) for a,b in zip(dates,dates[1:]) if a in nav and b in nav]
        for s in winners:
            peers=[p for p in ss if p['symbol']!=s['symbol']]; n=len(ss)
            own={d:bars[s['symbol']][d]['adjclose']/bars[s['symbol']][dates[0]]['adjclose'] for d in nav}
            pn={d:(nav[d]*n-own[d])/(n-1) for d in nav}
            x=[own[b]/own[a]-1 for a,b in pairs]; y=[pn[b]/pn[a]-1 for a,b in pairs]
            pr=mean([p['ranking_return'] for p in peers]); hr=mean([p['holding_return'] for p in peers]);rho=corr(x,y)
            details.append({'rank':s['rank'],'symbol':s['symbol'],'name':s['name'],'sector':sec,'peer_count':len(peers),'return_2025':s['ranking_return'],'peer_return_2025':pr,'excess_pp_2025':100*(s['ranking_return']-pr),'peer_positive_fraction_2025':mean([p['ranking_return']>0 for p in peers]),'daily_correlation_2025':rho,'paired_daily_observations':len(pairs),'return_2026':s['holding_return'],'peer_return_2026':hr,'excess_pp_2026':100*(s['holding_return']-hr)})
            assert abs(pn[dates[-1]]-1-pr)<1e-10
    details.sort(key=lambda x:x['rank']);summaries.sort(key=lambda x:-x['top50_count'])
    assert len(top)==50 and len(details)==50 and sum(s['all_count'] for s in summaries)==len(expanded)
    assert all(-1<=s['daily_correlation_2025']<=1 and s['paired_daily_observations']>=200 for s in details)
    out={'source_sha256':hashlib.sha256(raw).hexdigest(),'config':cfg,'expanded_count':len(expanded),'eligible_count':len(eligible),'excluded':[s for s in expanded if s['ranking_return'] is None],'sectors':summaries,'top50':details,'daily_gaps':gaps,'scope':'2025 selection/context; 2026 descriptive follow-up, no additional selection rule'}
    (ROOT/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    writecsv('sector_statistics.csv',summaries);writecsv('top50_peer_comparison.csv',details)
    writecsv('expanded_universe.csv',[{'symbol':s['symbol'],'name':s['name'],'sector':s['sector'],'rank_2025':s['rank'],'return_2025':s['ranking_return'],'return_2026':s['holding_return'],'eligible_2025':s['ranking_return'] is not None} for s in expanded])
    # Keep the exact upstream result used by this extension.
    (ROOT/'input_results.json').write_bytes(raw)
    render(out)
    print(json.dumps({'expanded':len(expanded),'eligible':len(eligible),'sectors':summaries,'examples':[x for x in details if x['symbol'] in ['MU','HOOD','APP','FIX','LRCX','PLTR']]},ensure_ascii=False,indent=2))

def render(d):
    names={'Information Technology':'信息技术','Industrials':'工业','Consumer Discretionary':'可选消费','Financials':'金融','Communication':'通信服务','Health Care':'医疗保健','Materials':'原材料','Consumer Staples':'必需消费','Utilities':'公用事业'}
    h=html.escape
    pct=lambda x:f'{x*100:+.2f}%'
    frac=lambda x:f'{x*100:.0f}%'
    def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+h(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+h(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    sector=table(['行业','前50 / 可比同行（全部）','2025行业收益','2025同行上涨比例','2025前50之外收益','2026前50收益','2026前50之外收益'],[[names[s['sector']],f"{s['top50_count']} / {s['eligible_count']}（{s['all_count']}）",pct(s['sector_return_2025']),frac(s['positive_fraction_2025']),pct(s['non_top50_return_2025']),pct(s['top50_return_2026']),pct(s['non_top50_return_2026'])] for s in d['sectors']])
    headers=['2025排名','股票 / 公司','行业','2025个股','2025同行（剔除自身）','超同行百分点','同行上涨比例','每日相关系数','有效日数','2026个股','2026同行','2026超同行百分点']
    rows=[]
    for s in d['top50']:
        vals=[s['rank'],s['symbol']+' · '+s['name'],names[s['sector']],pct(s['return_2025']),pct(s['peer_return_2025']),f"{s['excess_pp_2025']:+.2f}",frac(s['peer_positive_fraction_2025']),f"{s['daily_correlation_2025']:.2f}",s['paired_daily_observations'],pct(s['return_2026']),pct(s['peer_return_2026']),f"{s['excess_pp_2026']:+.2f}"]
        rows.append('<tr data-sector="'+h(s['sector'])+'" data-search="'+h((s['symbol']+' '+s['name']).lower())+'">'+''.join('<td>'+h(str(v))+'</td>' for v in vals)+'</tr>')
    # A static scatter distinguishes cumulative outperformance from daily co-movement.
    dots=[]
    ymax=math.ceil(max(s['excess_pp_2025'] for s in d['top50'])/50)*50
    for s in d['top50']:
        x=70+(s['daily_correlation_2025']+1)/2*800;y=330-s['excess_pp_2025']/ymax*280
        dots.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5"><title>{h(s["symbol"])}：相关 {s["daily_correlation_2025"]:.2f}；超同行 {s["excess_pp_2025"]:.2f} 个百分点</title></circle>')
        if s['symbol'] in ['WDC','MU','STX','HOOD','APP','FIX','LRCX','PLTR']:dots.append(f'<text x="{x+7:.2f}" y="{y-6:.2f}" font-size="12">{s["symbol"]}</text>')
    svg='<svg viewBox="0 0 930 400" role="img" aria-label="2025年个股与同行每日相关系数和全年超额收益散点图"><path d="M70 40V330H870" fill="none" stroke="#8797a5"/>'+''.join(f'<text x="{70+i*200}" y="355" text-anchor="middle">{(-1+i*.5):g}</text>' for i in range(5))+f'<text x="8" y="52">{ymax}pp</text><text x="30" y="335">0</text><text x="370" y="390">每日走势相关系数 →</text><text x="70" y="22">全年超过同行的收益（百分点）↑</text><g fill="#087e8b">'+''.join(dots)+'</g></svg>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>前50名：公司与行业</title><style>body{font:16px/1.65 system-ui;margin:0;background:#f3f6f8;color:#203040}main{max-width:1450px;margin:auto;padding:32px}section{background:white;border:1px solid #dce4ea;border-radius:12px;padding:24px;margin:24px 0}h1{font-size:32px}h2{font-size:23px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;border-bottom:1px solid #dee5ec;text-align:right;white-space:nowrap}td:nth-child(2),th:nth-child(2){text-align:left}th{background:#eef3f6}a{color:#066977}input,select{padding:10px;font:inherit;margin:6px}svg{width:100%;max-width:1000px}p{max-width:1050px}.note{color:#526575}</style><main>'''
    page+=f'<a href="../report.html">← 返回组合回测</a><h1>前 50 名：是行业普涨，还是个股领先？</h1><p>2025 年排名前 50 名 → 覆盖 {len(d["sectors"])} 个行业 → 扩展到 {d["expanded_count"]} 只证券，其中 {d["eligible_count"]} 只可比较 2025 全年。能源与房地产未命中。沿用 2025 年末固定证券集合及已保存的行业字段。</p>'
    page+='<section><h2>先分清三个问题</h2><p><b>行业涨没涨：</b>看同行等权收益和上涨家数比例。<b>公司多涨多少：</b>个股收益减去剔除自身后的同行收益。<b>是否一起波动：</b>看每日收益相关系数，越接近 1 越同步，接近 0 表示线性同步较弱。</p><p>例如：公司全年涨 100%，同行涨 20%，超同行是 80 个百分点；但这不代表 80% 的上涨由公司特殊事件造成。全年涨幅与每日同步程度是不同指标。</p><p class="note">这是描述性统计。未设置自动排除规则，未把低相关或高超额等同于公司特殊事件。2026 栏只用于观察后续表现，不倒灌进 2025 选股。</p></section>'
    page+='<section><h2>行业整体与同行扩展</h2>'+sector+'<p class="note">行业收益为期初等额买入持有；2025 从 2024-12-31 收盘到 2025-12-31 收盘，2026 从 1 月 2 日开盘到 10 月 6 日收盘。两年统一使用可比较的 2025 全年证券集合。全部扩展名单仍保留 SNDK、Q、PSKY，三只不混入全年对照。</p></section>'
    page+='<section><h2>上涨幅度与走势同步，是两件事</h2>'+svg+'<p>横轴越右，与同行每日涨跌越同步；纵轴越高，全年超出同行越多。图表不划分“行业导致”或“公司导致”的因果区域。</p></section>'
    page+='<section id="companies"><h2>50 家公司逐一比较</h2><input id="search" placeholder="搜索代码或公司"><select id="sector"><option value="">全部行业</option>'+''.join('<option value="'+h(s)+'">'+names[s]+'</option>' for s in names if s in {x['sector'] for x in d['sectors']})+'</select><span id="count"></span><div class="scroll"><table id="details"><thead><tr>'+''.join('<th>'+h(t)+'</th>' for t in headers)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section>'
    page+='<section><h2>分类、缺口与下一步核验</h2><p>当前沿用原始名单的行业字段，为 11 大行业层级；本次命中 9 个。未由模型重分类，也未独立认证每只证券的历史 GICS 归属。大行业可能过宽：存储、半导体设备和软件都可能落在信息技术。下一步应先补齐有来源与日期的细分行业，再对高偏离公司查财报、业务结构及特殊事件。</p><p>每日相关使用复权收盘收益；同行期初等权、随后权重漂移，并剔除被比较公司。只使用前后两个交易日都齐全的日收益，不跨缺口拼接。EA 缺 27 个交易日、FISV 缺 1 日，相应行业的共同日历会缩短；各股有效日数已列出。全年收益端点完整，未因为日频缺口偷偷删除同行。</p><p>沿用原回测供应商数据及公司行动边界；相关性包含市场共同涨跌，未控制市场因子，不能解释为因果贡献。2025 年末集合是事后固定研究范围，不代表年初可知的完整指数名单。</p><p><a href="expanded_universe.csv">全部扩展证券 CSV</a> · <a href="top50_peer_comparison.csv">50 家同行比较 CSV</a> · <a href="sector_statistics.csv">行业统计 CSV</a> · <a href="results.json">结果与缺口</a> · <a href="input_results.json">冻结上游结果</a> · <a href="../README.md">原始数据与口径来源</a></p></section></main>'
    page+='''<script>const rows=[...document.querySelectorAll('#details tbody tr')];const search=document.getElementById('search'),sector=document.getElementById('sector');function filter(){let n=0;for(const r of rows){r.hidden=!(r.dataset.search.includes(search.value.trim().toLowerCase())&&(!sector.value||r.dataset.sector===sector.value));if(!r.hidden)n++;}document.getElementById('count').textContent=`显示 ${n} / 50 家`;}search.addEventListener('input',filter);sector.addEventListener('change',filter);filter();</script></html>'''
    (ROOT/'report.html').write_text(page)

if __name__=='__main__':main()
