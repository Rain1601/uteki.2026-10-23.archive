"""Runtime helpers used by the Claude dialogue window.

Copied verbatim (S4, 2026-10-23) from the retired uteki.agents.runtime
modules named in each section, so the window no longer depends on legacy
code. Behaviour is unchanged; edit here, not in the archived originals.
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import stat
from threading import Lock


# ---- from uteki.agents.runtime.claude_messages ----

ENDPOINT = 'https://aihubmix.com/v1/messages'

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z')

_COUNTERS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')

_LOG_LOCK = Lock()

_LOG_USERS = 0

_LOG_PREVIOUS_DISABLE = 0

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


# ---- from uteki.agents.runtime.call_costs ----

def estimate_anthropic_usage(usage, pricing):
    """Anthropic input excludes cache reads; unsupported charges stay unknown."""
    if not isinstance(usage, dict) or not pricing:
        return None
    if any(isinstance(name, str) and 'cache' in name.lower()
           and name not in ('cache_read_input_tokens', 'cache_creation_input_tokens', 'cache_creation')
           for name in usage):
        return None
    for name in ('input_tokens', 'output_tokens'):
        if type(usage.get(name)) is not int or usage[name] < 0:
            return None
    for name in ('cache_read_input_tokens', 'cache_creation_input_tokens'):
        if name in usage and (type(usage[name]) is not int or usage[name] < 0):
            return None
    # This adapter sends no cache controls or server tools; their rates are not
    # part of its registered price snapshot. Never silently omit such charges.
    if usage.get('cache_creation_input_tokens', 0):
        return None
    for name in ('cache_creation', 'server_tool_use'):
        if name in usage and (not isinstance(usage[name], dict)
                or any(type(n) is not int or n != 0 for n in usage[name].values())):
            return None
    try:
        rates = [Decimal(str(pricing[name])) for name in ('input_per_million', 'output_per_million')]
        cached = usage.get('cache_read_input_tokens', 0)
        cache_rate = Decimal(str(pricing['cached_input_per_million'])) if cached else Decimal(0)
        if not all(rate.is_finite() and rate >= 0 for rate in (*rates, cache_rate)):
            return None
        return str((Decimal(usage['input_tokens']) * rates[0]
                    + Decimal(usage['output_tokens']) * rates[1] + Decimal(cached) * cache_rate) / Decimal(1000000))
    except (ArithmeticError, ValueError, TypeError, KeyError):
        return None


# ---- from uteki.agents.runtime.local_credentials ----

PROVIDER_KEYS = {'aihubmix': 'AIHUBMIX_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY'}

PROVIDER_KEY_ALIASES = {'aihubmix': ('AIHUBMIX_API_KEY', 'AI_HUB_MIX_API_KEY'),
                        'deepseek': ('DEEPSEEK_API_KEY',)}

def load_provider_key(root, provider):
    if provider not in PROVIDER_KEYS:
        raise ValueError('Unsupported credential provider')
    key_name = PROVIDER_KEYS[provider]
    aliases = PROVIDER_KEY_ALIASES[provider]
    configured = [os.environ[name] for name in aliases if os.environ.get(name)]
    if configured:
        if len(set(configured)) != 1:
            raise ValueError('Conflicting credential aliases for ' + provider)
        os.environ[key_name] = configured[0]
        return 'environment'
    path = Path(root) / '.env'
    if not path.exists():
        raise ValueError(f'Set {key_name} in environment or local .env')
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError('Local .env must be a private regular file (mode 600)')
    found = {}
    for line in path.read_text().splitlines():
        name, sep, value = line.strip().partition('=')
        name = name.removeprefix('export ').strip()
        if sep and name in aliases:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            if name in found:
                raise ValueError('Duplicate credential entry for ' + name)
            found[name] = value
    if not found or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', value) for value in found.values()):
        raise ValueError('Local .env needs a nonempty ' + ' or '.join(aliases))
    if len(set(found.values())) != 1:
        raise ValueError('Conflicting credential aliases for ' + provider)
    os.environ[key_name] = next(iter(found.values()))
    return 'local_env_file'


# ---- from uteki.agents.runtime.model_configuration ----

CONFIGURATION_FIELDS = (
    'provider', 'model', 'api_format', 'base_url', 'max_tokens', 'thinking',
    'reasoning_effort', 'temperature', 'top_p', 'top_k', 'seed', 'response_format',
    'tool_choice', 'parallel_tool_calls', 'stream', 'timeout_seconds', 'max_retries',
    'max_completion_tokens', 'preserve_thinking',
)

_PRE_QWEN_CONFIGURATION_FIELDS = tuple(key for key in CONFIGURATION_FIELDS if key not in ('max_completion_tokens', 'preserve_thinking'))

_LEGACY_CONFIGURATION_FIELDS = tuple(key for key in _PRE_QWEN_CONFIGURATION_FIELDS if key != 'top_k')

FINGERPRINT_FIELDS = ('system_sha256', 'input_sha256', 'tools_sha256', 'output_schema_sha256')

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
