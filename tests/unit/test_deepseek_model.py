"""DeepSeek adapter wire contract through the real SDK and mocked HTTP only."""
import asyncio
import json
import unittest

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.agent_output import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
import httpx2 as httpx
from openai import AsyncOpenAI
from openai.types.shared import Reasoning
from pydantic import BaseModel

from uteki.agents.runtime.deepseek_model import DeepSeekChatCompletionsModel


class Answer(BaseModel):
    answer: str


class DeepSeekModelTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.payload = {
            'id': 'response-test', 'object': 'chat.completion', 'created': 1,
            'model': 'deepseek-v4-pro-test',
            'system_fingerprint': 'fingerprint-test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': '{"answer":"source result"}',
                'reasoning_content': 'private provider reasoning'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
        }

    def execute(self, settings):
        def respond(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=self.payload, headers={'x-request-id': 'request-test'})

        async def invoke():
            async with AsyncOpenAI(
                api_key='test-key', base_url='https://api.deepseek.com', max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            ) as client:
                self.model = DeepSeekChatCompletionsModel(model='deepseek-v4-pro', openai_client=client)
                agent = Agent(
                    name='Planner', instructions='Use the planner role and source evidence.',
                    model=self.model, model_settings=settings,
                    output_type=AgentOutputSchema(Answer, strict_json_schema=False),
                )
                return await Runner.run(agent, 'Read the selected source.', max_turns=1,
                                        run_config=RunConfig(tracing_disabled=True))

        return asyncio.run(invoke())

    def test_enabled_efforts_reach_wire_with_json_and_role_prompt(self):
        for effort in ('low', 'high', 'max'):
            with self.subTest(effort=effort):
                extra_body = {'thinking': {'type': 'enabled'}, 'reasoning_effort': effort}
                result = self.execute(ModelSettings(
                    max_tokens=3000, temperature=0, store=False,
                    reasoning=Reasoning(effort='low'), extra_body=extra_body))
                body = self.requests[-1]
                self.assertEqual(body['thinking'], {'type': 'enabled'})
                self.assertEqual(body['reasoning_effort'], effort)
                self.assertEqual(body['response_format'], {'type': 'json_object'})
                self.assertEqual(body['max_tokens'], 3000)
                self.assertEqual(len(body['messages']), 2)
                self.assertIn('Use the planner role and source evidence.', body['messages'][0]['content'])
                self.assertIn('JSON Schema', body['messages'][0]['content'])
                for field in ('temperature', 'store', 'tools', 'parallel_tool_calls'):
                    self.assertNotIn(field, body)
                self.assertEqual(result.final_output, Answer(answer='source result'))
                self.assertEqual(self.model.response_text, '{"answer":"source result"}')
                self.assertEqual(self.model.response_metadata['system_fingerprint'], 'fingerprint-test')
                self.assertNotIn('private provider reasoning', json.dumps(self.model.response_metadata))
                self.assertEqual(extra_body, {'thinking': {'type': 'enabled'}, 'reasoning_effort': effort})

    def test_default_disabled_preserves_existing_wire_contract(self):
        self.execute(ModelSettings(temperature=0, store=False, reasoning=Reasoning(effort='high')))
        body = self.requests[0]
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(body['temperature'], 0)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertNotIn('reasoning_effort', body)
        self.assertNotIn('store', body)

    def test_explicit_disabled_none_and_enabled_default_are_supported(self):
        self.execute(ModelSettings(extra_body={'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none'}))
        self.assertEqual(self.requests[-1]['reasoning_effort'], 'none')
        self.execute(ModelSettings(extra_body={'thinking': {'type': 'enabled'}}))
        self.assertEqual(self.requests[-1]['thinking'], {'type': 'enabled'})
        self.assertNotIn('reasoning_effort', self.requests[-1])

    def test_invalid_settings_fail_before_http(self):
        invalid = [
            ModelSettings(extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'none'}),
            ModelSettings(extra_body={'thinking': {'type': 'disabled'}, 'reasoning_effort': 'high'}),
            ModelSettings(extra_body={'reasoning_effort': 'low'}),
            ModelSettings(extra_body={'thinking': {'type': 'auto'}}),
            ModelSettings(extra_body={'thinking': {'type': 'enabled', 'budget': 10}}),
            ModelSettings(extra_body={'thinking': 'enabled'}),
            ModelSettings(extra_body={'thinking': None}),
            ModelSettings(extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'medium'}),
            ModelSettings(extra_body={'reasoning_effort': None}),
            ModelSettings(extra_body={'reasoning_effort': []}),
            ModelSettings(extra_body=[]),
            ModelSettings(extra_body={'model': 'different-model'}),
            ModelSettings(extra_body={'response_format': {'type': 'text'}}),
            ModelSettings(extra_args={'reasoning_effort': 'high'}),
            ModelSettings(extra_args={'extra_body': {'thinking': {'type': 'enabled'}}}),
        ]
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.execute(settings)
            self.assertEqual(self.requests, [])

    def test_thinking_mode_keeps_local_schema_and_finish_reason_checks(self):
        settings = ModelSettings(extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'})
        for content, finish_reason in (('{"unrecognized":true}', 'stop'),
                                       ('{"answer":"truncated"}', 'length')):
            with self.subTest(finish_reason=finish_reason), self.assertRaises(ModelBehaviorError):
                self.payload['choices'][0]['message']['content'] = content
                self.payload['choices'][0]['finish_reason'] = finish_reason
                self.execute(settings)
            self.assertEqual(self.model.response_metadata['finish_reason'], finish_reason)
            self.assertEqual(self.model.response_metadata['raw_usage']['completion_tokens'], 50)
            self.assertEqual(self.model.response_metadata['request_id'], 'request-test')


if __name__ == '__main__':
    unittest.main()
