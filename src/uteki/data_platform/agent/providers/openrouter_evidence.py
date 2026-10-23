"""Raw HTTP observations and OpenRouter billing, independent of SDK parsing.

No credentials, networking, retries or runtime authorization live here. The
owning transport must supply authentic response bytes and bounded chunks.
Model content is still interpreted by the official SDK, never by this adapter.
"""
from __future__ import annotations

import base64
from decimal import Decimal
import http.client
import json
import re

from ....infrastructure.run_budget import RequestIdentityConflict, RequestRecoveryRequired
from ...contracts.common import canonical, digest


_PROTOCOLS = {'chat_completions', 'anthropic_messages', 'generation'}
_HEADERS = {'content-type', 'content-length', 'content-encoding',
            'x-generation-id', 'x-request-id', 'request-id'}


# 对响应 JSON 同样拒绝重复键，避免不同解析结果影响身份和费用核验。
def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_field')
        value[key] = item
    return value


# 非有限数字不构成合法的费用或响应证据，解析时即拒绝。
def _constant(_):
    raise ValueError('nonfinite_json_number')


# 用 Decimal 保留响应费用精度，并使用严格键及数值检查。
def _json(raw):
    return json.loads(raw.decode('utf-8'), parse_float=Decimal,
                      parse_constant=_constant, object_pairs_hook=_object)


# 观测值中的 Decimal 转为十进制文本，持久化时避免二进制浮点误差。
def _serializable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serializable(v) for v in value]
    return value


# 仅接受明确的 gen- 命名空间，不把其他消息 ID 推测成 OpenRouter generation ID。
def _generation(value):
    return isinstance(value, str) and len(value) <= 128 and bool(re.fullmatch(r'gen-[0-9A-Za-z-]+', value))


# 账单金额只接受有效非负数值，不把字符串、布尔值或上游估算隐式转换成实付费用。
def _cost(value):
    # No coercion of booleans, strings, upstream costs or SDK estimates.
    if type(value) not in {int, Decimal}:
        raise ValueError('invalid_billed_cost')
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError('invalid_billed_cost')
    return str(amount)


# 有界保存 HTTP 实体原始字节及必要响应头；中断、超限和长度冲突都保留已有前缀。
def capture_response(protocol, status, headers, chunks, *, max_bytes):
    """Consume bounded HTTP entity chunks, retaining a prefix on failure.

    This preserves bytes before Content-Encoding decompression, not TLS frames
    or HTTP chunk framing. The owning client must validate chunk framing.
    Only identity/content-type response headers are retained; authentication and
    arbitrary cookies/headers do not enter the durable application record.
    """
    if protocol not in _PROTOCOLS or type(status) is not int or not 100 <= status <= 599:
        raise ValueError('Explicit protocol and HTTP status required')
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('Explicit positive response byte bound required')
    selected = []
    for key, value in headers:
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError('HTTP headers must be text pairs')
        if key.lower() in _HEADERS:
            selected.append([key.lower(), value])
    body, error = bytearray(), None
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError('Transport chunks must be bytes')
            room = max_bytes - len(body)
            body.extend(chunk[:room])
            if len(chunk) > room:
                error = 'response_too_large'
                break
    except http.client.IncompleteRead as exc:
        body.extend(exc.partial[:max_bytes-len(body)])
        error = 'IncompleteRead'
    except (OSError, http.client.HTTPException) as exc:
        error = type(exc).__name__
    raw = bytes(body)
    lengths = [v.strip() for k,v in selected if k == 'content-length']
    if error is None and lengths:
        if len(set(lengths)) != 1 or not re.fullmatch(r'[0-9]{1,20}', lengths[0]):
            error = 'invalid_content_length'
        elif int(lengths[0]) != len(raw):
            error = 'content_length_mismatch'
    return dict(schema='gateway-http-observation-v1', protocol=protocol, status=status,
        headers=selected, transport_complete=error is None, error=error,
        body_base64=base64.b64encode(raw).decode('ascii'), body_sha256=digest(raw), byte_length=len(raw))


# 消费收据前复核格式、摘要、字节数及完整性字段，防止存储损坏被当作可信响应。
def response_bytes(capture):
    if capture.get('schema') != 'gateway-http-observation-v1':
        raise ValueError('Unknown HTTP observation schema')
    raw = base64.b64decode(capture['body_base64'], validate=True)
    if (digest(raw) != capture['body_sha256'] or len(raw) != capture['byte_length']
            or type(capture['transport_complete']) is not bool
            or capture['transport_complete'] != (capture['error'] is None)):
        raise ValueError('Corrupt HTTP observation')
    return raw


# 只解析 SSE 信封及事件类型，用于完整性与计量观察；模型正文和工具参数由 SDK 解释。
def _events(raw):
    """Read SSE envelopes only; never assemble model text or tool arguments."""
    text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    if not text.endswith('\n\n'):
        raise ValueError('incomplete_sse_event')
    events = []
    done = False
    for block in text.split('\n\n'):
        lines, name = [], None
        for line in block.split('\n'):
            if line.startswith('data:'):
                lines.append(line[5:].removeprefix(' '))
            elif line.startswith('event:'):
                if name is not None:
                    raise ValueError('duplicate_sse_event_name')
                name = line[6:].strip()
        if not lines:
            continue
        if done:
            raise ValueError('sse_data_after_done')
        payload = '\n'.join(lines)
        # OpenRouter may append its SSE sentinel after the native Messages
        # terminal event. It is not JSON and cannot replace message_stop.
        if payload == '[DONE]':
            if name not in (None, 'data') or not events or events[-1].get('type') != 'message_stop':
                raise ValueError('sse_done_without_message_stop')
            done = True
            continue
        event = _json(payload.encode('utf-8'))
        if not isinstance(event, dict) or (name is not None and name != event.get('type')):
            raise ValueError('invalid_sse_envelope')
        events.append(event)
    return events


# 提取可证实的协议完成、generation 身份、用量和账单；不据此宣称业务成功或路由正确。
def observe_response(capture):
    """Return observed identity/usage without asserting route or business success."""
    raw = response_bytes(capture)
    result = dict(protocol_complete=False, generation_id=None, model=None, provider=None,
                  usage_observations=[], billed_usd=None, billing_source=None, issues=[])
    try:
        headers = {}
        for key, value in capture['headers']:
            if key in headers and headers[key] != value:
                raise ValueError('conflicting_response_header')
            headers[key] = value
        header_id = headers.get('x-generation-id')
        if header_id is not None:
            if not _generation(header_id):
                raise ValueError('invalid_generation_header')
            result['generation_id'] = header_id
        if not capture['transport_complete']:
            result['issues'].append(capture['error'])
            return result
        if capture['status'] != 200:
            result['issues'].append('http_error')
            return result
        media = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        # Official HTTP clients decode response.content while retaining the
        # original Content-Encoding header. Only an explicitly tagged SDK
        # capture may parse those decoded bytes; raw-wire captures stay strict.
        if (headers.get('content-encoding', 'identity').strip().lower() != 'identity'
                and capture.get('body_representation') != 'decoded_by_httpx2'):
            raise ValueError('unsupported_content_encoding')
        protocol = capture['protocol']
        # Messages 必须有唯一起止事件及明确 stop_reason；传输 EOF 本身不等于模型流结束。
        if protocol == 'anthropic_messages' and media == 'text/event-stream':
            events = [e for e in _events(raw) if e.get('type') != 'ping']
            starts = [e.get('message') for e in events if e.get('type') == 'message_start']
            if (len(starts) != 1 or not events or events[0].get('type') != 'message_start'
                    or events[-1].get('type') != 'message_stop'
                    or sum(e.get('type') == 'message_stop' for e in events) != 1
                    or any(e.get('type') == 'error' for e in events)):
                raise ValueError('incomplete_messages_stream')
            message = starts[0]
            deltas = [e for e in events if e.get('type') == 'message_delta']
            if (not isinstance(message, dict) or not deltas
                    or not isinstance(deltas[-1].get('delta'), dict)
                    or not isinstance(deltas[-1]['delta'].get('stop_reason'), str)):
                raise ValueError('missing_messages_finish')
            usages = [message.get('usage')] + [e.get('usage') for e in deltas]
        elif media == 'application/json':
            value = _json(raw)
            if not isinstance(value, dict):
                raise ValueError('invalid_response_object')
            if protocol == 'generation':
                message = value.get('data')
                if not isinstance(message, dict):
                    raise ValueError('missing_generation_data')
                usages = [message]
            else:
                message, usages = value, [value.get('usage')]
                if protocol == 'chat_completions':
                    choices = value.get('choices')
                    if (value.get('object') != 'chat.completion' or not isinstance(choices, list)
                            or not choices or any(not isinstance(c, dict)
                                or not isinstance(c.get('finish_reason'), str) for c in choices)):
                        raise ValueError('incomplete_chat_completion')
                elif (value.get('type') != 'message' or not isinstance(value.get('stop_reason'), str)):
                    raise ValueError('incomplete_message')
        else:
            raise ValueError('unsupported_response_media')
        # 优先保留原始身份；头部与正文 generation 冲突时，后续不得猜测使用哪一个。
        response_id = message.get('id')
        if not isinstance(response_id, str) or not response_id:
            raise ValueError('missing_response_identity')
        if protocol == 'generation' and not _generation(response_id):
            raise ValueError('invalid_generation_data_identity')
        if _generation(response_id):
            if header_id is not None and header_id != response_id:
                raise ValueError('generation_identity_conflict')
            result['generation_id'] = response_id
        # A native msg_* ID is not converted to an assumed gen-* identity.
        result.update(model=message.get('model'),
            provider=message.get('provider_name') if protocol == 'generation' else message.get('provider'),
            usage_observations=_serializable([u for u in usages if isinstance(u, dict)]),
            protocol_complete=True)
        if result['generation_id'] is None:
            result['issues'].append('generation_identity_unavailable')
        elif protocol == 'generation':
            result.update(billed_usd=_cost(message.get('total_cost')), billing_source='generation.total_cost')
        # 只有明确的 Chat usage.cost 或 generation.total_cost 才作为账单；token 数仍是用量。
        elif protocol == 'chat_completions' and isinstance(message.get('usage'), dict):
            value = message['usage'].get('cost')
            if value is not None:
                result.update(billed_usd=_cost(value), billing_source='chat.usage.cost')
        elif protocol == 'anthropic_messages' and usages and isinstance(usages[-1], dict):
            # OpenRouter reports account cost in the final message_delta usage.
            # Its Messages adapter can serialize this decimal as a string.
            # Native token counters, upstream cost and CLI session estimates
            # remain distinct; a verified gen-* identity is still required.
            value = usages[-1].get('cost')
            if value is not None:
                if isinstance(value, str):
                    if len(value) > 64 or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value):
                        raise ValueError('invalid_messages_billed_cost')
                    value = Decimal(value)
                result.update(billed_usd=_cost(value), billing_source='messages.usage.cost')
        if result['billed_usd'] is None:
            result['issues'].append('billing_not_observed')
    # 解析或身份冲突保留原始证据与问题清单，撤销无法确认的金额，等待后续对账。
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        # Keep raw bytes and any unambiguous header identity for reconciliation.
        result.update(billed_usd=None, billing_source=None)
        if str(exc) in {'generation_identity_conflict', 'conflicting_response_header',
                        'invalid_generation_header', 'invalid_generation_data_identity'}:
            result['generation_id'] = None
        result['issues'].append(str(exc) if type(exc) is ValueError and len(str(exc)) < 80
                                else 'invalid_response_encoding')
    return result


# 将账单绑定来源命名空间、generation ID 和整份收据摘要，隔离合成与真实证据。
def _receipt(capture, observed, origin):
    if origin not in {'openrouter', 'synthetic'}:
        raise ValueError('Explicit response origin required')
    return dict(request_id=observed['generation_id'],
        source=origin+':'+observed['billing_source'], evidence_sha256=digest(canonical(capture)),
        identity_namespace=origin+':generation', evidence=capture)


# 在现有根账本提交响应与账单；恢复响应必须延续原始前缀，不能覆盖成另一份响应。
def record_response(budget, request_key, capture, *, origin, withhold_billing=False):
    """Save raw response and bill atomically in the existing root ledger."""
    if origin not in {'openrouter', 'synthetic'} or type(withhold_billing) is not bool:
        raise ValueError('Explicit origin and billing-observation flag required')
    if capture['protocol'] == 'generation':
        raise ValueError('Generation metadata is not a model response')
    observed = observe_response(capture)
    current = budget.inspect_request(request_key)
    prior = current['response_event']
    if prior is not None and prior.get('outcome_known') is False:
        old = prior['response']['http']
        if (capture['protocol'] != old['protocol'] or capture['status'] != old['status']
                or capture['headers'] != old['headers']
                or not response_bytes(capture).startswith(response_bytes(old))):
            raise RequestIdentityConflict('Recovered HTTP response differs from the original prefix/identity')
    # HTTP 错误可以是已知结果；成功响应则须同时满足传输完整与协议完整，费用另行判断。
    complete = capture['transport_complete'] and (capture['status'] != 200 or observed['protocol_complete'])
    amount = None if withhold_billing else observed['billed_usd']
    receipt = _receipt(capture, observed, origin) if amount is not None else None
    if (current['bill'] is not None and prior is not None
            and (prior.get('outcome_known') is False or 'prior_response_events' in prior)):
        # A generation lookup may have settled the interrupted request first.
        # Compare the independently observed inline bill, but retain the exact
        # already-authoritative receipt rather than replace it with another one.
        if amount is not None and (Decimal(amount) != Decimal(current['settled_usd'])
                or observed['generation_id'] != current['bill']['receipt']['request_id']):
            raise RequestIdentityConflict('Recovered inline charge conflicts with the reconciled bill')
        amount, receipt = None, None
    return budget.record_response(request_key,
        dict(complete=complete, http=capture, observation=observed, origin=origin,
             billing_observation_withheld=withhold_billing),
        billed_usd=amount, receipt=receipt, outcome_known=complete)


# 账单只能补到原响应已观察的同源 generation，不重发模型请求，也不猜测缺失身份。
def reconcile_response(budget, request_key, capture, *, origin):
    """Attach a generation bill to its already observed ID, never resend."""
    current = budget.inspect_request(request_key)
    if current['response_event'] is None:
        raise RequestRecoveryRequired('No original response identity; cannot guess a generation')
    original = current['response_event']['response']
    if original.get('origin') != origin:
        raise RequestIdentityConflict('Billing observation origin differs from original response')
    expected = observe_response(original['http'])['generation_id']
    observed = observe_response(capture)
    if (capture['protocol'] != 'generation' or expected is None
            or observed['generation_id'] != expected or observed['billed_usd'] is None):
        raise RequestIdentityConflict('Bill lacks matching generation identity and verified account charge')
    return budget.reconcile_request(request_key, billed_usd=observed['billed_usd'],
                                    receipt=_receipt(capture, observed, origin))
