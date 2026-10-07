"""Read-only adapter for explicitly pinned, single-call model experiments.

These traces do not claim to be complete Data Agent executions. Registration is
local configuration; neither IDs nor URLs can select an arbitrary file.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from .evaluation_artifacts import _path, _hash
from .agent_runs_history import _identity
from .agent_runs_shared import (_clean, artifact_page, summarize_calls, call_configuration_snapshot,
                              configured_value, configured_thinking)

REGISTRATION = 'data/evaluation_views/model-trials-v1.json'
ADAPTER = 'bounded-model-comparison-v1'
_SHA = re.compile(r'^[a-f0-9]{64}$')
_REQUIRED = {'packet', 'prepared_manifest', 'request', 'experiment_start', 'start',
             'response', 'validation', 'visible_output', 'source_catalog', 'source_bytes'}
_ALLOWED = _REQUIRED | {'parsed'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _registry(root):
    path = _path(root, REGISTRATION)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if data.get('schema_version') != 'model-trials-registration-v1' or not isinstance(data.get('runs'), list):
        raise ValueError('Unsupported model experiment registration')
    ids = [_identity(row['id']) for row in data['runs']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate experiment trace identity')
    return data['runs']


def registered_ids(root):
    return [row['id'] for row in _registry(root)]


def _scope(scope):
    if not isinstance(scope, dict) or not isinstance(scope.get('company_id'), str) or not scope['company_id'].strip():
        raise ValueError('Explicit company scope is required')
    sources, years, periods = (scope.get(k) for k in ('source_snapshot_ids', 'comparison_years', 'comparison_periods'))
    if not isinstance(sources, list) or not sources or len(set(sources)) != len(sources) or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError('Explicit source scope is required')
    if not isinstance(years, list) or not years or any(type(y) is not int or not 1900 <= y <= 2200 for y in years) or len(set(years)) != len(years):
        raise ValueError('Explicit comparison years are required')
    if (not isinstance(periods, list) or len(periods) != len(years)
            or any(not isinstance(p, dict) or type(p.get('fiscal_year')) is not int
                   or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(p.get('period_end', ''))) for p in periods)
            or {p['fiscal_year'] for p in periods} != set(years)):
        raise ValueError('Explicit fiscal period endings are required')
    if not isinstance(scope.get('currency'), str) or not scope['currency'].strip() or not scope.get('report_period_end'):
        raise ValueError('Explicit currency and report period are required')
    return scope


def _read_files(root, entry):
    files = entry.get('files')
    if not isinstance(files, dict) or not _REQUIRED <= set(files) or not set(files) <= _ALLOWED:
        raise ValueError('Explicit experiment evidence files are required')
    data, refs = {}, {}
    for key, pin in files.items():
        relative, sha = pin.get('path'), pin.get('sha256')
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError('Explicit evidence hash is required')
        path = _path(root, relative)
        if PurePosixPath(relative).parts[0] not in {'experiments', 'data'}:
            raise ValueError('Experiment evidence must be registered under experiments or data')
        size = path.stat().st_size
        if size > (128 * 1024 * 1024 if key == 'source_bytes' else 2 * 1024 * 1024):
            raise ValueError('Experiment evidence exceeds inspection limit')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('Experiment evidence integrity mismatch')
        data[key] = raw if key in {'visible_output', 'source_bytes'} else json.loads(raw)
        kind = ('restricted' if key in {'source_bytes', 'source_catalog', 'prepared_manifest'} else
                'input' if key in {'packet', 'request'} else
                'config' if key in {'experiment_start', 'start'} else
                'model_call' if key == 'response' else 'result')
        refs[key] = {'id': 'trial-' + hashlib.sha256((entry['id'] + ':' + key).encode()).hexdigest()[:24],
                     'run_id': entry['id'], 'step_id': entry['id'] + '--step-001', 'label': PurePosixPath(relative).name,
                     'kind': kind, 'sha256': sha, 'size_bytes': size,
                     'availability': 'restricted' if kind == 'restricted' else 'available'}
    return data, refs


def _validate_output(parsed, visible, packet):
    if not isinstance(parsed, dict) or set(parsed) != {'facts', 'analysis', 'gaps'} or any(not isinstance(parsed[k], list) for k in parsed):
        raise ValueError('Unsupported bounded output contract')
    if json.loads(visible) != parsed:
        raise ValueError('Parsed output differs from the visible response')
    blocks = {b['block_id']: b['text'] for b in packet['blocks']}
    periods = {str(p['fiscal_year']): p['period_end'] for p in packet['scope']['comparison_periods']}
    required = {'metric', 'period', 'period_end', 'value', 'unit', 'currency', 'block_id', 'row', 'column', 'quote'}
    for fact in parsed['facts']:
        if not isinstance(fact, dict) or set(fact) != required:
            raise ValueError('Unsupported fact contract')
        if (fact.get('block_id') not in blocks or not isinstance(fact.get('quote'), str) or not fact['quote']
                or fact['quote'] not in blocks[fact['block_id']] or fact.get('period') not in periods
                or fact.get('period_end') != periods[fact['period']] or fact.get('currency') != packet['scope']['currency']):
            raise ValueError('Fact evidence or period is outside the selected input')
        if any(not isinstance(fact[k], str) or not fact[k].strip() for k in required - {'row', 'value'}):
            raise ValueError('Fact fields must be nonempty')
        if type(fact['row']) is not int or fact['row'] < 0 or isinstance(fact['value'], bool):
            raise ValueError('Invalid fact number or row')
        try:
            if not math.isfinite(float(fact['value'])):
                raise ValueError('Non-finite fact value')
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid fact value') from error
    for claim in parsed['analysis']:
        if (not isinstance(claim, dict) or set(claim) != {'claim', 'block_ids'}
                or not isinstance(claim['claim'], str) or not claim['claim'].strip()
                or not isinstance(claim['block_ids'], list) or not claim['block_ids']
                or any(b not in blocks for b in claim['block_ids'])):
            raise ValueError('Analysis citation is outside the selected input')
    if any(not isinstance(g, str) for g in parsed['gaps']):
        raise ValueError('Invalid output gap')


def _loaded(root, identity, *, entry=None):
    _identity(identity)
    matches = [r for r in _registry(root) if r['id'] == identity] if entry is None else [entry] if entry.get('id') == identity else []
    if len(matches) != 1:
        raise ValueError('Select an explicitly registered model experiment')
    entry = matches[0]
    if entry.get('adapter') != ADAPTER or entry.get('agent') != 'data' or entry.get('role') != 'bounded_extraction_analysis':
        raise ValueError('Unsupported experiment adapter or role')
    data, refs = _read_files(root, entry)
    packet, response, start = data['packet'], data['response'], data['start']
    scope = _scope(entry.get('scope'))
    if packet.get('schema_version') not in {'bounded-model-comparison-packet-v1', 'reproducibility-pilot-packet-v1'} or _scope(packet.get('scope')) != scope:
        raise ValueError('Registered scope differs from experiment input')
    manifest, experiment = data['prepared_manifest'], data['experiment_start']
    if manifest.get('schema_version') != 'bounded-model-comparison-prepared-manifest-v1' or experiment.get('schema_version') != 'small-model-comparison-v1':
        raise ValueError('Unsupported experiment input schema')
    if not packet.get('task') or not isinstance(packet['task'], (str, dict)):
        raise ValueError('Explicit experiment task is required')
    source = packet.get('source', {})
    if scope['source_snapshot_ids'] != [source.get('source_snapshot_id')]:
        raise ValueError('This adapter requires the explicitly selected single source')
    matches = [s for s in data['source_catalog'] if s.get('source_snapshot_id') == source['source_snapshot_id']]
    if (len(matches) != 1 or matches[0].get('company_id') != scope['company_id']
            or matches[0].get('source_sha256') != source.get('source_sha256')
            or matches[0].get('period_end') != scope['report_period_end']
            or entry['files']['source_bytes']['sha256'] != source.get('source_sha256')):
        raise ValueError('Source identity, company, report period or bytes mismatch')
    if (manifest.get('packet_sha256') != refs['packet']['sha256'] or manifest.get('source_sha256') != source['source_sha256']
            or manifest.get('input_block_ids') != [b['block_id'] for b in packet['blocks']]):
        raise ValueError('Prepared manifest does not bind the selected packet')
    ids = set()
    for block in packet['blocks']:
        bid = block.get('block_id')
        if (not isinstance(bid, str) or not bid or bid in ids or not isinstance(block.get('text'), str)
                or block.get('text_hash') != hashlib.sha256(block['text'].encode()).hexdigest()
                or block.get('company_id', scope['company_id']) != scope['company_id']
                or block.get('source_snapshot_id', source['source_snapshot_id']) != source['source_snapshot_id']):
            raise ValueError('Invalid scoped source block')
        ids.add(bid)
    messages = data['request'].get('messages')
    if (not isinstance(messages, list) or len(messages) != 2
            or messages[0].get('role') != 'system' or not isinstance(messages[0].get('content'), str)
            or messages[1].get('role') != 'user' or json.loads(messages[1].get('content', '')) != packet
            or hashlib.sha256(messages[1]['content'].encode()).hexdigest() != refs['packet']['sha256']):
        raise ValueError('Request does not contain the exact pinned packet')
    expected = {'packet_sha256': refs['packet']['sha256'], 'manifest_sha256': refs['prepared_manifest']['sha256'],
                'system_sha256': hashlib.sha256(messages[0]['content'].encode()).hexdigest(),
                'messages_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False, indent=2, allow_nan=False).encode()).hexdigest()}
    for obj in (start, response, experiment):
        inp = obj.get('input', {})
        if (any(inp.get(k) != v for k, v in expected.items()) or inp.get('scope') != scope
                or inp.get('source', {}).get('source_sha256') != source['source_sha256']
                or inp.get('source', {}).get('source_snapshot_id') != source['source_snapshot_id']):
            raise ValueError('Call input hashes or source scope mismatch')
    for key in ('provider', 'requested_model', 'reasoning_configuration', 'started_at'):
        if not start.get(key) or start[key] != response.get(key):
            raise ValueError('Call configuration or identity mismatch')
    if entry.get('provider') != response['provider'] or entry.get('model') != response['requested_model']:
        raise ValueError('Registered model differs from the recorded call')
    visible = data['visible_output'].decode('utf-8')
    if 'parsed' in data:
        _validate_output(data['parsed'], visible, packet)
    elif visible.strip() and response.get('finish_reason') == 'stop' and data['validation'].get('status') == 'structure_and_citations_valid':
        raise ValueError('Valid output has no pinned parsed artifact')
    failed = response.get('status') == 'failed'
    valid = not failed and 'parsed' in data and response.get('finish_reason') == 'stop' and data['validation'].get('status') == 'structure_and_citations_valid'
    limited = response.get('finish_reason') == 'length'
    rid, sid = identity, identity + '--step-001'
    reasoning = response['reasoning_configuration']
    configuration = call_configuration_snapshot(response, start=start, limits=experiment.get('limits'),
        reasoning_configuration=reasoning,
        fingerprints={'system_sha256': expected['system_sha256'], 'input_sha256': expected['packet_sha256']})
    effort = configured_value(configuration, 'reasoning_effort')
    thinking = configured_thinking(configuration)
    raw = response.get('raw_usage') or {}
    call = {'call_id': rid + '--call-001', 'run_id': rid, 'step_id': sid, 'role': entry['role'],
            'provider': response['provider'], 'requested_model': response['requested_model'],
            'actual_upstream_model': response.get('returned_model'), 'reasoning_effort': effort, 'thinking_mode': thinking,
            'reasoning_configuration': reasoning, 'stage': 'end', 'status': response.get('status'),
            'started_at': response.get('started_at'), 'ended_at': response.get('ended_at'),
            'elapsed_seconds': response.get('elapsed_seconds'), 'estimated_usd': response.get('estimated_usd'),
            'actual_billed_usd': response.get('actual_billed_usd'), 'request_id': response.get('request_id'),
            'response_id': response.get('response_id'),
            'http_status': response.get('http_status'), 'provider_finish_reason': response.get('provider_finish_reason'),
            'configuration_snapshot': configuration,
            'finish_reason': response.get('finish_reason'), 'usage_presence': response.get('usage_presence', 'unknown'),
            'input_tokens': raw.get('prompt_tokens'), 'output_tokens': raw.get('completion_tokens'),
            'cached_tokens': (raw.get('prompt_tokens_details') or {}).get('cached_tokens', raw.get('prompt_cache_hit_tokens')),
            'reasoning_tokens': (raw.get('completion_tokens_details') or {}).get('reasoning_tokens'), 'files': [refs['response']]}
    usage = summarize_calls([call])
    public_scope = {**{k: scope[k] for k in ('company_id', 'source_snapshot_ids')},
                    'periods': [p['period_end'] for p in scope['comparison_periods']], 'report_period_end': scope['report_period_end']}
    result = {'kind': 'bounded_facts_analysis' if valid else 'no_visible_output' if not visible.strip() else 'invalid_output',
              'facts': data['parsed']['facts'] if valid else [], 'analysis': data['parsed']['analysis'] if valid else [],
              'gaps': data['parsed']['gaps'] if valid else ['Model request failed; no successful response or accepted output.' if failed else 'Output token limit reached; no evaluable visible answer.' if limited else 'No validated visible answer.'],
              'artifacts': [refs[k] for k in ('parsed', 'visible_output', 'validation') if k in refs],
              'validation': {k: data['validation'].get(k) for k in ('status', 'errors', 'gold_scoring', 'semantic_correctness')}}
    comparison = {**expected, 'task_sha256': _digest(packet['task']), 'contract_sha256': expected['system_sha256'],
                  'input_sha256': expected['packet_sha256'], 'scope_sha256': _digest(scope), 'eligible': True,
                  'reason': 'Same pinned task and input can compare configurations; inference compute is not equal.'}
    comparison['key'] = _digest({k: comparison[k] for k in ('input_sha256', 'task_sha256', 'contract_sha256', 'scope_sha256')})
    revision = _digest(entry)
    view = {'schema_version': 'agent-run-view-v1', 'id': rid, 'root_run_id': rid, 'agent': 'data', 'title': entry['title'],
            'origin': 'independent_bounded_model_experiment', 'live': False, 'root_terminal': True, 'revision': revision,
            'state': {'execution': 'failed' if failed else 'finished', 'connection': 'historical', 'delivery': 'failed' if failed else 'candidate_ready' if valid else 'output_limited' if limited else 'invalid_output',
                      'quality': 'not_evaluated', 'adoption': 'unchanged_candidate', 'stop_reason': response.get('finish_reason')},
            'scope': public_scope, 'run_tree': [{'id': rid, 'parent_run_id': None, 'parent_step_id': None,
                    'kind': 'bounded_model_experiment', 'role': entry['role'], 'status': 'failed' if failed else 'finished'}],
            'steps': [{'id': sid, 'run_id': rid, 'ordinal': 1, 'action': 'bounded_extraction_analysis', 'phase': 'model',
                       'status': 'failed' if failed else 'completed' if valid else 'output_limited' if limited else 'invalid_output', 'error_code': response.get('error_type') if failed else None,
                       'elapsed_seconds': call['elapsed_seconds'], 'started_at': call['started_at'], 'ended_at': call['ended_at'],
                       'files': [r for r in refs.values() if r['availability'] == 'available'], 'call_ids': [call['call_id']], 'child_run_ids': []}],
            'artifacts': list(refs.values()), 'calls': [call], 'usage': {**usage, 'own': deepcopy(usage)},
            'inputs': [refs['packet'], refs['request']], 'configs': [refs['start'], refs['experiment_start']],
            'diagnostics': ['Independent bounded model experiment: one model request; not a complete Data Agent run.',
                            'Structural and citation checks do not establish semantic correctness or human scoring.'],
            'integrity': {'status': 'verified', 'adapter': ADAPTER, 'registration_sha256': revision}, 'links': [],
            'task': packet['task'], 'result_view': result, 'comparison': comparison}
    return {'view': _clean(view), 'data': data, 'refs': refs}


def validate_registration(root, entry):
    """Fully verify a new explicit registration before appending it to the index."""
    return deepcopy(_loaded(root, _identity(entry['id']), entry=entry)['view'])


def load_run(root, identity):
    return deepcopy(_loaded(root, identity)['view'])


def list_runs(root):
    keys = ('schema_version', 'id', 'root_run_id', 'agent', 'title', 'origin', 'live', 'root_terminal', 'revision', 'state', 'scope', 'usage', 'integrity', 'diagnostics')
    return [{k: view[k] for k in keys} for entry in _registry(root) for view in [load_run(root, entry['id'])]]


def load_step(root, identity, step_id):
    view = load_run(root, identity)
    if step_id != view['steps'][0]['id']:
        raise ValueError('Unknown step in selected experiment')
    return view['steps'][0]


def read_artifact(root, identity, artifact_id, *, cursor=None, browse=None):
    loaded = _loaded(root, identity)
    keys = [k for k, ref in loaded['refs'].items() if ref['id'] == artifact_id]
    if len(keys) != 1:
        raise ValueError('Unknown artifact in selected experiment')
    key = keys[0]
    value, ref = loaded['data'][key], loaded['refs'][key]
    if ref['availability'] == 'restricted':
        safe = {'notice': 'Source metadata is restricted; inspect the pinned input packet.'}
    elif key == 'response':
        safe = loaded['view']['calls'][0]
    elif key == 'visible_output':
        safe = value.decode('utf-8')
    elif key == 'parsed':
        safe = {k: value[k] for k in ('facts', 'analysis', 'gaps')}
    elif key == 'packet':
        safe = {k: value[k] for k in ('schema_version', 'scope', 'task', 'source', 'blocks')}
    elif key == 'request':
        safe = {'system_prompt': value['messages'][0]['content'],
                'input_packet': json.loads(value['messages'][1]['content'])}
    elif key == 'validation':
        safe = {k: value.get(k) for k in ('status', 'errors', 'gold_scoring', 'semantic_correctness')}
    elif key == 'start':
        safe = {k: value.get(k) for k in ('provider', 'requested_model', 'reasoning_configuration', 'pricing_snapshot', 'started_at')}
        if value.get('configuration_snapshot') is not None:
            safe['configuration_snapshot'] = loaded['view']['calls'][0]['configuration_snapshot']
    else:
        limits = value.get('limits', {})
        safe = {'origin': value.get('origin'), 'started_at': value.get('started_at'), 'limits': {
            k: limits.get(k) for k in ('max_output_tokens_per_arm', 'timeout_seconds', 'requests_per_arm', 'automatic_retries', 'comparison_limit', 'cost_note')}}
    return artifact_page(ref, _clean(safe), cursor=cursor, browse=browse)
