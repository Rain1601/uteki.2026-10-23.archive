"""Read an independent assessment before its logs; offline, immutable delivery."""
from decimal import Decimal
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .data_review_delivery import _STYLE


_LABELS = {'pass': '固定标准通过 / Benchmark pass', 'fail': '固定标准未通过 / Benchmark fail',
           'unassessed': '未完成评审 / Unassessed', 'supported': '足够支持 / Supported',
           'partial': '部分支持 / Partial', 'missing': '缺失 / Missing'}
_CATEGORIES = {'required': '必需材料', 'optional': '可选材料', 'necessary_context': '必要上下文',
               'duplicate': '重复', 'irrelevant': '无关', 'unassessed': '未判定', 'table_structure': '原表附带内容'}
_LAYOUT = '''html,body{height:100%;overflow:hidden}body{display:flex;flex-direction:column}
header{padding:12px 24px;border-bottom:1px solid #e4dfd5;background:#fff}header p{margin:0}
.workspace{display:flex;flex:1;min-height:0}nav{width:220px;flex-shrink:0;padding:20px 16px;overflow:auto;border-right:1px solid #e4dfd5}
nav a{display:block;padding:8px;border-radius:6px;text-decoration:none}nav a:hover{background:#eeeae2}
main{overflow:auto;flex:1;min-width:0;width:100%;scroll-behavior:auto;padding:24px;box-sizing:border-box}
.case{max-width:960px;margin:0 auto 32px}.question{font-size:20px;font-weight:600}.verdict{font-weight:600}
.fail{color:#9a3e31}.pass{color:#35644a}.draft,.unassessed{color:#805f2c}.reading{max-width:800px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair section{margin:0}.stats{display:flex;gap:24px;flex-wrap:wrap}
.stats strong{display:block;font-size:22px;font-variant-numeric:tabular-nums}blockquote{margin:12px 0;border-left:2px solid #e4dfd5;padding:4px 16px;white-space:pre-wrap}
td{vertical-align:top}details{margin:16px 0}summary{padding:8px 0}li{margin:6px 0}a:focus-visible,summary:focus-visible{outline:2px solid #a45e3c;outline-offset:3px}
@media(max-width:720px){nav{width:140px;padding:12px 8px}main{padding:16px}.pair{grid-template-columns:1fr}}'''


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _need(isinstance(value, str) and value.strip(), 'explicit nonblank text required')
    return escape(value, quote=True)


def _url(value):
    _need(isinstance(value, str) and value.strip() == value and bool(value), 'explicit URL required')
    decoded = value
    for _ in range(3):
        _need(not any(ord(c) < 32 or ord(c) == 127 for c in decoded) and '\\' not in decoded,
              'control characters and backslashes are not allowed in links')
        parsed = urlsplit(decoded)
        _need(not parsed.username and not parsed.password, 'URL credentials are not allowed')
        if parsed.scheme:
            _need(parsed.scheme in {'http', 'https'} and bool(parsed.hostname), 'unsupported link protocol')
        else:
            _need(not parsed.netloc and not decoded.startswith('//'), 'protocol-relative links are not allowed')
        decoded = unquote(decoded)
    return escape(value, quote=True)


def _link(item):
    return '<a href="' + _url(item['url']) + '">' + _text(item['label']) + '</a>'


def _list(items, empty):
    _need(isinstance(items, list), 'explicit list required')
    return ('<ul>' + ''.join('<li>' + _text(item) + '</li>' for item in items) + '</ul>') if items else '<p class="muted">' + escape(empty) + '</p>'


def _hash(value, nullable=False):
    if value is None and nullable:
        return '未登记 / Not recorded'
    _need(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value), 'explicit SHA256 required')
    return value


def _money(value):
    _need(isinstance(value, str), 'decimal cost string required')
    number = Decimal(value)
    _need(number.is_finite() and number >= 0, 'finite nonnegative cost required')
    return '$' + format(number, '.4f')


def render_page(document):
    """Render recorded judgments, without claiming to reverify source semantics.

    Gold and run hashes are displayed bindings supplied by the caller. This
    renderer does not load those artifacts or verify arbitrary external links.
    """
    _need(document.get('schema_version') == 'evidence-benchmark-page-v1', 'unsupported page schema')
    title, introduction = _text(document.get('title')), _text(document.get('introduction'))
    cases = document.get('cases')
    _need(isinstance(cases, list) and cases, 'nonempty cases required')
    ids, navigation, sections = set(), [], []
    for case in cases:
        cid = case.get('case_id')
        _need(isinstance(cid, str) and re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}', cid) and cid not in ids,
              'unique safe case ID required')
        ids.add(cid)
        draft = case.get('status') == 'draft'
        _need(case.get('status') in {'draft', 'finished'}, 'explicit draft/finished state required')
        question = _text(case.get('question'))
        gold_hash = _hash(case.get('gold_sha256'))
        run_hash = _hash(case.get('run_sha256'), nullable=draft)
        review, score = case.get('review'), case.get('score')
        if not draft:
            _need(isinstance(review, dict) and isinstance(score, dict), 'finished case needs review and score')
        if review is not None:
            _need(review.get('schema_version') == 'evidence-review-v1' and review.get('case_id') == cid
                  and review.get('question') == case['question'], 'review identity mismatch')
        status = 'draft'
        if score is not None:
            _need(score.get('schema_version') == 'evidence-score-v1' and score.get('case_id') == cid,
                  'score identity mismatch')
            _need(score.get('status') in {'pass', 'fail', 'unassessed'}, 'invalid score state')
            gates = score.get('gates', {})
            _need(set(gates) == {'scope', 'truth', 'provenance', 'focus', 'required_coverage', 'all_characters_assessed'}
                  and all(v in {'pass', 'fail', 'unassessed'} for v in gates.values()), 'complete score gates required')
            expected = 'fail' if 'fail' in gates.values() else 'unassessed' if 'unassessed' in gates.values() else 'pass'
            _need(score['status'] == expected, 'score verdict conflicts with hard gates')
            if not draft:
                status = score['status']
        label = '评审草稿 · 未验收 / Draft' if draft else _LABELS[status]
        navigation.append('<a href="#' + cid + '">' + escape(cid) + '<br><small>' + label + '</small></a>')
        requirements = case.get('required')
        _need(isinstance(requirements, list) and requirements, 'required explanation rows needed')
        rows, required_ids = [], set()
        assessments = {r['id']: r for r in (review or {}).get('requirements', [])}
        for requirement in requirements:
            rid = requirement.get('id')
            _need(isinstance(rid, str) and rid.strip() and rid not in required_ids, 'unique required ID needed')
            required_ids.add(rid)
            assessment = assessments.get(rid)
            judgment = '尚未评审 / Pending' if draft or assessment is None else _LABELS[assessment['status']]
            reason = '' if draft or assessment is None else '<br><span class="muted">' + _text(assessment['reason']) + '</span>'
            rows.append('<tr><td>' + _text(rid) + '</td><td>' + _text(requirement['description']) + '</td><td>' + judgment + reason + '</td></tr>')
        if not draft:
            _need(set(assessments) == required_ids, 'required explanations differ from assessed requirements')
            _need(all(review.get('checks', {}).get(key, {}).get('status') == score['gates'][key]
                      for key in ('scope', 'truth', 'provenance', 'focus')), 'score differs from review gates')
        narrative = ''.join('<section><h3>' + heading + '</h3><p class="reading">' + _text(case.get(field)) + '</p></section>'
                            for field, heading in [('provided_explanation', 'Agent 提供了什么 / Delivered'),
                                                   ('coverage_explanation', '够回答哪些内容 / Sufficiency')])
        missing, extra = _list(case.get('missing'), '未列出缺失；草稿状态不表示已确认齐全。' if draft else '本次评审未发现必需材料缺失。'), _list(case.get('extra'), '未登记；仍需逐项核对。' if draft else '本次评审未列出额外材料。')
        stats = '<p class="muted">尚未完成统计或费用核对 / Metrics pending</p>'
        if score is not None:
            coverage, chars, costs = score['required_coverage'], score['characters'], score['cost']
            n, d = coverage['numerator'], coverage['denominator']
            _need(type(n) is int and type(d) is int and 0 <= n <= d and d == len(required_ids), 'coverage denominator mismatch')
            _need(score['gates']['required_coverage'] == ('pass' if n == d else 'fail'), 'coverage gate differs from counts')
            if review is not None:
                _need(n == sum(row.get('status') == 'supported' for row in assessments.values()), 'coverage differs from review')
            known, held = _money(costs['known_estimated_usd']), _money(costs['unknown_reserved_usd'])
            stats = '<div class="stats"><div>必需项完整覆盖<strong>' + str(n) + ' / ' + str(d) + '</strong></div><div>已知费用估算<strong>' + known + '</strong></div><div>未知费用预留<strong>' + held + '</strong></div></div>'
            stats += '<p class="muted">费用是本地估算，不是供应商实际账单。固定标准通过不代表已达到最小材料或稳定性目标；请同时看“多了什么”和判断边界。草稿统计不构成验收。</p><details><summary>材料量与判定口径 / Material accounting</summary><table><thead><tr><th>类型</th><th>去重字符数 / 占比</th></tr></thead><tbody>'
            character_sum, unique_total = 0, chars['unique_source_characters']
            _need(type(unique_total) is int and unique_total >= 0, 'invalid unique character total')
            for category, name in _CATEGORIES.items():
                metric = chars['categories'][category]
                amount, total = metric['numerator'], metric['denominator']
                _need(type(amount) is int and type(total) is int and 0 <= amount <= total, 'invalid character metric')
                _need(total == unique_total, 'character denominators differ')
                character_sum += amount
                share = f'{amount / total:.1%}' if total else '—'
                stats += '<tr><td>' + name + '</td><td>' + str(amount) + ' / ' + share + '</td></tr>'
            _need(character_sum == unique_total, 'character categories do not cover total')
            repeated = chars['repeated_location_occurrences']
            _need(type(repeated) is int and repeated >= 0, 'invalid repeated character count')
            _need(score['gates']['all_characters_assessed'] ==
                  ('unassessed' if chars['categories']['unassessed']['numerator'] else 'pass'), 'unassessed character gate differs')
            stats += '</tbody></table><p>重复位置的额外交付字符：' + str(repeated) + '。原表附带内容可能包含本题用不到的其他财务行、数值和比较列，并非只有排版结构；这部分单列，不计入必需覆盖或有效内容。可选材料不能抵消遗漏或真实性问题。</p></details>'
        evidence = case.get('evidence')
        _need(isinstance(evidence, list), 'evidence list required')
        evidence_html = ''.join('<section><p>' + _link(item) + '</p><blockquote>' + _text(item['quote']) + '</blockquote></section>' for item in evidence)
        _need(isinstance(case.get('process_links'), list), 'process links list required')
        process = ''.join('<li>' + _link(item) + '</li>' for item in case['process_links'])
        sections.append('<article class="case" id="' + cid + '"><p class="verdict ' + status + '">' + escape(cid) + ' · ' + label + '</p><h2 class="question">' + question + '</h2><h3>必须知道什么 / Required coverage</h3><p class="reading">' + _text(case.get('reference_explanation')) + '</p><table><thead><tr><th>项</th><th>必须提供的内容</th><th>独立判断</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>' + narrative + '<div class="pair"><section><h3>少了什么 / Missing</h3>' + missing + '</section><section><h3>多了什么 / Excess</h3>' + extra + '</section></div><section><h3>覆盖与费用 / Coverage & cost</h3>' + stats + '</section><h3>本次判断边界 / Limits</h3>' + _list(case.get('limitations'), '未登记边界。') + '<details><summary>查看关键原文片段 / Evidence excerpts</summary>' + (evidence_html or '<p>尚未登记片段 / No excerpts recorded</p>') + '</details><details><summary>版本与过程记录 / Versions & logs</summary><p>评测参考 SHA256：<code>' + gold_hash + '</code></p><p>运行 SHA256：<code>' + run_hash + '</code></p><p class="muted">以上为输入登记的版本绑定；本页不重新核验原件内容，也不自动证明评审语义。</p><ul>' + process + '</ul></details></article>')
    back = _link(document['back_link']) if document.get('back_link') else ''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title + '</title><style>' + _STYLE + _LAYOUT + '</style></head><body><header><p>' + back + '</p><h1>' + title + '</h1><p class="muted">' + introduction + '</p></header><div class="workspace"><nav aria-label="评测问题 / Cases">' + ''.join(navigation) + '</nav><main>' + ''.join(sections) + '</main></div></body></html>'


def render_evidence_benchmark(input_file, output):
    input_file, output = Path(input_file).resolve(), Path(output).resolve()
    _need(not output.exists() and not input_file.is_relative_to(output), 'output must be new and outside input')
    raw = input_file.read_bytes()
    page = render_page(json.loads(raw))
    output.mkdir(parents=True)
    (output / 'input.json').write_bytes(raw)
    (output / 'index.html').write_text(page, encoding='utf-8')
    manifest = {'schema_version': 'evidence-benchmark-page-delivery-v1', 'model_calls': 0,
                'files': {name: sha256((output / name).read_bytes()).hexdigest() for name in ('input.json', 'index.html')}}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'page': str(output / 'index.html'), **manifest}
