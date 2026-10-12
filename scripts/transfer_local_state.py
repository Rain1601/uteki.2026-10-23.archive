"""Explicit private-state transfer. Never uploads files or includes .env files.

Run only while model jobs and dialogue writes are stopped. Frozen files are
copied byte for byte; a manifest detects corruption and concurrent changes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def allowed(path):
    return not any(part.startswith('.env') or part in {
        '__pycache__', 'node_modules', '.venv', '.git', '.DS_Store'
    } for part in path.parts) and path.suffix not in {'.pyc', '.pyo'}


def safe_file(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('unsafe_relative_path')
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or not parts.parts or '..' in parts.parts or '\\' in relative
            or parts.as_posix() != relative):
        raise ValueError('unsafe_relative_path')
    target = root.joinpath(*parts.parts)
    for parent in (target, *target.parents):
        if parent.is_symlink():
            raise ValueError('symlink_not_allowed')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('path_outside_destination')
    return target


def validate_output_selections(selections):
    if not isinstance(selections, list) or any(not isinstance(value, str) for value in selections):
        raise ValueError('invalid_output_selections')
    for relative in selections:
        safe_file(Path('/transfer-validation'), relative)
        parts = PurePosixPath(relative).parts
        if len(parts) < 2 or parts[0] != 'output' or not allowed(Path(relative)):
            raise ValueError('output_selection_must_be_subdirectory')
    paths = [PurePosixPath(value) for value in selections]
    for index, path in enumerate(paths):
        if any(path == other or path in other.parents or other in path.parents
               for other in paths[:index]):
            raise ValueError('duplicate_or_overlapping_output_selections')
    return selections


def repository_path_allowed(relative, output_selections=()):
    parts = PurePosixPath(relative).parts
    return (len(parts) >= 2 and parts[0] in {'data', 'experiments'}
            or len(parts) >= 3 and parts[:2] == ('.local', 'claude-dialogues')
            or any(PurePosixPath(selected) in PurePosixPath(relative).parents
                   for selected in output_selections))


def private_mkdir(path):
    """Create every missing ancestor privately; never chmod existing directories."""
    pending = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise ValueError('symlink_not_allowed')
        pending.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise ValueError('destination_parent_is_not_directory')
    for directory in reversed(pending):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)


def archive_location(name, *, directory=False, output_selections=()):
    if directory and name in {'repository', 'dialogue'}:
        return name, None
    prefix, sep, relative = name.partition('/')
    if not sep or prefix not in {'repository', 'dialogue'} or not allowed(Path(relative)):
        raise ValueError('unapproved_archive_path')
    safe_file(Path('/transfer-validation'), relative)
    directory_root = directory and relative in {'data', 'experiments', '.local', '.local/claude-dialogues'}
    selected_directory = directory and any(
        PurePosixPath(relative) == PurePosixPath(selected)
        or PurePosixPath(relative) in PurePosixPath(selected).parents
        for selected in output_selections)
    if (prefix == 'repository' and not directory_root and not selected_directory
            and not repository_path_allowed(relative, output_selections)):
        raise ValueError('repository_path_outside_transfer_scope')
    return prefix, relative


def create(root, dialogue, output, include_output=None):
    if output.exists():
        raise ValueError('archive_already_exists')
    if dialogue is not None and not dialogue.is_dir():
        raise ValueError('explicit_dialogue_directory_missing')
    output_selections = validate_output_selections([] if include_output is None else include_output)
    for relative in output_selections:
        source = safe_file(root, relative)
        if not source.is_dir():
            raise ValueError('explicit_output_directory_missing: ' + relative)
        if output.resolve().is_relative_to(source.resolve()):
            raise ValueError('archive_inside_selected_output')
    selected = subprocess.check_output([
        'git', '-C', str(root), 'ls-files', '--others', '--ignored',
        '--exclude-standard', '-z', '--', 'data', 'experiments', '.local/claude-dialogues'
    ]).decode().split('\0')
    sources = {}
    directories = set()
    for relative in selected:
        path = Path(relative)
        if relative and allowed(path):
            source = safe_file(root, relative)
            if source.is_file():
                sources['repository/' + relative] = source
    for selected_output in output_selections:
        selected_root = safe_file(root, selected_output)
        directories.add('repository/' + selected_output)
        for source in sorted(selected_root.rglob('*')):
            relative = source.relative_to(root).as_posix()
            safe_file(root, relative)
            if allowed(Path(relative)):
                if source.is_file():
                    sources['repository/' + relative] = source
                elif source.is_dir():
                    directories.add('repository/' + relative)
                else:
                    raise ValueError('output_entry_not_regular_file_or_directory: ' + relative)
    if dialogue:
        directories.add('dialogue')
        for source in sorted(dialogue.rglob('*')):
            relative = source.relative_to(dialogue)
            if allowed(relative):
                safe_file(dialogue, relative.as_posix())
                if source.is_file():
                    sources['dialogue/' + relative.as_posix()] = source
                elif source.is_dir():
                    directories.add('dialogue/' + relative.as_posix())
    for name in (*sources, *directories):
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != '.')
    manifest = {'schema': 'uteki-private-transfer-v2' if output_selections else 'uteki-private-transfer-v1', 'repository_root': str(root),
                'dialogue_root': str(dialogue) if dialogue else None,
                'git_head_at_export': subprocess.check_output([
                    'git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip(),
                'credentials_included': False, 'directories': sorted(directories), 'files': {}}
    if output_selections:
        manifest['output_selections'] = output_selections
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, source in sorted(sources.items()):
                raw = source.read_bytes()
                manifest['files'][name] = {'sha256': digest(raw), 'bytes': len(raw)}
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = len(raw), 0o600
                archive.addfile(entry, io.BytesIO(raw))
            # Fail rather than export an inconsistent snapshot of a writing job.
            for name, source in sources.items():
                if digest(source.read_bytes()) != manifest['files'][name]['sha256']:
                    raise ValueError('source_changed_during_export: ' + name)
            raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
            entry = tarfile.TarInfo('transfer-manifest.json')
            entry.size, entry.mode = len(raw), 0o600
            archive.addfile(entry, io.BytesIO(raw))
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {'files': len(sources), 'directories': len(directories), 'archive_bytes': output.stat().st_size,
            'sha256': digest(output.read_bytes()), 'credentials_included': False}


def inspect_or_restore(archive_path, root=None, dialogue=None):
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        names = [entry.name for entry in members]
        if len(set(names)) != len(names) or any(not entry.isfile() for entry in members):
            raise ValueError('archive_contains_duplicate_or_non_file_entries')
        manifest = json.load(archive.extractfile('transfer-manifest.json'))
        if manifest.get('schema') not in {'uteki-private-transfer-v1', 'uteki-private-transfer-v2'}:
            raise ValueError('unsupported_manifest')
        if manifest['schema'] == 'uteki-private-transfer-v2':
            output_selections = validate_output_selections(manifest.get('output_selections'))
            if not output_selections:
                raise ValueError('invalid_output_selections')
        else:
            if 'output_selections' in manifest:
                raise ValueError('output_selections_require_v2')
            output_selections = []
        if set(names) != set(manifest['files']) | {'transfer-manifest.json'}:
            raise ValueError('archive_manifest_members_mismatch')
        directories = manifest.get('directories', [])
        if (not isinstance(directories, list) or any(not isinstance(name, str) for name in directories)
                or len(set(directories)) != len(directories)):
            raise ValueError('invalid_directory_manifest')
        if set(directories) & set(manifest['files']):
            raise ValueError('archive_destination_file_directory_conflict')
        if any('repository/' + selected not in directories for selected in output_selections):
            raise ValueError('selected_output_directory_not_in_manifest')
        for name in (*manifest['files'], *directories):
            if any(str(parent) in manifest['files'] for parent in PurePosixPath(name).parents):
                raise ValueError('archive_destination_file_directory_conflict')
        targets = []
        target_paths = set()
        directory_targets = set()
        for name in directories:
            prefix, relative = archive_location(name, directory=True, output_selections=output_selections)
            if root is not None:
                destination = root if prefix == 'repository' else dialogue
                if destination is None:
                    raise ValueError('explicit_dialogue_destination_required')
                target = safe_file(destination, relative) if relative else destination
                if target.is_symlink() or target.exists() and not target.is_dir():
                    raise ValueError('destination_directory_conflict')
                directory_targets.add(target.resolve())
        for name, record in manifest['files'].items():
            prefix, relative = archive_location(name, output_selections=output_selections)
            raw = archive.extractfile(name).read()
            if digest(raw) != record['sha256'] or len(raw) != record['bytes']:
                raise ValueError('archive_hash_mismatch: ' + name)
            if root is not None:
                destination = root if prefix == 'repository' else dialogue
                if destination is None:
                    raise ValueError('explicit_dialogue_destination_required')
                target = safe_file(destination, relative)
                normalized_target = target.resolve()
                if normalized_target in target_paths:
                    raise ValueError('multiple_archive_members_same_destination')
                target_paths.add(normalized_target)
                if target.exists() and (not target.is_file() or digest(target.read_bytes()) != record['sha256']):
                    raise ValueError('refuse_to_overwrite_different_file: ' + name)
                targets.append((name, target))
        # A file cannot also be a directory needed by another selected member.
        if target_paths & directory_targets:
            raise ValueError('archive_destination_file_directory_conflict')
        for target in target_paths | directory_targets:
            if any(parent in target_paths for parent in target.parents):
                raise ValueError('archive_destination_file_directory_conflict')
            if any(parent.exists() and not parent.is_dir() for parent in target.parents):
                raise ValueError('destination_parent_is_not_directory')
        # Validate the entire archive and all destinations before writing anything.
        for directory in sorted(directory_targets, key=lambda p: len(p.parts)):
            private_mkdir(directory)
        for name, target in targets:
            if target.exists():
                if target.is_symlink() or not target.is_file() or digest(target.read_bytes()) != manifest['files'][name]['sha256']:
                    raise ValueError('destination_changed_during_restore: ' + name)
                continue
            private_mkdir(target.parent)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(archive.extractfile(name).read())
        return {'files': len(manifest['files']), 'directories': len(directories), 'verified': True,
                'restored': root is not None, 'original_repository_root': manifest['repository_root'],
                'credentials_included': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('create')
    export.add_argument('--root', type=Path, required=True)
    export.add_argument('--dialogue-root', type=Path)
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--include-output', action='append', default=[], metavar='output/SUBDIRECTORY',
                        help='Explicit repository-relative output directory to include; repeatable, never includes .env files')
    verify = sub.add_parser('verify')
    verify.add_argument('archive', type=Path)
    restore = sub.add_parser('restore')
    restore.add_argument('archive', type=Path)
    restore.add_argument('--root', type=Path, required=True)
    restore.add_argument('--dialogue-root', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        result = create(args.root.resolve(), args.dialogue_root.resolve() if args.dialogue_root else None,
                        args.output, include_output=args.include_output)
    else:
        result = inspect_or_restore(args.archive, args.root.resolve() if args.command == 'restore' else None,
                                    args.dialogue_root.resolve() if args.command == 'restore' and args.dialogue_root else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
