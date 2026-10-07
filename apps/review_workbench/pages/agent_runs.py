"""Read-only Agent execution views. Business state comes from validated loaders."""
from html import escape
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode, urlsplit

from apps.review_workbench.assets import asset_text
from apps.review_workbench.components.visual_system import workbench_page

TABS = {'process': ('步骤', 'Steps'), 'artifacts': ('过程文件', 'Process files'),
        'usage': ('用量', 'Usage'), 'config': ('输入与配置', 'Input & configuration')}
AGENTS = {'data': ('Data', '已接入', 'Available'),
          'analysis': ('Analysis', '限定原型 · 待接入', 'Limited prototype · Not connected'),
          'risk': ('Risk', '后端未实现', 'Backend not implemented'),
          'portfolio': ('Portfolio', '后端未实现', 'Backend not implemented')}

CONFIG_FIELDS = ('provider', 'model', 'api_format', 'base_url', 'max_tokens', 'thinking',
                 'reasoning_effort', 'temperature', 'top_p', 'top_k', 'seed', 'response_format',
                 'tool_choice', 'parallel_tool_calls', 'stream', 'timeout_seconds', 'max_retries')
CONFIG_LABELS = {'temperature': ('采样温度', 'Temperature'), 'top_p': ('累计概率', 'Top-P'),
                 'top_k': ('候选 token 数', 'Top-K')}
CONFIG_POLICIES = {
    'policy.sonnet55_sampling_unsupported': (
        {'temperature', 'top_p', 'top_k'}, '按记录的模型规则，不接受非默认采样设置。',
        'The recorded model policy does not permit non-default sampling settings.'),
    'policy.deepseek_thinking_sampling_ignored': (
        {'temperature'}, '按记录的模型规则，思考模式忽略 temperature。',
        'The recorded model policy ignores temperature in thinking mode.'),
    'policy.deepseek_top_k_unsupported': (
        {'top_k'}, '记录的 API 文档未列出 Top-K，因此未发送。',
        'The recorded API documentation does not list Top-K, so it was not sent.'),
    'policy.seed_not_documented': (
        {'seed'}, '记录的 API 文档未列出 seed，因此未发送。',
        'The recorded API documentation does not list seed, so it was not sent.'),
}


def list_runs(root, **kwargs):
    from apps.review_workbench.data.agent_runs import list_runs as loader
    return loader(root, **kwargs)


def load_run(root, identity, **kwargs):
    from apps.review_workbench.data.agent_runs import load_run as loader
    return loader(root, identity, **kwargs)


def e(value):
    return escape('' if value is None else str(value), quote=True)


def bi(zh, en):
    return '<span lang="zh">' + e(zh) + '</span><span lang="en">' + e(en) + '</span>'


def unknown(value):
    return bi('未记录', 'Not recorded') if value is None or value == '' else e(value)


def number(value):
    return unknown(value) if value is None else e(f'{value:,}' if isinstance(value, (int, float)) else value)


def url(**values):
    return '/agent-runs?' + urlencode({k: v for k, v in values.items() if v is not None})


def safe_link(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//') or '\\' in value:
        return None
    parts = urlsplit(value)
    return value if not parts.scheme and not parts.netloc else None


def parse_selection(selection):
    if not isinstance(selection, dict) or set(selection) - {'agent', 'run', 'tab', 'step', 'artifact'}:
        raise ValueError('Unknown Agent run selection')
    args = {}
    for key, values in selection.items():
        if (not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str)
                or not values[0].strip() or values[0] != values[0].strip() or len(values[0]) > 300):
            raise ValueError('Explicit single nonblank Agent selection required')
        args[key] = values[0]
    if args.get('agent', 'data') not in AGENTS or args.get('tab', 'process') not in TABS:
        raise ValueError('Unsupported Agent view')
    if (args.get('step') or args.get('artifact')) and not args.get('run'):
        raise ValueError('An explicit run is required')
    if args.get('run') and args.get('agent', 'data') != 'data':
        raise ValueError('This Agent has no registered runs')
    return args


def _scope(scope):
    return ' · '.join(str(v) for v in (scope.get('company_id'),
        ', '.join(scope.get('periods') or []), scope.get('knowledge_cutoff')) if v)


def run_row(item, selected=None):
    identity = item['id']
    state = item.get('state') or {}
    return ('<a class="ar-run" data-run-row="' + e(identity) + '" href="' + e(url(agent='data', run=identity))
            + '"' + (' aria-current="page"' if identity == selected else '') + '><strong>'
            + e(item.get('title') or identity) + '</strong><small>' + e(_scope(item.get('scope') or {}))
            + '</small><small>' + unknown(state.get('execution')) + ' · ' + unknown(state.get('delivery')) + '</small></a>')


def ref_button(ref):
    return ('<button type="button" data-artifact="' + e(ref['id']) + '" data-artifact-run="' + e(ref['run_id'])
            + '">' + e(ref.get('label') or ref['id']) + '</button><small> ' + unknown(ref.get('availability')) + '</small>')


def refs(refs):
    return ''.join('<div class="ar-ref" data-ref-row="' + e(ref['id']) + '">' + ref_button(ref) + '</div>' for ref in refs)


def _step_rows(detail, selected):
    return ''.join('<li class="ar-step" data-step-row="' + e(step['id']) + '"><button type="button" data-step="'
        + e(step['id']) + '"' + (' aria-current="step"' if step['id'] == selected else '') + '><span data-step-label>'
        + e(step.get('ordinal')) + ' · ' + e(step.get('action') or step.get('phase') or step['id'])
        + '</span><small data-step-status>' + unknown(step.get('status')) + ' · ' + unknown(step.get('phase')) + '</small></button></li>' for step in detail.get('steps', []) if step.get('run_id') == detail['id'])


def _model_label(call):
    return (unknown(call.get('provider')) + ' · ' + unknown(call.get('requested_model')) + ' · '
            + bi('推理档位', 'Reasoning effort') + ': ' + unknown(call.get('reasoning_effort')))


def observed_time(value):
    """Only timezone-aware recorded timestamps can become Beijing time."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return None
        return {'beijing': stamp.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S') + ' UTC+08:00',
                'utc': stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}
    except (ValueError, OverflowError):
        return None


def call_timing(call):
    body = '<div class="model-call-timing" data-call-time="' + e(call.get('call_id')) + '"><dl>'
    utc = []
    for key, zh, en in [('started_at', '调用开始（北京时间）', 'Call started (Beijing time)'), ('ended_at', '调用结束（北京时间）', 'Call ended (Beijing time)')]:
        value = observed_time(call.get(key))
        body += '<div><dt>' + bi(zh, en) + '</dt><dd>'
        body += ('<time datetime="' + e(value['utc']) + '" title="' + e(value['utc']) + '">' + e(value['beijing']) + '</time>') if value else unknown(None)
        body += '</dd></div>'
        utc.append('<p>' + bi(zh, en) + ': ' + (e(value['utc']) if value else unknown(None)) + '</p>')
    return body + '</dl><details data-detail-key="utc-' + e(call.get('call_id')) + '"><summary>' + bi('查看 UTC 时间', 'Inspect UTC timestamps') + '</summary>' + ''.join(utc) + '</details></div>'


def configuration_snapshot(call):
    snapshot = call.get('configuration_snapshot')
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 'model-call-config-v1':
        snapshot = {}
    kind = snapshot.get('capture_kind')
    capture = (bi('发送前记录', 'Captured before dispatch') if kind == 'before_dispatch' else
               bi('历史部分记录', 'Partial historical record') if kind == 'historical_partial' else
               bi('未记录配置快照', 'Configuration snapshot not recorded'))
    body = '<details class="model-call-snapshot" data-detail-key="config-' + e(call.get('call_id')) + '" data-call-snapshot="' + e(call.get('call_id')) + '"><summary>' + bi('调用配置快照', 'Call configuration snapshot') + ' · ' + capture + '</summary>'
    body += '<p class="model-call-note">' + bi('这里显示已记录的请求配置。供应商实际生效配置尚未验证；未记录字段不补成默认值。', 'These are recorded request settings. The provider’s effective configuration is unverified; missing fields are not filled with defaults.') + '</p>'
    body += '<p class="model-call-note">' + bi('未发送不代表已知默认值。未发送原因来自记录的文档政策，不是供应商回显；固定采样参数也不保证逐字复现。', 'Not sent does not mean a known default. Omission reasons are recorded documentation policies, not provider echoes; fixed sampling settings do not guarantee identical output.') + '</p>'
    body += '<p class="model-call-hash">SHA256: ' + unknown(snapshot.get('sha256')) + '</p><div class="model-call-table-scroll"><table class="model-call-table"><thead><tr>'
    body += ''.join('<th>' + bi(*label) + '</th>' for label in [('字段', 'Field'), ('值', 'Value'), ('记录状态', 'Record status'), ('来源', 'Source')]) + '</tr></thead><tbody>'
    fields = snapshot.get('fields') if isinstance(snapshot.get('fields'), dict) else {}
    for key in CONFIG_FIELDS:
        field = fields.get(key) if isinstance(fields.get(key), dict) else {}
        state = field.get('status')
        known_value = state in {'explicit', 'recorded'} and 'value' in field
        label = bi('明确指定', 'Explicit') if state == 'explicit' else bi('已有记录', 'Recorded') if state == 'recorded' else bi('未发送', 'Not sent') if state == 'not_sent' else unknown(None)
        value = (field['value'] if isinstance(field['value'], str) else json.dumps(field['value'], ensure_ascii=False, sort_keys=True)) if known_value else None
        policy = CONFIG_POLICIES.get(field.get('source')) if isinstance(field.get('source'), str) else None
        explanation = ('<small>' + bi(policy[1], policy[2]) + '</small>'
                       if state == 'not_sent' and policy and key in policy[0] else '')
        field_label = bi(*CONFIG_LABELS[key]) if key in CONFIG_LABELS else key
        body += '<tr data-config-field="' + key + '"><td>' + field_label + '</td><td>' + (e(value) if known_value else bi('未发送', 'Not sent') if state == 'not_sent' else unknown(None)) + '</td><td>' + label + '</td><td>' + unknown(field.get('source')) + explanation + '</td></tr>'
    body += '</tbody></table></div>'
    fingerprints = snapshot.get('fingerprints')
    if isinstance(fingerprints, dict) and fingerprints:
        body += '<details data-detail-key="fingerprints-' + e(call.get('call_id')) + '"><summary>' + bi('核对指纹', 'Verification fingerprints') + '</summary><pre>' + e(json.dumps(fingerprints, ensure_ascii=False, sort_keys=True, indent=2)) + '</pre></details>'
    return body + '</details>'


def call_configuration_record(call):
    return ('<div class="model-call-record" data-config-call="' + e(call.get('call_id')) + '"><p class="model-call-label">'
            + e(call.get('call_id')) + ' · ' + unknown(call.get('role')) + ' · ' + _model_label(call)
            + '</p>' + call_timing(call) + configuration_snapshot(call) + '</div>')


def call_time_records(calls):
    return ''.join('<div class="model-call-record" data-timed-call="' + e(call.get('call_id')) + '"><p class="model-call-label">'
        + e(call.get('call_id')) + ' · ' + unknown(call.get('requested_model')) + '</p>' + call_timing(call) + '</div>' for call in calls)


def _step_detail(step, calls=()):
    if step is None:
        return '<p class="ar-empty">' + bi('选择一步，查看输入、决定和执行结果。', 'Select a step to inspect its input, decision and result.') + '</p>'
    body = '<h2>' + e(step.get('action') or step.get('phase') or step['id']) + '</h2><p>' + unknown(step.get('status')) + '</p>'
    if step.get('error_code'):
        body += '<p class="ar-error">' + e(step['error_code']) + '</p>'
    body += '<p class="ar-notice">' + bi('耗时（秒）', 'Elapsed seconds') + ': ' + unknown(step.get('elapsed_seconds')) + '</p>'
    matched = [call for call in calls if call['call_id'] in (step.get('call_ids') or [])]
    body += '<div class="ar-step-models">' + ''.join(call_configuration_record(call)
        + '<p>Request ID: ' + unknown(call.get('request_id')) + '</p>' for call in matched) + '</div>'
    if not matched:
        body += '<p class="ar-notice">' + bi('这一步没有已记录的模型调用。', 'No model call is recorded for this step.') + '</p>'
    body += refs(step.get('files') or [])
    for identity in step.get('call_ids') or []:
        body += '<p><button type="button" data-call="' + e(identity) + '">' + bi('关联模型调用', 'Related model call') + ' · ' + e(identity) + '</button></p>'
    for identity in step.get('child_run_ids') or []:
        body += '<p><button type="button" data-child-run="' + e(identity) + '">' + bi('打开子运行', 'Open child run') + ' · ' + e(identity) + '</button></p>'
    if not step.get('files'):
        body += '<p class="ar-notice">' + bi('该步尚无可查看文件。', 'No files are available for this step.') + '</p>'
    return body


def timed_steps(detail):
    """Only observed closed intervals can establish a time axis."""
    rows = []
    if detail.get('live'):
        for step in detail.get('steps', []):
            try:
                start = datetime.fromisoformat(step['started_at'].replace('Z', '+00:00'))
                end = datetime.fromisoformat(step['ended_at'].replace('Z', '+00:00'))
                if start.tzinfo is not None and end.tzinfo is not None and end >= start:
                    rows.append((step, start.timestamp(), end.timestamp()))
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
    return rows


def _timeline(detail):
    rows = timed_steps(detail)
    origin = min((row[1] for row in rows), default=0)
    span = max((row[2] for row in rows), default=origin) - origin or 1
    body = '<div class="ar-controls ar-process-mode"><div><button type="button" data-process-mode="list" aria-pressed="true">' + bi('步骤列表', 'Step list') + '</button> <button type="button" data-process-mode="timing" aria-pressed="false"' + (' disabled' if not rows else '') + '>' + bi('有计时步骤', 'Timed steps') + '</button></div></div>'
    body += '<p id="ar-timing-note" class="ar-notice">' + bi(f'{len(rows)} / {len(detail.get("steps", []))} 步有完整起止时间。缺少时间的步骤保留在列表；区间不相加为总耗时。', f'{len(rows)} / {len(detail.get("steps", []))} steps have complete start and end times. Steps without timing stay in the list; intervals are not added into a total.') + '</p><div id="ar-timing" hidden>'
    for step, start, end in rows:
        label = str(step.get('ordinal')) + ' · ' + str(step.get('action') or step.get('phase') or step['id'])
        body += '<div class="ar-timing-row" data-timing-row="' + e(step['id']) + '"><button type="button" data-step="' + e(step['id']) + '">' + e(label) + '</button><div class="ar-interval"><span style="left:' + str((start-origin)/span*100) + '%;width:' + str((end-start)/span*100) + '%"></span></div><small>' + e(step['run_id']) + ' · ' + e(step['started_at']) + ' → ' + e(step['ended_at']) + ' · ' + unknown(step.get('elapsed_seconds')) + ' s</small></div>'
    return body + '</div>'


def _artifacts(detail):
    head = ''.join('<th>' + bi(*label) + '</th>' for label in [('产物', 'Artifact'), ('类型', 'Type'), ('可用性', 'Availability'), ('字节', 'Bytes')])
    rows = ''.join('<tr data-artifact-row="' + e(ref['id']) + '"><td>' + ref_button(ref) + '</td><td>' + e(ref.get('kind'))
                   + '</td><td>' + unknown(ref.get('availability')) + '</td><td class="ar-number">' + number(ref.get('size_bytes')) + '</td></tr>'
                   for ref in detail.get('artifacts', []))
    return '<div class="ar-table-scroll"><table class="ar-table"><thead><tr>' + head + '</tr></thead><tbody id="ar-artifact-rows">' + rows + '</tbody></table></div>'


def _usage(detail):
    usage = detail.get('usage') or {}
    labels = [('requests', '调用尝试', 'Call attempts'), ('input_tokens', '已知输入 Token', 'Known input tokens'),
              ('output_tokens', '已知输出 Token', 'Known output tokens'), ('cached_tokens', '已知缓存 Token', 'Known cached tokens'),
              ('reasoning_tokens', '已知推理 Token', 'Known reasoning tokens'), ('unknown_usage_calls', '用量未知调用', 'Calls with unknown usage'),
              ('known_estimated_usd', '已知估算 USD', 'Known estimate USD'), ('unknown_cost_requests', '费用未知调用', 'Calls with unknown cost'),
              ('actual_billed_usd', '实际账单 USD', 'Actual billed USD')]
    own = usage.get('own') or {}
    body = '<div class="ar-table-scroll"><table class="ar-table" id="ar-usage-summary"><thead><tr><th>' + bi('计量', 'Measure') + '</th><th class="ar-number">' + bi('本运行', 'This run') + '</th><th class="ar-number">' + bi('含子任务', 'Including child runs') + '</th></tr></thead><tbody>'
    body += ''.join('<tr><td>' + bi(zh, en) + '</td><td class="ar-number" data-own-usage="' + key + '">' + number(own.get(key)) + '</td><td class="ar-number" data-usage="' + key + '">' + number(usage.get(key)) + '</td></tr>' for key, zh, en in labels) + '</tbody></table></div>'
    maximum = max([row.get('input_tokens', 0) or 0 for row in usage.get('roles', [])] + [1])
    body += '<div class="ar-tokens" id="ar-token-bars">'
    for row in usage.get('roles', []):
        amount = row.get('input_tokens')
        pct = 0 if amount is None else min(100, max(0, amount / maximum * 100))
        body += '<div class="ar-token-row"><span>' + e(row.get('role')) + '</span><div class="ar-token-bar"><span style="width:' + str(pct) + '%"></span></div><output>' + number(amount) + '</output></div>'
    body += '</div><p class="ar-notice">' + bi('条形表示各角色已知输入 Token。缓存和推理是子项，不重复相加；历史估算不是账单。', 'Bars show known input tokens by role. Cache and reasoning are subsets, not additional tokens. Historical estimates are not bills.') + '</p>'
    labels = [('调用 / 角色', 'Call / role'), ('模型', 'Model'), ('状态', 'Status'), ('输入', 'Input'), ('输出', 'Output'), ('缓存', 'Cached'), ('推理', 'Reasoning'), ('秒', 'Seconds'), ('估算 USD', 'Estimate USD')]
    body += '<div class="ar-table-scroll"><table class="ar-table"><thead><tr>' + ''.join('<th>' + bi(*label) + '</th>' for label in labels) + '</tr></thead><tbody id="ar-call-rows">'
    for call in detail.get('calls', []):
        identity = e(call['call_id'])
        trigger = '<button type="button" data-call="' + identity + '">' + identity + '</button>'
        body += '<tr data-call-row="' + identity + '"><td>' + trigger + '<small>' + e(call.get('role')) + '</small></td><td>' + e(call.get('requested_model')) + '</td><td>' + unknown(call.get('status')) + '</td>'
        body += ''.join('<td class="ar-number">' + number(call.get(key)) + '</td>' for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens', 'elapsed_seconds', 'estimated_usd')) + '</tr>'
    return body + '</tbody></table></div><div id="ar-call-detail"></div>'


def _content(detail, args):
    if detail is None:
        return '<p class="ar-empty">' + bi('选择一次运行，查看它的过程和产物。', 'Select a run to inspect its process and artifacts.') + '</p>'
    state = detail.get('state') or {}
    selected_step = next((s for s in detail.get('steps', []) if s['id'] == args.get('step')), None)
    if args.get('step') and selected_step is None:
        raise ValueError('Step does not belong to the selected run')
    if args.get('artifact') and not any(ref['id'] == args['artifact'] for ref in detail.get('artifacts', []) + detail.get('inputs', []) + detail.get('configs', [])):
        raise ValueError('Artifact does not belong to the selected run')
    result_url = '/agent-results?' + urlencode({'agent': detail.get('agent', 'data'), 'run': detail['id']})
    body = '<div class="ar-heading"><h1>' + e(detail.get('title') or detail['id']) + '</h1><a class="ar-link" href="' + e(result_url) + '">' + bi('查看运行结果与评分', 'View result & scores') + '</a></div><div class="ar-meta"><a href="' + e(result_url) + '">Trace ID: ' + e(detail['id']) + '</a><span>' + unknown(detail.get('origin')) + '</span></div>'
    models = {}
    for call in detail.get('calls', []):
        models.setdefault((call.get('role'), call.get('provider'), call.get('requested_model'), call.get('reasoning_effort')), call)
    body += '<div id="ar-model-summary">' + ''.join('<p>' + unknown(call.get('role')) + ' · ' + _model_label(call) + '</p>' for call in models.values()) + '</div>'
    body += '<details class="ar-call-times" open><summary>' + bi('已记录的模型调用时间', 'Recorded model call times') + '</summary><div id="ar-call-times">' + call_time_records(detail.get('calls') or []) + '</div></details>'
    body += '<details id="ar-run-relations"' + (' hidden' if len(detail.get('run_tree', [])) < 2 else '') + '><summary>' + bi('父子运行关系', 'Run relationships') + '</summary><ul id="ar-run-tree-items">'
    for item in detail.get('run_tree', []):
        body += '<li data-tree-run="' + e(item['id']) + '"><button type="button" data-child-run="' + e(item['id']) + '">' + e(item['id']) + '</button><span> · ' + e(item.get('role') or item.get('kind')) + ' · ' + unknown(item.get('status')) + '</span></li>'
    body += '</ul></details><p class="ar-scope" id="ar-scope">' + e(_scope(detail.get('scope') or {})) + '</p><dl class="ar-statuses">'
    for key, zh, en in [('execution', '执行', 'Execution'), ('delivery', '交付', 'Delivery'), ('quality', '内容质量', 'Content quality'), ('adoption', '采纳', 'Adoption')]:
        body += '<div><dt>' + bi(zh, en) + '</dt><dd data-state="' + key + '">' + unknown(state.get(key)) + '</dd></div>'
    body += '</dl><p class="ar-notice">' + bi('停止原因', 'Stop reason') + ': <span data-state="stop_reason">' + unknown(state.get('stop_reason')) + '</span></p>'
    body += '<nav class="ar-tabs" aria-label="Run views">' + ''.join('<a data-tab="' + key + '" href="' + e(url(agent='data', run=detail['id'], tab=key)) + '"' + (' aria-current="page"' if key == args.get('tab', 'process') else '') + '>' + bi(*label) + '</a>' for key, label in TABS.items()) + '</nav>'
    body += '<section data-panel="process"' + (' hidden' if args.get('tab', 'process') != 'process' else '') + '>' + _timeline(detail) + '<div id="ar-child-detail" hidden></div><div class="ar-process"><ol class="ar-steps" id="ar-steps">' + _step_rows(detail, args.get('step')) + '</ol><div class="ar-inspector" id="ar-step-detail">' + _step_detail(selected_step, detail.get('calls', [])) + '</div></div></section>'
    body += '<section data-panel="artifacts"' + (' hidden' if args.get('tab', 'process') != 'artifacts' else '') + '>' + _artifacts(detail) + '</section>'
    body += '<section data-panel="usage"' + (' hidden' if args.get('tab', 'process') != 'usage' else '') + '>' + _usage(detail) + '</section>'
    body += '<section data-panel="config"' + (' hidden' if args.get('tab', 'process') != 'config' else '') + '><h2>' + bi('逐次调用配置', 'Per-call configuration') + '</h2><div id="ar-call-snapshots">' + ''.join(call_configuration_record(call) for call in detail.get('calls') or []) + '</div><h2>' + bi('任务与范围', 'Task & scope') + '</h2><pre id="ar-scope-config">' + e(json.dumps(detail.get('scope') or {}, ensure_ascii=False, indent=2)) + '</pre><h2>' + bi('输入', 'Inputs') + '</h2><div id="ar-inputs">' + refs(detail.get('inputs') or []) + '</div><h2>' + bi('安全配置投影', 'Safe configuration projection') + '</h2><div id="ar-configs">' + refs(detail.get('configs') or []) + '</div></section>'
    body += '<section id="ar-artifact-detail" hidden><div class="ar-controls"><h2 id="ar-artifact-title"></h2><button id="ar-artifact-close" type="button">' + bi('关闭产物', 'Close artifact') + '</button></div><p id="ar-artifact-status" class="ar-notice"></p><div id="ar-artifact-children"></div><pre id="ar-artifact-content"></pre><button id="ar-artifact-more" type="button" hidden>' + bi('继续读取', 'Read more') + '</button></section>'
    body += '<div id="ar-diagnostics">' + ''.join('<p class="ar-notice ar-error">' + e(item) + '</p>' for item in detail.get('diagnostics', [])) + '</div>'
    for link in detail.get('links') or []:
        href = safe_link(link.get('href'))
        if href:
            body += '<p><a class="ar-link" href="' + e(href) + '">' + e(link.get('label')) + '</a></p>'
    return body


@workbench_page('agent-runs')
def render_agent_runs(root, selection, *, observation_root=None, output_roots=()):
    args = parse_selection(selection)
    agent = args.get('agent', 'data')
    options = {'observation_root': observation_root, 'output_roots': output_roots}
    listing = list_runs(root, **options) if agent == 'data' else []
    detail = load_run(root, args['run'], **options) if args.get('run') else None
    if detail is not None and detail['id'] != args['run']:
        raise ValueError('Loaded run identity mismatch')
    config = {'selection': args, 'detail': detail, 'listing': listing[:50], 'listing_total': len(listing), 'api': '/api/agent-runs'}
    payload = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    agents = '<h2>Agent</h2>' + ''.join('<a class="ar-agent" href="' + e(url(agent=key)) + '"' + (' aria-current="page"' if key == agent else '') + '><strong>' + label + '</strong><small>' + bi(zh, en) + '</small></a>' for key, (label, zh, en) in AGENTS.items())
    directory = '<h2>' + bi('运行', 'Runs') + '</h2><label class="ar-directory-search">' + bi('查找已列出的运行', 'Find listed runs') + '<input id="ar-search" type="search"></label><div id="ar-run-list">' + ''.join(run_row(item, args.get('run')) for item in listing[:50]) + '</div><p id="ar-list-count" class="ar-notice">' + bi(f'已列出 {min(50, len(listing))} / 共 {len(listing)}', f'{min(50, len(listing))} listed / {len(listing)} total') + '</p><button id="ar-list-more" type="button"' + (' hidden' if len(listing) <= 50 else '') + '>' + bi('加载更多运行', 'Load more runs') + '</button><p id="ar-list-empty" class="ar-empty"' + (' hidden' if listing else '') + '>' + bi('没有可显示的运行。', 'No runs to display.') + '</p>'
    content = _content(detail, args) if agent == 'data' else '<h1>' + AGENTS[agent][0] + '</h1><p class="ar-empty">' + bi(AGENTS[agent][1], AGENTS[agent][2]) + '</p>'
    toolbar = '<div class="ar-toolbar"><span>' + bi('Agent 工程观察', 'Agent engineering') + '</span><div class="ar-controls"><span id="ar-connection" role="status">' + (unknown((detail.get('state') or {}).get('connection')) if detail else '') + '</span><button id="ar-refresh" type="button">' + bi('刷新', 'Refresh') + '</button><button id="ar-language" type="button">中文 / EN</button></div></div>'
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent 运行 · Uteki</title><style>' + asset_text('agent_runs.css') + '</style></head><body><div class="ar-workspace"><aside class="ar-agents">' + agents + '</aside><aside class="ar-directory">' + directory + '</aside><main class="ar-main" id="ar-main">' + toolbar + '<p id="ar-message" role="status" class="ar-notice" hidden></p>' + content + '</main></div><script type="application/json" id="ar-config">' + payload + '</script><script>' + asset_text('agent_runs.js') + '</script></body></html>')
