"""Explicit, immutable historical Data-run adapters for the engineering view.

Historical absolute paths are statements to check, never paths to open. Only
registered relative paths and manifest-listed artifacts are readable here.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
from urllib.parse import urlencode

from .evaluation_artifacts import _path, _hash, _manifest, _read, _bound_reference
from .agent_runs_shared import (PROJECTION_VERSION, artifact_page, project_artifact, summarize_calls,
                               call_configuration_snapshot, configured_value, configured_thinking)

REGISTRATION = 'data/evaluation_views/agent-runs-v1.json'
ADAPTER = 'company-autonomous-financial-v1'
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$')
_CACHE = {}
_LOCK = threading.RLock()


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _registration_digest(entry):
    return hashlib.sha256(json.dumps({k: v for k, v in entry.items() if k != 'summary'}, sort_keys=True).encode()).hexdigest()


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Explicit valid run identity required')
    return value


def _registry(root):
    path = _path(root, REGISTRATION)
    if not path.exists():
        return {'schema_version': 'agent-runs-registration-v1', 'runs': []}
    value = _json(path)
    if value.get('schema_version') != 'agent-runs-registration-v1' or not isinstance(value.get('runs'), list):
        raise ValueError('Unsupported historical run registration')
    ids = [identity for row in value['runs'] for identity in
           [_identity(row['id']), *[_identity(child['id']) for child in row.get('children', [])]]]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate historical run identity')
    return value


def registered_ids(root):
    return [row['id'] for row in _registry(root)['runs']]


def _registered(root, relative, first=None):
    path = _path(root, relative)
    if first is not None and PurePosixPath(relative).parts[0] not in first:
        raise ValueError('Historical root must be explicitly registered under experiments/ or data/')
    return path


def _schema(value, expected):
    if value.get('schema_version') != expected:
        raise ValueError('Unsupported historical schema: expected ' + expected)
    return value


def _scope(value):
    from uteki.domain.research_data.execution_scope import ExecutionScope
    scope = ExecutionScope.model_validate(value).model_dump(mode='json')
    if len(scope['company_ids']) != 1 or not scope['source_snapshot_ids']:
        raise ValueError('Historical adapter requires one explicit company and selected sources')
    return scope


def _joined(base, relative):
    return str(PurePosixPath(base) / relative)


def _view_scope(scope, sources):
    return {'company_id': scope['company_ids'][0], 'source_snapshot_ids': scope['source_snapshot_ids'],
            'periods': sorted({s['period_end'] for s in sources if s.get('period_end')}),
            'snapshot_id': scope['snapshot_id'], 'knowledge_cutoff': scope['knowledge_cutoff']}


def _kind(relative):
    name = PurePosixPath(relative).name
    if '/implementation/' in '/' + relative or not name.endswith('.json'):
        return 'restricted'
    if '/calls/' in '/' + relative:
        return 'model_call'
    if 'config' in name or name == 'method-snapshot.json':
        return 'config'
    return {'input.json': 'input', 'request.json': 'input', 'packet.json': 'input',
            'job.json': 'input', 'decision.json': 'decision', 'receipt.json': 'receipt',
            'feedback.json': 'feedback', 'result.json': 'result'}.get(name, 'artifact')


def _execution(status):
    return 'failed' if status == 'failed' else 'cancelled' if status == 'cancelled' else 'finished'


def _build(root, entry):
    """Full import validation; return a safe view plus internal immutable refs."""
    root = Path(root).resolve()
    rid = _identity(entry['id'])
    if entry.get('adapter') != ADAPTER:
        raise ValueError('Unsupported historical run adapter')
    folder = _registered(root, entry['path'], {'experiments', 'data'})
    manifest = _manifest(folder, entry['manifest_sha256'])
    _schema(manifest, 'company-agent-run-v1')
    result = _schema(_read(folder, manifest, 'result.json'), 'company-agent-result-v1')
    if result.get('operation') != 'query':
        raise ValueError('Historical adapter supports explicit company query runs')
    scope = _scope(entry['scope'])
    if _scope(result['active_scope']) != scope:
        raise ValueError('Parent scope differs from registration')
    query_ref = entry['query']
    if result.get('query_run') != query_ref['path']:
        raise ValueError('Parent query relation mismatch')
    query_folder = _path(folder, query_ref['path'])
    if manifest['files'].get(_joined(query_ref['path'], 'manifest.json')) != query_ref['manifest_sha256']:
        raise ValueError('Query manifest is not pinned by parent')
    query_manifest = _manifest(query_folder, query_ref['manifest_sha256'])
    query = _schema(_read(query_folder, query_manifest, 'result.json'), 'autonomous-result-v2')
    request = _read(query_folder, query_manifest, 'request.json')
    if (_scope(query['active_scope']) != scope or request != query['request'] or _scope(request['scope']) != scope):
        raise ValueError('Query scope/request mismatch')
    dataset_ref = entry['dataset']
    dataset_folder = _registered(root, dataset_ref['path'], {'data'})
    dataset_manifest = _manifest(dataset_folder, dataset_ref['manifest_sha256'])
    _bound_reference(result['dataset'], dataset_ref)
    if (dataset_manifest['company']['company_id'] != scope['company_ids'][0]
            or dataset_manifest['snapshot_id'] != scope['snapshot_id']):
        raise ValueError('Dataset scope mismatch')
    sources = _read(dataset_folder, dataset_manifest, 'sources.json')
    source_map = {s['source_snapshot_id']: s for s in sources}
    if len(source_map) != len(sources):
        raise ValueError('Dataset has duplicate source identities')
    pins = entry['sources']
    if set(pins) != set(scope['source_snapshot_ids']):
        raise ValueError('Explicit source hash pins must match selected scope')
    selected = []
    for sid, sha in pins.items():
        source = source_map.get(sid, {})
        if (source.get('company_id') != scope['company_ids'][0] or source.get('source_sha256') != sha
                or dataset_manifest['files'].get(source.get('raw_file')) != sha):
            raise ValueError('Source/company/hash differs from selected dataset')
        selected.append(source)

    refs, internal, path_ids, steps, children, diagnostics = [], {}, {}, [], [], []
    tree = [{'id': rid, 'parent_run_id': None, 'parent_step_id': None, 'kind': 'query', 'role': 'planner', 'status': query['status']}]
    layer_pins = [(entry['path'], entry['manifest_sha256']), (_joined(entry['path'], query_ref['path']), query_ref['manifest_sha256']),
                  (dataset_ref['path'], dataset_ref['manifest_sha256'])]
    owners = [{'id': rid, 'path': '', 'model': 'model', 'role': 'planner', 'step_id': None}]

    def add(relative, owner=rid, step_id=None, native_id=None):
        if relative not in manifest['files']:
            return {'id': 'missing-' + hashlib.sha256(relative.encode()).hexdigest()[:20], 'run_id': owner,
                    'label': PurePosixPath(relative).name, 'kind': _kind(relative), 'availability': 'missing',
                    'sha256': None, 'size_bytes': None, 'step_id': step_id}
        if (owner, relative) in path_ids:
            ref = internal[path_ids[owner, relative]]['ref']
            if step_id and not ref['step_id']:
                ref['step_id'] = step_id
            return ref
        identity = native_id or 'file-' + hashlib.sha256((owner + ':' + relative).encode()).hexdigest()[:24]
        # The public endpoint is root-run scoped, so child-owned IDs also have to
        # be unique in the complete tree. Preserve native ID separately if needed.
        if identity in internal:
            identity = owner + '--' + identity
        path = _path(folder, relative)
        kind = _kind(relative)
        ref = {'id': identity, 'run_id': owner, 'label': relative, 'kind': kind,
               'availability': 'restricted' if kind == 'restricted' else 'available',
               'sha256': manifest['files'][relative], 'size_bytes': path.stat().st_size, 'step_id': step_id}
        refs.append(ref)
        internal[identity] = {'ref': ref, 'path': path, 'relative': relative}
        path_ids[owner, relative] = identity
        return ref

    query_prefix = query_ref['path']
    seen_steps = set()
    for row in query['trace']:
        ordinal = row['step']
        if type(ordinal) is not int or ordinal < 1 or ordinal in seen_steps:
            raise ValueError('Invalid or duplicate historical step')
        seen_steps.add(ordinal)
        sid = f'{rid}--step-{ordinal:03d}'
        relative = _joined(query_prefix, f'turn-{ordinal:03d}')
        for key in ('receipt', 'feedback'):
            if row.get(key) != f'turn-{ordinal:03d}/{key}.json':
                raise ValueError('Trace step file relation mismatch')
        receipt = _read(folder, manifest, _joined(relative, 'receipt.json'))
        if receipt.get('step') != ordinal or receipt.get('action') != row['action'] or receipt.get('status') != row['status']:
            raise ValueError('Step receipt differs from trace')
        packet = _read(folder, manifest, _joined(relative, 'input.json'))
        if _scope(packet['active_scope']) != scope or _scope(packet['request']['scope']) != scope:
            raise ValueError('Step input scope differs from registered query')
        files = [add(_joined(relative, name + '.json'), step_id=sid) for name in ('input', 'decision', 'receipt', 'feedback')]
        steps.append({'id': sid, 'run_id': rid, 'ordinal': ordinal, 'action': row['action'], 'phase': receipt.get('layer'),
                      'status': row['status'], 'error_code': receipt.get('error_code'), 'elapsed_seconds': None,
                      'files': files, 'call_ids': [], 'child_run_ids': []})
    step_map = {s['ordinal']: s for s in steps}
    declared_children = entry.get('children', [])
    declared_ordinals = [c['parent_step'] for c in declared_children]
    if len(declared_ordinals) != len(set(declared_ordinals)):
        raise ValueError('Duplicate extraction step registration')
    for child in declared_children:
        cid = _identity(child['id'])
        if cid == rid or cid in children:
            raise ValueError('Duplicate child run identity')
        children.append(cid)
        ordinal = child['parent_step']
        if ordinal not in step_map or step_map[ordinal]['action'] != 'financial_extract':
            raise ValueError('Extraction parent step mismatch')
        step = step_map[ordinal]
        batch_ref, direct_ref = child['batch'], child['direct']
        for pin in (batch_ref, direct_ref):
            _path(folder, pin['path'])
            if manifest['files'].get(_joined(pin['path'], 'manifest.json')) != pin['manifest_sha256']:
                raise ValueError('Child manifest is not pinned by parent')
            layer_pins.append((_joined(entry['path'], pin['path']), pin['manifest_sha256']))
        batch_folder = _path(folder, batch_ref['path'])
        batch_manifest = _manifest(batch_folder, batch_ref['manifest_sha256'])
        batch = _schema(_read(batch_folder, batch_manifest, 'result.json'), 'extraction-batch-run-v1')
        feedback = _read(folder, manifest, _joined(query_prefix, f'turn-{ordinal:03d}/feedback.json'))
        claim = feedback['result']
        _bound_reference(claim['run'], {'path': _joined(entry['path'], batch_ref['path']), 'manifest_sha256': batch_ref['manifest_sha256']})
        if (claim.get('company_id') != scope['company_ids'][0] or claim.get('source_snapshot_id') not in pins
                or claim.get('source_sha256') != pins[claim['source_snapshot_id']]):
            raise ValueError('Parent extraction receipt source mismatch')
        expected_direct = _joined(batch_ref['path'], 'extraction-01')
        if direct_ref['path'] != expected_direct or batch_manifest['files'].get('extraction-01/manifest.json') != direct_ref['manifest_sha256']:
            raise ValueError('Batch/direct relation mismatch')
        direct_folder = _path(folder, direct_ref['path'])
        direct_manifest = _manifest(direct_folder, direct_ref['manifest_sha256'])
        direct = _schema(_read(direct_folder, direct_manifest, 'result.json'), 'direct-extraction-run-v1')
        packet = _read(direct_folder, direct_manifest, 'packet.json')
        job = _read(direct_folder, direct_manifest, 'job.json')
        source = packet['source']
        if (packet['company_id'] != scope['company_ids'][0] or job['company_id'] != packet['company_id']
                or job['source_snapshot_id'] != source['source_snapshot_id'] or source['source_snapshot_id'] not in pins
                or source['source_snapshot_id'] != claim['source_snapshot_id']
                or source['source_sha256'] != pins[source['source_snapshot_id']]
                or packet['dataset_manifest_sha256'] != dataset_ref['manifest_sha256']
                or job['dataset_manifest_sha256'] != dataset_ref['manifest_sha256']):
            raise ValueError('Direct extraction source/dataset scope mismatch')
        if batch.get('batch_index') != claim.get('batch_index'):
            raise ValueError('Parent receipt and extraction batch selection differ')
        output_dataset_hash = direct_manifest['files'].get('dataset/manifest.json')
        output_dataset_ref = {'path': _joined(entry['path'], direct_ref['path'] + '/dataset'),
                              'manifest_sha256': output_dataset_hash}
        for returned in (claim, batch, direct):
            _bound_reference(returned['dataset'], output_dataset_ref)
        output_manifest = _read(direct_folder, direct_manifest, 'dataset/manifest.json')
        if any(returned['dataset'].get('snapshot_id') != output_manifest['snapshot_id'] for returned in (claim, batch, direct)):
            raise ValueError('Extraction output dataset snapshot differs across layers')
        # Reuse the extraction inspector's quote, normalization and read-only DB
        # checks, even when this child is not yet in the old view registry.
        from .direct_extraction_views import _load as load_extraction
        inspected = load_extraction(root, {'id': cid, 'path': _joined(entry['path'], direct_ref['path']),
            'manifest_sha256': direct_ref['manifest_sha256'],
            'dataset': {k: dataset_ref[k] for k in ('id', 'manifest_sha256')}})
        original_source = source_map[source['source_snapshot_id']]
        block_file = _joined(original_source['index_folder'], 'blocks.jsonl')
        if block_file not in dataset_manifest['files']:
            raise ValueError('Selected source has no pinned original block index')
        original_blocks = [json.loads(line) for line in _path(dataset_folder, block_file).read_text().splitlines()]
        block_map = {b['block_id']: b for b in original_blocks}
        if len(block_map) != len(original_blocks):
            raise ValueError('Original source has duplicate block IDs')
        for block in inspected['blocks']:
            original = block_map.get(block['block_id'])
            if (original is None or block['text_hash'] != original['text_hash']
                    or hashlib.sha256(original['text'].encode()).hexdigest() != original['text_hash']):
                raise ValueError('Extraction packet block differs from original selected source')
        for field in ('raw_record_count', 'normalized_record_count', 'unresolved_count'):
            if any(v.get(field) != direct.get(field) for v in (batch, claim)):
                raise ValueError('Extraction counts differ across pinned layers')
        tree.append({'id': cid, 'parent_run_id': rid, 'parent_step_id': step['id'], 'kind': 'extraction', 'role': 'extractor', 'status': direct['status']})
        step['child_run_ids'].append(cid)
        # This is one saved direct-extraction task, not an inferred Planner
        # decision loop. The parent retains its six/seven actual decisions.
        child_step = {'id': cid + '--step-001', 'run_id': cid, 'ordinal': 1, 'action': 'extract',
                      'phase': 'financial_extraction', 'status': direct['status'], 'error_code': None,
                      'elapsed_seconds': None, 'files': [], 'call_ids': [], 'child_run_ids': [],
                      'origin': 'direct_extraction_task'}
        steps.append(child_step)
        owners.append({'id': cid, 'path': direct_ref['path'], 'model': _joined(direct_ref['path'], 'model'),
                       'role': 'extractor', 'step_id': child_step['id']})
        for rel in direct_manifest['files']:
            if rel.startswith('implementation/'):
                continue
            added = add(_joined(direct_ref['path'], rel), owner=cid, step_id=child_step['id'])
            if rel in ('packet.json', 'job.json', 'prompt.json', 'system-prompt-effective.json', 'extraction.json', 'normalized.json', 'result.json'):
                child_step['files'].append(added)
        for name in ('result.json', 'method-snapshot.json', 'parent-packet.json', 'batch-job.json', 'coverage.json', 'batch-catalog.json'):
            if name in batch_manifest['files']:
                add(_joined(batch_ref['path'], name), owner=cid, step_id=child_step['id'])
    for step in steps:
        if step['action'] == 'financial_extract' and step['status'] == 'candidate_batch_generated' and not step['child_run_ids']:
            raise ValueError('Successful extraction requires an explicit child registration')
    if query.get('worker_runs'):
        diagnostics.append('Historical Worker substeps are not registered by this adapter; saved parent delegation evidence remains available.')

    # Native ArtifactRefs retain identity; file refs remain distinct from them.
    index = _read(query_folder, query_manifest, 'artifact-index.json')
    native_ids = set()
    from uteki.infrastructure.research_data.financial_records import digest
    for ref in index:
        if ref['artifact_id'] in native_ids:
            raise ValueError('Duplicate native artifact identity')
        native_ids.add(ref['artifact_id'])
        if _scope(ref['scope']) != scope or query_manifest['files'].get(ref['path']) != ref['sha256']:
            raise ValueError('Artifact identity/hash/scope mismatch')
        if ref.get('scope_id') != 'scope-' + digest(scope)[:24] or not set(ref.get('source_ids', [])) <= set(scope['source_snapshot_ids']):
            raise ValueError('Artifact source/scope identity mismatch')
        relative = _joined(query_prefix, ref['path'])
        if _path(folder, relative).stat().st_size != ref['size_bytes']:
            raise ValueError('Artifact size mismatch')
        add(relative, native_id=ref['artifact_id'], step_id=step_map.get(ref.get('created_step'), {}).get('id'))
    for rel in manifest['files']:
        if rel in ('result.json', 'request.json', 'scope.json', 'model-config.input.json', 'extractor-model-config.input.json') or (
                rel.startswith(query_prefix + '/') and '/' not in rel[len(query_prefix) + 1:] and rel.endswith('.json')):
            add(rel)

    call_sources = {}
    for owner in owners:
        model_prefix = owner['model']
        config_name = model_prefix + '/model-config.json'
        config = _read(folder, manifest, config_name) if config_name in manifest['files'] else {}
        if config_name in manifest['files']:
            add(config_name, owner['id'], owner['step_id'])
        association = {}
        for rel in manifest['files']:
            if not rel.startswith(model_prefix + '/') or '/' in rel[len(model_prefix) + 1:] or not re.search(r'-attempt-\d+\.json$', rel):
                continue
            attempt = _read(folder, manifest, rel)
            parent_step = step_map.get(attempt.get('decision')) if owner['role'] == 'planner' else None
            step_id = parent_step['id'] if parent_step else owner['step_id']
            ref = add(rel, owner['id'], step_id)
            if parent_step:
                parent_step['files'].append(ref)
            for call_ref in attempt.get('calls', []):
                call_path = _joined(model_prefix, call_ref['path'])
                if manifest['files'].get(call_path) != call_ref['sha256']:
                    raise ValueError('Attempt call reference hash mismatch')
                call = _read(folder, manifest, call_path)
                cid = call['call_id']
                if cid in association and association[cid] != step_id:
                    raise ValueError('Call associated with conflicting steps')
                association[cid] = step_id
            visible = attempt.get('visible_output')
            if visible:
                rel_output = _joined(model_prefix, visible['path'])
                if manifest['files'].get(rel_output) != visible['sha256']:
                    raise ValueError('Visible model output hash mismatch')
                output_ref = add(rel_output, owner['id'], step_id)
                if parent_step:
                    parent_step['files'].append(output_ref)
        for rel in manifest['files']:
            if not rel.startswith(model_prefix + '/calls/') or not re.search(r'-(start|end)\.json$', rel):
                continue
            record = _read(folder, manifest, rel)
            cid = record['call_id']
            stage = 'end' if rel.endswith('-end.json') else 'start'
            metadata = (owner['id'], owner['role'], association.get(cid, owner['step_id']))
            item = call_sources.setdefault(cid, {'identity': metadata, 'records': {}, 'refs': [], 'effort': config.get('reasoning_effort'), 'config': config})
            if item['identity'] != metadata:
                raise ValueError('Call identity belongs to conflicting run/step')
            if stage in item['records'] and item['records'][stage] != record:
                raise ValueError('Conflicting duplicate call evidence')
            item['records'][stage] = record
            item['refs'].append(add(rel, owner['id'], metadata[2]))
    calls = []
    for cid, item in call_sources.items():
        record = item['records'].get('end', item['records'].get('start'))
        start = item['records'].get('start', {})
        if any(start.get(key) != record.get(key) for key in ('call_id', 'provider', 'requested_model', 'started_at') if key in start):
            raise ValueError('Call start/end identity mismatch')
        owner, role, step_id = item['identity']
        usage = record.get('usage') or {}
        presence = record.get('usage_presence')
        if presence not in ('reported', 'absent', 'unknown'):
            raw = record.get('raw_usage') or {}
            confirmed = all(type(raw.get(k)) is int and raw[k] >= 0 for k in ('prompt_tokens', 'completion_tokens'))
            presence = 'reported' if confirmed and usage else 'unknown' if usage else 'absent'
        values = {field: usage.get(field) for field in ('input_tokens', 'output_tokens')}
        values.update(cached_tokens=(usage.get('input_tokens_details') or {}).get('cached_tokens'),
                      reasoning_tokens=(usage.get('output_tokens_details') or {}).get('reasoning_tokens'))
        for value in values.values():
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Invalid saved token usage')
        estimated = record.get('estimated_usd')
        if estimated is not None and (not Decimal(str(estimated)).is_finite() or Decimal(str(estimated)) < 0):
            raise ValueError('Invalid saved estimated cost')
        configuration = call_configuration_snapshot(record, start=start, config=item['config'],
            fingerprints={'system_sha256': item['config']['prompt_sha256']} if item['config'].get('prompt_sha256') else None)
        row = {'call_id': cid, 'run_id': owner, 'step_id': step_id, 'role': role,
               'reasoning_effort': configured_value(configuration, 'reasoning_effort'),
               'thinking_mode': configured_thinking(configuration), 'configuration_snapshot': configuration,
               **{key: record.get(key) for key in ('provider', 'requested_model', 'actual_upstream_model', 'stage', 'status',
                    'started_at', 'ended_at', 'elapsed_seconds', 'estimated_usd', 'actual_billed_usd', 'request_id', 'response_id', 'http_status', 'provider_finish_reason')},
               **values, 'usage_presence': presence, 'files': item['refs']}
        calls.append(row)
        if step_id:
            matching = next((s for s in steps if s['id'] == step_id), None)
            if matching:
                matching['call_ids'].append(cid)
        else:
            diagnostics.append('Call has no reliable step association: ' + cid)
    links = []
    for child in declared_children:
        if child.get('extraction_view_id'):
            from .direct_extraction_views import _registration as extraction_registration
            match = [r for r in extraction_registration(root) if r['id'] == child['extraction_view_id']]
            if len(match) != 1 or match[0]['path'] != _joined(entry['path'], child['direct']['path']) or match[0]['manifest_sha256'] != child['direct']['manifest_sha256'] or match[0].get('dataset') != {k: dataset_ref[k] for k in ('id', 'manifest_sha256')}:
                raise ValueError('Existing extraction view mapping mismatch')
            links.append({'label': '提取产物 / Extraction · ' + child['id'],
                          'href': '/extractions?' + urlencode({'run': child['extraction_view_id'], 'company': scope['company_ids'][0]})})
    checked = datetime.now(timezone.utc).isoformat()
    view = {'schema_version': 'agent-run-view-v1', 'id': rid, 'root_run_id': rid, 'agent': 'data',
            'title': str(entry['title']), 'origin': query['plan_origin'], 'live': False, 'root_terminal': True,
            'revision': entry['manifest_sha256'],
            'state': {'execution': _execution(query['status']), 'connection': 'historical', 'delivery': query['status'],
                      'quality': query.get('semantic_completeness', 'not_recorded'), 'adoption': 'unchanged_candidate' if query.get('financial_extractions') else 'not_recorded',
                      'stop_reason': query['stop_reason']},
            'scope': _view_scope(scope, selected), 'run_tree': tree, 'steps': steps, 'artifacts': refs,
            'calls': sorted(calls, key=lambda c: (c.get('started_at') or '', c['call_id'])),
            'usage': {**summarize_calls(calls), 'own': summarize_calls([c for c in calls if c['run_id'] == rid])},
            'inputs': [r for r in refs if r['kind'] == 'input'], 'configs': [r for r in refs if r['kind'] == 'config'],
            'diagnostics': diagnostics, 'integrity': {'status': 'verified_at_import', 'checked_at': checked,
                'scope': 'Registered manifests and listed files; not a continuing guarantee of unchanged bytes',
                'adapter': ADAPTER, 'projection': PROJECTION_VERSION, 'registration_sha256': _registration_digest(entry)}, 'links': links}
    return {'view': view, 'internal': internal, 'pins': layer_pins}


def validate_registration(root, entry):
    """Importer entrypoint: full validation without modifying historical bytes."""
    return deepcopy(_build(root, entry)['view'])


def _summary(view):
    return {k: deepcopy(view[k]) for k in ('schema_version', 'id', 'root_run_id', 'agent', 'title', 'origin', 'live',
            'root_terminal', 'revision', 'state', 'scope', 'usage', 'integrity', 'diagnostics')}


def list_runs(root):
    """Read imported summaries only; never rehash large datasets during polling."""
    rows = []
    for entry in _registry(root)['runs']:
        summary = entry.get('summary')
        if (isinstance(summary, dict) and summary.get('id') == entry['id'] and summary.get('revision') == entry['manifest_sha256']
                and summary.get('integrity', {}).get('registration_sha256') == _registration_digest(entry)
                and summary['integrity'].get('adapter') == ADAPTER and summary['integrity'].get('projection') == PROJECTION_VERSION):
            rows.append(deepcopy(summary))
        else:
            rows.append({'id': entry['id'], 'root_run_id': entry['id'], 'agent': 'data', 'title': str(entry.get('title', entry['id'])),
                         'live': False, 'root_terminal': True, 'state': {'execution': 'unknown', 'connection': 'historical'},
                         'scope': {}, 'usage': {}, 'integrity': {'status': 'index_missing'}, 'diagnostics': ['Explicit import is required to build a verified historical summary.']})
    return rows


def _loaded(root, identity):
    _identity(identity)
    rows = [row for row in _registry(root)['runs'] if row['id'] == identity]
    if len(rows) != 1:
        raise ValueError('Select an explicitly registered historical run')
    entry = rows[0]
    key = (str(Path(root).resolve()), entry['id'], hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest(), ADAPTER, PROJECTION_VERSION)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached:
            try:
                for relative, expected in cached['pins']:
                    if _hash(_path(_path(root, relative), 'manifest.json')) != expected:
                        raise ValueError('Registered manifest changed')
            except (OSError, ValueError):
                _CACHE.pop(key, None)
                raise
            return cached
        value = _build(root, entry)
        _CACHE[key] = value
        return value


def load_run(root, identity):
    return deepcopy(_loaded(root, identity)['view'])


def _read_ref(root, identity, loaded, artifact_id):
    item = loaded['internal'].get(artifact_id)
    if item is None:
        raise ValueError('Unknown artifact in selected run')
    ref = item['ref']
    # Re-run path traversal/symlink checks when opening cached references.
    try:
        relative = item['path'].relative_to(Path(root).resolve()).as_posix()
        path = _path(root, relative)
        if _hash(path) != ref['sha256'] or path.stat().st_size != ref['size_bytes']:
            raise ValueError('Artifact integrity mismatch; historical index invalidated')
        if ref['availability'] != 'restricted' and ref['size_bytes'] > 128 * 1024 * 1024:
            raise ValueError('Artifact exceeds supported inspection size')
        value = None if ref['availability'] == 'restricted' else _json(path)
    except (OSError, ValueError):
        with _LOCK:
            for key in list(_CACHE):
                if key[:2] == (str(Path(root).resolve()), loaded['view']['id']):
                    _CACHE.pop(key, None)
        raise
    return ref, value


def load_step(root, identity, step_id):
    loaded = _loaded(root, identity)
    matches = [s for s in loaded['view']['steps'] if s['id'] == step_id]
    if len(matches) != 1:
        raise ValueError('Unknown step in selected run')
    for ref in matches[0]['files']:
        if ref['availability'] == 'available':
            _read_ref(root, identity, loaded, ref['id'])
    return deepcopy(matches[0])


def read_artifact(root, identity, artifact_id, cursor=None, browse=None):
    loaded = _loaded(root, identity)
    ref, value = _read_ref(root, identity, loaded, artifact_id)
    return artifact_page(ref, project_artifact(value, ref['kind']), cursor=cursor, browse=browse)
