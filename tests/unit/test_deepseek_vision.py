"""Official DeepSeek image wire, local schema and metering; all HTTP is mocked."""
import asyncio
import base64
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.agent_output import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from agents.models.interface import ModelTracing
import httpx2 as httpx
from openai import AsyncOpenAI
from PIL import Image
from pydantic import BaseModel, ConfigDict

from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.deepseek_vision import DeepSeekVisionModel
from uteki.agents.runtime.run_budget import BudgetExceeded, RequestEnvelopeTooLarge, RunBudget


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str


def packet(raw=None, mime='image/png'):
    if raw is None:
        buf = BytesIO()
        Image.new('RGB', (12, 10), 'white').save(buf, format='PNG')
        raw = buf.getvalue()
    return [{'role': 'user', 'content': [
        {'type': 'input_image', 'image_url': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()},
        {'type': 'input_text', 'text': 'Read the exact frozen image.'}]}]


class DeepSeekVisionTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.payload = {'id': 'image-mock', 'object': 'chat.completion', 'created': 1,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': '{"title":"Performance"}'}}],
            'usage': {'prompt_tokens': 123, 'completion_tokens': 17, 'total_tokens': 140}}

    def invoke(self, folder, *, value=None, effort='high', settings=None, limit='2',
               max_request_bytes=400000, extra_agent=None):
        def respond(request):
            self.sent.append(request)
            return httpx.Response(200, json=self.payload, headers={'x-request-id': 'mock-request'})
        async def run():
            async with AsyncOpenAI(api_key='mock-deepseek-key', base_url='https://api.deepseek.com',
                    max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
                self.model = DeepSeekVisionModel('deepseek-flash', openai_client=client,
                                                reasoning_effort=effort)
                self.budget = RunBudget(folder/'budget.sqlite', limit)
                meter = MeteredModel(self.model, folder/'calls', 'figure', 'deepseek', 'deepseek-flash',
                    pricing_snapshot('deepseek', 'deepseek-flash'), self.budget,
                    max_request_bytes=max_request_bytes)
                selected = settings or ModelSettings(max_tokens=8192,
                    extra_body=copy.deepcopy(self.model.vision_settings))
                agent = Agent(name='Figure', instructions='Transcribe pixels only.', model=meter,
                    model_settings=selected, output_type=AgentOutputSchema(Answer, strict_json_schema=False),
                    **(extra_agent or {}))
                return await Runner.run(agent, packet() if value is None else value,
                    max_turns=1, run_config=RunConfig(tracing_disabled=True))
        return asyncio.run(run())

    def test_actual_sdk_transmits_exact_pixels_and_typed_json_with_raw_usage(self):
        for effort in ('high', 'none'):
            with self.subTest(effort=effort), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp); supplied = packet()
                result = self.invoke(folder, value=supplied, effort=effort)
                body = json.loads(self.sent[-1].content)
                image = body['messages'][1]['content'][0]
                self.assertEqual(image, {'type': 'image_url', 'image_url': {
                    'url': supplied[0]['content'][0]['image_url'], 'detail': 'high'}})
                self.assertEqual(body['model'], 'deepseek-flash')
                self.assertEqual(body['max_tokens'], 8192)
                self.assertEqual(body['thinking']['type'], 'enabled' if effort == 'high' else 'disabled')
                self.assertEqual(body['reasoning_effort'], effort)
                self.assertEqual(body['response_format'], {'type': 'json_object'})
                self.assertNotIn('tools', body)
                self.assertEqual(result.final_output, Answer(title='Performance'))
                self.assertEqual(supplied[0]['content'][0].keys(), {'type', 'image_url'})
                row = summarize(folder/'calls')['records'][0]
                self.assertEqual(row['raw_usage']['prompt_tokens'], 123)
                self.assertEqual(row['estimated_usd'], '0.0000573')
                self.assertEqual(row['finish_reason'], 'stop')
                self.assertEqual(row['request_id'], 'mock-request')
                self.assertEqual(row['configuration_snapshot']['fields']['base_url']['value'],
                                 'https://api.deepseek.com')

    def test_invalid_remote_corrupt_mismatch_multiframe_and_history_fail_before_http(self):
        invalid = []
        for uri in ('https://example.com/image.png', 'data:image/png;base64,YR==',
                    'file:///tmp/image.png', 'data:image/svg+xml;base64,PHN2Zy8+'):
            p = packet(); p[0]['content'][0]['image_url'] = uri; invalid.append(p)
        invalid.extend([packet(b'broken'), packet(mime='image/jpeg'), packet()*2])
        more = packet(); more[0]['content'].append(copy.deepcopy(more[0]['content'][0])); invalid.append(more)
        bot = packet(); bot[0]['role'] = 'assistant'; invalid.append(bot)
        animation = BytesIO()
        Image.new('RGB', (12, 10), 'red').save(animation, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (12, 10), 'blue')], duration=100, loop=0)
        invalid.append(packet(animation.getvalue(), 'image/gif'))
        for value in invalid:
            with self.subTest(value=str(value)[:60]), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    self.invoke(Path(temp), value=value)
        self.assertEqual(self.sent, [])

    def test_model_endpoint_retry_and_thinking_bounds(self):
        for model, effort in (('deepseek-v4-pro', 'high'), ('deepseek-flash', 'max')):
            with self.assertRaises(ValueError):
                DeepSeekVisionModel(model, reasoning_effort=effort)
        async def clients():
            for endpoint, retries in (('https://aihubmix.com/v1', 0), ('https://api.deepseek.com', 2)):
                async with AsyncOpenAI(api_key='mock', base_url=endpoint, max_retries=retries) as client:
                    with self.assertRaises(ValueError):
                        DeepSeekVisionModel('deepseek-flash', openai_client=client)
        asyncio.run(clients())
        for settings in (ModelSettings(max_tokens=8193),
                         ModelSettings(max_tokens=8192, extra_body={'thinking': {'type':'disabled'}}),
                         ModelSettings(max_tokens=8192, extra_args={'messages': []})):
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
                self.invoke(Path(temp), settings=settings)
        self.assertEqual(self.sent, [])

    def test_selected_key_cannot_fall_back_to_openai_or_aihubmix(self):
        model = DeepSeekVisionModel('deepseek-flash')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'wrong', 'AIHUBMIX_API_KEY': 'wrong'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
                model._get_client()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-selected'}, clear=True):
            self.assertEqual(str(model._get_client().base_url), 'https://api.deepseek.com')
            self.assertEqual(model._client.api_key, 'offline-selected')
        asyncio.run(model.aclose())

    def test_prior_state_tools_plain_output_or_unbounded_tokens_are_rejected(self):
        model = DeepSeekVisionModel('deepseek-flash')
        arguments = dict(system_instructions='Read pixels.', input=packet(),
            model_settings=ModelSettings(max_tokens=8192, extra_body=model.vision_settings),
            tools=[], handoffs=[], output_schema=AgentOutputSchema(Answer, strict_json_schema=False),
            tracing=ModelTracing.DISABLED)
        for change in ({'previous_response_id':'old'}, {'conversation_id':'old'}, {'prompt':{}},
                       {'tools':[object()]}, {'handoffs':[object()]}, {'output_schema':None},
                       {'model_settings':ModelSettings(max_tokens=None, extra_body=model.vision_settings)}):
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                asyncio.run(model.get_response(**(arguments | change)))
        self.assertIsNone(model._client)

    def test_supported_formats_keep_original_bytes(self):
        for fmt, mime in (('JPEG','image/jpeg'), ('PNG','image/png'),
                          ('GIF','image/gif'), ('WEBP','image/webp')):
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as temp:
                buf=BytesIO(); Image.new('RGB',(12,10),'white').save(buf, format=fmt)
                raw=buf.getvalue(); self.invoke(Path(temp), value=packet(raw,mime))
                body=json.loads(self.sent[-1].content)
                url=body['messages'][1]['content'][0]['image_url']['url']
                self.assertEqual(base64.b64decode(url.split(',',1)[1]), raw)

    def test_incomplete_and_schema_invalid_outputs_keep_actual_usage(self):
        for content, finish in (('{"title":"Partial"}', 'length'),
                                ('{"title":"Refused"}', 'content_filter'),
                                ('{"invented":true}', 'stop')):
            self.payload['choices'][0]['message']['content'] = content
            self.payload['choices'][0]['finish_reason'] = finish
            with self.subTest(finish=finish), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                with self.assertRaises(ModelBehaviorError):
                    self.invoke(folder)
                row = summarize(folder/'calls')['records'][0]
                self.assertEqual(row['finish_reason'], finish)
                self.assertEqual(row['usage_source'], 'provider_raw')
                self.assertEqual(row['estimated_usd'], '0.0000573')

    def test_missing_usage_preserves_unknown_reservation_and_blocks_next_call(self):
        del self.payload['usage']
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.invoke(folder)
            row = summarize(folder/'calls')['records'][0]
            self.assertIsNone(row['estimated_usd'])
            self.assertGreater(float(row['reserved_usd']), 0)
            with self.assertRaises(BudgetExceeded):
                self.invoke(folder)
            self.assertEqual(len(self.sent), 1)

    def test_budget_and_request_envelope_block_before_dispatch(self):
        for settings in ({'limit': '0.000001'}, {'max_request_bytes': 10}):
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(BudgetExceeded):
                self.invoke(Path(temp), **settings)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
