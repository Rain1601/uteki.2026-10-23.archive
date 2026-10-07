#!/usr/bin/env python3
"""Render the system's own semantic review/revision, preserving initial output."""
import argparse
from decimal import Decimal
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
    parser.add_argument('--initial-summary', type=Path, required=True)
    parser.add_argument('--initial-page', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--with-svg', action='store_true')
    args = parser.parse_args()
    summary_path, initial_path = view.local(args.summary), view.local(args.initial_summary)
    summary, initial = view.read(summary_path), view.read(initial_path)
    if (summary.get('schema_version') != 'business-semantic-self-review-v1' or summary.get('status') != 'candidate'
            or summary.get('execution_mode') != 'bounded_semantic_self_review'
            or initial.get('schema_version') != 'independent-business-run-v1' or initial.get('status') != 'candidate'
            or any(item.get('unknown_requests') or item.get('in_flight_requests') for item in (summary, initial))):
        raise ValueError('settled_completed_initial_and_self_review_required')
    run, origin = (ROOT / summary['candidate_path']).resolve(), (ROOT / initial['candidate_path']).resolve()
    if not run.is_relative_to(summary_path.parent) or not origin.is_relative_to(initial_path.parent):
        raise ValueError('candidate_outside_recorded_run')
    source, result = view.read(view.local(run/'source_packet.json')), view.read(view.local(run/'result.json'))
    origin_result = view.read(view.local(origin/'result.json'))
    draft, own_review = view.read(view.local(origin/'draft.json')), view.read(view.local(summary_path.parent/'review/review.json'))
    payload = view.parse_json_object(view.read(view.local(run/'request.json'))['messages'][0]['content'])
    if (result.get('execution_mode') != 'semantic_self_revision'
            or summary['input_run'] != initial['candidate_path']
            or summary['input_trace_id'] != origin_result['trace_id']
            or result.get('parent_trace_id') != origin_result['trace_id']
            or summary['input_result_sha256'] != view.sha(origin/'result.json')
            or summary['input_draft_sha256'] != view.sha(origin/'draft.json')
            or payload != {'frozen_source_packet': source, 'own_candidate': draft, 'own_self_review': own_review}
            or any(summary[key] != result[key] or initial[key] != result[key] for key in ('source_packet_sha256', 'skill_sha256'))):
        raise ValueError('self_revision_lineage_or_actual_payload_mismatch')
    if (result['budget']['estimated_spent_usd'] != summary['budget']['estimated_spent_usd']
            or summary['budget']['estimated_spent_usd'] != summary['estimated_spent_usd']):
        raise ValueError('self_review_cumulative_cost_mismatch')
    total = Decimal(initial['estimated_spent_usd']) + Decimal(summary['estimated_spent_usd'])
    calls = len(initial['attempts']) + summary['budget']['requests']
    initial_page = view.local(args.initial_page/'index.html')
    def execution_notice(result, paths, output):
        stages = initial['attempts'] + summary['attempts']
        rows = []
        for index, attempt in enumerate(stages, 1):
            directory = (ROOT/attempt['path']).resolve()
            links = [view.link(label, view.href(view.local(directory/name), output)) for name, label in
                     [('request.json','请求 / Request'), ('response.txt','模型原始响应 / Response'), ('result.json','记录 / Result')] if (directory/name).is_file()]
            rows.append('<li>' + str(index) + ' · ' + view.esc(attempt['mode']) + ' · ' + view.esc(attempt['status']) + ' · ' + ' / '.join(links) + '</li>')
        return ('<div class="notice"><strong>B2 · Agent 生成 → 模型自检 → 自动修订 / Agent generation → self-review → revision</strong>'
                '<p>本次修订读取同一冻结原文、自身初次产物，以及模型自己生成的审阅意见。没有读取参考答案或 Codex 的具体内容修订意见；没有人工修改本候选的事实、关系或引用。</p>'
                '<p>模型自检不是独立验收。下方“内容复核”是运行结束后的 Codex 原文核查，和自检分开记录。</p>'
                '<p>本次独立任务共 ' + str(calls) + ' 次模型调用 · 估算总费用 $' + str(total)
                + '（首次 $' + initial['estimated_spent_usd'] + ' + 自检及修订共 $' + summary['estimated_spent_usd']
                + '）。实际账单未核对；自检阶段使用共享累计账本，没有重复相加两阶段记录。</p><p>'
                + view.link('B1 · 首次独立版', view.href(initial_page, output)) + ' · '
                + view.link('首次执行账本 / Initial ledger', view.href(initial_path, output)) + ' · '
                + view.link('自检修订账本 / Self-review ledger', view.href(summary_path, output)) + ' · '
                + view.link('模型自检意见 / Model self-review', view.href(summary_path.parent/'review/review.json', output))
                + '</p><details><summary>三次真实请求与响应 / Actual requests and responses</summary><ol>' + ''.join(rows) + '</ol></details></div>')
    view.execution_notice = execution_notice
    view.build(run, args.output, args.review, args.with_svg, graph_stage=True)
    if args.with_svg:
        path = args.output/'verification.json'
        verification = view.read(path)
        page_path = args.output/'index.html'
        page_text = page_path.read_text().replace('图中已记录的归属关系清楚，不代表所有业务细节均已回答。', '图中关系是模型候选；未决问题为空也不能证明没有遗漏，正确性见内容复核。')
        page_path.write_text(page_text)
        verification['files']['page'] = view.sha(page_path)
        verification.update(initial_summary_sha256=view.sha(initial_path), self_review_summary_sha256=view.sha(summary_path),
                            independent_execution_mode='initial_generation_then_model_self_review_and_revision',
                            extraction_attempts=calls, task_estimated_spent_usd=str(total),
                            self_review_is_independent_evaluation=False, actual_payload_verified='frozen_source_packet + own_candidate + own_self_review')
        verification['files']['self_review_adapter'] = view.sha(Path(__file__))
        path.write_text(json.dumps(verification, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
