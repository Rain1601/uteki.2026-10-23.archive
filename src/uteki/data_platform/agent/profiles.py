"""Exact kernel/model/role bindings; no ambient model or prompt selection."""
from __future__ import annotations

import hashlib
import importlib.metadata
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..contracts.common import Contract, Text


# 提示词的路径、版本和内容摘要共同形成冻结身份，运行时不能静默替换正文。
class Prompt(Contract):
    path: Text
    version: Text
    sha256: Text


# 显式声明供应商、协议和上游路由，配置层禁止自动回退并要求支持指定参数。
class Route(Contract):
    provider: Literal['openrouter', 'deepseek']
    protocol: Literal['chat_completions', 'responses', 'anthropic_messages']
    upstream: tuple[Text, ...] = Field(min_length=1)
    allow_fallbacks: Literal[False]
    require_parameters: Literal[True]


# 一份配置绑定 SDK 内核、模型、角色、提示词和请求限制；能力状态与运行授权分开。
class Profile(Contract):
    schema_version: Literal['uteki-agent-profile-v1']
    kernel: Literal['openai', 'claude']
    model_id: Text
    role: Literal['query', 'plan', 'extract']
    sdk_version: Text
    status: Literal['offline_fixture_only', 'unverified', 'live_verified']
    capabilities: tuple[Text, ...]
    prompt: Prompt
    route: Route
    max_output_tokens: int = Field(gt=0)
    reasoning_effort: Literal['low', 'medium', 'high'] | None
    # Explicit provider-native controls; None retains the original frozen wire contract.
    request_controls: dict | None = None
    # False requests one tool per model response; None omits the provider
    # parameter. Local execution remains serial in either case.
    parallel_tool_calls: Literal[False] | None = False
    # Claude Code's per-tool inline-result threshold, in characters. This is
    # independent of model output tokens and the gateway request byte limit.
    mcp_max_result_chars: int | None = Field(default=None, ge=1, le=500000)
    # Explicit opt-in. Omitted fields preserve historical profile identities.
    skills: tuple[Text, ...] = ()
    model_version: Text | None = None

    # 校验跨字段约束：协议必须匹配内核，供应商参数及工具并行开关必须显式适配。
    @model_validator(mode='after')
    def protocol_matches(self):
        if (self.kernel == 'claude') != (self.route.protocol == 'anthropic_messages'):
            raise ValueError('protocol does not match the SDK kernel')
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError('duplicate capabilities')
        if len(set(self.skills)) != len(self.skills) or any(
                len(name)>64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) for name in self.skills):
            raise ValueError('invalid or duplicate Skill names')
        if self.mcp_max_result_chars is not None and self.kernel != 'claude':
            raise ValueError('MCP inline-result threshold requires the Claude SDK kernel')
        if self.parallel_tool_calls is None and not (
                self.kernel == 'openai' and self.route.provider == 'openrouter'
                and self.route.protocol == 'chat_completions' and self.request_controls is not None):
            raise ValueError('parallel tool parameter omission requires an explicit OpenRouter Chat profile')
        if self.request_controls is not None:
            permitted = ({'thinking', 'reasoning_effort'} if self.route.provider == 'deepseek'
                         else {'reasoning'}) if self.kernel == 'openai' else {'thinking', 'output_config'}
            if not self.request_controls or set(self.request_controls) - permitted:
                raise ValueError('unsupported provider request controls')
        if self.route.provider == 'deepseek' and self.route.upstream != ('deepseek',):
            raise ValueError('DeepSeek direct requires its own explicit upstream')
        return self


# 将已解析配置与经过摘要核验的提示词正文一起传递，避免运行阶段重新猜选配置。
class LoadedProfile:
    def __init__(self, profile: Profile, text: str, *, config_root: Path | None = None):
        self.profile, self.text = profile, text
        self.config_root = config_root

    # 核验实际安装 SDK 版本、必要能力和模式；离线模式只接受明确的 fixture 模型。
    def validate(self, *, kernel, role='query', mode='offline'):
        p = self.profile
        if p.kernel != kernel or p.role != role:
            raise ValueError('kernel/role profile mismatch; no fallback')
        if hashlib.sha256(self.text.encode()).hexdigest() != p.prompt.sha256:
            raise ValueError('prompt hash mismatch')
        if not {'tool_calls', 'tool_results'} <= set(p.capabilities):
            raise ValueError('required tool capabilities are not configured')
        if p.reasoning_effort is not None and p.request_controls is None:
            raise ValueError('reasoning settings require a separately verified model capability profile')
        package = 'openai-agents' if kernel == 'openai' else 'claude-agent-sdk'
        if importlib.metadata.version(package) != p.sdk_version:
            raise ValueError('installed SDK differs from the frozen profile')
        if mode == 'offline':
            if p.status != 'offline_fixture_only' or not p.model_id.startswith('fixture/'):
                raise ValueError('offline execution requires a fixture profile')
        elif mode == 'gateway':
            if p.status not in {'unverified','live_verified'} or p.model_id.startswith('fixture/'):
                raise ValueError('gateway execution requires an explicit candidate model profile')
            # This validates configuration, not authorization. The bound HTTP
            # transport separately admits the exact endpoint and contract.
        else:
            raise ValueError('unsupported execution mode')

    # 未启用的新字段不进入旧配置身份，保持历史持久化绑定及摘要的兼容性。
    def metadata(self):
        value = self.profile.model_dump(mode='json')
        if not self.profile.skills:
            value.pop('skills')
        if self.profile.model_version is None:
            value.pop('model_version')
        if self.profile.request_controls is None:
            value.pop('request_controls')  # Preserve existing frozen profile identities.
        if self.profile.parallel_tool_calls is False:
            value.pop('parallel_tool_calls')  # Existing profiles keep their original identity.
        if self.profile.mcp_max_result_chars is None:
            value.pop('mcp_max_result_chars')  # Keep historical bindings unchanged.
        return value


# 解析符号链接后检查配置及提示词均位于指定根目录，再核验模型身份和提示词摘要。
def load_profile(path: Path, *, config_root: Path, kernel: str, model_id: str, role: str) -> LoadedProfile:
    """Resolve prompt files inside the explicit configuration root, including symlinks."""
    root = config_root.resolve(strict=True)
    path = path.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError('profile is outside configuration root')
    profile = Profile.model_validate_json(path.read_bytes())
    if (profile.kernel, profile.model_id, profile.role) != (kernel, model_id, role):
        raise ValueError('model/kernel/role profile mismatch; no fallback')
    relative = Path(profile.prompt.path)
    if relative.is_absolute():
        raise ValueError('prompt path must be relative to configuration root')
    prompt_path = (root/relative).resolve(strict=True)
    if not prompt_path.is_relative_to(root):
        raise ValueError('prompt escapes configuration root')
    text = prompt_path.read_text(encoding='utf-8')
    if not text.strip() or hashlib.sha256(text.encode()).hexdigest() != profile.prompt.sha256:
        raise ValueError('empty or changed prompt')
    return LoadedProfile(profile, text, config_root=root)


# 不同模型必须拥有独立提示词正文；以内容摘要识别静默复用，而非只比较文件名。
def validate_distinct_prompts(profiles):
    """Different model profiles cannot silently share one prompt body."""
    seen = {}
    for loaded in profiles:
        p = loaded.profile
        previous = seen.setdefault(p.prompt.sha256, p.model_id)
        if previous != p.model_id:
            raise ValueError('different models require separate prompt bodies')
