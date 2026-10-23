"""Small, explicit multi-provider admission and conservative text pricing."""
from decimal import Decimal

from ...contracts.common import canonical, digest


# 真实调用必须匹配已授权执行契约、根额度、scope 配置和精确端点，不能仅凭模型配置放行。
def admit(contract, root, scope, endpoint):
    if (not isinstance(contract, dict) or contract.get('schema') != 'uteki-live-function-v1'
            or contract.get('inference_authorized') is not True
            or contract.get('limit_usd') != root['limit_usd']
            or contract.get('max_requests') != root['max_requests']
            or root['policy'].get('execution_contract_sha256') != digest(canonical(contract))
            or root['policy'].get('retain_usage_estimate_reservations') is not True):
        raise ValueError('live_execution_contract_not_authorized_or_bound')
    frozen = contract.get('scopes', {}).get(scope['scope_id'])
    policy = scope['policy']
    if (not isinstance(frozen, dict) or frozen.get('profile') != policy['profile']
            or frozen.get('transport') != policy['transport']
            or frozen.get('max_requests') != scope['max_requests']):
        raise ValueError('live_scope_differs_from_authorized_contract')
    provider = policy['profile']['route']['provider']
    if provider == 'deepseek':
        expected = ('https://api.deepseek.com/anthropic'
                    if policy['profile']['kernel'] == 'claude' else 'https://api.deepseek.com')
        prefix = '/anthropic' if policy['profile']['kernel'] == 'claude' else ''
    elif provider == 'openrouter':
        expected, prefix = 'https://openrouter.ai/api', '/api'
    else:
        raise ValueError('unsupported_live_provider')
    if endpoint != expected:
        raise ValueError('live_endpoint_differs_from_official_provider')
    # 计价依据必须显式携带币种、来源、观察时间及有限正价格，缺失时拒绝估算。
    price = frozen['pricing']
    if (price.get('currency') != 'USD' or not price.get('source') or not price.get('observed_at')
            or any(not Decimal(str(price[k])).is_finite() or Decimal(str(price[k])) <= 0
                   for k in ('input_per_million', 'output_per_million'))):
        raise ValueError('explicit_finite_official_pricing_required')
    return prefix, frozen


# 按冻结的每百万 token 单价计算 Decimal 金额；这是用量估算，不是供应商账单。
def price_tokens(pricing, input_tokens, output_tokens):
    if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
        raise ValueError('invalid_usage_counts')
    return (Decimal(input_tokens) * Decimal(str(pricing['input_per_million']))
             + Decimal(output_tokens) * Decimal(str(pricing['output_per_million']))) / Decimal(1_000_000)


# 以 UTF-8 请求字节数和固定协议余量保守预留输入费用，再加最大输出预算。
def reserve(pricing, raw, max_tokens):
    # Same conservative text-envelope rule as infrastructure.reserve_request:
    # one token per UTF-8 byte plus 16k for protocol/schema framing.
    return str(price_tokens(pricing, len(raw) + 16384, max_tokens))
