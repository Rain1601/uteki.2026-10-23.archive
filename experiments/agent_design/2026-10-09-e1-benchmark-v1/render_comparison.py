"""Render the explicitly validated E1 configuration comparison, without model calls."""
import argparse
from html import escape
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render(value, output):
    if value.get('schema_version') != 'e1-config-comparison-v1' or value.get('controlled_fields_equal') is not True:
        raise ValueError('A validated controlled comparison is required')
    verification = value.get('verification', {})
    if not all(verification.get(k) is True for k in ('run_and_dataset_manifests',
            'fresh_retrieval_only', 'independent_review_run_and_gold_binding')):
        raise ValueError('Verified artifact and independent-review bindings are required')
    rows, details = [], []
    for row in value['runs']:
        name = row['run']
        model = row['settings']['planner']
        costs, coverage = row['costs'], row['coverage']
        timing = costs.get('request_timing', {})
        def duration(field):
            seconds = timing.get(field)
            return '未完整记录' if seconds is None else escape(f'{seconds:.2f} 秒')
        review = ROOT / 'evaluation-only/reviews' / name / 'README.zh-CN.md'
        if not review.is_file():
            raise ValueError('Independent review is missing')
        href = escape(os.path.relpath(review, output), quote=True)
        chars = row['characters']
        extra = sum(chars['categories'][k]['numerator'] for k in ('table_structure', 'duplicate', 'irrelevant'))
        workflow = {'reviewed_data_ready': '已交付', 'attempts_exhausted': '多轮后仍未通过',
                    'blocked_by_review_failure': '审核失败', 'blocked_by_query': '查询未完成',
                    'failed': '执行失败'}.get(row['workflow_status'], row['workflow_status'])
        independent = {'pass': '符合冻结标准', 'fail': '未通过'}.get(row['independent_status'], row['independent_status'])
        rows.append('<tr>' + ''.join('<td>' + cell + '</td>' for cell in (
            escape(model['model']) + '<small>' + escape(model['provider'] + ' · ' + str(model.get('reasoning_effort') or '未设置')) + '</small>',
            escape(workflow),
            escape(independent) + ' · ' + str(coverage['numerator']) + '/' + str(coverage['denominator']),
            '$' + escape(costs['known_estimated_usd']) + '<small>未知费用预留 $' + escape(costs['unknown_reserved_usd']) + '</small>', str(costs['calls']),
            duration('cumulative_request_seconds') + '<small>请求跨度 ' + duration('request_window_seconds') + '</small>',
            str(chars['delivered_character_occurrences']) + ' / ' + str(extra),
            '<a href="' + href + '">原件核对 / Review ↗</a>'
        )) + '</tr>')
        parts = []
        for group in costs['by_provider_model_stage_cost_basis']:
            parts.append('<li>' + escape(str(group['requested_model']) + ' · ' + str(group['stage']))
                + ': $' + escape(group['known_estimated_usd']) + ' · ' + str(group['calls']) + ' calls'
                + ' · 未知费用预留 $' + escape(group['unknown_reserved_usd'])
                + '<p>' + escape(str(group['cost_basis'])) + '</p></li>')
        details.append('<details><summary>' + escape(name) + ' · 分阶段费用 / Costs</summary><ul>'
                       + ''.join(parts) + '</ul></details>')
    question = value['invariants']['request']['question']
    verification_note = ('已比对运行中记录的查询协议与 Skill 哈希。' if
        verification.get('query_protocol_snapshots_present') and verification.get('skill_hash_snapshots_present')
        else '部分运行未记录查询协议或 Skill 哈希，不能据此宣称这些快照已核对。')
    limitations = '<ul>' + ''.join('<li>' + escape(item) + '</li>' for item in value['limits']) + '</ul>'
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>E1 · 模型配置对照</title>
<style>body{margin:0;background:#faf9f6;color:#253b45;font:16px/1.65 system-ui,sans-serif}main{max-width:1280px;margin:40px auto;padding:0 28px}h1{font-size:30px}h2{font-size:21px}a{color:#376478}table{width:100%;border-collapse:collapse;background:white}td,th{text-align:left;padding:15px;border-bottom:1px solid #dfdcd5;vertical-align:top}th{font-size:13px;color:#59645e}small{display:block;color:#738077}.table{overflow:auto}details{margin:16px 0;padding:14px;background:white;border:1px solid #dfdcd5;border-radius:8px}summary{cursor:pointer}p{max-width:1000px}.note{color:#59645e}.question{padding:20px;background:#eaf0ee;border-radius:8px}</style>
<main><a href="../e1-evidence-benchmark-v3/">← 七题独立验收 / Benchmark</a>
<h1>同一问题，不同模型配置<br><small>Controlled configuration comparison</small></h1>
<p class="question">''' + escape(question) + '''</p>
<p>已核对冻结原问题、数据集清单、来源范围、截止日、已记录的代码与依赖指纹及非模型配置一致。''' + escape(verification_note) + '''Planner / Worker 模型及努力级别不同；审核配置固定。配置相同不证明不同供应商的实际采样、思考和缓存机制相同。这是单次系统配置对照，不能推导模型排名或稳定性。</p>
<div class="table"><table><thead><tr><th>取材模型</th><th>流程状态</th><th>独立内容验收</th><th>本次已知估算 USD / 未知预留</th><th>调用数</th><th>累计请求耗时 / 请求跨度</th><th>交付字符 / 已标附带与冗余</th><th>依据</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div>
<p class="note">耗时包含成功与失败调用。累计请求耗时相加各次收据的 elapsed_seconds，并发重叠也计入；请求跨度使用首个 started_at 至最后 ended_at，包含调用间空档。这两项都不是完整任务的端到端耗时，也不是首 token 延迟。字段缺失、无效或有未结束请求时，相应总计显示“未完整记录”；不使用文件修改时间估算。</p>
<p class="note">费用包含本次全新取材、审核及失败调用；复用旧取材的恢复任务不能进入此完整成本对照。历史开发与失败费用另计入本轮总账，不会被成功运行覆盖。未知预留不当作零费用。不同供应商的缓存折扣估算口径可能不同，不能把这里的估算当账户账单。字符分类来自独立评审，附带与冗余列不包含全部可压缩上下文；标准通过不代表已达到严格最小材料。</p>
<h2>比较边界 / Limits</h2>''' + limitations + '''<h2>查看费用组成 / Inspect costs</h2>''' + ''.join(details) + '''</main></html>'''
    output.mkdir(parents=True, exist_ok=False)
    (output / 'index.html').write_text(html)
    (output / 'comparison.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(json.loads(args.input.read_text()), args.output)
