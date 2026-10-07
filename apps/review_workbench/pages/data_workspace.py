"""Company-first inspection of existing, validated Data Agent artifacts."""
from collections import defaultdict
from hashlib import sha256
import json
from urllib.parse import urlencode, urlparse

from apps.review_workbench.assets import asset_text
from apps.review_workbench.components.site_navigation import bi, e
from apps.review_workbench.components.visual_system import workbench_page
from apps.review_workbench.data.evaluation_artifacts import load_catalog, load_dataset
from apps.review_workbench.data.direct_extraction_views import load_dataset_run
from apps.review_workbench.data.workspace_state import read_state, material_tasks
from apps.review_workbench.data.workspace_financials import build_financial_table, build_dataset_table
from apps.review_workbench.pages.dataset_view import render_block, field_table
from apps.review_workbench.pages.direct_extractions import processing_record

TABS = {'original': ('原件', 'Original'), 'financials': ('财务数据', 'Financial data'),
        'blocks': ('章节与表格', 'Sections & tables'), 'brief': ('材料精编', 'Filing brief'),
        'process': ('处理记录', 'Processing history')}
PARAMS = {'company', 'dataset', 'source', 'tab', 'run', 'fact', 'block', 'base', 'q', 'kind', 'offset'}


def url(**values):
    values = {k: v for k, v in values.items() if v is not None and v != ''}
    return '/data-workspace' + ('?' + urlencode(values) if values else '')


def disclosure(label, body, *, opened=False, css_class=None):
    return '<details' + (' class="' + e(css_class) + '"' if css_class else '') + (' open' if opened else '') + '><summary>' + bi(*label) + '</summary>' + body + '</details>'


def empty(zh, en):
    return '<p class="dw-empty">' + bi(zh, en) + '</p>'


def json_detail(label, value):
    return disclosure(label, '<pre>' + e(json.dumps(value, ensure_ascii=False, indent=2, default=str)) + '</pre>')


def parse_selection(selection):
    if set(selection) - PARAMS:
        raise ValueError('Unknown workspace selection')
    selection = {k: v for k, v in selection.items() if not (k == 'q' and v == [''])}
    for key, value in selection.items():
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str) or not value[0].strip():
            raise ValueError('Explicit single nonblank selection required: ' + key)
    args = {k: v[0] for k, v in selection.items()}
    if args.get('tab', 'original') not in TABS or args.get('base', '0') not in {'0', '1'}:
        raise ValueError('Unsupported workspace view')
    if args.get('kind', 'all') not in {'all', 'table', 'paragraph', 'heading', 'image'}:
        raise ValueError('Unsupported block filter')
    if len(args.get('q', '')) > 200:
        raise ValueError('Search is too long')
    if not args.get('dataset') and set(args) - {'company'}:
        raise ValueError('Select an explicit dataset first')
    if not args.get('source') and any(k in args for k in ('run', 'fact', 'block', 'base', 'q', 'kind', 'offset')):
        raise ValueError('Select an explicit material first')
    if args.get('fact') and not (args.get('run') or args.get('base') == '1'):
        raise ValueError('A fact requires its run or explicit base dataset')
    if args.get('base') == '1' and args.get('run'):
        raise ValueError('Base data and extraction versions are separate views')
    try:
        offset = int(args.get('offset', '0'))
    except ValueError:
        raise ValueError('Invalid block page') from None
    if offset < 0 or offset % 40:
        raise ValueError('Invalid block page')
    args['offset'] = offset
    return args


@workbench_page('data-detail')
def shell(content, sidebar, config):
    payload = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>数据产物明细 · Uteki</title><style>' + asset_text('data_workspace.css') + '</style></head>'
            '<body><header class="dw-header"><a href="/agent-results">' + bi('返回运行结果', 'Back to results') + '</a>'
            '<span>' + bi('数据产物明细', 'Data artifact details') + '</span><nav>'
            '<button id="dw-language" type="button">中文 / EN</button></nav></header>'
            '<div class="dw-layout"><aside class="dw-companies" aria-label="Companies">' + sidebar + '</aside>'
            '<main id="dw-main">' + content + '</main></div>'
            '<div id="dw-message" role="status" aria-live="polite" hidden></div>'
            '<script type="application/json" id="dw-config">' + payload + '</script>'
            '<script>' + asset_text('data_workspace.js') + '</script></body></html>')


def company_list(catalog, company_id, dataset_id):
    grouped = defaultdict(list)
    for entry in catalog['datasets']:
        grouped[entry['company_id']].append(entry)
    body = '<h2>' + bi('公司', 'Companies') + '</h2><input type="search" id="dw-company-search" aria-label="搜索公司 / Search companies" placeholder="搜索 / Search">'
    for cid, entries in grouped.items():
        item = entries[0]
        # Only a unique registered dataset can be represented by a direct company link.
        target = url(company=cid, dataset=entries[0]['id']) if len(entries) == 1 else url(company=cid)
        body += '<div class="dw-company" data-company-search="' + e(item['company_name'] + ' ' + item['symbol']) + '"><a href="' + e(target) + '"' + (' aria-current="page"' if company_id == cid else '') + '><strong>' + e(item['symbol']) + '</strong><span>' + e(item['company_name']) + '</span></a>'
        if len(entries) > 1 and company_id == cid:
            for entry in entries:
                body += '<a class="dw-dataset" href="' + e(url(company=cid, dataset=entry['id'])) + '"' + (' aria-current="page"' if dataset_id == entry['id'] else '') + '>' + e(entry['id']) + '</a>'
        body += '</div>'
    return body + '<p id="dw-company-empty" hidden>' + bi('没有匹配公司', 'No matching company') + '</p>'


def source_title(source):
    return e(source.get('form') or '—') + ' · ' + e(source.get('period_end') or '报告期未标注 / Period unknown')


def material_directory(data, source_id):
    body = '<details id="dw-material-directory" open><summary>' + bi('公司材料', 'Company materials') + '<span class="dw-count">' + str(len(data['sources'])) + '</span></summary>'
    body += '<div class="dw-filters"><label>' + bi('搜索材料', 'Find material') + '<input type="search" id="dw-material-search"></label><label>' + bi('年份', 'Year') + '<select id="dw-year"><option value="">全部 / All</option>'
    years = sorted({s.get('period_end', '')[:4] for s in data['sources'] if s.get('period_end')}, reverse=True)
    body += ''.join('<option>' + e(y) + '</option>' for y in years) + '</select></label><label>' + bi('类型', 'Type') + '<select id="dw-form"><option value="">全部 / All</option>'
    body += ''.join('<option>' + e(t) + '</option>' for t in sorted({s.get('form', '') for s in data['sources']})) + '</select></label><label>' + bi('分组', 'Group by') + '<select id="dw-group"><option value="year">年份 / Year</option><option value="form">文件类型 / Type</option></select></label></div>'
    body += '<div id="dw-materials" data-scroll-key="materials">'
    for source in sorted(data['sources'], key=lambda s: (s.get('period_end') or '', s['source_snapshot_id']), reverse=True):
        sid = source['source_snapshot_id']
        body += '<a class="dw-material" data-year="' + e((source.get('period_end') or '')[:4]) + '" data-form="' + e(source.get('form')) + '" href="' + e(url(dataset=data['id'], source=sid, tab='original')) + '"' + (' aria-current="page"' if source_id == sid else '') + '><strong>' + source_title(source) + '</strong><span>' + bi('公开日期 ', 'Published ') + e(source.get('available_at') or '—') + '</span><small>' + e(source.get('locale') or source.get('language') or '') + '</small></a>'
    body += '</div><p id="dw-material-empty" hidden>' + bi('没有符合筛选条件的材料。', 'No materials match these filters.') + '</p></details>'
    return body


def version_controls(tasks, args):
    body = '<div class="dw-version-picker"><p class="dw-note">' + bi('选择每项任务用于本页展示的版本。这里只整理查看范围，不改变数据采纳状态。', 'Choose which version of each task to display. This changes the view, not adoption.') + '</p>'
    for task in tasks['tasks']:
        body += '<section class="dw-task"><h3>' + bi(task['label_zh'], task['label_en']) + '</h3><label>' + bi('展示版本', 'Displayed version') + '<select data-task-choice="' + e(task['task_id']) + '"><option value="">未选择 / Not selected</option>'
        visible = [v for v in task['versions'] if not v['archived']]
        for i, version in enumerate(visible, 1):
            label = version.get('label_zh', f'版本 {i}') + ' / ' + version.get('label_en', f'Version {i}')
            body += '<option value="' + e(version['run_id']) + '"' + (' selected' if version['selected'] else '') + (' disabled' if not version.get('selectable', True) else '') + '>' + e(label) + '</option>'
        body += '</select></label>'
        history = ''
        for number, version in enumerate(visible, 1):
            history += '<div class="dw-version-row"><a href="' + e(url(dataset=args['dataset'], source=args['source'], tab='process', run=version['run_id'])) + '">' + bi(version.get('label_zh', f'版本 {number}'), version.get('label_en', f'Version {number}')) + '</a>'
            if version['selected']:
                history += '<span class="dw-status">' + bi('当前展示', 'Displayed') + '</span>'
            elif version.get('available', True):
                history += '<button data-state-action="archive" data-task="' + e(task['task_id']) + '" data-run="' + e(version['run_id']) + '">' + bi('归档', 'Archive') + '</button>'
            if not version.get('available', True):
                history += '<span class="dw-conflict">' + bi('来源校验未通过', 'Source validation failed') + '</span>'
            elif version.get('status') in {'failed', 'error'}:
                history += '<span class="dw-conflict">' + bi('提取失败', 'Extraction failed') + '</span>'
            history += '</div>'
        body += disclosure(('历史版本', 'Version history'), history)
        archived = [v for v in task['versions'] if v['archived']]
        if archived:
            body += disclosure(('已归档，可恢复', 'Archived · recoverable'), ''.join('<div class="dw-version-row"><a href="' + e(url(dataset=args['dataset'], source=args['source'], tab='process', run=v['run_id'])) + '">' + bi(v.get('label_zh', '已保存版本'), v.get('label_en', 'Saved version')) + '</a><button data-state-action="restore" data-task="' + e(task['task_id']) + '" data-run="' + e(v['run_id']) + '">' + bi('恢复', 'Restore') + '</button></div>' for v in archived))
        body += '</section>'
    if tasks.get('unassigned_runs'):
        body += empty('以下运行尚未登记任务分组，可单独查看。', 'These runs have no registered task group and can be inspected individually.')
        for run in tasks['unassigned_runs']:
            rid = run.get('run_id') or run.get('id')
            body += '<p><a href="' + e(url(dataset=args['dataset'], source=args['source'], tab='process', run=rid)) + '">' + e(rid) + '</a></p>'
    if tasks.get('gaps'):
        body += json_detail(('版本关联存在问题', 'Version binding issues'), tasks['gaps'])
    if not tasks['tasks'] and not tasks.get('unassigned_runs'):
        body += empty('这份材料尚无已登记的模型提取运行。', 'No model extraction runs are registered for this material.')
    return body + '</div>'


def locate_button(block_id, label, *, quote=None):
    return '<button class="dw-locate" data-locate="' + e(block_id) + '"' + (' data-quote="' + e(quote) + '"' if quote else '') + '>' + bi(*label) + '</button>'


def financial_view(matrix, args, version_labels=None):
    body = '<div class="dw-table-toolbar"><label>' + bi('搜索指标或口径', 'Search metrics or scope') + '<input id="dw-financial-search" type="search"></label><label>' + bi('结果', 'Results') + '<select id="dw-financial-filter"><option value="all">全部 / All</option><option value="conflict">存在冲突 / Conflicts</option><option value="review">待核验 / Needs review</option></select></label></div>'
    if not matrix['rows']:
        body += empty('当前展示范围内没有财务记录。请选择提取版本，或查看明确登记的基础数据。', 'No financial records in this view. Select extraction versions or inspect the registered base data.')
    else:
        body += '<div class="dw-table-scroll dw-financial-grid" data-scroll-key="financial-table"><table class="dw-financial-table"><thead><tr><th>' + bi('指标与口径', 'Metric & scope') + '</th>'
        for period in matrix['periods']:
            body += '<th>' + e(period['label']).replace('\n', '<br>') + '</th>'
        body += '</tr></thead><tbody>'
        detail_items = []
        for row in matrix['rows']:
            scope = row['scope']
            has_conflict = any(c.get('conflict') for c in row['cells'].values())
            body += '<tr data-financial-row data-conflict="' + str(has_conflict).lower() + '"><th>' + e(row['label']) + '<small>' + e(' / '.join(str(scope.get(k)) for k in ('unit', 'currency', 'accounting_basis') if scope.get(k))) + '</small>' + disclosure(('口径', 'Scope'), field_table(scope)) + '</th>'
            for period in matrix['periods']:
                cell = row['cells'].get(period['id'], {'candidates': []})
                body += '<td>'
                if not cell['candidates']:
                    body += '<span class="dw-muted">' + bi('未提取', 'Not extracted') + '</span>'
                if cell.get('conflict'):
                    body += '<span class="dw-conflict">' + bi('候选冲突', 'Conflicting candidates') + '</span>'
                elif len(cell['candidates']) > 1:
                    body += '<span class="dw-muted">' + bi('多个候选', 'Multiple candidates') + '</span>'
                for candidate in cell['candidates']:
                    key = sha256(json.dumps([candidate.get('run_id'), candidate['record_id']], ensure_ascii=False).encode()).hexdigest()[:20]
                    body += '<button class="dw-value" aria-pressed="false" data-fact-target="' + key + '" data-run="' + e(candidate.get('run_id') or '') + '" data-fact="' + e(candidate['record_id']) + '" data-fact-label="' + e(row['label']) + '" data-fact-period="' + e(period['label']) + '">' + e(candidate['display_value']) + '</button><small class="dw-review" data-review-status="' + e(candidate.get('review_status')) + '">' + review_label(candidate.get('review_status')) + '</small>'
                    detail_items.append((key, candidate, row['label'], period['label']))
                body += '</td>'
            body += '</tr>'
        body += '</tbody></table></div><p id="dw-financial-empty" hidden>' + bi('没有符合筛选条件的财务记录。', 'No financial records match these filters.') + '</p>'
        body += '<section id="dw-fact-inspector" class="dw-inspector" aria-label="数值核对 / Fact inspection"><header class="dw-inspector-head"><strong>' + bi('当前核对', 'Current inspection') + '</strong><div><button id="dw-return-fact" type="button" hidden>' + bi('回到数值', 'Return to value') + '</button><button id="dw-close-inspector" type="button" hidden>' + bi('清除选择', 'Clear selection') + '</button></div></header><p id="dw-inspector-empty">' + bi('点击一个数值，在此核对期间、口径和证据。表格会保持原位。', 'Select a value to inspect its period, scope and evidence here. The table stays in place.') + '</p><div id="dw-fact-details" class="dw-inspector-body" data-scroll-key="fact-inspector">'
        seen = set()
        for key, candidate, label, period_label in detail_items:
            if key in seen:
                continue
            seen.add(key)
            body += '<section class="dw-fact-detail" id="fact-' + key + '" hidden tabindex="-1"><h3>' + e(label) + ' · ' + e(candidate['display_value']) + '</h3><p>' + e(period_label) + '</p><p>' + review_label(candidate.get('review_status')) + ' · ' + bi('候选展示不代表采纳', 'Candidate display does not mean adoption') + '</p>'
            version_label = (version_labels or {}).get(candidate.get('run_id'))
            if version_label:
                body += '<p class="dw-fact-version">' + bi('提取版本：', 'Extraction version: ') + bi(*version_label) + '</p>'
            for role, refs in ((('数值证据', 'Value evidence'), candidate.get('evidence_refs', [])), (('口径证据', 'Scope evidence'), candidate.get('qualifier_refs', []))):
                for ref in refs:
                    body += '<div class="dw-citation"><strong>' + bi(*role) + '</strong><blockquote>' + e(ref.get('quote', '')) + '</blockquote>'
                    if ref.get('block_id'):
                        body += locate_button(ref['block_id'], ('定位原文', 'Locate in original'), quote=ref.get('quote'))
                    body += '</div>'
            if not candidate.get('evidence_refs'):
                body += empty('这条记录缺少可定位证据。', 'No locatable evidence is available for this record.')
            if candidate.get('review'):
                body += json_detail(('已有核验意见', 'Saved review'), candidate['review'])
            if candidate.get('run_id'):
                body += '<p><a href="' + e(url(dataset=args['dataset'], source=args['source'], tab='process', run=candidate['run_id'])) + '">' + bi('查看这次处理的输入、方法与结果', 'Inspect this extraction’s inputs, method and output') + '</a></p>'
            body += json_detail(('来源、提取版本与完整字段', 'Source, extraction version & fields'), candidate)
            body += '</section>'
        body += '</div></section>'
    if matrix.get('gaps'):
        body += json_detail(('财务数据缺口', 'Financial data gaps'), matrix['gaps'])
    return body


def review_label(status):
    labels = {'value_scope_matched': ('金额与期间核对匹配', 'Value and period matched'),
              'supported': ('证据支持', 'Supported'), 'not_reviewed': ('未登记逐条核验', 'No per-fact review'),
              'unreviewed': ('未登记逐条核验', 'No per-fact review'), 'needs_evidence': ('需补证据', 'Needs evidence')}
    return bi(*labels.get(status, (status or '未登记逐条核验', status or 'No per-fact review')))


def blocks_view(data, source, args):
    sid = source['source_snapshot_id']
    blocks = data['blocks'][sid]
    by_id = {b['block_id']: b for b in blocks}
    body = disclosure(('章节目录', 'Contents'), '<ul class="dw-outline">' + ''.join(
        '<li>' + ('<a href="' + e(url(dataset=data['id'], source=sid, tab='blocks', block=n['start_block_id'])) + '">' + e(n.get('title')) + '</a>' if n.get('start_block_id') in by_id else e(n.get('title'))) + '</li>'
        for n in data['indexes'][sid].get('nodes', []) if n.get('kind') != 'document') + '</ul>', opened=not args.get('block'))
    body += '<form class="dw-filters" action="/data-workspace">'
    for k, v in {'dataset': data['id'], 'source': sid, 'tab': 'blocks'}.items():
        body += '<input type="hidden" name="' + k + '" value="' + e(v) + '">'
    body += '<label>' + bi('搜索原文', 'Search source text') + '<input type="search" name="q" value="' + e(args.get('q')) + '"></label><label>' + bi('内容类型', 'Content type') + '<select name="kind">'
    for key, label in [('all', '全部 / All'), ('table', '表格 / Tables'), ('paragraph', '段落 / Passages'), ('heading', '标题 / Headings'), ('image', '图像引用 / Image references')]:
        body += '<option value="' + key + '"' + (' selected' if args.get('kind', 'all') == key else '') + '>' + label + '</option>'
    body += '</select></label><button>' + bi('搜索', 'Search') + '</button></form>'
    if args.get('block'):
        block = by_id[args['block']]
        body += '<section class="dw-selected-block"><h3>' + bi('当前原文内容', 'Selected source content') + '</h3>' + locate_button(block['block_id'], ('在完整原件中定位', 'Locate in full original')) + render_block(block) + json_detail(('来源定位信息', 'Source locator'), {k: v for k, v in block.items() if k not in {'table', 'text'}}) + '</section>'
    matched = [b for b in blocks if (args.get('kind', 'all') == 'all' or b['type'] == args['kind']) and args.get('q', '').casefold() in b['text'].casefold()]
    body += '<p class="dw-muted">' + bi(f'{len(matched)} 项原文内容', f'{len(matched)} source items') + '</p>'
    start = args['offset']
    for block in matched[start:start + 40]:
        body += '<article class="dw-block"><div class="dw-block-heading"><strong>' + bi('表格' if block['type'] == 'table' else '原文段落', 'Table' if block['type'] == 'table' else 'Source passage') + '</strong>' + locate_button(block['block_id'], ('定位原件', 'Locate source')) + '</div>'
        body += disclosure((block['text'][:130], block['text'][:130]), render_block(block)) + '</article>'
    if not matched:
        body += empty('没有匹配内容，试试其他关键词或类型。', 'No matching content. Try another keyword or type.')
    body += '<nav class="dw-pagination">'
    for target, label in ((start - 40, ('上一页', 'Previous')), (start + 40, ('下一页', 'Next'))):
        if 0 <= target < len(matched):
            body += '<a href="' + e(url(dataset=data['id'], source=sid, tab='blocks', q=args.get('q'), kind=args.get('kind'), offset=target)) + '">' + bi(*label) + '</a>'
    return body + '</nav>'


def storage_view(data, source):
    folder = data.get('storage', {}).get('dataset_path')
    join = lambda path: folder + '/' + path if folder and path else path
    mapping = {'原始文件 / Original': join(source.get('raw_file')),
               '章节索引 / Contents index': join(source.get('index_folder', '') + '/index.json'),
               '段落与表格 / Blocks': join(source.get('index_folder', '') + '/blocks.jsonl'),
               '基础财务数据 / Base records': data.get('storage', {}).get('records_path'),
               '基础数据库 / Base database': data.get('storage', {}).get('database_path')}
    return disclosure(('材料身份与保存位置', 'Material identity & storage'), '<p>' + bi('文件位置相对于项目根目录。提取版本有各自独立的数据库。', 'Paths are relative to the project root. Extraction versions have separate databases.') + '</p>' + field_table(mapping) + field_table(source))


def render_data_workspace(root, selection):
    args = parse_selection(selection)
    catalog = load_catalog(root)
    selected = next((d for d in catalog['datasets'] if d['id'] == args.get('dataset')), None)
    if args.get('dataset') and selected is None:
        raise ValueError('Dataset is not registered')
    company_id = args.get('company') or (selected['company_id'] if selected else None)
    if company_id and not any(d['company_id'] == company_id for d in catalog['datasets']):
        raise ValueError('Company is not registered')
    if selected and company_id != selected['company_id']:
        raise ValueError('Company and dataset do not match')
    sidebar = company_list(catalog, company_id, args.get('dataset'))
    config = {'selection': args, 'revision': 0}
    if not selected:
        return shell('<section class="dw-welcome"><h1>' + bi('从一家公司开始', 'Start with a company') + '</h1>' + empty('在左侧选择公司和数据包，查看材料及其加工结果。', 'Choose a company and dataset to inspect its materials and processed outputs.') + '</section>', sidebar, config)
    data = load_dataset(root, selected['id'])
    source = next((s for s in data['sources'] if s['source_snapshot_id'] == args.get('source')), None)
    if args.get('source') and source is None:
        raise ValueError('Material is outside the selected dataset')
    content = '<div class="dw-company-heading"><h1>' + e(data['company']['name']) + '</h1><span>' + e(data['company']['symbol']) + '</span></div>' + material_directory(data, args.get('source'))
    if not source:
        return shell(content + empty('选择一份材料，查看原件和加工结果。', 'Select a material to inspect its original and outputs.'), sidebar, config)
    sid = source['source_snapshot_id']
    if args.get('block') and not any(b['block_id'] == args['block'] for b in data['blocks'][sid]):
        raise ValueError('Block is outside the selected material')
    tasks = material_tasks(root, data, sid, read_state(root))
    config['revision'] = tasks['revision']
    config['selection'].update(dataset=data['id'], source=sid, tab=args.get('tab', 'original'))
    selected_ids = [t['selected_run_id'] for t in tasks['tasks'] if t.get('selected_run_id')]
    loaded_runs = dict(tasks.get('loaded_runs', {}))
    for rid in selected_ids:
        if rid not in loaded_runs:
            loaded_runs[rid] = load_dataset_run(root, data, rid, sid)
    if args.get('run') and args['run'] not in loaded_runs:
        loaded_runs[args['run']] = load_dataset_run(root, data, args['run'], sid)
    if args.get('run'):
        from apps.review_workbench.data.agent_runs import parent_for_extraction
        parent_id = parent_for_extraction(root, loaded_runs[args['run']])
        if parent_id:
            trace_query = e(urlencode({'agent': 'data', 'run': parent_id}))
            content += '<p class="dw-notice"><a href="/agent-results?' + trace_query + '">' + bi('返回这次运行的结果与评分', 'Back to this result & scores') + '</a> · <a href="/agent-runs?' + trace_query + '">Trace ID: ' + e(parent_id) + '</a></p>'
    matrix = build_dataset_table(data, sid) if args.get('base') == '1' else build_financial_table([loaded_runs[rid] for rid in selected_ids])
    # Direct links to historical candidates are inspectable without selecting or adopting them.
    if args.get('run') and (args['run'] not in selected_ids or not args.get('fact')):
        matrix = build_financial_table([loaded_runs[args['run']]])
        config['historical_fact'] = True
    if args.get('fact'):
        matches = [c for row in matrix['rows'] for cell in row['cells'].values() for c in cell['candidates'] if c['record_id'] == args['fact'] and (args.get('base') == '1' or c.get('run_id') == args.get('run'))]
        if not matches:
            raise ValueError('Fact is outside the selected source and version')
    content += '<div class="dw-material-heading"><h2>' + source_title(source) + '</h2><span>' + bi('公开日期 ', 'Published ') + e(source.get('available_at') or '—') + '</span></div><nav class="dw-tabs" aria-label="Material views">'
    for key, label in TABS.items():
        content += '<a data-tab="' + key + '" href="' + e(url(dataset=data['id'], source=sid, tab=key, base=args.get('base'))) + '"' + (' aria-current="page"' if args.get('tab', 'original') == key else '') + '>' + bi(*label) + '</a>'
    content += '</nav><div class="dw-reader" id="dw-reader"><section class="dw-source-pane"><div class="dw-pane-heading"><strong>' + bi('原始材料', 'Original material') + '</strong><button id="dw-expand-source" type="button" aria-pressed="false"><span data-expand-label>' + bi('展开阅读', 'Expand reader') + '</span><span data-collapse-label hidden>' + bi('返回对照', 'Return to comparison') + '</span></button></div>'
    content += '<p id="dw-source-context" class="dw-source-context" hidden></p><p id="dw-source-status" class="dw-source-status dw-muted" data-state="idle" aria-live="polite">' + bi('已保存原件；外部资源不加载。', 'Saved original; external resources are disabled.') + '</p>'
    content += '<iframe id="dw-source-frame" title="原始材料 / Original material" sandbox="" src="/data-workspace/source?' + e(urlencode({'dataset': data['id'], 'source': sid})) + '"></iframe><details id="dw-source-quote" hidden><summary>' + bi('对应的证据原文', 'Cited source text') + '</summary><blockquote></blockquote></details></section><div class="dw-divider" id="dw-divider" role="separator" tabindex="0" aria-label="调整两栏宽度 / Resize panes" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="50"></div><section class="dw-output-pane" data-scroll-key="outputs">'
    panels = {}
    panels['original'] = storage_view(data, source)
    version_labels = {v['run_id']: (t['label_zh'] + ' / ' + v.get('label_zh', '已保存版本'), t['label_en'] + ' / ' + v.get('label_en', 'Saved version')) for t in tasks['tasks'] for v in t['versions']}
    financial_head = '<div class="dw-financial-scope"><div class="dw-scope-summary"><strong>' + bi('当前展示', 'Current view') + '</strong><p>'
    if config.get('historical_fact'):
        financial_head += bi('历史版本预览', 'Historical version preview') + ' · ' + bi(*version_labels.get(args['run'], ('单次提取', 'Single extraction')))
        financial_head += '</p><small>' + bi('当前展示选择没有改变。', 'Display selections are unchanged.') + '</small>'
    elif args.get('base') == '1':
        financial_head += bi('正在查看已登记的基础数据库。', 'Showing the registered base database.') + '</p>'
    elif selected_ids:
        financial_head += bi(f'已选 {len(selected_ids)} 项任务', f'{len(selected_ids)} selected tasks') + '</p><p class="dw-version-summary">' + ' · '.join(bi(*version_labels[rid]) for rid in selected_ids) + '</p>'
    else:
        financial_head += bi('尚未选择提取版本', 'No extraction version selected') + '</p>'
    financial_head += '</div>'
    has_base = any(r['source_snapshot_id'] == sid for r in data['records'])
    if has_base:
        financial_head += '<p><a href="' + e(url(dataset=data['id'], source=sid, tab='financials', base='0' if args.get('base') == '1' else '1')) + '">' + (bi('查看选定提取版本', 'Show selected extraction versions') if args.get('base') == '1' else bi('查看已保存基础数据', 'Show saved base data')) + '</a></p>'
    financial_head += disclosure(('调整版本与历史', 'Adjust versions & history'), version_controls(tasks, args), opened=not selected_ids and args.get('base') != '1' and not config.get('historical_fact'), css_class='dw-versions') + '</div>'
    panels['financials'] = financial_head + financial_view(matrix, args, version_labels)
    panels['blocks'] = blocks_view(data, source, args)
    panels['brief'] = '<h3>' + bi('材料精编', 'Filing brief') + '</h3>' + empty('尚未生成。这份材料目前提供原件、章节与表格，以及已登记的财务提取产物。', 'Not generated. This material currently provides its original, sections and tables, and registered financial extractions.')
    process = version_controls(tasks, args)
    if args.get('run'):
        run = loaded_runs[args['run']]
        archived = any(v['run_id'] == args['run'] and v['archived'] for t in tasks['tasks'] for v in t['versions'])
        if archived:
            process += empty('此提取版本已归档，历史产物仍可查看。', 'This version is archived; its historical artifacts remain readable.')
        process += processing_record(run, root=root).replace('href="#financial-facts"', 'href="' + e(url(dataset=data['id'], source=sid, tab='financials')) + '"')
        process += '<p><a href="' + e(url(dataset=data['id'], source=sid, tab='financials', run=run['id'])) + '">' + bi('查看此版本的财务候选', 'Inspect financial candidates from this version') + '</a></p>'
        if not run.get('db_rows') and run['artifacts'].get('extraction.json', {}).get('records'):
            process += json_detail(('尚未入库的原始候选', 'Drafts not written to the database'), run['artifacts']['extraction.json']['records'])
        process += json_detail(('已有独立核验', 'Saved independent review'), run.get('review'))
        process += disclosure(('这次提取的保存位置', 'Extraction storage'), field_table({'运行 / Run': run['id'], '文件夹 / Folder': run['path'], '数据库 / Database': run['path'] + '/dataset/research.duckdb' if run.get('db_check') == 'payload_matches_normalized' else '未保存 / Not saved', 'manifest_sha256': run['manifest_sha256']}))
    else:
        process += empty('选择一个版本，查看实际输入、Prompt / Skill、输出与核验。', 'Choose a version to inspect its saved inputs, Prompt / Skill, outputs and review.')
    process += storage_view(data, source)
    process += json_detail(('解析诊断与已知缺口', 'Parsing diagnostics & known gaps'), {'diagnostics': data['indexes'][sid].get('diagnostics', []), 'gaps': [g for g in data['gaps'] if g.get('source_snapshot_id') in (None, sid)]})
    panels['process'] = process
    for key, panel in panels.items():
        content += '<section data-panel="' + key + '"' + (' class="dw-financial-panel"' if key == 'financials' else '') + (' hidden' if args.get('tab', 'original') != key else '') + '>' + panel + '</section>'
    content += '</section></div>'
    return shell(content, sidebar, config)
