"""Validate and register one explicitly selected, completed model-trial attempt.

This command performs no model calls and never changes experiment evidence. It
accepts registered-root paths only; every input and output is hash pinned before
an atomic append. An invalid visible output remains inspectable, without being
promoted to typed facts. Failed attempts use the same receipt contract.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from apps.review_workbench.data import agent_runs_experiments as experiments
from apps.review_workbench.data import agent_runs_history as history
from apps.review_workbench.data.evaluation_artifacts import _path


def relative(root, path):
    root, path = Path(root).resolve(), Path(path)
    name = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
    return _path(root, name).relative_to(root).as_posix()


def build_registration(root, *, identity, title, provider, model, prepared, output,
                       arm, source_catalog, source_bytes):
    root = Path(root).resolve()
    if any(not isinstance(v, str) or not v.strip() for v in (identity, title, provider, model, arm)):
        raise ValueError('Explicit trace identity, title, provider, model and arm are required')
    history._identity(identity)
    # The arm is a caller-selected child folder, not an arbitrary path.
    history._identity(arm)
    prepared, output = relative(root, prepared), relative(root, output)
    paths = {'packet': f'{prepared}/packet.json', 'prepared_manifest': f'{prepared}/manifest.json',
             'request': f'{output}/request.json', 'experiment_start': f'{output}/experiment-start.json',
             'start': f'{output}/{arm}/start.json', 'response': f'{output}/{arm}/response-metadata.json',
             'validation': f'{output}/{arm}/validation.json', 'visible_output': f'{output}/{arm}/visible-output.txt',
             'source_catalog': relative(root, source_catalog), 'source_bytes': relative(root, source_bytes)}
    packet = json.loads(_path(root, paths['packet']).read_text())
    validation = json.loads(_path(root, paths['validation']).read_text())
    if validation.get('status') == 'structure_and_citations_valid':
        paths['parsed'] = f'{output}/{arm}/parsed.json'
    files = {}
    for key, name in paths.items():
        path = _path(root, name)
        if not path.is_file():
            raise ValueError('Required trial evidence is missing')
        files[key] = {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    entry = {'id': identity, 'adapter': experiments.ADAPTER, 'agent': 'data',
             'role': 'bounded_extraction_analysis', 'title': title, 'provider': provider,
             'model': model, 'scope': packet.get('scope'), 'files': files}
    experiments.validate_registration(root, entry)
    return entry


def register_trial(root, *, dry_run=False, **selection):
    root = Path(root).resolve()
    entry = build_registration(root, **selection)
    target = _path(root, experiments.REGISTRATION)
    if dry_run:
        if entry['id'] in set(experiments.registered_ids(root)) | set(history.registered_ids(root)):
            raise ValueError('Trace ID is already registered')
        return entry
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _path(root, 'data/evaluation_views/.model-trials.import.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registry = experiments._registry(root)
        if entry['id'] in {r['id'] for r in registry} | set(history.registered_ids(root)):
            raise ValueError('Trace ID is already registered; overwrite is not permitted')
        # Revalidate after lock acquisition. No process may mutate the evidence
        # in the interval between a preflight and an administrative import.
        experiments.validate_registration(root, entry)
        payload = {'schema_version': 'model-trials-registration-v1', 'runs': [*registry, entry]}
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.model-trial-import-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    for key in ('id', 'title', 'provider', 'model', 'prepared', 'output', 'arm', 'source-catalog', 'source-bytes'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = vars(parser.parse_args(argv))
    args['identity'] = args.pop('id')
    entry = register_trial(**args)
    print(json.dumps({'id': entry['id'], 'dry_run': args['dry_run'], 'evidence_files': len(entry['files'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
