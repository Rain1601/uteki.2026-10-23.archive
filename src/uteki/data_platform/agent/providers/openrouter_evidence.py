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


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_field')
        value[key] = item
    return value


def _constant(_):
    raise ValueError('nonfinite_json_number')


def _json(raw):
    return json.loads(raw.decode('utf-8'), parse_float=Decimal,
                      parse_constant=_constant, object_pairs_hook=_object)


def _serializable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serializable(v) for v in value]
    return value


def _generation(value):
    return isinstance(value, str) and len(value) <= 128 and bool(re.fullmatch(r'gen-[0-9A-Za-z-]+', value))


def _cost(value):
    # No coercion of booleans, strings, upstream costs or SDK estimates.
    if type(value) not in {int, Decimal}:
        raise ValueError('invalid_billed_cost')
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError('invalid_billed_cost')
    return str(amount)


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


def response_bytes(capture):
    if capture.get('schema') != 'gateway-http-observation-v1':
        raise ValueError('Unknown HTTP observation schema')
    raw = base64.b64decode(capture['body_base64'], validate=True)
    if (digest(raw) != capture['body_sha256'] or len(raw) != capture['byte_length']
            or type(capture['transport_complete']) is not bool
            or capture['transport_complete'] != (capture['error'] is None)):
        raise ValueError('Corrupt HTTP observation')
    return raw


def _events(raw):
    """Read SSE envelopes only; never assemble model text or tool arguments."""
    text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    if not text.endswith('\n\n'):
        raise ValueError('incomplete_sse_event')
    events = []
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
        event = _json('\n'.join(lines).encode('utf-8'))
        if not isinstance(event, dict) or (name is not None and name != event.get('type')):
            raise ValueError('invalid_sse_envelope')
        events.append(event)
    return events


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
        if headers.get('content-encoding', 'identity').strip().lower() != 'identity':
            raise ValueError('unsupported_content_encoding')
        protocol = capture['protocol']
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
        elif protocol == 'chat_completions' and isinstance(message.get('usage'), dict):
            value = message['usage'].get('cost')
            if value is not None:
                result.update(billed_usd=_cost(value), billing_source='chat.usage.cost')
        # Messages token counters/session estimates are not a documented bill.
        if result['billed_usd'] is None:
            result['issues'].append('billing_not_observed')
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        # Keep raw bytes and any unambiguous header identity for reconciliation.
        result.update(billed_usd=None, billing_source=None)
        if str(exc) in {'generation_identity_conflict', 'conflicting_response_header',
                        'invalid_generation_header', 'invalid_generation_data_identity'}:
            result['generation_id'] = None
        result['issues'].append(str(exc) if type(exc) is ValueError and len(str(exc)) < 80
                                else 'invalid_response_encoding')
    return result


def _receipt(capture, observed, origin):
    if origin not in {'openrouter', 'synthetic'}:
        raise ValueError('Explicit response origin required')
    return dict(request_id=observed['generation_id'],
        source=origin+':'+observed['billing_source'], evidence_sha256=digest(canonical(capture)),
        identity_namespace=origin+':generation', evidence=capture)


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
