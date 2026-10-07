"""Build a local review page from an explicit system-agent run. No model calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import copy
import gzip
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlencode

from lxml import html as lhtml
from uteki.domain.business_map.models import business_map_from_dict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


revenue_view = load_helper('revenue_view_v2', HERE.parent / '2026-10-07-business-revenue-v2/build_view.py')
view = revenue_view.view
norm = lambda value: ' '.join(value.split())
text_hash = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite_json_number')
    value = json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError('json_object_required')
    return value


def source_dom(meta):
    path = view.local_path(meta['source_local_path'])
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta['source_sha256']:
        raise ValueError('source_hash_mismatch')
    dom = lhtml.fromstring(raw)
    tree = dom.getroottree()
    return {tree.getpath(node): node for node in dom.iter()}


def source_provenance(packet):
    """Describe only verified input formats; derived HTML is not an original PDF."""
    kind = packet.get('source_kind', 'html_input')
    original = packet.get('original_source_path')
    alternate = packet.get('original_source_local_path')
    if original and alternate and original != alternate:
        raise ValueError('conflicting_original_source_paths')
    original = original or alternate
    original_sha = packet.get('original_source_sha256')
    if kind == 'pdf_derived_selected_html':
        if not isinstance(original, str) or not original.strip() or not isinstance(original_sha, str):
            raise ValueError('original_pdf_provenance_required')
        path = view.local_path(original)
        if not path.is_file() or not path.read_bytes().startswith(b'%PDF-'):
            raise ValueError('original_pdf_required')
        if view.sha(path) != original_sha:
            raise ValueError('original_pdf_hash_mismatch')
        return {'kind': kind, 'source_label': '派生 HTML / Derived HTML',
                'source_hash_label': '派生 HTML SHA-256',
                'description': '输入来自报告 PDF 的选段派生 HTML；这不是 SEC 原生 HTML。原始 PDF 与派生 HTML 分别保留，使用各自的指纹。',
                'source_sha256': packet['source_sha256'],
                'original_source_path': original, 'original_source_sha256': original_sha}
    if original or original_sha:
        raise ValueError('original_source_requires_explicit_pdf_derivation')
    return {'kind': kind, 'source_label': '输入 HTML / Source HTML',
            'source_hash_label': '输入 HTML SHA-256',
            'description': '本次输入为已冻结的 HTML，片段与金额引用可定位到输入中的具体元素。',
            'source_sha256': packet['source_sha256']}


def validate_evidence(evidence, locator, nodes, targets, allowed_paths, table_paths):
    for key in ('exact_quote', 'source_dom_path', 'local_path', 'fragment'):
        if not isinstance(locator.get(key), str) or not locator[key]:
            raise ValueError('precise_source_evidence_required: ' + key)
    path = locator['source_dom_path']
    if path not in allowed_paths and not any(path.startswith(t + '/') for t in table_paths):
        raise ValueError('evidence_outside_source_packet')
    node = nodes.get(path)
    if node is None:
        raise ValueError('source_dom_path_not_found')
    source_text = norm(''.join(node.itertext()))
    quote = norm(locator['exact_quote'])
    if not quote or quote not in source_text:
        raise ValueError('quote_not_in_source_element')
    hash_text = source_text
    if locator.get('source_cell_dom_path'):
        cell = nodes.get(locator['source_cell_dom_path'])
        if cell is None or not locator['source_cell_dom_path'].startswith(path + '/'):
            raise ValueError('source_cell_not_in_evidence_table')
        hash_text = norm(''.join(cell.itertext()))
        if hash_text != locator.get('source_cell_text'):
            raise ValueError('source_cell_text_mismatch')
    recorded_hash = locator.get('text_hash') or evidence.get('text_hash')
    if recorded_hash != text_hash(hash_text):
        raise ValueError('source_text_hash_mismatch')
    target = view.local_path(locator['local_path'])
    if target not in targets:
        targets[target] = lhtml.fromstring(target.read_bytes())
    matches = targets[target].xpath('//*[@id=$f or @name=$f]', f=locator['fragment'])
    if len(matches) != 1 or quote not in norm(' '.join(matches[0].itertext())):
        raise ValueError('evidence_anchor_quote_mismatch')


def validate_agent(path, packet_path, skill_path, *, recovered=False):
    data = read_json(path)
    if data.get('schema_version') == 'business-map-v0.2':
        raise ValueError('business_map_v2_display_requires_basis_aware_renderer')
    business_map_from_dict(data)
    meta = data['metadata']
    for key in ('report_label', 'period_end', 'source_local_path', 'source_url',
                'source_sha256', 'source_packet_sha256', 'skill_sha256', 'trace_id'):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise ValueError('agent_metadata_required: ' + key)
    if meta.get('extraction_method') != ('system_agent_format_recovery' if recovered else 'system_agent'):
        raise ValueError('system_agent_provenance_required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', data['company_id']):
        raise ValueError('unsafe_company_asset_id')
    if meta['source_packet_sha256'] != view.sha(packet_path) or meta['skill_sha256'] != view.sha(skill_path):
        raise ValueError('agent_input_fingerprint_mismatch')
    packet = read_json(packet_path)
    for field in ('company_id', 'document_id'):
        if data[field] != packet[field]:
            raise ValueError('agent_packet_scope_mismatch')
    for field in ('period_end', 'source_sha256'):
        if meta[field] != packet[field]:
            raise ValueError('agent_packet_scope_mismatch')
    if len([b for b in data['businesses'] if b['kind'] == 'company']) != 1:
        raise ValueError('one_company_required')
    for node in data['businesses']:
        if node['kind'] == 'revenue_line':
            raise ValueError('business_contains_revenue_dimension')
        if node.get('review_status') != 'candidate' or not node['evidence_ids']:
            raise ValueError('candidate_node_evidence_required')
        for claim in node.get('monetization', []):
            if claim['basis'] != 'unknown' and not claim['evidence_ids']:
                raise ValueError('monetization_evidence_required')
    for edge in data['relationships']:
        if edge['kind'] == 'revenue_component_of':
            raise ValueError('business_contains_revenue_dimension')
        if edge.get('review_status') != 'candidate' or not edge['evidence_ids']:
            raise ValueError('candidate_relationship_evidence_required')
    nodes = source_dom(meta)
    allowed_paths = {b['source_dom_path'] for b in packet['blocks']}
    table_paths = {t['source_dom_path'] for t in packet['tables']}
    targets = {}
    locators = {}
    for evidence in data['evidence']:
        if evidence['document_id'] != data['document_id']:
            raise ValueError('cross_document_evidence')
        locator = {**evidence, **meta.get('evidence_locators', {}).get(evidence['id'], {})}
        validate_evidence(evidence, locator, nodes, targets, allowed_paths, table_paths)
        locators[evidence['id']] = locator
    return data, packet, nodes, targets, allowed_paths, table_paths, locators


def svg_markup(path, data, ids):
    svg = ET.fromstring(path.read_text())
    for element in svg.iter():
        for key, value in element.attrib.items():
            if key.split('}')[-1] == 'href' and not value.startswith('#'):
                raise ValueError('external_svg_reference')
        text = ' '.join(element.attrib.values()) + (element.text or '')
        if re.search(r'@import|url\(\s*[\"\']?\s*(?!#)[^\s\"\')]', text, re.I):
            raise ValueError('external_svg_style')
    labels = {el.get('data-id'): norm(''.join(el.itertext())) for el in svg.iter()
              if el.get('class') == 'label' and el.get('data-id')}
    edges = []
    for el in svg.iter():
        if 'flowchart-link' not in el.get('class', '').split():
            continue
        match = re.fullmatch(r'L_(N\d+)_(N\d+)_\d+', el.get('id', ''))
        if not match or el.get('id') not in labels:
            raise ValueError('unrecognized_svg_edge')
        edges.append((match[1], match[2], labels[el.get('id')]))
    expected = [(ids[e['source']], ids[e['target']], e['label']) for e in view.presentation_edges(data)]
    if Counter(edges) != Counter(expected):
        raise ValueError('svg_relationship_mismatch')
    return view.inline_svg(path, data, ids)


def safe_run_summary(result, meta):
    if result.get('status') != 'candidate' or result.get('validation') != 'passed':
        raise ValueError('completed_candidate_run_required')
    if result.get('trace_id') != meta['trace_id']:
        raise ValueError('result_trace_mismatch')
    for key in ('source_packet_sha256', 'skill_sha256'):
        if result.get(key) != meta[key]:
            raise ValueError('result_input_fingerprint_mismatch')
    return call_summary(result)


def call_summary(result):
    # The page never serializes raw model responses, prompts or the full result.
    fields = ('trace_id', 'status', 'model', 'requested_model', 'returned_model',
              'provider', 'reasoning_effort', 'estimated_usd', 'call_count',
              'elapsed_seconds', 'stop_reason', 'input_tokens', 'output_tokens')
    public = {key: result[key] for key in fields if key in result and
              isinstance(result[key], (str, int, float, bool, type(None)))}
    public['requested_model'] = result.get('model')
    costs = result.get('costs') or {}
    records = costs.get('records') or []
    public['call_count'] = costs.get('requests')
    public['unknown_cost_requests'] = costs.get('unknown_cost_requests')
    public['known_estimated_usd'] = costs.get('known_estimated_usd')
    public['estimated_usd'] = costs.get('known_estimated_usd') if costs.get('unknown_cost_requests') == 0 else None
    for field, source in (('returned_model', 'actual_upstream_model'), ('reasoning_effort', 'reasoning_effort'), ('stop_reason', 'stop_reason')):
        values = [r.get(source) for r in records]
        public[field] = ' / '.join(dict.fromkeys(values)) if values and all(isinstance(v, str) and v for v in values) else None
    for field in ('input_tokens', 'output_tokens', 'cache_read_input_tokens'):
        values = [(r.get('raw_usage') or {}).get(field) for r in records]
        public[field] = sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None
    elapsed = [r.get('elapsed_seconds') for r in records]
    public['elapsed_seconds'] = sum(elapsed) if elapsed and all(type(v) in (int, float) and v >= 0 for v in elapsed) else None
    return public


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def safe_review(path, business, packet, nodes, map_path, revenue_path, reference_map, reference_revenue):
    """Bind a separate content review to exact immutable outputs before display."""
    if path is None:
        return None
    review = read_json(path)
    meta = business['metadata']
    expected = {key: business[key] for key in ('company_id', 'document_id')}
    expected.update({key: meta[key] for key in ('period_end', 'trace_id', 'source_sha256', 'source_packet_sha256')})
    expected.update(business_map_sha256=view.sha(map_path), revenue_sha256=view.sha(revenue_path))
    binding = review.get('binding')
    if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError('review_run_binding_mismatch')
    reference_binding = review.get('reference_binding')
    if reference_map is not None:
        if not isinstance(reference_binding, dict) or any(reference_binding.get(key) != view.sha(path) for key, path in (
                ('business_map_sha256', reference_map), ('revenue_sha256', reference_revenue))):
            raise ValueError('review_reference_binding_mismatch')
    elif reference_binding:
        raise ValueError('review_reference_without_reference')
    def text(value, field):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('review_text_required: ' + field)
        return value
    public = {key: text(review.get(key), key) for key in ('verdict', 'summary')}
    if 'review_method' in review:
        public['review_method'] = text(review['review_method'], 'review_method')
    public['binding'] = expected
    if reference_map is not None:
        public['reference_binding'] = {key: reference_binding[key] for key in ('business_map_sha256', 'revenue_sha256')}
    checks, limitations = review.get('checks'), review.get('limitations')
    if not isinstance(checks, list) or not checks or not isinstance(limitations, list):
        raise ValueError('review_checks_and_limitations_required')
    blocks = {block['id']: block for block in packet['blocks']}
    seen, source_blocks, public_checks = set(), {}, []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError('review_check_object_required')
        item = {key: text(check.get(key), key) for key in ('id', 'label', 'status', 'actual', 'note')}
        if reference_map is not None:
            item['reference'] = text(check.get('reference'), 'reference')
        if item['id'] in seen or not re.fullmatch(r'[a-zA-Z0-9_-]+', item['id']):
            raise ValueError('review_check_id_invalid')
        seen.add(item['id'])
        if item['status'] not in ('pass', 'needs_improvement', 'gap'):
            raise ValueError('review_check_status_invalid')
        source_ids = check.get('source_block_ids')
        if not isinstance(source_ids, list) or any(not isinstance(bid, str) or bid not in blocks for bid in source_ids):
            raise ValueError('review_source_block_outside_packet')
        if len(source_ids) != len(set(source_ids)):
            raise ValueError('review_source_block_duplicate')
        for bid in source_ids:
            block = blocks[bid]
            node = nodes.get(block['source_dom_path'])
            actual_text = norm(''.join(node.itertext())) if node is not None else None
            if actual_text != block['text'] or text_hash(actual_text) != block['text_sha256']:
                raise ValueError('review_source_block_differs_from_original')
            source_blocks[bid] = {key: block[key] for key in ('id', 'text', 'section_path', 'source_dom_path')}
        item['source_block_ids'] = source_ids
        public_checks.append(item)
    public['checks'] = public_checks
    public['limitations'] = [text(value, 'limitation') for value in limitations]
    public['source_blocks'] = list(source_blocks.values())
    return public


def validate_revenue(path, business, packet):
    data = read_json(path)
    if not isinstance(data.get('charts'), list):
        raise ValueError('revenue_charts_list_required')
    if data['charts']:
        return revenue_view.validate_revenue(path, [business])
    # An explicit empty selection is a financial coverage gap, not a zero-valued
    # chart. Preserve scope/source checks without inserting a dummy chart.
    for key in ('company_id', 'document_id', 'period_end', 'source_sha256', 'source_url'):
        if not data.get(key) or data[key] != packet[key]:
            raise ValueError('empty_revenue_scope_mismatch')
    if data.get('currency') != packet['financial_currency'] or data.get('unit') != packet['financial_unit']:
        raise ValueError('empty_revenue_unit_mismatch')
    source_dom(data)
    if not isinstance(data.get('evidence'), list) or len({e['id'] for e in data['evidence']}) != len(data['evidence']):
        raise ValueError('empty_revenue_evidence_invalid')
    if data.get('reported_subtotals'):
        raise ValueError('subtotal_without_revenue_chart')
    return data


def safe_enrichment(path, business, map_path):
    """Display an explicitly selected, manually reviewed supplement; never fetch."""
    if path is None:
        return None
    data = read_json(path)
    expected = {key: business[key] for key in ('company_id', 'document_id')}
    expected.update(period_end=business['metadata']['period_end'], business_map_sha256=view.sha(map_path))
    if data.get('schema_version') != 'official-product-enrichment-v1' or data.get('binding') != expected:
        raise ValueError('enrichment_map_binding_mismatch')
    if data.get('provenance') != {'method': 'codex_manual_web_review', 'model_api_calls': 0}:
        raise ValueError('enrichment_manual_provenance_required')
    def text(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('enrichment_nonempty_text_required')
        return value
    def https(value):
        text(value)
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None or '\\' in value or re.search(r'\s', value):
            raise ValueError('enrichment_https_without_credentials_required')
        return value
    def checked(value):
        text(value)
        try:
            timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError('enrichment_checked_at_with_timezone_required') from None
        return value
    entities = data.get('entities')
    if not isinstance(entities, list) or not entities:
        raise ValueError('enrichment_entities_required')
    node_ids = {node['id'] for node in business['businesses']}
    seen, public_entities = set(), []
    for entity in entities:
        if not isinstance(entity, dict) or entity.get('business_id') not in node_ids or entity['business_id'] in seen:
            raise ValueError('enrichment_unknown_or_duplicate_business_id')
        seen.add(entity['business_id'])
        if any(not isinstance(entity.get(key), list) for key in ('official_links', 'to_watch', 'gaps')):
            raise ValueError('enrichment_lists_required')
        links, all_links, gaps, watch = [], {}, [text(gap) for gap in entity['gaps']], []
        for raw in entity['official_links']:
            if not isinstance(raw, dict):
                raise ValueError('enrichment_link_object_required')
            item = {key: text(raw.get(key)) for key in ('id', 'title', 'role', 'publisher', 'official_status', 'availability')}
            if item['id'] in all_links or item['role'] not in ('product', 'documentation', 'release_notes') or item['official_status'] not in ('verified', 'unverified') or item['availability'] not in ('readable', 'unavailable'):
                raise ValueError('enrichment_link_id_or_status_invalid')
            item.update(url=https(raw.get('url')), final_url=https(raw.get('final_url')), checked_at=checked(raw.get('checked_at')))
            item['published_at'] = text(raw['published_at']) if raw.get('published_at') is not None else None
            verification = raw.get('verification')
            if not isinstance(verification, dict):
                raise ValueError('enrichment_verification_required')
            item['verification'] = {key: text(verification.get(key)) for key in ('publisher_basis', 'product_match', 'locator', 'exact_quote', 'quote_sha256')}
            item['verification']['source_url'] = https(verification.get('source_url'))
            if text_hash(item['verification']['exact_quote']) != item['verification']['quote_sha256']:
                raise ValueError('enrichment_quote_hash_mismatch')
            all_links[item['id']] = item
            if item['official_status'] == 'verified' and item['availability'] == 'readable':
                links.append(item)
            else:
                gaps.append(item['title'] + '：' + item['official_status'] + ' / ' + item['availability'] + '；未作为已核验官方入口展示。')
        watch_ids, admitted_ids = set(), {item['id'] for item in links}
        for raw in entity['to_watch']:
            if not isinstance(raw, dict):
                raise ValueError('enrichment_watch_object_required')
            item = {key: text(raw.get(key)) for key in ('id', 'question', 'why', 'observable_signal', 'status')}
            ids = raw.get('source_ids')
            if item['id'] in watch_ids or item['status'] != 'suggested' or not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in all_links for i in ids) or len(ids) != len(set(ids)):
                raise ValueError('enrichment_watch_source_or_status_invalid')
            watch_ids.add(item['id'])
            item['source_ids'] = ids
            if set(ids) <= admitted_ids:
                watch.append(item)
            else:
                gaps.append('观察建议“' + item['question'] + '”尚缺已核验且可读的来源；未作为观察卡片展示。')
        public_entities.append({'business_id': entity['business_id'], 'official_links': links, 'to_watch': watch, 'gaps': gaps})
    return {'schema_version': data['schema_version'], 'binding': expected, 'provenance': data['provenance'], 'entities': public_entities,
            'checked_at': sorted({item['checked_at'] for entity in entities for item in entity['official_links']})}


def build(args):
    if (args.reference_map is None) != (args.reference_revenue is None):
        raise ValueError('reference_map_and_revenue_required_together')
    if args.reference_page and args.reference_map is None:
        raise ValueError('reference_page_requires_reference')
    run = args.run_dir.resolve()
    recovery_path = getattr(args, 'format_recovery', None)
    recovery_context = None
    if recovery_path:
        helper = load_helper('explicit_format_recovery', HERE / 'format_recovery.py')
        recovery_context = helper.verify_derived(ROOT, run, recovery_path)
    args.source_packet = args.source_packet or run / 'source_packet.json'
    args.skill = args.skill or run / 'skill.md'
    map_path, revenue_path = run / 'business_map.json', run / 'revenue.json'
    result_path = run / 'result.json'
    data, packet, nodes, targets, allowed, tables, locators = validate_agent(map_path, args.source_packet, args.skill, recovered=recovery_context is not None)
    meta = data['metadata']
    provenance = source_provenance(packet)
    raw_result = read_json(result_path)
    result = call_summary(recovery_context['result']) if recovery_context else safe_run_summary(raw_result, meta)
    if recovery_context:
        result['status'] = raw_result['status']
    for name in ('business_map.json', 'revenue.json', 'evidence.html'):
        if raw_result.get('artifacts_sha256', {}).get(name) != view.sha(run / name):
            raise ValueError('run_output_fingerprint_mismatch: ' + name)
    revenue = validate_revenue(revenue_path, data, packet)
    for chart in revenue['charts']:
        components_by_id = {p['id']: p for p in chart['parts'] + chart['adjustments']}
        for subtotal in chart.get('reported_subtotals', []):
            components = subtotal.get('component_ids', [])
            if not components or len(set(components)) != len(components) or not set(components) <= components_by_id.keys():
                raise ValueError('chart_subtotal_components_invalid')
            if sum(revenue_view.number(components_by_id[c]['value']) for c in components) != revenue_view.number(subtotal['value']):
                raise ValueError('chart_subtotal_does_not_reconcile')
    for evidence in revenue['evidence']:
        validate_evidence(evidence, evidence, nodes, targets, allowed, tables)
    reference = reference_revenue = None
    if args.reference_map is not None:
        reference, _ = view.validate(args.reference_map)
        reference_revenue = revenue_view.validate_revenue(args.reference_revenue, [reference])
        if any(data[k] != reference[k] for k in ('company_id', 'document_id')) or any(
                meta[k] != reference['metadata'][k] for k in ('period_end', 'source_sha256')):
            raise ValueError('reference_scope_mismatch')
    review_path = getattr(args, 'review', None)
    review = safe_review(review_path, data, packet, nodes, map_path, revenue_path,
                         args.reference_map, args.reference_revenue)
    enrichment_path = getattr(args, 'enrichment', None)
    enrichment = safe_enrichment(enrichment_path, data, map_path)
    output = args.output.resolve()
    if args.reference_page and not args.reference_page.is_file():
        raise ValueError('reference_page_not_found')
    if output == run or output.is_relative_to(run):
        raise ValueError('page_must_not_overwrite_run')
    output.mkdir(parents=True, exist_ok=True)
    assets = output / 'assets'
    assets.mkdir(exist_ok=True)
    mermaid, ids = view.mermaid(data)
    mmd_path = assets / (data['company_id'] + '.mmd')
    svg_path = assets / (data['company_id'] + '.svg')
    # Reject a stale SVG when a second-stage build changes the Mermaid input.
    if args.with_svg and (not mmd_path.is_file() or mmd_path.read_text() != mermaid):
        raise ValueError('prepare_current_mermaid_before_svg')
    diagram = svg_markup(svg_path, data, ids) if args.with_svg else '<p class="pending">Mermaid 已生成。SVG 尚未提供；可先查看节点与证据。</p>'
    mmd_path.write_text(mermaid)
    write_json(assets / (data['company_id'] + '-ids.json'), ids)
    public = copy.deepcopy(data)
    public['metadata'] = {key: meta[key] for key in ('report_label', 'period_end', 'node_labels',
        'node_roles', 'node_assertion_basis', 'source_sha256', 'source_packet_sha256',
        'skill_sha256', 'trace_id', 'extraction_method') if key in meta}
    for evidence in public['evidence']:
        loc = locators[evidence['id']]
        evidence['quote'] = loc['exact_quote']
        evidence['href'] = view.link(view.local_path(loc['local_path']), output, loc['fragment'])
    for evidence in revenue['evidence']:
        evidence['href'] = view.link(view.local_path(evidence['local_path']), output, evidence['fragment'])
    payload = {'map': public, 'revenue': revenue, 'run': result, 'review': review, 'enrichment': enrichment, 'provenance': provenance, 'svg_available': args.with_svg,
        'reference': {'node_count': len(reference['businesses']), 'relationship_count': len(reference['relationships']),
                      'revenue_chart_count': len(reference_revenue['charts']), 'method': reference['metadata']['extraction_method']} if reference else None,
        'links': {'map': view.link(map_path, output), 'revenue': view.link(revenue_path, output),
                  'result': view.link(result_path, output), 'packet': view.link(args.source_packet.resolve(), output),
                  'review': view.link(review_path.resolve(), output) if review_path else None,
                  'enrichment': view.link(enrichment_path.resolve(), output) if enrichment_path else None,
                  'skill': view.link(args.skill.resolve(), output), 'mermaid': view.link(mmd_path, output),
                  'svg': view.link(svg_path, output) if args.with_svg else None,
                  'source': view.link(view.local_path(meta.get('source_html_path', meta['source_local_path'])), output),
                  'original_source': view.link(view.local_path(provenance['original_source_path']), output) if provenance.get('original_source_path') else None,
                  'reference_map': view.link(args.reference_map.resolve(), output) if reference else None,
                  'reference_revenue': view.link(args.reference_revenue.resolve(), output) if reference else None,
                  'reference_page': view.link(args.reference_page.resolve(), output, data['company_id']) if args.reference_page else None}}
    notice = ''
    if recovery_context:
        source_run = recovery_context['source_run']
        payload['recovery'] = {key: raw_result[key] for key in ('source_binding', 'transformation', 'additional_model_calls', 'additional_estimated_usd', 'validation')}
        recovery_links = {'source_result': view.link(source_run / 'result.json', output),
            'raw_response': view.link(source_run / 'response.txt', output),
            'normalized_response': view.link(run / 'normalized-response.json', output),
            'recovery_manifest': view.link(recovery_path.resolve(), output)}
        workbench = getattr(args, 'workbench_url', None)
        if workbench:
            parts = urlsplit(workbench)
            if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError('invalid_workbench_url')
            recovery_links['source_process'] = workbench.rstrip('/') + '/agent-runs?' + urlencode({'agent': 'data', 'run': meta['trace_id'], 'tab': 'process'})
        payload['links'].update(recovery_links)
        labels = {'source_result': '原执行失败记录', 'raw_response': '原始模型正文', 'normalized_response': '仅去围栏后的 JSON', 'recovery_manifest': '恢复与指纹证明', 'source_process': '原失败 Trace 过程'}
        links = ''.join('<a href="' + html.escape(href, quote=True) + '">' + labels[key] + ' ↗</a>' for key, href in recovery_links.items())
        notice = '<section class="card" style="border-color:#bf985e;background:#fff8e9"><h3>格式恢复候选 / Format-recovered candidate</h3><p><strong>原执行仍为失败：StrictJSONError。</strong>供应商已返回完整正文；本页仅移除最外层一对 JSON 围栏，内部每个字节保持不变，再经完整契约校验生成。状态为 derived_candidate / passed_after_format_recovery，内容仍须审阅。</p><p>本地恢复新增模型调用 0 次，新增费用 $0。下方模型、用量、耗时和费用均引用原调用一次，不构成第二次收费。Trace 指向原失败执行。</p><div class="links">' + links + '</div></section>'
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('&', '\\u0026')
    page = (HERE / 'template.html').read_text().replace('<!-- DIAGRAM -->', diagram).replace('/* DATA */', serialized).replace('<!-- RECOVERY -->', notice)
    if recovery_context:
        page = page.replace('业务与收入图 · 真实运行候选', '业务与收入图 · 本地格式恢复候选').replace('本轮是一次系统 Agent 与 Claude 的实际执行候选。', '本页是从一次失败执行的完整响应生成的本地格式恢复候选，原执行状态保持失败。')
    if reference is None:
        page = re.sub(r'<!-- REFERENCE -->.*?<!-- /REFERENCE -->', '', page, flags=re.S)
    (output / 'index.html').write_text(page)
    check = {'schema_version': 'agent-business-revenue-view-v1', 'trace_id': meta['trace_id'],
        'extraction_method': meta['extraction_method'], 'builder_model_api_calls': 0, 'with_svg': args.with_svg,
        'company_id': data['company_id'], 'document_id': data['document_id'], 'period_end': meta['period_end'],
        'nodes': len(data['businesses']), 'relationships': len(data['relationships']), 'revenue_charts': len(revenue['charts']),
        'revenue_status': 'candidate' if revenue['charts'] else 'gap_no_complete_revenue_chart',
        'fingerprints': {name: view.sha(path) for name, path in {'business_map': map_path, 'revenue': revenue_path,
            'result': result_path, 'source_packet': args.source_packet, 'skill': args.skill,
            'reference_map': args.reference_map, 'reference_revenue': args.reference_revenue,
            'builder': Path(__file__), 'template': HERE / 'template.html', 'mermaid_helper': Path(view.__file__),
            'revenue_validator': Path(revenue_view.__file__), 'mermaid': mmd_path, 'html': output / 'index.html'}.items() if path is not None},
        'checks': ['system_agent provenance', 'source/packet/skill fingerprints', 'candidate domain contract',
                   'original DOM quote and text hash', 'local evidence fragments', 'separate business/revenue dimensions',
                   'source-cell amounts and signed reconciliation'],
        'not_claimed': ['full filing coverage', 'browser interaction or visual review', 'reference is ground truth', 'user adoption']}
    check['reference_attached'] = reference is not None
    if enrichment is not None:
        check['fingerprints']['enrichment'] = view.sha(enrichment_path)
        check['enrichment'] = {'entities': len(enrichment['entities']), 'checked_at': enrichment['checked_at'],
            'official_links': sum(len(e['official_links']) for e in enrichment['entities']),
            'watch_suggestions': sum(len(e['to_watch']) for e in enrichment['entities']), 'scheduled_monitoring': False}
        check['checks'].append('manual enrichment scope/map hash/node binding, HTTPS URLs, source references and quote fingerprints; no external fetch')
    if recovery_context:
        check['format_recovery'] = payload['recovery']
        check['fingerprints']['recovery_manifest'] = view.sha(recovery_path)
        check['fingerprints']['recovery_verifier'] = view.sha(HERE / 'format_recovery.py')
        check['fingerprints']['recovery_validation'] = view.sha(run / 'validation.json')
        check['checks'].append('failed source and response binding; exact single fence removal; full contract; unchanged materialized content')
    check['source_kind'] = provenance['kind']
    if reference is not None:
        check['checks'].append('same-source explicit reference')
    if provenance.get('original_source_sha256'):
        check['fingerprints']['original_pdf'] = provenance['original_source_sha256']
        check['checks'].append('original PDF fingerprint distinct from derived HTML input')
    if review is not None:
        check['review_verdict'] = review['verdict']
        check['fingerprints']['review'] = view.sha(review_path)
        check['checks'].append('independent review scope, Trace, output fingerprints and exact source blocks')
    if args.with_svg:
        check['fingerprints']['svg'] = view.sha(svg_path)
        check['checks'].append('SVG node IDs, edge endpoints and visible labels')
    write_json(output / 'verification.json', check)
    print(json.dumps({'output': str(output), 'nodes': check['nodes'], 'relationships': check['relationships'], 'with_svg': args.with_svg}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('run-dir', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    for option in ('reference-map', 'reference-revenue'):
        parser.add_argument('--' + option, type=Path, help='Optional explicit reference; provide both reference files together')
    parser.add_argument('--source-packet', type=Path, help='Defaults to frozen run/source_packet.json')
    parser.add_argument('--skill', type=Path, help='Defaults to frozen run/skill.md')
    parser.add_argument('--reference-page', type=Path)
    parser.add_argument('--review', type=Path, help='Optional independent review bound to this run and any selected reference')
    parser.add_argument('--enrichment', type=Path, help='Optional saved manual official-product supplement bound to this exact map')
    parser.add_argument('--with-svg', action='store_true')
    parser.add_argument('--format-recovery', type=Path, help='Explicit derived manifest; verifies exact transformation before rendering')
    parser.add_argument('--workbench-url', help='Optional workbench origin for the original failed Trace link')
    build(parser.parse_args())
