"""Freeze business inputs selected and actually read by the system Data Agent.

The caller supplies no chapter, block list or text. Selection comes from a sealed
query run and is checked against its scoped source index and body-delivery ledger.
This establishes indexed coverage, never semantic completeness of the question.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle

VERSION = 'runtime-indexed-sections-v1'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def _file(root, name):
    root = Path(root).resolve()
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('runtime_material_path_outside_root')
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
        raise ValueError('runtime_material_symlink')
    if not path.is_file():
        raise ValueError('runtime_material_file_missing: ' + str(name))
    return path


def _manifest(root):
    raw = _file(root, 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('runtime_frozen_manifest_required')
    for name, sha in files.items():
        if _sha(_file(root, name).read_bytes()) != sha:
            raise ValueError('runtime_frozen_file_changed: ' + name)
    return manifest, _sha(raw)


def validate_runtime_scope(packet, blocks):
    """In-memory shape checks; verify_runtime_packet rechecks frozen source bytes."""
    scope = packet.get('extraction_scope', {})
    if (scope.get('kind') != VERSION or scope.get('coverage_claim') != 'selected_indexed_sections_only'
            or scope.get('semantic_completeness') != 'not_evaluated'):
        raise ValueError('runtime_material_scope_invalid')
    nodes = scope.get('selected_nodes')
    ids = scope.get('section_block_ids')
    if (not isinstance(nodes, list) or not nodes or not isinstance(ids, list) or not ids
            or len(ids) != len(set(ids)) or set(ids) != set(blocks)
            or any(b.get('input_role') != 'selected_subsection' for b in blocks.values())):
        raise ValueError('runtime_material_selection_invalid')
    node_ids = [n.get('node_id') for n in nodes]
    if any(not isinstance(n, str) or not n.strip() for n in node_ids) or len(node_ids) != len(set(node_ids)):
        raise ValueError('runtime_material_nodes_invalid')
    if (scope.get('filtered_block_ids') != [] or scope.get('financial_analysis') is not False
            or scope.get('scope_metadata_block_ids') != []):
        raise ValueError('runtime_material_may_not_filter_or_invent_context')
    return scope


def _select(index, blocks, node_ids):
    by_id = {b['block_id']: i for i, b in enumerate(blocks)}
    nodes = {n['node_id']: n for n in index['nodes']}
    if len(by_id) != len(blocks) or len(nodes) != len(index['nodes']):
        raise ValueError('runtime_index_duplicate_identity')
    selected, expected, picked = set(), {}, []
    for nid in node_ids:
        if nid not in nodes:
            raise ValueError('runtime_selected_node_missing')
        n = nodes[nid]
        if n['start_block_id'] not in by_id or n['end_block_id'] not in by_id:
            raise ValueError('runtime_node_boundary_missing')
        lo, hi = by_id[n['start_block_id']], by_id[n['end_block_id']] + 1
        if lo >= hi:
            raise ValueError('runtime_node_boundary_invalid')
        body = blocks[lo:hi]
        expected[nid] = [b['block_id'] for b in body
                         if b['type'] not in {'image', 'page_marker'} and not b.get('layout_role')]
        if not expected[nid]:
            raise ValueError('runtime_selected_node_has_no_body')
        selected.update(range(lo, hi))
        picked.append(deepcopy(n))
    return [blocks[i] for i in sorted(selected)], expected, picked


def _packet_blocks(selected, nodes):
    result = []
    for b in selected:
        # Image interpretation needs a separate capability; do not silently drop it.
        if b['type'] == 'image' or not isinstance(b.get('text'), str) or not b['text'].strip():
            raise ValueError('runtime_selected_nontext_block_unsupported')
        if not b.get('dom_path') or type(b.get('ordinal')) is not int:
            raise ValueError('runtime_html_index_locator_required')
        result.append(dict(id=b['block_id'], ordinal=b['ordinal'], type=b['type'], text=b['text'],
            text_sha256=_sha(' '.join(b['text'].split()).encode()), source_dom_path=b['dom_path'],
            section_path=[n.get('title') or n['node_id'] for n in nodes],
            reported_page=b.get('reported_page'), input_role='selected_subsection'))
    return result


def verify_runtime_packet(packet, root, source_manifest):
    """Bind packet selection to the copied original index, scope and identity."""
    scope = validate_runtime_scope(packet, {b['id']: b for b in packet['blocks']})
    ref = source_manifest.get('runtime_selection')
    if not isinstance(ref, dict):
        raise ValueError('runtime_selection_manifest_required')
    frozen = {}
    for key in ('index', 'blocks', 'selection_report'):
        item = ref.get(key, {})
        raw = _file(root, item.get('path', '')).read_bytes()
        if _sha(raw) != item.get('sha256'):
            raise ValueError('runtime_selection_artifact_changed: ' + key)
        frozen[key] = raw
    report = json.loads(frozen['selection_report'])
    if report.get('extraction_scope') != scope:
        raise ValueError('runtime_selection_scope_changed')
    for key in ('company_id', 'document_id', 'period_end', 'source_sha256'):
        if report.get(key) != packet.get(key):
            raise ValueError('runtime_selection_source_changed: ' + key)
    index = json.loads(frozen['index'])
    if index.get('index_id') != scope.get('index_id'):
        raise ValueError('runtime_selection_index_changed')
    original_blocks = [json.loads(line) for line in frozen['blocks'].splitlines()]
    selected, _, nodes = _select(index, original_blocks, [n['node_id'] for n in scope['selected_nodes']])
    if nodes != scope['selected_nodes'] or _packet_blocks(selected, nodes) != packet['blocks']:
        raise ValueError('runtime_packet_does_not_cover_selected_index')
    if scope['section_block_ids'] != [b['block_id'] for b in selected]:
        raise ValueError('runtime_packet_block_order_changed')
    raw = _file(root, packet['source_local_path']).read_bytes()
    if _sha(raw) != packet['source_sha256']:
        raise ValueError('runtime_source_changed')
    company = packet['company_id']
    if not re.fullmatch(r'sec-\d{10}', company) or packet.get('form_type') not in {'10-K', '10-K/A'}:
        raise ValueError('runtime_sec_html_10k_only')
    validate_sec_filing(raw, company[4:], packet['form_type'], packet['period_end'])
    return report


def build_runtime_packet(port, query_result, *, query_output, output, root, max_bytes):
    """Freeze only complete runtime-selected nodes from one scoped SEC HTML 10-K."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('runtime_material_explicit_max_bytes_required')
    root, query_output, output = Path(root).resolve(), Path(query_output).resolve(), Path(output).resolve()
    if not output.is_relative_to(root) or output == root or output.exists():
        raise ValueError('runtime_material_new_output_inside_root_required')
    if output.is_relative_to(query_output) or output.is_relative_to(port.dataset):
        raise ValueError('runtime_material_output_inside_frozen_input')
    query_manifest, query_sha = _manifest(query_output)
    if 'result.json' not in query_manifest['files'] or json.loads((query_output/'result.json').read_bytes()) != query_result:
        raise ValueError('runtime_query_result_not_frozen')
    scope = port.scope.model_dump(mode='json')
    if query_result.get('active_scope') != scope:
        raise ValueError('runtime_query_active_scope_mismatch')
    if (query_result.get('status') != 'evidence_ready' or query_result.get('gaps')
            or query_result.get('pending_body_reads') or query_result.get('role') != 'planner'
            or query_result.get('purpose') != 'business_materials'
            or query_result.get('semantic_completeness') != 'not_evaluated'
            or not query_result.get('plan_origin')):
        raise ValueError('runtime_query_complete_body_required')
    coverage = query_result.get('coverage', [])
    if (not coverage or any(r.get('kind') not in {'read_node', 'information'} for r in coverage)
            or any(r.get('gap_ids') for r in coverage)
            or any(r.get('kind') == 'information' and
                   (r.get('program_check') != 'references_present' or not r.get('evidence_ids')) for r in coverage)):
        raise ValueError('runtime_business_read_node_plan_required')
    rows = [r for r in coverage if r.get('kind') == 'read_node']
    if not rows:
        raise ValueError('runtime_business_read_node_plan_required')
    sids = {r.get('source_id') for r in rows}
    if len(sids) != 1:
        raise ValueError('runtime_multiple_sources_not_supported')
    sid = next(iter(sids))
    source = port._source(sid)
    if (source['company_id'] not in scope['company_ids'] or sid not in scope['source_snapshot_ids']
            or port._blocked_source(source)):
        raise ValueError('runtime_source_outside_scope')
    date.fromisoformat(source['period_end'])
    dataset_manifest, dataset_sha = _manifest(port.dataset)
    if 'sources.json' not in dataset_manifest['files']:
        raise ValueError('runtime_frozen_sources_missing')
    source_rows = json.loads(_file(port.dataset, 'sources.json').read_bytes())
    if [s for s in source_rows if s.get('source_snapshot_id') == sid] != [source]:
        raise ValueError('runtime_source_metadata_changed')
    for name in (source.get('raw_file'), str(Path(source['index_folder'])/'index.json'),
                 str(Path(source['index_folder'])/'blocks.jsonl')):
        if name not in dataset_manifest['files']:
            raise ValueError('runtime_source_file_not_frozen')
    raw_path = _file(port.dataset, source.get('raw_file', ''))
    raw = raw_path.read_bytes()
    if (source.get('form') not in {'10-K', '10-K/A'} or raw_path.suffix.lower() not in {'.html', '.htm'}
            or not re.fullmatch(r'sec-\d{10}', source['company_id'])):
        raise ValueError('runtime_sec_html_10k_only')
    if _sha(raw) != source['source_sha256']:
        raise ValueError('runtime_original_hash_mismatch')
    identity = validate_sec_filing(raw, source['company_id'][4:], source['form'], source['period_end'])
    reader, missing = port._navigation(source)
    if missing:
        raise ValueError('runtime_source_index_unavailable')
    if (reader.index.get('source_snapshot_id') != sid or reader.index.get('form_type') != source['form']):
        raise ValueError('runtime_source_index_identity_mismatch')
    if (reader.index != json.loads((reader.folder/'index.json').read_bytes())
            or reader.blocks != [json.loads(line) for line in (reader.folder/'blocks.jsonl').read_bytes().splitlines()]):
        raise ValueError('runtime_source_index_changed')
    node_ids = [r.get('node_id') for r in rows]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError('runtime_duplicate_selected_node')
    selected, expected, nodes = _select(reader.index, reader.blocks, node_ids)
    bundle = load_evidence_bundle(query_output)
    if bundle.get('bundle_id') != query_result.get('evidence_bundle', {}).get('bundle_id'):
        raise ValueError('runtime_evidence_bundle_mismatch')
    items = {e['evidence_id']: e for e in bundle['items']}
    by_id = {b['block_id']: b for b in reader.blocks}
    for row in rows:
        required = expected[row['node_id']]
        if (row.get('program_check') != 'body_complete' or row.get('inventory_status') != 'available'
                or row.get('inventory_snapshot_id') != scope['snapshot_id']
                or row.get('inventory_index_id') != source['index_id']
                or row.get('required_block_ids') != required or row.get('returned_block_ids') != required
                or row.get('unread_block_ids') or row.get('gap_ids')):
            raise ValueError('runtime_claimed_coverage_differs_from_index')
        delivered = set()
        for eid in row.get('evidence_ids', []):
            item = items.get(eid, {})
            value = item.get('value', {})
            if (item.get('kind') != 'context' or item.get('scope') != scope
                    or value.get('source_snapshot_id') != sid or value.get('index_id') != source['index_id']):
                continue
            actual = {b['block_id']: b for b in value.get('blocks', [])}
            for bid in bundle.get('delivered_body', {}).get(eid, []):
                if bid not in actual or bid not in by_id or actual[bid].get('text') != by_id[bid]['text']:
                    raise ValueError('runtime_delivered_body_differs_from_source')
                delivered.add(bid)
        if not set(required) <= delivered:
            raise ValueError('runtime_body_not_actually_delivered')
    packet_blocks = _packet_blocks(selected, nodes)
    extraction_scope = dict(kind=VERSION, title=' / '.join(n.get('title') or n['node_id'] for n in nodes),
        selected_nodes=nodes, index_id=source['index_id'], section_block_ids=[b['id'] for b in packet_blocks],
        scope_metadata_block_ids=[], filtered_block_ids=[], financial_analysis=False,
        coverage_claim='selected_indexed_sections_only', semantic_completeness='not_evaluated')
    rel = lambda name: str((output/name).relative_to(root))
    packet = dict(schema_version='source-packet-v1', company_id=source['company_id'],
        document_id=source['document_id'], period_end=source['period_end'],
        source_snapshot_id=sid, source_local_path=rel('original.html'), source_sha256=source['source_sha256'],
        source_url=source['source_url'], source_kind='official_sec_html', form_type=source['form'],
        extraction_scope=extraction_scope, blocks=packet_blocks, tables=[])
    report = dict(schema_version=VERSION, status='declared_materials_delivered',
        **{k: packet[k] for k in ('company_id','document_id','period_end','source_sha256')},
        plan_origin=query_result['plan_origin'], semantic_completeness='not_evaluated',
        selection_sufficiency='not_evaluated', question=query_result['request']['question'],
        selected_requirements=[{k: row[k] for k in ('requirement_id','description','source_id','node_id')}
                               for row in rows],
        plans=deepcopy(query_result.get('plans', [])),
        active_scope=scope, extraction_scope=extraction_scope, identity_validation=identity,
        query_manifest_sha256=query_sha, query_result_sha256=_sha((query_output/'result.json').read_bytes()),
        dataset_manifest_sha256=dataset_sha, required_body_block_count=len(set().union(*map(set, expected.values()))),
        selected_block_count=len(packet_blocks), limitations=['Indexed chapter coverage is not question completeness.',
            'No image interpretation or financial table-cell extraction; table original text is preserved.'])
    index_raw = (reader.folder/'index.json').read_bytes()
    blocks_raw = (reader.folder/'blocks.jsonl').read_bytes()
    artifacts = {'original.html': raw, 'index.json': index_raw, 'blocks.jsonl': blocks_raw,
                 'selection-report.json': _bytes(report)}
    source_manifest = dict(schema_version='runtime-business-source-manifest-v1',
        **{k: packet[k] for k in ('company_id','document_id','period_end','source_url','source_snapshot_id')},
        content_sha256=packet['source_sha256'], source_local_path=packet['source_local_path'],
        runtime_selection={key: dict(path=rel(name), sha256=_sha(artifacts[name]))
            for key, name in [('index','index.json'), ('blocks','blocks.jsonl'), ('selection_report','selection-report.json')]})
    artifacts['source-manifest.json'] = _bytes(source_manifest)
    packet['source_manifest'] = dict(local_path=rel('source-manifest.json'), sha256=_sha(artifacts['source-manifest.json']))
    artifacts['source_packet.json'] = _bytes(packet)
    if len(artifacts['source_packet.json']) > max_bytes:
        raise ValueError('runtime_material_packet_exceeds_max_bytes_no_truncation')
    # Validate all source DOM paths before publishing any material artifact.
    from lxml import html
    dom = html.fromstring(raw); tree = dom.getroottree()
    paths = {tree.getpath(e): e for e in dom.iter()}
    for b in packet_blocks:
        el = paths.get(b['source_dom_path'])
        if el is None or ' '.join(''.join(el.itertext()).split()) != b['text']:
            raise ValueError('runtime_index_text_differs_from_original_dom')
    output.mkdir(parents=True, exist_ok=False)
    for name, content in artifacts.items():
        (output/name).write_bytes(content)
    manifest = dict(schema_version=VERSION, files={name: _sha(content) for name, content in artifacts.items()})
    (output/'manifest.json').write_bytes(_bytes(manifest))
    return dict(packet_path=str(output/'source_packet.json'), manifest=manifest, selection_report=report,
                selection_report_path=str(output/'selection-report.json'))
