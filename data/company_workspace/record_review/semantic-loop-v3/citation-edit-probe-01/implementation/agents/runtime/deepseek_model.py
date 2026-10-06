"""DeepSeek Chat Completions compatibility for the pinned Agents SDK.

JSON mode guarantees syntax, not schema: Runner still validates the original
output_type locally. Step 5 uses non-streaming, non-thinking, independent calls.
"""
from dataclasses import replace
import json

from agents import OpenAIChatCompletionsModel
from agents.exceptions import ModelBehaviorError


BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'


def json_instructions(instructions, schema):
    if schema is None:
        return instructions
    return (instructions or '') + (
        '\nReturn one JSON object only, without Markdown fences. '
        'Follow this JSON Schema; all required fields must be present:\n'
        + json.dumps(schema, ensure_ascii=False, sort_keys=True)
    )


class DeepSeekChatCompletionsModel(OpenAIChatCompletionsModel):
    # SDK-normalized usage defaults missing counters to zero. Keep the provider's
    # raw metadata so missing usage never becomes a free request in the ledger.
    response_metadata = None
    response_text = None

    async def _fetch_response(self, system_instructions, input, model_settings,
                              tools, output_schema, handoffs, span, tracing,
                              stream=False, prompt=None):
        self.response_metadata = None
        self.response_text = None
        if stream:
            raise NotImplementedError('DeepSeek metering currently requires non-streaming calls')
        schema = output_schema.json_schema() if output_schema and not output_schema.is_plain_text() else None
        extra_body = {**(model_settings.extra_body or {}), 'thinking': {'type': 'disabled'}}
        if schema is not None:
            extra_body['response_format'] = {'type': 'json_object'}
        settings = replace(model_settings, store=None, reasoning=None, extra_body=extra_body)
        # _fetch_response is the conversion boundary in openai-agents==0.22.2.
        # Strip the server-side schema only; Runner retains local schema validation.
        response = await super()._fetch_response(
            json_instructions(system_instructions, schema), input, settings,
            tools, None, handoffs, span, tracing, stream=False, prompt=prompt)
        usage = response.usage.model_dump(mode='json', exclude_unset=True) if response.usage else None
        choice = response.choices[0] if response.choices else None
        self.response_text = choice.message.content if choice else None
        self.response_metadata = {
            'actual_upstream_model': response.model,
            'response_id': response.id,
            'request_id': getattr(response, '_request_id', None),
            'finish_reason': choice.finish_reason if choice else None,
            'raw_usage': usage,
        }
        allowed = {'stop', 'tool_calls'} if tools or handoffs else {'stop'}
        if choice is None or choice.finish_reason not in allowed:
            raise ModelBehaviorError('DeepSeek response incomplete; inspect recorded finish_reason')
        if not choice.message.content and not choice.message.tool_calls:
            raise ModelBehaviorError('DeepSeek returned empty content')
        return response
