"""One explicitly configured request on caller-selected, frozen evidence. No batch/retry."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import httpx2 as httpx
from agents import ModelSettings

from uteki.agents.runtime.local_credentials import load_provider_key, PROVIDER_KEYS
from uteki.agents.runtime.model_configuration import build_configuration_snapshot
from uteki.agents.runtime.run_budget import RunBudget, reserve_request

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / 'experiments/model_comparison/2026-10-06-sonnet-deepseek-small-v1/run_comparison.py'
PRIOR_HASH = 'ca7c5ad62eecda125acef97cc53aa7c91443908fe90098ff23eb5485113a4d62'
PROFILE_KEYS = {'schema_version', 'id', 'provider', 'model', 'api_format', 'thinking',
                'reasoning_effort', 'max_tokens', 'timeout_seconds', 'max_retries', 'stream'}


def helpers():
    if PRIOR.is_symlink() or hashlib.sha256(PRIOR.read_bytes()).hexdigest() != PRIOR_HASH:
        raise ValueError('Frozen validation implementation changed')
    spec = importlib.util.spec_from_file_location('frozen_trial_validation', PRIOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_profile(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16000:
        raise ValueError('Explicit regular profile required')
    raw = path.read_bytes()
    p = json.loads(raw)
    if not isinstance(p, dict):
        raise ValueError('Unsupported or incomplete profile')
    version = p.get('schema_version')
    if not ((version == 'explicit-single-trial-profile-v1' and set(p) == PROFILE_KEYS)
            or (version == 'explicit-single-trial-profile-v2' and set(p) == PROFILE_KEYS | {'sampling'})):
        raise ValueError('Unsupported or incomplete profile')
    if not re.fullmatch(r'[a-z0-9-]{1,100}', str(p['id'])):
        raise ValueError('Invalid profile identity')
    identity = (p['provider'], p['model'], p['api_format'], p['thinking'])
    if identity not in {('aihubmix', 'claude-sonnet-5-5', 'anthropic_messages', 'adaptive'),
                       ('deepseek', 'deepseek-v4-pro', 'openai_chat_completions', 'enabled')}:
        raise ValueError('Unsupported explicit provider/model/protocol/thinking selection')
    if p['reasoning_effort'] not in {'low', 'high'}:
        raise ValueError('An explicit supported effort is required')
    if (type(p['max_tokens']) is not int or not 1024 <= p['max_tokens'] <= 24000
            or type(p['timeout_seconds']) is not int or not 10 <= p['timeout_seconds'] <= 300
            or type(p['max_retries']) is not int or p['max_retries'] != 0 or p['stream'] is not False):
        raise ValueError('Only one bounded non-streaming request without retries is permitted')
    if version == 'explicit-single-trial-profile-v2':
        sampling = p['sampling']
        if not isinstance(sampling, dict) or set(sampling) != {'temperature', 'top_p', 'top_k', 'seed'}:
            raise ValueError('All sampling decisions must be explicit')
        if any(sampling[k] is not None for k in ('temperature', 'top_k', 'seed')):
            raise ValueError('Unsupported sampling control for this model/mode')
        if p['provider'] == 'aihubmix' and sampling['top_p'] is not None:
            raise ValueError('Sonnet 5.5 does not support custom sampling')
        if p['provider'] == 'deepseek' and (type(sampling['top_p']) not in (int, float)
                or not 0.95 <= sampling['top_p'] <= 1.0):
            raise ValueError('DeepSeek thinking top_p must be explicitly within 0.95..1.0')
    return p, hashlib.sha256(raw).hexdigest()


def prepare(profile_path, prepared):
    h = helpers()
    p, profile_hash = load_profile(profile_path)
    packet, messages, metadata = h.load_prepared(prepared)
    if p['api_format'] == 'anthropic_messages':
        endpoint = 'https://aihubmix.com/v1/messages'
        base = 'https://aihubmix.com'
        body = {'model': p['model'], 'system': messages[0]['content'], 'messages': messages[1:],
                'thinking': {'type': p['thinking']}, 'output_config': {'effort': p['reasoning_effort']},
                'max_tokens': p['max_tokens'], 'stream': False}
    else:
        endpoint = 'https://api.deepseek.com/chat/completions'
        base = 'https://api.deepseek.com'
        body = {'model': p['model'], 'messages': messages,
                'thinking': {'type': p['thinking']}, 'reasoning_effort': p['reasoning_effort'],
                'max_tokens': p['max_tokens'], 'stream': False}
    values = {key: p[key] for key in ('provider', 'model', 'api_format', 'max_tokens',
              'reasoning_effort', 'stream', 'timeout_seconds', 'max_retries')}
    values['api_format'] = 'anthropic_messages' if p['api_format'] == 'anthropic_messages' else 'chat_completions'
    values.update(base_url=base, thinking={'type': p['thinking']})
    omitted = {'temperature', 'top_p', 'top_k', 'seed', 'response_format', 'tool_choice', 'parallel_tool_calls'}
    sources = {}
    if 'sampling' in p:
        if p['provider'] == 'aihubmix':
            sources.update({k: 'policy.sonnet55_sampling_unsupported' for k in ('temperature', 'top_p', 'top_k')})
        else:
            body['top_p'] = values['top_p'] = p['sampling']['top_p']
            omitted.remove('top_p')
            sources.update(temperature='policy.deepseek_thinking_sampling_ignored',
                           top_k='policy.deepseek_top_k_unsupported')
        sources['seed'] = 'policy.seed_not_documented'
    snapshot = build_configuration_snapshot(values, capture_kind='before_dispatch',
        capture_layer='http_request_before_dispatch', source='http_request',
        statuses={key: 'not_sent' for key in omitted}, sources=sources,
        fingerprints={'system_sha256': metadata['system_sha256'],
                      'input_sha256': metadata['packet_sha256']})
    price = deepcopy(h.pricing_snapshot(p['provider'], p['model']))
    return h, p, packet, messages, metadata, body, endpoint, snapshot, price, profile_hash


def reserve(budget, price, body, profile):
    return reserve_request(budget, price, (), {'request': body,
        'model_settings': ModelSettings(max_tokens=profile['max_tokens'])}, max_request_bytes=50000)


def inspect(profile_path, prepared, budget_usd):
    return inspect_prepared(prepare(profile_path, prepared), budget_usd)


def inspect_prepared(prepared_request, budget_usd):
    h, p, _, _, meta, body, _, snap, price, profile_hash = prepared_request
    with tempfile.TemporaryDirectory(prefix='uteki-explicit-trial-') as directory:
        budget = RunBudget(Path(directory) / 'budget.sqlite', budget_usd)
        reservation, amount = reserve(budget, price, body, p)
        budget.settle(reservation, '0')
    return {**meta, 'profile_id': p['id'], 'profile_sha256': profile_hash,
            'configuration_snapshot': snap, 'pricing_snapshot': price,
            'budget_limit_usd': str(budget_usd), 'conservative_request_reservation_usd': amount,
            'max_output_tokens_per_arm': p['max_tokens'], 'timeout_seconds': p['timeout_seconds'],
            'requests_per_arm': 1, 'automatic_retries': 0,
            'comparison_limit': 'Explicit request settings; provider effective settings are not independently echoed.',
            'cost_note': 'Public-price estimate, not an account bill.'}


def receipt_identifier(value):
    """Receipts carry bounded identifiers, never arbitrary provider objects."""
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}', value) else None


def native_usage(payload):
    raw = payload.get('usage')
    if not isinstance(raw, dict):
        return None
    keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
    if any(key in raw and (type(raw[key]) is not int or raw[key] < 0) for key in keys):
        return None
    if not {'input_tokens', 'output_tokens'} <= set(raw):
        return None
    # Cache writes were not requested; unknown write category must not be underpriced.
    if raw.get('cache_creation_input_tokens', 0) != 0:
        return None
    cached = raw.get('cache_read_input_tokens', 0)
    tokens = raw['input_tokens'] + cached
    result = {'prompt_tokens': tokens, 'completion_tokens': raw['output_tokens'],
              'total_tokens': tokens + raw['output_tokens']}
    if 'cache_read_input_tokens' in raw:
        result['prompt_tokens_details'] = {'cached_tokens': cached}
    thinking = raw.get('output_tokens_details')
    if isinstance(thinking, dict) and 'thinking_tokens' in thinking:
        value = thinking['thinking_tokens']
        if type(value) is not int or not 0 <= value <= raw['output_tokens']:
            return None
        result['completion_tokens_details'] = {'reasoning_tokens': value}
    return result


async def run_once(profile_path, prepared, output, budget_usd, *, client_factory=httpx.AsyncClient,
                   key_loader=load_provider_key, budget_path=None):
    prepared_request = prepare(profile_path, prepared)
    h, p, packet, messages, meta, body, endpoint, snapshot, price, profile_hash = prepared_request
    inspection = inspect_prepared(prepared_request, budget_usd)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    arm = output / '01-model'
    arm.mkdir()
    key = ''

    def write(path, value, text=False):
        value = value if text else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        if key:
            value = value.replace(key, '[REDACTED]')
        with path.open('x') as stream:
            stream.write(value)

    provenance = {'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'validator_sha256': PRIOR_HASH, 'python_version': sys.version.split()[0],
                  'http_client_version': httpx.__version__,
                  'request_body_sha256': hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()).hexdigest()}
    report = {'schema_version': 'small-model-comparison-v1', 'origin': 'independent_bounded_model_experiment',
              'started_at': h.utc_now(), 'input': meta, 'limits': inspection, 'arms': [],
              'status': 'started', 'actual_billed_usd': None, 'execution_provenance': provenance}
    write(output / 'request.json', {'messages': messages})
    write(output / 'http-request.json', {'endpoint': endpoint, 'body': body})
    write(output / 'configuration.json', snapshot)
    write(output / 'profile.json', p)
    write(output / 'experiment-start.json', report)
    try:
        budget = RunBudget(budget_path if budget_path is not None else output / 'budget.sqlite', budget_usd)
        reservation, amount = reserve(budget, price, body, p)
    except Exception as error:
        report.update(status='stopped_before_dispatch', error_type=type(error).__name__, ended_at=h.utc_now())
        write(output / 'summary.json', report)
        raise
    record = {'provider': p['provider'], 'requested_model': p['model'],
              'reasoning_configuration': 'thinking_' + p['thinking'] + '_' + p['reasoning_effort'],
              'configuration_snapshot': snapshot, 'profile_id': p['id'], 'profile_sha256': profile_hash,
              'execution_provenance': provenance,
              'input': meta, 'pricing_snapshot': price, 'started_at': h.utc_now(), 'status': 'started',
              'reservation_id': reservation, 'reserved_usd': amount, 'raw_usage': None,
              'usage_source': 'provider_raw', 'estimated_usd': None, 'actual_billed_usd': None}
    sent, settled = False, False
    started = time.monotonic()
    try:
        write(arm / 'start.json', record)
        key_loader(ROOT, p['provider'])
        key = os.environ[PROVIDER_KEYS[p['provider']]]
        headers = ({'x-api-key': key, 'anthropic-version': '2023-06-01'}
                   if p['api_format'] == 'anthropic_messages' else {'Authorization': 'Bearer ' + key})
        with h.quiet_sdk():
            async with client_factory(timeout=p['timeout_seconds'], follow_redirects=False) as client:
                sent = True
                response = await asyncio.wait_for(client.post(endpoint, json=body, headers=headers),
                                                 timeout=p['timeout_seconds'])
                record['http_status'] = response.status_code
                record['request_id'] = receipt_identifier(response.headers.get('request-id') or response.headers.get('x-request-id'))
                response.raise_for_status()
                payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('Invalid provider response')
        if p['api_format'] == 'anthropic_messages':
            usage = native_usage(payload)
            content = ''.join(block['text'] for block in payload.get('content', [])
                              if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str))
            provider_finish = receipt_identifier(payload.get('stop_reason'))
            finish = {'end_turn': 'stop', 'max_tokens': 'length'}.get(provider_finish, provider_finish)
        else:
            usage = h.select_usage(payload.get('usage'))
            choices = payload.get('choices')
            choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else {}
            message = choice.get('message') or {}
            content = message.get('content') if isinstance(message.get('content'), str) else ''
            provider_finish = finish = receipt_identifier(choice.get('finish_reason'))
        cost = str((Decimal(usage['prompt_tokens']) * Decimal(price['input_per_million'])
                    + Decimal(usage['completion_tokens']) * Decimal(price['output_per_million'])) / 1000000) if usage else None
        budget.settle(reservation, cost)
        settled = True
        record.update(status='received' if usage else 'usage_unknown', raw_usage=usage,
            usage_presence='reported' if usage else 'absent_or_invalid', estimated_usd=cost,
            returned_model=receipt_identifier(payload.get('model')), response_id=receipt_identifier(payload.get('id')),
            system_fingerprint=receipt_identifier(payload.get('system_fingerprint')),
            finish_reason=finish, provider_finish_reason=provider_finish,
            ended_at=h.utc_now(), elapsed_seconds=time.monotonic()-started)
        write(arm / 'response-metadata.json', record)
        write(arm / 'visible-output.txt', content, text=True)
        validation, parsed = h.validate_output(content, packet, finish)
        write(arm / 'validation.json', validation)
        if parsed is not None:
            write(arm / 'parsed.json', parsed)
        record['validation'] = validation
        report['status'] = ('stopped_usage_unknown' if usage is None else 'completed'
                            if validation['status'] == 'structure_and_citations_valid' else 'completed_with_invalid_outputs')
    except BaseException as error:
        if not settled:
            budget.settle(reservation, None if sent else '0')
        failure = h.error_metadata(error)
        if record.get('http_status') is not None:
            failure['http_status'] = record['http_status']
        record.update(status='failed', **failure, ended_at=h.utc_now(),
                      elapsed_seconds=time.monotonic()-started)
        write(arm / 'failure.json', record)
        for filename, value, is_text in (
                ('response-metadata.json', record, False),
                ('validation.json', {'status': 'invalid', 'errors': ['request_failed'],
                                     'gold_scoring': 'not_performed', 'semantic_correctness': 'not_evaluated'}, False),
                ('visible-output.txt', '', True)):
            if not (arm / filename).exists():
                write(arm / filename, value, text=is_text)
        report['status'] = 'stopped_request_failure'
        if isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
    finally:
        report.update(arms=[record], ended_at=h.utc_now(), budget=budget.summary())
        write(output / 'summary.json', report)
    serialized = json.dumps(report, ensure_ascii=False)
    return json.loads(serialized.replace(key, '[REDACTED]') if key else serialized)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--prepared', required=True, type=Path)
    parser.add_argument('--budget-usd', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if args.dry_run:
            report = inspect(args.profile, args.prepared, args.budget_usd)
        else:
            if args.output is None:
                parser.error('--output must be a new directory')
            result = asyncio.run(run_once(args.profile, args.prepared, args.output, args.budget_usd))
            report = {'status': result['status'], 'budget': result['budget']}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if args.dry_run or report['status'] == 'completed' else 1
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
