"""Classify terminal infrastructure failures without looking at answers."""
def terminal_stop_reason(result, error_records, ledger):
    if ledger['unsettled']:
        return 'unresolved_ledger'
    if ledger['requests'] >= ledger['request_cap'] or ledger['committed_usd'] >= ledger['usd_limit']:
        return 'hard_budget_or_request_guard'
    types={r.get('error_type') for r in error_records}
    statuses={r.get('http_status') for r in error_records}
    if 'BudgetExceeded' in types:
        return 'hard_budget_or_request_guard'
    if types & {'AuthenticationError','PermissionDeniedError'} or statuses & {401,403}:
        return 'authentication_or_permission_failure'
    if result.get('status')=='cancelled':
        return 'cancelled'
    # Transport status is supplied only for the final bounded call group outcome.
    if any(r.get('terminal_transport_failure') for r in error_records):
        return 'bounded_infrastructure_failure_unrecovered'
    return None


def transport_failure(record):
    meta=record.get('response_metadata') or record
    return (record.get('error_type') in {'APIConnectionError','APITimeoutError','RateLimitError','InternalServerError','ConnectError','ReadTimeout','TimeoutError','ConnectionError','ClaudeTransientTransportError'}
        or meta.get('transport_error_type') is not None or meta.get('stream_error_type') is not None
        or meta.get('http_status') in {408,429,500,502,503,504,529}
        or meta.get('provider_error_type') in {'overloaded_error','api_error','rate_limit_error','timeout_error'})
