"""Native Messages contracts through the real Runner; HTTP is always mocked."""
import asyncio
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.agent_output import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from agents.retry import ModelRetrySettings
import httpx2 as httpx
from pydantic import BaseModel

from uteki.agents.runtime.claude_messages import ClaudeMessagesModel, ENDPOINT
from uteki.agents.runtime.model_configuration import validate_configuration_snapshot


class Decision(BaseModel):
    action: str


def stream_events():
    return [
        {'type': 'message_start', 'message': {'id': 'msg_stream', 'type': 'message',
         'model': 'claude-opus-5-5', 'content': [],
         'usage': {'input_tokens': 100, 'output_tokens': 1, 'cache_read_input_tokens': 10}}},
        {'type': 'ping'},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': 'HIDDEN_INITIAL'}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'HIDDEN_REASONING'}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'HIDDEN_SIGNATURE'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '{"action":'}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '"inspect"}'}},
        {'type': 'content_block_stop', 'index': 1},
        {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 20}},
        {'type': 'message_stop'},
    ]


class MockWireBody(httpx.AsyncByteStream):
    def __init__(self, events, fail=None, delay=0):
        self.events, self.fail, self.delay = events, fail, delay

    async def __aiter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        for event in self.events:
            raw = ('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()
            # Exercise lines fragmented across transport reads.
            yield raw[:9]
            yield raw[9:]
        if self.fail:
            raise self.fail('PRIVATE_EXCEPTION offline-stream-key')


class ClaudeWireStreamingTests(unittest.TestCase):
    def invoke(self, root, *, events=None, stream=True, fail=None, delay=0, timeout=30, content_type='text/event-stream'):
        from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot
        from uteki.agents.runtime.run_budget import RunBudget
        self.requests = []
        async def respond(request):
            self.requests.append(request)
            return httpx.Response(200, headers={'request-id': 'req_early_headers', 'content-type': content_type,
                'private-header': 'DO_NOT_RETAIN'}, stream=MockWireBody(events if events is not None else stream_events(), fail, delay))
        def factory(**kwargs):
            kwargs['transport'] = httpx.MockTransport(respond)
            return httpx.AsyncClient(**kwargs)
        self.budget = RunBudget(root / 'budget.sqlite', '2')
        async def run():
            self.model = ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=timeout,
                                            stream=stream, client_factory=factory)
            try:
                model = MeteredModel(self.model, root / 'calls', 'offline_test', 'aihubmix',
                    'claude-opus-5-5', pricing_snapshot('aihubmix', 'claude-opus-5-5'), self.budget)
                return await model.get_response(system_instructions='Frozen system', input='Frozen packet',
                    model_settings=ModelSettings(max_tokens=100), tools=[], output_schema=None, handoffs=[])
            finally:
                await self.model.aclose()
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-stream-key'}):
            return asyncio.run(run())

    def test_complete_stream_accumulates_visible_text_and_final_cumulative_usage(self):
        from uteki.agents.runtime.call_costs import summarize
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.invoke(root)
            self.assertEqual(result.output[0].content[0].text, '{"action":"inspect"}')
            record = summarize(root / 'calls')['records'][0]
            self.assertEqual(record['raw_usage']['output_tokens'], 20)
            self.assertEqual(record['estimated_usd'], '0.000802')
            self.assertTrue(record['stream_complete'])
            self.assertTrue(record['headers_received'])
            self.assertEqual(record['transport_phase'], 'body_complete')
            self.assertEqual(record['request_id'], 'req_early_headers')
            self.assertGreaterEqual(record['headers_received_elapsed_seconds'], 0)
            self.assertTrue(json.loads(self.requests[0].content)['stream'])
            self.assertTrue(record['configuration_snapshot']['fields']['stream']['value'])
            retained = json.dumps(summarize(root / 'calls')) + self.model.response_text
            for private in ('HIDDEN_INITIAL', 'HIDDEN_REASONING', 'HIDDEN_SIGNATURE', 'offline-stream-key', 'DO_NOT_RETAIN'):
                self.assertNotIn(private, retained)
            self.assertEqual(len(self.requests), 1)

    def test_nonstream_body_failure_preserves_received_headers(self):
        from uteki.agents.runtime.call_costs import summarize
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError) as error:
                self.invoke(root, events=[], stream=False, fail=httpx.ReadError, content_type='application/json')
            self.assertIsNone(error.exception.__context__)
            row = summarize(root / 'calls')['records'][0]
            self.assertEqual(row['http_status'], 200)
            self.assertEqual(row['request_id'], 'req_early_headers')
            self.assertEqual(row['transport_phase'], 'reading_body')
            self.assertEqual(row['transport_error_type'], 'ReadError')
            self.assertIsNone(row['estimated_usd'])
            self.assertEqual(self.budget.summary()['unknown_requests'], 1)
            self.assertEqual(len(self.requests), 1)
            self.assertNotIn('PRIVATE_EXCEPTION', json.dumps(row))

    def test_partial_or_error_stream_never_settles_partial_usage_as_final(self):
        from uteki.agents.runtime.call_costs import summarize
        for ending in ('eof', 'read_error', 'provider_error'):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                events = stream_events()[:-2]
                fail = httpx.RemoteProtocolError if ending == 'read_error' else None
                if ending == 'provider_error':
                    events.append({'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'PRIVATE_PROVIDER_ERROR offline-stream-key'}})
                with self.assertRaises((RuntimeError, ModelBehaviorError)):
                    self.invoke(root, events=events, fail=fail)
                row = summarize(root / 'calls')['records'][0]
                self.assertFalse(row['stream_complete'])
                self.assertEqual(row['usage_presence'], 'partial')
                self.assertEqual(row['raw_usage']['output_tokens'], 1)
                self.assertIsNone(row['usage'])
                self.assertIsNone(row['estimated_usd'])
                self.assertEqual(row['request_id'], 'req_early_headers')
                self.assertEqual(self.model.response_text, '{"action":"inspect"}')
                self.assertEqual(self.budget.summary()['unknown_requests'], 1)
                self.assertEqual(len(self.requests), 1)
                for value in ('PRIVATE_PROVIDER_ERROR', 'PRIVATE_EXCEPTION', 'offline-stream-key', 'HIDDEN_REASONING'):
                    self.assertNotIn(value, json.dumps(row) + self.model.response_text)

    def test_complete_but_max_tokens_response_keeps_known_cost_without_delivering(self):
        from uteki.agents.runtime.call_costs import summarize
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); events = stream_events()
            events[-2]['delta']['stop_reason'] = 'max_tokens'
            with self.assertRaises(ModelBehaviorError):
                self.invoke(root, events=events)
            row = summarize(root / 'calls')['records'][0]
            self.assertTrue(row['stream_complete'])
            self.assertEqual(row['stop_reason'], 'max_tokens')
            self.assertEqual(row['estimated_usd'], '0.000802')
            self.assertEqual(row['status'], 'failed_or_cancelled')

    def test_missing_or_invalid_final_usage_is_not_zero(self):
        from uteki.agents.runtime.call_costs import summarize
        for change in ('missing_all', 'missing_final', 'invalid_final', 'decreasing_final'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); events = stream_events()
                if change == 'missing_all': events[0]['message'].pop('usage'); events[-2].pop('usage')
                if change == 'missing_final': events[-2].pop('usage')
                if change == 'invalid_final': events[-2]['usage']['output_tokens'] = True
                if change == 'decreasing_final': events[-2]['usage']['output_tokens'] = 0
                self.invoke(root, events=events)
                row = summarize(root / 'calls')['records'][0]
                self.assertIsNone(row['usage']); self.assertIsNone(row['estimated_usd'])
                self.assertEqual(self.budget.summary()['unknown_requests'], 1)

    def test_total_deadline_remains_bounded_after_receiving_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                self.invoke(Path(tmp), delay=.08, timeout=.02)
            self.assertTrue(self.model.response_metadata['headers_received'])
            self.assertEqual(self.model.response_metadata['transport_phase'], 'reading_stream')
            self.assertEqual(self.budget.summary()['unknown_requests'], 1)

    def test_invalid_stream_sequence_and_content_type_fail_closed(self):
        cases = [([{'type': 'message_stop'}], 'text/event-stream'),
                 (stream_events()[:-2] + [{'type': 'message_stop'}], 'text/event-stream'),
                 (stream_events(), 'application/json')]
        for events, content_type in cases:
            with self.subTest(content_type=content_type), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ModelBehaviorError):
                    self.invoke(Path(tmp), events=events, content_type=content_type)
                self.assertEqual(self.budget.summary()['unknown_requests'], 1)

    def test_transport_timeout_limits_and_boolean_are_explicit(self):
        ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=600, stream=True)
        for kwargs in ({'timeout_seconds': 600}, {'timeout_seconds': 601, 'stream': True},
                       {'timeout_seconds': 30, 'stream': 'true'}):
            with self.assertRaises(ValueError):
                ClaudeMessagesModel('claude-opus-5-5', **kwargs)

    def test_real_http11_chunked_stack_is_drained_without_asyncgen_shutdown_errors(self):
        """Use the actual HTTPX/httpcore parsers; only TCP I/O is replaced."""
        import httpcore2
        from httpcore2._backends.mock import AsyncMockBackend

        class TrackingBackend(AsyncMockBackend):
            async def connect_tcp(self, *args, **kwargs):
                self.last_stream = await super().connect_tcp(*args, **kwargs)
                return self.last_stream

        raw_chunks = []
        for event in stream_events():
            raw = ('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()
            raw_chunks.append(format(len(raw), 'x').encode() + b'\r\n' + raw + b'\r\n')
        backend = TrackingBackend([b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
            b'Transfer-Encoding: chunked\r\nRequest-Id: req_chunked\r\n\r\n', *raw_chunks, b'0\r\n\r\n'])
        errors = []
        async def run():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(lambda loop, context: errors.append(context))
            def factory(**kwargs):
                transport = httpx.AsyncHTTPTransport(retries=0)
                transport._pool = httpcore2.AsyncConnectionPool(network_backend=backend, retries=0)
                kwargs['transport'] = transport
                return httpx.AsyncClient(**kwargs)
            model = ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=30, stream=True, client_factory=factory)
            try:
                result = await model.get_response(system_instructions='Test system', input='Test packet',
                    model_settings=ModelSettings(max_tokens=100), tools=[], output_schema=None, handoffs=[])
                self.assertEqual(result.output[0].content[0].text, '{"action":"inspect"}')
            finally:
                await model.aclose()
            for _ in range(3):
                gc.collect()
                await asyncio.sleep(0)
            await loop.shutdown_asyncgens()
            await asyncio.sleep(0)
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-stream-key'}):
            asyncio.run(run())
        self.assertEqual(errors, [], 'No deferred generator-close errors may remain')
        self.assertEqual(backend.last_stream._buffer, [], 'HTTP chunk terminator must be consumed before returning')

    def test_events_after_message_stop_are_not_silently_accepted(self):
        for extra in ({'type': 'ping'}, {'type': 'message_stop'},
                      {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'extra'}}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ModelBehaviorError):
                    self.invoke(Path(tmp), events=stream_events() + [extra])
                self.assertEqual(self.model.response_metadata['stream_error_type'], 'event_after_message_stop')


class ClaudeMessagesTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.clients = []
        self.secret = 'offline-secret-key'
        self.payload = {'id': 'msg_test', 'model': 'claude-sonnet-5-5', 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 10},
            'content': [{'type': 'thinking', 'thinking': 'HIDDEN_THOUGHT', 'signature': 'HIDDEN_SIGNATURE'},
                        {'type': 'text', 'text': '{"action":"inspect"}'}]}

    def factory(self, **kwargs):
        self.client_kwargs = kwargs.copy()
        kwargs['transport'] = httpx.MockTransport(self.respond)
        client = httpx.AsyncClient(**kwargs)
        self.clients.append(client)
        return client

    def respond(self, request):
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, headers={'request-id': 'req_test'})

    def execute(self, *, effort='high', model='claude-sonnet-5-5', settings=None, input='Source packet', output_type=Decision):
        async def invoke():
            self.model = ClaudeMessagesModel(model, timeout_seconds=30,
                reasoning_effort=effort, client_factory=self.factory)
            try:
                agent = Agent(name='Planner', instructions='Read the supplied evidence.', model=self.model,
                    model_settings=settings or ModelSettings(max_tokens=3000),
                    output_type=AgentOutputSchema(output_type, strict_json_schema=False))
                return await Runner.run(agent, input, max_turns=1, run_config=RunConfig(tracing_disabled=True))
            finally:
                await self.model.aclose()
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': self.secret}):
            return asyncio.run(invoke())

    def test_real_runner_decision_and_exact_native_wire(self):
        for effort in ('low', 'medium', 'high'):
            with self.subTest(effort=effort):
                result = self.execute(effort=effort,
                    settings=ModelSettings(max_tokens=3000, retry=ModelRetrySettings(max_retries=0)))
                self.assertEqual(result.final_output, Decision(action='inspect'))
                request = self.requests[-1]
                body = json.loads(request.content)
                self.assertEqual(str(request.url), ENDPOINT)
                self.assertEqual(request.headers['x-api-key'], self.secret)
                self.assertEqual(body['thinking'], {'type': 'adaptive'})
                self.assertEqual(body['output_config'], {'effort': effort})
                self.assertEqual(body['messages'], [{'role': 'user', 'content': 'Source packet'}])
                self.assertEqual(body['max_tokens'], 3000)
                self.assertFalse(body['stream'])
                self.assertEqual(set(body), {'model', 'system', 'messages', 'max_tokens', 'thinking', 'output_config', 'stream'})
                self.assertIn('Read the supplied evidence.', body['system'])
                self.assertIn('JSON Schema', body['system'])
                self.assertEqual(self.model.response_metadata['request_sha256'], hashlib.sha256(request.content).hexdigest())
                self.assertEqual(self.model.response_text, '{"action":"inspect"}')
                saved = json.dumps(self.model.response_metadata) + self.model.response_text
                for secret in (self.secret, 'HIDDEN_THOUGHT', 'HIDDEN_SIGNATURE'):
                    self.assertNotIn(secret, saved)
                self.assertTrue(self.clients[-1].is_closed)
                self.assertFalse(self.client_kwargs['follow_redirects'])
                self.assertFalse(self.client_kwargs['trust_env'])
                self.assertEqual(self.client_kwargs['timeout'], 30)
        self.assertEqual(len(self.requests), 3)

    def test_configuration_matches_body_including_schema_instruction(self):
        model = ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=300)
        kwargs = dict(system_instructions='Source-only decisions.', input='中文材料',
            model_settings=ModelSettings(max_tokens=16000), tools=[], handoffs=[],
            output_schema=AgentOutputSchema(Decision, strict_json_schema=False))
        raw = model.request_body(**kwargs)
        body = json.loads(raw)
        snapshot = validate_configuration_snapshot(model.request_configuration(**kwargs))
        self.assertEqual(snapshot['capture_layer'], 'http_request_before_dispatch')
        self.assertEqual(snapshot['fields']['reasoning_effort']['value'], 'high')
        self.assertEqual(snapshot['fields']['max_retries']['value'], 0)
        self.assertEqual(snapshot['fields']['api_format']['value'], 'anthropic_messages')
        self.assertEqual(snapshot['fingerprints']['system_sha256'], hashlib.sha256(body['system'].encode()).hexdigest())
        self.assertIn('stateless host decision protocol. This endpoint offers no tools.', body['system'])
        self.assertIn('the host validates and executes it', body['system'])
        self.assertIn('no XML, tool-call markup, prose, or Markdown fences', body['system'])
        example = body['system'].split('Structural example: ', 1)[1].split('. ', 1)[0]
        from uteki.agents.data_query.autonomous import AutonomousDecision
        AutonomousDecision.model_validate_json(example)
        schema_text = body['system'].split('Follow this JSON Schema; all required fields must be present:\n', 1)[1]
        self.assertEqual(json.loads(schema_text), kwargs['output_schema'].json_schema())
        self.assertEqual(snapshot['fingerprints']['output_schema_sha256'], hashlib.sha256(schema_text.encode()).hexdigest())
        for field in ('temperature', 'top_p', 'top_k', 'seed', 'tool_choice', 'parallel_tool_calls', 'response_format'):
            self.assertEqual(snapshot['fields'][field]['status'], 'not_sent')
        self.assertNotIn('中文材料', json.dumps(snapshot, ensure_ascii=False))
        self.assertEqual(self.requests, [])

    def test_settings_models_efforts_and_nontext_reject_before_dispatch(self):
        invalid_settings = [ModelSettings(max_tokens=0), ModelSettings(max_tokens=16001), ModelSettings(),
            ModelSettings(max_tokens=100, temperature=0), ModelSettings(max_tokens=100, store=False),
            ModelSettings(max_tokens=100, extra_body={'tools': []}),
            ModelSettings(max_tokens=100, extra_headers={'x-secret': 'bad'}),
            ModelSettings(max_tokens=100, retry=ModelRetrySettings(max_retries=1))]
        for settings in invalid_settings:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.execute(settings=settings)
        for kwargs in ({'model': 'claude-latest'}, {'reasoning_effort': 'max'}, {'timeout_seconds': 0}):
            arguments = {'model': 'claude-sonnet-5-5', 'timeout_seconds': 30} | kwargs
            with self.assertRaises(ValueError):
                ClaudeMessagesModel(**arguments)
        for input in ([{'role': 'assistant', 'content': 'history'}],
                      [{'role': 'user', 'content': [{'type': 'input_image', 'image_url': 'https://example.invalid'}]}],
                      [{'role': 'user', 'content': 'first'}, {'role': 'user', 'content': 'second'}]):
            with self.assertRaises(ValueError):
                self.execute(input=input)
        self.assertEqual(self.requests, [])

    def test_thinking_default_preserves_adaptive_request_bytes(self):
        kwargs = dict(system_instructions='Frozen system', input='Frozen packet',
            model_settings=ModelSettings(max_tokens=6000), tools=[], output_schema=None, handoffs=[])
        for name in ('claude-sonnet-5-5', 'claude-opus-5-5'):
            with self.subTest(model=name):
                default = ClaudeMessagesModel(name, timeout_seconds=600, stream=True)
                explicit = ClaudeMessagesModel(name, timeout_seconds=600, stream=True, thinking_type='adaptive')
                raw = default.request_body(**kwargs)
                self.assertEqual(raw, explicit.request_body(**kwargs))
                self.assertEqual(json.loads(raw)['thinking'], {'type': 'adaptive'})
        self.assertEqual(self.requests, [])

    def test_between_tools_matches_body_and_configuration_for_supported_efforts(self):
        kwargs = dict(system_instructions='Frozen system', input='Frozen packet',
            model_settings=ModelSettings(max_tokens=6000), tools=[], output_schema=None, handoffs=[])
        for effort in ('low', 'medium', 'high'):
            with self.subTest(effort=effort):
                model = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=600, stream=True,
                    reasoning_effort=effort, thinking_type='between_tools')
                body = json.loads(model.request_body(**kwargs))
                snapshot = validate_configuration_snapshot(model.request_configuration(**kwargs))
                self.assertEqual(body['thinking'], {'type': 'between_tools'})
                self.assertEqual(body['output_config'], {'effort': effort})
                self.assertEqual(snapshot['fields']['thinking']['value'], body['thinking'])
                self.assertEqual(snapshot['fields']['reasoning_effort']['value'], effort)
                adaptive = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=600,
                    stream=True, reasoning_effort=effort)
                expected = json.loads(adaptive.request_body(**kwargs))
                expected['thinking'] = {'type': 'between_tools'}
                self.assertEqual(body, expected)
        self.assertEqual(self.requests, [])

    def test_unsupported_thinking_modes_reject_before_dispatch(self):
        for value in ('disabled', 'unknown', '', None, True, {'type': 'between_tools'}):
            with self.subTest(thinking_type=value), self.assertRaisesRegex(ValueError, 'thinking_type'):
                ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, thinking_type=value)
        with self.assertRaisesRegex(ValueError, 'requires claude-sonnet-5-5'):
            ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=30, thinking_type='between_tools')
        for effort in ('xhigh', 'max'):
            with self.subTest(effort=effort), self.assertRaisesRegex(ValueError, 'effort'):
                ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30,
                    reasoning_effort=effort, thinking_type='between_tools')
        self.assertEqual(self.requests, [])

    def test_larger_output_limit_is_explicit_stream_only_and_absolutely_bounded(self):
        kwargs = dict(system_instructions='System', input='Frozen packet',
            model_settings=ModelSettings(max_tokens=48000), tools=[], output_schema=None, handoffs=[])
        default = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, stream=True)
        with self.assertRaisesRegex(ValueError, '1..16000'):
            default.request_body(**kwargs)
        expanded = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, stream=True,
                                      max_output_tokens_limit=48000)
        body = json.loads(expanded.request_body(**kwargs))
        self.assertEqual(body['max_tokens'], 48000)
        self.assertEqual(body['thinking'], {'type':'adaptive'})
        self.assertEqual(body['output_config'], {'effort':'high'})
        self.assertTrue(body['stream'])
        self.assertEqual(expanded.request_configuration(**kwargs)['fields']['max_tokens']['value'], 48000)
        with self.assertRaisesRegex(ValueError, '1..48000'):
            expanded.request_body(**(kwargs | {'model_settings': ModelSettings(max_tokens=48001)}))
        for value in (0, 48001, True, 48000.0):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, stream=True,
                                    max_output_tokens_limit=value)
        with self.assertRaisesRegex(ValueError, 'require stream=true'):
            ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30, max_output_tokens_limit=48000)
        opus = ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=30, stream=True,
                                  max_output_tokens_limit=24000)
        opus_kwargs = kwargs | {'model_settings': ModelSettings(max_tokens=24000)}
        self.assertEqual(json.loads(opus.request_body(**opus_kwargs))['max_tokens'], 24000)
        with self.assertRaisesRegex(ValueError, '1..24000'):
            opus.request_body(**kwargs)
        for limit in (24001, 48000):
            with self.subTest(opus_limit=limit), self.assertRaisesRegex(ValueError, '1..24000'):
                ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=30, stream=True,
                                    max_output_tokens_limit=limit)
        with self.assertRaisesRegex(ValueError, 'require stream=true'):
            ClaudeMessagesModel('claude-opus-5-5', timeout_seconds=30, max_output_tokens_limit=24000)
        old_kwargs = kwargs | {'model_settings':ModelSettings(max_tokens=16000)}
        self.assertEqual(default.request_body(**old_kwargs), expanded.request_body(**old_kwargs))
        self.assertEqual(self.requests, [])

    def test_no_tool_handoff_or_provider_continuation(self):
        model = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30)
        basic = dict(system_instructions='System', input='Packet', model_settings=ModelSettings(max_tokens=100),
                     tools=[], output_schema=None, handoffs=[])
        for change in ({'tools': [object()]}, {'handoffs': [object()]}, {'previous_response_id': 'old'},
                       {'conversation_id': 'conversation'}, {'prompt': {'id': 'stored'}}):
            with self.assertRaises(ValueError):
                model.request_configuration(**(basic | change))
        self.assertEqual(self.requests, [])

    def test_incomplete_empty_invalid_schema_keep_usage_without_retry(self):
        for text, stop in (('{"action":"inspect"}', 'max_tokens'), ('', 'end_turn'),
                           ('{"unknown":true}', 'end_turn'), ('{}', 'pause_turn'),
                           ('<invoke name="load_skill"></invoke>\n{"action":"inspect"}', 'end_turn')):
            with self.subTest(stop=stop, text=text):
                before = len(self.requests)
                self.payload['stop_reason'] = stop
                self.payload['content'][-1]['text'] = text
                with self.assertRaises(ModelBehaviorError):
                    self.execute()
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.model.response_metadata['stop_reason'], stop)
                self.assertEqual(self.model.response_metadata['raw_usage']['output_tokens'], 20)
                self.assertEqual(self.model.response_text, text)

    def test_secret_echo_redaction_and_numeric_metadata_only(self):
        self.payload['id'] = self.secret
        self.payload['content'][-1]['text'] = json.dumps({'action': self.secret})
        self.payload['usage']['sensitive'] = {'secret': self.secret}
        result = self.execute()
        self.assertEqual(result.final_output.action, '[REDACTED]')
        self.assertIsNone(self.model.response_metadata['response_id'])
        self.assertNotIn(self.secret, json.dumps(self.model.response_metadata) + self.model.response_text)
        self.assertNotIn('sensitive', self.model.response_metadata['raw_usage'])

    def test_strict_decision_json_rejects_ambiguous_values_before_host_action(self):
        from uteki.agents.data_query.autonomous import AutonomousDecision
        cases = [
            ('{"action":"finish","action":"load_skill","skill":"query"}', 'duplicate_key'),
            ('{"action":"acquire","arguments":{"PRIVATE_FIELD":1,"PRIVATE_FIELD":2}}', 'duplicate_key'),
            *[('{"action":"acquire","arguments":{"PRIVATE_FIELD":' + value + '}}', 'non_finite_number')
              for value in ('NaN', 'Infinity', '-Infinity', '1e999')],
            ('[{"action":"load_skill","skill":"query"}]', 'root_not_object'),
            ('```json\n{"action":"load_skill","skill":"query"}\n```', 'invalid_json'),
            ('{"action":"finish"}{"action":"finish"}', 'invalid_json'),
        ]
        for text, code in cases:
            with self.subTest(code=code, text=text):
                self.payload['content'][-1]['text'] = text
                before, host_actions = len(self.requests), []
                with self.assertRaises(ModelBehaviorError) as error:
                    result = self.execute(output_type=AutonomousDecision)
                    host_actions.append(result.final_output.action)
                self.assertEqual(str(error.exception), 'JSON output rejected: ' + code)
                self.assertNotIn('PRIVATE_FIELD', str(error.exception))
                self.assertIsNone(error.exception.__context__)
                self.assertEqual(host_actions, [])
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.model.response_text, text)
                self.assertEqual(self.model.response_metadata['raw_usage']['output_tokens'], 20)

    def test_http_error_and_timeout_do_not_retain_body_or_retry(self):
        for timeout in (False, True):
            def respond(request):
                self.requests.append(request)
                if timeout:
                    raise httpx.ReadTimeout(self.secret, request=request)
                return httpx.Response(429, text='private-error-body ' + self.secret)
            self.respond = respond
            before = len(self.requests)
            with self.assertRaises((ModelBehaviorError, TimeoutError)) as error:
                self.execute()
            self.assertEqual(len(self.requests), before + 1)
            self.assertNotIn(self.secret, str(error.exception) + json.dumps(self.model.response_metadata))
            self.assertNotIn('private-error-body', json.dumps(self.model.response_metadata))

    def test_transport_categories_survive_without_private_exception_details(self):
        custom_error = type('private_error_name', (httpx.HTTPError,), {})
        for error_type, expected, outward in (
            (httpx.RemoteProtocolError, 'RemoteProtocolError', RuntimeError),
            (httpx.ConnectError, 'ConnectError', RuntimeError),
            (httpx.ReadTimeout, 'ReadTimeout', TimeoutError),
            (TimeoutError, 'TimeoutError', TimeoutError),
            (custom_error, 'HTTPError', RuntimeError),
        ):
            with self.subTest(error_type=error_type):
                def respond(request):
                    self.requests.append(request)
                    raise error_type('private-error-body ' + self.secret)
                self.respond = respond
                before = len(self.requests)
                with self.assertRaises(outward) as error:
                    self.execute()
                self.assertEqual(len(self.requests), before + 1)
                metadata = self.model.response_metadata
                self.assertEqual(metadata['transport_error_type'], expected)
                self.assertEqual(metadata['usage_presence'], 'absent')
                self.assertEqual(metadata['dispatch_status'], 'not_sent' if error_type is httpx.ConnectError else 'sent')
                self.assertIsNone(metadata.get('http_status'))
                self.assertIsNone(error.exception.__context__)
                retained = json.dumps(metadata) + str(error.exception)
                for private in (self.secret, 'private-error-body', 'private_error_name'):
                    self.assertNotIn(private, retained)

    def test_overlapping_requests_restore_logging_only_after_last_exit(self):
        async def invoke(cancel_last):
            entered = [asyncio.Event(), asyncio.Event()]
            release = [asyncio.Event(), asyncio.Event()]
            models, tasks = [], []
            def factory_for(index):
                async def respond(request):
                    entered[index].set()
                    await release[index].wait()
                    return httpx.Response(200, json=self.payload)
                def factory(**kwargs):
                    kwargs['transport'] = httpx.MockTransport(respond)
                    return httpx.AsyncClient(**kwargs)
                return factory
            try:
                for index in range(2):
                    model = ClaudeMessagesModel('claude-sonnet-5-5', timeout_seconds=30,
                        client_factory=factory_for(index))
                    models.append(model)
                    tasks.append(asyncio.create_task(model.get_response(
                        system_instructions='System', input='Packet', model_settings=ModelSettings(max_tokens=100),
                        tools=[], output_schema=None, handoffs=[])))
                    await asyncio.wait_for(entered[index].wait(), 1)
                self.assertEqual(logging.root.manager.disable, logging.CRITICAL)
                release[0].set()
                await tasks[0]
                self.assertEqual(logging.root.manager.disable, logging.CRITICAL)
                if cancel_last:
                    tasks[1].cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await tasks[1]
                else:
                    release[1].set()
                    await tasks[1]
                self.assertEqual(logging.root.manager.disable, logging.WARNING)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.gather(*(model.aclose() for model in models))
        previous = logging.root.manager.disable
        try:
            for cancel_last in (False, True):
                with self.subTest(cancel_last=cancel_last):
                    logging.disable(logging.WARNING)
                    with patch.dict(os.environ, {'AIHUBMIX_API_KEY': self.secret}):
                        asyncio.run(invoke(cancel_last))
        finally:
            logging.disable(previous)


if __name__ == '__main__':
    unittest.main()
