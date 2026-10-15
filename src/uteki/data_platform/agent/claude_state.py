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


class ClaudeState:
    """A binding and audit of public SDK messages, not an alternative SDK loop."""
    def __init__(self, journal, binding, *, cwd, cli_path):
        self.journal, self.binding = journal, binding
        self.cwd = str(Path(cwd).resolve())
        with Path(cli_path).open('rb') as stream:
            cli_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.identity = dict(sdk_version=version('claude-agent-sdk'), cli_sha256=cli_hash,
            cwd=self.cwd, config_dir=str(Path(os.environ['CLAUDE_CONFIG_DIR']).resolve()))
        self.expected_history = None

    def put(self, value):
        return self.journal.catalog.content.put_object(canonical(value)).model_dump(mode='json')

    def read(self, reference):
        raw = self.journal.catalog.content.read_object(ObjectRef.model_validate(reference))
        value = json.loads(raw)
        if canonical(value) != raw:
            raise ValueError('noncanonical Claude audit object')
        return value

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

    def _verify_response_coverage(self, assistants):
        # Inspect only the public protocol's message_start identity. The SDK
        # parses content; this does not reconstruct model output or replay SSE.
        expected = []
        for record in self.journal.budget.inspect_requests():
            if record['request']['context_ref'] != self.journal.context_ref:
                continue
            if record['stage'] != 'responded' or record['cost_state'] != 'settled':
                raise ValueError('native physical request is not confirmed')
            response = record['response_event']['response']
            if not response.get('complete') or response.get('status') != 200:
                raise ValueError('native model response is not complete and successful')
            raw = base64.b64decode(response['body_base64'], validate=True)
            if digest(raw) != response['body_sha256']:
                raise ValueError('saved native response bytes differ')
            starts = [event['message']['id'] for line in raw.splitlines() if line.startswith(b'data:')
                and (event := json.loads(line[5:])).get('type') == 'message_start']
            if len(starts) != 1:
                raise ValueError('native response lacks an unambiguous message identity')
            expected.extend(starts)
        actual = {m['message_id'] for m in assistants}
        if not expected or len(expected) != len(set(expected)) or set(expected) != actual:
            raise ValueError('native history does not cover every complete model response')

    def _verify_history(self, messages, saved, native):
        calls = {c['call_id']:c for c in native['tool_calls'].values()}
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
                    call = calls.get(block['id'])
                    name = block['name'].removeprefix('mcp__data__')
                    if (message['role'] != 'assistant' or call is None or block['id'] in used
                            or block['name'] != 'mcp__data__'+call['name']
                            or digest(canonical(dict(name=name, arguments=block['input']))) != call['fingerprint']):
                        raise ValueError('native tool invocation differs from the original business operation')
                    used.add(block['id'])
                elif kind == 'tool_result':
                    identity = block['tool_use_id']
                    call = calls.get(identity)
                    value = block.get('content')
                    if (message['role'] != 'user' or call is None or identity not in used or identity in returned
                            or call['status'] != 'completed' or call['output'] is None
                            or value != [dict(type='text', text=canonical(call['output']).decode())]
                            or bool(block.get('is_error', False)) != (call['output'].get('status') == 'error')):
                        raise ValueError('native tool result is missing, altered, pending or a cancellation substitute')
                    returned.add(identity)
        if used != set(calls) or returned != set(calls) or not used:
            raise ValueError('native tool history is incomplete')
        if not texts or texts[0] != self.read(saved['input_ref']) or any(t != CONTINUE_PROMPT for t in texts[1:]):
            raise ValueError('native user history differs from the original task or explicit continuations')

    def validate_request(self, request):
        if self.expected_history is None:
            return
        try:
            history = self.expected_history
            self._verify_history(request['messages'], history['saved'], history['native'])
            blocks = [dict((k,v) for k,v in b.items() if k != 'cache_control')
                for m in request['messages'] if m['role'] == 'assistant' for b in m['content']]
            # This pinned CLI inserts a synthetic conversational separator
            # after a finished tool turn on resume. It is not model output or
            # business evidence. Permit this exact trailing marker only; all
            # original assistant blocks and tool results still must match.
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
