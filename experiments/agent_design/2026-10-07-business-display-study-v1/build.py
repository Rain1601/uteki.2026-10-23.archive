"""Bound NVIDIA display study. Reads saved artifacts; no source/model calls."""
from __future__ import annotations
from collections import Counter
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import quote

from lxml import html

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN = ROOT / 'experiments/agent_design/2026-10-07-nvidia-business-revenue-v1/derived-01-single-fence'
REVIEW = RUN.parent / 'evaluation/semantic-review.json'
ENRICHMENT = ROOT / 'experiments/agent_design/2026-10-07-official-product-links-v1/nvidia-ai-enterprise.json'
OUTPUT = ROOT / 'docs/design/data-agent-acceptance/business-display-study-v1/index.html'
BASELINE = ROOT / 'docs/design/data-agent-acceptance/nvidia-business-revenue-v1/index.html'
spec = importlib.util.spec_from_file_location('saved_product_view_validation', HERE.parent / '2026-10-07-agent-business-revenue-v1/build_view.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
read = validator.read_json
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
edge_key = lambda e: '|'.join(e[k] for k in ('source_id', 'kind', 'target_id'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def link(path, fragment=None):
    path = path.resolve()
    require(path.is_relative_to(ROOT) and path.is_file(), 'missing_or_outside_local_link')
    if fragment:
        require(len(html.fromstring(path.read_bytes()).xpath('//*[@id=$id]', id=fragment)) == 1, 'evidence_anchor_missing_or_ambiguous')
    href = quote(os.path.relpath(path, OUTPUT.parent), safe='/')
    return href + ('#' + quote(fragment) if fragment else '')


def prepare():
    map_path = RUN / 'business_map.json'
    data = read(map_path)
    annotations = read(HERE / 'display_annotations.json')
    expected = {k: data[k] for k in ('company_id', 'document_id')}
    expected.update(period_end=data['metadata']['period_end'], business_map_sha256=sha(map_path), semantic_review_sha256=sha(REVIEW))
    require(annotations.get('binding') == expected, 'study_annotation_binding_mismatch')
    result = read(RUN / 'result.json')
    require(result['artifacts_sha256']['business_map.json'] == sha(map_path), 'frozen_map_hash_mismatch')
    # Reuse source/fragment validation without changing the shared renderer.
    validator.validate_agent(map_path, RUN / 'source_packet.json', RUN / 'skill.md', recovered=True)
    review = read(REVIEW)
    require(all(review['binding'].get(k) == expected[k] for k in ('company_id', 'document_id', 'period_end', 'business_map_sha256')), 'review_scope_mismatch')
    enrichment = validator.safe_enrichment(ENRICHMENT, data, map_path)
    nodes = {n['id']: n for n in data['businesses']}
    require(len(nodes) == len(data['businesses']), 'duplicate_node_id')
    markets = [n['id'] for n in data['businesses'] if data['metadata']['node_roles'].get(n['id']) == 'market']
    segments = [n['id'] for n in data['businesses'] if n['kind'] == 'reportable_segment']
    companies = [n['id'] for n in data['businesses'] if n['kind'] == 'company']
    products = [n['id'] for n in data['businesses'] if n['id'] not in markets + segments + companies]
    require((len(companies), len(markets), len(segments), len(products)) == (1, 4, 2, 12), 'unexpected_frozen_node_roles')
    edges = data['relationships']
    require(len({edge_key(e) for e in edges}) == len(edges), 'duplicate_relationship')
    require(Counter(e['kind'] for e in edges) == {'reported_under': 13, 'part_of': 9, 'supports': 2}, 'unexpected_relationship_coverage')
    by_key = {edge_key(e): e for e in edges}
    inference = {}
    checks = {c['id'] for c in review['checks']}
    for item in annotations['inferred_relationships']:
        key = edge_key(item)
        require(key in by_key and item['review_check_id'] in checks and key not in inference, 'invalid_inference_annotation')
        inference[key] = item['note']
    require(len(inference) == 3, 'three_explicit_review_annotations_required')
    warnings = {}
    for item in annotations['node_warnings']:
        require(item['business_id'] in nodes and item['review_check_id'] in checks, 'invalid_node_warning')
        warnings[item['business_id']] = item['note']
    require(set(annotations['market_excerpts']) == set(markets), 'market_excerpt_coverage')
    for ident, excerpt in annotations['market_excerpts'].items():
        require(excerpt and excerpt in nodes[ident]['description'], 'excerpt_not_in_original_description')
    market_edges = [e for e in edges if e['kind'] == 'part_of']
    report_edges = [e for e in edges if e['kind'] == 'reported_under']
    support_edges = [e for e in edges if e['kind'] == 'supports']
    require(all(e['source_id'] in products and e['target_id'] in markets for e in market_edges), 'unexpected_market_edge_scope')
    require(all((e['source_id'] in products and e['target_id'] in segments) or (e['source_id'] in segments and e['target_id'] in companies) for e in report_edges), 'unexpected_report_edge_scope')
    require({(e['source_id'], e['target_id']) for e in support_edges} == {('dc_compute', 'drive_hyperion'), ('omniverse', 'drive_hyperion')}, 'support_direction_mismatch')
    missing_market = [p for p in products if not any(e['source_id'] == p for e in market_edges)]
    missing_segment = [p for p in products if not any(e['source_id'] == p for e in report_edges)]
    require(set(missing_market) == {'jetson_embedded', 'vgpu_software', 'auto_infotainment'}, 'market_gap_coverage_mismatch')
    require(missing_segment == ['nvidia_ai_enterprise'], 'report_gap_coverage_mismatch')
    public_nodes = copy.deepcopy(data['businesses'])
    evidence = []
    for e in data['evidence']:
        item = {k: e[k] for k in ('id', 'section_path', 'source_dom_path', 'exact_quote')}
        item['href'] = link(ROOT / e['local_path'], e['fragment'])
        evidence.append(item)
    links = {'baseline': link(BASELINE), 'review': link(REVIEW), 'enrichment': link(ENRICHMENT),
             'map': link(map_path), 'annotations': link(HERE / 'display_annotations.json'), 'research': link(HERE / 'RESEARCH.zh-CN.md')}
    payload = {'scope': {**expected, 'source_sha256': data['metadata']['source_sha256'], 'report_label': data['metadata']['report_label']},
        'nodes': public_nodes, 'relationships': copy.deepcopy(edges), 'company': companies[0], 'markets': markets,
        'segments': segments, 'products': products, 'missing_market': missing_market, 'missing_segment': missing_segment,
        'market_excerpts': annotations['market_excerpts'], 'inference': inference, 'warnings': warnings,
        'evidence': evidence, 'enrichment': enrichment, 'links': links}
    return payload


def build():
    payload = prepare()
    template = HERE / 'template.html'
    text = template.read_text().replace('/* DATA */', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026'))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text)
    verification = {'schema_version': 'business-display-study-v1', 'binding': payload['scope'],
        'fingerprints': {'business_map': sha(RUN / 'business_map.json'), 'enrichment': sha(ENRICHMENT), 'review': sha(REVIEW),
                         'annotations': sha(HERE / 'display_annotations.json'), 'builder': sha(Path(__file__)), 'template': sha(template), 'html': sha(OUTPUT)},
        'coverage': {'nodes': len(payload['nodes']), 'products': len(payload['products']), 'markets': len(payload['markets']),
            'segments': len(payload['segments']), 'report_edges': 13, 'market_edges': 9, 'support_edges': 2,
            'inferred_report_edges': 1, 'inferred_market_edges': 2, 'matrix_cells': 48,
            'unrecorded_market_cells': 39, 'missing_market': payload['missing_market'], 'missing_direct_segment': payload['missing_segment']},
        'checks': ['frozen scope and map hash', 'independent review and explicit annotation binding', 'original source/evidence fragment validation',
                   'market excerpt is exact substring of model description', 'all node IDs in exactly one role', 'all 24 edges assigned to one view or support list',
                   'support direction preserved', 'no transitive segment or market assignment', 'official supplement bindings'],
        'model_api_calls': 0, 'source_fetches': 0, 'original_artifacts_modified': False,
        'not_claimed': ['full filing or technology-stack coverage', 'model semantic errors repaired', 'production workflow integration', 'visual review']}
    (HERE / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(OUTPUT), 'coverage': verification['coverage']}, ensure_ascii=False))


if __name__ == '__main__':
    build()
