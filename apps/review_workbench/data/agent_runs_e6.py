"""Read-only, explicitly registered sealed retrieval and source-review histories.

Display registration is not an Agent input. No filesystem paths from requests,
model calls, reconciliation, scoring or edits enter this adapter.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading

from .evaluation_artifacts import _path, _hash
from .agent_runs_history import _identity
from .agent_runs_shared import (_clean, artifact_page, project_artifact, summarize_calls,
                               call_configuration_snapshot, configured_value, configured_thinking)

REGISTRATION = 'data/evaluation_views/e6-runs-v1.json'
ADAPTER = 'sealed-data-evaluation-v1'
_SHA = re.compile(r'^[a-f0-9]{64}$')
_CACHE = {}
_LOCK = threading.RLock()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _registry(root):
    path = _path(root, REGISTRATION)
    if not path.exists():
        return []
    value = json.loads(path.read_text())
    if value.get('schema_version') != 'e6-runs-registration-v1' or not isinstance(value.get('runs'), list):
        raise ValueError('Unsupported sealed evaluation registration')
    ids = [_identity(e['id']) for e in value['runs']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate sealed evaluation identity')
    return value['runs']


def registered_ids(root):
    return [e['id'] for e in _registry(root)]


def _pinned(root, relative, expected):
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError('Explicit artifact hash required')
    path = _path(root, relative)
    if PurePosixPath(relative).parts[0] not in {'output', 'experiments', 'data'}:
        raise ValueError('Unsupported registered evidence directory')
    if _hash(path) != expected:
        raise ValueError('Sealed evaluation evidence integrity mismatch: ' + relative)
    return path


def _kind(relative):
    name = PurePosixPath(relative).name
    if 'implementation' in PurePosixPath(relative).parts or not name.endswith('.json'):
        return 'restricted'
    if '/calls/' in '/' + relative:
        return 'model_call'
    if 'config' in name:
        return 'config'
    if name in {'input.json', 'request.json', 'question-input.json', 'source-repair-input.json'} or name.endswith('-input.json'):
        return 'input'
    if name == 'result.json' or 'response' in name or name.endswith('-parsed.json'):
        return 'result'
    return 'artifact'


def _compact(value):
    # Evidence internals remain available through pinned artifact inspection.
    omitted = {'evidence_refs', 'original_proofs', 'raw_original_proofs', 'proofs', 'calls', 'raw_text',
               'integrity_and_isolation', 'reference_access', 'manifest_sha256', 'run_manifest_sha256'}
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if k not in omitted}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _reserved_cost(value):
    """Reject invalid saved amounts before they enter display cost totals."""
    if type(value) not in (str, int, float):
        raise ValueError('Invalid saved cost reservation')
    try:
        amount = Decimal(str(value))
    except DecimalException as error:
        raise ValueError('Invalid saved cost reservation') from error
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid saved cost reservation')
    return amount


def _build(root, entry):
    rid = _identity(entry['id'])
    if entry.get('adapter') != ADAPTER or entry.get('kind') not in {'autonomous_retrieval', 'source_repair', 'network_failure'}:
        raise ValueError('Unsupported registered evaluation adapter or kind')
    base = entry['path']
    folder = _path(root, base)
    manifest_path = _pinned(root, base + '/manifest.json', entry['manifest_sha256'])
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError('Sealed run manifest must be an object')
    files = manifest.get('files')
    if not isinstance(files, dict) or 'result.json' not in files:
        raise ValueError('Sealed run has no result binding')
    internal, refs, values = {}, [], {}
    stamps = [(base + '/manifest.json', entry['manifest_sha256'], manifest_path.stat())]
    for relative, sha in files.items():
        path = _pinned(root, base + '/' + relative, sha)
        stamps.append((base + '/' + relative, sha, path.stat()))
        kind = _kind(relative)
        if kind == 'restricted':
            continue
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('Artifact exceeds inspection limit')
        value = json.loads(path.read_text())
        ref = {'id': 'sealed-' + hashlib.sha256((rid + ':' + relative).encode()).hexdigest()[:24],
               'run_id': rid, 'step_id': None, 'label': relative, 'kind': kind,
               'availability': 'available', 'sha256': sha, 'size_bytes': path.stat().st_size}
        internal[ref['id']] = {'ref': ref, 'path': base + '/' + relative, 'value': value}
        refs.append(ref)
        values[relative] = value
    ref_by_path = {r['label']: r for r in refs}
    result = values['result.json']
    expected_schema = 'data-retrieval-cycle-v1' if entry['kind'] == 'autonomous_retrieval' else 'data-answer-review-result-v1'
    if result.get('schema_version') != expected_schema or result.get('scope') != entry.get('scope'):
        raise ValueError('Registered run schema/scope mismatch')
    scope = entry['scope']
    if not scope.get('company_ids') or not scope.get('source_snapshot_ids'):
        raise ValueError('Explicit company/source scope required')

    steps, association, reviews = [], {}, []
    def step(relative, action, status, phase, ordinal=None, error_code=None):
        sid = rid + '--step-' + str(len(steps) + 1).zfill(3)
        owned = [r for r in refs if r['label'].startswith(relative + '/') and '/calls/' not in r['label']
                 and (phase != 'query' or '/' not in r['label'][len(relative) + 1:])]
        for ref in owned:
            ref['step_id'] = sid
        row = {'id': sid, 'run_id': rid, 'ordinal': len(steps) + 1, 'action': action, 'phase': phase,
               'status': status, 'error_code': error_code, 'elapsed_seconds': None,
               'files': owned, 'call_ids': [], 'child_run_ids': [], 'historical_ordinal': ordinal, 'historical_path': relative,
               'attempt': relative.split('/')[0] if relative.startswith('attempt-') else None}
        steps.append(row)
        return row
    for relative, value in values.items():
        if isinstance(value, dict) and value.get('schema_version') == 'autonomous-result-v2' and relative.endswith('/query/result.json'):
            prefix = str(PurePosixPath(relative).parent)
            for trace in value.get('trace', []):
                turn = prefix + '/turn-' + str(trace['step']).zfill(3)
                receipt = values.get(turn + '/receipt.json', {})
                if receipt.get('step') != trace['step'] or receipt.get('action') != trace['action'] or receipt.get('status') != trace['status']:
                    raise ValueError('Trace receipt binding mismatch')
                row = step(turn, trace['action'], trace['status'], 'query', trace['step'], receipt.get('error_code'))
                model_prefix = str(PurePosixPath(prefix).parent) + '/model/'
                for ap, attempt in values.items():
                    if ap.startswith(model_prefix) and re.search(r'decision-\d+-attempt-\d+\.json$', ap) and attempt.get('decision') == trace['step']:
                        ref_by_path[ap]['step_id'] = row['id']; row['files'].append(ref_by_path[ap])
                        for call in attempt.get('calls', []):
                            cp = model_prefix + call['path']
                            if files.get(cp) != call['sha256']:
                                raise ValueError('Decision call hash binding mismatch')
                            association[cp] = row['id']
                        visible = attempt.get('visible_output')
                        if visible:
                            vp = model_prefix + visible['path']
                            if files.get(vp) != visible['sha256']:
                                raise ValueError('Decision output hash binding mismatch')
                            if vp in ref_by_path:
                                ref_by_path[vp]['step_id'] = row['id']; row['files'].append(ref_by_path[vp])
    for relative, value in values.items():
        if isinstance(value, dict) and value.get('schema_version') == 'data-answer-review-result-v1':
            prefix = str(PurePosixPath(relative).parent)
            prefix = '' if prefix == '.' else prefix
            row = step(prefix, 'review_sources_and_question', value['status'], 'review')
            if not prefix:
                row['files'] = [r for r in refs if '/calls/' not in r['label']]
            for ref in refs:
                if (not prefix or ref['label'].startswith(prefix + '/')) and '/calls/' in ref['label']:
                    association[ref['label']] = row['id']
            reviews.append({'label': prefix or entry['kind'], 'status': value['status'],
                            'analysis_eligible': value.get('analysis_eligible'),
                            'assessment': _compact(value.get('assessment')), 'failures': value.get('failures', []),
                            'question_protocol_repair_attempted': value.get('question_protocol_repair_attempted'),
                            'source_protocol_repair_attempted': value.get('source_protocol_repair_attempted')})
    call_groups = {}
    for relative, value in values.items():
        if '/calls/' not in '/' + relative or not re.search(r'-(start|end)\.json$', relative):
            continue
        cid = value['call_id']; group = call_groups.setdefault(cid, {})
        stage = 'end' if relative.endswith('-end.json') else 'start'
        if stage in group:
            raise ValueError('Duplicate sealed call identity')
        group[stage] = (relative, value)
    # Recover execution order from explicit attempt/review paths, keeping the
    # stable step IDs and call associations assigned above.
    steps.sort(key=lambda s: (int(s['attempt'].split('-')[-1]) if s.get('attempt') else 0,
                             0 if s['phase'] == 'query' else 1,
                             s.get('historical_ordinal') or 0, s['historical_path']))
    for ordinal, row in enumerate(steps, 1): row['ordinal'] = ordinal
    calls = []
    for cid, group in call_groups.items():
        rel, end = group.get('end', group.get('start'))
        start = group.get('start', ('', {}))[1]
        if any(start.get(k) != end.get(k) for k in ('call_id', 'provider', 'requested_model', 'started_at') if k in start):
            raise ValueError('Saved model call identity changed')
        sid = association.get(rel) or association.get(group.get('start', ('',))[0])
        config_prefix = rel.split('/calls/')[0]
        config = values.get(config_prefix + '/model-config.json', {})
        snapshot = call_configuration_snapshot(end, start=start, config=config)
        usage = end.get('usage') or {}
        call_refs = [ref_by_path[pair[0]] for pair in group.values()]
        for ref in call_refs:
            ref['step_id'] = sid
        row = {'call_id': cid, 'run_id': rid, 'step_id': sid,
               'role': 'question_reviewer' if '/question-model/' in '/' + rel else 'source_reviewer' if '/review-' in '/' + rel or not rel.startswith('attempt-') else 'planner',
               'configuration_snapshot': snapshot, 'reasoning_effort': configured_value(snapshot, 'reasoning_effort'),
               'thinking_mode': configured_thinking(snapshot), 'files': call_refs,
               **{k: end.get(k) for k in ('provider', 'requested_model', 'actual_upstream_model', 'stage', 'status', 'started_at', 'ended_at', 'elapsed_seconds', 'estimated_usd', 'actual_billed_usd', 'request_id', 'response_id', 'http_status', 'provider_finish_reason', 'usage_presence')},
               'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
               'cached_tokens': (usage.get('input_tokens_details') or {}).get('cached_tokens'),
               'reasoning_tokens': (usage.get('output_tokens_details') or {}).get('reasoning_tokens')}
        calls.append(row)
        if sid:
            s = next(s for s in steps if s['id'] == sid); s['call_ids'].append(cid); s['files'].extend(call_refs)
    evaluation_values, evaluation_refs = {}, []
    for name, pin in entry.get('evaluation', {}).items():
        path = _pinned(root, pin['path'], pin['sha256']); value = json.loads(path.read_text())
        stamps.append((pin['path'], pin['sha256'], path.stat()))
        ref = {'id': 'eval-' + hashlib.sha256((rid + ':' + name).encode()).hexdigest()[:24],
               'run_id': rid, 'step_id': None, 'label': name + ' · ' + path.name, 'kind': 'evaluation',
               'availability': 'available', 'sha256': pin['sha256'], 'size_bytes': path.stat().st_size}
        refs.append(ref); evaluation_refs.append(ref)
        internal[ref['id']] = {'ref': ref, 'path': pin['path'], 'value': value}
        selector = pin.get('selector')
        if selector:
            rows = value.get(selector['key'], [])
            matches = [r for r in rows if r.get(selector['field']) == selector['value']]
            if len(matches) != 1:
                raise ValueError('Independent assessment selection mismatch')
            value = matches[0]
        if name == 'independent_assessment':
            evidence = value.get('evidence_refs')
            if isinstance(evidence, dict):
                if evidence.get('run') != base or evidence.get('run_manifest_sha256') != entry['manifest_sha256']:
                    raise ValueError('Independent assessment run binding mismatch')
                if evidence.get('standard_sha256') != entry['evaluation']['standard']['sha256']:
                    raise ValueError('Independent assessment standard binding mismatch')
            else:
                expected_review = base
                if entry['kind'] == 'autonomous_retrieval':
                    candidates = [p.rsplit('/', 1)[0] for p, v in values.items() if isinstance(v, dict)
                                  and v.get('schema_version') == 'data-answer-review-result-v1']
                    if not candidates: raise ValueError('Independent audit has no bound review')
                    expected_review = base + '/' + sorted(candidates)[-1]
                if value.get('path') != expected_review:
                    raise ValueError('Independent audit review binding mismatch')
        evaluation_values[name] = value
    assessment = evaluation_values.get('independent_assessment')
    verdict = assessment.get('overall_verdict') or assessment.get('status') if assessment else None
    passed = result['status'] in {'reviewed_data_ready', 'reviewed'}
    # Select only a bound delivered packet, never independent gold values.
    review_inputs = [p for p in values if PurePosixPath(p).name == 'input.json' and isinstance(values[p], dict)
                     and values[p].get('schema_version') == 'data-answer-review-input-v1']
    packet = values[sorted(review_inputs)[-1]] if review_inputs else {}
    if packet and packet.get('scope') != scope:
        raise ValueError('Delivered packet scope mismatch')
    facts = []
    for fact in packet.get('facts', []):
        value = fact.get('value', {})
        if fact.get('kind') != 'record':
            continue
        facts.append({'fact_id': fact['fact_id'], 'metric': value.get('metric_id'),
                      'company_id': value.get('entity_id'), 'company': value.get('entity_id'),
                      'source_snapshot_id': value.get('source_snapshot_id'), 'source_id': value.get('source_snapshot_id'),
                      'block_id': (fact.get('citations') or [{}])[0].get('block_id'),
                      'row': ((fact.get('citations') or [{}])[0].get('cell') or {}).get('row'),
                      'column': ((fact.get('citations') or [{}])[0].get('cell') or {}).get('column'),
                      'period_data': value.get('period'), 'period': ((value.get('period') or {}).get('start') or '') + ' → ' + ((value.get('period') or {}).get('end') or ''), 'period_end': (value.get('period') or {}).get('end'),
                      'value': value.get('value_decimal'), 'unit': value.get('unit'),
                      'currency': value.get('unit') if value.get('unit') in {'USD', 'EUR', 'CNY'} else None,
                      'quote': ' | '.join(c.get('quote', '') for c in fact.get('citations', [])),
                      'citations': fact.get('citations', []), 'record': value})
    cost = evaluation_values.get('cost_audit', {})
    cost_rows = [c for c in cost.get('calls', []) if c.get('call_id') in call_groups and c.get('ledger_state') == 'unknown']
    try:
        usage = summarize_calls(calls)
        held = sum((_reserved_cost(c['reserved_usd']) for c in cost_rows), Decimal('0'))
        known_plus_held = str(Decimal(usage['known_estimated_usd']) + held)
    except DecimalException as error:
        raise ValueError('Invalid saved cost total') from error
    if cost_rows:
        usage.update(unknown_reserved_usd=str(held), known_plus_held_usd=known_plus_held)
        for call in calls:
            matches = [c for c in cost_rows if c['call_id'] == call['call_id']]
            if matches: call['reserved_usd'] = matches[0]['reserved_usd']
    limitations = list(entry.get('limitations', []))
    evaluation = {'schema_version': 'e6-evaluation-view-v1', 'kind': entry['kind'],
                  'summary': f"{entry['title']}：执行 {result['status']}；独立验收 {verdict or '未单独验收 / not individually assessed'}。",
                  'standard': _compact(evaluation_values.get('standard')), 'independent_assessment': _compact(assessment),
                  'program_checks': {'manifest_binding': 'verified', 'recorded_runtime_status': result['status'],
                                     'failures': result.get('failures', []), 'independent_reports': {k: _compact(v) for k, v in evaluation_values.items() if k not in {'standard', 'independent_assessment', 'cost_audit'}}},
                  'model_reviews': reviews, 'costs': {'basis': 'uncached peak list-price estimate; actual bill unverified',
                        'known_estimated_usd': usage['known_estimated_usd'], 'unknown_reserved_usd': str(held), 'unknown_requests': usage['unknown_cost_requests']},
                  'limitations': limitations, 'artifacts': evaluation_refs}
    unknown_bound = usage['unknown_cost_requests'] == len(cost_rows)
    usage['unknown_reserved_usd'] = str(held) if unknown_bound else None
    usage['known_plus_held_usd'] = known_plus_held if unknown_bound else None
    evaluation['costs']['unknown_reserved_usd'] = usage['unknown_reserved_usd']
    public_scope = {'company_ids': scope['company_ids'], 'company_id': scope['company_ids'][0] if len(scope['company_ids']) == 1 else None,
                    'source_snapshot_ids': scope['source_snapshot_ids'], 'snapshot_id': scope['snapshot_id'],
                    'knowledge_cutoff': scope['knowledge_cutoff'], 'periods': sorted({f.get('period_end') for f in facts if f.get('period_end')})}
    revision = _digest(entry)
    view = {'schema_version': 'agent-run-view-v1', 'id': rid, 'root_run_id': rid, 'agent': 'data',
            'title': entry['title'], 'origin': entry['kind'], 'live': False, 'root_terminal': True, 'revision': revision,
            'state': {'execution': 'finished' if passed else 'failed', 'connection': 'historical', 'delivery': result['status'],
                      'quality': verdict or 'not_evaluated', 'adoption': 'unchanged_candidate', 'stop_reason': result['status']},
            'scope': public_scope, 'run_tree': [{'id': rid, 'parent_run_id': None, 'parent_step_id': None, 'kind': entry['kind'], 'role': entry['kind'], 'status': result['status']}],
            'steps': steps, 'calls': sorted(calls, key=lambda c: (c.get('started_at') or '', c['call_id'])),
            'artifacts': refs, 'inputs': [r for r in refs if r['kind'] == 'input'], 'configs': [r for r in refs if r['kind'] == 'config'],
            'usage': {**usage, 'own': deepcopy(usage)}, 'task': result.get('question') or packet.get('question'),
            'result_view': {'kind': 'financial_facts' if facts else 'no_visible_output', 'facts': facts, 'analysis': [],
                            'documents': [{'source_id': d['source_snapshot_id'], 'company_id': d['company_id'],
                                           'source_url': d.get('source_url'), 'block_id': b['block_id'],
                                           'text': b['text'], 'type': b.get('type')}
                                          for d in packet.get('source_documents', []) for b in d.get('blocks', [])],
                            'gaps': result.get('failures', []) or packet.get('program_gaps', []),
                            'artifacts': [r for r in refs if r['kind'] == 'result' and '/model/' not in r['label'] and '/question-model/' not in r['label']],
                            'summary': '已保存的交付事实；失败运行保留候选事实，不表示审核通过。 / Saved delivered facts; failed runs retain candidates without implying acceptance.'},
            'evaluation': evaluation, 'diagnostics': limitations,
            'integrity': {'status': 'verified', 'adapter': ADAPTER, 'registration_sha256': revision}, 'links': []}
    return {'view': _clean(view), 'internal': internal, 'stamps': [(p, h, (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)) for p, h, s in stamps]}


def _loaded(root, identity):
    _identity(identity)
    matches = [e for e in _registry(root) if e['id'] == identity]
    if len(matches) != 1:
        raise ValueError('Select an explicitly registered sealed evaluation')
    entry = matches[0]; key = (str(Path(root).resolve()), identity, _digest(entry))
    with _LOCK:
        cached = _CACHE.get(key)
        if cached:
            for relative, expected, stamp in cached['stamps']:
                p = _path(root, relative); s = p.stat()
                if (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino) != stamp:
                    _CACHE.pop(key, None)
                    return _loaded(root, identity)
            return cached
        built = _build(root, entry); _CACHE[key] = built
        return built


def load_run(root, identity):
    return deepcopy(_loaded(root, identity)['view'])


def load_view(root, identity):
    """Isolate unavailable evidence for display; strict artifact reads stay closed."""
    _identity(identity)
    entries = [entry for entry in _registry(root) if entry['id'] == identity]
    if len(entries) != 1:
        raise ValueError('Select an explicitly registered sealed evaluation')
    entry = entries[0]
    try:
        return load_run(root, identity)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        # A registry identifies a run, but cannot establish its outcome or cost.
        # Do not cache this projection: restored files must be checked next time.
        reason = ('missing_files' if isinstance(error, FileNotFoundError) else
                  'unreadable_files' if isinstance(error, OSError) else 'invalid_evidence')
        message = {
            'missing_files': '本机材料缺失，无法核验此记录。 / Local evidence files are missing; this run cannot be verified.',
            'unreadable_files': '本机材料无法读取，无法核验此记录。 / Local evidence files cannot be read; this run cannot be verified.',
            'invalid_evidence': '材料校验失败，已阻止读取此记录的产物。 / Evidence validation failed; artifact access is blocked.',
        }[reason]
        return _clean({'schema_version': 'agent-run-view-v1', 'id': identity,
            'root_run_id': identity, 'agent': 'data', 'title': entry.get('title') or identity,
            'origin': entry.get('kind'), 'live': False, 'root_terminal': None,
            'revision': _digest({'registration': entry, 'availability': reason}),
            'state': {'execution': 'unknown', 'connection': 'historical', 'delivery': 'unavailable',
                      'quality': 'not_verified', 'adoption': 'unknown', 'stop_reason': None},
            'scope': {}, 'usage': {}, 'run_tree': [], 'steps': [], 'calls': [],
            'artifacts': [], 'inputs': [], 'configs': [], 'links': [], 'task': None,
            'result_view': {'kind': 'unavailable', 'facts': [], 'analysis': [], 'documents': [],
                            'gaps': [], 'artifacts': [], 'summary': message},
            'evaluation': {'schema_version': 'unavailable-evaluation-v1', 'kind': 'unavailable',
                           'summary': message},
            'integrity': {'status': 'unavailable' if isinstance(error, OSError) else 'invalid',
                          'adapter': ADAPTER, 'reason': reason}, 'diagnostics': [message]})


def list_runs(root):
    keys = ('schema_version', 'id', 'root_run_id', 'agent', 'title', 'origin', 'live', 'root_terminal', 'revision', 'state', 'scope', 'usage', 'integrity', 'diagnostics')
    return [{k: v[k] for k in keys} for e in _registry(root) for v in [load_view(root, e['id'])]]


def load_step(root, identity, step_id):
    matches = [s for s in load_run(root, identity)['steps'] if s['id'] == step_id]
    if len(matches) != 1: raise ValueError('Unknown step in selected sealed run')
    return matches[0]


def read_artifact(root, identity, artifact_id, *, cursor=None, browse=None):
    loaded = _loaded(root, identity); item = loaded['internal'].get(artifact_id)
    if item is None: raise ValueError('Unknown artifact in selected sealed run')
    ref = item['ref']; _pinned(root, item['path'], ref['sha256'])
    value = item['value']
    safe = project_artifact(value, ref['kind']) if ref['kind'] in {'config', 'model_call'} else _clean(value)
    return artifact_page(ref, safe, cursor=cursor, browse=browse)


def result_summary(root, identity):
    """Small selection row; full result, trace and assessments are on demand."""
    view = load_view(root, identity)
    keys = ('id', 'root_run_id', 'title', 'agent', 'origin', 'live', 'root_terminal', 'revision', 'state', 'scope', 'usage', 'integrity', 'diagnostics')
    value = {k: deepcopy(view[k]) for k in keys}
    starts = []
    for call in view['calls']:
        try:
            parsed = datetime.fromisoformat(call['started_at'].replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                starts.append(parsed.astimezone(timezone.utc))
        except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
            continue
    value['started_at'] = min(starts).isoformat() if starts else None
    value.update(schema_version='agent-result-view-v1', trace_id=identity, task=view['task'],
                 result_view={k: deepcopy(view['result_view'][k]) for k in ('kind', 'summary')},
                 evaluation={k: deepcopy(view['evaluation'][k]) for k in ('schema_version', 'kind', 'summary')},
                 comparison={'eligible': False, 'key': None, 'reason': 'Historical E6 experiments are not registered as strict model A/B arms.'})
    return value
