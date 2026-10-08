"""Provider selection shared by historical analysis runners."""
import os
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI


def model_adapter(model, provider, *, client_factory=None):
    client_factory = client_factory or AsyncOpenAI
    if provider == 'openai':
        return model
    if provider == 'deepseek':
        from uteki.agents.runtime.deepseek_model import BASE_URL, DeepSeekChatCompletionsModel
        return DeepSeekChatCompletionsModel(model=model, openai_client=client_factory(
            api_key=os.environ['DEEPSEEK_API_KEY'], base_url=BASE_URL, timeout=60, max_retries=0))
    if provider != 'aihubmix':
        raise ValueError('Unknown provider')
    from .qwen_model import MODELS, QwenChatCompletionsModel
    if model in MODELS:
        return QwenChatCompletionsModel(model=model, openai_client=client_factory(
            api_key=os.environ['AIHUBMIX_API_KEY'], base_url='https://aihubmix.com/v1', timeout=60, max_retries=0))
    return OpenAIChatCompletionsModel(model=model,openai_client=client_factory(
        api_key=os.environ['AIHUBMIX_API_KEY'],base_url='https://aihubmix.com/v1',timeout=60,max_retries=0))
