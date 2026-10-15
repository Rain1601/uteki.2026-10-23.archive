"""Thin official-SDK wiring for M0. The SDKs own execution and tool dispatch."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from pathlib import Path

import anyio
from agents import Agent, FunctionTool, ModelSettings, RunConfig, RunHooks, Runner
from agents.retry import ModelRetrySettings
from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, PermissionResultDeny,
                             ResultMessage, create_sdk_mcp_server, tool)

from .contracts import Delivery, FixtureStore, ProbeOutcome, ReadRequest, finish
from .profiles import OPENROUTER_OPENAI_URL, PromptProfile, worker_environment

TOOL_DESCRIPTION = 'Read one caller-supplied synthetic record at the exact snapshot hash. Read-only; errors do not contain facts.'


def openai_agent(profile: PromptProfile, store: FixtureStore, model) -> Agent:
    if profile.kernel != 'openai':
        raise ValueError('wrong kernel profile')

    async def read(_context, arguments: str):
        try:
            values = json.loads(arguments)
        except (ValueError, TypeError):
            return json.dumps({'status': 'error', 'code': 'invalid_arguments'})
        return json.dumps(store.read(values))

    return Agent(name='M0 read-only probe', instructions=profile.text, model=model,
        tools=[FunctionTool(name='read_fixture', description=TOOL_DESCRIPTION,
                            params_json_schema=ReadRequest.model_json_schema(), on_invoke_tool=read)],
        output_type=Delivery, model_settings=ModelSettings(store=False, preserve_raw_usage=True,
                                                        retry=ModelRetrySettings(max_retries=0)))


def openrouter_chat_model(profile: PromptProfile, *, api_key: str):
    """Official client/model construction only; no request or credential discovery.

    The shipped profiles are fixture-only. A live runner and gateway budget/route
    verification are intentionally not exposed by the M0 command.
    """
    from openai import AsyncOpenAI
    from agents import OpenAIChatCompletionsModel
    if profile.kernel != 'openai' or not api_key:
        raise ValueError('explicit OpenAI-kernel profile and key required')
    client = AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_OPENAI_URL,
                         max_retries=0, timeout=20)
    return OpenAIChatCompletionsModel(model=profile.model_id, openai_client=client), client


class _Responses(RunHooks):
    def __init__(self):
        self.responses = []

    async def on_llm_end(self, context, agent, response):
        self.responses.append(response)


async def run_openai(profile, store, model, prompt: str, *, max_turns: int = 3):
    observer = _Responses()
    agent = openai_agent(profile, store, model)
    result = None
    status, reason = None, None
    try:
        result = await Runner.run(agent, prompt, hooks=observer, max_turns=max_turns,
                                  run_config=RunConfig(tracing_disabled=True))
    except asyncio.CancelledError:
        status, reason = 'cancelled', 'caller_cancelled'
    except Exception as error:
        status, reason = 'error', type(error).__name__
    metadata = {'native_usage': [r.raw_usage for r in observer.responses],
                'native_events': [{'type': 'model_response', 'response_id': r.response_id,
                                   'raw_usage': r.raw_usage,
                                   'output': [item.model_dump(mode='json') for item in r.output]}
                                  for r in observer.responses]}
    if status:
        return ProbeOutcome('openai', status, reason=reason, **metadata)
    # Native completion is necessary but insufficient for business completion.
    output = result.final_output
    if isinstance(output, Delivery):
        output = output.model_dump()
    return finish('openai', store, output, **metadata)


def claude_options(profile: PromptProfile, store: FixtureStore, *, cwd: Path,
                   cli_path: Path, path_environment: str) -> ClaudeAgentOptions:
    if profile.kernel != 'claude' or not cwd.is_absolute() or not cli_path.is_absolute():
        raise ValueError('explicit Claude profile, working directory and CLI required')

    @tool('read_fixture', TOOL_DESCRIPTION, ReadRequest.model_json_schema())
    async def read(arguments):
        value = store.read(arguments)
        return {'content': [{'type': 'text', 'text': json.dumps(value)}],
                'is_error': value['status'] != 'ok'}

    async def check_tool(name, arguments, context):
        if name == 'mcp__fixture__read_fixture':
            return PermissionResultAllow(updated_input=arguments)
        return PermissionResultDeny(message='Outside the M0 read-only tool scope')

    return ClaudeAgentOptions(
        model=profile.model_id, fallback_model=None,
        system_prompt={'type': 'preset', 'preset': 'claude_code', 'append': profile.text},
        tools=[], allowed_tools=[],
        mcp_servers={'fixture': create_sdk_mcp_server('fixture', version='1.0.0', tools=[read])},
        strict_mcp_config=True, can_use_tool=check_tool,
        setting_sources=[], skills=[], plugins=[],
        cwd=cwd, cli_path=cli_path, max_turns=3,
        output_format={'type': 'json_schema', 'schema': Delivery.model_json_schema()},
        env=worker_environment(path=path_environment, config_directory=cwd / 'claude-config'))


async def run_claude(options, store, prompt: str, *, transport, cancel_event=None):
    """A supplied transport is mandatory here: the offline command cannot spawn CLI."""
    if transport is None:
        raise ValueError('M0 offline transport required; live runner is not enabled')
    messages = []
    terminal = None
    try:
        async with ClaudeSDKClient(options=options, transport=transport) as client:
            await client.query(prompt)
            async with anyio.create_task_group() as group:
                async def watch_cancel():
                    await cancel_event.wait()
                    await client.interrupt()

                if cancel_event is not None:
                    group.start_soon(watch_cancel)
                async for message in client.receive_response():
                    messages.append({'type': type(message).__name__, 'data': asdict(message)})
                    if isinstance(message, ResultMessage):
                        terminal = message
                group.cancel_scope.cancel()
    except asyncio.CancelledError:
        return ProbeOutcome('claude', 'cancelled', reason='caller_cancelled', native_events=messages)
    except Exception as error:
        return ProbeOutcome('claude', 'error', reason=type(error).__name__, native_events=messages)
    if terminal is None:
        return ProbeOutcome('claude', 'missing_terminal', reason='no_ResultMessage', native_events=messages)
    metadata = {'native_events': messages, 'native_usage': [terminal.usage],
                'native_cost_estimate_usd': terminal.total_cost_usd}
    if terminal.terminal_reason in {'aborted_streaming', 'aborted_tools'} or (cancel_event and cancel_event.is_set()):
        return ProbeOutcome('claude', 'cancelled', reason=terminal.terminal_reason or 'caller_cancelled', **metadata)
    if terminal.is_error or terminal.subtype != 'success':
        return ProbeOutcome('claude', 'error', reason=terminal.subtype, **metadata)
    return finish('claude', store, terminal.structured_output, **metadata)
