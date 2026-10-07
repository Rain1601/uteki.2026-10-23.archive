"""Bind visible inline-number locators against immutable v0.1.12 report blocks.

This checks exact source offsets, not financial fact correctness or model quality.
No network or model calls; no changes to the selected existing packages.
"""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'src'))
from lxml import html
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _visible_text
from uteki.infrastructure.research_data.financial_records import digest, dom_path_query
from uteki.infrastructure.research_data.semantic_anchors import build_record_anchors_v3

PREVIOUS = ROOT/'experiments/agent_design/2026-10-07-foundation-parallel-v1/parser'
spec = importlib.util.spec_from_file_location('frozen_cases', PREVIOUS/'verify.py')
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
out = Path(__file__).parent


def run(label, raw_path, identity):
    raw = raw_path.read_bytes()
    assert digest(raw) == identity['raw_sha256']
    folder = PREVIOUS/'packages'/label
    blocks = [json.loads(line) for line in (folder/'blocks.jsonl').read_text().splitlines()]
    changes = json.loads((PREVIOUS/'verification.json').read_text())['cases'][label]['changes']
    changed_paths = {c['dom_path'] for c in changes}
    tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
    by_element = {tree.xpath(dom_path_query(b['dom_path']))[0]: b for b in blocks}
    sid = identity['source_snapshot_id']
    records = []
    selected = {}
    for fact in tree.iter():
        if not isinstance(fact.tag, str) or fact.tag.lower() != 'ix:nonfraction':
            continue
        block = next((by_element[e] for e in (fact, *fact.iterancestors()) if e in by_element), None)
        if block is None or block['dom_path'] not in changed_paths:
            continue
        quote = normalize_text(_visible_text(fact, preserve_line_breaks=True))
        if not quote:
            continue
        fact_path = tree.getroottree().getpath(fact)
        rid = 'dom-probe-'+digest(fact_path.encode())[:24]
        selected[block['block_id']] = {**block, 'source_snapshot_id': sid}
        records.append({'record': {'record_id': rid, 'source_snapshot_id': sid,
            'evidence_ids': ['ev-'+rid], 'status': 'candidate'},
            'evidence': {'source_snapshot_id': sid, 'source_sha256': digest(raw),
                'evidence_id': 'ev-'+rid, 'block_id': block['block_id'],
                'dom_path': block['dom_path'], 'fact_dom_path': fact_path, 'quote': quote}})
    packet = {'scope': {'snapshot_id': 'dom-anchor-adaptation-'+sid,
            'company_ids': [identity['company_id']], 'source_snapshot_ids': [sid],
            'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2026-10-07',
            'include_candidates': True},
        'source': {'source_snapshot_id': sid, 'company_id': identity['company_id'],
                   'source_sha256': digest(raw)},
        'source_blocks': list(selected.values()), 'records': records}
    before = build_record_anchors_v3(packet, raw)
    packet['parser_version'] = 'sec-source-blocks-v0.1.12'
    after = build_record_anchors_v3(packet, raw)
    assert records, 'explicit selected material needs at least one affected visible inline fact'
    assert all(a['status'] == 'located' for a in after.values()), after
    return {'source': identity, 'raw_path': str(raw_path.relative_to(ROOT)),
        'parser_version': packet['parser_version'], 'affected_blocks_with_inline_facts': len(selected),
        'visible_inline_fact_probes': len(records),
        'located_before': sum(a['status'] == 'located' for a in before.values()),
        'located_after': sum(a['status'] == 'located' for a in after.values()),
        'bindings': [{'record_probe_id': rid, 'before': before[rid], 'after': after[rid]}
                     for rid in after],
        'source_unchanged': digest(raw_path.read_bytes()) == identity['raw_sha256'],
        'probe_inputs_sha256': digest(packet)}


result = {'schema_version': 'parser-consumer-acceptance-v1', 'model_calls': 0,
    'network_requests': 0, 'mode': 'real_frozen_source_dom_locator_check',
    'cases': {label: run(label, *value) for label, value in cases.inputs().items()},
    'limitations': ['DOM probes are not financially normalized records or model extractions.',
        'This verifies affected visible inline-fact locators, not unit/footnote semantics.',
        'NVIDIA PDF has no inline XBRL DOM and is outside this adapter scope.',
        'Historical source, dataset and parser packages remain unchanged.']}
(out/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({label: {k: value[k] for k in ('affected_blocks_with_inline_facts',
    'visible_inline_fact_probes', 'located_before', 'located_after')} for label, value in result['cases'].items()}, indent=2))
