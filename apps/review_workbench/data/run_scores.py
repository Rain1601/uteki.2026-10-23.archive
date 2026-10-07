"""Append-only human assessments in a separate store; never adoption or model input.

Bindings come from the server's result projection. The request's binding must
match exactly before any write. A store path is host configuration, never a trace
ID or a path supplied by the scoring request.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from uuid import uuid4

STORE_VERSION = 'agent-result-scores-v1'
RUBRIC_VERSION = 'agent-result-v1'
DIMENSIONS = ('accuracy', 'coverage', 'analysis', 'evidence')
REVIEWER_LIMIT = 100
NOTES_LIMIT = 4000
MAX_STORE_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 10000
_LOCK = threading.RLock()
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z')
_SCORE_ID = re.compile(r'score-[0-9a-f]{32}\Z')
_BINDING_KEYS = {'trace_id', 'revision', 'result_sha256'}
_PAYLOAD_KEYS = {'binding', 'rubric_version', 'reviewer', 'scores', 'notes'}
_RECORD_KEYS = _PAYLOAD_KEYS | {'id', 'created_at'}


class ScoreValidationError(ValueError):
    """Invalid scoring input or host store path."""


class StaleScoreError(ScoreValidationError):
    """The client reviewed another result version; HTTP callers should return 409."""


class CorruptScoreStoreError(ValueError):
    """Unreadable or invalid stored history; do not discard or overwrite it."""


def _binding(value):
    if not isinstance(value, dict) or set(value) != _BINDING_KEYS:
        raise ScoreValidationError('Exact result binding fields required')
    if not isinstance(value['trace_id'], str) or not _ID.fullmatch(value['trace_id']):
        raise ScoreValidationError('Explicit valid trace identity required')
    revision = value['revision']
    if not ((type(revision) is int and revision >= 0) or
            (isinstance(revision, str) and 0 < len(revision) <= 256 and revision.strip() == revision)):
        raise ScoreValidationError('Explicit nonempty result revision required')
    if not isinstance(value['result_sha256'], str) or not _SHA.fullmatch(value['result_sha256']):
        raise ScoreValidationError('Explicit result SHA256 required')
    return deepcopy(value)


def _payload(value):
    if not isinstance(value, dict) or set(value) != _PAYLOAD_KEYS:
        raise ScoreValidationError('Exact score submission fields required')
    binding = _binding(value['binding'])
    if value['rubric_version'] != RUBRIC_VERSION:
        raise ScoreValidationError('Unsupported scoring rubric')
    reviewer = value['reviewer']
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > REVIEWER_LIMIT:
        raise ScoreValidationError('Reviewer must contain 1..100 characters')
    if not isinstance(value['notes'], str) or len(value['notes']) > NOTES_LIMIT:
        raise ScoreValidationError('Notes must contain at most 4000 characters')
    scores = value['scores']
    if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
        raise ScoreValidationError('All four score dimensions are required; use null for unscored')
    if any(v is not None and (type(v) is not int or not 0 <= v <= 5) for v in scores.values()):
        raise ScoreValidationError('Scores must be integers 0..5 or null')
    if all(v is None for v in scores.values()):
        raise ScoreValidationError('At least one dimension must be scored')
    return dict(binding=binding, rubric_version=RUBRIC_VERSION, reviewer=reviewer.strip(),
                scores={key: scores[key] for key in DIMENSIONS}, notes=value['notes'])


def _empty():
    return {'schema_version': STORE_VERSION, 'records': []}


def _validate_store(value):
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'records'} or
            value['schema_version'] != STORE_VERSION or not isinstance(value['records'], list)):
        raise CorruptScoreStoreError('Invalid score store schema')
    if len(value['records']) > MAX_RECORDS:
        raise CorruptScoreStoreError('Score store exceeds its record limit')
    identities = set()
    try:
        for record in value['records']:
            if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
                raise ValueError('Invalid stored score fields')
            if not isinstance(record['id'], str) or not _SCORE_ID.fullmatch(record['id']) or record['id'] in identities:
                raise ValueError('Invalid or repeated score identity')
            identities.add(record['id'])
            if not isinstance(record['created_at'], str):
                raise ValueError('Invalid score timestamp')
            timestamp = datetime.fromisoformat(record['created_at'])
            if timestamp.tzinfo is None:
                raise ValueError('Score timestamp requires a timezone')
            payload = {key: record[key] for key in _PAYLOAD_KEYS}
            if _payload(payload) != payload:
                raise ValueError('Stored score is not canonical')
    except (ValueError, TypeError, OverflowError) as error:
        raise CorruptScoreStoreError('Invalid stored score history') from error
    return value


def _checked_path(store_path):
    if not isinstance(store_path, (str, os.PathLike)) or not str(store_path).strip():
        raise ScoreValidationError('Explicit host score store path required')
    path = Path(store_path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ScoreValidationError('Score store paths cannot contain symlinks')
    if path.exists() and not path.is_file():
        raise CorruptScoreStoreError('Score store is not a regular file')
    return path


def _read(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return _empty()
    except OSError as error:
        raise CorruptScoreStoreError('Score store could not be read') from error
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            if os.fstat(stream.fileno()).st_size > MAX_STORE_BYTES:
                raise CorruptScoreStoreError('Score store exceeds its size limit')
            raw = stream.read(MAX_STORE_BYTES + 1)
            if len(raw) > MAX_STORE_BYTES:
                raise CorruptScoreStoreError('Score store exceeds its size limit')
            value = json.loads(raw)
    except CorruptScoreStoreError:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise CorruptScoreStoreError('Score store could not be decoded') from error
    return _validate_store(value)


@contextmanager
def _locked(path, *, write):
    with _LOCK:
        path = _checked_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + '.lock')
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as error:
            raise CorruptScoreStoreError('Score store lock could not be opened') from error
        with os.fdopen(descriptor, 'a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            try:
                yield _checked_path(path)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if len(raw) > MAX_STORE_BYTES:
        raise ScoreValidationError('Score store size limit reached; existing history was preserved')
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_scores(store_path, binding):
    """Return only this trace's history, partitioned by exact current binding."""
    binding = _binding(binding)
    path = _checked_path(store_path)
    if not path.exists():
        state = _empty()
    else:
        with _locked(path, write=False) as locked:
            state = _read(locked)
    rows = [record for record in state['records'] if record['binding']['trace_id'] == binding['trace_id']]
    return {'binding': binding, 'rubric_version': RUBRIC_VERSION,
            'current': deepcopy([row for row in rows if row['binding'] == binding]),
            'stale': deepcopy([row for row in rows if row['binding'] != binding])}


def save_score(store_path, binding, payload):
    """Append an assessment; never replace another review or modify the result."""
    binding = _binding(binding)
    payload = _payload(payload)
    if payload['binding'] != binding:
        raise StaleScoreError('Result binding changed; reload the result before scoring')
    path = _checked_path(store_path)
    with _locked(path, write=True) as locked:
        state = _read(locked)
        if len(state['records']) >= MAX_RECORDS:
            raise ScoreValidationError('Score store record limit reached; existing history was preserved')
        record = dict(payload, id='score-' + uuid4().hex,
                      created_at=datetime.now(timezone.utc).isoformat())
        state['records'].append(record)
        _write(locked, state)
    return deepcopy(record)
