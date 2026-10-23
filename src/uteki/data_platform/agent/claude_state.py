"""Verify native Claude history without constructing or rewriting a transcript."""
from copy import deepcopy
from dataclasses import asdict
import base64
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path

from claude_agent_sdk import get_session_messages, TextBlock, ThinkingBlock, ToolUseBlock

from ..contracts.common import CatalogError, canonical, digest
from ..contracts.content import ObjectRef


CONTINUE_PROMPT = ('Continue the same Data Agent task within its original scope and remaining root limits. '
                   'Use the saved tool results; do not repeat completed operations. '
                   'Finish through the Data deliver or clarify tool.')


# 审计 Claude 原生会话与公开 SDK 消息，保留 CLI 自身的对话历史和执行循环。
class ClaudeState:
    """A binding and audit of public SDK messages, not an alternative SDK loop."""
    # 将 SDK 版本、CLI 文件摘要、隔离工作目录和配置目录纳入会话恢复身份。
    def __init__(self, journal, binding, *, cwd, cli_path):
        self.journal, self.binding = journal, binding
        self.cwd = str(Path(cwd).resolve())
        with Path(cli_path).open('rb') as stream:
            cli_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.identity = dict(sdk_version=version('claude-agent-sdk'), cli_sha256=cli_hash,
            cwd=self.cwd, config_dir=str(Path(os.environ['CLAUDE_CONFIG_DIR']).resolve()))
        self.expected_history = None

    # 审计对象以规范 JSON 写入内容存储，持久化状态只保存精确对象引用。
    def put(self, value):
        return self.journal.catalog.content.put_object(canonical(value)).model_dump(mode='json')

    # 读取后再检验规范编码，防止恢复时接受无法对应原始审计记录的对象。
    def read(self, reference):
        raw = self.journal.catalog.content.read_object(ObjectRef.model_validate(reference))
        value = json.loads(raw)
        if canonical(value) != raw:
            raise ValueError('noncanonical Claude audit object')
        return value

    # 首次绑定原始输入；续跑则核对原生历史、已观察消息及账本响应的完整对应关系。
    def prepare(self):
        try:
            session = self.journal.session()
            native = session.data['native_execution']
            saved = native.get('claude_session')
            if saved is None:
                if self.journal.resuming:
                    raise ValueError('original Claude binding is missing')
                saved = dict(format='uteki-claude-session-v1', identity=self.identity,
                    input_ref=self.put(canonical(self.binding.context).decode()), assistant_messages=[])
                native['claude_session'] = saved
                session.save()
                self.journal.checkpoint('claude_session_bound')
            if saved['format'] != 'uteki-claude-session-v1' or saved['identity'] != self.identity:
                raise ValueError('Claude SDK/CLI/workspace binding differs')
            if not self.journal.resuming:
                return self.read(saved['input_ref'])
            messages = get_session_messages(native['native_session_id'], directory=self.cwd)
            if not messages or any(m.session_id != native['native_session_id'] for m in messages):
                raise ValueError('original native session is missing or has a foreign identity')
            assistants = [self.read(r) for r in saved['assistant_messages']]
            by_uuid = {m['uuid']:m for m in assistants}
            found = []
            for message in messages:
                if message.type != 'assistant':
                    continue
                expected = by_uuid.get(message.uuid)
                value = message.message
                if (expected is None or value.get('id') != expected['message_id']
                        or value.get('model') != expected['model']
                        or value.get('content') != expected['content']):
                    raise ValueError('native assistant history differs from the observed SDK output')
                found.append(message.uuid)
            if len(found) != len(set(found)) or set(found) != set(by_uuid):
                raise ValueError('native session lost or duplicated observed assistant messages')
            # 原生历史既不能多出未知模型响应，也不能丢失已确认响应或业务工具结果。
            self._verify_response_coverage(assistants)
            history = [dict(role=m.type, content=m.message['content']) for m in messages]
            self._verify_history(history, saved, native)
            self.expected_history = dict(saved=deepcopy(saved), native=deepcopy(native),
                assistant_blocks=[b for m in assistants for b in m['content']])
            # These outputs are eligible to be observed, but are not visible
            # until the bridge forwards the actual resumed native request.
            self.binding.returned = [deepcopy(c['output']) for c in native['tool_calls'].values()]
            proof = dict(identity=self.identity, native_session_id=native['native_session_id'],
                context_ref=self.journal.context_ref, messages=[asdict(m) for m in messages])
            native.setdefault('claude_resume_checks', []).append(self.put(proof))
            session.save()
            return CONTINUE_PROMPT
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CatalogError('RECOVERY_REQUIRED', 'Claude session cannot safely resume: '+str(error)) from error

    # 工具产生副作用前记录公开 SDK 的原始助手消息；同一消息身份只允许同一内容。
    def record_assistant(self, message):
        """Keep only what the public SDK actually emitted, before tool effects."""
        kinds = {TextBlock:'text', ThinkingBlock:'thinking', ToolUseBlock:'tool_use'}
        try:
            value = dict(uuid=message.uuid, message_id=message.message_id, model=message.model,
                content=[dict(type=kinds[type(b)], **asdict(b)) for b in message.content])
            native = self.journal.state()
            if (not message.uuid or not message.message_id or message.error is not None
                    or message.parent_tool_use_id is not None
                    or message.session_id != native['native_session_id']):
                raise ValueError('assistant message lacks its bound main-session identity')
            session = self.journal.session()
            refs = session.data['native_execution']['claude_session']['assistant_messages']
            for ref in refs:
                old = self.read(ref)
                if old['uuid'] == message.uuid:
                    if old != value:
                        raise ValueError('assistant message identity changed')
                    return
            refs.append(self.put(value))
            session.save()
            self.journal.checkpoint('claude_assistant_observed')
        except (ValueError, KeyError, TypeError) as error:
            raise CatalogError('RECOVERY_REQUIRED', 'Claude assistant audit failed: '+str(error)) from error

    # 只读取 SSE 的 message_start 身份来对账，不拼接模型正文或自行重放流。
    def _verify_response_coverage(self, assistants):
        # Inspect only the public protocol's message_start identity. The SDK
        # parses content; this does not reconstruct model output or replay SSE.
        expected = []
        for record in self.journal.budget.inspect_requests():
            if record['request']['context_ref'] != self.journal.context_ref:
                continue
            if record['stage'] != 'responded' or record['cost_state'] not in {'settled','bounded'}:
                raise ValueError('native physical request is not confirmed')
            response = record['response_event']['response']
            captured=response.get('http',response)
            if not response.get('complete') or captured.get('status') != 200:
                raise ValueError('native model response is not complete and successful')
            if self.journal.gateway_binding is not None:
                from .providers.openrouter_evidence import response_bytes
                if (record.get('control_scope_id')!=self.journal.gateway_binding['scope_id']
                        or record['request'].get('profile')!=self.journal.profile
                        or record['request'].get('origin')!=self.journal.gateway['plan']['origin']):
                    raise ValueError('saved native HTTP request binding differs')
                raw=response_bytes(captured)
            else:
                raw = base64.b64decode(captured['body_base64'], validate=True)
                if digest(raw) != captured['body_sha256']:
                    raise ValueError('saved native response bytes differ')
            starts = [event['message']['id'] for line in raw.splitlines() if line.startswith(b'data:')
                and (event := json.loads(line[5:])).get('type') == 'message_start']
            if len(starts) != 1:
                raise ValueError('native response lacks an unambiguous message identity')
            expected.extend(starts)
        actual = {m['message_id'] for m in assistants}
        if not expected or len(expected) != len(set(expected)) or set(expected) != actual:
            raise ValueError('native history does not cover every complete model response')

    # 逐项核对工具调用指纹、顺序和原样返回；用户输入只能是原任务及显式续跑指令。
    def _verify_history(self, messages, saved, native, *, wire=False):
        calls = {c['call_id']:c for c in native['tool_calls'].values()}
        skill_calls = native.get('skill_tool_calls', {})
        used, returned, texts = set(), set(), []
        for message in messages:
            content = message.get('content', [])
            if isinstance(content, str):
                if message['role'] == 'user': texts.append(content)
                continue
            for block in content:
                kind = block.get('type')
                if kind == 'text' and message['role'] == 'user':
                    texts.append(block['text'])
                elif kind == 'tool_use':
                    if block['id'] in skill_calls:
                        call = skill_calls[block['id']]
                        if (message['role'] != 'assistant' or block['id'] in used
                                or block['name'] != call['name'] or block['input'] != call['arguments']):
                            raise ValueError('native Skill invocation differs from the recorded operation')
                        used.add(block['id'])
                        continue
                    call = calls.get(block['id'])
                    name = block['name'].removeprefix('mcp__data__')
                    if (message['role'] != 'assistant' or call is None or block['id'] in used
                            or block['name'] != 'mcp__data__'+call['name']
                            or digest(canonical(dict(name=name, arguments=block['input']))) != call['fingerprint']):
                        raise ValueError('native tool invocation differs from the original business operation')
                    used.add(block['id'])
                elif kind == 'tool_result':
                    identity = block['tool_use_id']
                    if identity in skill_calls:
                        call = skill_calls[identity]
                        tool_result = dict(content=block.get('content'),is_error=bool(block.get('is_error',False)))
                        if (message['role'] != 'user' or identity not in used or identity in returned
                                or call['status'] != 'completed' or call.get('wire_result') != tool_result):
                            raise ValueError('native Skill result differs from the observed wire result')
                        returned.add(identity)
                        continue
                    call = calls.get(identity)
                    value = block.get('content')
                    if (message['role'] != 'user' or call is None or identity not in used or identity in returned
                            or call['status'] != 'completed' or call['output'] is None
                            or value != [dict(type='text', text=canonical(call['output']).decode())]
                            or bool(block.get('is_error', False)) != (call['output'].get('status') == 'error')):
                        raise ValueError('native tool result is missing, altered, pending or a cancellation substitute')
                    returned.add(identity)
        expected = set(calls) | set(skill_calls)
        if used != expected or returned != expected or not used:
            raise ValueError('native tool history is incomplete')
        # Public get_session_messages excludes isMeta entries, including Skill
        # expansion. Check ordinary user history there, then check the exact
        # frozen expansion at the real resumed HTTP boundary before dispatch.
        original_texts = native.get('skill_wire_user_texts') if skill_calls and wire else None
        if original_texts is None:
            original_texts = [self.read(saved['input_ref'])]
        if not original_texts or texts[:len(original_texts)] != original_texts or any(t != CONTINUE_PROMPT for t in texts[len(original_texts):]):
            raise ValueError('native user history differs from the original task or explicit continuations')

    # 在首次恢复请求真正发送前，再核对 CLI 即将转发的上下文与已审计原生历史。
    def validate_request(self, request):
        if self.expected_history is None:
            return
        try:
            history = self.expected_history
            self._verify_history(request['messages'], history['saved'], history['native'],wire=True)
            blocks = [dict((k,v) for k,v in b.items() if k != 'cache_control')
                for m in request['messages'] if m['role'] == 'assistant' for b in m['content']]
            # This pinned CLI inserts a synthetic conversational separator
            # after a finished tool turn on resume. It is not model output or
            # business evidence. Permit this exact trailing marker only; all
            # original assistant blocks and tool results still must match.
            # 这里只允许当前锁定 CLI 的精确尾部控制标记，不能借此放宽原始业务证据校验。
            marker = dict(type='text',text='No response requested.')
            if blocks == history['assistant_blocks']+[marker]:
                self.binding.events.append(dict(type='native_resume_control_marker',content=marker))
                blocks = blocks[:-1]
            if blocks != history['assistant_blocks']:
                raise ValueError('forwarded native assistant context differs from the verified transcript')
            self.journal.checkpoint('claude_resume_request_verified')
            self.expected_history = None
        except (ValueError, KeyError, TypeError) as error:
            self.journal.failure_code = 'RECOVERY_REQUIRED'
            session = self.journal.session()
            session.data['native_execution']['events'].append(dict(type='claude_resume_request_rejected',
                reason=str(error), request_ref=self.put(request)))
            session.save()
            raise CatalogError('RECOVERY_REQUIRED', 'Claude resumed request rejected: '+str(error)) from error
