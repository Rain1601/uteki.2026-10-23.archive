"""Private, append-only local Claude dialogue; no provider tools or hidden retries."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import httpx2 as httpx
from uteki.agents.runtime.call_costs import estimate_anthropic_usage
from uteki.agents.runtime.claude_messages import ENDPOINT, _identifier, _numeric_usage, _suppress_transport_logging
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.model_configuration import build_configuration_snapshot, validate_configuration_snapshot

MODEL = 'claude-opus-5-5'
TIMEOUT = 240
MAX_BYTES = 400000


class DialogueError(ValueError):
    """Only fixed, non-sensitive error codes leave the CLI."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _private(path, directory=False):
    mode = path.lstat().st_mode
    if (path.is_symlink() or not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode))
            or stat.S_IMODE(mode) != (0o700 if directory else 0o600)):
        raise DialogueError('session_permissions_or_file_type_invalid')


def _read(path):
    _private(path)
    return path.read_bytes()


def _input(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DialogueError('input_must_be_regular_file')
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise DialogueError('input_must_be_utf8') from None
    if len(raw) > MAX_BYTES or not text.strip():
        raise DialogueError('input_empty_or_too_large')
    return raw


def _price(value):
    required = {'model', 'input_per_million', 'output_per_million', 'cache_read_per_million', 'source_url', 'checked_date'}
    if not isinstance(value, dict) or set(value) != required or value['model'] != MODEL:
        raise DialogueError('invalid_explicit_price')
    for field in ('input_per_million', 'output_per_million', 'cache_read_per_million'):
        try:
            amount = Decimal(str(value[field]))
        except (InvalidOperation, ValueError, TypeError):
            raise DialogueError('invalid_explicit_price') from None
        if not amount.is_finite() or amount < 0:
            raise DialogueError('invalid_explicit_price')
    if (Decimal(str(value['input_per_million'])) <= 0 or Decimal(str(value['output_per_million'])) <= 0
            or not isinstance(value['source_url'], str) or not value['source_url'].startswith('https://')):
        raise DialogueError('invalid_explicit_price')
    try:
        date.fromisoformat(value['checked_date'])
    except (ValueError, TypeError):
        raise DialogueError('invalid_explicit_price') from None
    return value


def init_session(session, *, system_file, model, budget_usd, max_calls, max_tokens, price_file):
    if model != MODEL or type(max_calls) is not int or not 1 <= max_calls <= 100:
        raise DialogueError('invalid_model_or_call_limit')
    if type(max_tokens) is not int or not 1 <= max_tokens <= 16000:
        raise DialogueError('invalid_output_limit')
    try:
        budget = Decimal(str(budget_usd))
    except (InvalidOperation, ValueError, TypeError):
        raise DialogueError('invalid_budget') from None
    if not budget.is_finite() or budget <= 0:
        raise DialogueError('invalid_budget')
    system = _input(system_file)
    try:
        price_value = json.loads(_input(price_file))
    except (ValueError, TypeError):
        raise DialogueError('invalid_explicit_price') from None
    price = _json(_price(price_value))
    session = Path(session).absolute()
    if session.exists() or session.is_symlink():
        raise DialogueError('session_exists')
    missing = []
    parent = session.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    session.mkdir(mode=0o700)
    (session / 'turns').mkdir(mode=0o700)
    _write(session / '.lock', b'')
    _write(session / 'system.txt', system)
    _write(session / 'price.json', price)
    config = {'schema_version': 'claude-dialogue-v1', 'created_at': _now(), 'model': model,
              'budget_usd': str(budget), 'max_calls': max_calls, 'max_tokens': max_tokens,
              'timeout_seconds': TIMEOUT, 'max_retries': 0, 'thinking': {'type': 'adaptive'},
              'reasoning_effort': 'high', 'stream': False,
              'system_sha256': _sha(system), 'price_sha256': _sha(price)}
    raw = _json(config)
    _write(session / 'session.json', raw)
    _write(session / 'session.sha256', _sha(raw).encode())
    return {'session': str(session), 'status': 'initialized', 'model': model, 'budget_usd': str(budget)}


@contextmanager
def _locked(session):
    _private(session, True)
    _private(session / '.lock')
    with (session / '.lock').open('rb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DialogueError('session_locked') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _state(session):
    raw = _read(session / 'session.json')
    if _read(session / 'session.sha256').decode() != _sha(raw):
        raise DialogueError('session_configuration_changed')
    config = json.loads(raw)
    system, price_raw = _read(session / 'system.txt'), _read(session / 'price.json')
    if _sha(system) != config['system_sha256'] or _sha(price_raw) != config['price_sha256']:
        raise DialogueError('session_inputs_changed')
    price = _price(json.loads(price_raw))
    _private(session / 'turns', True)
    folders = sorted((session / 'turns').iterdir())
    history, receipts = [], []
    for index, folder in enumerate(folders, 1):
        if folder.name != f'{index:04d}':
            raise DialogueError('turn_sequence_invalid')
        _private(folder, True)
        if not (folder / 'receipt.json').exists() or not (folder / 'receipt.sha256').exists():
            started = json.loads(_read(folder / 'started.json')) if (folder / 'started.json').exists() else {}
            receipts.append({'turn': index, 'status': 'interrupted', 'estimated_usd': None,
                             'reserved_usd': started.get('reserved_usd', config['budget_usd'])})
            continue
        receipt = json.loads(_read(folder / 'receipt.json'))
        if _sha(_read(folder / 'receipt.json')) != _read(folder / 'receipt.sha256').decode():
            raise DialogueError('turn_receipt_changed')
        for name, field in (('user.md', 'user_sha256'), ('request.json', 'request_sha256'),
                            ('answer.md', 'answer_sha256'), ('configuration.json', 'configuration_sha256')):
            if _sha(_read(folder / name)) != receipt[field]:
                raise DialogueError('turn_artifact_changed')
        request = json.loads(_read(folder / 'request.json'))
        if (_read(folder / 'request.sha256').decode() != receipt['request_sha256']
                or receipt['session_sha256'] != _sha(raw)
                or request['messages'] != history + [{'role': 'user', 'content': _read(folder / 'user.md').decode()}]):
            raise DialogueError('turn_history_changed')
        validate_configuration_snapshot(json.loads(_read(folder / 'configuration.json')))
        receipts.append(receipt)
        if receipt['status'] == 'completed':
            history.extend([{'role': 'user', 'content': _read(folder / 'user.md').decode()},
                            {'role': 'assistant', 'content': _read(folder / 'answer.md').decode()}])
    return config, system.decode(), price, history, receipts, _sha(raw)


def _summary(session, config, history, receipts, include_history=False):
    spent = sum((Decimal(r['estimated_usd']) for r in receipts if r['estimated_usd'] is not None), Decimal(0))
    held = sum((Decimal(r['reserved_usd']) for r in receipts if r['estimated_usd'] is None), Decimal(0))
    result = {'session': str(session), 'model': config['model'], 'budget_usd': config['budget_usd'],
              'attempted_turns': len(receipts), 'completed_turns': len(history) // 2,
              'max_calls': config['max_calls'], 'estimated_spent_usd': str(spent), 'held_usd': str(held),
              'remaining_usd': str(Decimal(config['budget_usd']) - spent - held),
              'unknown_cost_turns': sum(r['estimated_usd'] is None for r in receipts),
              'blocked': any(r['status'] != 'completed' for r in receipts), 'turns': receipts,
              'actual_billed_usd': None}
    if include_history:
        result['history'] = history
    return result


def inspect_session(session, include_history=False):
    session = Path(session).absolute()
    with _locked(session):
        config, _, _, history, receipts, _ = _state(session)
        return _summary(session, config, history, receipts, include_history)


async def turn(session, *, message_file, credentials_root, client_factory=None):
    session = Path(session).absolute()
    with _locked(session):
        config, system, price, history, receipts, session_sha = _state(session)
        summary = _summary(session, config, history, receipts)
        if summary['blocked']:
            raise DialogueError('previous_turn_failed_or_interrupted')
        if len(receipts) >= config['max_calls']:
            raise DialogueError('session_call_limit')
        user = _input(message_file)
        body = {'model': config['model'], 'system': system,
                'messages': history + [{'role': 'user', 'content': user.decode()}],
                'max_tokens': config['max_tokens'], 'thinking': {'type': 'adaptive'},
                'output_config': {'effort': 'high'}, 'stream': False}
        raw = _json(body)
        if len(raw) > MAX_BYTES:
            raise DialogueError('request_too_large')
        reserve = ((Decimal(len(raw) + 16000) * Decimal(str(price['input_per_million']))
                    + Decimal(config['max_tokens']) * Decimal(str(price['output_per_million']))) / 1000000)
        if reserve > Decimal(summary['remaining_usd']):
            raise DialogueError('session_budget_exhausted')
        load_provider_key(credentials_root, 'aihubmix')
        key = os.environ['AIHUBMIX_API_KEY']
        if key.encode() in raw:
            raise DialogueError('credential_in_request')
        index = len(receipts) + 1
        folder = session / 'turns' / f'{index:04d}'
        folder.mkdir(mode=0o700)
        snapshot = build_configuration_snapshot(
            {'provider': 'aihubmix', 'model': config['model'], 'api_format': 'anthropic_messages',
             'base_url': 'https://aihubmix.com', 'max_tokens': config['max_tokens'], 'thinking': body['thinking'],
             'reasoning_effort': 'high', 'stream': False, 'timeout_seconds': TIMEOUT, 'max_retries': 0},
            capture_kind='before_dispatch', capture_layer='http_request_before_dispatch', source='http_request',
            statuses={name: 'not_sent' for name in ('temperature', 'top_p', 'top_k', 'seed',
                      'response_format', 'tool_choice', 'parallel_tool_calls')},
            fingerprints={'system_sha256': _sha(system.encode()), 'input_sha256': _sha(_json(body['messages'])),
                          'tools_sha256': _sha(b'[]')})
        config_raw = _json(snapshot)
        receipt = {'schema_version': 'claude-dialogue-turn-v1', 'turn': index, 'status': 'failed',
            'runner_sha256': _sha(Path(__file__).read_bytes()),
            'started_at': _now(), 'session_sha256': session_sha, 'user_sha256': _sha(user),
            'request_sha256': _sha(raw), 'request_bytes': len(raw), 'configuration_sha256': _sha(config_raw),
            'reserved_usd': str(reserve), 'estimated_usd': None, 'actual_billed_usd': None,
            'cost_basis': 'frozen_public_price_estimate_not_bill', 'dispatch_status': 'not_sent',
            'raw_usage': None, 'usage_presence': 'absent', 'stop_reason': None, 'error_code': None}
        for name, data in (('user.md', user), ('request.json', raw), ('request.sha256', _sha(raw).encode()),
                           ('configuration.json', config_raw), ('started.json', _json(receipt))):
            _write(folder / name, data)
        client, answer, started = None, '', time.monotonic()
        try:
            client = (client_factory or httpx.AsyncClient)(timeout=TIMEOUT, follow_redirects=False,
                trust_env=False, transport=httpx.AsyncHTTPTransport(retries=0))
            _write(folder / 'dispatched.json', _json({'at': _now(), 'request_sha256': _sha(raw)}))
            receipt['dispatch_status'] = 'sent'
            with _suppress_transport_logging():
                response = await asyncio.wait_for(client.post(ENDPOINT, content=raw, headers={
                    'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}), TIMEOUT)
            receipt.update(http_status=response.status_code,
                request_id=_identifier(response.headers.get('request-id') or response.headers.get('x-request-id'), key))
            if response.status_code != 200:
                raise DialogueError('http_non_success')
            payload = response.json()
            if not isinstance(payload, dict):
                raise DialogueError('invalid_response')
            usage, presence = _numeric_usage(payload.get('usage'))
            receipt.update(raw_usage=usage, usage_presence=presence,
                response_id=_identifier(payload.get('id'), key),
                returned_model=_identifier(payload.get('model'), key),
                stop_reason=_identifier(payload.get('stop_reason'), key))
            rates = dict(price, cached_input_per_million=price['cache_read_per_million'])
            if presence == 'reported':
                receipt['estimated_usd'] = estimate_anthropic_usage(usage, rates)
            blocks = payload.get('content')
            if not isinstance(blocks, list):
                raise DialogueError('invalid_content')
            visible = ''.join(b['text'] for b in blocks if isinstance(b, dict)
                              and b.get('type') == 'text' and isinstance(b.get('text'), str))
            if key in visible:
                raise DialogueError('credential_in_response')
            answer = visible
            if receipt['stop_reason'] != 'end_turn' or not answer.strip():
                raise DialogueError('incomplete_or_empty_response')
            if receipt['estimated_usd'] is None:
                raise DialogueError('usage_or_price_unknown')
            if receipt['returned_model'] != config['model']:
                raise DialogueError('unexpected_returned_model')
            receipt['status'] = 'completed'
        except BaseException as error:
            receipt['error_code'] = (str(error) if isinstance(error, DialogueError)
                else 'timeout' if isinstance(error, (TimeoutError, httpx.TimeoutException))
                else 'cancelled' if isinstance(error, asyncio.CancelledError) else 'request_failed')
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    receipt['client_close_error'] = True
            if receipt['dispatch_status'] == 'not_sent':
                receipt['estimated_usd'] = '0'
            answer_raw = answer.encode()
            receipt.update(answer_sha256=_sha(answer_raw), ended_at=_now(), elapsed_seconds=time.monotonic() - started)
            _write(folder / 'answer.md', answer_raw)
            receipt_raw = _json(receipt)
            _write(folder / 'receipt.json', receipt_raw)
            _write(folder / 'receipt.sha256', _sha(receipt_raw).encode())
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    for name in ('session', 'system-file', 'model', 'budget-usd', 'price-file'):
        init.add_argument('--' + name, required=True)
    init.add_argument('--max-calls', type=int, required=True)
    init.add_argument('--max-tokens', type=int, required=True)
    send = commands.add_parser('turn')
    for name in ('session', 'message-file', 'credentials-root'):
        send.add_argument('--' + name, required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--session', required=True)
    inspect.add_argument('--history', action='store_true')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        if command == 'init':
            result = init_session(**args)
        elif command == 'turn':
            result = asyncio.run(turn(**args))
        else:
            args['include_history'] = args.pop('history')
            result = inspect_session(**args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') == 'failed' else 0
    except Exception as error:
        print(json.dumps({'error': str(error) if isinstance(error, DialogueError) else 'local_operation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
