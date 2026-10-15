"""Claude SDK/MCP binding. Claude's native CLI owns the execution loop."""
from __future__ import annotations

from dataclasses import asdict
import asyncio
import time
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher,
    PermissionResultAllow, PermissionResultDeny, ResultMessage,
    create_sdk_mcp_server, tool)

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding
from .claude_state import ClaudeState
from .providers.claude_transport import OfflineClaudeTransport
from ..application.runtime import RuntimeJournal, run_once
from ..contracts.common import CatalogError, canonical, digest
from ..contracts.query import parse
from ..contracts.run import RuntimeLimits


def make_options(profile, binding, *, cwd, cli_path, max_turns):
    profile.validate(kernel='claude')
    if not Path(cwd).is_absolute() or not Path(cli_path).is_absolute():
        raise ValueError('absolute isolated cwd and installed CLI path required')
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise ValueError('positive explicit SDK max_turns required')
    handlers = []
    pending = {}
    for name, envelope in ENVELOPES.items():
        async def invoke(arguments, name=name):
            identity = digest(canonical(dict(name=name, arguments=arguments)))
            call_id = pending.pop(identity, None)
            if binding.journal is not None and call_id is None:
                raise CatalogError('RECOVERY_REQUIRED', 'MCP invocation has no unambiguous native tool identity')
            output = await binding.invoke(name, arguments, call_id=call_id)
            value = json.loads(output)
            return dict(content=[dict(type='text', text=output)], is_error=value.get('status') == 'error')
        handlers.append(tool(name, DESCRIPTIONS[name], envelope.model_json_schema())(invoke))
    permitted = {'mcp__data__'+name for name in ENVELOPES}

    async def permission(name, arguments, context):
        if name in permitted and binding.terminal is None:
            return PermissionResultAllow(updated_input=arguments)
        return PermissionResultDeny(message='Outside the Data Agent tool scope')

    async def pre_tool(event, tool_use_id, context):
        if event.get('tool_name') not in permitted or binding.terminal is not None:
            return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'Only the bounded Data tools may execute before delivery'}}
        if binding.journal is not None:
            try:
                if event.get('session_id') != binding.journal.state()['native_session_id']:
                    raise CatalogError('INVALID_STATE', 'native session differs from the persisted binding')
                name = event['tool_name'].removeprefix('mcp__data__')
                args = event['tool_input']
                identity = digest(canonical(dict(name=name, arguments=args)))
                if identity in pending and pending[identity] != tool_use_id:
                    raise CatalogError('INVALID_STATE', 'identical concurrent native tool calls cannot be disambiguated')
                binding.journal.tool_key(tool_use_id, name, args)
                pending[identity] = tool_use_id
            except (CatalogError,ValueError) as error:
                binding.events.append(dict(type='native_tool_denied', tool_use_id=tool_use_id, reason=str(error)))
                return {'hookSpecificOutput': {'hookEventName':'PreToolUse','permissionDecision':'deny',
                    'permissionDecisionReason':str(error)}}
        return {}

    async def post_tool(event, tool_use_id, context):
        if binding.journal is not None:
            binding.journal.checkpoint('claude_post_tool')
        if event.get('tool_name') in {'mcp__data__deliver','mcp__data__clarify'} and binding.terminal is not None:
            # A successful MCP handler alone is not a business terminal. Only
            # the immutable DataService delivery permits this native stop.
            binding.terminal_requested = True
            binding.events.append(dict(type='native_stop_requested', boundary='claude_PostToolUse',
                                       tool_use_id=tool_use_id, reason='validated_'+binding.terminal['kind']))
            return {'continue_': False, 'stopReason': 'Validated Data Agent terminal control committed'}
        return {}

    return ClaudeAgentOptions(model=profile.profile.model_id, fallback_model=None,
        system_prompt=profile.text, tools=[], allowed_tools=[], permission_mode='default',
        mcp_servers={'data': create_sdk_mcp_server('data', version='1.0.0', tools=handlers)},
        strict_mcp_config=True, can_use_tool=permission,
        hooks={'PreToolUse': [HookMatcher(hooks=[pre_tool])],
               'PostToolUse': [HookMatcher(hooks=[post_tool])]},
        setting_sources=[], skills=[], plugins=[], cwd=cwd, cli_path=cli_path,
        max_turns=max_turns, effort=profile.profile.reasoning_effort,
        thinking={'type': 'disabled'} if profile.profile.reasoning_effort is None else {'type': 'adaptive'})


async def run_offline(service, context_ref, profile, *, cwd, cli_path, limits, transport=None, checkpoint=None, recover=False, started=None):
    started=time.monotonic() if started is None else started
    profile.validate(kernel='claude')
    limits = parse(RuntimeLimits, limits).model_dump(mode='json')
    return await run_once(service, context_ref, dict(profile=profile.metadata(), limits=limits),
        lambda attach: _run_offline(service,context_ref,profile,cwd=cwd,cli_path=cli_path,
            limits=limits,transport=transport,checkpoint=checkpoint,recover=recover,started=started,attach=attach))


async def _run_offline(service, context_ref, profile, *, cwd, cli_path, limits, transport=None, checkpoint=None, recover=False, started=None, attach=None):
    """Caller supplies an isolated worker with loopback fixture or scripted Transport.

    No live credential/config loading or implicit provider construction occurs.
    The native HTTP boundary is durably gated before every forwarded request.
    """
    profile.validate(kernel='claude')
    if transport is not None:
        raise ValueError('scripted CLI transport cannot replace the native HTTP metering boundary; use the separate M0 probe')
    if transport is None:
        endpoint = urlsplit(os.environ.get('ANTHROPIC_BASE_URL', ''))
        allowed_env = {'PATH','LANG','PYTHONNOUSERSITE','CLAUDE_CONFIG_DIR',
            'ANTHROPIC_BASE_URL','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC','CLAUDE_CODE_MAX_OUTPUT_TOKENS',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','LC_CTYPE','__CF_USER_TEXT_ENCODING'}
        if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or not endpoint.port
                or endpoint.username is not None or endpoint.query or endpoint.fragment
                or set(os.environ) - allowed_env
                or os.environ.get('ANTHROPIC_AUTH_TOKEN') != 'uteki-offline-fixture'
                or os.environ.get('ANTHROPIC_API_KEY') != ''
                or any(os.environ.get(k) != os.environ['ANTHROPIC_BASE_URL'] for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'))
                or Path(os.environ.get('CLAUDE_CONFIG_DIR', '')).resolve() != (Path(cwd)/'claude-config').resolve()
                or os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS') != str(profile.profile.max_output_tokens)):
            raise ValueError('native offline execution requires an isolated loopback-only worker environment; unexpected variable names: '+','.join(sorted(set(os.environ)-allowed_env)))
    journal = RuntimeJournal(service, context_ref, profile.metadata(), limits,recover=recover,checkpoint=checkpoint,started=started)
    if attach is not None:attach(journal)
    if journal.cached is not None:
        return journal.cached
    journal.checkpoint = checkpoint or (lambda phase: None)
    binding = bridge = None
    events, terminal, error, error_code = [], None, None, None
    def observe_wire(request):
        for message in request.get('messages', []):
            blocks = message.get('content', [])
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if block.get('type') != 'tool_result':
                    continue
                content = block.get('content', '')
                pieces = [content] if isinstance(content,str) else [p.get('text','') for p in content if p.get('type')=='text']
                for piece in pieces:
                    binding.observe(piece, boundary='claude_forwarded_native_request')
    try:
        journal.guard_transport()
        binding = ToolBinding(service, context_ref, journal=journal)
        options = make_options(profile, binding, cwd=cwd, cli_path=cli_path, max_turns=journal.limits.native_max_turns)
        if journal.resuming:
            options.resume = journal.state()['native_session_id']
        else:
            options.session_id = journal.state()['native_session_id']
        state = ClaudeState(journal, binding, cwd=cwd, cli_path=cli_path)
        bridge = OfflineClaudeTransport(journal, os.environ['ANTHROPIC_BASE_URL'],
            before_request=journal.guard_action, observed_request=observe_wire, validate_request=state.validate_request)
        async with bridge:
            prompt = state.prepare()
            journal.begin_continuation()
            options.env = {k:bridge.base_url for k in ('ANTHROPIC_BASE_URL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')}
            options.env['ANTHROPIC_AUTH_TOKEN'] = bridge.token
            async with ClaudeSDKClient(options=options) as client:
                try:
                    await client.query(prompt)
                    async for message in client.receive_response():
                        if isinstance(message, AssistantMessage):
                            state.record_assistant(message)
                        events.append(dict(type=type(message).__name__, data=asdict(message)))
                        if isinstance(message, ResultMessage):
                            terminal = message
                except asyncio.CancelledError:
                    journal.stop('cancelled')
                    raise
    except asyncio.CancelledError:
        journal.stop('cancelled')
        error = 'CANCELLED'
    except Exception as exc:
        error_code = getattr(exc,'code',None)
        error = type(exc).__name__+': '+str(exc)
    events.append(dict(type='native_transport', requests=bridge.events if bridge is not None else []))
    if terminal is not None and terminal.subtype == 'error_max_turns':
        journal.stop('native_max_turns')
    success = (terminal is not None and not terminal.is_error and terminal.subtype == 'success'
               and terminal.session_id == journal.state()['native_session_id'] and error is None)
    outcome=(binding.outcome(native_success=success,events=events,profile=profile,error=error,error_code=error_code)
        if binding is not None else journal.failure_outcome(error,error_code=error_code,events=events))
    return journal.finish(outcome)
