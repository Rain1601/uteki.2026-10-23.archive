"""Read published observation events without executing or repairing a run.

The observation descriptor is not permission to read an arbitrary output path.
The host must explicitly allow its business output root as well.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from apps.review_workbench.data.evaluation_artifacts import _path
from apps.review_workbench.data.agent_runs_shared import (
    artifact_page, project_artifact, summarize_calls,
)

SCHEMA = 'agent-observation-v1'
ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,199}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
EVENT_TYPES = frozenset({'run.started', 'run.finished', 'step.started', 'step.action_started',
                         'step.finished', 'model_call.started', 'model_call.finished', 'artifact.published'})


def _identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid observation identity')
    return value


def _json(path, maximum=262144):
    if path.stat().st_size > maximum:
        raise ValueError('Observation metadata exceeds its size limit')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('Observation metadata must be an object')
    return value


def _output(descriptor, output_roots):
    value = descriptor.get('output_root')
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('Observed output requires an explicit host path')
    target = Path(value)
    for root in output_roots:
        allowed = Path(root).resolve()
        try:
            relative = target.relative_to(allowed)
        except ValueError:
            continue
        if relative.parts:
            checked = _path(allowed, relative.as_posix())
            if checked != target:
                raise ValueError('Observed output path is not canonical')
            return checked
    raise ValueError('Observed output is outside the configured output roots')


def _descriptor(observation_root, identity, output_roots):
    _identity(identity)
    if observation_root is None:
        raise KeyError('Live observation is not configured')
    base = Path(observation_root)
    if base.is_symlink():
        raise ValueError('Observation root cannot be a symlink')
    folder = _path(base, identity)
    if not folder.is_dir():
        raise KeyError('Unknown observed run')
    descriptor = _json(_path(folder, 'descriptor.json'), 65536)
    if (descriptor.get('schema_version') != SCHEMA or descriptor.get('root_run_id') != identity
            or descriptor.get('run_id') != identity or not isinstance(descriptor.get('generation'), str)
            or not ID.fullmatch(descriptor['generation'])):
        raise ValueError('Observation descriptor identity mismatch')
    output = _output(descriptor, output_roots)
    store = base.resolve()
    if store.is_relative_to(output) or output.is_relative_to(store):
        raise ValueError('Observation and business output must be separate')
    return folder, descriptor, output


def registered_ids(observation_root):
    if observation_root is None or not Path(observation_root).exists():
        return set()
    root = Path(observation_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Invalid observation root')
    return {p.name for p in root.iterdir() if ID.fullmatch(p.name) and
            (p.is_symlink() or (p.is_dir() and (p / 'descriptor.json').exists()))}


def _read_events(folder, descriptor, revision=None):
    directory = _path(folder, 'events')
    if not directory.is_dir():
        raise ValueError('Observation event directory is missing')
    names = sorted(p.name for p in directory.iterdir() if re.fullmatch(r'\d{12}\.json', p.name))
    high = len(names)
    if revision is not None and (type(revision) is not int or not 0 <= revision <= high):
        raise ValueError('Invalid observation revision')
    end = high if revision is None else revision
    events = []
    for seq, name in enumerate(names, 1):
        if name != f'{seq:012d}.json':
            raise ValueError('Observation sequence has a gap')
        if seq > end:
            break
        event = _json(_path(directory, name))
        if (event.get('schema_version') != SCHEMA or event.get('generation') != descriptor['generation']
                or event.get('root_run_id') != descriptor['root_run_id'] or event.get('seq') != seq
                or event.get('event_id') != f"{descriptor['root_run_id']}:{seq}"
                or event.get('type') not in EVENT_TYPES or not isinstance(event.get('data'), dict)):
            raise ValueError('Invalid observation event')
        _identity(event.get('run_id'))
        for field in ('step_id', 'parent_run_id', 'parent_step_id', 'call_id'):
            if event.get(field) is not None:
                _identity(event[field])
        events.append(event)
    return events, end


def _connection(folder, descriptor, terminal, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Observation clock must include a timezone')
    at = None
    try:
        heartbeat = _json(_path(folder, 'heartbeat.json'), 65536)
        if (heartbeat.get('schema_version') != SCHEMA or heartbeat.get('root_run_id') != descriptor['root_run_id']
                or heartbeat.get('generation') != descriptor['generation']):
            raise ValueError('Heartbeat belongs to another run generation')
        at = heartbeat.get('heartbeat_at')
        timestamp = datetime.fromisoformat(at)
        if timestamp.tzinfo is None:
            raise ValueError('Heartbeat has no timezone')
        age = (now - timestamp).total_seconds()
        healthy = -5 <= age <= 15
    except (OSError, ValueError, TypeError):
        healthy = False
    return {'heartbeat_at': at, 'server_now': now.isoformat(),
            'connection_state': 'complete' if terminal else 'connected' if healthy else 'stale'}


def _kind(ref):
    """Classify from writer-published paths; unknown files stay restricted."""
    path = Path(ref['path'])
    name = path.name
    if name.startswith('.') or path.suffix != '.json':
        return 'restricted'
    if 'source-config' in name or 'budget' in name or 'credential' in name:
        return 'restricted'
    if 'config' in name or name in {'prompt.json', 'method.json'}:
        return 'config'
    if path.parent.name == 'calls' and (name.endswith('-start.json') or name.endswith('-end.json')):
        return 'model_call'
    allowed = {'input', 'decision', 'receipt', 'feedback', 'result', 'request', 'scope', 'packet', 'extraction',
               'normalized', 'job', 'manifest', 'artifact-index', 'evidence-bundle', 'system-prompt-effective',
               'prompt', 'model-usage', 'trace', 'handoff', 'assessment', 'errors', 'diagnostics',
               'business_map', 'revenue', 'validation', 'source_packet'}
    if path.stem in allowed or path.stem.startswith(('plan-', 'decision-', 'review-', 'usage-')) or 'artifacts' in path.parts:
        return path.stem if path.stem in {'input', 'decision', 'receipt', 'feedback', 'result'} else 'artifact'
    return 'restricted'


def _ref(ref, event, references):
    if not isinstance(ref, dict):
        return None
    owner, artifact_id = ref.get('run_id'), ref.get('artifact_id')
    _identity(owner)
    _identity(artifact_id)
    if not isinstance(ref.get('sha256'), str) or not SHA.fullmatch(ref['sha256']):
        raise ValueError('Published artifact hash mismatch')
    path = ref.get('path')
    # Validate lexical scope before the host root is used at read time.
    if not isinstance(path, str) or not path or Path(path).is_absolute() or '\\' in path or any(p in {'.', '..'} for p in path.split('/')):
        raise ValueError('Invalid published artifact path')
    if type(ref.get('size_bytes')) is not int or ref['size_bytes'] < 0:
        raise ValueError('Invalid published artifact size')
    identity = 'artifact-' + hashlib.sha256(f'{owner}/{artifact_id}'.encode()).hexdigest()[:32]
    previous = references.get(identity)
    if owner != event['run_id'] and not (event['data'].get('reused') is True and previous):
        raise ValueError('Published artifact owner mismatch')
    if previous and any(previous[k] != ref[k] for k in ('run_id', 'path', 'sha256', 'size_bytes')):
        raise ValueError('Published artifact identity has conflicting content')
    produced_step = previous['step_id'] if previous else event.get('step_id')
    references[identity] = dict(ref, step_id=produced_step)
    kind = _kind(ref)
    return {'id': identity, 'run_id': owner, 'label': Path(path).name,
            'kind': kind, 'availability': 'restricted' if kind == 'restricted' else 'available',
            'sha256': ref['sha256'], 'size_bytes': ref['size_bytes'],
            'step_id': references[identity]['step_id']}


def _read_ref(output, ref, maximum=128 * 1024 * 1024):
    path = _path(output, ref['path'])
    if ref['size_bytes'] > maximum or path.stat().st_size != ref['size_bytes']:
        raise ValueError('Artifact exceeds the supported inspection size')
    raw = path.read_bytes()
    if len(raw) != ref['size_bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('Published artifact changed or is incomplete')
    return json.loads(raw)


def _counter(value):
    return value if type(value) is int and value >= 0 else None


def _period(value):
    # Published scope files and safe event metadata may use an object or its
    # JSON string. Compare the same explicit period without inferring dates.
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if not isinstance(parsed, (dict, list)):
            return value
        value = parsed
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _scope_view(scope):
    if not isinstance(scope, dict):
        raise ValueError('Observed scope must be an object')
    value = project_artifact(scope, 'artifact')
    for plural, singular in (('company_ids', 'company_id'), ('source_snapshot_ids', 'source_snapshot_id')):
        values = scope.get(plural)
        if values is None:
            values = [scope[singular]] if scope.get(singular) else []
        if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError('Invalid observed business scope')
        value[plural] = list(values)
    if len(value['company_ids']) == 1:
        value['company_id'] = value['company_ids'][0]
    periods = scope.get('periods', [])
    if not isinstance(periods, list):
        raise ValueError('Invalid observed periods')
    value['periods'] = [_period(p) for p in periods]
    return value


def _scope_relation(parent, child, *, previous_parent=None):
    for key in ('company_ids', 'source_snapshot_ids', 'periods'):
        if parent.get(key) and child.get(key) and not set(child[key]) <= set(parent[key]):
            raise ValueError('Observed child scope is outside its parent scope')
        if previous_parent and previous_parent.get(key) and child.get(key) and not parent.get(key):
            raise ValueError('Observed parent scope removes its child scope boundary')


def _update_scope(runs, identity, updated):
    run = runs[identity]
    previous = run['scope']
    if previous.get('company_ids') and set(previous['company_ids']) != set(updated.get('company_ids', [])):
        raise ValueError('Observed scope changes its selected company')
    if run.get('parent_run_id'):
        _scope_relation(runs[run['parent_run_id']]['scope'], updated)
    for child in runs.values():
        if child.get('parent_run_id') == identity:
            _scope_relation(updated, child['scope'], previous_parent=previous)
    run['scope'] = updated


def _call(record, event, file_ref, run):
    cid = event['call_id'] or event['data'].get('call_id')
    if not cid or record.get('call_id') != cid:
        raise ValueError('Model call record identity mismatch')
    u = record.get('usage') or {}
    raw = record.get('raw_usage') or {}
    if not isinstance(u, dict) or not isinstance(raw, dict):
        raise ValueError('Invalid model usage record')
    if any(not isinstance(u.get(k) or {}, dict) for k in ('input_tokens_details', 'output_tokens_details')):
        raise ValueError('Invalid model usage details')
    presence = record.get('usage_presence')
    if presence not in {'reported', 'absent', 'unknown'}:
        presence = 'reported' if all(_counter(raw.get(k)) is not None for k in ('prompt_tokens', 'completion_tokens')) else 'unknown'
    from .agent_runs_shared import call_configuration_snapshot, configured_value, configured_thinking
    snapshot = call_configuration_snapshot(record, config={'reasoning_effort': event['data'].get('reasoning_effort')})
    return {'call_id': cid, 'run_id': event['run_id'], 'step_id': event.get('step_id'),
            'role': event['data'].get('role') or run.get('role', 'unknown'),
            'stage': record.get('stage'), 'provider': record.get('provider'),
            'requested_model': record.get('requested_model'), 'actual_upstream_model': record.get('actual_upstream_model'),
            'reasoning_effort': configured_value(snapshot, 'reasoning_effort'),
            'thinking_mode': configured_thinking(snapshot),
            'configuration_snapshot': snapshot,
            'request_id': record.get('request_id'), 'response_id': record.get('response_id'),
            'http_status': record.get('http_status'), 'provider_finish_reason': record.get('provider_finish_reason'),
            'status': record.get('status'), 'started_at': record.get('started_at'), 'ended_at': record.get('ended_at'),
            'elapsed_seconds': record.get('elapsed_seconds'), 'input_tokens': _counter(u.get('input_tokens')),
            'output_tokens': _counter(u.get('output_tokens')),
            'cached_tokens': _counter((u.get('input_tokens_details') or {}).get('cached_tokens')),
            'reasoning_tokens': _counter((u.get('output_tokens_details') or {}).get('reasoning_tokens')),
            'usage_presence': presence, 'usage_source': record.get('usage_source', 'saved_model_record'),
            'estimated_usd': record.get('estimated_usd'), 'actual_billed_usd': record.get('actual_billed_usd'),
            'cost_basis': record.get('cost_basis'), 'files': [file_ref] if file_ref else []}


def _project(folder, descriptor, output, events, revision, *, now=None):
    identity = descriptor['root_run_id']
    runs, steps, calls, artifacts, references, finished_calls = {}, {}, {}, {}, {}, set()
    diagnostics = []
    terminal = False
    state = {'execution': 'unknown', 'connection': 'stale', 'delivery': 'not_recorded',
             'quality': 'not_evaluated', 'adoption': 'not_recorded', 'stop_reason': None}
    scope = _scope_view(descriptor.get('scope', {}))
    initial_scope = dict(scope)
    for event in events:
        kind, data, rid, sid = event['type'], event['data'], event['run_id'], event.get('step_id')
        if terminal:
            raise ValueError('Observation contains events after its root terminal')
        if kind == 'run.started':
            if rid in runs or (rid != identity and event.get('parent_run_id') not in runs):
                raise ValueError('Invalid observed parent or duplicate run')
            run_scope = _scope_view(data.get('scope', {}))
            if rid != identity:
                parent_step = event.get('parent_step_id')
                if parent_step and (parent_step not in steps or steps[parent_step]['run_id'] != event['parent_run_id']):
                    raise ValueError('Observed parent step is missing or belongs to another run')
                _scope_relation(runs[event['parent_run_id']]['scope'], run_scope)
            runs[rid] = {'id': rid, 'parent_run_id': event.get('parent_run_id'),
                         'parent_step_id': event.get('parent_step_id'), 'kind': data.get('kind'),
                         'role': data.get('role'), 'status': 'running', 'scope': run_scope}
            if rid == identity:
                state['execution'] = 'running'
                scope = run_scope
            elif event.get('parent_step_id') in steps:
                steps[event['parent_step_id']]['child_run_ids'].append(rid)
        elif rid not in runs:
            raise ValueError('Observation event precedes its run start')
        if sid and sid not in steps and kind in {'step.started', 'step.action_started', 'step.finished'}:
            steps[sid] = {'id': sid, 'run_id': rid, 'ordinal': data.get('ordinal'), 'action': None,
                          'phase': 'planning', 'status': 'running', 'error_code': None, 'elapsed_seconds': None,
                          'started_at': event['at'], 'ended_at': None, 'files': [], 'call_ids': [], 'child_run_ids': []}
        if sid in steps and steps[sid]['run_id'] != rid:
            raise ValueError('Step belongs to another observed run')
        if kind.startswith('step.'):
            if not sid:
                raise ValueError('Step event requires a step identity')
            row = steps[sid]
            row['action'] = data.get('action', row['action'])
            row['ordinal'] = data.get('ordinal', row['ordinal'])
            row['phase'] = data.get('phase', 'executing' if kind == 'step.action_started' else row['phase'])
            if kind == 'step.finished':
                row.update(status=data.get('status', 'finished'), error_code=data.get('error_code'),
                           elapsed_seconds=data.get('elapsed_seconds'), ended_at=event['at'], phase='finished')
        # All payloads are obtained only through references published within this revision.
        for field, value in data.items():
            if field == 'ref' or field.endswith('_ref'):
                public = _ref(value, event, references)
                if public:
                    artifacts[public['id']] = public
                    if sid in steps and public['id'] not in {r['id'] for r in steps[sid]['files']}:
                        steps[sid]['files'].append(public)
                    if public['label'] == 'scope.json' and public['run_id'] == rid:
                        updated = _scope_view(_read_ref(output, references[public['id']], maximum=65536))
                        _update_scope(runs, rid, updated)
                        if rid == identity:
                            scope = updated
        if kind.startswith('model_call.'):
            file_ref = _ref(data.get('record_ref'), event, references)
            if file_ref is None:
                diagnostics.append('A model call has no published record; usage is unknown.')
                continue
            record = _read_ref(output, references[file_ref['id']], maximum=262144)
            call = _call(record, event, file_ref, runs[rid])
            cid = call['call_id']
            if cid in calls:
                old = calls[cid]
                if any(old.get(k) != call.get(k) for k in ('run_id', 'step_id', 'provider', 'requested_model')):
                    raise ValueError('Model call ownership or model changed')
                previous = old['configuration_snapshot']
                current = call['configuration_snapshot']
                if previous['capture_kind'] == 'before_dispatch':
                    if current['capture_kind'] == 'before_dispatch' and current['sha256'] != previous['sha256']:
                        raise ValueError('Model call configuration changed between start and end')
                    if current['capture_kind'] == 'historical_partial':
                        call['configuration_snapshot'] = previous
                        call['reasoning_effort'] = old['reasoning_effort']
                        call['thinking_mode'] = old['thinking_mode']
                if cid in finished_calls and call != old:
                    raise ValueError('Model call has conflicting terminal records')
            calls[cid] = call
            if kind == 'model_call.finished':
                finished_calls.add(cid)
            if sid in steps and cid not in steps[sid]['call_ids']:
                steps[sid]['call_ids'].append(cid)
        if kind == 'run.finished':
            if runs[rid]['status'] != 'running':
                raise ValueError('Duplicate observed run terminal')
            runs[rid]['status'] = data.get('status', 'finished')
            if rid == identity:
                terminal = True
                state.update(execution=data.get('status', 'unknown'),
                             delivery=data.get('business_status') or 'not_recorded',
                             quality=data.get('quality') or 'not_evaluated',
                             adoption=data.get('adoption') or 'not_recorded', stop_reason=data.get('stop_reason'))
    connection = _connection(folder, descriptor, terminal, now=now)
    state['connection'] = connection['connection_state']
    if not terminal and state['connection'] == 'stale':
        state['execution'] = 'unknown'
    if not scope.get('company_ids') or not scope.get('source_snapshot_ids'):
        diagnostics.append('Business scope has not yet been published; no default scope was selected.')
    if calls and any(c['usage_presence'] != 'reported' for c in calls.values()):
        diagnostics.append('Some model usage is not confirmed by the provider; recorded zero is not confirmed zero consumption.')
    rows = list(artifacts.values())
    usage = summarize_calls(list(calls.values()))
    usage['own'] = summarize_calls([c for c in calls.values() if c['run_id'] == identity])
    result = {'schema_version': 'agent-run-view-v1', 'id': identity, 'root_run_id': identity,
              'agent': 'data', 'title': str(descriptor.get('title') or identity),
              'origin': descriptor.get('origin', 'unknown'), 'live': True, 'root_terminal': terminal,
              'revision': revision, 'started_at': descriptor.get('started_at'), 'state': state, 'scope': scope,
              'initial_scope': initial_scope,
              'run_tree': list(runs.values()), 'steps': list(steps.values()), 'artifacts': rows,
              'calls': list(calls.values()), 'usage': usage,
              'inputs': [r for r in rows if r['label'] in {'request.json', 'job.json', 'packet.json'}],
              'configs': [r for r in rows if r['kind'] == 'config' or r['label'] == 'system-prompt-effective.json'],
              'diagnostics': diagnostics, 'integrity': {'status': 'published_references', 'scope': 'selected_revision'},
              'links': [], **connection}
    return result, references


def load_run(observation_root, identity, *, output_roots=(), revision=None, now=None):
    folder, descriptor, output = _descriptor(observation_root, identity, output_roots)
    events, high = _read_events(folder, descriptor, revision)
    return _project(folder, descriptor, output, events, high, now=now)[0]


def list_runs(observation_root, *, output_roots=()):
    result = []
    for identity in sorted(registered_ids(observation_root)):
        try:
            view = load_run(observation_root, identity, output_roots=output_roots)
            result.append({k: v for k, v in view.items() if k not in {'steps', 'artifacts', 'calls', 'inputs', 'configs', 'run_tree'}})
        except (OSError, ValueError, KeyError):
            result.append({'id': identity, 'root_run_id': identity, 'agent': 'data', 'title': identity,
                           'origin': 'unknown', 'live': True, 'root_terminal': False, 'revision': 0,
                           'scope': {}, 'state': {'execution': 'unknown', 'connection': 'unavailable',
                           'delivery': 'not_recorded', 'quality': 'not_evaluated', 'adoption': 'not_recorded', 'stop_reason': None},
                           'usage': summarize_calls([]), 'diagnostics': ['Observation unavailable, incomplete or outside the configured scope.']})
    return result


def load_step(observation_root, identity, step_id, *, output_roots=(), revision=None):
    _identity(step_id)
    view = load_run(observation_root, identity, output_roots=output_roots, revision=revision)
    for step in view['steps']:
        if step['id'] == step_id:
            return step
    raise KeyError('Unknown step in selected run')


def read_artifact(observation_root, identity, artifact_id, *, output_roots=(), revision=None, cursor=None, browse=None):
    _identity(artifact_id)
    folder, descriptor, output = _descriptor(observation_root, identity, output_roots)
    events, high = _read_events(folder, descriptor, revision)
    view, references = _project(folder, descriptor, output, events, high)
    ref = next((r for r in view['artifacts'] if r['id'] == artifact_id), None)
    if ref is None:
        raise KeyError('Unknown artifact in selected run')
    if ref['availability'] != 'available':
        raise ValueError('Artifact is restricted or unavailable')
    value = _read_ref(output, references[artifact_id])
    return artifact_page(ref, project_artifact(value, ref['kind']), cursor=cursor, browse=browse)


def _encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def _decode(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Invalid event cursor')
    try:
        result = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid event cursor') from error
    if not isinstance(result, dict):
        raise ValueError('Invalid event cursor')
    return result


def read_events(observation_root, identity, *, output_roots=(), after='0', limit=100, now=None):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Event limit must be 1..500')
    folder, descriptor, output = _descriptor(observation_root, identity, output_roots)
    all_events, latest = _read_events(folder, descriptor)
    start, high = 0, latest
    if after not in ('0', 0, None):
        cursor = _decode(after)
        if (set(cursor) != {'version', 'run_id', 'generation', 'after', 'high'} or cursor['version'] != 1
                or cursor['run_id'] != identity or cursor['generation'] != descriptor['generation']
                or type(cursor['after']) is not int or type(cursor['high']) is not int
                or not 0 <= cursor['after'] <= cursor['high'] <= latest):
            raise ValueError('Event cursor belongs to another run or revision')
        start = cursor['after']
        high = cursor['high'] if start < cursor['high'] else latest
    selected = all_events[start:min(start + limit, high)]
    delivered = start + len(selected)
    root_terminal = any(e['type'] == 'run.finished' and e['run_id'] == identity for e in all_events[:high])
    # Event payload files and private host paths are accessed via dedicated safe endpoints.
    public = [{k: e[k] for k in ('event_id', 'type', 'run_id', 'parent_run_id', 'parent_step_id', 'seq', 'at', 'step_id', 'call_id')}
              for e in selected]
    return {'events': public, 'last_delivered_seq': delivered, 'high_watermark': high,
            'next_cursor': _encode({'version': 1, 'run_id': identity, 'generation': descriptor['generation'], 'after': delivered, 'high': high}),
            'has_more': delivered < high, 'root_terminal': root_terminal,
            **_connection(folder, descriptor, root_terminal, now=now)}
