"""Render an actual filing-brief run; no model call and no semantic modification."""
import argparse
import html
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from uteki.agents.filing_brief import contract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run=(ROOT/args.run).resolve();output=(ROOT/args.output).resolve()
    if not run.is_relative_to(ROOT) or not output.is_relative_to(ROOT):raise ValueError('project_paths_required')
    result=json.loads((run/'summary.json').read_text())
    brief_path=(ROOT/result['brief_path']).resolve()
    if not brief_path.is_relative_to(run) and not result.get('candidate_retained_from_prior'):
        raise ValueError('brief_not_in_selected_run')
    stage=brief_path.parent
    packet=json.loads((stage/'packet.json').read_text());task=json.loads((stage/'task.json').read_text())
    brief=contract.validate_brief(json.loads(brief_path.read_text()),packet,task,result['source_packet_sha256'])
    e=html.escape
    def localized(value):
        return ''.join(f'<span class="lang-{lang}">{e(value[lang])}</span>' for lang in ('zh','en'))
    nav=[];articles=[]
    for item in brief['items']:
        nav.append(f'<a href="#{e(item["id"])}"><b>{e(item["id"])}</b> {localized({l:item["statement"][l][:70] for l in ("zh","en")})}</a>')
        citations=''.join(f'<details><summary><a href="evidence.html#{e(r["block_id"])}">{e(r["block_id"])} ↗</a></summary><blockquote>{e(r["quote"])}</blockquote></details>' for r in item['excerpts'])
        qualifiers=''.join('<li>'+localized(q)+'</li>' for q in item['qualifications'])
        articles.append(f'<article id="{e(item["id"])}"><small>{e(item["id"])} · {e(item["priority"])} · {e(item["kind"])}</small><p class="claim">{localized(item["statement"])}</p><p class="muted">{localized(item["attribution"])} · {localized(item["period_scope"])}</p><ul>{qualifiers}</ul><details><summary>重要性与原文 / Importance & evidence</summary><p>{localized(item["priority_reason"])}</p>{citations}</details></article>')
    gaps=''.join(f'<article><small>{e(g["id"])} · {e(g["status"])}</small><p>{localized(g["question"])}</p><p>{localized(g["explanation"])}</p></article>' for g in brief['gaps'])
    coverage=''.join(f'<tr><td><a href="evidence.html#{e(c["block_id"])}">{e(c["block_id"])}</a></td><td>{e(c["disposition"])}</td><td>{e(", ".join(c["item_ids"]))}</td><td>{localized(c["reason"])}</td></tr>' for c in brief['coverage'])
    output.mkdir(parents=True,exist_ok=True)
    for name in ('evidence.html','brief.zh.md','brief.en.md','brief.json'):
        shutil.copyfile(stage/name,output/name)
    budget=result['budget'];review=result.get('self_review','not_run')
    # Bind a review to the displayed candidate. A pre-revision audit is not a
    # review of the revised output, including historical summaries lacking this key.
    review_files=list(run.glob('*/review.json'))
    matching=[json.loads(p.read_text()) for p in review_files
              if json.loads(p.read_text()).get('brief_sha256')==contract.digest(brief)]
    review=matching[-1]['computed_status'] if matching else 'not_run_for_this_candidate'
    report='not_evaluated'
    findings=''
    review_path=run.parent/'evaluation/independent-review.json'
    if review_path.exists():
        reviewed=json.loads(review_path.read_text())
        if reviewed.get('brief_sha256')==contract.digest(brief):
            report=reviewed['status']
            shutil.copyfile(review_path,output/'independent-review.json')
            findings='<details><summary>独立复核记录 / Independent findings</summary><ul>'+''.join(
                f'<li>{e(c["item_id"])} · {e(c["detail"])}</li>' for c in reviewed.get('claim_checks',[])
                if c['verdict']!='supported')+'</ul><a href="independent-review.json">完整复核记录 / Full review</a></details>'
    source_link=packet['source_url'] if packet['source_url'].startswith(('http://','https://')) else '#'
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>财报精编 · {e(packet['company_id'])}</title>
<style>html,body{{height:100%;margin:0}}body{{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;color:#283738;background:#f8f8f5;display:flex;flex-direction:column}}*{{box-sizing:border-box}}header{{padding:12px 24px;border-bottom:1px solid #d9ded9;background:white;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}h1{{font-size:19px;margin:0}}header a,button{{font:inherit;color:#31596a}}button{{background:white;border:1px solid #c7d1ce;border-radius:4px;cursor:pointer}}.layout{{display:grid;grid-template-columns:280px minmax(0,1fr);flex:1;min-height:0}}nav{{overflow:auto;padding:14px;border-right:1px solid #d9ded9}}nav a{{display:block;padding:10px;color:inherit;text-decoration:none;border-bottom:1px solid #e4e7e1;font-size:14px}}nav a:focus,nav a:hover{{background:#e9efec}}main{{overflow:auto;padding:24px 40px;scroll-behavior:smooth}}.content{{max-width:980px;margin:auto}}article{{padding:24px 0;border-bottom:1px solid #d9ded9;scroll-margin-top:12px}}small,.muted{{color:#61716b}}.claim{{font-size:19px;line-height:1.8;margin:12px 0}}a{{color:#315e70}}summary{{cursor:pointer}}blockquote{{border-left:2px solid #b7c8bf;padding-left:16px;margin-left:8px;color:#52635b}}.status{{background:#eef2ed;border:1px solid #d5ded3;padding:15px 20px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}}.lang-en{{display:none}}body.english .lang-en{{display:initial}}body.english .lang-zh{{display:none}}@media(max-width:760px){{.layout{{grid-template-columns:170px minmax(0,1fr)}}main{{padding:18px}}.claim{{font-size:17px}}}}@media(prefers-reduced-motion:reduce){{main{{scroll-behavior:auto}}}}</style>
<header><h1>财报精编 / Filing brief</h1><span>{e(packet['company_id'])} · {e(packet['period_end'])}</span><button id="language">English / 中文</button><a href="{e(source_link,quote=True)}">财报原件 / Original ↗</a><a href="evidence.html">原文索引 / Source index</a><a href="brief.json">JSON</a></header>
<div class="layout"><nav aria-label="精编目录 / Brief contents">{''.join(nav)}<a href="#gaps">缺口 / Gaps</a><a href="#coverage">覆盖处置 / Coverage</a></nav><main><div class="content"><h2>{localized(brief['title'])}</h2><p>{localized(brief['scope_limitation'])}</p><div class="status">实际系统 Agent 产物 / Actual Agent output · {len(brief['items'])} items · {len(brief['coverage'])} blocks<br>当前稿模型复核 / Model review of this candidate: {e(review)} · 独立内容审阅 / Independent review: {e(report)}<br>本任务估算费用 / Task estimate: ${e(budget['estimated_spent_usd'])} · 未知费用预留 / Unknown reserve: ${e(budget['held_usd'])}<br>范围：所选小节；不代表整份财报精编完成。 / Selected subsection only.{findings}</div>{''.join(articles)}<h2 id="gaps">缺口 / Gaps</h2>{gaps}<h2 id="coverage">覆盖处置 / Coverage</h2><p>处置记录齐全不等于语义完整。 / Complete accounting does not establish semantic completeness.</p><table><thead><tr><th>Source block</th><th>Disposition</th><th>Items</th><th>Reason</th></tr></thead><tbody>{coverage}</tbody></table></div></main></div>
<script>document.getElementById('language').addEventListener('click',()=>{{document.body.classList.toggle('english');document.documentElement.lang=document.body.classList.contains('english')?'en':'zh-CN';}});</script></html>'''
    (output/'index.html').write_text(page)
    (output/'manifest.json').write_text(json.dumps(dict(run=str(run.relative_to(ROOT)),brief_sha256=contract.digest(brief),semantic_acceptance=report,visual_review='not_performed'),indent=2)+'\n')
    print(output/'index.html')


if __name__=='__main__':main()
