"""Abrupt-exit fixture. No network and no SDK import; never a production runner."""
import os
from pathlib import Path
import sys

from uteki.infrastructure.run_budget import RunBudget


if __name__ == '__main__':
    path, stop = Path(sys.argv[1]), sys.argv[2]
    budget = RunBudget(path, '1')
    budget.bind_root('synthetic-process-root', mode='remote', max_requests=3,
                     policy={'scenario':'synthetic process death; no model calls'})
    if stop == 'preparing':
        reserve = budget._reserve
        def exit_in_prepare(db, amount):
            reserve(db, amount)
            os._exit(73)
        budget._reserve = exit_in_prepare
    budget.prepare_request('physical-request', {'model':'fixture','request_hash':'synthetic'}, reserve_usd='.4')
    if stop == 'prepared': os._exit(73)
    budget.begin_request('physical-request')
    if stop == 'dispatched': os._exit(73)
    if stop == 'responding':
        inspect = budget._request
        def exit_before_response_commit(db, key):
            result = inspect(db, key)
            if result['stage'] == 'responded': os._exit(73)
            return result
        budget._request = exit_before_response_commit
    budget.record_response('physical-request', {'output':'original synthetic response'}, billed_usd='.2',
        receipt={'request_id':'synthetic-receipt','source':'fixture','evidence_sha256':'b'*64})
    if stop == 'responded': os._exit(73)
    raise ValueError('unknown test checkpoint')
