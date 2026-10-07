"""Result inspection and human scoring; execution and artifacts stay immutable."""
from html import escape
import json
from urllib.parse import urlencode

from apps.review_workbench.assets import asset_text
from apps.review_workbench.components.visual_system import workbench_page
from apps.review_workbench.pages.agent_runs import AGENTS, safe_link, call_configuration_record


def list_results(root, **kwargs):
    from apps.review_workbench.data.agent_run_results import list_results as loader
    return loader(root, **kwargs)


def load_result(root, identity, **kwargs):
    from apps.review_workbench.data.agent_run_results import load_result as loader
    return loader(root, identity, **kwargs)


def compare_results(root, left, right, **kwargs):
    from apps.review_workbench.data.agent_run_results import compare_results as loader
    return loader(root, left, right, **kwargs)


def e(value):
    return escape('' if value is None else str(value), quote=True)


def bi(zh, en):
    return '<span lang="zh">' + e(zh) + '</span><span lang="en">' + e(en) + '</span>'


def known(value):
    return bi('未记录', 'Not recorded') if value is None or value == '' else e(value)


def number(value):
    return known(value) if value is None else e(f'{value:,}' if isinstance(value, (int, float)) else value)


def delivery_label(detail):
    if (detail.get('result_view') or {}).get('kind') == 'no_visible_output':
        return bi('未交付 · 无可见结果', 'Not delivered · No visible output')
    return known((detail.get('state') or {}).get('delivery'))


def delivery_notice(detail):
    if (detail.get('result_view') or {}).get('kind') != 'no_visible_output':
        return ''
    body = '<div class="rr-delivery-notice" data-delivery-notice><strong>' + bi('未交付：没有可见正文', 'Not delivered: no visible answer') + '</strong>'
    if (detail.get('state') or {}).get('stop_reason') == 'length':
        body += '<p>' + bi('这次调用因输出额度用尽而停止。', 'This call stopped at its output limit.') + '</p>'
    usage = detail.get('usage') or {}
    output, reasoning = usage.get('output_tokens'), usage.get('reasoning_tokens')
    if type(output) is int and output > 0 and type(reasoning) is int and output == reasoning:
        body += '<p>' + bi(f'已记录的 {output:,} 个输出 Token 全部用于推理，没有返回正文。', f'All {output:,} reported output tokens were reasoning tokens; no visible answer was returned.') + '</p>'
    body += '<p>' + bi('这条记录可检查未交付原因与成本；没有正文可评判提取准确性或分析质量。', 'Inspect this attempt for non-delivery and cost; no answer is available to assess extraction accuracy or analysis quality.') + '</p></div>'
    return body


def url(**values):
    return '/agent-results?' + urlencode({k: v for k, v in values.items() if v is not None})


def parse_selection(selection):
    if not isinstance(selection, dict) or set(selection) - {'agent', 'run', 'compare', 'artifact'}:
        raise ValueError('Unknown Agent result selection')
    args = {}
    for key, values in selection.items():
        if (not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str)
                or not values[0].strip() or values[0] != values[0].strip() or len(values[0]) > 300):
            raise ValueError('Explicit single nonblank selection required')
        args[key] = values[0]
    if args.get('agent', 'data') not in AGENTS:
        raise ValueError('Unknown Agent')
    if (args.get('compare') or args.get('artifact')) and not args.get('run'):
        raise ValueError('An explicit primary run is required')
    if args.get('compare') == args.get('run') and args.get('run'):
        raise ValueError('Select two different runs')
    if args.get('run') and args.get('agent', 'data') != 'data':
        raise ValueError('This Agent has no registered results')
    return args


def _scope(scope):
    return ' · '.join(str(v) for v in (scope.get('company_id'), ', '.join(scope.get('periods') or []),
                                       scope.get('knowledge_cutoff')) if v)


def _refs(detail):
    """Keep the root Trace ID separate from the artifact's actual child owner."""
    seen, result = set(), []
    for ref in (detail.get('artifacts') or []) + (detail.get('configs') or []) + (detail.get('result_view', {}).get('artifacts') or []):
        key = (ref['id'], ref['run_id'])
        if key not in seen:
            result.append(ref)
            seen.add(key)
    return result


def _ref_buttons(refs):
    return ''.join('<div class="rr-ref"><button type="button" data-artifact="' + e(ref['id'])
        + '" data-artifact-owner="' + e(ref['run_id']) + '">' + e(ref.get('label') or ref['id'])
        + '</button><small>' + known(ref.get('availability')) + '</small></div>' for ref in refs)


def _model_summary(detail):
    body = '<section class="rr-models"><h3>' + bi('模型与配置', 'Models & configuration') + '</h3>'
    models = detail.get('models') or []
    if not models:
        return body + '<p class="rr-note">' + bi('没有已记录的模型调用。', 'No model calls are recorded.') + '</p></section>'
    body += '<div class="rr-table-scroll"><table class="rr-table"><thead><tr>'
    body += ''.join('<th>' + bi(*label) + '</th>' for label in [('角色 / 模型', 'Role / model'), ('供应商', 'Provider'), ('推理档位 / 模式', 'Effort / mode'), ('调用', 'Calls')]) + '</tr></thead><tbody>'
    for model in models:
        mode = bi('供应商默认，档位未指定', 'Provider default, effort unspecified') if model.get('thinking_mode') == 'provider_default_unspecified' else known(model.get('thinking_mode'))
        body += '<tr><td><strong>' + known(model.get('model')) + '</strong><small>' + known(model.get('role')) + '</small></td><td>' + known(model.get('provider')) + '</td><td>' + known(model.get('reasoning_effort')) + '<small>' + mode + '</small></td><td class="rr-number">' + number(model.get('call_count')) + '</td></tr>'
    usage = detail.get('usage') or {}
    body += '</tbody></table></div><dl class="rr-metrics">'
    for key, zh, en in [('input_tokens', '输入 Token', 'Input tokens'), ('output_tokens', '输出 Token', 'Output tokens'), ('known_estimated_usd', '已知估算 USD', 'Known estimate USD'), ('unknown_cost_requests', '费用未知调用', 'Unknown-cost calls')]:
        body += '<div><dt>' + bi(zh, en) + '</dt><dd>' + number(usage.get(key)) + '</dd></div>'
    body += '</dl><p class="rr-note">' + bi('包含子任务调用。未记录的档位不推定为默认值；估算费用不是账单。', 'Includes child calls. Missing effort is not inferred as a default; estimated cost is not a bill.') + '</p>'
    if detail.get('configs'):
        body += '<details><summary>' + bi('查看运行配置记录', 'Inspect configuration records') + '</summary>' + _ref_buttons(detail['configs']) + '</details>'
    body += '<h4>' + bi('实际调用时间与配置快照', 'Actual call times & configuration snapshots') + '</h4>'
    body += ''.join(call_configuration_record(call) for call in detail.get('calls') or []) or '<p class="rr-note">' + bi('没有可显示的逐次调用记录。', 'No per-call records are available.') + '</p>'
    return body + '</section>'


def _result_body(detail):
    view = detail.get('result_view') or {}
    body = '<section class="rr-output"><h3>' + bi('运行结果', 'Run result') + '</h3>'
    if view.get('summary'):
        body += '<p class="rr-note">' + e(view['summary']) + '</p>'
    if view.get('kind') == 'no_visible_output':
        body += '<p class="rr-empty rr-warning" data-no-output>' + bi('本次调用没有可见结果。请查看停止原因、用量和过程；不能将其作为已完成报告。', 'This call produced no visible result. Inspect its stop reason, usage and process; this is not a completed report.') + '</p>'
    if view.get('facts'):
        body += '<h4>' + bi('提取事实', 'Extracted facts') + '</h4><div class="rr-table-scroll"><table class="rr-table rr-facts"><thead><tr>'
        body += ''.join('<th>' + bi(*label) + '</th>' for label in [('指标', 'Metric'), ('期间', 'Period'), ('数值 / 单位', 'Value / unit'), ('证据', 'Evidence')]) + '</tr></thead><tbody>'
        for fact in view['facts']:
            body += '<tr><td>' + e(fact.get('metric')) + '</td><td>' + known(fact.get('period')) + '<small>' + known(fact.get('period_end')) + '</small></td><td class="rr-number">' + number(fact.get('value')) + '<small>' + known(fact.get('unit')) + ' · ' + known(fact.get('currency')) + '</small></td><td><details><summary>' + e(fact.get('block_id')) + '</summary><p>' + bi('行 / 列', 'Row / column') + ': ' + known(fact.get('row')) + ' / ' + known(fact.get('column')) + '</p><blockquote>' + e(fact.get('quote')) + '</blockquote></details></td></tr>'
        body += '</tbody></table></div>'
    if view.get('analysis'):
        body += '<h4>' + bi('分析', 'Analysis') + '</h4><ol class="rr-analysis">'
        for item in view['analysis']:
            if isinstance(item, dict):
                body += '<li><p>' + e(item.get('claim')) + '</p><small>' + e(' · '.join(item.get('block_ids') or [])) + '</small></li>'
            else:
                body += '<li>' + e(item) + '</li>'
        body += '</ol>'
    if view.get('gaps'):
        body += '<h4>' + bi('结果缺口', 'Result gaps') + '</h4><ul class="rr-gaps">' + ''.join('<li>' + e(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)) + '</li>' for item in view['gaps']) + '</ul>'
    if view.get('kind') == 'data_artifacts' and not view.get('artifacts'):
        body += '<p class="rr-empty">' + bi('尚无可读取的结果文件。', 'No readable result files are available.') + '</p>'
    if view.get('artifacts'):
        body += '<h4>' + bi('结果文件', 'Result files') + '</h4>' + _ref_buttons(view['artifacts'])
    for link in detail.get('links') or []:
        href = safe_link(link.get('href'))
        if href:
            body += '<p><a class="rr-trace" href="' + e(href) + '">' + bi('产物明细', 'Artifact details') + ' · ' + e(link.get('label')) + '</a></p>'
    extra = [ref for ref in _refs(detail) if (ref['id'], ref['run_id']) not in {(x['id'], x['run_id']) for x in (view.get('artifacts') or []) + (detail.get('configs') or [])}]
    if extra:
        body += '<details><summary>' + bi('更多运行文件', 'More run files') + '</summary>' + _ref_buttons(extra) + '</details>'
    return body + '</section>'


RUBRIC = [('accuracy', '事实准确性', 'Factual accuracy'), ('coverage', '任务覆盖', 'Task coverage'),
          ('analysis', '分析价值', 'Analytical value'), ('evidence', '证据可追溯', 'Evidence traceability')]


def _scores(detail):
    body = '<section class="rr-scores"><h3>' + bi('独立评分', 'Independent scoring') + '</h3><p class="rr-note">' + bi('每项 0–5 分；0 为零分，留空为未评分。1–4 表示从较弱到较好，5 表示完全满足任务。评分记录单独保存，不改变原产物或采纳状态。', 'Score each dimension from 0 to 5. Zero is a score; blank means unscored. Scores 1–4 range from weak to good; 5 fully meets the task. Reviews are stored separately and do not change the output or adoption state.') + '</p>'
    body += '<details><summary>' + bi('评分口径 · agent-result-v1', 'Rubric · agent-result-v1') + '</summary><ul class="rr-note">'
    for zh, en in [('事实准确性：数值、符号、期间和分析陈述是否正确。', 'Accuracy: correct values, signs, periods and analytical statements.'), ('任务覆盖：是否完成明确要求的内容；缺失与无输出应被计入。', 'Coverage: completion of the requested work, including omissions or no output.'), ('分析价值：解释是否有依据，是否区分事实、推断和限制。', 'Analysis: useful, supported explanations that distinguish facts, inferences and limits.'), ('证据可追溯：结论能否回到匹配范围的来源位置。', 'Evidence: claims can be traced to source locations within the selected scope.')]:
        body += '<li>' + bi(zh, en) + '</li>'
    body += '</ul></details><form data-score-form><label>' + bi('评分人', 'Reviewer') + '<input name="reviewer" required maxlength="100" autocomplete="off"></label><div class="rr-score-fields">'
    for key, zh, en in RUBRIC:
        body += '<label>' + bi(zh, en) + '<select name="' + key + '"><option value="">—</option>' + ''.join('<option value="' + str(i) + '">' + str(i) + '</option>' for i in range(6)) + '</select></label>'
    body += '</div><label>' + bi('评分依据与备注', 'Reasons and notes') + '<textarea name="notes" rows="3" maxlength="4000"></textarea></label><div class="rr-controls"><button type="submit">' + bi('保存这次评分', 'Save review') + '</button><button type="button" data-reload-scores>' + bi('重读评分', 'Reload reviews') + '</button></div></form><p data-score-status role="status" class="rr-note"></p><div data-score-history></div></section>'
    return body


def _card(detail, label):
    identity = detail['id']
    process_url = '/agent-runs?' + urlencode({'agent': detail.get('agent', 'data'), 'run': identity})
    body = '<article class="rr-result" data-result="' + e(identity) + '"><header><p class="rr-eyebrow">' + e(label) + ' · ' + e(detail.get('origin')) + '</p><h2>' + e(detail.get('title') or identity) + '</h2><a class="rr-trace" href="' + e(process_url) + '">Trace ID · ' + e(identity) + ' ↗</a><p class="rr-scope">' + e(_scope(detail.get('scope') or {})) + '</p></header>'
    task = detail.get('task')
    if task:
        body += '<details class="rr-task"><summary>' + bi('任务输入', 'Task input') + '</summary><pre>' + e(task if isinstance(task, str) else json.dumps(task, ensure_ascii=False, indent=2)) + '</pre></details>'
    body += delivery_notice(detail) + '<dl class="rr-statuses">'
    for key, zh, en in [('execution', '执行', 'Execution'), ('delivery', '交付', 'Delivery'), ('quality', '内容质量', 'Content quality'), ('adoption', '采纳', 'Adoption')]:
        label = delivery_label(detail) if key == 'delivery' else known((detail.get('state') or {}).get(key))
        body += '<div><dt>' + bi(zh, en) + '</dt><dd data-state="' + key + '">' + label + '</dd></div>'
    body += '</dl><p class="rr-note">' + bi('停止原因', 'Stop reason') + ': ' + known((detail.get('state') or {}).get('stop_reason')) + '</p>'
    if detail.get('live'):
        body += '<p class="rr-note">' + bi('当前显示已读取的运行版本。查看实时过程或刷新以读取新结果；评分绑定当前版本。', 'Showing the loaded revision. Open the live process or refresh for newer results; reviews are bound to this revision.') + '</p>'
    body += _model_summary(detail) + _result_body(detail)
    body += '<section class="rr-artifact-view" data-artifact-view hidden><div class="rr-controls"><h3 data-artifact-title></h3><button type="button" data-close-artifact>' + bi('关闭文件', 'Close file') + '</button></div><p data-artifact-status class="rr-note" role="status"></p><div data-artifact-children></div><pre data-artifact-content></pre><button type="button" data-more-artifact hidden>' + bi('继续读取', 'Read more') + '</button></section>'
    return body + _scores(detail) + '</article>'


@workbench_page('agent-results')
def render_agent_results(root, selection, *, observation_root=None, output_roots=()):
    args = parse_selection(selection)
    agent = args.get('agent', 'data')
    options = {'observation_root': observation_root, 'output_roots': output_roots}
    listing = list_results(root, agent=agent, **options) if agent == 'data' else {'results': [], 'total': 0}
    items = listing['results']
    details, comparison = [], None
    if args.get('run'):
        primary = load_result(root, args['run'], **options)
        if primary['id'] != args['run']:
            raise ValueError('Loaded result identity mismatch')
        details.append(primary)
        if args.get('compare'):
            comparison = compare_results(root, args['run'], args['compare'], **options)
            second = comparison['right']
            if comparison['left']['id'] != args['run'] or second['id'] != args['compare']:
                raise ValueError('Comparison identity mismatch')
            details = [comparison['left'], second]
        if args.get('artifact') and not any(ref['id'] == args['artifact'] for ref in _refs(details[0])):
            raise ValueError('Artifact does not belong to the selected result')
    directory = '<h2>' + bi('Agent 运行结果', 'Agent results') + '</h2><nav class="rr-agents" aria-label="Agent">'
    for key, (label, zh, en) in AGENTS.items():
        directory += '<a href="' + e(url(agent=key)) + '"' + (' aria-current="page"' if agent == key else '') + '><strong>' + e(label) + '</strong><small>' + bi(zh, en) + '</small></a>'
    directory += '</nav><label class="rr-search">' + bi('查找运行结果', 'Find results') + '<input id="rr-search" type="search"></label><div id="rr-result-list">'
    for item in items:
        identity = item['id']
        directory += '<a class="rr-run" data-result-row="' + e(identity) + '" href="' + e(url(agent=agent, run=identity)) + '"' + (' aria-current="page"' if identity == args.get('run') else '') + '><strong>' + e(item.get('title') or identity) + '</strong><small>' + e(identity) + '</small><small>' + e(_scope(item.get('scope') or {})) + '</small><small>' + delivery_label(item) + '</small></a>'
    directory += '</div><p id="rr-list-empty" class="rr-empty"' + (' hidden' if items else '') + '>' + bi('没有可显示的结果。', 'No results to display.') + '</p>'
    toolbar = '<div class="rr-toolbar"><h1>' + bi('运行结果', 'Run results') + '</h1><div class="rr-controls"><button type="button" id="rr-refresh">' + bi('刷新结果', 'Refresh results') + '</button><button type="button" id="rr-language">中文 / EN</button></div></div>'
    content = ''
    if details:
        candidates = [item for item in items if item['id'] != args['run']]
        content += '<p class="rr-note" data-saved-comparison>' + bi('这里读取已保存的运行结果。选择、并排比较或刷新页面均不会触发新的模型调用。请按各自实际调用时间区分历史结果。', 'This view reads saved results. Selecting, comparing or refreshing does not start a new model call. Use each result’s actual call time to identify historical runs.') + '</p>'
        content += '<form class="rr-comparison-picker" method="get" action="/agent-results"><input type="hidden" name="agent" value="' + e(agent) + '"><input type="hidden" name="run" value="' + e(args['run']) + '"><label>' + bi('选择第二次运行', 'Select a second run') + '<select name="compare" required><option value="" disabled' + (' selected' if not args.get('compare') else '') + '>—</option>'
        content += ''.join('<option value="' + e(item['id']) + '"' + (' selected' if item['id'] == args.get('compare') else '') + '>' + e(item.get('title') or item['id']) + ' · ' + e(item['id']) + '</option>' for item in candidates)
        content += '</select></label><button type="submit"' + (' disabled' if not candidates else '') + '>' + bi('并排比较', 'Compare side by side') + '</button>'
        if comparison:
            content += '<a href="' + e(url(agent=agent, run=args['run'])) + '">' + bi('返回单次结果', 'Single result') + '</a>'
        content += '</form>'
        if comparison:
            content += '<section class="rr-comparison-note' + ('' if comparison.get('comparable') else ' rr-warning') + '" data-comparable="' + str(bool(comparison.get('comparable'))).lower() + '"><strong>' + (bi('输入、任务与输出约定一致，可逐项对照。', 'Input, task and output contract match for comparison.') if comparison.get('comparable') else bi('输入或任务口径不一致，不构成同条件 A/B。', 'Inputs or task contracts differ; this is not a like-for-like A/B.')) + '</strong>'
            content += '<p class="rr-note">' + bi('模型、推理档位与输出预算仍需逐项核对。评分独立保存，不自动汇总或排名。', 'Compare model, reasoning effort and output budget separately. Reviews remain independent; no automatic total or ranking.') + '</p>'
            content += ''.join('<p class="rr-note">' + e(reason) + '</p>' for reason in comparison.get('reasons') or []) + '</section>'
            if comparison.get('limitations'):
                content += '<div class="rr-note">' + ''.join('<p>' + e(item) + '</p>' for item in comparison['limitations']) + '</div>'
        content += '<div class="rr-results' + (' rr-pair' if comparison else '') + '">' + ''.join(_card(detail, 'A' if i == 0 and comparison else 'B' if comparison else 'Result') for i, detail in enumerate(details)) + '</div>'
    else:
        content = '<p class="rr-empty">' + (bi('选择一次运行，查看产物、模型配置和评分。每个 Trace ID 都连接到对应过程。', 'Select a run to inspect its output, model settings and reviews. Each Trace ID links to its process.') if agent == 'data' else bi(AGENTS[agent][1], AGENTS[agent][2])) + '</p>'
    config = {'selection': args, 'details': details, 'api': '/api/agent-results', 'artifact_api': '/api/agent-runs'}
    payload = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent 运行结果 · Uteki</title><style>' + asset_text('agent_results.css') + '</style></head><body><div class="rr-workspace"><aside class="rr-directory">' + directory + '</aside><main class="rr-main">' + toolbar + content + '</main></div><script type="application/json" id="rr-config">' + payload + '</script><script>' + asset_text('agent_results.js') + '</script></body></html>'
