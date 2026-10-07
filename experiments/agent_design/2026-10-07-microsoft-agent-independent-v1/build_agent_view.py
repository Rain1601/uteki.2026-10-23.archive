#!/usr/bin/env python3
"""Render a completed independent system Agent candidate with its real run ledger.

This adapter reuses the frozen-renderer baseline without changing historical pages
or extraction artifacts. Prepare Mermaid, render it, then call --with-svg.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('clean_business_view', ROOT / 'experiments/agent_design/2026-10-07-microsoft-clean-reextract-v1/build_view.py')
view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(view)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--with-svg', action='store_true')
    args = parser.parse_args()
    summary_path = view.local(args.summary)
    summary = view.read(summary_path)
    if (summary.get('schema_version') != 'independent-business-run-v1'
            or summary.get('execution_mode') != 'independent_generation_with_bounded_self_revision'
            or summary.get('status') != 'candidate' or not summary.get('candidate_path')
            or summary.get('unknown_requests') or summary.get('in_flight_requests')):
        raise ValueError('completed_independent_candidate_and_settled_ledger_required')
    run = (ROOT / summary['candidate_path']).resolve()
    if not run.is_relative_to(summary_path.parent):
        raise ValueError('candidate_outside_selected_run')
    result = view.read(view.local(run / 'result.json'))
    if (summary['source_packet_sha256'] != result['source_packet_sha256']
            or summary['skill_sha256'] != result['skill_sha256']
            or not any(item.get('trace_id') == result['trace_id'] and item.get('path') == summary['candidate_path']
                       and item.get('status') == 'candidate' for item in summary['attempts'])):
        raise ValueError('summary_candidate_binding_mismatch')

    def execution_notice(result, paths, output):
        attempts = summary['attempts']
        independent = len(attempts) == 1
        title = 'Agent 独立首次生成 / Independent initial generation' if independent else 'Agent 独立生成与自动修订 / Generation with bounded self-revision'
        explanation = ('系统从冻结原文与固定 Skill 生成本候选。此次执行未触发修订。' if independent else
                       '系统首次生成后，根据程序校验返回的错误自动修订。修订使用同一冻结原文和该运行自身的输出；保留全部尝试。')
        rows = []
        for i, attempt in enumerate(attempts, 1):
            directory = (ROOT / attempt['path']).resolve()
            if not directory.is_relative_to(summary_path.parent):
                raise ValueError('attempt_outside_selected_run')
            logs = []
            for name, label in [('request.json', '请求 / Request'), ('response.txt', '原始响应 / Response'), ('result.json', '结果 / Result')]:
                if (directory / name).is_file():
                    logs.append(view.link(label, view.href(directory / name, output)))
            rows.append('<li>第 ' + str(i) + ' 次 / Attempt ' + str(i) + ' · ' + view.esc(attempt.get('mode', '未记录'))
                        + ' · ' + view.esc(attempt['status']) + ' · ' + ' / '.join(logs) + '</li>')
        fields = view.read(paths['configuration.json']).get('fields', {}) if 'configuration.json' in paths else {}
        settings = {key: {'value': fields[key].get('value'), 'status': fields[key].get('status')}
                    for key in ('model', 'thinking', 'reasoning_effort', 'max_tokens', 'stream', 'temperature', 'top_p', 'top_k') if key in fields}
        return ('<div class="notice"><strong>' + title + '</strong><p>' + explanation
                + ' 原文输入、Skill 与真实请求均留档；是否达到参考版质量由运行后复核判断。单次完成不代表已证明稳定性。</p>'
                + '<p>模型调用 ' + str(len(attempts)) + ' 次 · 本次任务累计估算 $' + view.esc(summary['estimated_spent_usd'])
                + ' / 上限 $' + view.esc(summary['budget_limit_usd']) + '。含失败用量；实际账单尚未核对。费用是本次独立任务，历史参考费用另计。</p>'
                + '<p>' + view.link('完整执行与费用 / Execution ledger', view.href(summary_path, output)) + '</p>'
                + '<details><summary>尝试记录与指定配置 / Attempts and requested settings</summary><ol>' + ''.join(rows)
                + '</ol><p class="caption">下面是请求时指定/未发送的配置，不是供应商生效值证明。</p><pre>'
                + view.esc(json.dumps(settings, ensure_ascii=False, indent=2)) + '</pre></details></div>')

    view.execution_notice = execution_notice
    view.build(run, args.output, args.review, args.with_svg, graph_stage=True)
    if args.with_svg:
        verification_path = args.output / 'verification.json'
        verification = view.read(verification_path)
        verification.update(independent_execution_summary_sha256=view.sha(summary_path),
                            independent_execution_mode=summary['execution_mode'],
                            extraction_attempts=len(summary['attempts']),
                            estimated_spent_usd=summary['estimated_spent_usd'])
        verification['files']['independent_adapter'] = view.sha(Path(__file__))
        verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
