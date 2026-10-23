"""Actual installed SDK serialization, with synthetic responses and no inference."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

import httpx2
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel, Runner, RunConfig, ModelTracing, ModelSettings
from uteki.data_platform.agent.providers.gateway_openai import GatewayOpenAIModel, _Transport
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.agent.openai_runtime import make_agent, make_run_config
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
from uteki.data_platform.agent.binding import ENVELOPES, ToolBinding

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT/'config/data_platform'


def stub_binding(**fields):
    # Serialization stubs expose the production shared (non-document) tool projection.
    binding = SimpleNamespace(envelopes=ENVELOPES, document_mode=False, **fields)
    binding.tool_schema = lambda name: ToolBinding.tool_schema(binding, name)
    binding.tool_description = lambda name: ToolBinding.tool_description(binding, name)
    return binding


def loaded(kernel, lane):
    relative = f'model-profiles/{kernel}/live-{lane}/query.json'
    value = json.loads((CONFIG/relative).read_text())
    return load_profile(CONFIG/relative, config_root=CONFIG, kernel=kernel, model_id=value['model_id'], role='query')


def save(name, value):
    target = os.environ.get('UTEKI_LIVE_CAPTURE_EVIDENCE')
    if target:
        root = Path(target); root.mkdir(parents=True, exist_ok=True)
        (root/(name+'.json')).write_text(json.dumps(value, indent=2)+'\n')


class LiveCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_provider_parallel_parameter_keeps_native_tools_serial(self):
        profile = loaded('openai', 'C-luna-openai')
        requests, events = [], []
        active = maximum = 0

        async def invoke(name, arguments, *, call_id):
            nonlocal active, maximum
            active += 1; maximum = max(maximum, active)
            events.append(('start', call_id))
            await asyncio.sleep(.03)
            events.append(('end', call_id)); active -= 1
            return json.dumps({'call_id': call_id})

        async def handle(request):
            body = json.loads(await request.aread()); requests.append(body)
            message = dict(role='assistant', content='done')
            finish = 'stop'
            if len(requests) == 1:
                message = dict(role='assistant', content=None, tool_calls=[
                    dict(id=f'call-{n}', type='function',
                         function=dict(name='find_assets', arguments='{}')) for n in (1, 2)])
                finish = 'tool_calls'
            return httpx2.Response(200, json=dict(id=f'capture-{len(requests)}', object='chat.completion',
                created=1, model=profile.profile.model_id, choices=[dict(index=0,
                finish_reason=finish, message=message)],
                usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)))

        async with AsyncOpenAI(api_key='synthetic', base_url='http://capture.invalid/v1', max_retries=0,
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as client:
            model = OpenAIChatCompletionsModel(model=profile.profile.model_id, openai_client=client)
            model.gateway_metered = True
            agent = make_agent(profile, stub_binding(terminal=None, invoke=invoke), model, mode='gateway')
            result = await Runner.run(agent, 'Synthetic parallel calls.', max_turns=3,
                                      run_config=make_run_config())
            self.assertEqual(len(result.interruptions), 2)
            self.assertEqual(events, [])
            state = result.to_state()
            for interruption in state.get_interruptions(): state.approve(interruption)
            result = await Runner.run(agent, state, max_turns=3, run_config=make_run_config())
        self.assertEqual(result.final_output, 'done')
        self.assertEqual(maximum, 1)
        self.assertEqual(events, [('start', 'call-1'), ('end', 'call-1'), ('start', 'call-2'), ('end', 'call-2')])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all('parallel_tool_calls' not in r for r in requests))
        self.assertEqual([m['tool_call_id'] for m in requests[1]['messages'] if m['role']=='tool'], ['call-1', 'call-2'])

    async def test_profile_omission_is_frozen_and_gateway_rejects_reintroduced_parameter(self):
        luna = loaded('openai', 'C-luna-openai')
        self.assertIsNone(luna.metadata()['parallel_tool_calls'])
        deepseek = loaded('openai', 'A-deepseek-openai')
        self.assertNotIn('parallel_tool_calls', deepseek.metadata())
        with self.assertRaisesRegex(ValueError, 'requires an explicit OpenRouter Chat profile'):
            type(deepseek.profile).model_validate_json(json.dumps(deepseek.metadata() | {'parallel_tool_calls': None}))
        wire = GatewayHTTP.__new__(GatewayHTTP)
        wire.guard = lambda: None
        wire.profile = luna.metadata(); wire.path = '/v1/chat/completions'
        wire.protocol = 'chat_completions'; wire.transport = {'max_request_bytes': 10000}
        body = dict(model=luna.profile.model_id, max_tokens=4096, reasoning={'effort':'low'},
            provider=dict(only=['openai'], order=['openai'], allow_fallbacks=False, require_parameters=True))
        self.assertEqual(wire.validate_request(wire.path, json.dumps(body).encode(), {}), body)
        for value in (False, True, None):
            with self.assertRaisesRegex(ValueError, 'gateway_parallel_tool_omission_differs'):
                wire.validate_request(wire.path, json.dumps(body | {'parallel_tool_calls':value}).encode(), {})

    async def test_local_admission_failure_is_not_reported_as_network_failure(self):
        def reject(*args):
            raise ValueError('gateway_request_exceeds_bound')
        journal = SimpleNamespace(guard_action=lambda:None, deadline=__import__('time').monotonic()+30,
                                  profile={'route':{'provider':'deepseek'}})
        model = GatewayOpenAIModel.__new__(GatewayOpenAIModel)
        model.journal = journal
        model.state = SimpleNamespace(journal=journal,request=lambda request:('unsent-intent',None))
        model.wire = SimpleNamespace(validate_request=reject)
        async with AsyncOpenAI(api_key='synthetic', base_url='http://uteki-gateway.invalid/v1',
                max_retries=0, http_client=httpx2.AsyncClient(transport=_Transport(model))) as client:
            model.inner = OpenAIChatCompletionsModel(model='deepseek-flash', openai_client=client)
            with self.assertRaisesRegex(CatalogError, 'INVALID_REQUEST: native request rejected before dispatch: gateway_request_exceeds_bound'):
                await model.get_response('Local validation.', 'payload', ModelSettings(), [], None, [], ModelTracing.DISABLED)

    async def test_openai_sdk_serializes_each_explicit_provider_profile(self):
        for lane in ('A-deepseek-openai','C-luna-openai','D-sonnet-openai'):
            profile = loaded('openai', lane)
            requests = []
            async def handle(request):
                body = json.loads(await request.aread()); requests.append(body)
                return httpx2.Response(200, json=dict(id='capture', object='chat.completion', created=1,
                    model=profile.profile.model_id, choices=[dict(index=0, finish_reason='stop',
                    message=dict(role='assistant', content='Local capture only'))],
                    usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)))
            async with AsyncOpenAI(api_key='synthetic', base_url='http://capture.invalid/v1', max_retries=0,
                    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as client:
                model = OpenAIChatCompletionsModel(model=profile.profile.model_id, openai_client=client)
                model.gateway_metered = True
                binding = stub_binding(terminal=None)
                agent = make_agent(profile, binding, model, mode='gateway')
                await Runner.run(agent, 'Local serialization capture only.', max_turns=1,
                                 run_config=RunConfig(tracing_disabled=True))
            save(lane, dict(requests=requests, real_model_calls=0))
            self.assertEqual(len(requests), 1)
            body = requests[0]
            self.assertEqual(body['model'], profile.profile.model_id)
            self.assertEqual(body['messages'][0]['content'], profile.text)
            self.assertEqual(len(body['tools']), 8)
            self.assertEqual(body['max_tokens'], 4096)
            for key, value in profile.profile.request_controls.items(): self.assertEqual(body[key], value)
            if profile.profile.route.provider == 'deepseek': self.assertNotIn('provider', body)
            else:
                self.assertEqual(body['provider']['only'], list(profile.profile.route.upstream))
                self.assertFalse(body['provider']['allow_fallbacks'])
                self.assertTrue(body['provider']['require_parameters'])
                self.assertNotIn('store', body)
                if lane in ('C-luna-openai', 'D-sonnet-openai'): self.assertNotIn('parallel_tool_calls', body)
                else: self.assertFalse(body['parallel_tool_calls'])

    async def test_claude_native_cli_serializes_deepseek_effort(self):
        profile = loaded('claude', 'B-deepseek-claude')
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_CONNECT(self): self.send_error(403)
            def do_GET(self): self.send_error(403)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                events = [dict(type='message_start', message=dict(id='msg_capture', type='message',
                    role='assistant', model=profile.profile.model_id, content=[], stop_reason=None,
                    stop_sequence=None, usage=dict(input_tokens=10, output_tokens=1))),
                    dict(type='content_block_start', index=0, content_block=dict(type='text', text='')),
                    dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text='Capture complete')),
                    dict(type='content_block_stop', index=0),
                    dict(type='message_delta', delta=dict(stop_reason='end_turn', stop_sequence=None), usage=dict(output_tokens=3)),
                    dict(type='message_stop')]
                raw=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200); self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix='uteki-live-capture-') as temporary:
                work = Path(temporary)
                url = 'http://127.0.0.1:'+str(server.server_port)
                env = dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='C.UTF-8', PYTHONNOUSERSITE='1',
                    CLAUDE_CONFIG_DIR=str(work/'claude-config'), ANTHROPIC_BASE_URL=url, ANTHROPIC_API_KEY='',
                    ANTHROPIC_AUTH_TOKEN='synthetic', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                    CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096', HTTP_PROXY=url, HTTPS_PROXY=url, ALL_PROXY=url,
                    NO_PROXY='127.0.0.1,localhost')
                command = [sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_sdk_worker.py'),
                    str(CONFIG),str(work/'result.json'),'model-profiles/claude/live-B-deepseek-claude/query.json']
                result = await asyncio.to_thread(subprocess.run, command, cwd=work, env=env,
                    capture_output=True, text=True, timeout=50)
                save('B-deepseek-claude', dict(requests=requests, returncode=result.returncode,
                    stderr=result.stderr, real_model_calls=0))
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(len(requests),1)
                body=requests[0]
                self.assertEqual(body['model'],'deepseek-flash')
                self.assertEqual(body['max_tokens'],4096)
                self.assertEqual(body.get('output_config'), {'effort':'low'})
                self.assertEqual(len(body['tools']),8)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
