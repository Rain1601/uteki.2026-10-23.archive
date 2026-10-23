"""DeepSeek usage is an estimate, never an OpenRouter generation bill."""
from .openrouter_evidence import observe_response, response_bytes, _events, _json
from .live_policy import price_tokens


# 先保存原始响应及完整性，再用报告的 token 量估算费用；始终保留为估算而非账单。
def record_response(budget, key, capture, *, profile, pricing):
    observed = observe_response(capture)
    complete = capture['transport_complete'] and (capture['status'] != 200 or observed['protocol_complete'])
    current = budget.record_response(key, dict(complete=complete, http=capture,
        observation=observed, origin='deepseek', billing_observation_withheld=False),
        billed_usd=None, outcome_known=complete)
    if not complete or capture['status'] != 200:
        return current
    raw = response_bytes(capture)
    # Chat 与 Messages 的用量字段不同，按明确协议读取，不凭 SDK 会话汇总猜测用量。
    if capture['protocol'] == 'chat_completions':
        value = _json(raw)
        model = value.get('model')
        usage = value.get('usage', {})
        input_tokens, output_tokens = usage.get('prompt_tokens'), usage.get('completion_tokens')
    else:
        events = _events(raw)
        message = next(e['message'] for e in events if e.get('type') == 'message_start')
        model = message.get('model')
        usage = dict(message.get('usage', {}))
        for event in events:
            if event.get('type') == 'message_delta':
                usage.update(event.get('usage', {}))
        # 缓存读写输入也纳入输入量，并统一使用冻结的未缓存峰值单价形成保守估算。
        counts = [usage.get('input_tokens'), usage.get('cache_read_input_tokens', 0),
                  usage.get('cache_creation_input_tokens', 0)]
        if any(type(n) is not int or n < 0 for n in counts):
            raise ValueError('missing_or_invalid_deepseek_input_usage')
        input_tokens, output_tokens = sum(counts), usage.get('output_tokens')
    # 响应模型必须与请求冻结配置一致，否则不能把此用量归入目标模型。
    if model != profile['model_id']:
        raise ValueError('deepseek_response_model_differs_from_requested_model')
    amount = price_tokens(pricing, input_tokens, output_tokens)
    return budget.retain_usage_estimate(key, estimated_usd=str(amount), evidence=dict(
        response_sha256=capture['body_sha256'], model=model, usage=usage, pricing=pricing,
        method='reported_tokens_at_peak_uncached_price', provider='deepseek'))
