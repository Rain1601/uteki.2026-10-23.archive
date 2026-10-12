"""One immutable image through the official DeepSeek Chat Completions endpoint.

The host freezes acquisition and validates JSON locally. This adapter only
transports the supplied pixels; it never downloads, resizes or converts them.
"""
import os

from openai import AsyncOpenAI

from .claude_vision import _frozen_image_packet
from .deepseek_model import BASE_URL, DeepSeekChatCompletionsModel, _validated_extra_body


def validate_vision_configuration(model, reasoning_effort):
    if model != 'deepseek-flash':
        raise ValueError('DeepSeek vision requires the explicitly selected deepseek-flash model')
    if reasoning_effort not in ('high', 'none'):
        raise ValueError('DeepSeek vision reasoning_effort must be high or none')
    return {'thinking': {'type': 'enabled' if reasoning_effort == 'high' else 'disabled'},
            'reasoning_effort': reasoning_effort}


class DeepSeekVisionModel(DeepSeekChatCompletionsModel):
    """Preserve raw usage/finish handling from the shared DeepSeek transport."""

    def __init__(self, model, *, reasoning_effort='high', timeout_seconds=300,
                 openai_client=None):
        self.vision_settings = validate_vision_configuration(model, reasoning_effort)
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 600):
            raise ValueError('DeepSeek vision timeout must be positive and at most 600 seconds')
        if openai_client is not None and (
                str(openai_client.base_url).rstrip('/') != BASE_URL
                or openai_client.max_retries != 0):
            raise ValueError('DeepSeek vision requires its official endpoint and no transport retries')
        self.timeout_seconds = timeout_seconds
        self._owns_client = openai_client is None
        super().__init__(model=model, openai_client=openai_client)

    def _get_client(self):
        if self._client is None:
            key = os.environ.get('DEEPSEEK_API_KEY')
            if not key:
                raise ValueError('DeepSeek vision requires DEEPSEEK_API_KEY')
            self._client = AsyncOpenAI(api_key=key, base_url=BASE_URL,
                                       max_retries=0, timeout=self.timeout_seconds)
        return super()._get_client()

    async def aclose(self):
        if self._owns_client and self._client is not None:
            await self._client.close()

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, *, previous_response_id=None,
                           conversation_id=None, prompt=None):
        if previous_response_id is not None or conversation_id is not None or prompt is not None:
            raise ValueError('DeepSeek vision accepts no prior conversation or hosted prompt')
        self._validated_input(input, model_settings, tools, output_schema, handoffs)
        # The pinned SDK reads _client.base_url for its trace before calling
        # _fetch_response. Instantiate only after the local image contract passes.
        self._get_client()
        return await super().get_response(system_instructions, input, model_settings,
            tools, output_schema, handoffs, tracing, previous_response_id=None,
            conversation_id=None, prompt=None)

    def _validated_input(self, input, model_settings, tools, output_schema, handoffs):
        # Reuse the strict, pure frozen-image verifier; no Claude dispatch occurs.
        _frozen_image_packet(input)
        if tools or handoffs:
            raise ValueError('DeepSeek vision accepts one independent non-streaming image without tools')
        if output_schema is None or output_schema.is_plain_text():
            raise ValueError('DeepSeek vision requires a structured output schema')
        if (type(model_settings.max_tokens) is not int
                or not 0 < model_settings.max_tokens <= 8192):
            raise ValueError('DeepSeek vision requires an explicit output bound of at most 8192 tokens')
        if _validated_extra_body(model_settings) != self.vision_settings:
            raise ValueError('DeepSeek vision settings must match its selected thinking configuration')
        # The pinned SDK converts input_image into Chat image_url. high means
        # original detail in DeepSeek; retain exactly the frozen data URL.
        message = input[0]
        image, text = message['content']
        return [{**message, 'content': [{**image, 'detail': 'high'}, dict(text)]}]

    async def _fetch_response(self, system_instructions, input, model_settings, tools,
                              output_schema, handoffs, span, tracing, stream=False, prompt=None):
        if stream or prompt is not None:
            raise ValueError('DeepSeek vision accepts no stream or hosted prompt')
        converted = self._validated_input(input, model_settings, tools, output_schema, handoffs)
        return await super()._fetch_response(system_instructions, converted, model_settings,
            tools, output_schema, handoffs, span, tracing, stream=False, prompt=None)
