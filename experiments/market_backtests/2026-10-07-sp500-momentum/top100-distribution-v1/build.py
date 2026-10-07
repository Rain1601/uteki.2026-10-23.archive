"""Top-100 descriptive distribution; frozen prices, no new selection factors."""
from pathlib import Path
import json,csv,hashlib,math
P=Path(__file__).resolve().parent
source=P/'input_results.json'
if not source.exists(): source.write_bytes((P.parent/'results.json').read_bytes())
d=json.loads(source.read_text());eligible=[s for s in d['stocks'] if s['rank'] is not None];top=sorted([s for s in eligible if s['rank']<=100],key=lambda s:s['rank'])
names={'Information Technology':'信息技术','Industrials':'工业','Financials':'金融','Consumer Discretionary':'可选消费','Health Care':'医疗保健','Communication':'通信服务','Materials':'原材料','Consumer Staples':'必需消费','Utilities':'公用事业','Real Estate':'房地产','Energy':'能源'}
sectors=[]; rows=[]
for key,label in names.items():
    selected=[s for s in top if s['sector']==key]; peers=[s for s in eligible if s['sector']==key]
    means={scope:{year:math.fsum(s[field] for s in ss)/len(ss) for year,field in [('2025','ranking_return'),('2026','holding_return')]} for scope,ss in [('all',peers),('selected',selected)]}
    sectors.append({'key':key,'name':label,'count':len(selected),'peerCount':len(peers),'means':means,'stocks':[{'symbol':s['symbol'],'name':s['name'],'rank':s['rank'],'r2025':s['ranking_return'],'r2026':s['holding_return']} for s in selected]})
    for s in selected:rows.append({'rank':s['rank'],'symbol':s['symbol'],'name':s['name'],'sector':key,'return_2025':s['ranking_return'],'return_2026':s['holding_return'],'sector_mean_2025':means['all']['2025'],'sector_mean_2026':means['all']['2026'],'selected_mean_2025':means['selected']['2025'],'selected_mean_2026':means['selected']['2026']})
assert len(top)==100 and len({s['symbol'] for s in top})==100
payload={'sectors':sectors,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'config':d['config'],'selection':'2025 full-year return top 100 of 500 eligible year-end constituent securities','excluded_from_full_year':['SNDK','Q','PSKY']}
(P/'data.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
with (P/'top100.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(sorted(rows,key=lambda x:x['rank']))
t=(P/'template.html').read_text();(P/'report.html').write_text(t.replace('__DATA__',json.dumps(payload,ensure_ascii=False).replace('</','<\\/')))
print('100 stocks; 11 sectors; frozen data and report generated')
