"""Freeze configured Skills in the existing content store and stage native SDK files.

This module owns packages and read permissions, not an agent loop. Native SDKs
still discover their metadata and load/read the selected Skill on demand.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shlex
from types import MappingProxyType

from .skills import LoadedSkill, get_skill, _json
from ..catalog.database import ensure_directory, read_regular
from ..contracts.common import CatalogError, canonical
from ..contracts.content import ObjectRef


def bundle_hash(content, files):
    return hashlib.sha256(_json(dict(content=content,
        files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}))).hexdigest()


class RuntimeSkills:
    def __init__(self, profile, journal, *, available_tools):
        self.profile, self.journal = profile, journal
        self.names = profile.profile.skills
        self.bundles = ()
        if not self.names:
            return
        session = journal.session()
        native = session.data['native_execution']
        snapshot = native.get('skill_snapshot')
        if snapshot is None:
            if journal.resuming:
                raise CatalogError('RECOVERY_REQUIRED','original Skill snapshot is missing')
            if profile.config_root is None:
                raise ValueError('Skill-enabled profile requires an explicit configuration root')
            bundles = tuple(get_skill(name,config_root=profile.config_root,
                model=profile.profile.model_id,sdk=profile.profile.kernel,
                model_version=profile.profile.model_version,sdk_version=profile.profile.sdk_version,
                available_tools=tuple(available_tools)) for name in self.names)
            snapshot = []
            for skill in bundles:
                value = dict(name=skill.name,content=skill.content,selection=dict(skill.selection),sha256=skill.sha256,
                    files={name:journal.catalog.content.put_object(raw).model_dump(mode='json')
                           for name,raw in skill.files.items()})
                reference = journal.catalog.content.put_object(canonical(value)).model_dump(mode='json')
                snapshot.append(dict(name=skill.name,sha256=skill.sha256,ref=reference))
            native['skill_snapshot'] = snapshot
            session.save()
            journal.checkpoint('skill_snapshot_committed')
        # Always verify through CAS, including the initial read. Recovery never
        # re-renders changed templates or reads the current configuration tree.
        try:
            if [v['name'] for v in snapshot] != list(self.names):
                raise ValueError('Skill snapshot names differ')
            bundles = []
            for item in snapshot:
                raw = journal.catalog.content.read_object(ObjectRef.model_validate(item['ref']))
                value = json.loads(raw)
                if canonical(value) != raw or value['name'] != item['name']:
                    raise ValueError('invalid Skill snapshot')
                files = {}
                for name, reference in value['files'].items():
                    parts = Path(name).parts
                    if (not parts or parts[0] not in {'references','scripts'} or '\\' in name
                            or any(p in {'','.','..'} for p in name.split('/'))):
                        raise ValueError('unsafe Skill resource path')
                    files[name] = journal.catalog.content.read_object(ObjectRef.model_validate(reference))
                digest = bundle_hash(value['content'],files)
                selection = value['selection']
                if (digest != value['sha256'] or digest != item['sha256']
                        or selection['model'] != profile.profile.model_id
                        or selection['sdk'] != profile.profile.kernel
                        or selection['sdk_version'] != profile.profile.sdk_version
                        or selection['model_version'] != profile.profile.model_version):
                    raise ValueError('Skill snapshot binding differs')
                bundles.append(LoadedSkill(value['name'],value['content'],MappingProxyType(files),
                    MappingProxyType(selection),digest))
            self.bundles = tuple(bundles)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise CatalogError('RECOVERY_REQUIRED','Skill snapshot cannot be verified') from error

    def files(self, prefix):
        return {str(Path(prefix)/skill.name/relative):raw for skill in self.bundles
                for relative,raw in {'SKILL.md':skill.content.encode(),**skill.files}.items()}

    def stage(self, parent):
        parent = Path(parent)
        for skill in self.bundles:
            path = parent/skill.name
            if path.exists() or path.is_symlink():
                self.verify(path,skill)
            else:
                skill.write_to(path)
        return parent

    @staticmethod
    def verify(path,skill):
        expected = {'SKILL.md':skill.content.encode(),**skill.files}
        try:
            if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_dir():
                raise ValueError('unsafe Skill directory')
            actual = {p.relative_to(path).as_posix() for p in path.rglob('*') if not p.is_dir() or p.is_symlink()}
            if actual != set(expected) or any(read_regular(path/name)!=raw for name,raw in expected.items()):
                raise ValueError('staged Skill differs from snapshot')
        except (ValueError,OSError) as error:
            raise CatalogError('RECOVERY_REQUIRED','staged Skill is missing, changed or incomplete') from error

    def record(self,kind,**fields):
        session = self.journal.session()
        session.data['native_execution'].setdefault('skill_events',[]).append(dict(type=kind,**deepcopy(fields)))
        session.save()

    def begin_tool(self,call_id,name,arguments):
        self.journal.guard_action()
        if not call_id:
            raise CatalogError('RECOVERY_REQUIRED','native Skill tool identity is required')
        session = self.journal.session()
        calls = session.data['native_execution'].setdefault('skill_tool_calls',{})
        call = calls.get(call_id)
        identity = dict(name=name,arguments=arguments)
        if call is None:
            call = calls[call_id] = dict(**deepcopy(identity),status='pending',output=None)
            session.save()
        elif any(call[k] != v for k,v in identity.items()):
            raise CatalogError('RECOVERY_REQUIRED','native Skill tool identity changed')
        return call

    def finish_tool(self,call_id,output):
        session = self.journal.session()
        call = session.data['native_execution']['skill_tool_calls'][call_id]
        if call['status']=='completed' and call['output']!=output:
            raise CatalogError('RECOVERY_REQUIRED','native Skill tool output changed')
        call.update(status='completed',output=deepcopy(output))
        session.save()
        self.journal.checkpoint('skill_tool_committed')

    async def invoke_openai(self,context,arguments,name,invoke):
        call = self.begin_tool(context.tool_call_id,name,json.loads(arguments))
        if call['status']=='completed':
            return call['output']
        output = await invoke(context,arguments)
        # SDK ItemHelpers serializes these native tools via str(output).
        # Freeze that exact text before canonical JSON can reorder dict keys.
        output = str(output)
        self.finish_tool(context.tool_call_id,output)
        return output

    def observe_claude_request(self,request):
        session = self.journal.session()
        native = session.data['native_execution']
        calls = native.get('skill_tool_calls',{})
        texts = []
        for message in request.get('messages',[]):
            if message.get('role')!='user':
                continue
            blocks = message.get('content',[])
            if isinstance(blocks,str):
                texts.append(blocks)
                continue
            for block in blocks:
                if block.get('type')=='text':
                    texts.append(block['text'])
                call = calls.get(block.get('tool_use_id'))
                if block.get('type')=='tool_result' and call is not None:
                    value = dict(content=block.get('content'),is_error=bool(block.get('is_error',False)))
                    if 'wire_result' in call and call['wire_result']!=value:
                        raise CatalogError('RECOVERY_REQUIRED','native Skill result changed on the wire')
                    call['wire_result'] = deepcopy(value)
        native['skill_wire_user_texts'] = texts
        session.save()

    def allow_read(self, path, *, root, prefix):
        if not isinstance(path,str) or not path:
            return False
        path = Path(path)
        root = Path(root).resolve()
        target = path if path.is_absolute() else root/path
        if any(p.is_symlink() for p in (target,*target.parents)):
            return False
        try:
            relative = target.resolve(strict=True).relative_to(root).as_posix()
            expected = self.files(prefix).get(relative)
            return expected is not None and read_regular(target) == expected
        except (ValueError,OSError):
            return False

    @staticmethod
    def allow_workdir(path, root):
        """An explicit spelling of the current workspace is not a cwd change."""
        if path is None:
            return True
        if not isinstance(path,str):
            return False
        root = Path(root)
        directory = Path(path) if path.strip() else Path('.')
        target = directory if directory.is_absolute() else root/directory
        try:
            return (not any(p.is_symlink() for p in (target,*target.parents))
                and target.resolve(strict=True)==root.resolve(strict=True))
        except (ValueError,OSError):
            return False

    async def openai_session(self):
        from agents.sandbox import Manifest, SandboxPathGrant
        from agents.sandbox.sandboxes import UnixLocalSandboxClient
        root = ensure_directory(self.journal.catalog.root,
            'runs/'+self.journal.context['run_id']+'/skill-runtime')
        source = self.stage(ensure_directory(root,'source'))
        work = ensure_directory(root,'workspace')
        for skill in self.bundles:
            loaded = work/'.agents'/skill.name
            if loaded.exists() or loaded.is_symlink():
                self.verify(loaded,skill)
        client = UnixLocalSandboxClient(inherit_host_environment=False)
        session = await client.create(manifest=Manifest(root=str(work),
            extra_path_grants=(SandboxPathGrant(path=str(source),read_only=True),)))
        return session,source,work

    def openai_capabilities(self, source, work):
        from agents.sandbox.capabilities import LocalDirLazySkillSource, Shell, Skills
        from agents.sandbox.entries import LocalDir
        owner = self
        class RecordedSkills(Skills):
            def tools(self):
                tools = super().tools()
                for tool in tools:
                    original = tool.on_invoke_tool
                    async def invoke(context,arguments,original=original):
                        return await owner.invoke_openai(context,arguments,'load_skill',original)
                    tool.on_invoke_tool = invoke
                return tools
        def configure(toolset):
            original = toolset.exec_command.on_invoke_tool
            async def read(context, arguments):
                self.journal.guard_action()
                args = json.loads(arguments)
                try:
                    words = shlex.split(args['cmd'])
                except ValueError:
                    return 'SKILL_READ_DENIED: malformed command.'
                # Reuse the official Shell, with a precise read-only boundary.
                # No arbitrary commands, scripts, cwd changes, or substitutions.
                if len(words)!=2 or words[0]!='cat' or args['cmd']!=shlex.join(words):
                    return 'SKILL_READ_DENIED: use cat followed by one listed Skill file path.'
                if not self.allow_workdir(args.get('workdir'),work):
                    return 'SKILL_READ_DENIED: workdir must resolve to the current workspace; omit it or use ".".'
                if args.get('tty',False):
                    return 'SKILL_READ_DENIED: tty must be false for Skill file reads.'
                if not self.allow_read(words[1],root=work,prefix='.agents'):
                    return 'SKILL_READ_DENIED: path must identify an unchanged file in the loaded Skill package.'
                result = await original(context,arguments)
                path = Path(words[1])
                target = path if path.is_absolute() else work/path
                expected = self.files('.agents')[target.resolve().relative_to(work.resolve()).as_posix()]
                # Completion of a native tool call is not proof that its output
                # contains the full file (the SDK can truncate or return errors).
                self.record('skill_file_read',path=words[1],call_id=context.tool_call_id,
                    full_content_returned=bool(expected) and expected in str(result).encode('utf-8'))
                return result
            async def invoke(context,arguments):
                return await self.invoke_openai(context,arguments,'exec_command',read)
            toolset.exec_command.on_invoke_tool = invoke
            toolset.write_stdin = None
        return [RecordedSkills(lazy_from=LocalDirLazySkillSource(source=LocalDir(src=str(source)))),
                Shell(configure_tools=configure)]
