"""Independent evaluation only. Never imported by the running Agent."""
from collections import Counter
from decimal import Decimal
import hashlib, json, os
from pathlib import Path
from html import escape
from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader
ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/figure-materials-20261012'
EXPECTED=BASE/'evaluation-only/expected.json'
golden=json.loads(EXPECTED.read_text())
rows=[]
for company in ('msft','googl'):
 dataset=ROOT/'output/preparation-acceptance-20261012/v5'/company/'dataset'
 bundle=BASE/'parsed-v3'/company
 reader=FigureMaterialReader(bundle,dataset)
 for item in reader.list():
  material=reader.read(item['figure_id']); trans=material['transcription']; image_sha=material['image_sha256']
  required=golden['images'][image_sha]
  actual=lambda role:[t['text'] for t in trans['texts'] if t['role']==role]
  checks={
   'legend_exact':Counter(actual('legend'))==Counter([required]+golden['legend_other']),
   'x_ticks_exact':Counter(actual('x_tick'))==Counter(golden['x_ticks']),
   'y_ticks_exact':Counter(actual('y_tick'))==Counter(golden['y_ticks']),
   'no_fabricated_values':trans['printed_values']==[],
   'no_fabricated_title':actual('title')==[],
   'complete_visible_text_count':len(trans['texts'])==34,
   'no_unreadable_regions':trans['unreadable_regions']==[],
   'grounded_consumer_read':material['coordinate_status']=='ocr_grounded',
  }
  by_id={t['id']:t['text'] for t in trans['texts']}
  colors={by_id[s['legend_id']]:s['color'].lower() for s in trans['series']}
  checks['series_colors']=colors[required]=='red' and colors['S&P 500']=='green' and colors['NASDAQ Composite']=='yellow' and colors['RDG Internet Composite'] in ('blue','dark blue')
  assert all(checks.values()),(item,checks)
  rows.append({'figure_id':item['figure_id'],'title':required,'checks':checks,'image_sha256':image_sha,'material':material})
assert len(rows)==2
calls={}
for version in ('parsed-v1','parsed-v2'):
 for f in (BASE/version).rglob('*-end.json'):
  d=json.loads(f.read_text());calls[d['call_id']]=d
cost=sum(Decimal(d['estimated_usd']) for d in calls.values())
report={'scope':'MSFT and GOOGL FY2025 10-K main HTML + referenced visible raster figures; no exhibits/proxy',
 'status':'passed_in_scope','golden_sha256':hashlib.sha256(EXPECTED.read_bytes()).hexdigest(),
 'figures':[{k:v for k,v in r.items() if k!='material'} for r in rows],
 'model_requests':len(calls),'extraction_estimated_usd':str(cost),'advisor_estimated_usd':'0.403976',
 'total_estimated_usd':str(cost+Decimal('0.403976')),'independent_model_batches':2,
 'final_coordinate_replay':'deterministic only; no additional API request',
 'input_tokens':sum(d['usage']['input_tokens'] for d in calls.values()),
 'output_tokens':sum(d['usage']['output_tokens'] for d in calls.values()),
 'limits':['Not a curve digitizer: no exact values exist on the source lines', 'No claim of complete financial normalization (2970 facts remain unmapped)', 'Named Tesseract English adapter; arbitrary languages/scans/formats not accepted', 'Main Query agent image-tool orchestration not evaluated'],
 'bundle_sha256':{c:hashlib.sha256((BASE/'parsed-v3'/c/'manifest.json').read_bytes()).hexdigest() for c in ('msft','googl')}}
(BASE/'evaluation-only/acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
# Acceptance-owned package links; do not rewrite frozen runtime acceptance flags.
package={'version':'reviewed-material-package-v1','independent_acceptance':report,
 'members':{c:{'dataset':str(ROOT/'output/preparation-acceptance-20261012/v5'/c/'dataset'), 'figures':str(BASE/'parsed-v3'/c)} for c in ('msft','googl')}}
(BASE/'material-package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2))
page=BASE/'review';page.mkdir(exist_ok=True)
def link(path):return escape(os.path.relpath(path,page),quote=True)
parts=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>FY2025 图片材料验收 / Figure acceptance</title><style>
*{box-sizing:border-box}body{margin:0;background:#faf9f6;color:#253238;font:15px/1.65 system-ui,sans-serif}main{max-width:1200px;margin:32px auto;padding:0 24px}h1{font-size:26px}h2{font-size:21px}a{color:#326275}section{background:white;border:1px solid #deded8;border-radius:8px;padding:24px;margin:24px 0}.muted{color:#64716d}.summary{border-left:3px solid #387d64;padding-left:18px}.frame{position:relative}.frame img{display:block;width:100%}.frame svg{position:absolute;inset:0;width:100%;height:100%}rect{fill:transparent;stroke:transparent;stroke-width:1.5}rect.active,rect:hover{fill:#f7c85b44;stroke:#976824}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #eee;padding:6px 10px}button{font:inherit;background:transparent;color:#326275;border:0;cursor:pointer;text-decoration:underline}.scroll{max-height:330px;overflow:auto}details{margin:16px 0}code{font-size:12px;overflow-wrap:anywhere}</style><main>
<h1>FY2025 材料准备：图片缺口已补齐</h1><p class="muted">Microsoft · Alphabet / Google ｜ 系统 Agent 真实执行，Codex 对照原件核验</p>
<div class="summary"><b>限定主文范围，材料准备验收通过。</b><p>此前文字、表格和索引已通过；本轮补齐两张原图及 68 项可见文字，保留精确图片出处。图中没有印刷曲线数值，因此没有生成猜测数据。</p></div>
<p>工程获取 → Sonnet 读取原图 → 本机 OCR 定位 → 完整性校验 → 独立原图核验。初稿文字正确、部分坐标错位；已由实际文字检测替代模型估位置。</p>
''']
parts.append(f'<p>4 次图像模型调用：${cost}；顾问：$0.403976；合计估算 <b>${report["total_estimated_usd"]}</b>。最终坐标重建没有额外模型调用。</p>')
for i,r in enumerate(rows):
 m=r['material'];texts=m['transcription']['texts']
 parts.append(f'<section><h2>{escape(r["title"])}</h2><p>34 项文字核对通过 · 4 个图例 · 21 个时间刻度 · 9 个金额刻度。点下方文字可高亮原图位置。</p><div class="frame"><img src="{link(m["original_image_path"])}" alt="{escape(r["title"])} original figure"><svg viewBox="0 0 1000 1000" preserveAspectRatio="none">')
 for j,t in enumerate(texts):
  b=t['box'];parts.append(f'<rect id="r{i}-{j}" x="{b["x0"]}" y="{b["y0"]}" width="{b["x1"]-b["x0"]}" height="{b["y1"]-b["y0"]}"><title>{escape(t["text"])}</title></rect>')
 parts.append('</svg></div><details><summary>解析文字与原图高亮 / Text and source regions</summary><div class="scroll"><table><tr><th>类型 / Role</th><th>原文 / Text</th></tr>')
 for j,t in enumerate(texts):parts.append(f'<tr><td>{escape(t["role"])}</td><td><button data-target="r{i}-{j}">{escape(t["text"])}</button></td></tr>')
 parts.append('</table></div></details><details><summary>原报告上下文与精确出处 / Filing context</summary>')
 sourceid=m['source_snapshot_id']; doc=ROOT/'output/preparation-acceptance-20261012/v5/googl/dataset/indexes'/sourceid/'document.html'
 for b in m['document_context']:
  parts.append(f'<p><a href="{link(doc)}#{escape(b["block_id"])}">{escape(b["block_id"])}</a> · {escape(b["text"])}</p>')
 parts.append(f'</details><p><a href="{link(m["original_image_path"])}">冻结原图</a> · <a href="{escape(m["source_url"],quote=True)}">SEC 原图</a> · <a href="{link(doc)}#{escape(m["locations"][0]["block_id"])}">报告中的图片位置</a></p><details><summary>绑定 / Provenance</summary><code>Image SHA256: {r["image_sha256"]}</code><p>最终高亮位置来自 OCR。模型初稿中关于位置估计的局限性说明作为历史记录保留，不代表最终位置仍越界。</p></details></section>')
parts.append('''<p class="muted">边界：本次是两份 FY2025 10-K 主文及引用图片的材料保真验收。不是所有财务指标已建库，也不是任意材料、语言或公司均已验收；主 Query Agent 的图片工具调用另行测试。</p><p><a href="../evaluation-only/acceptance.json">独立核验结果</a> · <a href="../material-package.json">完整材料包入口</a></p></main><script>document.querySelectorAll('button[data-target]').forEach(b=>b.onclick=()=>{document.querySelectorAll('rect.active').forEach(r=>r.classList.remove('active'));const r=document.getElementById(b.dataset.target);r.classList.add('active');r.closest('.frame').scrollIntoView({behavior:'smooth',block:'center'});});</script></html>''')
(page/'index.html').write_text(''.join(parts))
print(json.dumps({k:v for k,v in report.items() if k not in ('figures','limits','bundle_sha256')},ensure_ascii=False,indent=2))
