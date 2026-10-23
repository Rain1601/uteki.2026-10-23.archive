"""Publish a never-enabled root ledger; never recreate an enabled ledger."""
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from uteki.data_platform.application.run_budget import RunBudget
from ..content.store import _fsync_directory
from ..contracts.common import CatalogError
from ..contracts.content import ObjectRef

SCHEMA='uteki-runtime-initialization-v1'

# 生成待初始化根描述：网关引用原批次账本；离线模式绑定根策略、字节限制和初始化身份。
def new_root_descriptor(journal, root_session, native_id, ledger_path):
    if journal.gateway_binding is not None:
        root=journal.gateway['budget'].inspect_root()
        return dict(ledger_path=ledger_path,mode=root['mode'],max_requests=root['max_requests'],policy=root['policy'],
            gateway=deepcopy(journal.gateway_binding),
            initialization=dict(context_ref=journal.context_ref,native_session_id=native_id,status='pending'))
    return dict(ledger_path=ledger_path,mode='offline',max_requests=journal.limits.max_model_requests,
        policy=dict(context_ref=root_session.data['context']['context_ref'],run_policy=journal.root_policy,
            request_bytes=journal.limits.max_request_bytes,response_bytes=journal.limits.max_response_bytes,
            initialization_id=native_id),
        initialization=dict(context_ref=journal.context_ref,native_session_id=native_id,status='pending'))


# 子任务启动前检查原始初始化 owner 已准备就绪，防止在父账本认领未完成时继续执行。
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


# 将冻结原件持久化发布到目标路径；文件已存在时只能核验一致，不能覆盖或接管。
def _publish(path, raw, checkpoint):
    # 禁止跟随符号链接，并逐字节核对普通文件及长度，确保恢复使用同一份初始镜像。
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
            # 临时文件先 fsync，再以硬链接原子占用目标名；并发占用只允许完全相同的原件。
            try:os.link(temporary,path)
            except FileExistsError:verify()
            checkpoint('runtime_ledger_linked')
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
    _fsync_directory(path.parent)
    checkpoint('runtime_ledger_published')


# 依据原始冻结意图完成初始化；只有尚未启用的新根可以发布空账本，已启用账本绝不重建。
def complete_initialization(journal):
    """Only a frozen initialization intent may create a new root's empty ledger."""
    if journal.gateway_binding is not None:return _complete_gateway_initialization(journal)
    session=journal.session();native=session.data['native_execution']
    intent=native.get('initialization')
    if not intent or intent.get('schema_version')!=SCHEMA or native['phase']!='initializing':
        raise CatalogError('RECOVERY_REQUIRED','no supported original initialization intent')
    expected='runs/'+journal.context['root_run_id']+'/budget.sqlite'
    if native['ledger_path']!=expected:
        raise CatalogError('RECOVERY_REQUIRED','initial ledger path differs')
    path=journal.catalog.root/expected
    # 只有本次意图拥有新根时才允许首次认领，其他初始化必须复用已存在的根绑定。
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
        # 将 ready 临时归一为 pending 仅用于比较身份，避免把其他初始化认领误认为自己的恢复。
        if pending!=descriptor:
            raise CatalogError('RECOVERY_REQUIRED','root was claimed by a different initialization')
        if current['initialization']['status']=='pending':
            reference=intent.get('ledger_image')
            # 未保存镜像时先生成并内容寻址保存空账本；目标文件若已出现则拒绝猜测其来源。
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
            # 恢复发布使用原来冻结的镜像，随后核验账本仍为空、未停止且契约一致。
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
    # 进入已绑定阶段后只能打开原账本，缺失或损坏必须报告恢复需求，不能清空历史费用。
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
    # 初始化流程只处理尚未开展的运行；已有模型请求或 SDK 状态时不能重新从起点启动。
    if any(row['request'].get('context_ref')==journal.context_ref for row in budget.inspect_requests()):
        raise CatalogError('RECOVERY_REQUIRED','initialization already contains a model request; no SDK restart')
    native=journal.state()
    if native['tool_calls'] or native.get('openai_checkpoint') or native.get('claude_session'):
        raise CatalogError('RECOVERY_REQUIRED','initialization already contains native SDK work')
    return budget


# 将业务根接到预先发布的批次账本，只做绑定与就绪状态提交，不在此处创建账本。
def _complete_gateway_initialization(journal):
    """Attach one business root to a prepublished batch; never create a ledger here."""
    from .gateway_batch import load_gateway_binding
    session=journal.session();native=session.data['native_execution'];intent=native.get('initialization')
    if not intent or intent.get('schema_version')!=SCHEMA or native['phase']!='initializing':
        raise CatalogError('RECOVERY_REQUIRED','no original gateway initialization intent')
    expected=journal.gateway['ledger_path']
    if native['ledger_path']!=expected:raise CatalogError('RECOVERY_REQUIRED','gateway ledger path differs')
    budget=load_gateway_binding(session,journal.gateway_binding,journal.profile,journal.limits.model_dump(mode='json'))['budget']
    root=session.root_session();current=root.data.get('root_budget')
    if intent['owns_new_root']:
        descriptor=intent['root_descriptor']
        wanted=new_root_descriptor(journal,root,native['native_session_id'],expected)
        if descriptor!=wanted:raise CatalogError('RECOVERY_REQUIRED','gateway initialization binding differs')
        if current is None:
            root.data['root_budget']=deepcopy(descriptor);root.save()
            journal.checkpoint('root_initialization_saved');current=descriptor
        pending=deepcopy(current)
        if pending.get('initialization',{}).get('status') not in {'pending','ready'}:
            raise CatalogError('RECOVERY_REQUIRED','invalid gateway initialization state')
        pending['initialization']['status']='pending'
        if pending!=descriptor:raise CatalogError('RECOVERY_REQUIRED','business root belongs to a different gateway binding')
        if current['initialization']['status']=='pending':
            root.data['root_budget']['initialization']['status']='ready';root.save()
            journal.checkpoint('root_initialization_ready')
    # 非首次认领只能沿用原业务根的精确网关绑定，不能把既有根切换到另一个预算范围。
    elif current is None or current.get('gateway')!=journal.gateway_binding:
        raise CatalogError('RECOVERY_REQUIRED','original business root gateway binding missing')
    # 新 attempt 或已授权额度修订都绑定新的精确上下文，历史请求仍累计在原 scope。
    if any(r.get('control_scope_id')==journal.gateway_binding['scope_id'] and
           (('attempt_ref' not in journal.gateway_binding and not journal.gateway.get('allowance_revision'))
            or r['request'].get('context_ref')==journal.context_ref)
           for r in budget.inspect_requests()):
        raise CatalogError('RECOVERY_REQUIRED','initializing scope already contains requests; no SDK restart')
    if native['tool_calls'] or native.get('openai_checkpoint') or native.get('claude_session'):
        raise CatalogError('RECOVERY_REQUIRED','initialization already contains SDK work')
    return budget
