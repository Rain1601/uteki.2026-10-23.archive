"""Result-first projection of the same trace registry used by /agent-runs.

No extraction, scoring, adoption or model calls occur at this boundary. A result
identity is its root Trace ID; provider request IDs remain call-level metadata.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import urlencode

from . import agent_runs
from .agent_runs_shared import _clean, summarize_calls


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _run_start(row):
    def stamp(value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None
    explicit = stamp(row.get('started_at'))
    if explicit is not None:
        return explicit
    calls = [value for call in row.get('calls') or [] if (value := stamp(call.get('started_at'))) is not None]
    return min(calls) if calls else float('-inf')


def _models(calls, *, include_configuration=True):
    groups = {}
    for call in calls:
        key = (*tuple(call.get(k) for k in ('role', 'provider', 'requested_model', 'reasoning_effort', 'thinking_mode')),
               (call.get('configuration_snapshot') or {}).get('sha256') if include_configuration else None)
        groups.setdefault(key, []).append(call)
    return [{'role': key[0], 'provider': key[1], 'model': key[2], 'reasoning_effort': key[3], 'thinking_mode': key[4],
             **({'configuration_snapshot': deepcopy(rows[0].get('configuration_snapshot'))} if include_configuration else {}),
             'call_count': len(rows), 'call_ids': [c['call_id'] for c in rows], 'step_ids': sorted({c['step_id'] for c in rows if c.get('step_id')}),
             'usage': summarize_calls(rows)} for key, rows in groups.items()]


def load_result(root, identity, *, observation_root=None, output_roots=(), revision=None):
    options = {'observation_root': observation_root, 'output_roots': output_roots, 'revision': revision}
    run = agent_runs.load_run(root, identity, **options)
    # Freeze artifact reads at the exact run revision captured above.
    options['revision'] = run['revision']
    task = run.get('task')
    if task is None:
        candidates = [ref for ref in run.get('inputs', []) if PurePosixPath(ref.get('label', '')).name == 'request.json'
                      and ref.get('run_id') == identity and ref.get('availability') == 'available']
        for ref in sorted(candidates, key=lambda ref: (len(ref['label']), ref['label'])):
            page = agent_runs.read_artifact(root, identity, ref['id'], **options)
            value = page.get('content')
            if isinstance(value, dict):
                task = value.get('question') or value.get('task')
                if task is None and isinstance(value.get('request'), dict):
                    task = value['request'].get('question')
                if task:
                    break
    task = _clean(task) if task is not None else None
    output = deepcopy(run.get('result_view'))
    if output is None:
        final_refs = [ref for ref in run.get('artifacts', []) if ref.get('availability') == 'available' and (
            ref.get('kind') == 'result' or PurePosixPath(ref.get('label', '')).name in {
                'result.json', 'records.json', 'normalized-records.json', 'evidence.json', 'evidence-bundle.json', 'gaps.json',
                'business_map.json', 'revenue.json'})]
        output = {'kind': 'data_artifacts', 'facts': [], 'analysis': [], 'gaps': [], 'artifacts': final_refs,
                  'summary': '已保存的候选与证据文件；内容核验与采纳状态以执行记录为准。 / Saved candidate and evidence artifacts; review and adoption follow the recorded state.'}
    output.setdefault('summary', '限定材料的事实与短分析，非完整研究报告。 / Bounded facts and short analysis; not a full research report.' if output['kind'] == 'bounded_facts_analysis' else
                      '未产生可评价的可见结果。 / No evaluable visible result.' if output['kind'] == 'no_visible_output' else '输出未通过契约检查。 / Output did not pass the recorded contract checks.')
    comparison = deepcopy(run.get('comparison')) or {'eligible': False, 'key': None,
        'reason': 'No explicit shared input, task and output contract registration; this run is not a controlled A/B arm.',
        'input_sha256': None, 'task_sha256': None, 'contract_sha256': None, 'scope_sha256': None}
    result = {k: deepcopy(run.get(k)) for k in ('title', 'agent', 'origin', 'live', 'root_terminal', 'revision', 'state',
                'scope', 'usage', 'artifacts', 'configs', 'calls', 'integrity', 'diagnostics', 'links', 'steps', 'inputs', 'evaluation', 'started_at')}
    result.update(schema_version='agent-result-view-v1', id=identity, trace_id=run['root_run_id'], task=task,
                  models=_models(run.get('calls', [])), result_view=output, comparison=comparison,
                  process_url='/agent-runs?' + urlencode({'agent': run['agent'], 'run': run['root_run_id']}))
    # Read and verify final artifact bytes through the same scoped reader. The
    # result body remains typed only for known adapters; arbitrary JSON stays an
    # artifact. Live checks are pinned to the captured high-watermark revision.
    inspection_refs = {ref['id']: ref for ref in [*output['artifacts'], *run.get('configs', []),
                      *(ref for call in run.get('calls', []) for ref in call.get('files', []))]
                      if ref.get('availability') == 'available'}
    # Sealed evaluation import already verifies every listed byte and caches
    # a file identity stamp. Re-reading all refs would repeat the complete
    # immutable-tree check once per call; scoped artifact requests still hash
    # their individual bytes before displaying them.
    if run.get('integrity', {}).get('adapter') != 'sealed-data-evaluation-v1':
        for ref in inspection_refs.values():
            agent_runs.read_artifact(root, identity, ref['id'], **options)
    stable = {k: result[k] for k in ('trace_id', 'revision', 'task', 'scope', 'models', 'configs', 'result_view')}
    stable['state'] = {k: run.get('state', {}).get(k) for k in ('execution', 'delivery', 'quality', 'adoption', 'stop_reason')}
    # Preserve scores on unchanged historical evidence. A reconstructed snapshot
    # is a new presentation of already-bound bytes, not a new model request.
    binding_calls = deepcopy(run.get('calls', []))
    for call in binding_calls:
        if (call.get('configuration_snapshot') or {}).get('capture_kind') == 'historical_partial':
            call['thinking_mode'] = ('enabled' if call.get('reasoning_configuration') == 'thinking_enabled_high' else
                                    'provider_default_unspecified' if call.get('reasoning_configuration') == 'provider_default_unspecified' else None)
    stable['models'] = _models(binding_calls, include_configuration=False)
    captured = [{'call_id': call['call_id'], 'sha256': call['configuration_snapshot']['sha256']}
                for call in run.get('calls', []) if (call.get('configuration_snapshot') or {}).get('capture_kind') == 'before_dispatch']
    if captured:
        stable['call_configurations'] = captured
    result['binding'] = {'trace_id': result['trace_id'], 'revision': result['revision'], 'result_sha256': _digest(stable)}
    return _clean(result)


def list_results(root, *, observation_root=None, output_roots=(), agent='data'):
    if agent not in {'data', 'analysis', 'risk', 'portfolio'}:
        raise ValueError('Unknown Agent selection')
    options = {'observation_root': observation_root, 'output_roots': output_roots}
    from . import agent_runs_e6
    rows = [(agent_runs_e6.result_summary(root, row['id']) if row.get('integrity', {}).get('adapter') == agent_runs_e6.ADAPTER
             else load_result(root, row['id'], **options))
            for row in agent_runs.list_runs(root, **options) if row.get('agent') == agent]
    return {'results': sorted(rows, key=lambda row: (_run_start(row), row['id']), reverse=True), 'total': len(rows)}


def compare_results(root, left, right, *, observation_root=None, output_roots=()):
    options = {'observation_root': observation_root, 'output_roots': output_roots}
    a, b = load_result(root, left, **options), load_result(root, right, **options)
    reasons = []
    if left == right:
        reasons.append('Select two distinct root traces.')
    if not a['comparison']['eligible'] or not b['comparison']['eligible']:
        reasons.append('Both traces require an explicit frozen comparison input and task contract.')
    elif a['comparison']['key'] != b['comparison']['key']:
        reasons.append('The source input, task, scope or output contract differs.')
    if a['agent'] != b['agent']:
        reasons.append('The Agent families differ.')
    return {'comparable': not reasons, 'reasons': reasons, 'left': a, 'right': b,
            'comparison_key': a['comparison']['key'] if not reasons else None,
            'limitations': ['One sample per configuration is not a model capability ranking.',
                           'Reasoning settings and inference compute may differ; compare the recorded configurations.']}
