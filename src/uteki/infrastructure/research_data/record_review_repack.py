"""Repack explicitly selected frozen review records without model calls."""
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.domain.research_data.execution_scope import ExecutionScope
from .financial_records import digest
from .query_dataset import contained
from .query_service import QueryDataPort


def _encoded(packet):
    return json.dumps(packet, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _combine(entries, metrics):
    first = entries[0][0]
    result = deepcopy({k: v for k, v in first.items() if k not in (
        'packet_id', 'records', 'target_block_id', 'target_block_ids', 'source_blocks',
        'source_fragments', 'context_gaps', 'unresolved_note_references', 'metric_definitions')})
    result['schema_version'] = 'record-review-input-v2'
    result.update(records=[], target_block_ids=[], source_blocks=[], source_fragments=[],
                  context_gaps=[], unresolved_note_references=[])
    indexes = {'source_blocks': {}, 'source_fragments': {}}
    for packet, item in entries:
        result['records'].append(deepcopy(item))
        for key in ('context_gaps', 'unresolved_note_references'):
            for value in packet[key]:
                if value not in result[key]: result[key].append(deepcopy(value))
        for target in packet.get('target_block_ids', [packet.get('target_block_id')]):
            if target is None: raise ValueError('packet target block required')
            if target not in result['target_block_ids']: result['target_block_ids'].append(target)
        for key in indexes:
            for value in packet[key]:
                block = value['block_id']
                old = indexes[key].get(block)
                if old is None:
                    old = deepcopy(value)
                    indexes[key][block] = old
                    result[key].append(old)
                elif old != value:
                    # Neighborhood copies omit compact HTML; keep the target copy's HTML.
                    if key != 'source_fragments' or {k: v for k, v in old.items() if k != 'compact_html'} != {
                            k: v for k, v in value.items() if k != 'compact_html'}:
                        raise ValueError('conflicting source block or fragment')
                    if old.get('compact_html') is None: old['compact_html'] = value.get('compact_html')
                    elif value.get('compact_html') not in (None, old['compact_html']):
                        raise ValueError('conflicting compact HTML')
    result['metric_definitions'] = {item['record']['metric_id']: deepcopy(metrics[item['record']['metric_id']])
                                    for _, item in entries}
    result['packet_id'] = 'review-'+digest(result)[:24]
    return result


def repack_review_inputs(inputs, record_ids, output, *, batch_size=24, max_packet_bytes=300000):
    """Preserve source context and values, selecting records in parent input order."""
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if output.is_relative_to(inputs): raise ValueError('output is inside frozen inputs')
    if output.exists(): raise FileExistsError('output already exists')
    if type(batch_size) is not int or not 1 <= batch_size <= 24: raise ValueError('batch size must be 1..24')
    if type(max_packet_bytes) is not int or max_packet_bytes < 1: raise ValueError('positive packet byte limit required')
    if not record_ids or any(not isinstance(r, str) or not r for r in record_ids) or len(set(record_ids)) != len(record_ids):
        raise ValueError('explicit nonempty unique record IDs required')
    parent_manifest = _verify_manifest(inputs)
    if 'input-manifest.json' not in parent_manifest['files']: raise ValueError('input spec is not sealed')
    spec = json.loads((inputs/'input-manifest.json').read_text())
    dataset = Path(spec['dataset']).resolve()
    if output.is_relative_to(dataset): raise ValueError('output is inside frozen dataset')
    dataset_manifest = _verify_manifest(dataset, spec['dataset_manifest_sha256'])
    if 'metrics.json' not in dataset_manifest['files']: raise ValueError('metric definitions are not sealed')
    metrics = json.loads((dataset/'metrics.json').read_text())
    scope = ExecutionScope.model_validate(spec['scope'])
    if not scope.include_candidates: raise ValueError('candidate review permission required')
    with QueryDataPort(dataset) as port: port.scoped(scope).discover_data()
    selected = set(record_ids)
    if not selected <= set(spec['record_ids']): raise ValueError('record IDs outside parent inputs')
    groups, seen, fragment_files = {}, set(), {}
    for ref in spec['packets']:
        path = contained(inputs, ref['path'])
        if parent_manifest['files'].get(ref['path']) != ref['sha256'] or digest(path.read_bytes()) != ref['sha256']:
            raise ValueError('packet file hash mismatch')
        packet = json.loads(path.read_text())
        if packet['packet_id'] != ref['packet_id'] or packet['packet_id'] != 'review-'+digest({
                k: v for k, v in packet.items() if k != 'packet_id'})[:24]: raise ValueError('packet identity mismatch')
        if ExecutionScope.model_validate(packet['scope']) != scope: raise ValueError('packet scope mismatch')
        source = packet['source']
        if source['source_snapshot_id'] not in scope.source_snapshot_ids or source['company_id'] not in scope.company_ids:
            raise ValueError('source outside selected scope')
        ids = [item['record']['record_id'] for item in packet['records']]
        if ids != ref['record_ids']: raise ValueError('packet record reference mismatch')
        if seen.intersection(ids) or len(ids) != len(set(ids)): raise ValueError('duplicate parent record IDs')
        seen.update(ids)
        chosen = [item for item in packet['records'] if item['record']['record_id'] in selected]
        if not chosen: continue
        for item in chosen:
            metric_id = item['record']['metric_id']
            definition = metrics.get(metric_id)
            if not isinstance(definition, dict) or definition.get('metric_id') != metric_id or not isinstance(
                    definition.get('definition'), str) or not definition['definition'].strip():
                raise ValueError('selected metric definition is missing or invalid')
            if digest(item['record']) != item['record_sha256']: raise ValueError('record hash mismatch')
            if item['record']['source_snapshot_id'] != source['source_snapshot_id'] or item['evidence']['source_snapshot_id'] != source['source_snapshot_id']:
                raise ValueError('record or evidence source mismatch')
        for fragment in packet['source_fragments']:
            name, expected = fragment['original_fragment_path'], fragment['original_fragment_sha256']
            raw = contained(inputs, name).read_bytes()
            if parent_manifest['files'].get(name) != expected or digest(raw) != expected:
                raise ValueError('original fragment hash mismatch')
            if name in fragment_files and fragment_files[name] != raw: raise ValueError('fragment path conflict')
            fragment_files[name] = raw
        key = digest({'source': source, 'scope': packet['scope'], 'output_schema': packet['output_schema'],
                      'context_completeness': packet['context_completeness'], 'schema_version': packet['schema_version']})
        groups.setdefault(key, []).extend((packet, item) for item in chosen)
    if seen != set(spec['record_ids']) or not selected <= seen: raise ValueError('parent record coverage mismatch')
    packets = []
    for entries in groups.values():
        pending = []
        for entry in entries:
            candidate = _combine([*pending, entry], metrics)
            if pending and (len(pending) >= batch_size or len(_encoded(candidate)) > max_packet_bytes):
                packets.append(_combine(pending, metrics))
                pending = []
                candidate = _combine([entry], metrics)
            if len(_encoded(candidate)) > max_packet_bytes: raise ValueError('single record context exceeds packet byte limit')
            pending.append(entry)
        if pending: packets.append(_combine(pending, metrics))
    output.mkdir(parents=True, exist_ok=False)
    references = []
    for number, packet in enumerate(packets, 1):
        name = f'packets/{number:03d}.json'
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream: stream.write(_encoded(packet))
        references.append({'path': name, 'packet_id': packet['packet_id'], 'sha256': digest(path.read_bytes()),
                           'record_ids': [item['record']['record_id'] for item in packet['records']]})
    for name, raw in fragment_files.items():
        path = contained(output, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream: stream.write(raw)
    result = {'schema_version': spec['schema_version'], 'dataset': str(dataset),
              'dataset_manifest_sha256': spec['dataset_manifest_sha256'], 'scope': deepcopy(spec['scope']),
              'record_ids': list(record_ids), 'packets': references,
              'parent_inputs': {'path': str(inputs), 'manifest_sha256': digest((inputs/'manifest.json').read_bytes())},
              'repack': {'batch_size': batch_size, 'max_packet_bytes': max_packet_bytes},
              'status': 'prepared_not_reviewed', 'model_calls': 0}
    write_new(output/'input-manifest.json', result)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return result
