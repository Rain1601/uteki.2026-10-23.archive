"""Persist full tool output and read bounded JSON ranges with pinned cursors."""
from copy import deepcopy
import json
import re
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.domain.research_data.run_artifacts import ArtifactRef, ArtifactReadRequest, ArtifactCursor
from .financial_records import digest
from .query_dataset import contained


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def child_pointer(pointer, key):
    return pointer + '/' + str(key).replace('~', '~0').replace('/', '~1')


def at_pointer(value, pointer):
    if not pointer:
        return value
    if not pointer.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    for part in pointer[1:].split('/'):
        if re.search(r'~(?![01])', part):
            raise ValueError('invalid JSON pointer escape')
        key = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not key.isdigit() or str(int(key)) != key or int(key) >= len(value):
                raise ValueError('array pointer outside artifact')
            value = value[int(key)]
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            raise ValueError('pointer outside artifact')
    return value


class ArtifactReadProgress:
    """Track delivered content ranges, so overlapping reads do not invent progress."""
    def __init__(self):
        self.complete, self.ranges, self.collections = set(), {}, {}

    def _complete(self, artifact_id, pointer):
        return any(aid == artifact_id and (parent == '' or pointer == parent or pointer.startswith(parent + '/'))
                   for aid, parent in self.complete)

    @staticmethod
    def _mark(artifact_id):
        return {'artifact_id': artifact_id, 'complete': [], 'ranges': [], 'collections': []}

    @staticmethod
    def _full_value(mark, value, pointer):
        # Count actual leaves, so reading an already delivered child through its
        # parent does not invent progress. Parent completion is only bookkeeping.
        if isinstance(value, (dict, list)) and value:
            entries = value.items() if isinstance(value, dict) else enumerate(value)
            for key, item in entries:
                ArtifactReadProgress._full_value(mark, item, child_pointer(pointer, key))
            mark['collections'].append((pointer, 0, len(value), len(value)))
        else:
            mark['complete'].append(pointer)

    @classmethod
    def preview_mark(cls, artifact_id, full, preview):
        mark = cls._mark(artifact_id)
        def visit(original, observed, pointer):
            if original == observed:
                cls._full_value(mark, original, pointer)
            elif isinstance(original, dict) and isinstance(observed, dict):
                for key, value in observed.items():
                    if key in original: visit(original[key], value, child_pointer(pointer, key))
            elif isinstance(original, list) and isinstance(observed, list) and original[:len(observed)] == observed:
                for i, value in enumerate(observed):
                    cls._full_value(mark, value, child_pointer(pointer, i))
                mark['collections'].append((pointer, 0, len(observed), len(original)))
            elif isinstance(original, str) and isinstance(observed, str) and original.startswith(observed):
                mark['ranges'].append((pointer, 0, len(observed), len(original)))
        visit(full, preview, '')
        return mark

    @classmethod
    def page_mark(cls, page):
        pointer, unit = page['pointer'], page['unit']
        mark = cls._mark(page['artifact_id'])
        extent = (pointer, page['offset'], page['end_offset'], page['total_count'])
        if unit == 'entries':
            for item in page['items']:
                cls._full_value(mark, item['value'], child_pointer(pointer, item['key']))
            mark['collections'].append(extent)
        elif unit == 'items':
            for i, item in enumerate(page['items'], start=page['offset']):
                cls._full_value(mark, item, child_pointer(pointer, i))
            mark['collections'].append(extent)
        elif unit == 'characters':
            mark['ranges'].append(extent)
        elif page['returned_count']:
            mark['complete'].append(pointer)
        if page['total_count'] == 0:
            mark['complete'].append(pointer)
        return mark

    @staticmethod
    def _merge(old, start, end):
        merged = []
        for lo, hi in sorted([*old, (start, end)]):
            if merged and lo <= merged[-1][1]: merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else: merged.append((lo, hi))
        return merged

    def apply(self, mark):
        changed, aid = False, mark['artifact_id']
        for pointer, start, end, total in mark['ranges']:
            if self._complete(aid, pointer) or start == end: continue
            old = self.ranges.get((aid, pointer), [])
            merged = self._merge(old, start, end)
            changed |= sum(hi - lo for lo, hi in merged) > sum(hi - lo for lo, hi in old)
            self.ranges[aid, pointer] = merged
            if merged == [(0, total)]: self.complete.add((aid, pointer))
        for pointer in mark['complete']:
            if not self._complete(aid, pointer):
                changed = True
                self.complete.add((aid, pointer))
        for pointer, start, end, total in mark['collections']:
            if self._complete(aid, pointer) or start == end: continue
            merged = self._merge(self.collections.get((aid, pointer), []), start, end)
            self.collections[aid, pointer] = merged
            if merged == [(0, total)]: self.complete.add((aid, pointer))
        return changed

    def would_change(self, mark):
        return deepcopy(self).apply(mark)


class ArtifactStore:
    def __init__(self, root, *, refs=()):
        self.root = Path(root).resolve()
        self.refs = {r.artifact_id: r for r in (ArtifactRef.model_validate(v) for v in refs)}
        for ref in self.refs.values():
            self._validate_ref(ref)

    @staticmethod
    def _validate_ref(ref):
        expected = 'scope-' + digest(ref.scope.model_dump(mode='json'))[:24]
        if ref.scope_id != expected or not set(ref.source_ids) <= set(ref.scope.source_snapshot_ids):
            raise ValueError('artifact reference scope mismatch')

    def put(self, kind, value, *, scope, step, parent_ids=(), source_ids=(), evidence_id=None):
        scope = ExecutionScope.model_validate(scope)
        if not set(source_ids) <= set(scope.source_snapshot_ids):
            raise ValueError('artifact source is outside scope')
        identity = {'kind': kind, 'scope': scope.model_dump(mode='json'), 'value': value,
                    'parent_ids': list(parent_ids), 'source_ids': list(source_ids), 'evidence_id': evidence_id}
        aid = 'art-' + digest(identity)[:32]
        if aid in self.refs:
            self.load(aid)
            return self.refs[aid].model_dump(mode='json')
        if any(parent not in self.refs for parent in parent_ids):
            raise ValueError('unknown parent artifact')
        path = contained(self.root, 'artifacts/' + aid + '.json')
        if (self.root / 'artifacts').is_symlink():
            raise ValueError('artifact directory cannot be a symlink')
        write_new(path, value)
        ref = ArtifactRef(artifact_id=aid, kind=kind, path=str(path.relative_to(self.root)),
            sha256=digest(path.read_bytes()), size_bytes=path.stat().st_size, scope=scope,
            scope_id='scope-' + digest(scope.model_dump(mode='json'))[:24], created_step=step,
            parent_ids=parent_ids, source_ids=source_ids, evidence_id=evidence_id)
        self.refs[aid] = ref
        return ref.model_dump(mode='json')

    def load(self, artifact_id):
        if artifact_id not in self.refs:
            raise ValueError('unknown artifact ID')
        ref = self.refs[artifact_id]
        original_path = self.root / ref.path
        if any(p.is_symlink() for p in (original_path, *original_path.parents) if p != self.root.parent):
            raise ValueError('artifact symlink is not allowed')
        path = contained(self.root, ref.path)
        raw = path.read_bytes()
        if path.is_symlink() or len(raw) != ref.size_bytes or digest(raw) != ref.sha256:
            raise ValueError('artifact integrity mismatch')
        return json.loads(raw)

    def read(self, request):
        request = ArtifactReadRequest.model_validate(request)
        value = at_pointer(self.load(request.artifact_id), request.pointer)
        ref = self.refs[request.artifact_id]
        binding = {'artifact_id': ref.artifact_id, 'sha256': ref.sha256, 'scope_id': ref.scope_id,
                   'snapshot_id': ref.scope.snapshot_id, 'pointer': request.pointer}
        offset = request.offset or 0
        if request.cursor:
            if any(getattr(request.cursor, k) != v for k, v in binding.items()):
                raise ValueError('artifact cursor scope, hash or pointer mismatch')
            if request.offset is not None and request.offset != request.cursor.offset:
                raise ValueError('artifact cursor offset conflict')
            offset = request.cursor.offset
        unit = 'items' if isinstance(value, list) else 'entries' if isinstance(value, dict) else 'characters' if isinstance(value, str) else 'scalar'
        values = (value if isinstance(value, (list, str)) else
                  [{'key': k, 'value': v} for k, v in value.items()] if isinstance(value, dict) else [value])
        total = len(values)
        if offset > total:
            raise ValueError('artifact offset out of range')
        selected = '' if unit == 'characters' else []
        cursor = offset
        while cursor < total and cursor - offset < request.limit:
            candidate = selected + values[cursor] if unit == 'characters' else [*selected, values[cursor]]
            if json_size(candidate) > request.max_bytes:
                break
            selected = candidate
            cursor += 1
        gaps = []
        if cursor == offset and cursor < total:
            entry_pointer = child_pointer(request.pointer, cursor if unit == 'items' else values[cursor]['key']) if unit in ('items', 'entries') else request.pointer
            gaps = [{'reason': 'item_too_large', 'pointer': entry_pointer,
                     'required_bytes': json_size(values[cursor] if unit == 'characters' else [values[cursor]]),
                     'next_action': 'read a child pointer or increase max_bytes'}]
        next_cursor = ArtifactCursor(**binding, offset=cursor).model_dump(mode='json') if cursor < total else None
        return {'status': 'item_too_large' if gaps else 'limited' if next_cursor else 'read',
                **binding, 'unit': unit, 'offset': offset, 'end_offset': cursor,
                'total_count': total, 'returned_count': cursor - offset,
                'items': selected, 'bytes_returned': json_size(selected),
                'next_cursor': next_cursor, 'gaps': gaps}

    def preview(self, artifact_id, *, max_bytes=12000, limit=12):
        """Keep complete fields/items. Every omitted range has a pointer to read."""
        value = self.load(artifact_id)
        if json_size(value) <= max_bytes:
            return {'value': value, 'truncated': False, 'reads': []}
        if not isinstance(value, dict):
            page = self.read({'artifact_id': artifact_id, 'limit': limit, 'max_bytes': max_bytes})
            return {'value': page['items'], 'truncated': page['next_cursor'] is not None, 'reads': [page]}
        result, reads = {}, []
        ordered = sorted(value, key=lambda k: (isinstance(value[k], (dict, list)),
            ['blocks', 'nodes', 'hits', 'items', 'records', 'computed_facts'].index(k) if k in
            ['blocks', 'nodes', 'hits', 'items', 'records', 'computed_facts'] else 99))
        for key in ordered:
            candidate = {**result, key: value[key]}
            if json_size(candidate) <= max_bytes:
                result = candidate
                continue
            remaining = max_bytes - json_size(result) - json_size(key) - 8
            pointer = child_pointer('', key)
            if isinstance(value[key], list) and remaining >= 512:
                page = self.read({'artifact_id': artifact_id, 'pointer': pointer,
                                  'limit': limit, 'max_bytes': remaining})
                result[key] = page['items']
                reads.append({k: v for k, v in page.items() if k != 'items'})
            else:
                reads.append({'artifact_id': artifact_id, 'pointer': pointer,
                              'status': 'not_previewed', 'required_bytes': json_size(value[key])})
        return {'value': result, 'truncated': True, 'reads': reads[:limit],
                'unlisted_paths': max(0, len(reads) - limit), 'browse_pointer': ''}

    def index(self, *, scope, step, evidence_only=False):
        refs = [r.model_dump(mode='json') for r in self.refs.values()
                if r.kind != 'artifact_index' and (not evidence_only or r.evidence_id)]
        return self.put('artifact_index', refs, scope=scope, step=step)


def load_evidence_bundle(root):
    """Consumer readback for current manifests and frozen embedded v1 bundles."""
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    path = root / 'evidence-bundle.json'
    if digest(path.read_bytes()) != manifest['files'].get('evidence-bundle.json'):
        raise ValueError('evidence bundle integrity mismatch')
    bundle = json.loads(path.read_text())
    if bundle['schema_version'] == 'autonomous-evidence-manifest-v1':
        return bundle
    if bundle['schema_version'] != 'autonomous-evidence-manifest-v2':
        raise ValueError('unsupported evidence manifest version')
    store = ArtifactStore(root, refs=[item['artifact'] for item in bundle['items']])
    return {**bundle, 'items': [{**item, 'value': store.load(item['artifact']['artifact_id'])}
                               for item in bundle['items']]}
