"""Visible, metered retry of transient native transport failures only.

Each attempt is a separate provider request. Partial text is never joined across
attempts. The caller's one budget includes unknown-cost reservations in full.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path


def transient_failure(metadata):
    metadata = metadata or {}
    if metadata.get('stop_reason') == 'max_tokens':
        return False
    return (metadata.get('transport_error_type') in {
        'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout', 'TimeoutError',
        'ConnectError', 'ReadError', 'WriteError', 'RemoteProtocolError',
    } or metadata.get('http_status') in {408, 429, 500, 502, 503, 504}
        or metadata.get('stream_error_type') in {'incomplete_stream', 'incomplete_event'}
        or metadata.get('provider_error_type') in {'overloaded_error', 'api_error'})


async def metered_response(meter, *, folder, kwargs, max_attempts=2,
                           before_attempt=None, delay_seconds=2):
    """At most one retry by default; validation, cancellation and budget stop.

    `before_attempt` rechecks frozen input dependencies and cancellation. Uses the
    same validated kwargs on every attempt; each response/metadata stays separate.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError('retry_attempts_must_be_between_one_and_three')
    if not 0 <= delay_seconds <= 30:
        raise ValueError('retry_delay_must_be_bounded')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    for number in range(1, max_attempts + 1):
        if before_attempt:
            await before_attempt()
        attempt = folder / f'{number:03d}'
        attempt.mkdir()
        retry = False
        outcome = {'attempt': number, 'max_attempts': max_attempts, 'status': 'failed',
                   'will_retry': False}
        try:
            result = await meter.get_response(**kwargs)
            outcome['status'] = 'completed'
            return result
        except Exception as error:
            outcome['error_type'] = type(error).__name__
            retry = transient_failure(getattr(meter.inner, 'response_metadata', None))
            # Local ValueError/JSON/schema failures must not become network retries.
            retry = retry and not isinstance(error, ValueError) and number < max_attempts
            outcome['will_retry'] = retry
            if not retry:
                raise
        finally:
            native = meter.inner
            (attempt/'response_metadata.json').write_text(json.dumps(
                getattr(native, 'response_metadata', None), ensure_ascii=False, indent=2))
            text = getattr(native, 'response_text', None)
            if text is not None:
                (attempt/'response.txt').write_text(text)
            if meter.budget:
                outcome['budget'] = meter.budget.summary()
            (attempt/'outcome.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
            observation = getattr(meter, 'observation_context', None)
            if observation:
                for path in attempt.iterdir():
                    observation.publish(path)
        if retry:
            await asyncio.sleep(delay_seconds * number)
