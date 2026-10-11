"""One read-only boundary for registered history and host-enabled live runs."""
import base64
import json
from pathlib import Path

from apps.review_workbench.data import agent_runs_history as history
from apps.review_workbench.data import agent_runs_live as live
from apps.review_workbench.data import agent_runs_experiments as experiments
from apps.review_workbench.data import agent_runs_e6 as e6


def _history_ids(root):
    if not (Path(root) / history.REGISTRATION).exists():
        return set()
    return set(history.registered_ids(root))


def _source(root, identity, observation_root):
    live._identity(identity)
    historical = identity in _history_ids(root)
    observed = identity in live.registered_ids(observation_root)
    trial = identity in experiments.registered_ids(root)
    evaluation = identity in e6.registered_ids(root)
    if sum((historical, observed, trial, evaluation)) > 1:
        raise ValueError('Run identity appears in multiple registries')
    if not historical and not observed and not trial and not evaluation:
        raise KeyError('Unknown registered run')
    return 'history' if historical else 'experiment' if trial else 'e6' if evaluation else 'live'


def list_runs(root, *, observation_root=None, output_roots=()):
    historical = history.list_runs(root) if _history_ids(root) else []
    observed = live.list_runs(observation_root, output_roots=output_roots)
    trials = experiments.list_runs(root)
    rows = [*historical, *observed, *trials, *e6.list_runs(root)]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Run identity appears in multiple registries')
    return sorted(rows, key=lambda r: r['id'])


def list_page(root, *, agent='data', cursor=None, limit=50, observation_root=None, output_roots=()):
    if agent not in {'data', 'analysis', 'risk', 'portfolio'}:
        raise ValueError('Unknown Agent selection')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Run list limit must be 1..100')
    after = ''
    if cursor:
        value = live._decode(cursor)
        if set(value) != {'version', 'agent', 'after'} or value['version'] != 'run-list-v1' or value['agent'] != agent:
            raise ValueError('Run list cursor selection mismatch')
        after = live._identity(value['after'])
    rows = [r for r in list_runs(root, observation_root=observation_root, output_roots=output_roots)
            if r.get('agent') == agent]
    pending = [r for r in rows if r['id'] > after]
    selected = pending[:limit]
    next_cursor = live._encode({'version': 'run-list-v1', 'agent': agent, 'after': selected[-1]['id']}) if len(pending) > limit else None
    return {'runs': selected, 'next_cursor': next_cursor, 'has_more': next_cursor is not None, 'total': len(rows)}


def load_run(root, identity, *, observation_root=None, output_roots=(), revision=None):
    source = _source(root, identity, observation_root)
    if source in {'history', 'experiment', 'e6'}:
        result = (history if source == 'history' else e6 if source == 'e6' else experiments).load_run(root, identity)
        if revision is not None and str(revision) != str(result['revision']):
            raise ValueError('Historical run revision does not match')
        return result
    return live.load_run(observation_root, identity, output_roots=output_roots, revision=revision)


def load_step(root, identity, step_id, *, observation_root=None, output_roots=(), revision=None):
    source = _source(root, identity, observation_root)
    if source in {'history', 'experiment', 'e6'}:
        if revision is not None:
            load_run(root, identity, revision=revision)
        return (history if source == 'history' else e6 if source == 'e6' else experiments).load_step(root, identity, step_id)
    return live.load_step(observation_root, identity, step_id, output_roots=output_roots, revision=revision)


def read_artifact(root, identity, artifact_id, *, cursor=None, browse=None, observation_root=None, output_roots=(), revision=None):
    source = _source(root, identity, observation_root)
    if source in {'history', 'experiment', 'e6'}:
        if revision is not None:
            load_run(root, identity, revision=revision)
        return (history if source == 'history' else e6 if source == 'e6' else experiments).read_artifact(root, identity, artifact_id, cursor=cursor, browse=browse)
    return live.read_artifact(observation_root, identity, artifact_id, output_roots=output_roots,
                              revision=revision, cursor=cursor, browse=browse)


def read_events(root, identity, *, after='0', limit=100, observation_root=None, output_roots=()):
    if _source(root, identity, observation_root) != 'live':
        raise ValueError('Historical runs do not have a live event stream')
    return live.read_events(observation_root, identity, after=after, limit=limit, output_roots=output_roots)


def parent_for_extraction(root, extraction):
    """Show a parent link only after the registered child identity is verified."""
    if not _history_ids(root) or not extraction.get('manifest_sha256'):
        return None
    config = json.loads((Path(root) / history.REGISTRATION).read_text())
    candidates = []
    for entry in config['runs']:
        for child in entry.get('children', []):
            if (child.get('extraction_view_id') == extraction.get('id')
                    and child.get('direct', {}).get('manifest_sha256') == extraction['manifest_sha256']):
                view = history.load_run(root, entry['id'])
                if any(r['id'] == child['id'] for r in view['run_tree']):
                    candidates.append(entry['id'])
    if len(set(candidates)) > 1:
        raise ValueError('Extraction has ambiguous parent registrations')
    return candidates[0] if candidates else None
