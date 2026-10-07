"""Read a validated brief; render the same item IDs and evidence in two languages."""
import html
from pathlib import Path
from .contract import validate_brief


def render(brief, packet, task, packet_sha, output):
    brief = validate_brief(brief, packet, task, packet_sha)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for lang in ('zh', 'en'):
        lines = [f"# {brief['title'][lang]}", '', brief['scope_limitation'][lang], '',
            f"Company: {brief['company_id']} · Period: {brief['period_end']} · Cutoff: {task['cutoff']}", '',
            '质量状态 / Quality: candidate; exact source locations checked; semantic acceptance pending.', '']
        for item in brief['items']:
            lines += [f"## {item['id']} · {item['priority']}", '', item['statement'][lang], '',
                f"归属 / Attribution: {item['attribution'][lang]}",
                f"期间 / Period: {item['period_scope'][lang]}",
                f"依据类型 / Basis: {item['kind']} · {item['uncertainty']}", '',
                f"重要性 / Why: {item['priority_reason'][lang]}", '']
            lines += [f"- {q[lang]}" for q in item['qualifications']]
            lines += ['', ' · '.join(f"[原文 / Source {r['block_id']}](evidence.html#{r['block_id']})" for r in item['excerpts']), '']
        lines += ['## 缺口 / Gaps', '']
        for gap in brief['gaps']:
            lines += [f"- **{gap['status']}**: {gap['question'][lang]} — {gap['explanation'][lang]}"]
        lines += ['', '## 覆盖 / Coverage', '', '| Source block | Disposition | Items | Reason |', '|---|---|---|---|']
        for row in brief['coverage']:
            reason = row['reason'][lang].replace('|', '\\|').replace('\n', ' ')
            lines += [f"| [{row['block_id']}](evidence.html#{row['block_id']}) | {row['disposition']} | {', '.join(row['item_ids'])} | {reason} |"]
        (output/f'brief.{lang}.md').write_text('\n'.join(lines)+'\n')
    e = html.escape
    parts = ['<!doctype html><meta charset="utf-8"><title>Filing brief evidence</title>',
        '<style>body{font:18px/1.6 system-ui;max-width:960px;margin:40px auto;padding:0 24px}article{border-top:1px solid #ddd;padding:24px 0}pre{white-space:pre-wrap}small{overflow-wrap:anywhere}</style>',
        '<h1>精编原文依据 / Filing brief evidence</h1>',
        '<p>Selected source only. Exact locations verified; semantic review remains separate.</p>',
        f'<p>{e(packet["company_id"])} · {e(packet["document_id"])} · {e(packet["period_end"])}</p>',
        f'<small>Source SHA-256: {e(packet["source_sha256"])}</small>']
    for block in packet['blocks']:
        parts += [f'<article id="{e(block["id"], quote=True)}"><h2>{e(block["id"])}</h2>',
            f'<small>Original DOM: {e(block["source_dom_path"])}</small><pre>{e(block["text"])}</pre></article>']
    (output/'evidence.html').write_text('\n'.join(parts))
    return {'items': len(brief['items']), 'blocks': len(brief['coverage']), 'gaps': len(brief['gaps']),
            'location_checks': 'passed', 'semantic_acceptance': 'not_evaluated'}
