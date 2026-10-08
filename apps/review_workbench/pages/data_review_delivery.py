"""Pure-local, immutable HTML delivery of a sealed Data-only content review."""
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlparse

from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.evidence_coordinates import character_span
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained


_STYLE = '''body{margin:0;background:#f8f7f3;color:#282620;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}main{max-width:1100px;margin:auto;padding:30px}h1{font-size:26px;margin:8px 0}h2{font-size:19px;margin-top:28px}h3{font-size:16px}a{color:#234b5c}section,article{border:1px solid #e4dfd5;background:#fff;padding:18px;margin:14px 0;border-radius:6px}p{margin:8px 0}.muted{color:#68665f;font-size:13px}.scope{overflow-wrap:anywhere}.quote{white-space:pre-wrap;overflow-wrap:anywhere;padding:14px;background:#fcfbf8}mark{background:#fff0ad;color:inherit}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}.meta{display:flex;gap:14px;flex-wrap:wrap}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #e4dfd5;padding:8px}article:target{outline:2px solid #a56931;scroll-margin-top:16px}code{overflow-wrap:anywhere}'''


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _http_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Explicit HTTP(S) links without credentials required')
    return value


def _link(url, label):
    return '<a href="' + escape(url, quote=True) + '">' + escape(label) + '</a>'


def _quote_coordinates(quote, documents):
    sid, bid = quote.get('source_snapshot_id'), quote.get('block_id')
    source = documents.get(sid)
    if source is None:
        raise ValueError('Citation source is outside delivered evidence')
    candidates = [block for block in source['blocks'] if block['block_id'] == bid]
    if len(candidates) != 1 or candidates[0].get('type') == 'image':
        raise ValueError('Citation block is absent, ambiguous or not readable text')
    block = candidates[0]
    for key, expected in (('source_sha256', source['source_sha256']), ('index_id', source['index_id']),
                           ('text_hash', block.get('text_hash'))):
        if quote.get(key) is not None and quote[key] != expected:
            raise ValueError('Citation identity conflicts with frozen original')
    if quote.get('original_block') is not None and quote['original_block'] != block:
        raise ValueError('Citation original block differs from delivered evidence')
    text = quote.get('quote')
    if not isinstance(text, str) or not text:
        raise ValueError('Citation needs exact original text')
    span = character_span(quote, text=block['text'])
    if span is None:
        # Compatibility for old review schemas. Enumerate all overlapping exact
        # occurrences; never silently choose the first occurrence of repeated text.
        positions = [match.start() for match in re.finditer('(?=' + re.escape(text) + ')', block['text'])]
        if len(positions) != 1:
            raise ValueError('Legacy citation needs unique text or explicit character coordinates')
        span = positions[0], positions[0] + len(text)
    return source, block, span


def validate_source_preview_config(dataset_key=None, source_preview_base_url=None):
    """Shared explicit preview endpoint validation, without registration or I/O."""
    if (dataset_key is None) != (source_preview_base_url is None):
        raise ValueError('Supply both explicit dataset_key and source_preview_base_url, or neither')
    if dataset_key is not None:
        if not isinstance(dataset_key, str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}', dataset_key):
            raise ValueError('Explicit valid dataset registration key required')
        _http_url(source_preview_base_url)
        if urlparse(source_preview_base_url).query or urlparse(source_preview_base_url).fragment:
            raise ValueError('Source preview endpoint must not include a query or fragment')


def render_data_review(review_dir, output, *, expected_manifest_sha256,
                       dataset_key=None, source_preview_base_url=None):
    """Render one sealed review; no model work, publication, adoption or registry writes.

    Optional dataset_key and source_preview_base_url must be supplied together.
    The base URL is the exact /data-workspace/source endpoint. A caller owns
    registration of that dataset; this renderer does not invent/register it.
    Local exact quote highlights remain usable without the optional endpoint.
    """
    root, output = Path(review_dir).resolve(), Path(output).resolve()
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_manifest_sha256):
        raise ValueError('Explicit externally pinned review manifest SHA256 required')
    validate_source_preview_config(dataset_key, source_preview_base_url)
    _verify_manifest(root, expected_manifest_sha256)
    manifest = _json(root/'manifest.json')
    if not {'input.json', 'result.json'} <= set(manifest['files']):
        raise ValueError('Review input and result must be in the frozen manifest')
    packet, result = _json(root/'input.json'), _json(root/'result.json')
    if (result['packet_id'] != packet['packet_id'] or result['input_sha256'] != digest(packet)
            or result['scope'] != packet['scope']):
        raise ValueError('Review result is not bound to this exact input and scope')
    fresh = prepare_review_packet(packet['query_ref']['path'], packet['dataset_ref']['path'],
        expected_scope=packet['scope'], max_packet_bytes=packet['max_packet_bytes'],
        source_delivery=packet.get('source_delivery', 'full_indexed_text_v1'))
    if fresh != packet:
        raise ValueError('Review input no longer matches frozen upstream evidence')
    if result.get('assessment') is not None:
        if 'response.json' not in manifest['files']:
            raise ValueError('Assessed review must retain its original response')
        assessment, eligible = validate_assessment(packet, _json(root/'response.json'))
        if result['assessment'] != assessment:
            raise ValueError('Saved assessment differs from the validated response')
        if result['status'] == 'reviewed' and (not eligible or not result['analysis_eligible'] or result['failures']):
            raise ValueError('Review cannot be displayed as passed with unresolved failures')
    elif result['status'] == 'reviewed' or result.get('analysis_eligible'):
        raise ValueError('Missing assessment cannot be displayed as reviewed')
    else:
        assessment = None
    dataset = Path(packet['dataset_ref']['path']).resolve()
    if output.exists() or any(output.is_relative_to(p) for p in (root, dataset, Path(packet['query_ref']['path']).resolve())):
        raise ValueError('Delivery output must be new and outside frozen inputs')
    documents = {doc['source_snapshot_id']: doc for doc in packet['source_documents']}
    if len(documents) != len(packet['source_documents']) or not set(documents) <= set(packet['scope']['source_snapshot_ids']):
        raise ValueError('Delivered sources are duplicated or outside scope')
    for doc in documents.values():
        ids = [b['block_id'] for b in doc['blocks']]
        if len(ids) != len(set(ids)):
            raise ValueError('Delivered block identity is ambiguous')
    source_metadata = {s['source_snapshot_id']: s for s in _json(dataset/'sources.json')}
    rows, references = [], []
    for fact in packet['facts']:
        citations = []
        for quote in fact['citations']:
            source, block, span = _quote_coordinates(quote, documents)
            identity = 'reference-' + digest([source['source_snapshot_id'], block['block_id'], span])[:20]
            citations.append(_link('#' + identity, '原文引用 / Source citation'))
            reference = {'id': identity, 'source_snapshot_id': source['source_snapshot_id'],
                'block_id': block['block_id'], 'char_start': span[0], 'char_end': span[1],
                'quote': block['text'][span[0]:span[1]], 'source_sha256': source['source_sha256'],
                'text_hash': block.get('text_hash'), 'index_id': source['index_id']}
            if not any(r['id'] == identity for r in references): references.append(reference)
        value = fact.get('value', {})
        title = value.get('statement') or value.get('summary') or value.get('text') or fact['fact_id']
        if not isinstance(title, str): title = json.dumps(title, ensure_ascii=False)
        rows.append('<article><h3>' + escape(fact['kind']) + '</h3><p>' + escape(title[:500]) + '</p><p>'
                    + ' · '.join(citations) + '</p><details><summary>完整数据 / Full data</summary><pre>'
                    + escape(json.dumps(fact, ensure_ascii=False, indent=2)) + '</pre></details></article>')
    # Validate reviewer quotes too: even rejected judgements must not invent a
    # source location in the visible delivery.
    if assessment:
        for field in ('facts', 'requirements', 'source_checks'):
            for row in assessment[field]:
                for quote in row['citations']: _quote_coordinates(quote, documents)
    html_parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Data Agent · 证据交付</title><style>' + _STYLE + '</style></head><body><main>',
        '<p class="muted">Data Agent · 冻结证据交付 / Frozen evidence delivery</p><h1>' + escape(packet['question']) + '</h1>',
        '<section><p><strong>状态 / Status: ' + escape(result['status']) + '</strong></p>',
        '<p>内容复核是模型意见，尚未经人工验收；此页不代表已采纳、已发布或已产生投资结论。</p>',
        '<p class="muted">Model review is not human acceptance, adoption, publication or an investment conclusion.</p>',
        '<p class="scope">' + escape(' / '.join(packet['scope']['company_ids'])) + ' · 截止 / Cutoff: '
            + escape(packet['scope']['knowledge_cutoff']) + '</p>',
        '<p>交付 ' + str(sum(len(d['blocks']) for d in documents.values())) + ' 个原文块 / source blocks · '
            + str(len(packet['facts'])) + ' 项数据 / facts · ' + str(len(references)) + ' 处精确引用 / exact references</p>',
        '<p>这是本次检索选取的原文集合；未声明数学意义上的最小集合，也未声明整份报告审阅完整。</p>',
        '<details><summary>范围、来源与执行身份 / Scope and origin</summary><pre>' + escape(json.dumps({
            'scope': packet['scope'], 'source_delivery': packet.get('source_delivery', 'full_indexed_text_v1'),
            'query_origin': packet['query_plan_origin'], 'review_origin': result['plan_origin']}, ensure_ascii=False, indent=2)) + '</pre></details></section>',
        '<h2>本次取得的数据 / Retrieved data</h2>', *rows,
        '<h2>精确原文与上下文 / Exact original evidence</h2>']
    for ref in references:
        source = documents[ref['source_snapshot_id']]
        block = next(b for b in source['blocks'] if b['block_id'] == ref['block_id'])
        lo, hi = ref['char_start'], ref['char_end']; text = block['text']
        context = ('…' if lo > 180 else '') + text[max(0, lo - 180):lo]
        suffix = text[hi:hi + 180] + ('…' if hi + 180 < len(text) else '')
        links = []
        if source.get('source_url'): links.append(_link(_http_url(source['source_url']), '原始来源页面 / Original source page'))
        source_file = 'source-index-' + digest(source['source_snapshot_id'])[:16] + '.json'
        links.append(_link(source_file, '冻结目录索引 / Frozen index'))
        if dataset_key:
            params = {'dataset': dataset_key, 'source': ref['source_snapshot_id'], 'block': ref['block_id'],
                'char_start': lo, 'char_end': hi, 'source_sha256': ref['source_sha256']}
            if len(ref['quote'].encode('utf-8')) <= 1024: params['quote'] = ref['quote']
            if ref['text_hash']: params['text_hash'] = ref['text_hash']
            links.append(_link(source_preview_base_url + '?' + urlencode(params) + '#workspace-evidence',
                               '在原件中高亮 / Highlight in original'))
        html_parts += ['<article id="' + ref['id'] + '"><p class="muted">' + escape(ref['source_snapshot_id']) + ' · '
            + escape(ref['block_id']) + ' · [' + str(lo) + ', ' + str(hi) + ')</p>',
            '<div class="quote">' + escape(context) + '<mark>' + escape(ref['quote']) + '</mark>' + escape(suffix) + '</div>',
            '<p class="meta">' + ' · '.join(links) + '</p>', '<details><summary>完整原文块 / Complete original block</summary><div class="quote">'
            + escape(text[:lo]) + '<mark>' + escape(text[lo:hi]) + '</mark>' + escape(text[hi:]) + '</div></details></article>']
    html_parts += ['<h2>完整交付集合 / Complete delivered set</h2>',
        '<p class="muted">包括检索原文及随附限定条件；这里只展示本次交付的块，不代表整份来源。</p>']
    for sid, source in documents.items():
        for block in source['blocks']:
            html_parts += ['<details><summary>' + escape(sid + ' · ' + block['block_id'] + ' · '
                + str(len(block.get('text', ''))) + ' characters') + '</summary><section><div class="quote">'
                + escape(block.get('text', '')) + '</div><details><summary>原始结构 / Original structure</summary><pre>'
                + escape(json.dumps(block, ensure_ascii=False, indent=2)) + '</pre></details></section></details>']
    if assessment and assessment.get('revision_requests'):
        html_parts += ['<h2>待修订 / Requested revisions</h2><section><ul>'
            + ''.join('<li>' + escape(item) + '</li>' for item in assessment['revision_requests'])
            + '</ul></section>']
    html_parts += ['<h2>复核与缺口 / Review and gaps</h2><section><pre>' + escape(json.dumps({
        'query_gaps': packet['query_gaps'], 'program_gaps': packet['program_gaps'],
        'assessment': assessment, 'failures': result['failures']}, ensure_ascii=False, indent=2)) + '</pre></section>',
        '<h2>冻结文件 / Frozen artifacts</h2><p>' + ' · '.join(_link(name, label) for name, label in (
            ('input.json', '原始交付输入 / Input'), ('result.json', '复核结果 / Result'),
            ('review-manifest.json', '原复核 manifest / Original review manifest'),
            ('dataset-manifest.json', '原数据 manifest / Original dataset manifest'),
            ('delivery.json', '本页引用清单 / Page references'))) + '</p>',
        '<p class="muted">原件预览依赖调用者明确登记的数据集。未配置工作台地址时，仍可在本页核对冻结原文与精确高亮。</p></main></body></html>']
    # Read/validate all copied artifacts before creating any delivery output.
    copies = {'input.json': (root/'input.json').read_bytes(), 'result.json': (root/'result.json').read_bytes(),
        'review-manifest.json': (root/'manifest.json').read_bytes(), 'dataset-manifest.json': (dataset/'manifest.json').read_bytes()}
    for sid in documents:
        metadata = source_metadata[sid]
        path = contained(dataset, metadata['index_folder'] + '/index.json')
        copies['source-index-' + digest(sid)[:16] + '.json'] = path.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in copies.items(): (output/name).write_bytes(raw)
    (output/'index.html').write_text(''.join(html_parts), encoding='utf-8')
    summary = {'schema_version': 'data-review-delivery-v1', 'review_manifest_sha256': expected_manifest_sha256,
        'review_status': result['status'], 'human_acceptance': 'not_evaluated', 'adoption': 'unchanged_candidate',
        'dataset_key': dataset_key, 'source_preview_base_url': source_preview_base_url,
        'references': references, 'review_path': str(root), 'dataset_manifest_sha256': packet['dataset_ref']['manifest_sha256']}
    write_new(output/'delivery.json', summary)
    write_new(output/'manifest.json', {'files': {p.name: digest(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}})
    return {**summary, 'page': str(output/'index.html'), 'manifest_sha256': digest((output/'manifest.json').read_bytes())}
