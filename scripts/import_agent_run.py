"""Explicitly validate and register one frozen historical Data query run.

The JSON spec declares the adapter, every local path/hash, source scope, child
relations and optional existing view IDs. No directory discovery or model calls.
"""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from apps.review_workbench.data import agent_runs_history as history


def import_run(root, spec):
    """Validate first, append a new ID atomically, leave all frozen files intact."""
    root = Path(root).resolve()
    entry = deepcopy(spec)
    entry.pop('summary', None)
    view = history.validate_registration(root, entry)
    entry['summary'] = history._summary(view)
    target = history._path(root, history.REGISTRATION)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A separate lock inode survives atomic registry replacement. Live writers
    # never use this registry; this serializes explicit administrative imports.
    lock_path = history._path(root, 'data/evaluation_views/.agent-runs.import.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registry = history._registry(root)
        existing_ids = {identity for row in registry['runs'] for identity in
                        [row['id'], *[child['id'] for child in row.get('children', [])]]}
        incoming_ids = {entry['id'], *[child['id'] for child in entry.get('children', [])]}
        if incoming_ids & existing_ids:
            raise ValueError('Run ID is already registered; historical registrations are not silently replaced')
        registry['runs'].append(entry)
        payload = (json.dumps(registry, ensure_ascii=False, indent=2) + '\n').encode()
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.agent-run-import-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return history._summary(view)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Explicit checkout root; defaults to this script checkout')
    parser.add_argument('--spec', type=Path, required=True, help='One complete explicit registration spec as JSON')
    args = parser.parse_args(argv)
    result = import_run(args.root, json.loads(args.spec.read_text(encoding='utf-8')))
    print(json.dumps({'id': result['id'], 'integrity': result['integrity'], 'usage': result['usage']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
