"""OpenAI's Runner owns the loop; the binding owns business validation."""
from __future__ import annotations

from copy import deepcopy
import asyncio
import time

from agents import Agent, FunctionTool, ModelSettings, RunConfig, RunHooks, Runner, ToolExecutionConfig, ToolsToFinalOutputResult
from agents.retry import ModelRetrySettings
from agents.exceptions import MaxTurnsExceeded

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding
from .metering import OfflineMeteredModel
from .openai_state import OpenAIState
from ..application.runtime import RuntimeJournal, run_once
from ..contracts.query import parse
from ..contracts.run import RuntimeLimits


# 通过公开 SDK 钩子记录输入和响应；工具结果只有进入下一次模型输入才获得可见性。
class Observer(RunHooks):
    def __init__(self, binding):
        self.binding, self.events = binding, []

    # 保存模型实际输入，并将其中原样出现的 function_call_output 交给共享绑定确认。
    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.events.append(dict(type='model_input', system_prompt=system_prompt, input=deepcopy(input_items)))
        for item in input_items:
            if isinstance(item, dict) and item.get('type') == 'function_call_output':
                self.binding.observe(item.get('output'), boundary='openai_on_llm_start')

    # 保留 SDK 响应标识、结构化输出和原始 usage，作为执行观察而非业务正确性证明。
    async def on_llm_end(self, context, agent, response):
        self.events.append(dict(type='model_response', response_id=response.response_id,
            output=[item.model_dump(mode='json') for item in response.output], raw_usage=response.raw_usage))


# 用冻结配置装配原生 Agent；工具参数、业务调用和终态判断复用共享 ToolBinding。
def make_agent(profile, binding, model, *, mode='offline', skill_capabilities=None):
    profile.validate(kernel='openai',mode=mode)
    if mode=='offline' and getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    if mode=='gateway' and getattr(model,'gateway_metered',False) is not True:
        raise ValueError('gateway entry requires the bound native HTTP adapter')
    tools = []
    for name, envelope in binding.envelopes.items():
        # 默认参数绑定当前工具名，避免循环闭包把所有回调指向最后一个工具。
        async def invoke(context, arguments, name=name):
            return await binding.invoke(name, arguments, call_id=context.tool_call_id)
        # Arbitrary dimension/QName maps are part of the shared contract. They
        # cannot be represented as OpenAI strict objects with fixed keys.
        tools.append(FunctionTool(name=name, description=binding.tool_description(name),
            params_json_schema=binding.tool_schema(name), on_invoke_tool=invoke, strict_json_schema=False,
            needs_approval=True))

    # 只有业务层交付或澄清提交成功，才通知 Runner 结束模型循环。
    async def stop(context, results):
        binding.terminal_requested = binding.terminal is not None
        return ToolsToFinalOutputResult(is_final_output=binding.terminal is not None, final_output=binding.terminal)

    extra={}
    if mode=='gateway':
        upstream=list(profile.profile.route.upstream)
        controls=profile.profile.request_controls
        extra['extra_body']=deepcopy(controls) if controls is not None else dict(reasoning={'enabled':False})
        if profile.profile.route.provider=='openrouter':
            extra['extra_body']['provider']=dict(only=upstream,order=upstream,allow_fallbacks=False,require_parameters=True)
    # OpenRouter's Chat API does not document OpenAI's optional `store`
    # control. Omit it for explicit live profiles. Parallel-tool omission is
    # separately frozen in the profile: general API support does not imply
    # every endpoint admits the parameter with require_parameters=True.
    compatible_route = (mode=='gateway' and profile.profile.route.provider=='openrouter'
                        and profile.profile.request_controls is not None)
    agent_class = Agent
    if profile.profile.skills:
        from agents.sandbox import SandboxAgent
        if skill_capabilities is None:
            raise ValueError('Skill-enabled Agent requires its frozen native capabilities')
        agent_class = SandboxAgent
        extra_agent = dict(capabilities=skill_capabilities)
    else:
        extra_agent = {}
    return agent_class(name='Uteki Data Agent', instructions=profile.text, model=model, tools=tools,
        **extra_agent,
        tool_use_behavior=stop, model_settings=ModelSettings(parallel_tool_calls=profile.profile.parallel_tool_calls,
            max_tokens=profile.profile.max_output_tokens, store=None if compatible_route else False, preserve_raw_usage=True,
            retry=ModelRetrySettings(max_retries=0),**extra))


# 即使供应商一次返回多个工具调用，本地副作用仍由 SDK 按并发数 1 串行执行。
def make_run_config(sandbox_session=None):
    # Provider output may contain several tool calls when its parallel-tool
    # parameter is omitted. Use the official SDK to serialize local side effects.
    extra = {}
    if sandbox_session is not None:
        from agents.sandbox import SandboxRunConfig
        extra['sandbox'] = SandboxRunConfig(session=sandbox_session)
    return RunConfig(tracing_disabled=True,**extra,
        tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1))


# 离线入口只接受脚本模型，经 run_once 绑定配置与限制，防止重复启动同一上下文。
async def run_offline(service, context_ref, profile, *, model, limits, checkpoint=None, recover=False, started=None):
    started=time.monotonic() if started is None else started
    profile.validate(kernel='openai')
    if getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    limits = parse(RuntimeLimits, limits).model_dump(mode='json')
    return await run_once(service, context_ref, dict(profile=profile.metadata(), limits=limits),
        lambda attach: _run(service,context_ref,profile,model=model,limits=limits,checkpoint=checkpoint,
            recover=recover,started=started,attach=attach))


# 网关入口要求显式端点、凭据和持久化绑定；实际网络准入仍由 HTTP 边界逐次检查。
async def run_gateway(service, context_ref, profile, *, gateway_binding, endpoint, credential,
                      limits, execution_contract=None, checkpoint=None, recover=False, started=None):
    """Explicit bound endpoint; live requests still require GatewayHTTP admission."""
    started=time.monotonic() if started is None else started
    profile.validate(kernel='openai',mode='gateway')
    limits=parse(RuntimeLimits,limits).model_dump(mode='json')
    return await run_once(service,context_ref,dict(profile=profile.metadata(),limits=limits,gateway=gateway_binding),
        lambda attach:_run(service,context_ref,profile,model=None,limits=limits,checkpoint=checkpoint,
            recover=recover,started=started,attach=attach,gateway_binding=gateway_binding,
            gateway_options=dict(endpoint=endpoint,credential=credential,execution_contract=execution_contract)))


# 统一运行装配：恢复日志和 SDK 状态，驱动原生 Runner，并汇总真实终态与失败原因。
async def _run(service, context_ref, profile, *, model, limits, checkpoint=None, recover=False, started=None, attach=None,
               gateway_binding=None, gateway_options=None):
    mode='gateway' if gateway_binding is not None else 'offline'
    profile.validate(kernel='openai',mode=mode)
    if mode=='offline' and getattr(model, 'offline_fixture', False) is not True:
        raise ValueError('offline entry requires an explicitly scripted model')
    journal = RuntimeJournal(service, context_ref, profile.metadata(), limits,recover=recover,checkpoint=checkpoint,started=started,
        gateway_binding=gateway_binding)
    if attach is not None:attach(journal)
    if journal.cached is not None:
        return journal.cached
    journal.checkpoint = checkpoint or (lambda phase: None)
    binding = observer = gateway_model = sandbox_session = None
    error = error_code = None
    try:
        journal.guard_transport()
        binding = ToolBinding(service, context_ref, journal=journal)
        observer = Observer(binding)
        durable = OpenAIState(journal,binding)
        if mode=='gateway':
            from .providers.gateway_openai import GatewayOpenAIModel
            gateway_model=GatewayOpenAIModel(journal,durable,**gateway_options)
            adapter=gateway_model
        else:
            adapter=OfflineMeteredModel(model,journal,state=durable)
        skill_capabilities = None
        if profile.profile.skills:
            from .skill_runtime import RuntimeSkills
            skills = RuntimeSkills(profile,journal,available_tools=binding.envelopes)
            sandbox_session,source,work = await skills.openai_session()
            skill_capabilities = skills.openai_capabilities(source,work)
        agent = make_agent(profile,binding,adapter,mode=mode,skill_capabilities=skill_capabilities)
        state = await durable.load(agent)
        journal.begin_continuation()
        # This is the public SDK approval/resume workflow. Runner retains the
        # model/tool loop and turn state; the host persists before authorizing
        # already-permitted business tools, whose own checks still apply.
        # SDK 工具审批中断先形成持久化检查点，再批准任务范围内工具并继续原生循环。
        while True:
            journal.guard_action()
            for interruption in state.get_interruptions():
                state.approve(interruption)
            result = await Runner.run(agent, state, hooks=observer,
                max_turns=journal.limits.native_max_turns, run_config=make_run_config(sandbox_session))
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
    # 无论结束、取消还是异常，都关闭本网关客户端，避免遗留请求连接。
    finally:
        if gateway_model is not None:await gateway_model.close()
        if sandbox_session is not None:await sandbox_session.stop()
    events=observer.events if observer is not None else []
    outcome=(binding.outcome(native_success=success,events=events,profile=profile,error=error,error_code=error_code)
        if binding is not None else journal.failure_outcome(error,error_code=error_code,events=events))
    return journal.finish(outcome)
