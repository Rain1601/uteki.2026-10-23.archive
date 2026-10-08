"""Read-only comparison of completed runs; gold stays outside the runtime."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from summarize_runs import summarize

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(root, expected=None, required=()):
    """Verify recorded artifacts without importing or executing application runtime."""
    root = root.resolve()
    path = root / 'manifest.json'
    if expected is not None and sha(path) != expected:
        raise ValueError('Manifest identity differs: ' + str(root))
    files = read(path)['files']
    actual = {str(p.relative_to(root)) for p in root.rglob('*')
              if p.is_file() and p != path}
    if actual != set(files):
        raise ValueError('Manifest file inventory differs: ' + str(root))
    if not set(required) <= set(files):
        raise ValueError('Required comparison files not frozen: ' + str(root))
    for relative, digest in files.items():
        item = (root / relative).resolve()
        if not item.is_relative_to(root) or not item.is_file() or sha(item) != digest:
            raise ValueError('Frozen artifact differs: ' + str(item))
    return sha(path)


def compare(names):
    if len(names) < 2 or len(set(names)) != len(names):
        raise ValueError('At least two distinct runs are required')
    if any(Path(name).name != name or name in ('.', '..') for name in names):
        raise ValueError('Run names must be direct children of runs/')
    receipts = {r['run']: r for r in summarize(ROOT / 'runs')['runs']}
    frozen_path = ROOT / 'evaluation-only/frozen/E1-04-v1.json'
    frozen = read(frozen_path)
    baseline = None
    rows = []
    for name in names:
        run = ROOT / 'runs' / name
        run_hash = verify_manifest(run, required=('config.json', 'original-request.json',
            'implementation.json', 'dependencies.json', 'result.json'))
        config = read(run / 'config.json')
        result = read(run / 'result.json')
        request = read(run / 'original-request.json')
        if request['question'] != frozen['case']['query_zh']:
            raise ValueError('Question differs from frozen case: ' + name)
        attempts = result.get('attempts', [])
        if not attempts or any(a.get('execution') != 'new' for a in attempts):
            raise ValueError('Reused retrieval is not a full configuration-cost comparison: ' + name)
        if config.get('initial_query_ref') or request.get('initial_query_ref'):
            raise ValueError('Initial query reuse is not a fresh comparison: ' + name)
        if receipts[name]['unmatched_started_calls']:
            raise ValueError('Run has unmatched started calls: ' + name)
        dataset_hash = verify_manifest(Path(config['request']['dataset']), frozen['dataset_manifest_sha256'])
        protocols, skills = [], []
        for attempt in attempts:
            query_ref = attempt.get('query_ref')
            if query_ref:
                query = Path(query_ref['path'])
                if not query.resolve().is_relative_to(run.resolve()):
                    raise ValueError('Query points outside fresh run: ' + name)
                verify_manifest(query, query_ref['manifest_sha256'])
                protocols.append(read(query / 'config.json'))
                for plan in read(query / 'result.json').get('plans', []):
                    if plan.get('skill_hashes'):
                        skills.append(plan['skill_hashes'])
        # Compare available protocol and Skill snapshots; choices of actions may differ.
        unique = lambda items: sorted({json.dumps(x, sort_keys=True) for x in items})
        invariant = deepcopy(config)
        settings = {}
        for role in ('planner', 'worker'):
            settings[role] = {k: invariant[role].pop(k)
                              for k in ('provider', 'model', 'reasoning_effort')}
        # All other settings, including review model, budget and limits, must match.
        signature = {'config': invariant,
                     'request': request,
                     'implementation': read(run / 'implementation.json'),
                     'dependencies': read(run / 'dependencies.json'),
                     'dataset_manifest_sha256': dataset_hash,
                     'query_protocol_snapshots': unique(protocols),
                     'skill_hash_snapshots': unique(skills)}
        if baseline is None:
            baseline = signature
        elif signature != baseline:
            raise ValueError('Comparison inputs, implementation or non-model settings differ: ' + name)
        review = ROOT / 'evaluation-only/reviews' / name
        score = read(review / 'score.json')
        independent = read(review / 'review.json')
        audit = read(review / 'original-check.json')
        if score['case_id'] != 'E1-04' or independent['case_id'] != 'E1-04':
            raise ValueError('This explicit experiment compares E1-04 only')
        if (independent['question'] != request['question'] or
                audit['gold_freeze_sha256'] != sha(frozen_path) or
                audit['run_manifest_sha256'] != run_hash):
            raise ValueError('Independent review is not bound to this frozen run/case: ' + name)
        if score.get('workflow_status', result['status']) != result['status']:
            raise ValueError('Independent review workflow binding differs: ' + name)
        rows.append({'run': name, 'settings': settings, 'workflow_status': result['status'],
                     'independent_status': score['status'],
                     'coverage': score['required_coverage'],
                     'characters': score['characters'],
                     'costs': receipts[name],
                     'manifest_sha256': run_hash,
                     'original_check_sha256': sha(review / 'original-check.json'),
                     'review_sha256': sha(review / 'review.json')})
    return {'schema_version': 'e1-config-comparison-v1',
            'case_id': 'E1-04',
            'gold_sha256': sha(frozen_path),
            'controlled_fields_equal': True,
            'verification': {'run_and_dataset_manifests': True, 'fresh_retrieval_only': True,
                'independent_review_run_and_gold_binding': True,
                'query_protocol_snapshots_present': bool(baseline['query_protocol_snapshots']),
                'skill_hash_snapshots_present': bool(baseline['skill_hash_snapshots'])},
            'invariants': baseline,
            'limits': ['One run per configuration; no stability estimate.',
                       'Planner/worker effort differs across providers; this is a system configuration comparison.',
                       'Reviewer configuration is fixed; its cost is included, not attributed to the worker model.',
                       'Recorded settings equality does not prove identical provider sampling, upstream model revisions, effective reasoning or cache behavior.',
                       'All failed calls in each run are included; historical development runs remain in the total ledger.'],
            'runs': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.runs)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
