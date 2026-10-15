"""Claude SDK/MCP binding. Claude's native CLI owns the execution loop."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, HookMatcher,
    PermissionResultAllow, PermissionResultDeny, ResultMessage, UserMessage,
    ToolResultBlock, create_sdk_mcp_server, tool)

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding


def make_options(profile, binding, *, cwd, cli_path, max_turns):
    profile.validate(kernel='claude')
    if not Path(cwd).is_absolute() or not Path(cli_path).is_absolute():
        raise ValueError('absolute isolated cwd and installed CLI path required')
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise ValueError('positive explicit SDK max_turns required')
    handlers = []
    for name, envelope in ENVELOPES.items():
        async def invoke(arguments, name=name):
            output = await binding.invoke(name, arguments)
            value = json.loads(output)
            return dict(content=[dict(type='text', text=output)], is_error=value.get('status') == 'error')
        handlers.append(tool(name, DESCRIPTIONS[name], envelope.model_json_schema())(invoke))
    permitted = {'mcp__data__'+name for name in ENVELOPES}

    async def permission(name, arguments, context):
        if name in permitted and binding.delivery is None:
            return PermissionResultAllow(updated_input=arguments)
        return PermissionResultDeny(message='Outside the Data Agent tool scope')

    async def pre_tool(event, tool_use_id, context):
        if event.get('tool_name') not in permitted or binding.delivery is not None:
            return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'Only the bounded Data tools may execute before delivery'}}
        return {}

    return ClaudeAgentOptions(model=profile.profile.model_id, fallback_model=None,
        system_prompt=profile.text, tools=[], allowed_tools=[], permission_mode='default',
        mcp_servers={'data': create_sdk_mcp_server('data', version='1.0.0', tools=handlers)},
        strict_mcp_config=True, can_use_tool=permission,
        hooks={'PreToolUse': [HookMatcher(hooks=[pre_tool])]},
        setting_sources=[], skills=[], plugins=[], cwd=cwd, cli_path=cli_path,
        max_turns=max_turns, effort=profile.profile.reasoning_effort,
        thinking={'type': 'disabled'} if profile.profile.reasoning_effort is None else {'type': 'adaptive'})


def observe_message(binding, message):
    if isinstance(message, UserMessage) and isinstance(message.content, list):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                content = block.content
                if isinstance(content, str):
                    binding.observe(content, boundary='claude_user_message_tool_result')
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            binding.observe(item.get('text'), boundary='claude_user_message_tool_result')


async def run_offline(service, context_ref, profile, *, cwd, cli_path, max_turns, transport=None):
    """Caller supplies an isolated worker with loopback fixture or scripted Transport.

    No live credential/config loading or implicit provider construction occurs
    here. Full durable cancellation, metering and recovery belong to step two.
    """
    profile.validate(kernel='claude')
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
    binding = ToolBinding(service, context_ref)
    options = make_options(profile, binding, cwd=cwd, cli_path=cli_path, max_turns=max_turns)
    events, terminal, error = [], None, None
    try:
        async with ClaudeSDKClient(options=options, transport=transport) as client:
            from ..contracts.common import canonical
            await client.query(canonical(binding.context).decode())
            async for message in client.receive_response():
                events.append(dict(type=type(message).__name__, data=asdict(message)))
                observe_message(binding, message)
                if isinstance(message, ResultMessage):
                    terminal = message
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
    success = terminal is not None and not terminal.is_error and terminal.subtype == 'success' and error is None
    return binding.outcome(native_success=success, events=events, profile=profile, error=error)
