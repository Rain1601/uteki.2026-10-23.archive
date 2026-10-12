"""Frozen-image contract and real SDK/native-meter wiring, without model calls."""
import asyncio
import base64
import copy
import hashlib
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
import httpx2 as httpx
from PIL import Image, ImageFile
from pydantic import BaseModel, ConfigDict

from uteki.agents.runtime.claude_vision import ClaudeVisionModel, MAX_IMAGE_BYTES
from uteki.agents.runtime.run_budget import RequestEnvelopeTooLarge, RunBudget
from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize


class Figure(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str


def image_bytes(fmt='PNG', size=(12, 10), color='white'):
    buffer = BytesIO()
    Image.new('RGB', size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def packet(raw=None, mime='image/png'):
    return [{'role': 'user', 'content': [
        {'type': 'input_image', 'image_url': 'data:' + mime + ';base64,' + base64.b64encode(raw or image_bytes()).decode()},
        {'type': 'input_text', 'text': 'Extract the figure title.'}]}]


def arguments(value=None):
    return dict(system_instructions='Read the image.', input=packet() if value is None else value,
        model_settings=ModelSettings(max_tokens=200), tools=[], handoffs=[],
        output_schema=AgentOutputSchema(Figure, strict_json_schema=False))


class ClaudeVisionTests(unittest.TestCase):
    def setUp(self):
        self.model = ClaudeVisionModel('claude-sonnet-5-5', timeout_seconds=30)

    def test_supported_formats_and_exact_frozen_bytes(self):
        for fmt, mime in [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('GIF', 'image/gif'), ('WEBP', 'image/webp')]:
            with self.subTest(fmt=fmt):
                raw = image_bytes(fmt)
                kwargs = arguments(packet(raw, mime))
                body = json.loads(self.model.request_body(**kwargs))
                image, text = body['messages'][0]['content']
                self.assertEqual(image['source']['media_type'], mime)
                self.assertEqual(base64.b64decode(image['source']['data']), raw)
                self.assertEqual(text, {'type': 'text', 'text': 'Extract the figure title.'})
                self.assertIn('JSON Schema', body['system'])
                self.assertNotIn('format', body['output_config'])

    def test_rejects_remote_file_malformed_or_noncanonical_base64(self):
        for uri in ['https://example.com/image.png', 'file:///tmp/image.png',
                    'data:image/svg+xml;base64,PHN2Zy8+', 'data:image/png;base64,!!!!',
                    'data:image/png;base64,YQ=', 'data:image/png;base64,YR==',
                    'data:image/png;base64,', 'data:image/png;base64,YQ==\n']:
            with self.subTest(uri=uri):
                value = packet()
                value[0]['content'][0]['image_url'] = uri
                with self.assertRaises(ValueError):
                    self.model.request_body(**arguments(value))

    def test_rejects_corruption_media_mismatch_oversize_and_animation(self):
        buffer = BytesIO()
        Image.new('RGB', (12, 10), 'red').save(buffer, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (12, 10), 'blue')], duration=100, loop=0)
        for raw, mime in [(image_bytes('JPEG')[:-10], 'image/jpeg'),
                          (image_bytes('PNG')[:-20], 'image/png'),
                          (image_bytes(), 'image/jpeg'),
                          (image_bytes(size=(2001, 1)), 'image/png'),
                          (buffer.getvalue(), 'image/gif'),
                          (b'x' * (MAX_IMAGE_BYTES + 1), 'image/png')]:
            with self.subTest(mime=mime, length=len(raw)):
                with self.assertRaises(ValueError):
                    self.model.request_body(**arguments(packet(raw, mime)))

    def test_permissive_global_decoder_cannot_bypass_completeness_validation(self):
        with patch.object(ImageFile, 'LOAD_TRUNCATED_IMAGES', True):
            with self.assertRaisesRegex(ValueError, 'strict image decoding'):
                self.model.request_body(**arguments())

    def test_rejects_extra_images_empty_text_conversation_tools_settings_and_schema(self):
        values = []
        two = packet(); two[0]['content'].insert(0, copy.deepcopy(two[0]['content'][0])); values.append(two)
        empty = packet(); empty[0]['content'][1]['text'] = ' '; values.append(empty)
        values.extend([packet() * 2, 'image text', [{'role': 'assistant', 'content': packet()[0]['content']}],
                       [{'role': 'user', 'content': list(reversed(packet()[0]['content']))}]])
        for value in values:
            with self.assertRaises(ValueError):
                self.model.request_body(**arguments(value))
        for overrides in [dict(tools=[object()]), dict(conversation_id='past'),
                          dict(output_schema=None), dict(model_settings=ModelSettings(max_tokens=200, temperature=0))]:
            with self.assertRaises(ValueError):
                self.model.request_body(**(arguments() | overrides))
        with self.assertRaises(ValueError):
            ClaudeVisionModel('claude-sonnet-5-5', timeout_seconds=30, schema_protocol='host_decision')

    def test_actual_image_payload_affects_fingerprint_and_capacity(self):
        first = arguments(packet(image_bytes(color='white')))
        second = arguments(packet(image_bytes(color='black')))
        a, b = self.model.request_configuration(**first), self.model.request_configuration(**second)
        self.assertNotEqual(a['fingerprints']['input_sha256'], b['fingerprints']['input_sha256'])
        raw = self.model.request_body(**first)
        bounded = ClaudeVisionModel('claude-sonnet-5-5', timeout_seconds=30, max_request_bytes=len(raw) - 1)
        with self.assertRaises(RequestEnvelopeTooLarge):
            bounded.request_body(**first)

    def invoke_sdk(self, folder, answer='{"title":"Performance"}'):
        sent = []
        def respond(request):
            sent.append(request)
            return httpx.Response(200, json={'id': 'msg_figure', 'model': 'claude-sonnet-5-5',
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 150, 'output_tokens': 20},
                'content': [{'type': 'text', 'text': answer}]})
        def factory(**kwargs):
            kwargs['transport'] = httpx.MockTransport(respond)
            return httpx.AsyncClient(**kwargs)
        async def invoke():
            native = ClaudeVisionModel('claude-sonnet-5-5', timeout_seconds=30, client_factory=factory)
            try:
                metered = MeteredModel(native, folder / 'calls', 'figure', 'aihubmix', 'claude-sonnet-5-5',
                    pricing_snapshot('aihubmix', 'claude-sonnet-5-5'), RunBudget(folder / 'budget.sqlite', '2'))
                agent = Agent(name='Figure', instructions='Read the image.', model=metered,
                    model_settings=ModelSettings(max_tokens=200),
                    output_type=AgentOutputSchema(Figure, strict_json_schema=False))
                return await Runner.run(agent, packet(), max_turns=1, run_config=RunConfig(tracing_disabled=True))
            finally:
                await native.aclose()
        with patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-vision-key'}):
            result = asyncio.run(invoke())
        return result, sent

    def test_real_runner_and_meter_use_image_wire_fingerprint_and_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            result, sent = self.invoke_sdk(folder)
            self.assertEqual(result.final_output, Figure(title='Performance'))
            self.assertEqual(len(sent), 1)
            row = summarize(folder / 'calls')['records'][0]
            self.assertEqual(row['request_bytes'], len(sent[0].content))
            self.assertEqual(row['request_sha256'], hashlib.sha256(sent[0].content).hexdigest())
            self.assertEqual(row['raw_usage']['input_tokens'], 150)
            self.assertIsNotNone(row['estimated_usd'])
            self.assertEqual(json.loads(sent[0].content)['messages'][0]['content'][0]['type'], 'image')

    def test_invalid_model_result_does_not_bypass_local_schema_validation(self):
        for answer in ['{"wrong":"field"}', '{"title":null}']:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ModelBehaviorError):
                    self.invoke_sdk(Path(temp), answer)
                self.assertIsNotNone(summarize(Path(temp) / 'calls')['records'][0]['estimated_usd'])


if __name__ == '__main__':
    unittest.main()
