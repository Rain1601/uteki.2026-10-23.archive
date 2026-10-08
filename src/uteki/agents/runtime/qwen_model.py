"""Bounded Qwen Chat adapter: explicit effort, total output cap, local validation."""
from dataclasses import replace

from agents import OpenAIChatCompletionsModel
from agents.exceptions import ModelBehaviorError

from .deepseek_model import json_instructions


MODELS = frozenset({'qwen3.8-flash'})


class QwenChatCompletionsModel(OpenAIChatCompletionsModel):
    strict_visible_json = True
    raw_chat_usage = True
    output_limit_parameter = 'max_completion_tokens'
    wire_response_format = 'json_object'
    response_metadata = None
    response_text = None

    async def _fetch_response(self, system_instructions, input, model_settings,
                              tools, output_schema, handoffs, span, tracing,
                              stream=False, prompt=None):
        self.response_metadata = self.response_text = None
        if self.model not in MODELS:
            raise ValueError('Unregistered Qwen model')
        if stream:
            raise ValueError('Qwen metering requires non-streaming calls')
        body = model_settings.extra_body
        if (model_settings.extra_args not in (None, {}) or not isinstance(body, dict)
                or set(body) != {'reasoning_effort', 'preserve_thinking'}
                or not isinstance(body['reasoning_effort'], str)
                or body['reasoning_effort'] not in {'none', 'low', 'medium', 'xhigh'}
                or body['preserve_thinking'] is not False):
            raise ValueError('Qwen requires explicit registered effort and preserve_thinking=false')
        if (type(model_settings.max_tokens) is not int or not 256 <= model_settings.max_tokens <= 8192
                or model_settings.temperature is not None or model_settings.top_p is not None
                or model_settings.reasoning is not None):
            raise ValueError('Qwen requires a bounded total output limit and no implicit sampling overrides')
        if tools or handoffs:
            raise ValueError('Qwen decision adapter uses host-executed JSON actions, not native tools')
        schema = output_schema.json_schema() if output_schema and not output_schema.is_plain_text() else None
        extra = {**body, 'max_completion_tokens': model_settings.max_tokens}
        if schema is not None:
            extra['response_format'] = {'type': 'json_object'}
        settings = replace(model_settings, max_tokens=None, store=None, extra_body=extra)
        response = await super()._fetch_response(
            json_instructions(system_instructions, schema), input, settings,
            tools, None, handoffs, span, tracing, stream=False, prompt=prompt)
        choice = response.choices[0] if response.choices else None
        self.response_text = choice.message.content if choice else None
        self.response_metadata = {
            'actual_upstream_model': response.model,
            'system_fingerprint': getattr(response, 'system_fingerprint', None),
            'response_id': response.id, 'request_id': getattr(response, '_request_id', None),
            'finish_reason': choice.finish_reason if choice else None,
            'raw_usage': response.usage.model_dump(mode='json', exclude_unset=True) if response.usage else None,
        }
        if choice is None or choice.finish_reason != 'stop':
            raise ModelBehaviorError('Qwen response incomplete; inspect recorded finish_reason')
        if not choice.message.content or choice.message.tool_calls:
            raise ModelBehaviorError('Qwen requires one visible JSON decision')
        return response
