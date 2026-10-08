"""Bounded native Claude Messages transport for one host-owned planner decision.

This adapter does not execute tools or continue provider turns. An opt-in small
native decision envelope constrains wire JSON; full decisions remain locally validated.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import fields
import hashlib
import json
import logging
import math
import os
import re
import ssl
from threading import Lock
import time

from agents import Model, ModelResponse, ModelSettings
from agents.exceptions import ModelBehaviorError
from agents.usage import Usage
import httpx2 as httpx
from openai.types.responses import ResponseOutputMessage, ResponseOutputText

from .model_configuration import build_configuration_snapshot
from .run_budget import RequestEnvelopeTooLarge
from .strict_json import StrictJSONError, parse_json_object

ENDPOINT = 'https://aihubmix.com/v1/messages'
MODELS = frozenset({'claude-sonnet-5-5', 'claude-opus-5-5'})
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z')
_COUNTERS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
_TRANSPORT_ERROR_TYPES = frozenset({
    'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout',
    'ConnectError', 'ReadError', 'WriteError', 'CloseError',
    'LocalProtocolError', 'RemoteProtocolError', 'ProxyError',
    'UnsupportedProtocol', 'DecodingError', 'TooManyRedirects',
})
_LOG_LOCK = Lock()
_LOG_USERS = 0
_LOG_PREVIOUS_DISABLE = 0


class ClaudeTransientTransportError(RuntimeError):
    """A classified transient request failure; retries belong above the call meter."""


def _certificate_failure(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ssl.SSLCertVerificationError):
            return True
        error = error.__cause__ or error.__context__
    return False


@contextmanager
def _suppress_transport_logging():
    """Keep overlapping private requests suppressed until the last exit."""
    global _LOG_USERS, _LOG_PREVIOUS_DISABLE
    with _LOG_LOCK:
        if _LOG_USERS == 0:
            _LOG_PREVIOUS_DISABLE = logging.root.manager.disable
            logging.disable(max(logging.CRITICAL, _LOG_PREVIOUS_DISABLE))
        _LOG_USERS += 1
    try:
        yield
    finally:
        with _LOG_LOCK:
            _LOG_USERS -= 1
            if _LOG_USERS == 0:
                logging.disable(_LOG_PREVIOUS_DISABLE)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identifier(value, secret):
    return value if isinstance(value, str) and _ID.fullmatch(value) and secret not in value else None


def _numeric_usage(raw, *, require_totals=True):
    """Only known numeric counters survive; invalid values cannot become zero."""
    if not isinstance(raw, dict):
        return None, 'absent' if raw is None else 'malformed'
    result, valid = {}, True
    if any(isinstance(name, str) and 'cache' in name.lower()
           and name not in (*_COUNTERS, 'cache_creation') for name in raw):
        valid = False
    for name in _COUNTERS:
        if name not in raw:
            valid = valid and (not require_totals or name not in ('input_tokens', 'output_tokens'))
        elif type(raw[name]) is int and raw[name] >= 0:
            result[name] = raw[name]
        else:
            valid = False
    for name, allowed in (
            ('cache_creation', {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}),
            ('server_tool_use', {'web_search_requests', 'web_fetch_requests'})):
        if name in raw:
            nested = raw[name]
            if not isinstance(nested, dict) or set(nested) - allowed:
                valid = False
                continue
            result[name] = {}
            for key, count in nested.items():
                if type(count) is int and count >= 0:
                    result[name][key] = count
                else:
                    valid = False
    return result, 'reported' if valid else 'malformed'


def _user_text(value):
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError('Claude planner requires one user text packet')
        message = value[0]
        if (set(message) - {'role', 'content', 'type'} or message.get('role') != 'user'
                or message.get('type', 'message') != 'message'):
            raise ValueError('Claude planner accepts only a single user message')
        value = message.get('content')
        if isinstance(value, list):
            if (len(value) != 1 or not isinstance(value[0], dict)
                    or set(value[0]) != {'type', 'text'} or value[0]['type'] != 'input_text'):
                raise ValueError('Claude planner accepts text only')
            value = value[0]['text']
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Claude planner requires nonempty user text')
    return value


def decision_envelope_schema():
    from uteki.agents.data_query.decision_protocol import ACTION_RULES
    return {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': list(ACTION_RULES)},
        'requirement_ids': {'type': 'array', 'items': {'type': 'string'}},
        'reason': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        'payload_json': {'anyOf': [{'type': 'string'}, {'type': 'null'}]}},
        'required': ['action', 'requirement_ids', 'reason', 'payload_json'], 'additionalProperties': False}


def decode_decision_envelope(text):
    """Decode without repairing the wire JSON or relaxing the host contract."""
    from uteki.agents.data_query.decision_protocol import ACTION_RULES
    value = parse_json_object(text)
    if set(value) != {'action', 'requirement_ids', 'reason', 'payload_json'}:
        raise StrictJSONError('invalid_decision_envelope_fields')
    action, refs, reason, payload = (value[k] for k in ('action', 'requirement_ids', 'reason', 'payload_json'))
    if (type(action) is not str or action not in ACTION_RULES or type(refs) is not list
            or any(type(ref) is not str for ref in refs)
            or (reason is not None and type(reason) is not str)
            or (payload is not None and type(payload) is not str)):
        raise StrictJSONError('invalid_decision_envelope_types')
    result = {'action': action, 'requirement_ids': refs, 'reason': reason}
    field = ACTION_RULES[action].payload
    if field is None:
        if payload is not None:
            raise StrictJSONError('unexpected_decision_payload')
    else:
        if payload is None:
            raise StrictJSONError('missing_decision_payload')
        # Payloads may be objects, arrays or strings. The wrapper delegates all
        # lexical checks to the same strict parser (including duplicate keys).
        wrapper = parse_json_object('{"payload":' + payload + '}')
        if set(wrapper) != {'payload'}:
            raise StrictJSONError('invalid_decision_payload')
        result[field] = wrapper['payload']
    encoded = None
    try:
        encoded = _canonical(result)
    except UnicodeEncodeError:
        pass
    # Raise outside the encoding handler: raw payload must not survive as
    # exception context or appear in the host's bounded validation hints.
    if encoded is None:
        raise StrictJSONError('invalid_decision_unicode')
    return encoded.decode('utf-8')


class ClaudeMessagesModel(Model):
    native_usage_format = 'anthropic_messages'

    def __init__(self, model, *, timeout_seconds, reasoning_effort='high', client_factory=None,
                 max_request_bytes=400000, stream=False, max_output_tokens_limit=16000,
                 thinking_type='adaptive', schema_protocol='host_decision'):
        if not isinstance(model, str) or model not in MODELS:
            raise ValueError('Explicit supported Claude model required')
        if schema_protocol not in {'host_decision', 'json_object', 'native_decision_envelope'}:
            raise ValueError('Explicit supported Claude schema protocol required')
        self.schema_protocol = schema_protocol
        if not isinstance(reasoning_effort, str) or reasoning_effort not in {'low', 'medium', 'high'}:
            raise ValueError('Claude effort must be low, medium or high')
        if not isinstance(thinking_type, str) or thinking_type not in {'adaptive', 'between_tools'}:
            raise ValueError('Claude thinking_type must be adaptive or between_tools')
        if thinking_type == 'between_tools' and model != 'claude-sonnet-5-5':
            raise ValueError('between_tools requires claude-sonnet-5-5')
        maximum_timeout = 600 if stream is True else 300
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= maximum_timeout):
            raise ValueError('Explicit timeout exceeds the bounded transport mode limit')
        if type(max_request_bytes) is not int or max_request_bytes < 1:
            raise ValueError('max_request_bytes must be a positive integer')
        if type(stream) is not bool:
            raise ValueError('stream must be an explicit boolean')
        # Local safety bounds, not a claim about the provider's model capacity.
        # Larger requests remain opt-in; the default budget stays at 16000.
        maximum_output_limit = 48000 if model == 'claude-sonnet-5-5' else 24000
        if type(max_output_tokens_limit) is not int or not 1 <= max_output_tokens_limit <= maximum_output_limit:
            raise ValueError('max_output_tokens_limit must be within 1..' + str(maximum_output_limit))
        if max_output_tokens_limit > 16000 and not stream:
            raise ValueError('Output limits above 16000 require stream=true')
        self.stream = stream
        self.thinking_type = thinking_type
        self.model, self.timeout_seconds, self.reasoning_effort = model, timeout_seconds, reasoning_effort
        self.max_request_bytes = max_request_bytes
        self.max_output_tokens_limit = max_output_tokens_limit
        self._client_factory = client_factory or httpx.AsyncClient
        self._client, self._closed, self._inflight = None, False, False
        self.response_metadata = None
        self.response_text = None

    def _request(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                 tracing=None, *, previous_response_id=None, conversation_id=None, prompt=None):
        if self._closed:
            raise ValueError('Claude adapter is closed')
        if tools or handoffs or previous_response_id is not None or conversation_id is not None or prompt is not None:
            raise ValueError('Claude planner tools, handoffs and server-side conversation state are unsupported')
        if not isinstance(model_settings, ModelSettings):
            raise ValueError('Explicit ModelSettings required')
        for field in fields(ModelSettings):
            if field.name not in {'max_tokens', 'retry'} and getattr(model_settings, field.name) is not None:
                raise ValueError('Unsupported Claude planner setting: ' + field.name)
        retry = model_settings.retry
        if retry is not None and (type(retry.max_retries) is not int or retry.max_retries != 0
                                  or retry.backoff is not None or retry.policy is not None):
            raise ValueError('Claude planner retries must be disabled')
        maximum = model_settings.max_tokens
        if type(maximum) is not int or not 1 <= maximum <= self.max_output_tokens_limit:
            raise ValueError('Explicit max_tokens must be within 1..' + str(self.max_output_tokens_limit))
        if system_instructions is not None and not isinstance(system_instructions, str):
            raise ValueError('System instructions must be text')
        schema = output_schema.json_schema() if output_schema and not output_schema.is_plain_text() else None
        system = system_instructions or ''
        if self.schema_protocol == 'native_decision_envelope':
            from uteki.agents.data_query.decision_protocol import ACTION_RULES
            if schema is None or set(schema.get('properties', {}).get('action', {}).get('enum', ())) != set(ACTION_RULES):
                raise ValueError('Native decision envelope requires the host AutonomousDecision schema')
            system += ('\nThis endpoint offers no tools. Return the native JSON decision envelope, not XML or tool-call markup. '
                'All four envelope fields are required. action is the host action name; requirement_ids is an array '
                '(use [] when no references are needed); reason is the short task explanation or null. '
                'payload_json is a JSON-encoded string containing ONLY the selected action payload value, '
                'not a whole decision and not an object wrapping the payload field. For actions without payload, '
                'payload_json must be null. The host decodes that string into the selected action field and validates '
                'the complete decision against the original schema below. Do not include unrelated fields. '
                'The outer native schema guarantees only the envelope; all inner constraints still apply. '
                'Action-to-payload-field mapping:\n' + _canonical({a:r.payload for a,r in ACTION_RULES.items()}).decode('utf-8')
                + '\nOriginal host decision JSON Schema (applies AFTER envelope decoding):\n' + _canonical(schema).decode('utf-8'))
        elif schema is not None and self.schema_protocol == 'host_decision':
            system += ('\nYou are in a stateless host decision protocol. This endpoint offers no tools. '
                       'Tool names describe host actions, not tools you can invoke. '
                       'Select an action by putting its name in the JSON action field; '
                       'the host validates and executes it, then supplies the result in a later request. '
                       'Return exactly one JSON object and nothing else: no XML, tool-call markup, '
                       'prose, or Markdown fences before or after it. '
                       'Structural example: {"action":"load_skill","skill":"query"}. '
                       'This example is not an instruction to choose that action. '
                       'Choose the action and its payload from the current packet and permitted schema. '
                       'Follow this JSON Schema; all required fields must be present:\n'
                       + _canonical(schema).decode('utf-8'))
        elif schema is not None:
            system += ('\nReturn exactly one JSON object matching the supplied JSON Schema. '
                       'Return no prose, Markdown fences, XML or tool-call markup outside that object. '
                       'This endpoint offers no tools. Follow the task instructions and include every '
                       'required field. JSON Schema:\n' + _canonical(schema).decode('utf-8'))
        body = {'model': self.model, 'messages': [{'role': 'user', 'content': _user_text(input)}],
                'max_tokens': maximum, 'thinking': {'type': self.thinking_type},
                'output_config': {'effort': self.reasoning_effort}, 'stream': self.stream}
        if self.schema_protocol == 'native_decision_envelope':
            body['output_config']['format'] = {'type': 'json_schema', 'schema': decision_envelope_schema()}
        if system:
            body['system'] = system
        raw = _canonical(body)
        if len(raw) > self.max_request_bytes:
            raise RequestEnvelopeTooLarge('Native Claude request exceeds configured byte capacity')
        return body, raw, schema

    def request_body(self, *args, **kwargs):
        """Exact payload used for conservative reservation; never written to logs."""
        return self._request(*args, **kwargs)[1]

    def request_configuration(self, *args, **kwargs):
        body, _, schema = self._request(*args, **kwargs)
        fingerprints = {'input_sha256': _sha(_canonical(body['messages'])), 'tools_sha256': _sha(b'[]')}
        if 'system' in body:
            fingerprints['system_sha256'] = _sha(body['system'].encode('utf-8'))
        if schema is not None:
            fingerprints['output_schema_sha256'] = _sha(_canonical(schema))
        native = self.schema_protocol == 'native_decision_envelope'
        if native:
            fingerprints['output_schema_sha256'] = _sha(_canonical(body['output_config']['format']['schema']))
        return build_configuration_snapshot(
            {'provider': 'aihubmix', 'model': self.model, 'api_format': 'anthropic_messages',
             'base_url': 'https://aihubmix.com', 'max_tokens': body['max_tokens'],
             'thinking': body['thinking'], 'reasoning_effort': self.reasoning_effort,
             'stream': self.stream, 'timeout_seconds': self.timeout_seconds, 'max_retries': 0,
             **({'response_format': {'type': 'json_schema'}} if native else {})},
            capture_kind='before_dispatch', capture_layer='http_request_before_dispatch', source='http_request',
            sources={'response_format': 'http_request.output_config.format'} if native else None,
            statuses={name: 'not_sent' for name in ('temperature', 'top_p', 'top_k', 'seed',
                      *(() if native else ('response_format',)), 'tool_choice', 'parallel_tool_calls')}, fingerprints=fingerprints)

    def _stream_error(self, category):
        self.response_metadata['stream_error_type'] = category
        self.response_metadata['stream_complete'] = False
        if category in {'incomplete_stream', 'incomplete_event'} or (
                category == 'provider_error_event' and self.response_metadata.get('provider_error_type')
                in {'overloaded_error', 'api_error', 'rate_limit_error', 'timeout_error'}):
            raise ClaudeTransientTransportError('Claude Messages stream interrupted')
        raise ModelBehaviorError('Claude Messages stream is incomplete or invalid')

    async def _collect_stream(self, response, key, started):
        """Accumulate only visible text; partial usage never settles as a final bill."""
        metadata = self.response_metadata
        seen_start = False
        blocks = {}
        closed = set()
        parts = []
        usage = {}
        usage_seen = False
        usage_invalid = False
        final_output_usage = False
        seen_delta = False
        event_name = None
        data_lines = []
        event_bytes = 0
        metadata.update(stream_complete=False, stream_event_count=0)

        def update_usage(raw, *, final=False):
            nonlocal usage_seen, usage_invalid, final_output_usage
            if raw is None:
                return
            usage_seen = True
            safe, presence = _numeric_usage(raw, require_totals=False)
            usage_invalid |= presence != 'reported'
            if safe:
                for name, value in safe.items():
                    if name in usage and type(value) is int and type(usage[name]) is int and value < usage[name]:
                        usage_invalid = True
                    usage[name] = value
            if final and isinstance(raw, dict) and type(raw.get('output_tokens')) is int:
                final_output_usage = True
            metadata.update(raw_usage=usage or None,
                            usage_presence='malformed' if usage_invalid else 'partial')

        def visible(value):
            if not isinstance(value, str):
                self._stream_error('invalid_text')
            parts.append(value)
            text = ''.join(parts)
            metadata['visible_text_secret_redacted'] = key in text
            self.response_text = text.replace(key, '[REDACTED]')

        def consume(name, raw):
            nonlocal seen_start, seen_delta
            if metadata['stream_complete']:
                self._stream_error('event_after_message_stop')
            malformed = False
            try:
                event = parse_json_object(raw)
            except StrictJSONError:
                malformed = True
            if malformed:
                self._stream_error('invalid_event_json')
            if not name or event.get('type') != name:
                self._stream_error('event_type_mismatch')
            metadata['stream_event_count'] += 1
            if 'first_event_elapsed_seconds' not in metadata:
                metadata['first_event_elapsed_seconds'] = time.monotonic() - started
            if name == 'ping':
                return False
            if name == 'error':
                kind = (event.get('error') or {}).get('type') if isinstance(event.get('error'), dict) else None
                allowed = {'overloaded_error', 'api_error', 'invalid_request_error', 'authentication_error',
                           'permission_error', 'not_found_error', 'rate_limit_error', 'timeout_error', 'billing_error'}
                metadata['provider_error_type'] = kind if kind in allowed else 'unknown_error'
                self._stream_error('provider_error_event')
            if name == 'message_start':
                message = event.get('message')
                if seen_start or not isinstance(message, dict) or message.get('content') != []:
                    self._stream_error('invalid_message_start')
                seen_start = True
                metadata.update(actual_upstream_model=_identifier(message.get('model'), key),
                                response_id=_identifier(message.get('id'), key))
                update_usage(message.get('usage'))
                return False
            if not seen_start:
                self._stream_error('missing_message_start')
            if name == 'content_block_start':
                index, block = event.get('index'), event.get('content_block')
                if (type(index) is not int or index != len(blocks) or seen_delta or
                        len(closed) != len(blocks) or not isinstance(block, dict)):
                    self._stream_error('invalid_block_start')
                kind = block.get('type')
                if kind not in {'text', 'thinking', 'redacted_thinking'}:
                    self._stream_error('unsupported_content_block')
                blocks[index] = kind
                if kind == 'text':
                    visible(block.get('text'))
                return False
            if name in {'content_block_delta', 'content_block_stop'}:
                index = event.get('index')
                if type(index) is not int or index not in blocks or index in closed or seen_delta:
                    self._stream_error('invalid_block_sequence')
                if name == 'content_block_stop':
                    closed.add(index)
                    return False
                delta = event.get('delta')
                if not isinstance(delta, dict):
                    self._stream_error('invalid_content_delta')
                kind = delta.get('type')
                if kind == 'text_delta' and blocks[index] == 'text':
                    visible(delta.get('text'))
                elif kind in {'thinking_delta', 'signature_delta'} and blocks[index] == 'thinking':
                    pass  # Intentionally do not retain hidden content or signatures.
                elif kind == 'citations_delta' and blocks[index] == 'text':
                    self._stream_error('unsupported_citation_delta')
                else:
                    self._stream_error('invalid_content_delta')
                return False
            if name == 'message_delta':
                delta = event.get('delta')
                if len(closed) != len(blocks) or not isinstance(delta, dict):
                    self._stream_error('invalid_message_delta')
                seen_delta = True
                if delta.get('stop_reason') is not None:
                    metadata['stop_reason'] = _identifier(delta.get('stop_reason'), key)
                update_usage(event.get('usage'), final=True)
                return False
            if name == 'message_stop':
                if not seen_delta or len(closed) != len(blocks):
                    self._stream_error('invalid_message_stop')
                metadata['stream_complete'] = True
                safe, presence = _numeric_usage(usage if usage_seen else None)
                metadata['raw_usage'] = safe
                metadata['usage_presence'] = ('malformed' if usage_invalid else
                    presence if not usage_seen or final_output_usage else 'partial')
                return True
            self._stream_error('unsupported_event')

        async for line in response.aiter_lines():
            if not line:
                if data_lines:
                    consume(event_name, '\n'.join(data_lines))
                elif event_name:
                    self._stream_error('missing_event_data')
                event_name, data_lines, event_bytes = None, [], 0
                continue
            if line.startswith(':'):
                continue
            event_bytes += len(line.encode('utf-8'))
            if event_bytes > 1024 * 1024:
                self._stream_error('event_too_large')
            field, separator, value = line.partition(':')
            if value.startswith(' '):
                value = value[1:]
            if field == 'event':
                if event_name is not None:
                    self._stream_error('duplicate_event_name')
                event_name = value
            elif field == 'data':
                data_lines.append(value)
            elif field not in {'id', 'retry'}:
                self._stream_error('invalid_event_field')
        # Exhaust the complete HTTP body, including its chunk terminator. Returning
        # at message_stop strands HTTPX/httpcore async generators until loop shutdown.
        if event_name or data_lines:
            self._stream_error('incomplete_event')
        if metadata['stream_complete']:
            metadata['transport_phase'] = 'body_complete'
            return {'content': [{'type': 'text', 'text': self.response_text or ''}]}
        # A final un-delimited event or EOF before message_stop is incomplete.
        self._stream_error('incomplete_stream')

    async def _receive(self, raw, headers, key, started):
        async with self._client.stream('POST', ENDPOINT, content=raw, headers=headers) as response:
            self.response_metadata.update(http_status=response.status_code, headers_received=True,
                headers_received_elapsed_seconds=time.monotonic() - started,
                request_id=_identifier(response.headers.get('request-id') or response.headers.get('x-request-id'), key),
                transport_phase='reading_stream' if self.stream else 'reading_body')
            if response.status_code in {408, 429, 500, 502, 503, 504, 529}:
                raise ClaudeTransientTransportError('Claude Messages temporary HTTP failure')
            if response.status_code != 200:
                raise ModelBehaviorError('Claude Messages returned a non-success status')
            if self.stream:
                if response.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'text/event-stream':
                    self._stream_error('unexpected_content_type')
                return await self._collect_stream(response, key, started)
            await response.aread()
            self.response_metadata['transport_phase'] = 'body_complete'
            payload = None
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                pass
            if not isinstance(payload, dict):
                raise ModelBehaviorError('Claude Messages returned invalid JSON')
            return payload

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing=None, *, previous_response_id=None, conversation_id=None, prompt=None):
        if self._inflight:
            raise ValueError('Claude planner calls must be sequential')
        self.response_text = None
        self.response_metadata = None
        body, raw, schema = self._request(system_instructions, input, model_settings, tools, output_schema,
            handoffs, tracing, previous_response_id=previous_response_id, conversation_id=conversation_id, prompt=prompt)
        self.response_metadata = {'request_sha256': _sha(raw), 'request_bytes': len(raw),
            'dispatch_status': 'not_sent', 'actual_upstream_model': None, 'response_id': None,
            'request_id': None, 'stop_reason': None, 'raw_usage': None, 'usage_presence': 'absent',
            'headers_received': False, 'transport_phase': 'not_sent'}
        if self.schema_protocol == 'native_decision_envelope':
            self.response_metadata.update(schema_protocol=self.schema_protocol,
                wire_schema_sha256=_sha(_canonical(body['output_config']['format']['schema'])),
                host_output_schema_sha256=_sha(_canonical(schema)),
                provider_enforced_schema='decision_envelope_only', host_schema_validation='local',
                transport_decode='not_started')
        key = os.environ.get('AIHUBMIX_API_KEY')
        if not isinstance(key, str) or not key:
            raise ValueError('AIHUBMIX_API_KEY must already be loaded')
        self._inflight = True
        try:
            if self._client is None:
                self._client = self._client_factory(timeout=self.timeout_seconds, follow_redirects=False,
                    transport=httpx.AsyncHTTPTransport(retries=0), trust_env=False)
            headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            failure = None
            transient = False
            certificate_failure = False
            started = time.monotonic()
            with _suppress_transport_logging():
                try:
                    self.response_metadata.update(dispatch_status='sent', transport_phase='awaiting_headers')
                    payload = await asyncio.wait_for(self._receive(raw, headers, key, started), self.timeout_seconds)
                except (httpx.TimeoutException, TimeoutError) as error:
                    failure = 'timeout'
                    name = type(error).__name__
                    self.response_metadata['transport_error_type'] = (
                        name if name in _TRANSPORT_ERROR_TYPES else 'TimeoutError')
                except ssl.SSLError as error:
                    failure = 'transport'
                    certificate_failure = _certificate_failure(error)
                    transient = not certificate_failure
                    self.response_metadata['transport_error_type'] = (
                        'SSLCertVerificationError' if certificate_failure else 'SSLError')
                except httpx.HTTPError as error:
                    failure = 'transport'
                    certificate_failure = _certificate_failure(error)
                    transient = (not certificate_failure and isinstance(error, (
                        httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)))
                    name = type(error).__name__
                    # Never persist exception messages, request objects or an
                    # arbitrary class name. Only stable transport categories.
                    self.response_metadata['transport_error_type'] = (
                        name if name in _TRANSPORT_ERROR_TYPES else 'HTTPError')
            if failure == 'timeout':
                if self.response_metadata.get('transport_error_type') in {'ConnectTimeout','PoolTimeout'} and not self.response_metadata['headers_received']:
                    self.response_metadata['dispatch_status'] = 'not_sent'
                raise TimeoutError('Claude Messages request timed out')
            if failure:
                if self.response_metadata.get('transport_error_type') == 'ConnectError' and not self.response_metadata['headers_received']:
                    self.response_metadata['dispatch_status'] = 'not_sent'
                if transient:
                    raise ClaudeTransientTransportError('Claude Messages temporary transport failure')
                raise RuntimeError('Claude Messages transport failed')
            if not self.stream:
                usage, presence = _numeric_usage(payload.get('usage'))
                self.response_metadata.update(actual_upstream_model=_identifier(payload.get('model'), key),
                    response_id=_identifier(payload.get('id'), key), stop_reason=_identifier(payload.get('stop_reason'), key),
                    raw_usage=usage, usage_presence=presence)
            usage = self.response_metadata['raw_usage']
            blocks = payload.get('content')
            if not isinstance(blocks, list):
                raise ModelBehaviorError('Claude Messages returned invalid content')
            visible = ''.join(block['text'] for block in blocks if isinstance(block, dict)
                and block.get('type') == 'text' and isinstance(block.get('text'), str))
            self.response_text = visible.replace(key, '[REDACTED]')
            self.response_metadata['visible_text_secret_redacted'] = key in visible or self.response_metadata.get('visible_text_secret_redacted', False)
            if self.response_metadata['stop_reason'] != 'end_turn' or not self.response_text.strip():
                raise ModelBehaviorError('Claude Messages response incomplete or empty')
            host_text = self.response_text
            if self.schema_protocol == 'native_decision_envelope':
                try:
                    host_text = decode_decision_envelope(self.response_text)
                except StrictJSONError as error:
                    self.response_metadata.update(transport_decode='rejected', transport_decode_error=error.code)
                    raise ModelBehaviorError('Native decision envelope rejected: ' + error.code) from None
                self.response_metadata.update(transport_decode='decoded', host_decision_sha256=_sha(host_text.encode('utf-8')))
            invalid_schema = False
            if output_schema and not output_schema.is_plain_text():
                syntax_error = None
                try:
                    parse_json_object(host_text)
                except StrictJSONError as error:
                    syntax_error = error.code
                if syntax_error:
                    raise ModelBehaviorError('JSON output rejected: ' + syntax_error)
                try:
                    output_schema.validate_json(host_text)
                except Exception:
                    invalid_schema = True
            if invalid_schema:
                if self.schema_protocol == 'native_decision_envelope':
                    self.response_metadata['host_schema_validation'] = 'rejected'
                raise ModelBehaviorError('Claude Messages response does not match the output schema')
            if self.schema_protocol == 'native_decision_envelope':
                self.response_metadata['host_schema_validation'] = 'passed'
            safe_usage = usage or {}
            # SDK requires integer usage defaults. MeteredModel uses raw counters,
            # never these placeholders, to settle costs.
            uncached = safe_usage.get('input_tokens', 0)
            cached = safe_usage.get('cache_read_input_tokens', 0)
            created = safe_usage.get('cache_creation_input_tokens', 0)
            output_tokens = safe_usage.get('output_tokens', 0)
            input_tokens = uncached + cached + created
            return ModelResponse(output=[ResponseOutputMessage(id=self.response_metadata['response_id'] or 'native-message',
                role='assistant', type='message', status='completed', content=[ResponseOutputText(
                    type='output_text', text=host_text, annotations=[])])],
                usage=Usage(requests=1, input_tokens=input_tokens, output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    input_tokens_details={'cached_tokens': cached, 'cache_write_tokens': created}),
                response_id=self.response_metadata['response_id'], request_id=self.response_metadata['request_id'], raw_usage=usage)
        finally:
            self._inflight = False

    async def aclose(self):
        self._closed = True
        if self._client is not None:
            await self._client.aclose()

    async def close(self):
        await self.aclose()

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError('Use get_response; optional wire streaming is accumulated internally')
        yield  # pragma: no cover
