"""Explicit experiment adapter reusing the reviewed Mermaid renderer and evidence view."""
import argparse
import importlib.util
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('baseline_view',ROOT/'experiments/agent_design/2026-10-07-microsoft-clean-reextract-v1/build_view.py')
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--summary',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--review',type=Path)
    ap.add_argument('--with-svg',action='store_true');ap.add_argument('--overview',action='store_true');args=ap.parse_args()
    summary_path=view.local(args.summary);summary=view.read(summary_path)
    if summary.get('schema_version')!='business-coverage-run-v1' or summary.get('in_flight_requests'):
        raise ValueError('completed_coverage_run_required')
    run=view.local(ROOT/summary['candidate_path']/'result.json').parent
    result=view.read(run/'result.json')
    for key in ('source_packet_sha256','skill_sha256'):
        if result[key]!=summary[key]:raise ValueError('candidate_summary_binding_mismatch')
    inventory_path=summary_path.parent/'inventory/inventory.json'
    inventory=view.read(inventory_path) if inventory_path.exists() else None
    final_path=summary_path.parent/'audit_final/audit.json'
    audit_path=final_path if final_path.exists() else summary_path.parent/'audit_initial/audit.json'
    audit=view.read(audit_path) if audit_path.exists() else None
    draft=view.read(run/'draft.json')
    digest=hashlib.sha256(json.dumps(draft,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if summary['candidate_sha256']!=digest:raise ValueError('candidate_hash_mismatch')
    if audit and audit['candidate_sha256']!=digest:audit=None
    mentions={m['id']:m for m in inventory['mentions']} if inventory else {}
    def notice(result,paths,output):
        entries=[]
        for attempt in summary['attempts']:
            d=ROOT/attempt['path']
            links=[view.link(label,view.href(d/name,output)) for name,label in [('request.json','请求 / Request'),('response.txt','原答 / Response'),('result.json','结果 / Result')] if (d/name).exists()]
            entries.append('<li>'+view.esc(attempt['mode']+' · '+attempt['status'])+' · '+' / '.join(links)+'</li>')
        mapping=[]
        if audit:
            for item in audit['mappings']:
                mention=mentions[item['mention_id']]
                mapping.append('<tr><td>'+view.esc(mention['surface'])+'</td><td>'+view.esc(mention['category'])+'</td><td>'+view.esc(item['disposition'])+'</td><td>'+view.esc(', '.join(item['node_ids']))+'</td><td>'+view.esc(item['rationale'])+'</td></tr>')
        links=[view.link('技术方案 / Plan',view.href(Path(__file__).parent/'PLAN.zh-CN.md',output)),view.link('执行账本 / Run ledger',view.href(summary_path,output))]
        if inventory:links.append(view.link('原文提及清单 / Inventory',view.href(inventory_path,output)))
        if audit:links.append(view.link('逐项自检 / Self audit',view.href(audit_path,output)))
        if summary.get('prior_run'):
            links.append(view.link('上一轮账本 / Previous run',view.href(ROOT/summary['prior_run']/'summary.json',output)))
        if summary.get('input_audit_path'):
            links.append(view.link('本轮修订依据 / Revision input audit',view.href(ROOT/summary['input_audit_path'],output)))
        return ('<div class="notice"><strong>原文覆盖与证据核对 / Source coverage and claim audit</strong>'
            '<p>本轮状态：'+view.esc(summary['status'])+' · 自检：'+view.esc(summary['self_check_status'])+
            '。同模型自检不是独立验收；独立结果见下方内容复核。原始候选和旧版本保留。</p>'
            '<p>从已封存的系统独立候选继续；任务账本含历史恢复共 '+str(summary['budget']['requests'])+' 次请求，已知估算 $'+view.esc(summary['estimated_spent_usd'])+
            '；费用未知 '+str(summary.get('unknown_requests',0))+' 笔，仍保留 $'+view.esc(summary['budget'].get('held_usd','0'))+
            ' 预算占用，尚非最终账单。图形为系统候选，不因流程执行成功而变成已采纳事实。</p><p>'+' · '.join(links)+'</p>'
            '<details><summary>各阶段真实请求 / Stage records</summary><ol>'+''.join(entries)+'</ol></details>'
            '<details><summary>原文提及 → 图中位置 / Mention mapping ('+str(len(mapping))+')</summary><table><thead><tr><th>原文提及</th><th>语境</th><th>处置</th><th>节点</th><th>依据</th></tr></thead><tbody>'+''.join(mapping)+'</tbody></table></details></div>')
    view.execution_notice=notice
    view.build(run,args.output,args.review,args.with_svg,graph_stage=True,overview=args.overview)
    if args.with_svg:
        p=args.output/'verification.json';v=view.read(p)
        v.update(coverage_summary_sha256=view.sha(summary_path),self_check_status=summary['self_check_status'],
            coverage_adapter_sha256=view.sha(Path(__file__)),browser_visual_review='not_performed')
        p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
