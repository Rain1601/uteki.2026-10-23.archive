"""Runnable offline probe using official SDKs and explicitly synthetic peers.

The OpenAI Model supplies scripted model responses. The Claude Transport is a
scripted CLI peer exercising the real SDK MCP bridge; it is NOT a Claude CLI
or model implementation and provides no evidence of live model compatibility.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from agents import Model, ModelResponse, Usage
from claude_agent_sdk import Transport
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from .adapters import claude_options, run_claude, run_openai
from .contracts import FixtureStore
from .profiles import load_profile

PINNED = {'openai-agents': '0.22.2', 'openai': '3.13.0', 'claude-agent-sdk': '0.2.166', 'mcp': '2.2.0'}


@contextmanager
def no_external_io():
    """Turn accidental network or subprocess use in this harness into a failure."""
    with ExitStack() as stack:
        for name in ['socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto',
                     'socket.create_connection', 'socket.getaddrinfo', 'subprocess.Popen']:
            stack.enter_context(patch(name, side_effect=AssertionError('external I/O forbidden in offline probe')))
        yield


def _delivery(tool_result, invalid=False):
    if not tool_result or tool_result.get('status') != 'ok':
        return {'result_ref': 'unread', 'value': '0', 'unit': 'invented'}
    return {'result_ref': 'unread' if invalid else tool_result['result_ref'],
            'value': tool_result['value'], 'unit': tool_result['unit']}


class ScriptedModel(Model):
    def __init__(self, requests, *, invalid=False, wait=False):
        self.requests = requests
        self.invalid, self.wait = invalid, wait
        self.calls = 0
        self.inputs = []
        self.entered = asyncio.Event()

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):
        self.entered.set()
        if self.wait:
            await asyncio.Event().wait()
        self.inputs.append(input)
        index = self.calls
        self.calls += 1
        if index < len(self.requests):
            output = [ResponseFunctionToolCall(type='function_call', name='read_fixture',
                        arguments=json.dumps(self.requests[index]), call_id=f'fixture-call-{index}',
                        id=f'fixture-tool-{index}')]
        else:
            outputs = [json.loads(item['output']) for item in input
                       if isinstance(item, dict) and item.get('type') == 'function_call_output']
            self.last_tool_result = outputs[-1] if outputs else None
            value = _delivery(self.last_tool_result, self.invalid)
            output = [ResponseOutputMessage(id='fixture-final', type='message', role='assistant',
                      status='completed', content=[ResponseOutputText(type='output_text',
                      text=json.dumps(value), annotations=[])])]
        return ModelResponse(output=output, usage=Usage(requests=1),
                             response_id=f'fixture-response-{index}', raw_usage=None)

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError('streaming is outside this offline fixture')
        yield  # pragma: no cover


class ScriptedCLI(Transport):
    """Test double at the SDK's documented Transport seam, not a production loop."""
    def __init__(self, arguments, *, invalid=False, missing_terminal=False,
                 cancelled=False, fatal=False, native_usage=None, native_cost=None):
        self.arguments = arguments
        self.invalid, self.missing_terminal = invalid, missing_terminal
        self.cancelled, self.fatal = cancelled, fatal
        self.native_usage, self.native_cost = native_usage, native_cost
        self.queue = asyncio.Queue()
        self.ready = False
        self.closed = False
        self.writes = []
        self.mcp_results = []
        self.entered = asyncio.Event()

    async def connect(self):
        self.ready = True

    def is_ready(self):
        return self.ready

    async def close(self):
        self.closed, self.ready = True, False
        await self.queue.put(None)

    async def end_input(self):
        pass

    async def read_messages(self):
        while True:
            value = await self.queue.get()
            if value is None:
                return
            yield value

    async def mcp(self, stage, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if method != 'notifications/initialized':
            message['id'] = stage
        if params is not None:
            message['params'] = params
        await self.queue.put({'type': 'control_request', 'request_id': stage,
            'request': {'subtype': 'mcp_message', 'server_name': 'fixture', 'message': message}})

    async def terminal(self, output=None, *, cancelled=False):
        result = {'type': 'result', 'subtype': 'error_during_execution' if self.fatal else 'success',
                  'duration_ms': 0, 'duration_api_ms': 0, 'is_error': self.fatal,
                  'num_turns': 0 if cancelled else 2,
                  'session_id': 'fixture-session-only', 'structured_output': output,
                  'terminal_reason': 'aborted_tools' if cancelled else 'completed'}
        if self.native_usage is not None:
            result['usage'] = self.native_usage
        if self.native_cost is not None:
            result['total_cost_usd'] = self.native_cost
        await self.queue.put(result)

    async def write(self, data):
        message = json.loads(data)
        self.writes.append(message)
        if message['type'] == 'control_request':
            subtype = message['request']['subtype']
            await self.queue.put({'type': 'control_response', 'response': {
                'subtype': 'success', 'request_id': message['request_id'],
                'response': {'commands': [], 'models': []} if subtype == 'initialize' else {}}})
            if subtype == 'interrupt':
                await self.terminal(cancelled=True)
        elif message['type'] == 'user':
            self.entered.set()
            if self.cancelled:
                return
            await self.mcp('mcp-init', 'initialize', {'protocolVersion': '2025-06-18',
                'capabilities': {}, 'clientInfo': {'name': 'offline-cli-peer', 'version': '1'}})
        elif message['type'] == 'control_response':
            response = message['response']
            if response['subtype'] != 'success':
                raise AssertionError('SDK control request failed')
            stage = response['request_id']
            if stage == 'permission-tool':
                decision = response['response']
                assert decision['behavior'] == 'allow'
                await self.mcp('mcp-call', 'tools/call', {'name': 'read_fixture', 'arguments': decision['updatedInput']})
                return
            result = response['response']['mcp_response']
            if 'error' in result:
                raise AssertionError('SDK MCP request failed: ' + json.dumps(result['error']))
            if stage == 'mcp-init':
                await self.mcp('mcp-ready', 'notifications/initialized')
            elif stage == 'mcp-ready':
                await self.mcp('mcp-list', 'tools/list')
            elif stage == 'mcp-list':
                self.listed_tools = result['result']['tools']
                await self.queue.put({'type': 'control_request', 'request_id': 'permission-tool',
                    'request': {'subtype': 'can_use_tool', 'tool_name': 'mcp__fixture__read_fixture',
                                'input': self.arguments, 'tool_use_id': 'fixture-tool'}})
            elif stage == 'mcp-call':
                body = result['result']
                self.mcp_results.append(body)
                text = next(c['text'] for c in body['content'] if c['type'] == 'text')
                try:
                    tool_result = json.loads(text)
                except ValueError:
                    tool_result = None
                if self.missing_terminal:
                    await self.queue.put(None)
                else:
                    await self.terminal(_delivery(tool_result, self.invalid))


async def exercise(fixture_path: Path, profile_directory: Path, work: Path):
    import claude_agent_sdk
    raw = fixture_path.read_bytes()
    openai_profile = load_profile(profile_directory / 'openai-claude.json',
                                   model_id='fixture/claude-v1', kernel='openai')
    claude_profile = load_profile(profile_directory / 'claude-claude.json',
                                   model_id='fixture/claude-v1', kernel='claude')
    cli_path = Path(claude_agent_sdk.__file__).parent / '_bundled/claude'
    reports = {}
    for scenario in ('success', 'tool_error', 'invalid_delivery', 'missing_terminal', 'cancel'):
        for kernel, profile in [('openai', openai_profile), ('claude', claude_profile)]:
            if kernel == 'openai' and scenario == 'missing_terminal':
                continue
            store = FixtureStore(raw)
            arguments = {'record_id': 'absent' if scenario == 'tool_error' else 'alpha',
                         'snapshot_sha256': store.snapshot_sha256}
            prompt = 'Read this synthetic fixture record: ' + json.dumps(arguments)
            if kernel == 'openai':
                peer = ScriptedModel([arguments], invalid=scenario == 'invalid_delivery', wait=scenario == 'cancel')
                task = asyncio.create_task(run_openai(profile, store, peer, prompt))
                if scenario == 'cancel':
                    await peer.entered.wait()
                    task.cancel()
                outcome = await task
            else:
                peer = ScriptedCLI(arguments, invalid=scenario == 'invalid_delivery',
                                    missing_terminal=scenario == 'missing_terminal', cancelled=scenario == 'cancel')
                options = claude_options(profile, store, cwd=work, cli_path=cli_path, path_environment='/usr/bin:/bin')
                cancel = asyncio.Event()
                task = asyncio.create_task(run_claude(options, store, prompt, transport=peer,
                                                       cancel_event=cancel))
                if scenario == 'cancel':
                    await peer.entered.wait()
                    cancel.set()
                outcome = await task
            expected = {'success': 'completed', 'tool_error': 'invalid_delivery',
                        'invalid_delivery': 'invalid_delivery', 'missing_terminal': 'missing_terminal',
                        'cancel': 'cancelled'}[scenario]
            passed = (outcome.status == expected and outcome.gateway_cost_usd is None
                      and (kernel != 'claude' or peer.closed))
            reports[f'{kernel}/{scenario}'] = {**asdict(outcome), 'tool_calls': len(store.calls),
                                              'expected_status': expected, 'passed': passed}
    return {'mode': 'offline_synthetic', 'passed': all(r['passed'] for r in reports.values()),
            'model_api_calls': 0, 'native_cli_runs': 0,
            'versions': {package: importlib.metadata.version(package) for package in PINNED},
            'bundled_cli_sha256': hashlib.sha256(cli_path.read_bytes()).hexdigest(),
            'fixture_sha256': hashlib.sha256(raw).hexdigest(),
            'prompt_profiles': [asdict(openai_profile), asdict(claude_profile)],
            'scenarios': reports,
            'limitations': ['OpenAI Runner used scripted Model responses',
                           'Claude SDK used a scripted CLI Transport; native CLI loop not run',
                           'No live model, provider routing, gateway bill, skills, memory or resume acceptance',
                           'Tool return validation is not a proof of model understanding or full production evidence visibility']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    versions = {package: importlib.metadata.version(package) for package in PINNED}
    if versions != PINNED:
        raise SystemExit('SDK version mismatch; install requirements/m0.txt')
    if args.output.exists():
        raise SystemExit('Output already exists; preserve previous evidence and use a new path')
    with tempfile.TemporaryDirectory(prefix='uteki-m0-') as directory, no_external_io():
        report = asyncio.run(asyncio.wait_for(exercise(args.fixture, args.profiles, Path(directory)), timeout=30))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': 'passed' if report['passed'] else 'failed',
                      'scenarios': len(report['scenarios']), 'model_api_calls': 0}))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
