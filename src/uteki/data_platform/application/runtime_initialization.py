"""Publish a never-enabled root ledger; never recreate an enabled ledger."""
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from uteki.infrastructure.run_budget import RunBudget
from ..content.store import _fsync_directory
from ..contracts.common import CatalogError
from ..contracts.content import ObjectRef

SCHEMA='uteki-runtime-initialization-v1'

def new_root_descriptor(journal, root_session, native_id, ledger_path):
    return dict(ledger_path=ledger_path,mode='offline',max_requests=journal.limits.max_model_requests,
        policy=dict(context_ref=root_session.data['context']['context_ref'],run_policy=journal.root_policy,
            request_bytes=journal.limits.max_request_bytes,response_bytes=journal.limits.max_response_bytes,
            initialization_id=native_id),
        initialization=dict(context_ref=journal.context_ref,native_session_id=native_id,status='pending'))


def check_root_ready(journal, root):
    if root.get('phase')=='initializing':
        raise CatalogError('RECOVERY_REQUIRED','original root initialization has not claimed its ledger yet')
    marker=root.get('initialization')
    if marker:
        from .session import Session
        owner=Session(journal.catalog,marker['context_ref']).data.get('native_execution',{})
        if (marker['status']!='ready' or owner.get('native_session_id')!=marker['native_session_id']
                or owner.get('phase')=='initializing'):
            raise CatalogError('RECOVERY_REQUIRED','original root initialization must finish before a child starts')


def _publish(path, raw, checkpoint):
    def verify():
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size!=len(raw) or stream.read(len(raw)+1)!=raw:
                raise CatalogError('RECOVERY_REQUIRED','unconfirmed initial ledger differs from frozen input')
    if path.exists() or path.is_symlink():
        verify()
    else:
        fd,name=tempfile.mkstemp(prefix='.initial-ledger-',dir=path.parent)
        temporary=Path(name)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            checkpoint('runtime_ledger_temporary_written')
            try:os.link(temporary,path)
            except FileExistsError:verify()
            checkpoint('runtime_ledger_linked')
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
    _fsync_directory(path.parent)
    checkpoint('runtime_ledger_published')


def complete_initialization(journal):
    """Only a frozen initialization intent may create a new root's empty ledger."""
    session=journal.session();native=session.data['native_execution']
    intent=native.get('initialization')
    if not intent or intent.get('schema_version')!=SCHEMA or native['phase']!='initializing':
        raise CatalogError('RECOVERY_REQUIRED','no supported original initialization intent')
    expected='runs/'+journal.context['root_run_id']+'/budget.sqlite'
    if native['ledger_path']!=expected:
        raise CatalogError('RECOVERY_REQUIRED','initial ledger path differs')
    path=journal.catalog.root/expected
    if intent['owns_new_root']:
        descriptor=intent['root_descriptor']
        wanted=new_root_descriptor(journal,session.root_session(),native['native_session_id'],expected)
        if descriptor!=wanted:
            raise CatalogError('RECOVERY_REQUIRED','original root initialization binding differs')
        root=session.root_session();current=root.data.get('root_budget')
        if current is None:
            if path.exists() or path.is_symlink():
                raise CatalogError('RECOVERY_REQUIRED','unexpected ledger before original root claim')
            root.data['root_budget']=deepcopy(descriptor);root.save()
            journal.checkpoint('root_initialization_saved')
            current=descriptor
        pending=deepcopy(current)
        if pending.get('initialization',{}).get('status') not in {'pending','ready'}:
            raise CatalogError('RECOVERY_REQUIRED','root initialization state differs')
        pending['initialization']['status']='pending'
        if pending!=descriptor:
            raise CatalogError('RECOVERY_REQUIRED','root was claimed by a different initialization')
        if current['initialization']['status']=='pending':
            reference=intent.get('ledger_image')
            if reference is None:
                if path.exists() or path.is_symlink():
                    raise CatalogError('RECOVERY_REQUIRED','unbound ledger cannot be adopted')
                with tempfile.TemporaryDirectory(prefix='.initial-budget-',dir=path.parent) as directory:
                    initial=RunBudget(Path(directory)/'empty.sqlite',journal.root_policy['max_usd'],allow_zero_limit=True)
                    initial.bind_root(journal.context['root_run_id'],mode=descriptor['mode'],
                        max_requests=descriptor['max_requests'],policy=descriptor['policy'])
                    journal.checkpoint('runtime_ledger_image_created')
                    reference=journal.catalog.content.put_object(initial.path.read_bytes()).model_dump(mode='json')
                session=journal.session()
                session.data['native_execution']['initialization']['ledger_image']=reference
                session.save();journal.checkpoint('runtime_ledger_image_saved')
            raw=journal.catalog.content.read_object(ObjectRef.model_validate(reference))
            _publish(path,raw,journal.checkpoint)
            budget=RunBudget.open_existing(path,journal.root_policy['max_usd'],root_run_id=journal.context['root_run_id'])
            contract=budget.inspect_root()
            if (contract['mode']!=descriptor['mode'] or contract['policy']!=descriptor['policy']
                    or contract['max_requests']!=descriptor['max_requests'] or contract['stop_reason'] is not None
                    or budget.inspect_requests() or budget.summary()['requests']):
                raise CatalogError('RECOVERY_REQUIRED','initial ledger is not the frozen empty root')
            root=journal.session().root_session()
            root.data['root_budget']['initialization']['status']='ready'
            root.save();journal.checkpoint('root_initialization_ready')
    root=journal.session().root_session()
    descriptor=root.data.get('root_budget') or root.data.get('native_execution')
    if not descriptor or descriptor['ledger_path']!=expected:
        raise CatalogError('RECOVERY_REQUIRED','original root ledger binding is missing')
    try:
        budget=RunBudget.open_existing(path,journal.root_policy['max_usd'],root_run_id=journal.context['root_run_id'])
        contract=budget.inspect_root()
    except (OSError,ValueError,sqlite3.Error) as error:
        raise CatalogError('RECOVERY_REQUIRED','enabled root ledger is missing or invalid; never recreate it') from error
    if root.data.get('root_budget') and any(contract[key]!=descriptor[key] for key in ('mode','max_requests','policy')):
        raise CatalogError('RECOVERY_REQUIRED','root ledger contract differs from its original descriptor')
    if (contract['mode']!='offline' or journal.limits.max_model_requests>contract['max_requests']
            or journal.limits.max_request_bytes>contract['policy']['request_bytes']
            or journal.limits.max_response_bytes>contract['policy']['response_bytes']):
        raise CatalogError('SCOPE_VIOLATION','initialization cannot expand frozen root transport limits')
    if any(row['request'].get('context_ref')==journal.context_ref for row in budget.inspect_requests()):
        raise CatalogError('RECOVERY_REQUIRED','initialization already contains a model request; no SDK restart')
    native=journal.state()
    if native['tool_calls'] or native.get('openai_checkpoint') or native.get('claude_session'):
        raise CatalogError('RECOVERY_REQUIRED','initialization already contains native SDK work')
    return budget
