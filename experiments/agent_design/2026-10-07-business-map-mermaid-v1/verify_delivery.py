"""Read-only structural verification of an explicitly selected diagram delivery.

Writes only --report. It does not render graphs or exercise browser interactions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit
import urllib.request
import xml.etree.ElementTree as ET

from lxml import html
from uteki.domain.business_map.models import business_map_from_dict

ROOT = Path(__file__).resolve().parents[3]
INVERSE = {'part_of': '包含', 'reported_under': '报告中列示',
           'revenue_component_of': '收入构成', 'supports': '支撑来自'}
ARCHIVE_FILES = ('README.zh-CN.md', 'business-map.mmd', 'business-map.svg',
                 'business_map.json', 'id-map.json', 'input.txt', 'source.html',
                 'verification.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def archive_check(folder):
    require({p.name for p in folder.iterdir()} == set(ARCHIVE_FILES), 'archive_file_set')
    data = json.loads((folder / 'business_map.json').read_text())
    business_map_from_dict(data)
    supports = [e for e in data['relationships'] if e['kind'] == 'supports']
    require(len(data['businesses']) == len(data['relationships']) == 6, 'archive_graph_counts')
    require(len(supports) == 2 and len({e['source_id'] for e in supports}) == 1
            and len({e['target_id'] for e in supports}) == 2, 'archive_shared_support')
    require(len([n for n in data['businesses'] if n['kind'] == 'reportable_segment']) == 2,
            'archive_segment_count')
    original = json.loads((folder / 'verification.json').read_text())
    for name, expected in original['artifact_sha256'].items():
        if name in ARCHIVE_FILES:
            require(sha(folder / name) == expected, 'archive_original_hash: ' + name)
    source = html.parse(str(folder / 'source.html'))
    for evidence in data['evidence']:
        loc = data['metadata']['evidence_locators'][evidence['id']]
        matches = source.xpath('//*[@id=$fragment]', fragment=loc['fragment'])
        require(len(matches) == 1 and matches[0].text == loc['exact_quote'], 'archive_evidence')
        require(hashlib.sha256(matches[0].text.encode()).hexdigest() == evidence['text_hash'],
                'archive_paragraph_hash')
    svg = ET.parse(folder / 'business-map.svg').getroot()
    nodes = [n for n in svg.iter() if n.tag.endswith('}g') and 'node' in n.get('class', '').split()]
    edges = [n for n in svg.iter() if 'flowchart-link' in n.get('class', '').split()]
    require(len(nodes) == len(edges) == 6, 'archive_svg_counts')
    return {'path': str(folder.relative_to(ROOT)), 'nodes': 6, 'relationships': 6,
            'supports': 2, 'files': {name: sha(folder / name) for name in ARCHIVE_FILES},
            'original_snapshot_bytes_preserved': True,
            'note': 'Exact eight-file snapshot. Original /tmp provenance paths and renderer-config hash are retained; no path rewrite, browser profile, or renderer config copy.'}


def verify(page, node_binary, archive=None, http_base=None):
    page = page.resolve()
    output = page.parent
    tree = html.parse(str(page))
    payload = tree.xpath('//script[@id="map-data"]')
    require(len(payload) == 1, 'one_payload_required')
    maps = json.loads(payload[0].text)
    require(len(maps) == 4, 'four_cases_required')
    all_ids = tree.xpath('//*[@id]/@id')
    require(len(all_ids) == len(set(all_ids)), 'duplicate_page_dom_ids')
    links, parsed_targets = [], {}

    def check_link(value, owner):
        url = urlsplit(value)
        if url.scheme or url.netloc:
            return
        target = (output / unquote(url.path)).resolve() if url.path else page
        directory_index = target.is_dir()
        if directory_index:
            target = target / 'index.html'
        require(target.is_file(), 'missing_local_link: ' + value)
        if url.fragment:
            if target not in parsed_targets:
                parsed_targets[target] = html.parse(str(target))
            matches = parsed_targets[target].xpath('//*[@id=$f or @name=$f]', f=unquote(url.fragment))
            require(len(matches) == 1, 'missing_or_duplicate_fragment: ' + value)
        links.append({'owner': owner, 'href': value, 'resolved_path': str(target.relative_to(ROOT)),
                      'fragment': unquote(url.fragment) or None, 'directory_index': directory_index})

    def data_links(value, owner):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and (key == 'href' or key.endswith('_href')):
                    check_link(child, owner + ':' + key)
                else:
                    data_links(child, owner + ':' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                data_links(child, owner + ':' + str(index))

    for element in tree.xpath('//*[@href or @src]'):
        for key in ('href', 'src'):
            if element.get(key):
                check_link(element.get(key), 'page:' + element.tag)
    data_links(maps, 'payload')
    cases = []
    for data in maps:
        business_map_from_dict(data)
        cid = data['company_id']
        ids = {n['id']: f'N{i:03}' for i, n in enumerate(data['businesses'])}
        reverse = {value: key for key, value in ids.items()}
        source = (output / urlsplit(data['json_href']).path).resolve()
        original = json.loads(source.read_text())
        clean = {key: data[key] for key in original}
        original_evidence = {e['id']: e for e in original['evidence']}
        clean['evidence'] = [{key: e[key] for key in original_evidence[e['id']]} for e in data['evidence']]
        require(clean == original, 'payload_differs_from_input: ' + cid)
        expected = []
        for edge in data['relationships']:
            market = (edge['kind'] == 'supports'
                      and data['metadata'].get('node_roles', {}).get(edge['target_id']) == 'market')
            expected.append({'source': edge['source_id'] if market else edge['target_id'],
                             'target': edge['target_id'] if market else edge['source_id'],
                             'label': '面向市场' if market else INVERSE[edge['kind']],
                             'kind': edge['kind'], 'evidence_ids': edge['evidence_ids']})
        require(data['presentation_edges'] == expected, 'presentation_semantics: ' + cid)
        sections = tree.xpath('//section[@data-company=$cid]', cid=cid)
        require(len(sections) == 1, 'one_svg_section: ' + cid)
        nodes = sections[0].xpath('.//*[@data-node-id]')
        require(Counter(n.get('data-node-id') for n in nodes) == Counter(ids.keys()), 'svg_node_set: ' + cid)
        for node in nodes:
            nid = node.get('data-node-id')
            require(re.fullmatch(re.escape(cid) + '-flowchart-' + ids[nid] + r'-\d+', node.get('id')),
                    'svg_node_mapping: ' + cid)
            item = next(n for n in data['businesses'] if n['id'] == nid)
            label = data['metadata'].get('node_labels', {}).get(nid, {}).get('zh') or item['name']
            actual = ''.join(''.join(t.itertext()) for t in node.xpath('.//text'))
            require(''.join(actual.split()) == ''.join(label.split()), 'svg_label: ' + cid + ':' + nid)
        paths = sections[0].xpath('.//path[contains(concat(" ",normalize-space(@class)," ")," flowchart-link ")]')
        pairs = []
        for path in paths:
            match = re.fullmatch(re.escape(cid) + r'-L_(N\d+)_(N\d+)_\d+', path.get('id'))
            require(match is not None, 'svg_edge_id: ' + cid)
            pairs.append((reverse[match[1]], reverse[match[2]]))
        require(Counter(pairs) == Counter((e['source'], e['target']) for e in expected), 'svg_edges: ' + cid)
        ranks = data['layer_ranks']
        require(ranks is not None and set(ranks) == set(ids), 'layer_node_coverage: ' + cid)
        require(all(ranks[e['source']] < ranks[e['target']] for e in expected), 'layer_edge_order: ' + cid)
        mermaid = output / 'assets' / (cid + '.mmd')
        svg = output / 'assets' / (cid + '.svg')
        for suffix in ('mmd', 'svg'):
            check_link('assets/' + cid + '.' + suffix, 'generated_download')
        mermaid_edges = []
        for line in mermaid.read_text().splitlines():
            match = re.fullmatch(r'\s*(N\d+)\s+(-->|-\.->)\|"(.*?)"\|\s+(N\d+)', line)
            if match:
                mermaid_edges.append((reverse[match[1]], reverse[match[4]], match[3], match[2]))
        require(Counter(mermaid_edges) == Counter((e['source'], e['target'], e['label'], '-.->' if e['kind'] == 'supports' else '-->') for e in expected), 'mermaid_edges: ' + cid)
        standalone = ET.parse(svg).getroot()
        asset_nodes = [e for e in standalone.iter() if 'node' in e.get('class', '').split()]
        asset_edges = [e for e in standalone.iter() if 'flowchart-link' in e.get('class', '').split()]
        require(len(asset_nodes) == len(ids) and len(asset_edges) == len(expected), 'standalone_svg_counts: ' + cid)
        cases.append({'company_id': cid, 'nodes': len(ids), 'relationships': len(expected),
                      'supports': sum(e['kind'] == 'supports' for e in expected),
                      'layers': max(ranks.values()) + 1, 'evidence': len(data['evidence']),
                      'payload_matches_input': True, 'svg_node_mapping_and_labels_match': True,
                      'all_relationships_preserved_in_payload_mermaid_svg': True,
                      'map_sha256': sha(source), 'svg_sha256': sha(svg), 'mermaid_sha256': sha(mermaid)})
    marker_refs = re.findall(r'url\(#([^\)]+)\)', page.read_text())
    require(all(ref in all_ids for ref in marker_refs), 'unresolved_svg_marker')
    scripts = tree.xpath('//script[not(@type) or @type="text/javascript"]')
    require(bool(scripts), 'missing_page_script')
    with tempfile.TemporaryDirectory(prefix='uteki-delivery-check-', dir='/tmp') as temp:
        for i, script in enumerate(scripts):
            path = Path(temp) / f'page-{i}.js'
            path.write_text(script.text or '')
            result = subprocess.run([node_binary, '--check', str(path)], capture_output=True, text=True)
            require(result.returncode == 0, 'javascript_syntax: ' + result.stderr)
    totals = {'cases': len(cases), 'nodes': sum(c['nodes'] for c in cases),
              'relationships': sum(c['relationships'] for c in cases), 'evidence': sum(c['evidence'] for c in cases),
              'unique_dom_ids': len(all_ids), 'duplicate_dom_ids': 0, 'local_hrefs': len(links),
              'fragment_links': sum(bool(link['fragment']) for link in links), 'marker_references': len(marker_refs)}
    require(totals['nodes'] == 59 and totals['relationships'] == 66, 'delivery_totals')
    report = {'schema_version': 'business-map-delivery-check-v1', 'status': 'passed',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'verifier_sha256': sha(Path(__file__)),
              'page': str(page.relative_to(ROOT)), 'page_sha256': sha(page), 'cases': cases, 'totals': totals,
              'javascript_node_check': {'exit_code': 0, 'inline_scripts': len(scripts)},
              'local_links': links, 'directory_index_links_supported': True,
              'not_run': ['browser_visual_review', 'browser_interaction_tests', 'external_source_url_checks',
                          'recursive_crawl_of_original_filing_resources', 'model_api_calls'],
              'scope_note': 'Structural, file/anchor, syntax and optional loopback HEAD checks only. No claim of visual acceptance or interactive behavior.'}
    if archive:
        report['skill_forward_check'] = archive_check(archive.resolve())
    if http_base:
        parsed = urlsplit(http_base)
        require(parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port == 8769,
                'explicit_loopback_8769_required')
        paths = ['index.html'] + ['assets/' + c['company_id'] + '.' + ext for c in cases for ext in ('svg', 'mmd')]

        def head(path):
            request = urllib.request.Request(http_base.rstrip('/') + '/' + path, method='HEAD')
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                    return {'path': path, 'status': response.status, 'content_type': response.headers.get('Content-Type'),
                            'content_length': response.headers.get('Content-Length')}
            except Exception as error:
                return {'path': path, 'error_type': type(error).__name__}

        with ThreadPoolExecutor(max_workers=4) as pool:
            report['http_head'] = list(pool.map(head, paths))
        if not all(row.get('status') == 200 for row in report['http_head']):
            report['status'] = 'http_check_failed'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--skill-check', type=Path)
    parser.add_argument('--http-base')
    args = parser.parse_args()
    result = verify(args.page, args.node, args.skill_check, args.http_base)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'totals': result['totals']}, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
