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
    # A transient call which recovered within existing bounds must not stop later slots.
    if result.get('status') != 'reviewed_data_ready' and (types & {
        'APIConnectionError','APITimeoutError','RateLimitError','InternalServerError','ConnectError',
        'ReadTimeout','TimeoutError','ConnectionError'} or any(isinstance(s,int) and (s==429 or s>=500) for s in statuses)
        or any(r.get('transport_error_type') or r.get('stream_error_type') or r.get('provider_error_type') in {'overloaded_error','api_error','rate_limit_error','timeout_error'} for r in error_records)):
        return 'bounded_infrastructure_failure_unrecovered'
    return None
