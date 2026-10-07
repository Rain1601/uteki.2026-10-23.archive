"""One process owns one observation tree. Original business files stay untouched.

All references use paths relative to descriptor.output_root. The reader must apply
its own allowed-output roots and safe-content projections; a hash is not permission.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

from uteki.domain.runs.observation import EVENT_TYPES, SCHEMA_VERSION, ObservationContext, ObservationError


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path, value, *, replace=False):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    descriptor, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            # link is atomic and, unlike rename, cannot overwrite an existing event.
            os.link(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def safe_scope(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if not isinstance(value, dict):
        return {}
    allowed = {'company_ids', 'company_id', 'source_snapshot_ids', 'source_snapshot_id',
        'snapshot_id', 'source_policy_id', 'knowledge_cutoff', 'include_candidates',
        'periods', 'period_start', 'period_end', 'report_period_end', 'task_type',
        'symbol', 'market', 'cik', 'as_of'}
    result = {key: value[key] for key in allowed if key in value}
    if isinstance(value.get('period_catalog'), list):
        result['periods'] = [row['period'] for row in value['period_catalog']
                             if isinstance(row, dict) and isinstance(row.get('period'), dict)]
    selection = value.get('filing_selection')
    if isinstance(selection, dict):
        result['filing_selection'] = {key: selection[key] for key in
            ('mode', 'annual_form', 'report_period_end') if key in selection}
    return result


class ObservationRecorder:
    def __init__(self, root, output, *, kind, role, origin, scope=None, title='', protected=(), heartbeat_seconds=5):
        root, output = Path(root).absolute(), Path(output).absolute()
        for path in (root, output, *(Path(p).absolute() for p in protected if p)):
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise ValueError('observation paths cannot contain symlinks')
        root, output = root.resolve(), output.resolve()
        if output.exists():
            raise ValueError('observed root output must be new')
        if any(root.is_relative_to(p) or p.is_relative_to(root)
               for p in (output, *(Path(p).resolve() for p in protected if p))):
            raise ValueError('observation root must be separate from business output and frozen data')
        self.root_run_id = 'run-' + uuid4().hex
        self.generation = uuid4().hex
        self.output = output
        self.directory = root / self.root_run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / 'events').mkdir()
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._seq = 0
        self._fault = None
        self._terminal = False
        self._stop = threading.Event()
        self._published = set()
        self._published_paths = {}
        self._file_refs = {}
        self._owners = {}
        self._heartbeat_seconds = heartbeat_seconds
        self.context = ObservationContext(self, self.root_run_id, role, output)
        self._owners[output] = self.context
        self.descriptor = dict(schema_version=SCHEMA_VERSION, generation=self.generation,
            root_run_id=self.root_run_id, run_id=self.root_run_id, parent_run_id=None,
            parent_step_id=None, kind=kind, role=role, origin=origin, started_at=utc_now(),
            output_root=str(output), scope=safe_scope(scope), title=str(title)[:500])
        try:
            _atomic(self.directory / 'descriptor.json', self.descriptor)
            self._heartbeat()
            self.context.emit('run.started', kind=kind, role=role, origin=origin,
                              scope=safe_scope(scope), title=str(title)[:500])
            self.guard()
        except BaseException:
            self._stop.set()
            raise
        self._thread = threading.Thread(target=self._beat, name='uteki-observation', daemon=True)
        self._thread.start()

    def _fail(self, error):
        with self._lock:
            self._fault = self._fault or type(error).__name__

    def guard(self):
        if os.getpid() != self._pid:
            raise ObservationError('cross-process observation writer is unsupported')
        with self._lock:
            if self._fault:
                raise ObservationError('observation recording failed: ' + self._fault)
            if self._terminal:
                raise ObservationError('observation tree is already closed')

    def emit(self, context, event_type, data):
        # Events during cleanup are best effort; gate new work with guard().
        with self._lock:
            try:
                self.guard()
                if event_type not in EVENT_TYPES:
                    raise ValueError('unsupported observation event')
                seq = self._seq + 1
                event = dict(schema_version=SCHEMA_VERSION, generation=self.generation,
                    event_id=f'{self.root_run_id}:{seq}', root_run_id=self.root_run_id,
                    run_id=context.run_id, parent_run_id=context.parent_run_id,
                    parent_step_id=context.parent_step_id, seq=seq, at=utc_now(), type=event_type,
                    step_id=context.step_id, call_id=data.get('call_id'), data=data)
                _atomic(self.directory / 'events' / f'{seq:012d}.json', event)
                self._seq = seq
                return True
            except Exception as error:
                self._fail(error)
                return False

    def _heartbeat(self):
        with self._lock:
            self.guard()
            _atomic(self.directory / 'heartbeat.json', dict(schema_version=SCHEMA_VERSION,
                root_run_id=self.root_run_id, generation=self.generation, heartbeat_at=utc_now()), replace=True)

    def _beat(self):
        while not self._stop.wait(self._heartbeat_seconds):
            try:
                self._heartbeat()
            except Exception as error:
                self._fail(error)
                return

    def child(self, parent, output, *, kind, role, origin, scope=None, title=''):
        self.guard()
        output = Path(output).resolve()
        if not output.is_relative_to(self.output) or output == self.output or output.exists():
            raise ValueError('observed child output must be inside root business output')
        context = ObservationContext(self, 'run-' + uuid4().hex, role, output,
                                     parent.run_id, parent.step_id)
        with self._lock:
            if output in self._owners:
                raise ValueError('observed output already belongs to a run')
            self._owners[output] = context
        context.emit('run.started', kind=kind, role=role, origin=origin,
            output_path=str(output.relative_to(self.output)), scope=safe_scope(scope), title=str(title)[:500])
        context.guard()
        return context

    def publish(self, context, path, *, kind=None, artifact_id=None, **metadata):
        try:
            if not path.is_absolute():
                path = context.output / path
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('observed artifacts cannot be symlinks')
            path = path.resolve()
            relative = str(path.relative_to(self.output))
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            owner = max((p for p in self._owners if path.is_relative_to(p)), key=lambda p: len(p.parts))
            explicit_owner = metadata.pop('owned_by_context', False)
            owner_context = context if explicit_owner else self._owners[owner]
            previous = self._file_refs.get((relative, sha))
            if previous is not None and previous['run_id'] != context.run_id:
                if metadata.get('reused'):
                    context.emit('artifact.published', ref=previous, reused=True)
                    return previous
                return None
            if owner_context.run_id != context.run_id and not metadata.get('reused'):
                return None
            existing = self._published_paths.get((owner_context.run_id, relative, sha))
            if existing:
                if metadata.get('reused'):
                    context.emit('artifact.published', ref=existing, reused=True)
                return existing
            aid = artifact_id or 'file-' + hashlib.sha256(relative.encode()).hexdigest()[:24]
            ref = dict(artifact_id=aid, run_id=owner_context.run_id, path=relative, sha256=sha,
                       size_bytes=len(raw), kind=kind or path.stem, status='available', **metadata)
            key = (context.run_id, aid, sha)
            with self._lock:
                if key not in self._published:
                    context.emit('artifact.published', ref=ref)
                    self._published.add(key)
                    self._published_paths[(owner_context.run_id, relative, sha)] = ref
                    self._file_refs[(relative, sha)] = ref
            return ref
        except Exception as error:
            self._fail(error)
            return None

    def publish_tree(self, context, folder=None):
        folder = Path(folder or context.output)
        if folder.exists():
            for path in sorted(folder.rglob('*')):
                if (path.is_file() and not path.name.startswith('.') and path.suffix.lower()
                        not in {'.sqlite', '.db', '.wal', '.shm'}):
                    context.publish(path)

    def finish(self, context, *, result=None, error=None, elapsed_seconds=None):
        self.publish_tree(context)
        result = result if isinstance(result, dict) else {}
        terminal = ('cancelled' if isinstance(error, asyncio.CancelledError) or result.get('status') == 'cancelled' else
                    'failed' if error or self._fault or result.get('status') == 'failed' else 'finished')
        refs = [context.publish(context.output/name) for name in ('result.json', 'manifest.json')
                if (context.output/name).is_file()]
        context.emit('run.finished', status=terminal, business_status=result.get('status'),
            stop_reason=type(error).__name__ if error else result.get('stop_reason'),
            error_type=type(error).__name__ if error else None,
            elapsed_seconds=elapsed_seconds,
            result_ref=next((r for r in refs if r and r['path'].endswith('result.json')), None),
            manifest_ref=next((r for r in refs if r and r['path'].endswith('manifest.json')), None),
            quality=result.get('semantic_completeness', result.get('semantic_acceptance', 'not_evaluated')),
            adoption=result.get('adoption', 'not_recorded'))
        if context.run_id == self.root_run_id:
            self._stop.set()
            self._thread.join(timeout=1)
            with self._lock:
                self._terminal = True


@contextmanager
def observed_run(*, output, kind, role, origin, observation_root=None, observation_context=None,
                 scope=None, title='', protected=(), child=False):
    """The enclosing runner still owns original results, model cleanup and budget settlement."""
    if observation_root is not None and observation_context is not None:
        raise ValueError('provide observation_root or observation_context, not both')
    context = observation_context
    owns = observation_root is not None or (context is not None and child)
    if observation_root is not None:
        context = ObservationRecorder(observation_root, output, kind=kind, role=role,
            origin=origin, scope=scope, title=title, protected=protected).context
    elif context is not None and child:
        context = context.recorder.child(context, output, kind=kind, role=role,
                                        origin=origin, scope=scope, title=title)
    started = time.monotonic()
    error = None
    try:
        if context:
            context.guard()
        yield context
    except BaseException as exc:
        error = exc
        raise
    finally:
        if context and owns:
            result = None
            try:
                result = json.loads((Path(output)/'result.json').read_text())
            except (OSError, ValueError):
                pass
            context.recorder.finish(context, result=result, error=error,
                                    elapsed_seconds=time.monotonic()-started)
            if error is None and context.recorder._fault:
                raise ObservationError('observation recording failed: ' + context.recorder._fault)


@contextmanager
def observed_step(context, ordinal, *, phase, namespace='stage'):
    if context is None:
        yield None
        return
    step = context.for_step(ordinal, namespace=namespace)
    step.guard()
    step.emit('step.started', ordinal=ordinal, phase=phase)
    step.guard()
    started = time.monotonic()
    error = None
    try:
        yield step
    except BaseException as exc:
        error = exc
        raise
    finally:
        step.emit('step.finished', status='cancelled' if isinstance(error, asyncio.CancelledError)
                  else 'failed' if error else 'finished', error_type=type(error).__name__ if error else None,
                  elapsed_seconds=time.monotonic()-started, phase=phase)
