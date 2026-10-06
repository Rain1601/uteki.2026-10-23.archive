"""Shared, read-only matrices and source drilldown for extraction candidates."""
import json
from collections import OrderedDict
from urllib.parse import urlencode

from apps.review_workbench.components.site_navigation import bi, e
from apps.review_workbench.pages.data_evaluation import saved_json, table, details, verdict
from apps.review_workbench.pages.dataset_view import field_table, render_block


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def fact_url(run, context, kind=None, fact=None):
    values = dict(context or {})
    values.update(run=run['id'])
    if context:
        values['tab'] = 'records'
    if kind is not None:
        values.update(kind=kind, fact=fact)
    return ('/evaluation' if context else '/extractions') + '?' + urlencode(
        {k: v for k, v in values.items() if v is not None and v != ''})


def _bound_review(run):
    review = run.get('review')
    if not isinstance(review, dict) or any(review.get(k) != run[k] for k in ('company_id', 'source_snapshot_id')) or review.get('run_id') != run['id']:
        return None
    if review.get('source_sha256', run['source_sha256']) != run['source_sha256']:
        return None
    return review


def _review(run, kind, row):
    review = _bound_review(run)
    facts = review.get('facts', []) if isinstance(review, dict) else []
    key = 'draft_id' if kind == 'reported' else 'record_id'
    found = [f for f in facts if isinstance(f, dict) and row.get(key) and f.get(key) == row[key]]
    return found[0] if len(found) == 1 else None


def _review_findings(run, context, dataset):
    review = _bound_review(run)
    if review is None:
        return ''
    negative = {'incorrect', 'insufficient', 'contradicted', 'needs_evidence', 'needs_revision', 'insufficient_evidence', 'unsupported'}
    groups = [('coverage', ('覆盖审核', 'Coverage review'), review.get('coverage_findings', [])),
              ('relations', ('关系核验问题', 'Relation review issues'),
               [item for item in review.get('relations', []) if item.get('verdict') in negative])]
    labels = {'incorrect': ('不正确', 'Incorrect'), 'insufficient': ('不足', 'Insufficient'),
              'needs_evidence': ('需补证据', 'Needs evidence'), 'unsupported': ('缺少支持', 'Unsupported')}
    body = ''
    for identity, label, findings in groups:
        if not findings:
            continue
        body += '<section class="ev-review-findings" data-review-section="' + identity + '"><h3>' + bi(*label) + '</h3><ul>'
        for finding in findings:
            state = finding.get('verdict')
            status = bi(*labels[state]) if state in labels else verdict(state) if state else bi('覆盖说明', 'Coverage note')
            key = finding.get('id') or finding.get('relation_id')
            body += '<li data-review-finding="' + e(key) + '"><strong>' + status + '</strong><p>' + e(finding.get('rationale', '')) + '</p>'
            if dataset and context:
                valid_blocks = {b['block_id'] for b in dataset['blocks'][run['source_snapshot_id']]}
                for bid in finding.get('source_block_ids', []):
                    if bid in valid_blocks:
                        url = '/evaluation?' + urlencode({'dataset': context['dataset'], 'tab': 'blocks', 'source': run['source_snapshot_id'], 'block': bid}) + '#block-detail'
                        body += '<a href="' + e(url) + '">' + e(bid) + '</a> '
            body += details(bi('查看这项核验的字段', 'Inspect this finding’s fields'), field_table(finding)) + '</li>'
        body += '</ul></section>'
    return body


def _status(run, kind, row):
    found = _review(run, kind, row)
    labels = {'value_scope_matched': ('金额/期间核对匹配', 'Value / period matched'),
              'needs_evidence': ('需补证据', 'Needs evidence'), 'not_reviewed': ('未核验', 'Not reviewed')}
    value = found.get('verdict') if found else None
    return bi(*labels[value]) if value in labels else verdict(value) if found else bi('未登记逐条审核', 'No per-fact review')


def _period(row, kind, run):
    if kind == 'normalized':
        value = row.get('period')
        if isinstance(value, dict):
            label = (str(value['start']) + ' — ' if value.get('start') else '') + str(value.get('end', ''))
            label += '\n' + ' / '.join(str(value[k]) for k in ('kind', 'basis') if value.get(k))
            return _json(value), label, value
        return _json(value), '期间未解析 / Unresolved period', value
    periods = {p['period_id']: p.get('period') for p in run['artifacts'].get('packet.json', {}).get('period_catalog', [])}
    value = periods.get(row.get('period_id'))
    label = row.get('period') or '期间未解析 / Unresolved period'
    if isinstance(value, dict):
        label += '\n' + (str(value['start']) + ' — ' if value.get('start') else '') + str(value.get('end', ''))
    # Preserve the model's declared period even if it disagrees with a selected ID.
    return _json([row.get('period_id'), row.get('period'), value]), label, value


def _matrix(run, kind, rows, context):
    if not rows:
        return '<p class="ev-empty">' + bi('本次没有这一层的候选记录。', 'This run has no candidates at this layer.') + '</p>'
    groups, periods = OrderedDict(), OrderedDict()
    for row in rows:
        identity = {key: row.get(key) for key in ('entity_id', 'entity', 'metric_id', 'metric', 'unit',
            'accounting_basis', 'dimensions', 'denominator', 'value_kind', 'kind', 'speaker', 'value_relation')}
        group = groups.setdefault(_json(identity), {'scope': identity, 'cells': {}})
        pkey, plabel, _ = _period(row, kind, run)
        periods.setdefault(pkey, plabel)
        group['cells'].setdefault(pkey, []).append(row)
    body = '<div class="ev-scroll ev-financial-matrix"><table><thead><tr><th>' + bi('指标 / 口径', 'Metric / scope') + '</th>'
    body += ''.join('<th title="' + e(key) + '">' + e(label) + '</th>' for key, label in periods.items()) + '</tr></thead><tbody>'
    for group in groups.values():
        scope = group['scope']
        label = scope.get('metric') or scope.get('metric_id') or '未解析指标 / Unresolved metric'
        meta = [scope.get('entity') or scope.get('entity_id'), scope.get('unit'), scope.get('accounting_basis')]
        if scope.get('dimensions'):
            meta.append(_json(scope['dimensions']))
        if scope.get('denominator'):
            meta.append(scope['denominator'])
        body += '<tr data-scope="' + e(_json(scope)) + '"><th scope="row">' + e(label) + '<small>' + e(' / '.join(str(v or '未明确 / Unspecified') for v in meta)) + '</small></th>'
        for pkey in periods:
            body += '<td>'
            candidates = group['cells'].get(pkey, [])
            if not candidates:
                body += '<span class="ev-note">' + bi('无候选', 'No candidate') + '</span>'
            for row in candidates:
                identity = row.get('draft_id' if kind == 'reported' else 'record_id')
                value = row.get('value' if kind == 'reported' else 'value_decimal')
                upper = row.get('upper' if kind == 'reported' else 'upper_decimal')
                display = str(value) if value is not None else '未解析 / Unresolved'
                display = {'gt': '> ', 'gte': '≥ ', 'approx': '≈ '}.get(row.get('value_relation'), '') + display
                if upper is not None:
                    display += ' – ' + str(upper)
                body += '<div class="ev-fact-cell"><a href="' + e(fact_url(run, context, kind, identity) + '#fact-detail') + '" data-fact-id="' + e(identity) + '">' + e(display) + '</a><small>' + _status(run, kind, row) + '</small></div>'
            body += '</td>'
        body += '</tr>'
    return body + '</tbody></table></div>'


def _detail(run, kind, row, context, dataset):
    key = 'draft_id' if kind == 'reported' else 'record_id'
    normalized = run['artifacts'].get('normalized.json', {})
    draft_id = row.get('draft_id') if kind == 'reported' else row.get('origin', {}).get('draft_id')
    unresolved = [item for item in normalized.get('unresolved', []) if item.get('draft_id') == draft_id]
    body = '<section class="ev-detail" id="fact-detail"><p><a href="' + e(fact_url(run, context) + '#financial-facts') + '">' + bi('返回所选运行的事实表', 'Back to this run’s fact tables') + '</a></p><h3>' + e(row.get('metric') or row.get('metric_id') or row.get(key)) + '</h3>'
    body += '<p>' + bi('模型原文候选', 'Reported model candidate') if kind == 'reported' else '<p>' + bi('规范化候选', 'Normalized candidate')
    body += ' · ' + _status(run, kind, row) + '</p>'
    body += field_table({k: row.get(k) for k in (key, 'entity', 'entity_id', 'metric', 'metric_id', 'period', 'period_id',
        'value', 'value_decimal', 'upper', 'upper_decimal', 'value_relation', 'unit', 'accounting_basis', 'dimensions', 'status') if k in row})
    _, _, actual_period = _period(row, kind, run)
    if actual_period is not None:
        body += details(bi('选择的实际期间', 'Selected exact period'), field_table(actual_period))
    if kind == 'normalized':
        body += saved_json(('转换前的模型候选', 'Model candidate before conversion'), row.get('origin', {}).get('raw'))
    body += '<h3>' + bi('程序处理与未解决项', 'Processing & unresolved items') + '</h3>'
    if unresolved:
        body += table([('原因', 'Reason'), ('具体内容', 'Details')], [[e(item.get('reason')), e(_json(item))] for item in unresolved])
    elif kind == 'reported':
        mapped = [r for r in normalized.get('records', []) if r.get('origin', {}).get('draft_id') == draft_id]
        body += '<p>' + (bi('已有规范化候选；仍需独立内容审核。', 'A normalized candidate exists; independent content review is still required.') if mapped else
                        bi('没有可关联的规范化候选，也没有这条草稿的已保存诊断。', 'No associated normalized candidate or saved per-draft diagnostic.')) + '</p>'
    else:
        body += '<p>' + bi('程序检查与单位转换已形成候选，不代表财务语义已审核。', 'Program checks and unit conversion produced a candidate; financial semantics are not thereby approved.') + '</p>'
    body += saved_json(('模型标记的未明确字段', 'Model-declared unresolved fields'), row.get('unresolved_fields', [])) if kind == 'reported' else ''
    review = _review(run, kind, row)
    if review:
        body += '<h3>' + bi('这一条的核对意见', 'Review of this value') + '</h3><p>' + _status(run, kind, row) + '</p>'
        body += '<p>' + e(review.get('rationale') or '') + '</p>'
        body += saved_json(('完整审核记录', 'Complete review record'), review)
    else:
        body += '<p>' + bi('未登记这一条的独立审核结论。', 'No independent verdict is registered for this candidate.') + '</p>'
    body += '<h3>' + bi('原文证据与原表', 'Source evidence & original table') + '</h3>'
    if kind == 'reported':
        refs = [{'role': role, **ref} for role in ('evidence', 'qualifiers') for ref in row.get(role, [])]
    else:
        refs = [normalized['evidence'][eid] for key in ('evidence_ids', 'qualifier_evidence_ids', 'question_evidence_ids') for eid in row.get(key, [])]
    blocks = {b['block_id']: b for b in (dataset['blocks'][run['source_snapshot_id']] if dataset else run['blocks'])}
    shown = set()
    for ref in refs:
        bid, quote = ref.get('block_id'), ref.get('quote', '')
        block = blocks.get(bid)
        found = bool(block and quote and quote in block['text'])
        body += '<blockquote>' + e(quote) + '</blockquote><p>' + e(bid) + ' · ' + (bi('引文字符匹配，语义仍待审核', 'Quote text matches; semantics need review') if found else bi('引文未在所选原文块中匹配', 'Quote does not match the selected source block')) + '</p>'
        if block is not None and bid not in shown:
            if context:
                destination = '/evaluation?' + urlencode({'dataset': context['dataset'], 'tab': 'blocks', 'source': run['source_snapshot_id'], 'block': bid,
                    'return_run': run['id'], 'return_kind': kind, 'return_fact': row[key]}) + '#block-detail'
                body += '<p><a href="' + e(destination) + '">' + bi('在原文结构中定位', 'Locate in source structure') + '</a></p>'
            body += details(bi('展开完整原文块 / 表格', 'Expand complete source block / table'), render_block(block), opened=True)
            shown.add(bid)
    if not refs:
        body += '<p>' + bi('此候选没有原文引用。', 'This candidate has no source references.') + '</p>'
    body += saved_json(('候选的完整字段', 'Complete candidate fields'), row)
    return body + '</section>'


def render_fact_matrices(run, *, context=None, dataset=None, kind=None, fact=None):
    if bool(kind) != bool(fact) or (kind and kind not in {'reported', 'normalized'}):
        raise ValueError('Select a reported or normalized candidate explicitly')
    artifacts = run['artifacts']
    reported = artifacts.get('extraction.json', {}).get('records', [])
    normalized = artifacts.get('normalized.json', {}).get('records', [])
    body = '<section id="financial-facts"><h2>' + bi('财务事实候选', 'Financial fact candidates') + '</h2><p>' + bi(
        '原文候选是模型依据材料提出的值；规范化候选经过明确的单位转换。两者都需内容审核，程序通过不等于已采纳。',
        'Reported drafts are model-proposed source values; normalized candidates use explicit unit conversion. Both need content review. Program checks do not constitute adoption.') + '</p>'
    body += '<p>' + bi('当前运行：', 'Selected run: ') + e(run['id']) + ' · ' + bi('执行状态：', 'Execution status: ') + e(artifacts.get('result.json', {}).get('status', 'not_saved')) + '</p>'
    body += '<p class="ev-note">' + bi(f'本次输入 {len(run["blocks"])} 个原文块；候选只对应本次选取范围，不代表整份财报已完成。',
        f'This run received {len(run["blocks"])} source blocks. Candidates cover this selection, not an implied complete filing.') + '</p>'
    body += saved_json(('本次任务与范围', 'Task & scope of this run'), artifacts.get('packet.json', {}).get('task'))
    if fact:
        rows = reported if kind == 'reported' else normalized
        key = 'draft_id' if kind == 'reported' else 'record_id'
        matches = [row for row in rows if row.get(key) == fact]
        if len(matches) != 1:
            raise ValueError('Candidate is missing or ambiguous in selected run/layer')
        body += _detail(run, kind, matches[0], context, dataset)
    body += '<h3>' + bi(f'模型原文候选（{len(reported)}）', f'Reported model drafts ({len(reported)})') + '</h3>'
    body += _matrix(run, 'reported', reported, context)
    body += '<h3>' + bi(f'规范化候选（{len(normalized)}）', f'Normalized candidates ({len(normalized)})') + '</h3>'
    body += '<p>' + (bi(f'数据库已核对：{len(run["db_rows"])} 条 payload 与规范化候选一致。', f'Database checked: {len(run["db_rows"])} payloads match normalized candidates.')
                     if run['db_check'] == 'payload_matches_normalized' else bi('本次未提供可核对的数据库产物。', 'No database artifact is available for verification in this run.')) + '</p>'
    body += _matrix(run, 'normalized', normalized, context)
    body += _review_findings(run, context, dataset)
    body += saved_json(('本次全部未解决项', 'All unresolved items in this run'), artifacts.get('normalized.json', {}).get('unresolved', []))
    body += saved_json(('模型报告的覆盖缺口', 'Model-reported coverage gaps'), artifacts.get('extraction.json', {}).get('gaps', []))
    return body + '</section>'
