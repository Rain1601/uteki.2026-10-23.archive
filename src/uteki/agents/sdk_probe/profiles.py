"""Exact model/kernel prompt binding and explicit offline configuration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

OPENROUTER_OPENAI_URL = 'https://openrouter.ai/api/v1'
OPENROUTER_ANTHROPIC_URL = 'https://openrouter.ai/api'


@dataclass(frozen=True)
class PromptProfile:
    model_id: str
    kernel: str
    version: str
    status: str
    text: str
    sha256: str


def load_profile(path: Path, *, model_id: str, kernel: str) -> PromptProfile:
    data = json.loads(path.read_text())
    if set(data) != {'model_id', 'kernel', 'version', 'status', 'instructions'}:
        raise ValueError('invalid prompt profile')
    if data['model_id'] != model_id or data['kernel'] != kernel:
        raise ValueError('model/kernel profile mismatch; no fallback')
    if kernel not in {'openai', 'claude'} or data['status'] != 'offline_fixture_only':
        raise ValueError('this M0 entrypoint accepts offline profiles only')
    if not model_id.startswith('fixture/'):
        raise ValueError('real models require separately frozen live-run configuration')
    if not all(isinstance(data[k], str) and data[k].strip() for k in data):
        raise ValueError('empty prompt profile field')
    return PromptProfile(model_id, kernel, data['version'], data['status'],
                         data['instructions'], hashlib.sha256(data['instructions'].encode()).hexdigest())


def worker_environment(*, path: str, config_directory: Path) -> dict[str, str]:
    """Explicit fresh worker env; never merge ambient credentials/routing/settings.

    Caller must pass this to a new process. Claude options.env alone is an
    overlay on os.environ, not an environment-isolation boundary.
    """
    if not config_directory.is_absolute():
        raise ValueError('absolute isolated config directory required')
    return {'PATH': path, 'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1',
            'CLAUDE_CONFIG_DIR': str(config_directory),
            'ANTHROPIC_BASE_URL': OPENROUTER_ANTHROPIC_URL,
            'ANTHROPIC_API_KEY': '', 'ANTHROPIC_AUTH_TOKEN': 'offline-not-a-credential',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'}
