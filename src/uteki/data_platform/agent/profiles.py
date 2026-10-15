"""Exact kernel/model/role bindings; no ambient model or prompt selection."""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..contracts.common import Contract, Text


class Prompt(Contract):
    path: Text
    version: Text
    sha256: Text


class Route(Contract):
    provider: Literal['openrouter']
    protocol: Literal['chat_completions', 'responses', 'anthropic_messages']
    upstream: tuple[Text, ...] = Field(min_length=1)
    allow_fallbacks: Literal[False]
    require_parameters: Literal[True]


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

    @model_validator(mode='after')
    def protocol_matches(self):
        if (self.kernel == 'claude') != (self.route.protocol == 'anthropic_messages'):
            raise ValueError('protocol does not match the SDK kernel')
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError('duplicate capabilities')
        return self


class LoadedProfile:
    def __init__(self, profile: Profile, text: str):
        self.profile, self.text = profile, text

    def validate(self, *, kernel, role='query', mode='offline'):
        p = self.profile
        if p.kernel != kernel or p.role != role:
            raise ValueError('kernel/role profile mismatch; no fallback')
        if hashlib.sha256(self.text.encode()).hexdigest() != p.prompt.sha256:
            raise ValueError('prompt hash mismatch')
        if not {'tool_calls', 'tool_results'} <= set(p.capabilities):
            raise ValueError('required tool capabilities are not configured')
        if p.reasoning_effort is not None:
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

    def metadata(self):
        return self.profile.model_dump(mode='json')


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
    return LoadedProfile(profile, text)


def validate_distinct_prompts(profiles):
    """Different model profiles cannot silently share one prompt body."""
    seen = {}
    for loaded in profiles:
        p = loaded.profile
        previous = seen.setdefault(p.prompt.sha256, p.model_id)
        if previous != p.model_id:
            raise ValueError('different models require separate prompt bodies')
