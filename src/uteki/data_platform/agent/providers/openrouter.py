"""Explicit OpenRouter configuration only; no request, key discovery or fallback."""
from __future__ import annotations


# 从已加载配置生成显式路由说明；只提供配置数据，不查找密钥或发起请求。
def configuration(loaded):
    p = loaded.profile
    return dict(provider='openrouter', protocol=p.route.protocol, model=p.model_id,
        base_url='https://openrouter.ai/api' if p.kernel == 'claude' else 'https://openrouter.ai/api/v1',
        routing=dict(order=list(p.route.upstream), allow_fallbacks=False, require_parameters=True),
        max_output_tokens=p.max_output_tokens, reasoning_effort=p.reasoning_effort,
        retries=0, prompt_sha256=p.prompt.sha256, verification=p.status)
