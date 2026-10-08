"""Small, allowlisted configuration evidence; never a provider-effective echo.

SDK capture observes arguments before adapter conversion. It neither resolves a
model/client nor adds defaults. Fingerprints hash UTF-8 system text, canonical
JSON input/schema, and canonical JSON tool names; their contents are not saved.
"""
from copy import deepcopy
import hashlib
import json
import math
import re


CONFIGURATION_FIELDS = (
    'provider', 'model', 'api_format', 'base_url', 'max_tokens', 'thinking',
    'reasoning_effort', 'temperature', 'top_p', 'top_k', 'seed', 'response_format',
    'tool_choice', 'parallel_tool_calls', 'stream', 'timeout_seconds', 'max_retries',
    'max_completion_tokens', 'preserve_thinking',
)
_PRE_QWEN_CONFIGURATION_FIELDS = tuple(key for key in CONFIGURATION_FIELDS if key not in ('max_completion_tokens', 'preserve_thinking'))
_LEGACY_CONFIGURATION_FIELDS = tuple(key for key in _PRE_QWEN_CONFIGURATION_FIELDS if key != 'top_k')
FINGERPRINT_FIELDS = ('system_sha256', 'input_sha256', 'tools_sha256', 'output_schema_sha256')
_REQUEST_FIELDS = ('max_tokens', 'thinking', 'reasoning_effort', 'temperature', 'top_p', 'top_k',
                   'seed', 'response_format', 'tool_choice', 'parallel_tool_calls', 'stream',
                   'max_completion_tokens', 'preserve_thinking')
_LAYERS = {'historical_records', 'sdk_adapter_before_dispatch', 'http_request_before_dispatch'}
_ENDPOINTS = {'https://api.deepseek.com', 'https://api.deepseek.com/v1',
              'https://aihubmix.com', 'https://aihubmix.com/v1',
              'https://api.openai.com/v1', 'https://api.anthropic.com'}
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}\Z')
_SOURCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,95}\Z')


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _safe_value(key, value):
    if value is None:
        return None
    if key in {'provider', 'model'}:
        return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None
    if key == 'base_url':
        # Unknown/proxy URLs may carry credentials in any URL component. Do not
        # persist them, even when a URL parser would consider them well formed.
        return value if isinstance(value, str) and value.rstrip('/') in _ENDPOINTS else None
    if key == 'api_format':
        return value if value in ('chat_completions', 'responses', 'anthropic_messages') else None
    if key in {'max_tokens', 'max_completion_tokens', 'max_retries', 'top_k'}:
        return value if type(value) is int and 0 <= value <= 2**63 - 1 else None
    if key == 'seed':
        return value if type(value) is int and -(2**63) <= value <= 2**63 - 1 else None
    if key in {'temperature', 'top_p'}:
        return value if _number(value) else None
    if key in {'stream', 'parallel_tool_calls', 'preserve_thinking'}:
        return value if type(value) is bool else None
    if key == 'reasoning_effort':
        return value if value in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra') else None
    if key == 'thinking':
        if isinstance(value, str):
            return value if value in ('enabled', 'disabled', 'adaptive', 'between_tools') else None
        if isinstance(value, dict) and value.get('type') in ('enabled', 'disabled', 'adaptive', 'between_tools'):
            result = {'type': value['type']}
            if type(value.get('budget_tokens')) is int and 0 <= value['budget_tokens'] <= 2**63 - 1:
                result['budget_tokens'] = value['budget_tokens']
            return result
    if key == 'response_format':
        kind = value.get('type') if isinstance(value, dict) else value
        return {'type': kind} if kind in ('text', 'json_object', 'json_schema') else None
    if key == 'tool_choice':
        if isinstance(value, str):
            if value in ('auto', 'none', 'required'):
                return value
            return {'type': 'function', 'name_sha256': hashlib.sha256(value.encode()).hexdigest()}
        if isinstance(value, dict) and value.get('type') == 'function':
            digest = value.get('name_sha256')
            if isinstance(digest, str) and _HASH.fullmatch(digest):
                return {'type': 'function', 'name_sha256': digest}
            function = value.get('function')
            name = function.get('name') if isinstance(function, dict) else value.get('name')
            if isinstance(name, str) and name:
                return {'type': 'function', 'name_sha256': hashlib.sha256(name.encode()).hexdigest()}
    if key == 'timeout_seconds':
        if _number(value) and value >= 0:
            return value
        if isinstance(value, dict) and value and set(value) <= {'connect', 'read', 'write', 'pool'}:
            if all(v is None or (_number(v) and v >= 0) for v in value.values()):
                return deepcopy(value)
    return None


def build_configuration_snapshot(values, *, capture_kind='historical_partial',
                                 source='historical.record', sources=None,
                                 fingerprints=None, capture_layer=None, statuses=None):
    """Project known values without guessing missing settings or retaining extras.

    ``explicit`` means present at the captured dispatch boundary, not proof of
    provider support. Historical values are ``recorded``. Bad/unknown values are
    omitted, including unapproved endpoints and raw response/tool schemas.
    """
    if capture_kind not in ('before_dispatch', 'historical_partial'):
        raise ValueError('Invalid configuration capture kind')
    layer = capture_layer or ('historical_records' if capture_kind == 'historical_partial'
                              else 'sdk_adapter_before_dispatch')
    if layer not in _LAYERS or (capture_kind == 'historical_partial') != (layer == 'historical_records'):
        raise ValueError('Invalid configuration capture layer')
    if not isinstance(values, dict) or not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError('Invalid configuration input')
    sources = sources if isinstance(sources, dict) else {}
    statuses = statuses if isinstance(statuses, dict) else {}
    fields = {}
    for key in CONFIGURATION_FIELDS:
        status = statuses.get(key)
        if status not in (None, 'explicit', 'recorded', 'not_recorded', 'not_sent'):
            raise ValueError('Invalid configuration field status')
        if status == 'not_sent':
            if values.get(key) is not None:
                raise ValueError('An omitted field cannot have a value')
            origin = sources.get(key, 'request.omitted')
            if not isinstance(origin, str) or not _SOURCE.fullmatch(origin):
                raise ValueError('Invalid omitted configuration source')
            fields[key] = {'value': None, 'status': 'not_sent', 'source': origin}
            continue
        value = _safe_value(key, values.get(key))
        origin = sources.get(key, source)
        if not isinstance(origin, str) or not _SOURCE.fullmatch(origin):
            value = None
        default_status = 'explicit' if capture_kind == 'before_dispatch' else 'recorded'
        if status == 'not_recorded':
            value = None
        if capture_kind == 'historical_partial' and status == 'explicit':
            raise ValueError('Historical values must use recorded status')
        fields[key] = {'value': value,
                       'status': (status or default_status) if value is not None else 'not_recorded',
                       'source': origin if value is not None else 'not_recorded'}
    fingerprints = fingerprints if isinstance(fingerprints, dict) else {}
    result = {'schema_version': 'model-call-config-v1', 'capture_kind': capture_kind,
              'capture_layer': layer, 'effective_configuration': 'unverified', 'fields': fields,
              'fingerprints': {key: fingerprints[key] for key in FINGERPRINT_FIELDS
                               if isinstance(fingerprints.get(key), str) and _HASH.fullmatch(fingerprints[key])}}
    result['sha256'] = _hash(result)
    return result


def validate_configuration_snapshot(snapshot):
    """Return a detached safe snapshot, rejecting unknown fields or a bad hash."""
    try:
        if not isinstance(snapshot, dict) or set(snapshot) != {
                'schema_version', 'capture_kind', 'capture_layer', 'effective_configuration',
                'fields', 'fingerprints', 'sha256'}:
            raise ValueError
        fields = snapshot['fields']
        if not isinstance(fields, dict) or set(fields) not in (
                set(CONFIGURATION_FIELDS), set(_PRE_QWEN_CONFIGURATION_FIELDS), set(_LEGACY_CONFIGURATION_FIELDS)):
            raise ValueError
        expected = build_configuration_snapshot(
            {key: field['value'] for key, field in fields.items()},
            capture_kind=snapshot['capture_kind'], capture_layer=snapshot['capture_layer'],
            sources={key: field['source'] for key, field in fields.items()},
            statuses={key: field['status'] for key, field in fields.items()},
            fingerprints=snapshot['fingerprints'])
        if set(fields) != set(CONFIGURATION_FIELDS):
            # v1 originally had 16 fields. Keep historical bytes/identity: a
            # reader must not add a new unknown field and invalidate old hashes.
            for key in set(CONFIGURATION_FIELDS)-set(fields):
                del expected['fields'][key]
            expected['sha256'] = _hash({key: value for key, value in expected.items() if key != 'sha256'})
        if snapshot != expected:
            raise ValueError
        return expected
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('Invalid model configuration snapshot') from None


def _get(value, key):
    try:
        return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
    except Exception:
        return None


def _argument(args, kwargs, name, index):
    return kwargs[name] if name in kwargs else args[index] if len(args) > index else None


def capture_model_configuration(provider, model, inner, args, kwargs):
    """Observe SDK arguments/client values without touching credentials or I/O."""
    settings = _argument(args, kwargs, 'model_settings', 2)
    values = {'provider': provider, 'model': model}
    sources = {'provider': 'meter.provider', 'model': 'meter.requested_model'}
    for key in ('max_tokens', 'temperature', 'top_p', 'top_k', 'seed', 'tool_choice', 'parallel_tool_calls'):
        values[key] = _get(settings, key)
        sources[key] = 'sdk.model_settings.' + key
    reasoning = _get(settings, 'reasoning')
    values['reasoning_effort'] = _get(reasoning, 'effort')
    sources['reasoning_effort'] = 'sdk.model_settings.reasoning.effort'
    # Select allowed settings individually; never serialize freeform extras.
    # The SDK expands extra_args, then its HTTP client merges extra_body.
    for extra_name in ('extra_args', 'extra_body'):
        extra = _get(settings, extra_name)
        if isinstance(extra, dict):
            for key in _REQUEST_FIELDS:
                if key in extra:
                    values[key] = extra[key]
                    sources[key] = 'sdk.model_settings.' + extra_name + '.' + key
    if _get(inner, 'output_limit_parameter') == 'max_completion_tokens':
        values['max_completion_tokens'] = _get(settings, 'max_tokens')
        sources['max_completion_tokens'] = 'adapter.total_output_from_sdk_max_tokens'
        values['max_tokens'] = None
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    from agents.models.openai_responses import OpenAIResponsesModel, OpenAIResponsesWSModel
    if isinstance(inner, OpenAIChatCompletionsModel):
        values.setdefault('api_format', 'chat_completions')
        values.setdefault('stream', False)
    elif isinstance(inner, OpenAIResponsesModel) and not isinstance(inner, OpenAIResponsesWSModel):
        values.setdefault('api_format', 'responses')
        values.setdefault('stream', False)
    sources.setdefault('api_format', 'sdk.adapter.type')
    sources.setdefault('stream', 'sdk.adapter.get_response')
    client = _get(inner, '_client')
    import httpx2 as httpx
    base = _get(client, 'base_url')
    if base is not None:
        # Only known client URL objects are converted, never arbitrary reprs.
        values['base_url'] = str(base) if isinstance(base, (str, httpx.URL)) else None
    timeout = _get(settings, 'timeout')
    timeout_source = 'sdk.model_settings.timeout'
    if timeout is None:
        timeout = _get(client, 'timeout')
        timeout_source = 'sdk.client.timeout'
    values['timeout_seconds'] = ({key: getattr(timeout, key) for key in ('connect', 'read', 'write', 'pool')}
                                 if isinstance(timeout, httpx.Timeout) else timeout)
    values['max_retries'] = _get(client, 'max_retries')
    sources.update(base_url='sdk.client.base_url', timeout_seconds=timeout_source, max_retries='sdk.client.max_retries')
    fingerprints = {}
    system = _argument(args, kwargs, 'system_instructions', 0)
    if isinstance(system, str):
        fingerprints['system_sha256'] = hashlib.sha256(system.encode()).hexdigest()
    supplied = _argument(args, kwargs, 'input', 1)
    if supplied is not None:
        try:
            fingerprints['input_sha256'] = _hash(supplied)
        except (TypeError, ValueError, OverflowError, RecursionError):
            pass
    tools = _argument(args, kwargs, 'tools', 3)
    handoffs = _argument(args, kwargs, 'handoffs', 5)
    if isinstance(tools, list) and (handoffs is None or isinstance(handoffs, list)):
        names = [_get(tool, 'name') for tool in tools] + [_get(handoff, 'tool_name') for handoff in handoffs or []]
        if all(isinstance(name, str) for name in names):
            fingerprints['tools_sha256'] = _hash(names)
    schema = _argument(args, kwargs, 'output_schema', 4)
    if schema is not None:
        from agents.agent_output import AgentOutputSchema
        if isinstance(schema, AgentOutputSchema):
            try:
                if not schema.is_plain_text():
                    fingerprints['output_schema_sha256'] = _hash(schema.json_schema())
                    # Requested SDK format, before any provider adapter changes.
                    if 'response_format' not in values:
                        adapter_format = _get(inner, 'wire_response_format')
                        values['response_format'] = {'type': adapter_format if adapter_format == 'json_object' else 'json_schema'}
                        sources['response_format'] = 'adapter.wire_response_format' if adapter_format == 'json_object' else 'sdk.output_schema'
            except (TypeError, ValueError, OverflowError, RecursionError):
                pass
    return build_configuration_snapshot(values, capture_kind='before_dispatch',
        source='sdk.captured', sources=sources, fingerprints=fingerprints)
