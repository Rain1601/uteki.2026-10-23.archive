"""Inspection only: no agent execution, edits, or adoption actions."""
from urllib.parse import urlencode

from apps.review_workbench.assets import asset_text
from apps.review_workbench.components.site_navigation import bi, page, e
from apps.review_workbench.data.direct_extraction_views import load_catalog, load_run
from apps.review_workbench.pages.data_evaluation import saved_json, table, select_control, details
from apps.review_workbench.pages.dataset_view import render_block
from apps.review_workbench.pages.extraction_facts import render_fact_matrices


def processing_record(run, *, root=None):
    """Readable saved inputs and outputs, without inventing an execution trace."""
    artifacts = run['artifacts']
    packet, job = artifacts.get('packet.json', {}), artifacts.get('job.json', {})
    result = artifacts.get('result.json', {})
    blocks = packet.get('blocks', [])
    task = job.get('task')
    if not isinstance(task, str):
        task = ''
    body = '<section id="processing-record"><h2>' + bi('这次处理做了什么', 'What this extraction did') + '</h2>'
    parent_id = None
    if root is not None:
        from apps.review_workbench.data.agent_runs import parent_for_extraction
        try:
            parent_id = parent_for_extraction(root, run)
        except (OSError, ValueError, KeyError):
            # A missing parent cannot invalidate this separately verified extraction.
            pass
    if parent_id:
        body += '<p class="ev-note">' + bi('这里展示提取步骤保存的输入与输出。完整主运行包含计划、拒绝步骤、子任务和用量。',
            'This view shows saved extraction inputs and outputs. The parent run includes plans, rejected steps, child tasks and usage.')
        body += ' <a href="/agent-results?' + e(urlencode({'agent': 'data', 'run': parent_id})) + '">' + bi('查看运行结果与评分', 'View result & scores') + '</a> · <a href="/agent-runs?' + e(urlencode({'agent': 'data', 'run': parent_id})) + '">Trace ID: ' + e(parent_id) + '</a></p>'
    else:
        body += '<p class="ev-note">' + bi('以下内容来自这次运行保存的文件。这里展示提取步骤的输入与输出；尚无已验证的主运行关联。',
            'These are saved extraction inputs and outputs; a verified parent run association is not available.') + '</p>'
    body += '<h3>' + bi('1. 收到什么任务与材料', '1. Task and source input') + '</h3>'
    body += '<p class="ev-question">' + (e(task) if task else bi('未保存可读任务说明。', 'No readable task instruction was saved.')) + '</p>'
    if 'packet.json' in artifacts:
        body += '<p>' + bi(f'本次实际输入 {len(blocks)} 段原文或表格，只代表本次选择的范围。',
            f'This extraction received {len(blocks)} source passages or tables, covering only this selected scope.') + '</p>'
        for position, block in enumerate(blocks, 1):
            title = bi(f'输入 {position}：', f'Input {position}: ') + e(block.get('type', ''))
            content = render_block(block) if block.get('type') else '<p>' + e(block.get('text', '')) + '</p>'
            body += details(title, content)
    else:
        body += '<p>' + bi('输入材料未保存，无法回看。', 'The input packet was not saved and cannot be inspected.') + '</p>'
    body += '<h3>' + bi('2. 使用什么模型和提取方法', '2. Model and extraction method') + '</h3>'
    usage = result.get('usage', {}).get('summary', {})
    model = ' / '.join(str(usage[k]) for k in ('provider', 'model', 'reasoning_effort') if usage.get(k))
    body += '<p>' + bi('模型：', 'Model: ') + (e(model) if model else bi('未保存配置', 'Configuration not saved')) + '</p>'
    prompt = artifacts.get('prompt.json', {})
    body += '<p>' + bi('方法版本：', 'Method version: ') + e(prompt.get('version') or '—') + '</p>'
    effective = artifacts.get('system-prompt-effective.json', {}).get('text')
    if isinstance(effective, str):
        body += details(bi('阅读实际发送的 System Prompt / Skill', 'Read the effective System Prompt / Skill'),
            '<pre>' + e(effective) + '</pre>')
    else:
        body += '<p>' + bi('本次未保存完整有效提示词；不能从配置名称还原实际输入。',
            'The effective prompt was not saved; its contents cannot be reconstructed from a configuration name.') + '</p>'
    body += '<h3>' + bi('3. 产生什么结果', '3. Saved output') + '</h3>'
    if 'extraction.json' in artifacts:
        body += '<p>' + bi(f'模型提取 {len(artifacts["extraction.json"].get("records", []))} 条原文候选。',
            f'The model returned {len(artifacts["extraction.json"].get("records", []))} source candidates.') + '</p>'
    else:
        body += '<p>' + bi('本次没有保存提取结果。', 'No extraction output was saved for this run.') + '</p>'
    if run.get('db_check') == 'payload_matches_normalized':
        body += '<p>' + bi(f'已核对数据库中的 {len(run["db_rows"])} 条候选记录。',
            f'{len(run["db_rows"])} candidate database records were checked.') + '</p>'
    else:
        body += '<p>' + bi('本次未保存可核对的数据库产物。', 'No inspectable database artifact was saved for this run.') + '</p>'
    body += '<p><a href="#financial-facts">' + bi('查看下方财务数据，点击数值核对原文',
        'Inspect the financial data below; click a value to check its source') + '</a></p>'
    body += '<h3>' + bi('4. 还有哪些问题', '4. Open issues') + '</h3>'
    if result.get('error'):
        body += '<p>' + bi('运行失败：', 'Run failed: ') + e(result['error']) + '</p>'
    normalized = artifacts.get('normalized.json')
    if normalized is None:
        body += '<p>' + bi('未保存规范化检查，不能判断是否存在入库问题。',
            'Normalization checks were not saved; database readiness is unknown.') + '</p>'
    else:
        issues = normalized.get('unresolved', [])
        body += '<p>' + bi(f'程序记录了 {len(issues)} 项未解决事项；这不是缺失指标总数。',
            f'The program recorded {len(issues)} unresolved items; this is not the number of missing metrics.') + '</p>'
    gaps = artifacts.get('extraction.json', {}).get('gaps', [])
    if gaps:
        body += details(bi('模型报告的范围与缺口', 'Scope and gaps reported by the model'),
            '<ul>' + ''.join('<li>' + e(gap) + '</li>' for gap in gaps) + '</ul>')
    body += '<p>' + (bi('已有独立审核；具体意见随下方每条数据展示。',
        'An independent review is saved; findings appear with the financial facts below.') if run.get('review') is not None
        else bi('尚无已登记的独立审核。', 'No independent review has been registered.')) + '</p>'
    body += '<p class="ev-note">' + bi('候选结果保留原状态，尚未因本页展示而被采纳。原始文件、字段和校验详情在页面底部展开查看。',
        'Candidates retain their saved status; displaying them does not adopt them. Expand the raw artifacts and checks at the bottom for details.') + '</p>'
    return body + '</section>'


def render_direct_extractions(root, selection):
    if set(selection) - {'run', 'company', 'source', 'kind', 'fact'} or any(len(v) != 1 for v in selection.values()):
        raise ValueError('Only one registered run/company/source selection is allowed')
    args = {k: v[0] for k, v in selection.items()}
    if any(not args[k].strip() for k in ('run', 'kind', 'fact') if k in args) or ((args.get('kind') or args.get('fact')) and not args.get('run')):
        raise ValueError('Explicit run and candidate selection required')
    catalog = load_catalog(root)
    def finish(body):
        return page('财报抽取验收', '<div class="ev-workspace">' + body + '</div>')
    body = '<style>' + asset_text('data_evaluation.css') + '</style><h1>' + bi('财报抽取验收', 'Financial extraction inspection') + '</h1>'
    body += '<p>' + bi('内部只读验收。候选记录尚未采纳；完整性校验不代表财务语义正确。',
                      'Internal read-only inspection. Candidates are not adopted; integrity checks do not establish semantic correctness.') + '</p>'
    if not catalog:
        return finish(body + '<p class="workspace-empty">' + bi('尚未登记真实抽取运行。运行冻结并登记后，产物将在这里显示。',
                      'No real extraction run is registered. Frozen, registered artifacts will appear here.') + '</p>')
    body += '<form method="get" action="/extractions" class="ev-filters">'
    for key, label in (('company', ('公司', 'Company')), ('source', ('来源', 'Source'))):
        field = 'company_id' if key == 'company' else 'source_snapshot_id'
        choices = sorted({r[field] for r in catalog if r[field]})
        if args.get(key) and args[key] not in choices:
            raise ValueError('Unknown registered ' + key)
        body += select_control(key, label, [(v, v) for v in choices], args.get(key, ''), all_label='全部 / All')
    body += '<button type="submit">' + bi('筛选', 'Filter') + '</button></form>'
    visible = [r for r in catalog if (not args.get('company') or args['company'] == r['company_id']) and
               (not args.get('source') or args['source'] == r['source_snapshot_id'])]
    body += table([('运行', 'Run'), ('公司 / 财年末', 'Company / Fiscal end'), ('材料', 'Source'), ('文件校验', 'Integrity')],
        [['<a href="/extractions?' + e(urlencode({**args, 'run': r['id']})) + '">' + e(r['id']) + '</a>',
          e(r['company_id'] + ' / ' + str(r['period_end'])), e(r['source_snapshot_id']),
          e(r['integrity']) + (' / ' + bi('部分产物缺失', 'Some artifacts missing') if r['missing'] else '')] for r in visible])
    if not args.get('run'):
        return finish(body + '<p>' + bi('选择一次运行查看产物。', 'Select a run to inspect its artifacts.') + '</p>')
    if args['run'] not in {r['id'] for r in visible}:
        raise ValueError('Selected run is outside the selected company/source')
    run = load_run(root, args['run'])
    artifacts = run['artifacts']
    body += '<h2>' + e(run['id']) + '</h2>'
    result = artifacts.get('result.json', {})
    states = {'candidate': ('已产出候选', 'Candidate output saved'), 'failed': ('运行失败', 'Run failed')}
    status = result.get('status')
    body += '<p>' + bi('执行状态：', 'Execution status: ') + (bi(*states[status]) if status in states else e(status or '—')) + '</p>'
    if run['missing']:
        body += '<p>' + bi('本次未保存：', 'Not saved: ') + e(', '.join(run['missing'])) + '</p>'
    body += processing_record(run, root=root)
    body += render_fact_matrices(run, kind=args.get('kind'), fact=args.get('fact'))
    body += saved_json(('身份、完整性与缺口', 'Identity, integrity & gaps'), {k: run[k] for k in
        ('company_id', 'source_snapshot_id', 'period_end', 'scope_status', 'source_check', 'manifest_sha256', 'missing', 'db_check')})
    if run['parent_run_id']:
        parent = run['parent_run_id']
        body += '<p>' + bi('父运行：', 'Parent run: ') + (('<a href="/extractions?' + e(urlencode({'run': parent})) + '">' + e(parent) + '</a>')
                  if parent in {r['id'] for r in catalog} else e(parent) + ' (' + bi('未登记', 'Not registered') + ')') + '</p>'
    labels = {'result.json': ('执行结果', 'Execution result'), 'job.json': ('任务', 'Job'),
              'prompt.json': ('提取提示词与版本', 'Extraction prompt & version'), 'system-prompt-effective.json': ('实际系统提示词', 'Effective system prompt'),
              'packet.json': ('输入材料与选择的原文块', 'Input packet & selected source blocks'),
              'extraction.json': ('原始抽取草稿（含未入库项）', 'Original draft (including unstored items)'),
              'normalized.json': ('规范化记录、未解决项与校验', 'Normalized records, unresolved items & validation')}
    for filename, label in labels.items():
        if filename in artifacts:
            body += saved_json(label, artifacts[filename])
        else:
            body += '<p>' + bi(*label) + ': ' + bi('本次运行未保存', 'Not saved in this run') + '</p>'
    body += saved_json(('数据库实际记录', 'Actual database payloads'), {'check': run['db_check'], 'rows': run['db_rows']})
    body += saved_json(('全部草稿的引用上下文（含未入库项）', 'Evidence contexts for all drafts (including unstored items)'), run['draft_contexts'])
    for evidence in run['evidence_checks']:
        body += saved_json(('原文引用与上下文 ' + evidence['evidence_id'], 'Quote & context ' + evidence['evidence_id']), evidence)
    body += saved_json(('Codex 独立审核', 'Independent Codex review'), run['review']) if run['review'] is not None else '<p>' + bi('尚未登记 Codex 独立审核。', 'No independent Codex review is registered.') + '</p>'
    return finish(body)
