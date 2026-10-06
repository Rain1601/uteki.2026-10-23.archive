"""Read-only inspection of registered datasets and recorded Data Agent runs."""
import json
from collections import defaultdict
from urllib.parse import urlencode, urlparse

from apps.review_workbench.assets import asset_text
from apps.review_workbench.components.site_navigation import bi, page
from apps.review_workbench.data.evaluation_artifacts import load_catalog, load_dataset, load_run
from apps.review_workbench.data.direct_extraction_views import dataset_runs, load_dataset_run
from apps.review_workbench.pages.dataset_view import field_table, render_block
from apps.review_workbench.pages.query_runs import amount, e, period


PARAMS = {'dataset', 'tab', 'source', 'record', 'block', 'q', 'type', 'metric', 'offset', 'run', 'step',
          'kind', 'fact', 'return_run', 'return_kind', 'return_fact'}
TABS = {'materials': ('公司材料', 'Company materials'), 'blocks': ('原文目录', 'Source contents'),
        'records': ('财务事实', 'Financial facts'), 'runs': ('运行回放', 'Run replay')}
PAGE_SIZE = 40
VERDICTS = {'supported': ('证据支持', 'Supported'), 'contradicted': ('与证据矛盾', 'Contradicted'),
            'insufficient_evidence': ('证据不足', 'Insufficient evidence'),
            'complete': ('本题完成', 'Complete for this question'), 'needs_revision': ('需要修订', 'Needs revision'),
            'text_sufficient': ('本题文本足够', 'Text sufficient for this question'),
            'requires_more_source_content': ('需要补充来源内容', 'More source content required')}
GAP_REASONS = {'unmapped_concept': ('未映射的财务概念', 'Unmapped concepts'),
               'unsupported_duration': ('尚不支持的期间', 'Unsupported duration'),
               'image_reference_only': ('图片只有引用', 'Image reference only'),
               'item_heading_ambiguous': ('章节标题有歧义', 'Ambiguous section heading'),
               'repeated_legal_headers_excluded': ('重复页眉已排除', 'Repeated headers excluded'),
               'item_anchor_body_override': ('章节按正文位置定位', 'Section located from body')}


def href(**values):
    return '/evaluation' + ('?' + urlencode({k: v for k, v in values.items() if v is not None and v != ''}) if values else '')


def link(label, *, anchor=None, **values):
    url = href(**values) + ('#' + anchor if anchor else '')
    return '<a href="' + e(url) + '">' + label + '</a>'


def details(label, body, *, opened=False):
    return '<details' + (' open' if opened else '') + '><summary>' + label + '</summary>' + body + '</details>'


def saved_json(label, value):
    return details(bi(*label), '<pre>' + e(json.dumps(value, ensure_ascii=False, indent=2, default=str)) + '</pre>')


def table(labels, rows):
    return '<div class="ev-scroll"><table><thead><tr>' + ''.join('<th>' + bi(*x) + '</th>' for x in labels) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join('<td>' + cell + '</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def source_label(source):
    return ' / '.join(str(source.get(k) or '—') for k in ('form', 'period_end', 'available_at'))


def verdict(value):
    return bi(*VERDICTS[value]) if value in VERDICTS else e(value or '—')


def select_control(name, label, options, selected, *, all_label=None):
    items = ([('', all_label)] if all_label else []) + options
    return '<label>' + bi(*label) + '<select name="' + e(name) + '">' + ''.join(
        '<option value="' + e(key) + '"' + (' selected' if key == selected else '') + '>' + e(text) + '</option>'
        for key, text in items) + '</select></label>'


def filters(data, args, extra=''):
    body = '<form method="get" action="/evaluation" class="ev-filters">'
    for key in ('dataset', 'tab'):
        body += '<input type="hidden" name="' + key + '" value="' + e(args[key]) + '">'
    body += select_control('source', ('材料', 'Material'), [(s['source_snapshot_id'], source_label(s)) for s in data['sources']],
                           args.get('source', ''), all_label='选择材料 / Select material' if args['tab'] == 'blocks' else '全部材料 / All materials')
    body += extra + '<label>' + bi('搜索当前范围', 'Search this scope') + '<input name="q" type="search" maxlength="200" value="' + e(args.get('q', '')) + '"></label>'
    return body + '<button type="submit">' + bi('筛选', 'Filter') + '</button></form>'


def pagination(args, count):
    offset = args['offset']
    body = '<div class="ev-pagination">' + bi(f'匹配 {count} 项', f'{count} matches')
    for target, label in ((offset - PAGE_SIZE, ('上一页', 'Previous')), (offset + PAGE_SIZE, ('下一页', 'Next'))):
        if 0 <= target < count:
            values = {k: v for k, v in args.items() if k not in {'record', 'block', 'step'}}
            values['offset'] = target
            body += link(bi(*label), **values)
    return body + '</div>'


def material_diagnostics(data, args, registered=None):
    groups = defaultdict(list)
    for gap in data['gaps']:
        if args.get('source') and gap.get('source_snapshot_id') not in (None, args['source']):
            continue
        groups[(gap.get('source_snapshot_id', ''), gap.get('layer', ''), gap.get('reason', ''))].append(gap)
    body = '<p>' + bi('数量是处理时记录的事件数，不等于缺失指标数。',
                      'Counts are recorded processing events, not distinct missing metrics.') + '</p>'
    for (sid, layer, reason), gaps in sorted(groups.items()):
        concepts = sorted({g['concept'] for g in gaps if g.get('concept')})
        content = '<p>' + e(layer) + '</p>'
        if concepts:
            content += '<p>' + bi(f'{len(concepts)} 个不同概念', f'{len(concepts)} distinct concepts') + '</p><pre>' + e('\n'.join(concepts)) + '</pre>'
        content += saved_json(('全部缺口记录', 'All recorded gaps'), gaps)
        label = e(f'{sid or "dataset"} · {reason} · {len(gaps)}')
        if reason in GAP_REASONS:
            label += ' · ' + bi(*GAP_REASONS[reason])
        body += details(label, content)
    if not groups:
        body += '<p>' + bi('没有已记录缺口；这不证明处理完整。', 'No recorded gaps; completeness is not established.') + '</p>'
    if registered and registered['gaps']:
        body += saved_json(('提取运行关联缺口', 'Extraction binding gaps'), {'binding_gaps': registered['gaps']})
    body += details(bi('本数据版本声明的限制', 'Declared limits for this dataset'),
                    '<ul>' + ''.join('<li>' + e(limit) + '</li>' for limit in data['limits']) + '</ul>')
    return details(bi('处理诊断与能力边界', 'Processing diagnostics & limits'), body)


def source_outline(data, source, *, return_context=None):
    sid = source['source_snapshot_id']
    by_id = {block['block_id']: block for block in data['blocks'][sid]}
    nodes = [node for node in data['indexes'][sid].get('nodes', []) if node.get('kind') != 'document']
    body = '<section class="ev-outline"><h3>' + bi('章节目录', 'Section contents') + '</h3>'
    if not nodes:
        return body + '<p>' + bi('尚无可用章节目录；可继续查看已解析的段落与表格。',
                                'No section contents are available. Parsed passages and tables remain accessible.') + '</p></section>'
    body += '<ul>'
    for node in nodes:
        bid = node.get('start_block_id')
        title = node.get('title') or '未命名章节 / Untitled section'
        body += '<li class="ev-outline-' + ('part' if node.get('kind') == 'part' else 'item') + '">'
        if bid in by_id:
            body += link(e(title), anchor='block-detail', dataset=data['id'], tab='blocks', source=sid,
                         block=bid, **(return_context or {}))
        else:
            body += e(title) + ' · ' + bi('定位不可用', 'Location unavailable')
        if node.get('reported_page') is not None:
            body += '<small>' + bi('原文页 ', 'Source page ') + e(node['reported_page']) + '</small>'
        body += '</li>'
    return body + '</ul></section>'


def original_links(data, source):
    raw_url = '/evaluation/source?' + urlencode({'dataset': data['id'], 'source': source['source_snapshot_id']})
    body = '<a href="' + e(raw_url) + '">' + bi('阅读已保存原件', 'Read saved original') + '</a>'
    if urlparse(source.get('source_url', '')).scheme in {'https', 'http'}:
        body += ' · <a href="' + e(source['source_url']) + '" rel="noreferrer">' + bi('官方来源', 'Official source') + '</a>'
    return body


def material_versions(data, source, root, registered):
    sid = source['source_snapshot_id']
    runs = [run for run in registered['runs'] if run['source_snapshot_id'] == sid]
    body = '<section id="material-financial-facts"><h3>' + bi('财务事实与提取版本', 'Financial facts & extraction versions') + '</h3>'
    body += '<p class="ev-note">' + bi('各次提取独立保留，候选条数不能跨版本相加。逐条审核与共享采纳分别记录。',
        'Each extraction is retained separately. Candidate counts must not be added across versions. Per-fact review and shared adoption are separate.') + '</p>'
    rows = []
    statuses = {'completed': ('执行完成', 'Execution completed'), 'completed_with_gaps': ('存在处理缺口', 'Completed with gaps'),
                'failed': ('执行失败', 'Execution failed'), 'candidate': ('已产出候选', 'Candidates produced'), 'budget_exhausted': ('达到运行限额', 'Run limit reached')}
    for number, ref in enumerate(runs, 1):
        run = load_dataset_run(root, data, ref['id'], sid)
        artifacts = run['artifacts']; result = artifacts.get('result.json', {})
        state = result.get('status')
        raw = artifacts.get('extraction.json'); normalized = artifacts.get('normalized.json')
        counts = (bi(f'原文候选 {len(raw.get("records", []))} 条', f'{len(raw.get("records", []))} reported drafts') if raw is not None else bi('原文候选未保存', 'Reported drafts not saved'))
        counts += '<br>' + (bi(f'规范化候选 {len(normalized.get("records", []))} 条', f'{len(normalized.get("records", []))} normalized candidates') if normalized is not None else bi('规范化产物未保存', 'Normalized output not saved'))
        review = bi('已登记审核，查看范围与结论', 'Review saved; inspect scope & verdicts') if run.get('review') is not None else bi('尚无独立审核', 'No independent review')
        counts += '<small>' + review + '<br>' + bi('未因运行完成而自动采纳', 'Completion does not imply adoption') + '</small>'
        metadata = {'run_id': run['id'], 'parent_run_id': run.get('parent_run_id'),
                    'path': run['path'], 'manifest_sha256': run['manifest_sha256']}
        label = bi(f'提取版本 {number}', f'Extraction version {number}')
        metric_catalog = artifacts.get('packet.json', {}).get('metric_catalog') or {}
        catalog_items = metric_catalog.values() if isinstance(metric_catalog, dict) else metric_catalog
        metric_labels = {item.get('metric_id'): item.get('label') or item.get('metric_id')
                         for item in catalog_items if isinstance(item, dict)}
        actual_metrics = list(dict.fromkeys(str(row.get('metric') or metric_labels.get(row.get('metric_id')) or row.get('metric_id'))
                                           for row in (raw or {}).get('records', []) + (normalized or {}).get('records', [])
                                           if row.get('metric') or row.get('metric_id')))
        if actual_metrics:
            label += '<p class="ev-version-metrics">' + e(' / '.join(actual_metrics[:3])) + '</p>'
            if len(actual_metrics) > 3:
                label += details(bi('本次已产出的全部指标', 'All metrics produced in this run'), '<p>' + e(' / '.join(actual_metrics)) + '</p>')
        task_input = artifacts.get('job.json', {}).get('task')
        if task_input is not None:
            label += saved_json(('本次任务（job.json）', 'This task (job.json)'), task_input)
        elif artifacts.get('packet.json', {}).get('task') is not None:
            label += saved_json(('本次任务（packet.json）', 'This task (packet.json)'), artifacts['packet.json']['task'])
        label += details(bi('版本标识与存储', 'Version identity & storage'), field_table(metadata))
        process = '/extractions?' + urlencode({'run': run['id']}) + '#processing-record'
        actions = link(bi('查看数字与证据', 'Inspect numbers & evidence'), dataset=data['id'], tab='records', source=sid, run=run['id'])
        actions += '<br><a href="' + e(process) + '">' + bi('输入、提取方法与检查', 'Inputs, extraction method & checks') + '</a>'
        rows.append([label, bi(*statuses[state]) if state in statuses else e(state or '未保存 / Not saved'), counts, actions])
    if rows:
        body += table([('版本', 'Version'), ('执行状态', 'Execution status'), ('产物与审核', 'Outputs & review'), ('查看', 'Inspect')], rows)
    else:
        body += '<p class="ev-empty">' + bi('这份材料尚无已登记的财务提取结果。',
                'No financial extraction results are registered for this material.') + '</p>'
    base_count = sum(row['source_snapshot_id'] == sid for row in data['records'])
    body += '<p>' + bi(f'基础数据包另外保存 {base_count} 条记录。', f'The base dataset separately contains {base_count} records.')
    if base_count:
        body += ' ' + link(bi('查看基础记录与状态', 'Inspect base records & status'), dataset=data['id'], tab='records', source=sid)
    return body + '</p></section>'


def materials(data, root, args):
    registered = dataset_runs(root, data)
    sid = args.get('source')
    if not sid:
        rows = []
        for source in data['sources']:
            source_id = source['source_snapshot_id']
            runs = [run for run in registered['runs'] if run['source_snapshot_id'] == source_id]
            rows.append([e(source.get('form') or '—'), e(source.get('period_end') or '—'),
                         e(source.get('available_at') or '—'),
                         bi(f'{len(runs)} 次已登记提取', f'{len(runs)} registered extractions'),
                         link(bi('查看材料与产物', 'Inspect material & outputs'), dataset=data['id'], tab='materials', source=source_id)])
        body = '<h2>' + bi('公司材料', 'Company materials') + '</h2><p>' + bi('选择一份材料，查看原件、原文目录、财务事实、财报精编和处理过程。',
                'Select a material to inspect its original, source contents, financial facts, filing brief and processing history.') + '</p>'
        body += table([('材料类型', 'Form'), ('报告期截至', 'Reporting period end'), ('公开日期', 'Publication date'),
                       ('财务提取', 'Financial extractions'), ('材料', 'Material')], rows)
        if not rows:
            body += '<p class="ev-empty">' + bi('当前数据版本没有已登记材料。', 'No materials are registered in this dataset version.') + '</p>'
        body += material_diagnostics(data, args, registered)
        return body
    source = next(item for item in data['sources'] if item['source_snapshot_id'] == sid)
    source_blocks = data['blocks'][sid]
    body = '<p>' + link(bi('返回公司材料列表', 'Back to company materials'), dataset=data['id'], tab='materials') + '</p>'
    body += '<section id="material-detail"><h2>' + e(source.get('form') or '—') + ' · ' + bi('报告期截至 ', 'Period ended ') + e(source.get('period_end') or '—') + '</h2>'
    body += '<p class="ev-note">' + bi('公开日期：', 'Publication date: ') + e(source.get('available_at') or '—') + '</p>'
    body += '<nav class="ev-material-nav">' + ''.join('<a href="#' + key + '">' + bi(*label) + '</a>' for key, label in (
        ('material-original', ('原始材料', 'Original material')), ('material-contents', ('原文目录', 'Source retrieval')),
        ('material-financial-facts', ('财务事实', 'Financial facts')), ('material-brief', ('财报精编', 'Filing brief')))) + '</nav>'
    body += '<section id="material-original"><h3>' + bi('原始材料', 'Original material') + '</h3><p>' + original_links(data, source) + '</p>'
    body += '<p class="ev-note">' + bi('已保存原件并核对文件一致性。公开日期来自来源记录，不是下载时间。',
             'The saved original has passed file-integrity checks. Publication date comes from source metadata, not download time.') + '</p></section>'
    body += '<section id="material-contents"><h3>' + bi('原文结构', 'Source structure') + '</h3><p>'
    for kind, label in (('paragraph', ('段落', 'Passages')), ('table', ('表格', 'Tables'))):
        count = sum(block['type'] == kind for block in source_blocks)
        body += link(bi(f'{label[0]}（{count}）', f'{label[1]} ({count})'), dataset=data['id'], tab='blocks', source=sid, type=kind) + ' '
    body += link(bi('查看全部原文块', 'Browse all source blocks'), dataset=data['id'], tab='blocks', source=sid) + '</p>'
    body += '<p class="ev-note">' + bi('表格数量包含 HTML 排版表格，不等于财务报表数量。', 'Table counts include HTML layout tables, not only financial statements.') + '</p>'
    body += source_outline(data, source) + '</section>'
    body += material_versions(data, source, root, registered)
    body += '<section id="material-brief"><h3>' + bi('财报精编', 'Filing brief') + '</h3><p>' + bi('未生成', 'Not generated') + '</p><p class="ev-note">' + bi('原文目录和财务提取不代表已完成财报精编。',
              'Source contents and financial extractions do not constitute a completed filing brief.') + '</p></section>'
    storage = data.get('storage') or {}
    storage_meta = {key: source[key] for key in ('company_id', 'source_snapshot_id', 'raw_file', 'index_folder', 'raw_file_sha256', 'source_url', 'status') if key in source}
    if storage.get('dataset_path'):
        storage_meta.update(storage)
        storage_meta['raw_file'] = storage['dataset_path'].rstrip('/') + '/' + source['raw_file']
        index_path = storage['dataset_path'].rstrip('/') + '/' + source['index_folder']
        storage_meta.update({'index_file': index_path + '/index.json', 'blocks_file': index_path + '/blocks.jsonl'})
        path_label = bi('以下文件位置相对项目根目录。', 'File paths below are relative to the repository root.')
    else:
        path_label = bi('以下文件位置相对当前数据包。', 'File paths below are relative to this dataset.')
    body += details(bi('材料标识与存储位置', 'Material identity & storage'),
        '<p>' + path_label + '</p>' + field_table(storage_meta) +
        '<p>' + bi('章节目录保存在 index.json，原文块保存在 blocks.jsonl。提取版本保存 JSON 候选；存在 DuckDB 时，规范化候选也可在数据库中核对。基础记录保存在 records.json，数据库保存在 research.duckdb。',
        'Section contents are saved in index.json; source blocks in blocks.jsonl. Each extraction saves JSON candidates; when DuckDB is present, normalized candidates can also be checked against the database. Base records are in records.json; the database is research.duckdb.') + '</p>')
    body += material_diagnostics(data, args, registered)
    return body + '</section>'


def block_detail(data, source, block, return_context=None):
    meta = {k: block[k] for k in ('block_id', 'ordinal', 'type', 'reported_page', 'pdf_page', 'dom_path', 'source_anchor', 'text_hash') if k in block}
    blocks = data['blocks'][source['source_snapshot_id']]
    position = next(i for i, item in enumerate(blocks) if item['block_id'] == block['block_id'])
    neighbors = '<div class="ev-pagination">'
    for index, label in ((position - 1, ('上一原文块', 'Previous source block')), (position + 1, ('下一原文块', 'Next source block'))):
        if 0 <= index < len(blocks):
            neighbors += link(bi(*label), anchor='block-detail', dataset=data['id'], tab='blocks',
                              source=source['source_snapshot_id'], block=blocks[index]['block_id'], **(return_context or {}))
    neighbors += '</div>'
    return _render_block_detail(block, neighbors, meta)


def _render_block_detail(block, neighbors, meta):
    title = bi('原文表格', 'Source table') if block.get('type') == 'table' else bi('原文内容', 'Source passage')
    if block.get('ordinal') is not None:
        title += ' · ' + e(block['ordinal'])
    return '<section class="ev-detail" id="block-detail"><h3>' + title + '</h3>' + neighbors + render_block(block) + details(
        bi('定位与来源标识', 'Location & source identity'), field_table(meta)) + saved_json(('完整块结构', 'Complete block structure'), block) + '</section>'


def blocks_view(data, args):
    sid = args.get('source')
    choices = sorted({b['type'] for group in data['blocks'].values() for b in group})
    body = filters(data, args, select_control('type', ('块类型', 'Block type'), [(t, t) for t in choices], args.get('type', ''), all_label='全部类型 / All types'))
    if not sid:
        return body + '<p class="ev-empty">' + bi('选择一份材料，查看其原件、解析块和诊断。', 'Select a material to inspect its source, blocks and diagnostics.') + '</p>'
    source = next(s for s in data['sources'] if s['source_snapshot_id'] == sid)
    return_context = {k: args[k] for k in ('return_run', 'return_kind', 'return_fact') if args.get(k)}
    if return_context:
        body += '<p>' + link(bi('返回财务事实与审核', 'Back to the financial fact & review'), anchor='fact-detail',
            dataset=data['id'], tab='records', source=sid, run=args['return_run'], kind=args['return_kind'], fact=args['return_fact']) + '</p>'
    source_blocks = data['blocks'][sid]; index = data['indexes'][sid]
    body += '<h2>' + e(source_label(source)) + '</h2>'
    body += '<p>' + link(bi('返回这份材料与产物', 'Back to this material & outputs'), dataset=data['id'], tab='materials', source=sid) + ' · ' + original_links(data, source) + '</p>'
    raw_url = '/evaluation/source?' + urlencode({'dataset': data['id'], 'source': sid})
    if source.get('declared_mime_type') == 'text/html' or str(source.get('raw_file', '')).endswith(('.html', '.htm')):
        body += details(bi('在此阅读完整原件', 'Read the complete original here'), '<p>' + bi('原件以隔离模式显示，外部图片和脚本不加载。', 'The source is sandboxed; external images and scripts are not loaded.') + '</p><iframe loading="lazy" sandbox="" class="ev-source" title="Frozen source" src="' + e(raw_url) + '"></iframe>')
    chosen = next((b for b in source_blocks if b['block_id'] == args.get('block')), None)
    if args.get('block') and chosen is None:
        raise KeyError('Block outside selected source')
    if chosen:
        body += block_detail(data, source, chosen, return_context)
    if not chosen and not args.get('q') and not args.get('type'):
        body += source_outline(data, source, return_context=return_context)
    body += '<h3>' + bi('段落与表格', 'Passages & tables') + '</h3>'
    selected = [b for b in source_blocks if (not args.get('type') or b['type'] == args['type']) and args.get('q', '').casefold() in (b['block_id'] + ' ' + b['text']).casefold()]
    rows = [[e(b.get('ordinal')), e(b['type']), e(b.get('reported_page')), e(b['text'][:200]) + ('…' if len(b['text']) > 200 else ''),
             link(bi('阅读全文', 'Read content'), anchor='block-detail', dataset=data['id'], tab='blocks', source=sid, block=b['block_id'], q=args.get('q'), type=args.get('type'), offset=args['offset'], **return_context)] for b in selected[args['offset']:args['offset'] + PAGE_SIZE]]
    body += pagination(args, len(selected)) + table([('序号', 'Ordinal'), ('类型', 'Type'), ('页码', 'Page'), ('原文预览', 'Text preview'), ('查看完整块', 'Complete block')], rows)
    diagnostics = index.get('diagnostics', [])
    technical = field_table({k: source[k] for k in ('company_id', 'source_snapshot_id', 'raw_file', 'index_folder', 'raw_file_sha256', 'available_at', 'status') if k in source})
    technical += '<p>' + e(f"{data['raw_sizes'][sid]:,}") + ' bytes · ' + e(index.get('parser_version')) + '</p>'
    technical += saved_json(('解析诊断', 'Parsing diagnostics'), diagnostics)
    technical += saved_json(('资源引用', 'Asset references'), data['assets'][sid])
    technical += '<p>' + bi('资源引用不等于图像字节已取得或内容已理解。', 'An asset reference does not establish byte availability or content understanding.') + '</p>'
    body += details(bi('解析诊断、来源标识与资源限制', 'Parsing diagnostics, source identity & asset limits'), technical)
    return body


def quote_view(data, citation):
    sid = citation['source_snapshot_id']; bid = citation['block_id']
    matches = [b for b in data['blocks'].get(sid, []) if b['block_id'] == bid]
    if len(matches) != 1 or not citation['quote'] or citation['quote'] not in matches[0]['text']:
        raise ValueError('Review evidence outside selected dataset')
    return '<blockquote>' + e(citation['quote']) + '</blockquote>' + link(e(bid), anchor='block-detail', dataset=data['id'], tab='blocks', source=sid, block=bid)


def record_detail(data, record, catalog, root):
    source = next(s for s in data['sources'] if s['source_snapshot_id'] == record['source_snapshot_id'])
    body = '<section class="ev-detail" id="record-detail"><h2>' + bi('这一行的原文、字段与核验', 'Source, fields & review for this row') + '</h2><p class="ev-id">' + e(record['record_id']) + '</p><div class="ev-compare"><section><h3>' + bi('候选数据', 'Candidate record') + '</h3>'
    body += field_table({k: record.get(k) for k in ('entity_id', 'metric_id', 'period', 'value_decimal', 'unit', 'accounting_basis', 'dimensions', 'value_kind', 'status')})
    body += saved_json(('全部字段与来源元数据', 'All fields & provenance'), record) + '</section><section><h3>' + bi('证据与表格', 'Evidence & table') + '</h3>'
    evs = [data['evidence'][eid] for role in ('evidence_ids', 'qualifier_evidence_ids', 'question_evidence_ids') for eid in record.get(role, [])]
    if not evs:
        body += '<p>' + bi('该记录未提供证据引用。', 'No evidence references supplied for this record.') + '</p>'
    seen = set()
    for ev in evs:
        body += quote_view(data, ev)
        block = next(b for b in data['blocks'][source['source_snapshot_id']] if b['block_id'] == ev['block_id'])
        if block['block_id'] not in seen:
            body += details(bi('展开完整原文块 / 表格', 'Expand source block / table'), render_block(block))
            seen.add(block['block_id'])
        if ev.get('number_metadata'):
            body += details(bi('原始数值与单位元数据', 'Original numeric metadata'), field_table(ev['number_metadata']))
    body += '</section></div><section><h3>' + bi('已保存的模型核验', 'Saved model review') + '</h3>'
    matched = False
    for entry in catalog['runs']:
        if entry['dataset_id'] != data['id']:
            continue
        run = load_run(root, entry['id'])
        if run['dataset_id'] != data['id']:
            raise ValueError('Record review dataset mismatch')
        for fact in run.get('facts', []):
            value = fact.get('value', {})
            if fact.get('kind') != 'record' or value.get('record_id') != record['record_id'] or value.get('source_snapshot_id') != record['source_snapshot_id']:
                continue
            assessment = run.get('assessment') or {}
            review = next((r for r in assessment.get('facts', []) if r['fact_id'] == fact['fact_id']), None)
            matched = True
            body += '<p>' + link(e(entry['label']), dataset=data['id'], tab='runs', run=entry['id']) + '</p>'
            if review:
                body += '<strong>' + verdict(review['verdict']) + '</strong><p>' + e(review['rationale']) + '</p>'
                body += ''.join(quote_view(data, c) for c in review.get('citations', []))
            else:
                body += '<p>' + bi('该事实没有已保存的内容核验结论。', 'No saved content verdict for this fact.') + '</p>'
    if not matched:
        body += '<p class="ev-empty">' + bi('未纳入已登记运行的内容核验。不能因同一材料另有记录通过，就视为这一行已通过。',
                    'Not included in a registered content review. Another reviewed row from the same material does not approve this row.') + '</p>'
    return body + '<p class="ev-note">' + bi('模型意见仅适用于其任务和版本。人工验收未记录；本页不改变共享采纳状态。', 'Model opinions apply only to their task and version. Human acceptance is not recorded; this page does not change adoption.') + '</p></section></section>'


def records_view(data, args, catalog, root):
    from apps.review_workbench.pages.extraction_facts import render_fact_matrices
    registered = dataset_runs(root, data)
    runs = [r for r in registered['runs'] if not args.get('source') or r['source_snapshot_id'] == args['source']]
    body = '<h2>' + bi('已登记的提取运行', 'Registered extraction runs') + '</h2>'
    body += '<p>' + bi('选择材料和运行版本。不会自动选择最近一次，也不会用新运行覆盖失败草稿。',
                      'Choose a material and run version. The latest run is not selected automatically, and newer runs do not replace failed drafts.') + '</p>'
    if runs:
        source_names = {source['source_snapshot_id']: source_label(source) for source in data['sources']}
        body += table([('运行', 'Run'), ('材料', 'Source'), ('查看', 'Inspect')], [[bi(f'提取版本 {number}', f'Extraction version {number}') + details(bi('版本标识', 'Version identity'), e(r['id'])), e(source_names[r['source_snapshot_id']]),
            link(bi('查看事实矩阵', 'Inspect fact matrices'), dataset=data['id'], tab='records', source=r['source_snapshot_id'], run=r['id'])] for number, r in enumerate(runs, 1)])
    else:
        body += '<p class="ev-empty">' + bi('此范围尚无与数据包版本绑定的提取运行。基础数据包的已存记录在下方。', 'No extraction run is bound to this dataset version and scope. Existing base dataset records are below.') + '</p>'
    if registered['gaps']:
        body += saved_json(('提取运行关联缺口', 'Extraction binding gaps'), {'binding_gaps': registered['gaps']})
    if args.get('run'):
        run = load_dataset_run(root, data, args['run'], args.get('source'))
        context = {k: args[k] for k in ('dataset', 'source', 'q', 'metric', 'offset') if k in args}
        body += render_fact_matrices(run, context=context, dataset=data, kind=args.get('kind'), fact=args.get('fact'))
        body += '<p><a href="/extractions?' + e(urlencode({'run': run['id']})) + '">' + bi('查看完整输入、提示词和运行产物', 'Inspect full input, prompts & run artifacts') + '</a></p>'
        if run['review'] is not None:
            body += saved_json(('完整独立审核', 'Complete independent review'), run['review'])
    elif args.get('fact') or args.get('kind'):
        raise ValueError('Explicit extraction run required for candidate selection')
    body += '<h2>' + bi('基础数据包中的候选记录', 'Candidate records in the base dataset') + '</h2>'
    keys = sorted({r['metric_id'] for r in data['records']})
    body += filters(data, args, select_control('metric', ('指标', 'Metric'), [(k, k) for k in keys], args.get('metric', ''), all_label='全部指标 / All metrics'))
    body += details(bi('数据库表、字段与类型', 'Database tables, fields & types'), table([('表', 'Table'), ('列', 'Column'), ('类型', 'Type'), ('可空', 'Nullable')], [[e(row[k]) for k in ('table_name', 'column_name', 'data_type', 'is_nullable')] for row in data['columns']]))
    by_id = {r['record_id']: r for r in data['records']}
    if args.get('record'):
        record = by_id.get(args['record'])
        if record is None or (args.get('source') and record['source_snapshot_id'] != args['source']):
            raise KeyError('Record outside selected source/dataset')
        body += record_detail(data, record, catalog, root)
    selected = [r for r in data['records'] if (not args.get('source') or r['source_snapshot_id'] == args['source']) and
                (not args.get('metric') or r['metric_id'] == args['metric']) and args.get('q', '').casefold() in json.dumps(r, ensure_ascii=False).casefold()]
    rows = [[e(r['entity_id']), e(r['metric_id']), period(r['period']) if r.get('period') else e(r.get('period_resolution')),
             amount(r), e(r.get('accounting_basis')), e(r.get('value_kind')), e(r.get('status')),
             link(bi('查看原文与核验', 'Inspect evidence & review'), anchor='record-detail', dataset=data['id'], tab='records', source=r['source_snapshot_id'], record=r['record_id'])] for r in selected[args['offset']:args['offset'] + PAGE_SIZE]]
    body += '<p>' + bi('展示冻结记录，已核对其与 DuckDB payload 的一致性及公司、来源归属；显示精确数值与原始口径。候选行数不等于独立事实数。',
                      'Frozen records match the DuckDB payloads and company/source identities, retaining exact values and basis. Candidate rows are not unique-fact counts.') + '</p>'
    return body + pagination(args, len(selected)) + table([('实体', 'Entity'), ('指标', 'Metric'), ('期间', 'Period'), ('值 / 单位', 'Value / unit'),
               ('口径', 'Basis'), ('性质', 'Value kind'), ('源记录状态', 'Record status'), ('详情', 'Detail')], rows)


def runs_view(data, args, catalog, root):
    entries = [r for r in catalog['runs'] if r['dataset_id'] == data['id']]
    if args.get('run') and args['run'] not in {r['id'] for r in entries}:
        raise KeyError('Run outside selected dataset')
    body = '<h2>' + bi('已保存的运行', 'Saved runs') + '</h2>'
    body += '<ul class="ev-run-list">' + ''.join('<li>' + link(e(r['label']), dataset=data['id'], tab='runs', run=r['id']) + '</li>' for r in entries) + '</ul>'
    if not entries:
        return body + '<p class="ev-empty">' + bi('该数据包尚未登记可回放的运行；不展示其他公司的运行。', 'No replay is registered for this dataset. Other companies’ runs are not substituted.') + '</p>'
    if not args.get('run'):
        return body + '<p>' + bi('选择一次运行，查看实际输入、步骤、结果与核验。', 'Select a run to inspect its input, steps, output and review.') + '</p>'
    if args['run'] not in {r['id'] for r in entries}:
        raise KeyError('Run outside selected dataset')
    run = load_run(root, args['run'])
    if run['dataset_id'] != data['id']:
        raise ValueError('Run dataset mismatch')
    body += '<h3>' + e(run['label']) + '</h3><p class="ev-question">' + e(run['question']) + '</p>'
    rr = run.get('review_result') or {}
    body += field_table({'query_status': run['result'].get('status'), 'review_status': rr.get('status', 'not_available'),
                         'analysis_eligible': rr.get('analysis_eligible'), 'adoption': rr.get('adoption', 'not_available')})
    body += details(bi('本次输入范围', 'Pinned input scope'), field_table(run['scope']))
    body += '<h3>' + bi('已提交事实与审阅意见', 'Submitted facts & review') + '</h3>'
    assessment = run.get('assessment') or {}
    if not assessment:
        body += '<p class="ev-empty">' + bi('本次没有已保存的内容核验结论。未核验不等于已通过。', 'No saved content review for this run. Unreviewed does not mean approved.') + '</p>'
    for fact in run.get('facts', []):
        review = next((a for a in assessment.get('facts', []) if a['fact_id'] == fact['fact_id']), None)
        value = fact.get('value', {})
        title = value.get('metric_id') or value.get('statement') or fact['fact_id']
        if fact['kind'] == 'record':
            bound = [r for r in data['records'] if r['record_id'] == value.get('record_id') and r['source_snapshot_id'] == value.get('source_snapshot_id')]
            if len(bound) != 1:
                raise ValueError('Run fact outside selected dataset records')
            content = field_table({k: value.get(k) for k in ('record_id', 'metric_id', 'period', 'value_decimal', 'unit', 'value_kind', 'accounting_basis')})
            content += link(bi('查看这条记录的证据', 'Inspect this record’s evidence'), anchor='record-detail', dataset=data['id'], tab='records', source=value['source_snapshot_id'], record=value['record_id'])
        else:
            content = field_table(value)
        if review:
            content += '<p><strong>' + verdict(review['verdict']) + '</strong></p><p>' + e(review['rationale']) + '</p>' + ''.join(quote_view(data, c) for c in review.get('citations', []))
        body += '<section data-fact-id="' + e(fact['fact_id']) + '">' + details(e(title), content) + '</section>'
    body += details(bi('问题覆盖、来源充分性与限制', 'Question coverage, source sufficiency & limitations'),
                    field_table({k: assessment.get(k) for k in ('requirements', 'source_checks', 'question_coverage', 'coverage_reason', 'missing_information', 'limitations')}))
    body += '<h3>' + bi('实际执行步骤', 'Recorded execution steps') + '</h3><p>' + bi('展开步骤查看已保存的工具输入、返回及反馈。这里回放历史，不重新执行工具。', 'Expand steps to inspect saved tool inputs, outputs and feedback. Replay does not execute tools.') + '</p>'
    step_rows = [[e(str(step['step'])), e(step['actor']) if step.get('actor') else bi('Data 主角色', 'Data lead'), e(step.get('action')), e(step.get('status')),
                  link(bi('查看输入与返回', 'Inspect input & output'), anchor='step-detail', dataset=data['id'], tab='runs', run=run['id'], step=str(step['step']))] for step in run['steps']]
    body += table([('步骤', 'Step'), ('执行角色', 'Actor'), ('动作', 'Action'), ('状态', 'Status'), ('详情', 'Detail')], step_rows)
    if args.get('step'):
        chosen = [s for s in run['steps'] if str(s['step']) == args['step']]
        if len(chosen) != 1:
            raise KeyError('Unknown run step')
        step = chosen[0]
        body += '<section class="ev-detail" id="step-detail"><h3>' + e(str(step['step']) + ' · ' + str(step.get('action') or '—')) + '</h3>'
        body += saved_json(('工具输入', 'Tool input'), step.get('decision')) + saved_json(('工具返回', 'Tool output'), step.get('result')) + saved_json(('反馈', 'Feedback'), step.get('feedback')) + '</section>'
    body += '<ul class="ev-note">' + ''.join('<li>' + e(x) + '</li>' for x in run.get('limitations', [])) + '</ul>'
    return body


def render_evaluation(root, query):
    if set(query) - PARAMS or any(not isinstance(v, list) or len(v) != 1 for v in query.values()):
        raise ValueError('Unknown or ambiguous evaluation selection')
    args = {k: v[0] for k, v in query.items()}
    if any(not isinstance(v, str) for v in args.values()) or len(args.get('q', '')) > 200:
        raise ValueError('Invalid evaluation filter')
    if any(not args[k].strip() for k in ('dataset', 'tab', 'record', 'block', 'run', 'step', 'kind', 'fact', 'return_run', 'return_kind', 'return_fact') if k in args):
        raise ValueError('Blank identity selection')
    args.setdefault('tab', 'materials')
    if args['tab'] not in TABS:
        raise KeyError('Unknown evaluation view')
    filters_by_tab = {'materials': {'source'}, 'blocks': {'source', 'block', 'q', 'type', 'offset', 'return_run', 'return_kind', 'return_fact'},
                      'records': {'source', 'record', 'q', 'metric', 'offset', 'run', 'kind', 'fact'}, 'runs': {'run', 'step'}}
    if set(query) - {'dataset', 'tab'} - filters_by_tab[args['tab']]:
        raise ValueError('Filter does not apply to selected evaluation view')
    raw_offset = args.get('offset', '0')
    if not str(raw_offset).isdigit():
        raise ValueError('Invalid page offset')
    args['offset'] = int(raw_offset)
    catalog = load_catalog(root)
    body = '<style>' + asset_text('dataset_view.css') + '\n' + asset_text('data_evaluation.css') + '</style><div class="ev-workspace"><header class="ev-heading"><h1>' + bi('数据评估', 'Data evaluation') + '</h1><p>' + bi('查看材料被解析成什么，以及每条数据的证据和核验。', 'Inspect parsed materials and the evidence and review behind each record.') + '</p></header><div class="ev-layout"><aside class="ev-datasets"><h2>' + bi('公司 / 数据版本', 'Company / dataset') + '</h2>'
    for item in catalog['datasets']:
        label = e(item['company_name']) + '<small>' + e(item.get('symbol')) + '</small>'
        body += '<div' + (' class="ev-active"' if item['id'] == args.get('dataset') else '') + '>' + link(label, dataset=item['id']) + '</div>'
    body += '<p>' + bi('名单来自已登记的冻结数据包，不改变持续研究名单。', 'This list comes from registered frozen datasets and does not change research coverage.') + '</p></aside><section class="ev-main">'
    if not args.get('dataset'):
        if set(query) - {'tab'}:
            raise ValueError('Explicit dataset selection required')
        body += '<p class="ev-empty">' + bi('先选择一个公司的数据版本。随后可以查看材料、解析块、数据库行和运行回放。', 'Select a company dataset first, then inspect materials, parsed blocks, database rows and run replay.') + '</p>'
    else:
        if args['dataset'] not in {d['id'] for d in catalog['datasets']}:
            raise KeyError('Unknown dataset')
        data = load_dataset(root, args['dataset'])
        if args['tab'] == 'records' and args.get('run'):
            if 'source' in args and not args['source'].strip():
                raise ValueError('Blank source for selected extraction run')
            if 'source' not in args:
                # Resolve only the caller's exact run, already bound to this
                # dataset manifest, issuer and immutable source by dataset_runs.
                matches = [r for r in dataset_runs(root, data)['runs'] if r['id'] == args['run']]
                if len(matches) != 1:
                    raise ValueError('Extraction run missing or ambiguous in selected dataset')
                args['source'] = matches[0]['source_snapshot_id']
        if args.get('source') and args['source'] not in {s['source_snapshot_id'] for s in data['sources']}:
            raise KeyError('Source outside selected dataset')
        if (args.get('block') and (args['tab'] != 'blocks' or not args.get('source'))) or (args.get('record') and args['tab'] != 'records') or (args.get('run') and args['tab'] not in {'runs', 'records'}) or (args.get('step') and not args.get('run')):
            raise ValueError('Object and view selection disagree')
        return_keys = {'return_run', 'return_kind', 'return_fact'}
        if return_keys & args.keys():
            if not return_keys <= args.keys() or args['return_kind'] not in {'reported', 'normalized'}:
                raise ValueError('Incomplete financial fact return selection')
            run = load_dataset_run(root, data, args['return_run'], args.get('source'))
            filename, key = ('extraction.json', 'draft_id') if args['return_kind'] == 'reported' else ('normalized.json', 'record_id')
            if len([r for r in run['artifacts'].get(filename, {}).get('records', []) if r.get(key) == args['return_fact']]) != 1:
                raise ValueError('Return candidate outside selected run')
        body += '<div class="ev-scope"><strong>' + e(data['company']['name']) + '</strong><span>' + e(data['company'].get('symbol')) + '</span>' + details(bi('数据版本', 'Dataset version'), field_table({key: data[key] for key in ('id', 'snapshot_id', 'manifest_sha256', 'status')})) + '</div><nav class="ev-tabs" aria-label="Evaluation views">'
        body += ''.join('<a href="' + e(href(dataset=data['id'], tab=key, source=args.get('source') if key != 'runs' else None)) + '"' + (' aria-current="page"' if args['tab'] == key else '') + '>' + bi(*label) + '</a>' for key, label in TABS.items()) + '</nav>'
        if args['tab'] == 'materials': body += materials(data, root, args)
        elif args['tab'] == 'blocks': body += blocks_view(data, args)
        elif args['tab'] == 'records': body += records_view(data, args, catalog, root)
        else: body += runs_view(data, args, catalog, root)
    from apps.review_workbench.pages.data_workspace import url as workspace_url
    target = workspace_url(dataset=args.get('dataset'), source=args.get('source'))
    body += '<p><a href="' + e(target) + '">' + bi('在新数据工作台查看', 'Open in the new data workspace') + '</a></p>'
    return page('数据评估', body + '</section></div></div>')
