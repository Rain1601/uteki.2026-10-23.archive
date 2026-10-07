"""Explicit local path relocation without mutating frozen observation history."""
import hashlib
import json
from pathlib import Path
import re

RECEIPT_PATH = Path('.local/observation-relocation.json')
VERSION = 'observation-relocation-v1'


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value):
    path = Path(value)
    if not value or path.is_absolute() or '..' in path.parts or str(path) == '.':
        raise ValueError('relocation_relative_path_required')
    return path


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('relocation_absolute_root_required')
    return path


def verify_relocated_output(*, root, observation_root, stage, trace_id, descriptor_path, descriptor):
    """Validate an explicitly installed receipt; does not modify any old record."""
    root, observation_root, stage = map(lambda p: Path(p).resolve(), (root, observation_root, stage))
    receipt_path = root / RECEIPT_PATH
    if (not receipt_path.is_file() or receipt_path.is_symlink()
            or not receipt_path.resolve().is_relative_to(root)):
        raise ValueError('recovery_trace_output_mismatch')
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('schema_version') != VERSION or receipt.get('new_root') != str(root):
        raise ValueError('relocation_receipt_root_mismatch')
    old_root = _absolute(receipt['old_root'])
    obs_rel = _relative(receipt['observation_root_relative'])
    if (root / obs_rel).resolve() != observation_root or not observation_root.is_relative_to(root):
        raise ValueError('relocation_observation_root_mismatch')
    rows = receipt.get('traces')
    if not isinstance(rows, list) or len({r.get('trace_id') for r in rows}) != len(rows):
        raise ValueError('relocation_trace_entries_invalid')
    selected = [row for row in rows if row.get('trace_id') == trace_id]
    if len(selected) != 1:
        raise ValueError('relocation_trace_not_registered')
    row = selected[0]
    expected_descriptor = observation_root / trace_id / 'descriptor.json'
    if (Path(descriptor_path).resolve() != expected_descriptor.resolve()
            or _sha(expected_descriptor) != row.get('descriptor_sha256')):
        raise ValueError('relocation_descriptor_hash_mismatch')
    relative = _relative(row['stage_relative'])
    original = _absolute(row['original_output_root'])
    if (original != old_root / relative or descriptor.get('output_root') != str(original)
            or not stage.is_relative_to(root) or stage != (root / relative).resolve()
            or stage.relative_to(root) != relative):
        raise ValueError('relocation_stage_suffix_mismatch')
    if descriptor.get('root_run_id') != trace_id or descriptor.get('run_id') != trace_id:
        raise ValueError('relocation_trace_identity_mismatch')


def create_receipt(*, root, old_root, observation_root, trace_ids=None):
    """Build a local receipt from copied originals. Caller writes a new file."""
    root, observation_root = Path(root).resolve(), Path(observation_root).resolve()
    old_root = _absolute(str(old_root))
    if not observation_root.is_relative_to(root):
        raise ValueError('relocation_observation_root_outside_repository')
    selected = set(trace_ids) if trace_ids is not None else None
    if selected is not None and (not selected or any(not re.fullmatch(r'run-[a-f0-9]{32}', x) for x in selected)):
        raise ValueError('relocation_trace_ids_invalid')
    rows = []
    for path in sorted(observation_root.glob('run-*/descriptor.json')):
        trace = path.parent.name
        if selected is not None and trace not in selected:
            continue
        descriptor = json.loads(path.read_text())
        original = _absolute(descriptor['output_root'])
        if not original.is_relative_to(old_root):
            if selected is not None: raise ValueError('relocation_original_outside_selected_root')
            continue
        relative = _relative(str(original.relative_to(old_root)))
        stage = (root / relative).resolve()
        if (not re.fullmatch(r'run-[a-f0-9]{32}', trace)
                or descriptor.get('root_run_id') != trace or descriptor.get('run_id') != trace
                or not stage.is_relative_to(root) or stage.relative_to(root) != relative or not stage.is_dir()):
            raise ValueError('relocation_original_trace_or_stage_invalid')
        rows.append(dict(trace_id=trace, original_output_root=str(original), stage_relative=str(relative),
                         descriptor_sha256=_sha(path)))
    if not rows or (selected is not None and {r['trace_id'] for r in rows} != selected):
        raise ValueError('relocation_selected_traces_missing')
    return dict(schema_version=VERSION,old_root=str(old_root),new_root=str(root),
                observation_root_relative=str(observation_root.relative_to(root)),traces=rows,
                original_history_modified=False)
