"""One frozen Opus 5.5 consultation; --prepare and --self-test are offline."""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import tempfile
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
HELPERS = BASE.parent / '2026-10-07-data-agent-consultation-v1/consult.py'
HELPERS_SHA256 = '56dcd0151a6a93016aa24bf04e37a0543923166584e72088f824ae00f5b37d10'
if HELPERS.is_symlink() or hashlib.sha256(HELPERS.read_bytes()).hexdigest() != HELPERS_SHA256:
    raise ValueError('Frozen consultation helpers changed')
_spec = importlib.util.spec_from_file_location('frozen_consultation_helpers', HELPERS)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

MODEL = 'claude-opus-5-5'
LIMIT = '0.8'
DOCUMENTS = ('context-request.md', 'system.txt', 'codex-baseline.md', 'price.json')


def prices(path):
    value = h.read_json(path)
    expected = {'model', 'input_per_million', 'output_per_million',
                'cache_read_per_million', 'source_url', 'checked_date'}
    if not isinstance(value, dict) or set(value) != expected or value['model'] != MODEL:
        raise ValueError('Explicit Opus 5.5 price evidence required')
    for field, amount in [('input_per_million', '4'), ('output_per_million', '20'),
                          ('cache_read_per_million', '0.2')]:
        if Decimal(str(value[field])) != Decimal(amount):
            raise ValueError('Price differs from this authorized consultation')
    if not isinstance(value['source_url'], str) or not value['source_url'].startswith('https://'):
        raise ValueError('HTTPS price source required')
    if not isinstance(value['checked_date'], str) or not h.re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['checked_date']):
        raise ValueError('Price verification date required')
    return value


def prepare(base=BASE, sources=()):
    base = Path(base)
    with h.locked(base):
        if (base / 'runs').exists() or (base / 'budget.sqlite').exists():
            raise ValueError('Preparation is frozen after a dispatch attempt')
        price = prices(base / 'price.json')
        context = (base / 'context-request.md').read_text(encoding='utf-8')
        system = (base / 'system.txt').read_text(encoding='utf-8')
        if not context.strip() or not system.strip():
            raise ValueError('Complete context and system are required')
        body = h.request_for(MODEL, context, system)
        raw = h.canonical(body)
        reserve = h.reservation_amount(raw, price)
        if reserve > Decimal(LIMIT):
            raise h.BudgetExceeded('Conservative reservation exceeds USD 0.8')
        paths = [base / name for name in DOCUMENTS] + [Path(__file__), HELPERS]
        paths += [ROOT / 'src/uteki/agents/runtime' / name for name in
                  ('model_configuration.py', 'run_budget.py', 'local_credentials.py')]
        paths += [ROOT / name for name in ('src/uteki/__init__.py', 'src/uteki/agents/__init__.py',
                                         'src/uteki/agents/runtime/__init__.py')]
        paths += [Path(path).absolute() for path in sources]
        source_hashes = {str(path.absolute()): h.file_hash(path) for path in paths}
        prepared = base / 'prepared'
        prepared.mkdir(exist_ok=True)
        for name in DOCUMENTS:
            (prepared / name).write_bytes((base / name).read_bytes())
        (prepared / 'request.json').write_bytes(raw)
        configuration = h.configuration(body)
        h.write_json(prepared / 'configuration.json', configuration)
        inspection = {'model': MODEL, 'provider': 'aihubmix', 'endpoint': h.ENDPOINT,
            'request_sha256': h.digest(raw), 'request_bytes': len(raw),
            'configuration_sha256': configuration['sha256'], 'reservation_usd': str(reserve),
            'budget_limit_usd': LIMIT, 'max_tokens': h.MAX_TOKENS, 'thinking': 'adaptive',
            'effort': 'high', 'timeout_seconds': h.TIMEOUT, 'stream': False, 'max_retries': 0,
            'calls': 1, 'tools_sampling_seed_cache_controls': 'not_sent',
            'reservation_rule': 'Input tokens <= request UTF-8 bytes + 16000; output <= 16000.',
            'cost_note': 'Public-price estimate, not an account bill or provider-enforced hard cap.'}
        h.write_json(base / 'inspection.json', inspection)
        manifest = {'schema_version': 'data-contract-pageindex-consultation-v1',
            'prepared_at': h.utc_now(), 'source_sha256': source_hashes,
            'prepared_sha256': {name: h.file_hash(prepared / name) for name in
                               (*DOCUMENTS, 'request.json', 'configuration.json')},
            'inspection_sha256': h.file_hash(base / 'inspection.json'),
            'runtime': h.runtime_evidence()}
        h.write_json(base / 'manifest.json', manifest)
        (base / 'manifest.sha256').write_text(h.file_hash(base / 'manifest.json') + '\n')
        return dict(inspection, status='prepared', model_calls=0)


def verify(base):
    if h.file_hash(base / 'manifest.json') != (base / 'manifest.sha256').read_text().strip():
        raise ValueError('Manifest changed')
    manifest = h.read_json(base / 'manifest.json')
    for name, expected in manifest['source_sha256'].items():
        if h.file_hash(name) != expected:
            raise ValueError('Pinned source changed')
    for name, expected in manifest['prepared_sha256'].items():
        if Path(name).name != name or h.file_hash(base / 'prepared' / name) != expected:
            raise ValueError('Frozen file changed')
    if h.file_hash(base / 'inspection.json') != manifest['inspection_sha256'] or h.runtime_evidence() != manifest['runtime']:
        raise ValueError('Inspection or runtime changed')
    prepared = base / 'prepared'
    price = prices(prepared / 'price.json')
    body = h.request_for(MODEL, (prepared / 'context-request.md').read_text(encoding='utf-8'),
                         (prepared / 'system.txt').read_text(encoding='utf-8'))
    raw = (prepared / 'request.json').read_bytes()
    if raw != h.canonical(body):
        raise ValueError('Request bytes differ from frozen inputs and controls')
    snapshot = h.validate_configuration_snapshot(h.read_json(prepared / 'configuration.json'))
    if snapshot != h.configuration(body) or h.reservation_amount(raw, price) > Decimal(LIMIT):
        raise ValueError('Configuration or reservation changed')
    return raw, price, snapshot


async def run(base=BASE, *, client_factory=h.httpx.AsyncClient, key_loader=h.load_provider_key):
    base = Path(base)
    with h.locked(base):
        raw, price, snapshot = verify(base)  # Verify once, before dispatch; send these exact bytes.
        output = base / 'runs/opus55'
        output.mkdir(parents=True, exist_ok=False)
        budget = h.RunBudget(base / 'budget.sqlite', LIMIT)
        key, token, sent, settled = '', None, False, False
        started = time.monotonic()
        record = {'schema_version': 'data-contract-pageindex-receipt-v1', 'status': 'started',
            'provider': 'aihubmix', 'requested_model': MODEL, 'started_at': h.utc_now(),
            'manifest_sha256': h.file_hash(base / 'manifest.json'), 'request_sha256': h.digest(raw),
            'configuration_sha256': snapshot['sha256'], 'runner_sha256': h.file_hash(__file__),
            'http_status': None, 'response_id': None, 'returned_model': None, 'request_id': None,
            'stop_reason': None, 'raw_usage': None, 'estimated_usd': None, 'actual_billed_usd': None,
            'model_identity_note': 'Provider claim only; actual model weights are not independently verified.',
            'omissions': 'All non-text content, hidden thinking, signatures and response bodies are omitted.'}
        try:
            amount = h.reservation_amount(raw, price)
            token = budget.reserve(amount)
            record.update(reservation_id=token, reserved_usd=str(amount))
            h.write_json(output / 'start.json', record, exclusive=True)
            key_loader(ROOT, 'aihubmix')
            key = os.environ[h.PROVIDER_KEYS['aihubmix']]
            if not key:
                raise ValueError('Credential unavailable')
            headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            previous_logging = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                async with client_factory(timeout=h.TIMEOUT, follow_redirects=False,
                        transport=h.httpx.AsyncHTTPTransport(retries=0), trust_env=False) as client:
                    sent = True
                    response = await asyncio.wait_for(client.post(h.ENDPOINT, content=raw, headers=headers), h.TIMEOUT)
            finally:
                logging.disable(previous_logging)
            record.update(http_status=response.status_code,
                          request_id=h.identifier(response.headers.get('request-id') or response.headers.get('x-request-id')))
            if response.status_code != 200:
                record.update(status='failed', error_classification='non_200_response')
            else:
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get('content'), list):
                    raise ValueError('Invalid provider response')
                record.update(response_id=h.identifier(payload.get('id')), returned_model=h.identifier(payload.get('model')),
                    stop_reason=h.identifier(payload.get('stop_reason')), raw_usage=h.numeric_usage(payload.get('usage')))
                visible = ''.join(block['text'] for block in payload['content'] if isinstance(block, dict)
                                  and block.get('type') == 'text' and isinstance(block.get('text'), str))
                record['visible_text_secret_redacted'] = key in visible
                with (output / 'answer.md').open('x', encoding='utf-8') as stream:
                    stream.write(visible.replace(key, '[REDACTED]'))
                cost, status = h.usage_cost(payload.get('usage'), price)
                record.update(estimated_usd=cost, usage_status=status)
                budget.settle(token, cost)
                settled = True
                record['status'] = 'completed' if cost is not None and record['stop_reason'] == 'end_turn' and visible.strip() else 'incomplete'
        except BaseException as error:
            record.update(status='failed', error_type=type(error).__name__,
                error_classification='timeout' if isinstance(error, (TimeoutError, h.httpx.TimeoutException)) else 'transport_or_validation_failure')
        finally:
            if token is not None and not settled:
                budget.settle(token, None if sent else '0')
                record['usage_status'] = 'unknown_after_dispatch' if sent else 'not_dispatched'
            record.update(ended_at=h.utc_now(), elapsed_seconds=time.monotonic() - started, dispatched=sent)
            h.write_json(output / 'receipt.json', record, exclusive=True, key=key)
            h.write_json(output / 'budget-summary.json', budget.summary(), exclusive=True)
        return {'status': record['status'], 'http_status': record['http_status'],
                'estimated_usd': record['estimated_usd'], 'budget': budget.summary()}


async def self_test():
    """Synthetic transport acceptance only; no API or real credentials."""
    calls, secret = [], 'offline-secret-example'
    old_key = os.environ.get(h.PROVIDER_KEYS['aihubmix'])
    def key_loader(*_):
        os.environ[h.PROVIDER_KEYS['aihubmix']] = secret
    def factory(handler):
        def create(**kwargs):
            kwargs['transport'] = h.httpx.MockTransport(handler)
            return h.httpx.AsyncClient(**kwargs)
        return create
    def scaffold(base):
        base.mkdir()
        for name in DOCUMENTS[:-1]:
            (base / name).write_text('Explicit synthetic offline test\n', encoding='utf-8')
        h.write_json(base / 'price.json', {'model': MODEL, 'input_per_million': 4,
            'output_per_million': 20, 'cache_read_per_million': 0.2,
            'source_url': 'https://example.invalid/offline', 'checked_date': '2026-10-07'})
        prepare(base)
    def response(request):
        calls.append(request)
        return h.httpx.Response(200, json={'id': 'msg_test', 'model': MODEL, 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 10},
            'content': [{'type': 'thinking', 'thinking': 'MUST_NOT_PERSIST', 'signature': 'MUST_NOT_PERSIST'},
                        {'type': 'text', 'text': 'Visible answer ' + secret}]})
    try:
        with tempfile.TemporaryDirectory(prefix='uteki-pageindex-offline-') as folder:
            base = Path(folder) / 'success'
            scaffold(base)
            result = await run(base, client_factory=factory(response), key_loader=key_loader)
            assert result['status'] == 'completed' and result['estimated_usd'] == '0.000802'
            assert calls[0].content == (base / 'prepared/request.json').read_bytes()
            saved = ''.join(p.read_text() for p in (base / 'runs/opus55').glob('*'))
            assert 'MUST_NOT_PERSIST' not in saved and secret not in saved
            assert (base / 'runs/opus55/answer.md').read_text() == 'Visible answer [REDACTED]'
            for action in (lambda: run(base, client_factory=factory(response), key_loader=key_loader),):
                try:
                    await action()
                except FileExistsError:
                    pass
                else:
                    raise AssertionError('Repeat dispatch accepted')
            try:
                prepare(base)
            except ValueError:
                pass
            else:
                raise AssertionError('Reprepare accepted')
            timeout_base = Path(folder) / 'timeout'
            scaffold(timeout_base)
            def timeout(request):
                raise h.httpx.ReadTimeout(secret, request=request)
            failed = await run(timeout_base, client_factory=factory(timeout), key_loader=key_loader)
            assert failed['budget']['unknown_requests'] == 1
            changed = Path(folder) / 'changed'
            scaffold(changed)
            (changed / 'prepared/request.json').write_bytes(b'{}')
            try:
                await run(changed, client_factory=factory(response), key_loader=key_loader)
            except ValueError:
                pass
            else:
                raise AssertionError('Changed request accepted')
            assert len(calls) == 1 and not (changed / 'runs').exists()
        return {'status': 'offline_self_test_passed', 'model_calls': 0,
                'checks': ['exact_request_bytes', 'known_cost', 'hidden_content_omission', 'secret_redaction',
                           'repeat_block', 'reprepare_block', 'timeout_cost_hold', 'tamper_before_dispatch']}
    finally:
        if old_key is None:
            os.environ.pop(h.PROVIDER_KEYS['aihubmix'], None)
        else:
            os.environ[h.PROVIDER_KEYS['aihubmix']] = old_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--self-test', action='store_true')
    parser.add_argument('--source', action='append', default=[], type=Path)
    args = parser.parse_args()
    try:
        if args.source and not args.prepare:
            raise ValueError('Source selection is preparation-only')
        result = prepare(sources=args.source) if args.prepare else asyncio.run(self_test() if args.self_test else run())
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['status'] in {'prepared', 'completed', 'offline_self_test_passed'} else 1
    except Exception as error:
        print(json.dumps({'status': 'stopped', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
