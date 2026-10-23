"""One user-authorized official OpenAI SDK request, charged to the existing batch.

This diagnostic does not resume the Agent or change its frozen route/profile.
The prior unknown charge stays unknown and fully reserved.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time

import httpx2
from openai import OpenAI, APIStatusError
from uteki.infrastructure.run_budget import RunBudget
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response


def save(path, value):
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--authorization', type=Path, required=True,
                        help='Explicit user instruction authorizing this single diagnostic')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    scope = 'C-luna-openai'
    if manifest['lanes'][scope]['model_id'] != 'openai/gpt-5.6-luna':
        raise ValueError('This diagnostic is restricted to the original Luna lane')
    instruction = args.authorization.read_text().strip()
    if not instruction: raise ValueError('Explicit diagnostic authorization required')
    key = None
    for line in args.env_file.read_text().splitlines():
        name, sep, candidate = line.strip().removeprefix('export ').partition('=')
        if sep and name.strip() == 'OPENROUTER_API_KEY': key = candidate.strip().strip('\"\'')
    if not key or any(c in key for c in '\r\n'): raise ValueError('Local OpenRouter credential unavailable')
    ledger = Path(manifest['data_root'])/'gateway-batches'/manifest['batch_id']/'budget.sqlite'
    budget = RunBudget.open_existing(ledger, manifest['contract']['limit_usd'], root_run_id=manifest['batch_id'])
    identity = 'diagnostic:'+hashlib.sha256(instruction.encode()).hexdigest()
    if any(r['request_key'] == identity for r in budget.inspect_requests()):
        raise ValueError('This instruction already has a diagnostic request; inspect it, never resend')
    args.output.mkdir(parents=True, exist_ok=False)
    payload = dict(model='openai/gpt-5.6-luna', messages=[{'role':'user','content':'Reply with OK.'}], max_tokens=64)
    request = dict(boundary='official_sdk_diagnostic', endpoint='https://openrouter.ai/api/v1/chat/completions',
        method='POST', body=payload, sdk_version=importlib.metadata.version('openai'),
        purpose='one minimal network-versus-routing diagnostic; not business acceptance')
    unknown = {r['request_key']:hashlib.sha256(RunBudget._json(r['response_event']).encode()).hexdigest()
               for r in budget.inspect_requests() if r['cost_state'] == 'unknown'}
    auth = dict(id=identity, authorized_by='user', user_message=instruction, max_requests=1,
        root_run_id=manifest['batch_id'], scope_id=scope, max_reserve_usd='.02',
        request_sha256=hashlib.sha256(RunBudget._json(request).encode()).hexdigest(), retained_unknown_requests=unknown)
    before = budget.inspect_root()
    save(args.output/'intent.json', dict(request=request, authorization=auth, ledger_before=before,
        reservation_usd='.02', pricing_bound='Luna endpoint snapshot: <= $0.8 input / $3.6 output per million; <=4096 request bytes plus 16384 framing allowance, 64 output tokens'))
    budget.prepare_request(identity, request, reserve_usd='.02', scope_id=scope, diagnostic_authorization=auth)
    sent = 0; started = time.monotonic(); captured = None; error = None

    def before_send(outgoing):
        nonlocal sent
        if (sent or outgoing.method != 'POST' or str(outgoing.url) != request['endpoint']
                or len(outgoing.content) > 4096 or json.loads(outgoing.content) != payload):
            raise ValueError('Additional or changed request refused before network')
        save(args.output/'request.json', dict(url=str(outgoing.url), body=json.loads(outgoing.content)))
        budget.begin_request(identity)
        sent += 1

    try:
        # Official client and its standard HTTP transport; the hook only meters
        # the physical request. No custom gateway body/route conversion.
        with httpx2.Client(event_hooks={'request':[before_send]}, trust_env=False,
                follow_redirects=False, timeout=30) as http:
            with OpenAI(base_url='https://openrouter.ai/api/v1', api_key=key,
                    max_retries=0, timeout=30, http_client=http) as client:
                try:
                    response = client.chat.completions.with_raw_response.create(**payload).http_response
                except APIStatusError as exc:
                    response = exc.response
                    error = type(exc).__name__
                captured = capture_response('chat_completions', response.status_code, response.headers.items(),
                    [response.content], max_bytes=100000)
                captured['body_representation'] = 'decoded_by_httpx2'
    except Exception as exc:
        error = type(exc).__name__
        if sent:
            captured = capture_response('chat_completions', 599, [], [], max_bytes=100000)
            captured.update(transport_complete=False, error=error)
        else:
            budget.abandon_prepared(identity, reason='diagnostic rejected before network: '+error)
    if captured is not None:
        save(args.output/'response.json', captured)
        record_response(budget, identity, captured, origin='openrouter')
    row = budget.inspect_request(identity)
    report = dict(request_key=identity, physical_requests=sent, elapsed_seconds=round(time.monotonic()-started,3),
        status=captured['status'] if captured else None, error=error,
        response_observation=row['response_event']['response']['observation'] if row['response_event'] else None,
        billed_usd=row['settled_usd'], old_unknown_reservations_retained=True,
        ledger_after=budget.inspect_root(), business_case_passed=False)
    save(args.output/'result.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if captured and captured['status'] == 200 else 1


if __name__ == '__main__': raise SystemExit(main())
