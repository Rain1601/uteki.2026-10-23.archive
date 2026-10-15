"""Bounded local read runs stored through ContentStore and atomic control heads."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ..catalog.database import ensure_directory, read_regular, write_control
from ..contracts.common import CatalogError, canonical, digest, new_id, utc_now
from ..contracts.content import ObjectRef
from ..contracts.query import parse
from ..contracts.run import ResultRef


def ref_key(reference):
    reference = parse(ResultRef, reference)
    return digest(reference.canonical_bytes())


class Session:
    def __init__(self, catalog, context_ref):
        self.catalog = catalog
        self.uncertain = False
        self.head_ref = None
        if not isinstance(context_ref,str) or not context_ref.startswith('req_') or len(context_ref)!=30 or not context_ref[4:].isalnum():
            raise CatalogError('CONTEXT_NOT_FOUND', 'invalid context identity')
        try:
            mapping_path = catalog.root/'contexts'/context_ref
            if mapping_path.parent.is_symlink():
                raise ValueError('unsafe context directory')
            mapping = json.loads(read_regular(mapping_path))
            run = catalog._get('runs','run_id',mapping['run_id'])
            self.path = catalog.root/'runs'/run['run_id']
            if self.path.parent.is_symlink() or self.path.is_symlink():
                raise ValueError('unsafe run directory')
            self.head_ref = ObjectRef.model_validate_json(read_regular(self.path/'head.json'))
            self.data = json.loads(catalog.content.read_object(self.head_ref))
            if (self.data['schema_version'] != 'uteki-tool-session-v1' or self.data['context']['context_ref'] != context_ref
                    or self.data['context']['run_id'] != run['run_id']):
                raise ValueError('context/run binding differs')
            context_raw = catalog.content.read_object(ObjectRef.model_validate(mapping['context']))
            if canonical(self.data['context']) != context_raw:
                raise ValueError('immutable context differs')
            if (self.path/'creation.json').exists() and not (self.path/'creation-complete.json').exists():
                raise CatalogError('RECOVERY_REQUIRED','context creation acknowledgement incomplete; repeat original create_context with recover=True')
        except CatalogError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CatalogError('CONTEXT_NOT_FOUND', 'context or run state is missing, corrupt or incompatible') from error

    @classmethod
    def create(cls, catalog, context, request_key, *, recover=False, checkpoint=None):
        """Explicit recovery completes creation only; it never rewinds a running session."""
        if type(recover) is not bool:
            raise CatalogError('INVALID_REQUEST','recover must be a boolean')
        checkpoint = checkpoint or (lambda phase: None)
        run = catalog.start_run('data-context:'+request_key,purpose='deterministic data tools: '+context['request']['question'],kind='read')
        path = ensure_directory(catalog.root,'runs/'+run['run_id'])
        instance = cls.__new__(cls)
        instance.catalog, instance.path, instance.uncertain, instance.head_ref = catalog, path, False, None
        try:
            prepared = None
            if (path/'creation.json').exists():
                reference = ObjectRef.model_validate_json(read_regular(path/'creation.json'))
                prepared = json.loads(catalog.content.read_object(reference))
            if (path/'head.json').exists():
                instance.head_ref = ObjectRef.model_validate_json(read_regular(path/'head.json'))
                instance.data = json.loads(catalog.content.read_object(instance.head_ref))
                if prepared is not None and prepared['context'] != instance.data['context']:
                    raise CatalogError('CONTEXT_INVALID','creation and current context differ')
            elif prepared is not None:
                if (path/'creation-complete.json').exists() or (catalog.root/'contexts'/prepared['context']['context_ref']).exists():
                    raise CatalogError('CONTEXT_INVALID','completed context lost its head; cannot reset to its initial state')
                if not recover:
                    raise CatalogError('RECOVERY_REQUIRED','context creation incomplete; repeat original request with recover=True')
                instance.data = prepared
            else:
                remnants = list(path.iterdir())
                if any(not p.name.startswith('.pending-') or p.is_symlink() or not p.is_file() for p in remnants):
                    raise CatalogError('CONTEXT_INVALID','run files exist without a verifiable creation/head')
                binding = dict(request=context['request'],read_policy=context['read_policy'],run_id=run['run_id'])
                intent = catalog._existing('data-context-creation',request_key,binding)
                if intent is not None:
                    if not recover:
                        raise CatalogError('RECOVERY_REQUIRED','context control files incomplete; repeat original request with recover=True')
                    initial = ObjectRef.model_validate_json(intent)
                    instance.data = json.loads(catalog.content.read_object(initial))
                    # Losing completed controls is corruption, never permission to
                    # restart from the creation intent and forget prior operations.
                    mappings = catalog.root/'contexts'
                    if mappings.exists() and any(json.loads(read_regular(p)).get('run_id')==run['run_id'] for p in mappings.iterdir() if p.name.startswith('req_')):
                        raise CatalogError('CONTEXT_INVALID','existing mapping has lost its state; cannot reset')
                else:
                    if remnants:
                        raise CatalogError('CONTEXT_INVALID','pending files have no durable creation intent')
                    context = context | dict(run_id=run['run_id'],root_run_id=run['root_run_id'])
                    instance.data = dict(schema_version='uteki-tool-session-v1',context=context,revision=0,previous=None,
                        status='open',plan=dict(version=0,needs=[]),plan_history=[],state=None,operations={},results={},cursors={},
                        turns=0,wall_seconds=0.0,no_progress_turns=0,seen_results=[],delivery=None)
                    initial = catalog.content.put_object(canonical(instance.data))
                    # Reuse the existing durable registration/ContentStore
                    # mechanism, so even the first control-file write can fail.
                    with catalog.database.transaction():
                        catalog._register_key('data-context-creation',request_key,binding,initial.model_dump_json())
                write_control(path/'creation.json',canonical(initial.model_dump(mode='json')))
                checkpoint('context_prepared')
            saved = instance.data['context']
            identity = saved['context_ref']
            if not isinstance(identity,str) or len(identity)!=30 or not identity.startswith('req_') or not identity[4:].isalnum():
                raise CatalogError('CONTEXT_INVALID','saved context identity is invalid')
            if (instance.data['schema_version'] != 'uteki-tool-session-v1' or saved['run_id'] != run['run_id']
                    or saved['root_run_id'] != run['root_run_id']):
                raise CatalogError('CONTEXT_INVALID','saved context is not bound to the registered run')
            if saved['request'] != context['request'] or saved['read_policy'] != context['read_policy']:
                raise CatalogError('IDEMPOTENCY_CONFLICT','context request differs')
            mapping_root = ensure_directory(catalog.root,'contexts')
            mapping_path = mapping_root/saved['context_ref']
            # A current head may include prior operations. Recover only its mapping,
            # never substitute the initial creation record for that head.
            if instance.head_ref is not None and mapping_path.exists():
                if prepared is not None and not (path/'creation-complete.json').exists():
                    if not recover:
                        raise CatalogError('RECOVERY_REQUIRED','context creation acknowledgement is incomplete; use recover=True')
                    mapping = json.loads(read_regular(mapping_path))
                    if mapping['run_id'] != run['run_id'] or catalog.content.read_object(ObjectRef.model_validate(mapping['context'])) != canonical(saved):
                        raise CatalogError('CONTEXT_INVALID','existing mapping differs; no recovery was performed')
                    # A visible mapping may have failed its directory fsync.
                    # Re-acknowledge the identical bytes before marking complete.
                    write_control(mapping_path,canonical(mapping))
                    write_control(path/'creation-complete.json',canonical({'context_ref':saved['context_ref']}))
                return cls(catalog,saved['context_ref'])
            if instance.head_ref is not None and not recover:
                raise CatalogError('RECOVERY_REQUIRED','context mapping missing; repeat original request with recover=True')
            if instance.head_ref is None:
                instance.save()
            checkpoint('context_head_written')
            context_obj = catalog.content.put_object(canonical(saved))
            write_control(mapping_path,canonical(dict(run_id=run['run_id'],context=context_obj.model_dump(mode='json'))))
            checkpoint('context_mapping_written')
            write_control(path/'creation-complete.json',canonical({'context_ref':saved['context_ref']}))
            return cls(catalog,saved['context_ref'])
        except OSError as error:
            raise CatalogError('RECOVERY_REQUIRED','context creation write outcome uncertain; reopen and repeat original request with recover=True') from error
        except CatalogError:
            raise
        except (ValueError,KeyError,TypeError) as error:
            raise CatalogError('CONTEXT_INVALID','saved context creation data is invalid; no recovery was performed') from error

    def save(self):
        self.catalog.database.assert_open()
        if self.uncertain:
            raise CatalogError('RECOVERY_REQUIRED','session head outcome uncertain; reopen before inspecting results')
        self.data['revision'] += 1
        self.data['previous'] = self.head_ref.model_dump(mode='json') if self.head_ref else None
        reference = self.catalog.content.put_object(canonical(self.data))
        try:
            write_control(self.path/'head.json',canonical(reference.model_dump(mode='json')),replace=True)
        except OSError as error:
            self.uncertain = True
            raise CatalogError('RECOVERY_REQUIRED','session head write outcome uncertain; no successful response returned') from error
        self.head_ref = reference

    def lookup(self, reference):
        reference = parse(ResultRef,reference)
        if reference.run_id != self.data['context']['run_id']:
            raise CatalogError('RESULT_REF_INVALID','result belongs to a different run')
        value = self.data['results'].get(ref_key(reference))
        if value is None:
            raise CatalogError('RESULT_REF_INVALID','result was not returned by this run')
        operation = self.data['operations'].get(reference.operation_id)
        if operation is None or operation['status'] != 'completed':
            raise CatalogError('RESULT_REF_INVALID','operation has no completed response')
        return deepcopy(value)

    def proposed_plan(self, state, tool):
        if state.next_action != tool:
            raise CatalogError('INVALID_REQUEST','state.next_action must equal current tool')
        plan = deepcopy(self.data['plan'])
        if state.plan_update:
            update = state.plan_update
            if update.base_version != plan['version']:
                raise CatalogError('PLAN_VERSION_MISMATCH','plan base version changed')
            needs = [n.model_dump(mode='json') for n in update.needs]
            mapped = {n['need_id']:n for n in needs}
            if any(mapped.get(n['need_id']) != n for n in plan['needs']):
                raise CatalogError('INVALID_REQUEST','existing needs cannot be removed or rewritten')
            plan = dict(version=plan['version']+1,needs=needs)
        if not plan['needs']:
            raise CatalogError('INVALID_REQUEST','first tool call requires a nonempty plan')
        current = [n.need_id for n in state.satisfied]+[n.need_id for n in state.gaps]
        if len(current) != len(set(current)) or set(current) != {n['need_id'] for n in plan['needs']}:
            raise CatalogError('INVALID_REQUEST','state must cover every need exactly once')
        for entry in (*state.satisfied,*state.gaps):
            for reference in entry.result_refs:
                self.lookup(reference)
        return plan

    def accept(self, *, key, fingerprint, tool, request, state, plan):
        if self.data['status'] != 'open':
            raise CatalogError('INVALID_STATE','query run is terminal')
        if any(o['status']=='accepted' for o in self.data['operations'].values()):
            raise CatalogError('OPERATION_INTERRUPTED','accepted operation has no confirmed response; inspect it before continuing')
        if plan != self.data['plan']:
            self.data['plan_history'].append(deepcopy(self.data['plan']))
        self.data['plan'], self.data['state'] = plan, state.model_dump(mode='json')
        identity = new_id('op')
        self.data['operations'][identity] = dict(operation_id=identity,request_key=key,fingerprint=fingerprint,
            tool=tool,request=request.model_dump(mode='json'),state=state.model_dump(mode='json'),
            status='accepted',accepted_at=utc_now(),response=None)
        self.data['turns'] += 1
        self.save()
        return identity

    def replay(self, key, fingerprint):
        matches = [v for v in self.data['operations'].values() if v['request_key']==key]
        if not matches:
            return None
        operation = matches[0]
        if operation['fingerprint'] != fingerprint:
            raise CatalogError('IDEMPOTENCY_CONFLICT','request key reused with different arguments or state')
        if operation['status'] != 'completed':
            raise CatalogError('OPERATION_INTERRUPTED','previous response is uncertain; effects are not automatically repeated')
        return deepcopy(operation['response'])

    def register(self, operation_id, kind, item):
        item = deepcopy(item)
        reference = ResultRef(run_id=self.data['context']['run_id'],operation_id=operation_id,
            kind=kind,item_id=new_id('res'))
        item['result_ref'] = reference.model_dump(mode='json')
        self.data['results'][ref_key(reference)] = item
        return item

    def complete(self, operation_id, response, elapsed):
        self.data['wall_seconds'] += elapsed
        operation = self.data['operations'][operation_id]
        operation['response'] = deepcopy(response)
        operation['status'] = 'completed'
        operation['completed_at'] = utc_now()
        self.save()
        return deepcopy(response)
