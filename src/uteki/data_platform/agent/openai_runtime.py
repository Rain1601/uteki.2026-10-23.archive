"""OpenAI's Runner owns the loop; the binding owns business validation."""
from __future__ import annotations

from copy import deepcopy
import asyncio
import time

from agents import Agent, FunctionTool, ModelSettings, RunConfig, RunHooks, Runner, ToolsToFinalOutputResult
from agents.retry import ModelRetrySettings
from agents.exceptions import MaxTurnsExceeded

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding
from .metering import OfflineMeteredModel
from .openai_state import OpenAIState
from ..application.runtime import RuntimeJournal, run_once
from ..contracts.query import parse
from ..contracts.run import RuntimeLimits


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
            return await binding.invoke(name, arguments, call_id=context.tool_call_id)
        # Arbitrary dimension/QName maps are part of the shared contract. They
        # cannot be represented as OpenAI strict objects with fixed keys.
        tools.append(FunctionTool(name=name, description=DESCRIPTIONS[name],
            params_json_schema=envelope.model_json_schema(), on_invoke_tool=invoke, strict_json_schema=False,
            needs_approval=True))

    async def stop(context, results):
        binding.terminal_requested = binding.terminal is not None
        return ToolsToFinalOutputResult(is_final_output=binding.terminal is not None, final_output=binding.terminal)

    return Agent(name='Uteki Data Agent', instructions=profile.text, model=model, tools=tools,
        tool_use_behavior=stop, model_settings=ModelSettings(parallel_tool_calls=False,
            max_tokens=profile.profile.max_output_tokens, store=False, preserve_raw_usage=True,
            retry=ModelRetrySettings(max_retries=0)))


async def run_offline(service, context_ref, profile, *, model, limits, checkpoint=None, recover=False, started=None):
    started=time.monotonic() if started is None else started
    profile.validate(kernel='openai')
    if getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    limits = parse(RuntimeLimits, limits).model_dump(mode='json')
    return await run_once(service, context_ref, dict(profile=profile.metadata(), limits=limits),
        lambda attach: _run_offline(service,context_ref,profile,model=model,limits=limits,checkpoint=checkpoint,
            recover=recover,started=started,attach=attach))


async def _run_offline(service, context_ref, profile, *, model, limits, checkpoint=None, recover=False, started=None, attach=None):
    """Explicit scripted Model injection; no default provider or live entrypoint."""
    profile.validate(kernel='openai')
    if getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    journal = RuntimeJournal(service, context_ref, profile.metadata(), limits,recover=recover,checkpoint=checkpoint,started=started)
    if attach is not None:attach(journal)
    if journal.cached is not None:
        return journal.cached
    journal.checkpoint = checkpoint or (lambda phase: None)
    binding = observer = None
    error = error_code = None
    try:
        journal.guard_transport()
        binding = ToolBinding(service, context_ref, journal=journal)
        observer = Observer(binding)
        durable = OpenAIState(journal,binding)
        agent = make_agent(profile, binding, OfflineMeteredModel(model, journal,state=durable))
        state = await durable.load(agent)
        journal.begin_continuation()
        # This is the public SDK approval/resume workflow. Runner retains the
        # model/tool loop and turn state; the host persists before authorizing
        # already-permitted business tools, whose own checks still apply.
        while True:
            journal.guard_action()
            for interruption in state.get_interruptions():
                state.approve(interruption)
            result = await Runner.run(agent, state, hooks=observer,
                max_turns=journal.limits.native_max_turns, run_config=RunConfig(tracing_disabled=True))
            if not result.interruptions:
                break
            state = result.to_state()
            durable.save(state)
        observer.events.append(dict(type='runner_final_output', output=result.final_output))
        success = binding.terminal_requested and binding.terminal is not None
    except asyncio.CancelledError:
        journal.stop('cancelled')
        success, error = False, 'CANCELLED'
    except MaxTurnsExceeded as exc:
        journal.stop('native_max_turns')
        success, error = False, type(exc).__name__+': '+str(exc)
    except Exception as exc:
        error_code = getattr(exc,'code',None)
        success, error = False, type(exc).__name__+': '+str(exc)
    events=observer.events if observer is not None else []
    outcome=(binding.outcome(native_success=success,events=events,profile=profile,error=error,error_code=error_code)
        if binding is not None else journal.failure_outcome(error,error_code=error_code,events=events))
    return journal.finish(outcome)
