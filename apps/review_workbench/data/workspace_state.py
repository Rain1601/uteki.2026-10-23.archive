"""UI-only display choices and version archives; frozen research stays immutable."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading

from apps.review_workbench.data.evaluation_artifacts import _ID, _SHA, _path, _hash, load_dataset
from apps.review_workbench.data import direct_extraction_views as extraction_views


REGISTRATION = 'data/evaluation_views/workspace-tasks-v1.json'
STATE_PATH = 'data/review_workbench/ui-state-v1.json'
STATE_VERSION = 'workspace-ui-state-v1'
TASK_VERSION = 'workspace-task-registration-v1'
_LOCK = threading.RLock()
_PIN_FIELDS = {'task_id', 'dataset_id', 'dataset_manifest_sha256', 'company_id',
               'source_snapshot_id', 'source_sha256', 'run_id', 'run_manifest_sha256'}


class WorkspaceStateError(ValueError):
    pass


class WorkspaceConflictError(WorkspaceStateError):
    """A UI choice changed after the caller read its revision."""


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise WorkspaceStateError('Explicit valid identity required')
    return value


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise WorkspaceStateError('Explicit SHA256 required')
    return value


def _empty():
    return {'schema_version': STATE_VERSION, 'revision': 0,
            'selections': {}, 'archived_versions': {}, 'audit_events': []}


def _validate_pin(pin):
    if not isinstance(pin, dict) or set(pin) != _PIN_FIELDS:
        raise WorkspaceStateError('Invalid UI reference')
    for key, value in pin.items():
        (_sha if key.endswith('sha256') else _identity)(value)


def _validate_state(state):
    if (not isinstance(state, dict) or set(state) != set(_empty())
            or state['schema_version'] != STATE_VERSION
            or type(state['revision']) is not int or state['revision'] < 0
            or not isinstance(state['selections'], dict)
            or not isinstance(state['archived_versions'], dict)
            or not isinstance(state['audit_events'], list)):
        raise WorkspaceStateError('Invalid workspace UI state')
    for key, pin in state['selections'].items():
        _validate_pin(pin)
        if key != pin['task_id']:
            raise WorkspaceStateError('Selection task identity mismatch')
    for key, pin in state['archived_versions'].items():
        _validate_pin(pin)
        if key != pin['run_id'] or any(p['run_id'] == key for p in state['selections'].values()):
            raise WorkspaceStateError('Archived version is selected or has a mismatched identity')
    if len(state['audit_events']) != state['revision']:
        raise WorkspaceStateError('UI revision and audit history disagree')
    for sequence, event in enumerate(state['audit_events'], 1):
        if (not isinstance(event, dict) or event.get('revision') != sequence
                or event.get('action') not in {'select_version', 'archive', 'restore'}):
            raise WorkspaceStateError('Invalid UI audit event')
    return state


def _read(path):
    try:
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else _empty()
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceStateError('Workspace UI state could not be read') from error
    return _validate_state(state)


@contextmanager
def _locked(root, *, write):
    path = _path(root, STATE_PATH)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = _path(root, STATE_PATH + '.lock')
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            try:
                # Recheck the fixed state path after acquiring the lock.
                yield _path(root, STATE_PATH)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _save(path, state):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(root):
    """Missing state means no choices, never an implicit company or latest run."""
    if not _path(root, STATE_PATH).exists():
        return _empty()
    with _locked(root, write=False) as path:
        return deepcopy(_read(path))


def _tasks(root):
    path = _path(root, REGISTRATION)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceStateError('Task registration could not be read') from error
    if (not isinstance(value, dict) or value.get('schema_version') != TASK_VERSION
            or not isinstance(value.get('tasks'), list)):
        raise WorkspaceStateError('Unsupported workspace task registration')
    identities, run_ids = set(), set()
    for task in value['tasks']:
        required = {'task_id', 'label_zh', 'label_en', 'dataset', 'company_id',
                    'source_snapshot_id', 'source_sha256', 'versions'}
        if not isinstance(task, dict) or not required <= task.keys():
            raise WorkspaceStateError('Incomplete task registration')
        tid = _identity(task['task_id'])
        if tid in identities:
            raise WorkspaceStateError('Duplicate task identity')
        identities.add(tid)
        for key in ('label_zh', 'label_en'):
            if not isinstance(task[key], str) or not task[key].strip():
                raise WorkspaceStateError('Task labels are required')
        if not isinstance(task['dataset'], dict) or set(task['dataset']) != {'id', 'manifest_sha256'}:
            raise WorkspaceStateError('Task requires a pinned dataset')
        _identity(task['dataset']['id']); _sha(task['dataset']['manifest_sha256'])
        _identity(task['company_id']); _identity(task['source_snapshot_id']); _sha(task['source_sha256'])
        if not isinstance(task['versions'], list) or not task['versions']:
            raise WorkspaceStateError('Task requires explicit versions')
        for version in task['versions']:
            if not isinstance(version, dict) or not {'run_id', 'manifest_sha256'} <= version.keys():
                raise WorkspaceStateError('Task version requires a run manifest pin')
            rid = _identity(version['run_id']); _sha(version['manifest_sha256'])
            input_refs = version.get('input_artifacts')
            if not isinstance(input_refs, dict) or set(input_refs) != {'job.json', 'packet.json'}:
                raise WorkspaceStateError('Task version requires explicit job and packet input pins')
            for input_sha in input_refs.values():
                _sha(input_sha)
            if rid in run_ids:
                raise WorkspaceStateError('A run cannot belong to multiple task slots')
            run_ids.add(rid)
    return value['tasks']


def _pin(task, run):
    return {'task_id': task['task_id'], 'dataset_id': task['dataset']['id'],
            'dataset_manifest_sha256': task['dataset']['manifest_sha256'],
            'company_id': task['company_id'], 'source_snapshot_id': task['source_snapshot_id'],
            'source_sha256': task['source_sha256'], 'run_id': run['id'],
            'run_manifest_sha256': run['manifest_sha256']}


def _material_runs(root, data, source_id):
    """Load each explicitly bound run once per read, retaining all existing checks.

    This is request-local reuse, not a cache: every call revalidates frozen bytes,
    database payloads, source scope and source block hashes through load_run.
    """
    if not _path(root, extraction_views.REGISTRATION).is_file():
        return {}, [{'reason': 'extraction_registry_missing'}]
    try:
        registrations = extraction_views._registration(root)
    except (OSError, KeyError, TypeError) as error:
        raise WorkspaceStateError('Extraction registration could not be read') from error
    sources = {source['source_snapshot_id']: source for source in data['sources']}
    originals = {block['block_id']: block for block in data['blocks'][source_id]}
    loaded, gaps = {}, []
    for entry in registrations:
        pin = entry.get('dataset')
        if pin and pin['id'] != data['id']:
            continue
        try:
            run = extraction_views.load_run(root, entry['id'])
        except ValueError:
            if pin:
                gaps.append({'run_id': entry['id'], 'reason': 'dataset_or_source_binding_mismatch'})
            continue
        sid = run['source_snapshot_id']
        if not pin:
            if run['company_id'] == data['company']['company_id'] and sid in sources:
                gaps.append({'run_id': entry['id'], 'reason': 'dataset_manifest_not_bound'})
            continue
        if (run.get('dataset') != pin or run['manifest_sha256'] != entry['manifest_sha256']
                or pin['manifest_sha256'] != data['manifest_sha256']
                or run['company_id'] != data['company']['company_id'] or sid not in sources
                or run['source_sha256'] != sources[sid]['source_sha256']):
            gaps.append({'run_id': entry['id'], 'reason': 'dataset_or_source_binding_mismatch'})
            continue
        if sid != source_id:
            continue
        if any(block['block_id'] not in originals
               or originals[block['block_id']].get('text_hash') != block['text_hash']
               for block in run['blocks']):
            gaps.append({'run_id': entry['id'], 'reason': 'Extraction packet block differs from selected dataset source'})
            continue
        loaded[entry['id']] = run
    return loaded, gaps


def material_tasks(root, dataset, source_id, state=None):
    """Return task slots and already validated runs for this request's source only."""
    identity = dataset if isinstance(dataset, str) else dataset['id']
    data = load_dataset(root, _identity(identity))
    if isinstance(dataset, dict) and dataset.get('manifest_sha256') != data['manifest_sha256']:
        raise WorkspaceStateError('Dataset changed during workspace read')
    _identity(source_id)
    sources = [source for source in data['sources'] if source['source_snapshot_id'] == source_id]
    if len(sources) != 1:
        raise WorkspaceStateError('Source outside selected dataset')
    source = sources[0]
    state = read_state(root) if state is None else deepcopy(_validate_state(state))
    loaded, gaps = _material_runs(root, data, source_id)
    tasks, claimed = [], set()
    def bound_run(rid):
        if rid not in loaded:
            raise WorkspaceStateError('Registered run unavailable in selected material')
        return loaded[rid]
    for task in _tasks(root):
        if task['dataset']['id'] != data['id'] or task['source_snapshot_id'] != source_id:
            continue
        scope_matches = (task['dataset']['manifest_sha256'] == data['manifest_sha256']
                         and task['company_id'] == data['company']['company_id']
                         and task['source_sha256'] == source['source_sha256'])
        view = {key: deepcopy(task[key]) for key in ('task_id', 'label_zh', 'label_en')}
        view.update(selected_run_id=None, versions=[])
        for version in task['versions']:
            rid = version['run_id']; claimed.add(rid)
            item = {**deepcopy(version), 'available': False, 'selectable': False,
                    'archived': False, 'selected': False}
            try:
                if not scope_matches:
                    raise WorkspaceStateError('Task dataset/company/source pin mismatch')
                run = bound_run(rid)
                if run['manifest_sha256'] != version['manifest_sha256']:
                    raise WorkspaceStateError('Task run manifest pin mismatch')
                for name, expected in version['input_artifacts'].items():
                    if (name not in run['artifacts'] or
                            _hash(_path(root, run['path'] + '/' + name)) != expected):
                        raise WorkspaceStateError('Task input artifact pin mismatch')
                pin = _pin(task, run)
                archive = state['archived_versions'].get(rid)
                if archive is not None and archive != pin:
                    raise WorkspaceStateError('Archived version pin changed')
                item.update(available=True, selectable=archive is None, archived=archive is not None)
                artifacts = run['artifacts']
                item.update(status=artifacts.get('result.json', {}).get('status'),
                            reported_count=len(artifacts['extraction.json'].get('records', [])) if 'extraction.json' in artifacts else None,
                            normalized_count=len(artifacts['normalized.json'].get('records', [])) if 'normalized.json' in artifacts else None,
                            has_review=run['review'] is not None)
                if state['selections'].get(task['task_id']) == pin:
                    item['selected'] = True
                    view['selected_run_id'] = rid
            except ValueError as error:
                item['gap'] = str(error)
                gaps.append({'task_id': task['task_id'], 'run_id': rid, 'reason': str(error)})
            view['versions'].append(item)
        if task['task_id'] in state['selections'] and view['selected_run_id'] is None:
            gaps.append({'task_id': task['task_id'], 'reason': 'saved_selection_unavailable_or_pin_changed'})
        tasks.append(view)
    unassigned = []
    for rid, run in loaded.items():
        if rid not in claimed:
            unassigned.append({'run_id': rid, 'manifest_sha256': run['manifest_sha256'],
                               'available': True, 'selectable': False, 'archived': False,
                               'reason': 'task_not_registered'})
    task_ids = {task['task_id'] for task in tasks}
    for task_id, pin in state['selections'].items():
        if (pin['dataset_id'] == data['id'] and pin['source_snapshot_id'] == source_id
                and task_id not in task_ids):
            gaps.append({'task_id': task_id, 'reason': 'saved_task_no_longer_registered'})
    return {'revision': state['revision'], 'tasks': tasks, 'unassigned_runs': unassigned,
            'gaps': gaps, 'loaded_runs': loaded}


def update_state(root, payload):
    """Validate a user action against current frozen pins, then atomically save UI state."""
    required = {'action', 'expected_revision', 'dataset_id', 'source_snapshot_id', 'task_id', 'run_id'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise WorkspaceStateError('Exact action and scope fields required')
    action = payload['action']
    if action not in {'select_version', 'archive', 'restore'}:
        raise WorkspaceStateError('Unsupported workspace action')
    if type(payload['expected_revision']) is not int or payload['expected_revision'] < 0:
        raise WorkspaceStateError('Expected revision must be a nonnegative integer')
    for key in ('dataset_id', 'source_snapshot_id', 'task_id'):
        _identity(payload[key])
    rid = payload['run_id']
    if rid is not None:
        _identity(rid)
    elif action != 'select_version':
        raise WorkspaceStateError('Archive and restore require an explicit run')
    with _locked(root, write=True) as path:
        state = _read(path)
        if state['revision'] != payload['expected_revision']:
            raise WorkspaceConflictError('Workspace revision changed; reload before saving')
        data = load_dataset(root, payload['dataset_id'])
        view = material_tasks(root, data, payload['source_snapshot_id'], state)
        matches = [task for task in view['tasks'] if task['task_id'] == payload['task_id']]
        if len(matches) != 1:
            raise WorkspaceStateError('Task outside selected material')
        task = next(t for t in _tasks(root) if t['task_id'] == payload['task_id'])
        source = next(s for s in data['sources'] if s['source_snapshot_id'] == payload['source_snapshot_id'])
        if (task['company_id'] != data['company']['company_id'] or task['source_sha256'] != source['source_sha256']
                or task['dataset']['manifest_sha256'] != data['manifest_sha256']):
            raise WorkspaceStateError('Task scope pin changed')
        before = deepcopy(state)
        pin = None
        if rid is not None:
            versions = [v for v in matches[0]['versions'] if v['run_id'] == rid and v['available']]
            if len(versions) != 1:
                raise WorkspaceStateError('Run outside task or its manifest pin changed')
            pin = _pin(task, {'id': rid, 'manifest_sha256': versions[0]['manifest_sha256']})
        if action == 'select_version':
            if rid is None:
                state['selections'].pop(task['task_id'], None)
            else:
                if rid in state['archived_versions']:
                    raise WorkspaceStateError('Restore an archived version before selecting it')
                state['selections'][task['task_id']] = pin
        elif action == 'archive':
            if any(p['run_id'] == rid for p in state['selections'].values()):
                raise WorkspaceStateError('Selected versions cannot be archived')
            state['archived_versions'][rid] = pin
        else:
            state['archived_versions'].pop(rid, None)
        if state == before:
            return deepcopy(state)
        state['revision'] += 1
        state['audit_events'].append({'revision': state['revision'],
            'timestamp': datetime.now(timezone.utc).isoformat(), 'action': action,
            'task_id': task['task_id'], 'reference': pin,
            'previous_selection': before['selections'].get(task['task_id'])})
        _validate_state(state)
        _save(path, state)
        return deepcopy(state)
