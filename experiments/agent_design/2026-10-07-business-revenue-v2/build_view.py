"""Separate explicitly selected business structures and disclosed revenue data."""
from __future__ import annotations
import argparse
import gzip
import importlib.util
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from lxml import html as lhtml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('business_view_v1', Path(__file__).parent.parent/'2026-10-07-business-map-mermaid-v1/build_view.py')
view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(view)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('revenue_number_required')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('revenue_number_required') from None
    if not result.is_finite():
        raise ValueError('finite_revenue_required')
    return result


def validate_revenue(path, maps):
    data = json.loads(path.read_text())
    for field in ('company_id', 'document_id', 'period_end', 'currency', 'unit',
                  'source_local_path', 'source_sha256', 'source_url', 'evidence', 'charts'):
        if not data.get(field):
            raise ValueError('revenue_missing_scope: '+field)
    scope = next((m for m in maps if m['company_id'] == data['company_id']), None)
    if scope is None or data['document_id'] != scope['document_id'] or data['period_end'] != scope['metadata']['period_end']:
        raise ValueError('revenue_scope_mismatch')
    if data['source_sha256'] != scope['metadata']['source_sha256']:
        raise ValueError('revenue_source_mismatch')
    if data['currency'] != 'USD' or data['unit'] != 'million':
        raise ValueError('unsupported_revenue_unit')
    source = view.local_path(data['source_local_path'])
    raw = gzip.decompress(source.read_bytes()) if source.suffix == '.gz' else source.read_bytes()
    if view.hashlib.sha256(raw).hexdigest() != data['source_sha256']:
        raise ValueError('revenue_source_hash_mismatch')
    norm = lambda t: ' '.join(t.split())
    source_dom = lhtml.fromstring(raw)
    source_texts = [norm(s.join(source_dom.itertext())) for s in ('', ' ')]
    evidence = {e['id']: e for e in data['evidence']}
    if len(evidence) != len(data['evidence']):
        raise ValueError('duplicate_revenue_evidence')
    targets = {}
    for e in evidence.values():
        if not e.get('exact_quote') or not e.get('fragment'):
            raise ValueError('revenue_precise_evidence_required')
        target = view.local_path(e['local_path'])
        if target not in targets:
            targets[target] = lhtml.fromstring(target.read_bytes())
        matches = targets[target].xpath('//*[@id=$f or @name=$f]', f=e['fragment'])
        if len(matches) != 1 or norm(e['exact_quote']) not in norm(' '.join(matches[0].itertext())):
            raise ValueError('revenue_anchor_quote_mismatch')
        if not any(norm(e['exact_quote']) in text for text in source_texts):
            raise ValueError('revenue_quote_not_in_source')
    def refs(ids):
        if not isinstance(ids, list) or not ids or any(e not in evidence for e in ids):
            raise ValueError('revenue_evidence_reference')
    def bound_amount(value, evidence_id, cited_ids):
        if not evidence_id or evidence_id not in cited_ids or evidence_id not in evidence:
            raise ValueError('revenue_amount_binding_required')
        e = evidence[evidence_id]
        if not e.get('source_cell_dom_path') or not e.get('source_cell_text'):
            raise ValueError('revenue_source_cell_required')
        cells = source_dom.xpath(e['source_cell_dom_path'])
        if len(cells) != 1 or not hasattr(cells[0], 'itertext'):
            raise ValueError('revenue_source_cell_not_unique')
        raw_cell = norm(''.join(cells[0].itertext()))
        if raw_cell != e['source_cell_text']:
            raise ValueError('revenue_source_cell_text_mismatch')
        token = raw_cell
        parenthesized = token.startswith('(') and token.endswith(')')
        if parenthesized:
            token = token[1:-1]
        if not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', token) or parenthesized and token.startswith('-'):
            raise ValueError('unsupported_revenue_cell_number')
        amount = Decimal(token.replace(',', '')) * (-1 if parenthesized else 1)
        if number(value) != amount:
            raise ValueError('revenue_amount_differs_from_source_cell')
    chart_ids = set()
    for chart in data['charts']:
        for field in ('id', 'title', 'denominator_label', 'chart_type', 'total',
                      'total_evidence_ids', 'parts', 'adjustments'):
            if field not in chart:
                raise ValueError('revenue_chart_missing_field: '+field)
        if not chart.get('id') or chart['id'] in chart_ids:
            raise ValueError('duplicate_revenue_chart')
        chart_ids.add(chart['id'])
        if not chart.get('title') or not chart.get('denominator_label') or chart.get('chart_type') not in ('bar', 'donut'):
            raise ValueError('revenue_chart_scope_required')
        total = number(chart['total'])
        if total <= 0:
            raise ValueError('positive_revenue_denominator_required')
        refs(chart['total_evidence_ids'])
        bound_amount(chart['total'], chart.get('total_amount_evidence_id'), chart['total_evidence_ids'])
        parts = chart['parts']; adjustments = chart['adjustments']
        if not isinstance(parts, list) or not parts or not isinstance(adjustments, list):
            raise ValueError('revenue_parts_required')
        ids = set()
        for row in parts + adjustments + chart.get('reported_subtotals', []):
            if any(field not in row for field in ('id', 'label', 'value', 'evidence_ids')):
                raise ValueError('revenue_row_missing_field')
            if not row.get('id') or row['id'] in ids or not row.get('label'):
                raise ValueError('duplicate_or_empty_revenue_row')
            ids.add(row['id']); number(row['value']); refs(row['evidence_ids'])
            bound_amount(row['value'], row.get('amount_evidence_id'), row['evidence_ids'])
        if sum((number(p['value']) for p in parts + adjustments), Decimal(0)) != total:
            raise ValueError('revenue_does_not_reconcile')
        if any(number(p['value']) < 0 for p in parts):
            raise ValueError('negative_amount_belongs_in_adjustments')
        if chart['chart_type'] == 'donut' and adjustments:
            raise ValueError('donut_cannot_include_adjustments')
    for subtotal in data.get('reported_subtotals', []):
        refs(subtotal.get('evidence_ids'))
        bound_amount(subtotal.get('value'), subtotal.get('amount_evidence_id'), subtotal['evidence_ids'])
        components = subtotal.get('component_ids', [])
        if not components or len(set(components)) != len(components):
            raise ValueError('subtotal_components_required')
        scopes = [c for c in data['charts'] if set(components) <= {p['id'] for p in c['parts']}]
        if len(scopes) != 1:
            raise ValueError('subtotal_scope_ambiguous')
        actual = sum((number(p['value']) for p in scopes[0]['parts'] if p['id'] in components), Decimal(0))
        if actual != number(subtotal['value']):
            raise ValueError('subtotal_does_not_reconcile')
    return data


def build(inputs, revenues, output, with_svg=False):
    output.mkdir(parents=True, exist_ok=True)
    assets = output/'assets'; assets.mkdir(exist_ok=True)
    maps = []
    for path in inputs:
        data, _ = view.validate(path)
        if any(n['kind'] == 'revenue_line' for n in data['businesses']) or any(e['kind'] == 'revenue_component_of' for e in data['relationships']):
            raise ValueError('business_graph_contains_revenue_dimension: '+data['company_id'])
        maps.append(data)
    if len({m['company_id'] for m in maps}) != len(maps):
        raise ValueError('duplicate_company_scope')
    revenue_by_company = {}
    for path in revenues:
        data = validate_revenue(path, maps)
        if data['company_id'] in revenue_by_company:
            raise ValueError('duplicate_revenue_company')
        revenue_by_company[data['company_id']] = {**data, 'json_href':view.link(path, output)}
        for e in data['evidence']:
            e['href'] = view.link(view.local_path(e['local_path']), output, e['fragment'])
    sections = []; checks = []; public_maps = []
    for path, data in zip(inputs, maps):
        mmd, ids = view.mermaid(data)
        company = data['company_id']; meta = data['metadata']
        (assets/(company+'.mmd')).write_text(mmd)
        (assets/(company+'-ids.json')).write_text(json.dumps(ids, ensure_ascii=False, indent=2)+'\n')
        diagram_path = assets/(company+'.svg')
        public = {**data, 'presentation_edges':view.presentation_edges(data), 'layer_ranks':view.layer_ranks(data),
                  'source_href':view.link(view.local_path(meta.get('source_html_path', meta['source_local_path'])), output),
                  'json_href':view.link(path, output), 'readme_href':view.link(path.parent/'README.zh-CN.md', output),
                  'revenue':revenue_by_company.get(company)}
        for e in public['evidence']:
            loc = meta['evidence_locators'][e['id']]
            e['href'] = view.link(view.local_path(loc['local_path']), output, loc['fragment'])
            e['quote'] = loc['exact_quote']
        public_maps.append(public)
        if with_svg:
            svg = view.inline_svg(diagram_path, data, ids)
            sections.append(f'<section class="map-section" data-company="{view.escaped(company)}" hidden><div class="diagram-scroll" tabindex="0" aria-label="{view.escaped(company)}业务结构图">{svg}</div></section>')
        checks.append({'company_id':company, 'nodes':len(data['businesses']), 'relationships':len(data['relationships']),
                       'input_sha256':view.sha(path), 'mermaid_sha256':view.sha(assets/(company+'.mmd')),
                       'svg_sha256':view.sha(diagram_path) if with_svg else None,
                       'revenue_charts':len(public['revenue']['charts']) if public['revenue'] else 0})
    if with_svg:
        template = Path(__file__).with_name('view-template.html').read_text()
        payload = json.dumps(public_maps, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
        (output/'index.html').write_text(template.replace('<!-- DIAGRAMS -->', ''.join(sections)).replace('/* DATA */', payload))
    result = {'schema_version':'business-revenue-review-v2', 'model_api_calls':0, 'cases':checks,
              'checks':['Explicit company/document/period/source', 'Separate business and revenue dimensions',
                        'Exact evidence anchors and source quotes', 'Amounts match explicitly bound source cells',
                        'Amounts reconcile including signed adjustments',
                        'Donut requires nonnegative complete parts without adjustments'],
              'not_claimed':['Production agent extraction', 'Full filing coverage', 'User visual acceptance', 'Claude review this iteration']}
    (output/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'cases':len(maps),'revenue_cases':len(revenue_by_company),'with_svg':with_svg}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maps', type=Path, nargs='+', required=True)
    parser.add_argument('--revenues', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-svg', action='store_true')
    args = parser.parse_args()
    build(args.maps, args.revenues, args.output, args.with_svg)
