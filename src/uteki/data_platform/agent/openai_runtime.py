"""OpenAI's Runner owns the loop; the binding owns business validation."""
from __future__ import annotations

from copy import deepcopy

from agents import Agent, FunctionTool, ModelSettings, RunConfig, RunHooks, Runner, ToolsToFinalOutputResult
from agents.retry import ModelRetrySettings

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding


class Observer(RunHooks):
    def __init__(self, binding):
        self.binding, self.events = binding, []

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.events.append(dict(type='model_input', system_prompt=system_prompt, input=deepcopy(input_items)))
        for item in input_items:
            if isinstance(item, dict) and item.get('type') == 'function_call_output':
                self.binding.observe(item.get('output'), boundary='openai_on_llm_start')

    async def on_llm_end(self, context, agent, response):
        self.events.append(dict(type='model_response', response_id=response.response_id,
            output=[item.model_dump(mode='json') for item in response.output], raw_usage=response.raw_usage))


def make_agent(profile, binding, model):
    profile.validate(kernel='openai')
    if getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    tools = []
    for name, envelope in ENVELOPES.items():
        async def invoke(context, arguments, name=name):
            return await binding.invoke(name, arguments)
        # Arbitrary dimension/QName maps are part of the shared contract. They
        # cannot be represented as OpenAI strict objects with fixed keys.
        tools.append(FunctionTool(name=name, description=DESCRIPTIONS[name],
            params_json_schema=envelope.model_json_schema(), on_invoke_tool=invoke, strict_json_schema=False))

    async def stop(context, results):
        binding.terminal_requested = binding.delivery is not None
        return ToolsToFinalOutputResult(is_final_output=binding.delivery is not None, final_output=binding.delivery)

    return Agent(name='Uteki Data Agent', instructions=profile.text, model=model, tools=tools,
        tool_use_behavior=stop, model_settings=ModelSettings(parallel_tool_calls=False,
            max_tokens=profile.profile.max_output_tokens, store=False, preserve_raw_usage=True,
            retry=ModelRetrySettings(max_retries=0)))


async def run_offline(service, context_ref, profile, *, model, max_turns):
    """Explicit scripted Model injection; no default provider or live entrypoint."""
    profile.validate(kernel='openai')
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise ValueError('positive explicit SDK max_turns required')
    binding = ToolBinding(service, context_ref)
    observer = Observer(binding)
    agent = make_agent(profile, binding, model)
    error = None
    try:
        from ..contracts.common import canonical
        result = await Runner.run(agent, canonical(binding.context).decode(), hooks=observer,
            max_turns=max_turns, run_config=RunConfig(tracing_disabled=True))
        observer.events.append(dict(type='runner_final_output', output=result.final_output))
        success = binding.terminal_requested and binding.delivery is not None
    except Exception as exc:
        success, error = False, type(exc).__name__+': '+str(exc)
    return binding.outcome(native_success=success, events=observer.events, profile=profile, error=error)
