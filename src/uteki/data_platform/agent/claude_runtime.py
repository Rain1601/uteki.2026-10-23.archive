"""Claude SDK/MCP binding. Claude's native CLI owns the execution loop."""
from __future__ import annotations

from dataclasses import asdict
import asyncio
import time
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher,
    PermissionResultAllow, PermissionResultDeny, ResultMessage, ToolAnnotations,
    create_sdk_mcp_server, tool)

from .binding import DESCRIPTIONS, ENVELOPES, ToolBinding
from .claude_state import ClaudeState
from .providers.claude_transport import OfflineClaudeTransport
from ..application.runtime import RuntimeJournal, run_once
from ..contracts.common import CatalogError, canonical, digest
from ..contracts.query import parse
from ..contracts.run import RuntimeLimits


# 将共享业务工具注册为 SDK MCP 工具，并限制 CLI 只能使用本次 Data 工具集合。
def make_options(profile, binding, *, cwd, cli_path, max_turns, mode='offline', runtime_skills=None):
    profile.validate(kernel='claude',mode=mode)
    if not Path(cwd).is_absolute() or not Path(cli_path).is_absolute():
        raise ValueError('absolute isolated cwd and installed CLI path required')
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise ValueError('positive explicit SDK max_turns required')
    handlers = []
    pending = {}
    for name, envelope in binding.envelopes.items():
        # 用参数指纹关联 PreToolUse 捕获的原生调用 ID，保持幂等记录与真实工具身份一致。
        async def invoke(arguments, name=name):
            identity = digest(canonical(dict(name=name, arguments=arguments)))
            call_id = pending.pop(identity, None)
            if binding.journal is not None and call_id is None:
                raise CatalogError('RECOVERY_REQUIRED', 'MCP invocation has no unambiguous native tool identity')
            output = await binding.invoke(name, arguments, call_id=call_id)
            value = json.loads(output)
            return dict(content=[dict(type='text', text=output)], is_error=value.get('status') == 'error')
        annotations=(ToolAnnotations(maxResultSizeChars=profile.profile.mcp_max_result_chars)
                     if profile.profile.mcp_max_result_chars is not None else None)
        handlers.append(tool(name, binding.tool_description(name), binding.tool_schema(name), annotations=annotations)(invoke))
    permitted = {'mcp__data__'+name for name in binding.envelopes}
    if profile.profile.skills and runtime_skills is None:
        raise ValueError('Skill-enabled Claude options require the frozen Skill runtime')

    def skill_allowed(name,arguments):
        if runtime_skills is None:
            return False
        if name=='Skill':
            return arguments.get('skill') in runtime_skills.names
        if name=='Read':
            return runtime_skills.allow_read(arguments.get('file_path',''),root=cwd,prefix='.claude/skills')
        return False

    # 仅允许终态提交之前的已注册业务工具，其余调用一律交回拒绝结果。
    async def permission(name, arguments, context):
        if (name in permitted or skill_allowed(name,arguments)) and binding.terminal is None:
            return PermissionResultAllow(updated_input=arguments)
        return PermissionResultDeny(message='Outside the Data Agent tool scope')

    # 执行前核验原生会话并登记调用身份；同参数并发调用无法区分时拒绝猜测映射。
    async def pre_tool(event, tool_use_id, context):
        if binding.terminal is None and skill_allowed(event.get('tool_name'),event.get('tool_input',{})):
            if event.get('session_id') != binding.journal.state()['native_session_id']:
                return {'hookSpecificOutput': {'hookEventName':'PreToolUse','permissionDecision':'deny',
                    'permissionDecisionReason':'Skill session differs from the bound run'}}
            runtime_skills.begin_tool(tool_use_id,event['tool_name'],event['tool_input'])
            return {'hookSpecificOutput': {'hookEventName':'PreToolUse','permissionDecision':'allow'}}
        if event.get('tool_name') not in permitted or binding.terminal is not None:
            return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'Only the bounded Data tools may execute before delivery'}}
        if binding.journal is not None:
            try:
                if event.get('session_id') != binding.journal.state()['native_session_id']:
                    raise CatalogError('INVALID_STATE', 'native session differs from the persisted binding')
                name = event['tool_name'].removeprefix('mcp__data__')
                args = event['tool_input']
                identity = digest(canonical(dict(name=name, arguments=args)))
                if identity in pending and pending[identity] != tool_use_id:
                    raise CatalogError('INVALID_STATE', 'identical concurrent native tool calls cannot be disambiguated')
                binding.journal.tool_key(tool_use_id, name, args)
                pending[identity] = tool_use_id
            except (CatalogError,ValueError) as error:
                binding.events.append(dict(type='native_tool_denied', tool_use_id=tool_use_id, reason=str(error)))
                return {'hookSpecificOutput': {'hookEventName':'PreToolUse','permissionDecision':'deny',
                    'permissionDecisionReason':str(error)}}
        return {}

    # 工具完成后打检查点；只有 DataService 已提交终态才请求 CLI 停止。
    async def post_tool(event, tool_use_id, context):
        if runtime_skills is not None and event.get('tool_name') in {'Skill','Read'}:
            runtime_skills.finish_tool(tool_use_id,event.get('tool_response'))
        if binding.journal is not None:
            binding.journal.checkpoint('claude_post_tool')
        if event.get('tool_name') in {'mcp__data__deliver','mcp__data__clarify'} and binding.terminal is not None:
            # A successful MCP handler alone is not a business terminal. Only
            # the immutable DataService delivery permits this native stop.
            binding.terminal_requested = True
            binding.events.append(dict(type='native_stop_requested', boundary='claude_PostToolUse',
                                       tool_use_id=tool_use_id, reason='validated_'+binding.terminal['kind']))
            return {'continue_': False, 'stopReason': 'Validated Data Agent terminal control committed'}
        return {}

    # 只在启用 Skill 时读取隔离目录的项目设置；工具仍受逐次权限边界约束。
    return ClaudeAgentOptions(model=profile.profile.model_id, fallback_model=None,
        system_prompt=profile.text, tools=['Skill','Read'] if runtime_skills else [], allowed_tools=[], permission_mode='default',
        mcp_servers={'data': create_sdk_mcp_server('data', version='1.0.0', tools=handlers)},
        strict_mcp_config=True, can_use_tool=permission,
        hooks={'PreToolUse': [HookMatcher(hooks=[pre_tool])],
               'PostToolUse': [HookMatcher(hooks=[post_tool])]},
        setting_sources=['project'] if runtime_skills else [], skills=list(profile.profile.skills), plugins=[], cwd=cwd, cli_path=cli_path,
        max_turns=max_turns, effort=profile.profile.reasoning_effort,
        thinking={'type': 'disabled'} if profile.profile.reasoning_effort is None else {'type': 'adaptive'})


# 离线入口绑定 fixture 配置及运行限制，实际 CLI 网络仍须经过受控回环传输。
async def run_offline(service, context_ref, profile, *, cwd, cli_path, limits, transport=None, checkpoint=None, recover=False, started=None):
    started=time.monotonic() if started is None else started
    profile.validate(kernel='claude')
    limits = parse(RuntimeLimits, limits).model_dump(mode='json')
    return await run_once(service, context_ref, dict(profile=profile.metadata(), limits=limits),
        lambda attach: _run(service,context_ref,profile,cwd=cwd,cli_path=cli_path,
            limits=limits,transport=transport,checkpoint=checkpoint,recover=recover,started=started,attach=attach))


# 网关入口只装配显式授权范围；请求是否可发、费用是否可继续由共享日志和传输控制。
async def run_gateway(service, context_ref, profile, *, gateway_binding, endpoint, credential,
                      cwd, cli_path, limits, execution_contract=None, checkpoint=None, recover=False, started=None):
    started=time.monotonic() if started is None else started
    profile.validate(kernel='claude',mode='gateway')
    limits=parse(RuntimeLimits,limits).model_dump(mode='json')
    return await run_once(service,context_ref,dict(profile=profile.metadata(),limits=limits,gateway=gateway_binding),
        lambda attach:_run(service,context_ref,profile,cwd=cwd,cli_path=cli_path,limits=limits,
            checkpoint=checkpoint,recover=recover,started=started,attach=attach,gateway_binding=gateway_binding,
            gateway_options=dict(endpoint=endpoint,credential=credential,execution_contract=execution_contract)))


# CLI 拥有原生循环；宿主只负责环境隔离、会话审计、传输边界和最终状态汇总。
async def _run(service, context_ref, profile, *, cwd, cli_path, limits, transport=None, checkpoint=None,
               recover=False, started=None, attach=None, gateway_binding=None, gateway_options=None):
    """Caller supplies an isolated worker with loopback fixture or scripted Transport.

    No live credential/config loading or implicit provider construction occurs.
    The native HTTP boundary is durably gated before every forwarded request.
    """
    mode='gateway' if gateway_binding is not None else 'offline'
    profile.validate(kernel='claude',mode=mode)
    if transport is not None:
        raise ValueError('scripted CLI transport cannot replace the native HTTP metering boundary; use the separate M0 probe')
    if transport is None:
        endpoint = urlsplit(os.environ.get('ANTHROPIC_BASE_URL', ''))
        # 白名单和回环代理共同排除继承环境中的隐式凭据、配置及直连传输路径。
        allowed_env = {'PATH','LANG','PYTHONNOUSERSITE','CLAUDE_CONFIG_DIR',
            'ANTHROPIC_BASE_URL','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC','CLAUDE_CODE_MAX_OUTPUT_TOKENS',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','LC_CTYPE','__CF_USER_TEXT_ENCODING'}
        if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or not endpoint.port
                or endpoint.username is not None or endpoint.query or endpoint.fragment
                or set(os.environ) - allowed_env
                or os.environ.get('ANTHROPIC_AUTH_TOKEN') != ('uteki-offline-fixture' if mode=='offline' else 'uteki-gateway-worker')
                or os.environ.get('ANTHROPIC_API_KEY') != ''
                or any(os.environ.get(k) != os.environ['ANTHROPIC_BASE_URL'] for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'))
                or Path(os.environ.get('CLAUDE_CONFIG_DIR', '')).resolve() != (Path(cwd)/'claude-config').resolve()
                or os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS') != str(profile.profile.max_output_tokens)):
            raise ValueError('native execution requires an isolated loopback-only worker environment; unexpected variable names: '+','.join(sorted(set(os.environ)-allowed_env)))
    journal = RuntimeJournal(service, context_ref, profile.metadata(), limits,recover=recover,checkpoint=checkpoint,started=started,
        gateway_binding=gateway_binding)
    if attach is not None:attach(journal)
    if journal.cached is not None:
        return journal.cached
    journal.checkpoint = checkpoint or (lambda phase: None)
    binding = bridge = runtime_skills = None
    events, terminal, error, error_code = [], None, None, None
    # 从实际转发的原生请求观察工具结果，避免把 MCP 处理器返回误认为模型已收到。
    def observe_wire(request):
        if runtime_skills is not None:
            runtime_skills.observe_claude_request(request)
        for message in request.get('messages', []):
            blocks = message.get('content', [])
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if block.get('type') != 'tool_result':
                    continue
                content = block.get('content', '')
                pieces = [content] if isinstance(content,str) else [p.get('text','') for p in content if p.get('type')=='text']
                for piece in pieces:
                    binding.observe(piece, boundary='claude_forwarded_native_request')
    try:
        journal.guard_transport()
        binding = ToolBinding(service, context_ref, journal=journal)
        if profile.profile.skills:
            from .skill_runtime import RuntimeSkills
            from ..catalog.database import ensure_directory
            runtime_skills = RuntimeSkills(profile,journal,available_tools=binding.envelopes)
            runtime_skills.stage(ensure_directory(Path(cwd).resolve(),'.claude/skills'))
        options = make_options(profile, binding, cwd=cwd, cli_path=cli_path, max_turns=journal.limits.native_max_turns,
            mode=mode,runtime_skills=runtime_skills)
        # 恢复必须复用持久化的原生 session_id；首次运行才显式创建该会话。
        if journal.resuming:
            options.resume = journal.state()['native_session_id']
        else:
            options.session_id = journal.state()['native_session_id']
        state = ClaudeState(journal, binding, cwd=cwd, cli_path=cli_path)
        if gateway_binding is None:
            bridge = OfflineClaudeTransport(journal, os.environ['ANTHROPIC_BASE_URL'],
                before_request=journal.guard_action, observed_request=observe_wire, validate_request=state.validate_request)
        else:
            from .providers.gateway_claude import GatewayClaudeTransport
            bridge = GatewayClaudeTransport(journal,observed_request=observe_wire,
                validate_request=state.validate_request,**gateway_options)
        async with bridge:
            prompt = state.prepare()
            journal.begin_continuation()
            options.env = {k:bridge.base_url for k in ('ANTHROPIC_BASE_URL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')}
            options.env['ANTHROPIC_AUTH_TOKEN'] = bridge.token
            timeout=max(0,journal.deadline-time.monotonic()) if mode=='gateway' else None
            async with asyncio.timeout(timeout), ClaudeSDKClient(options=options) as client:
                try:
                    await client.query(prompt)
                    # 助手消息先做原件审计，ResultMessage 只记录 SDK 终态，业务终态另行校验。
                    async for message in client.receive_response():
                        events.append(dict(type=type(message).__name__, data=asdict(message)))
                        if isinstance(message, AssistantMessage):
                            # Official SDK error messages are diagnostics, not
                            # model evidence. Preserve them before classifying;
                            # do not mislabel an API failure as missing identity.
                            if message.error is not None:
                                blocked=next((e for e in reversed(bridge.events) if e.get('status')=='blocked_or_failed'),{})
                                code=blocked.get('error_code')
                                if code:
                                    raise CatalogError('INVALID_REQUEST','native request rejected before dispatch: '+code)
                                raise CatalogError('MODEL_ERROR','Claude SDK assistant error: '+str(message.error))
                            state.record_assistant(message)
                        if isinstance(message, ResultMessage):
                            terminal = message
                except asyncio.CancelledError:
                    journal.stop('cancelled')
                    raise
    except asyncio.CancelledError:
        journal.stop('cancelled')
        error = 'CANCELLED'
    except TimeoutError:
        journal.stop('wall_time')
        error='GATEWAY_HOST_DEADLINE'
    except Exception as exc:
        error_code = getattr(exc,'code',None)
        error = type(exc).__name__+': '+str(exc)
    events.append(dict(type='native_transport', requests=bridge.events if bridge is not None else []))
    if terminal is not None and terminal.subtype == 'error_max_turns':
        journal.stop('native_max_turns')
    success = (terminal is not None and not terminal.is_error and terminal.subtype == 'success'
               and terminal.session_id == journal.state()['native_session_id'] and error is None)
    outcome=(binding.outcome(native_success=success,events=events,profile=profile,error=error,error_code=error_code)
        if binding is not None else journal.failure_outcome(error,error_code=error_code,events=events))
    return journal.finish(outcome)
