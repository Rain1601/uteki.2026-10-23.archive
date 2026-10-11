"""Zero-API, synthetic stop-policy checks; the shared ledger is read-only."""
import json
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch

import runtime_helpers as helpers
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


def write(folder, relative, value):
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def check():
    matrix = helpers.read(helpers.EXP / 'execution-matrix.v1.json')
    config = helpers.read(helpers.ROOT / matrix['runs'][0]['config'])
    ledger_before = helpers.ledger(config)
    checks = []

    class FakeBudget:
        path = Path(config['planner']['budget_ledger'])

    delegated = []
    # The original method captured by task_guard is a synthetic no-write stub.
    with patch.object(RunBudget, 'reserve', lambda budget, amount: delegated.append(str(amount)) or 'no-write'):
        with helpers.task_guard(config):
            assert RunBudget.reserve(FakeBudget(), '2.99') == 'no-write'
            try:
                RunBudget.reserve(FakeBudget(), '3.01')
            except BudgetExceeded:
                pass
            else:
                raise AssertionError('Task guard failed before dispatch')
    assert delegated == ['2.99']
    checks.append('task_warning_checks_next_reservation_before_dispatch_and_preserves_original_delegate')

    baseline = helpers.read(helpers.OUTPUT / 'ledger-before.v1.json')
    near_boundary = dict(ledger_before, occupied_usd=str(Decimal(baseline['occupied_usd']) + Decimal('2.98')))
    with patch.object(RunBudget, 'reserve', lambda budget, amount: (_ for _ in ()).throw(AssertionError('Must not delegate'))):
        with helpers.task_guard(config), patch.object(helpers, 'ledger', return_value=near_boundary):
            try:
                RunBudget.reserve(FakeBudget(), '0.03')
            except BudgetExceeded:
                pass
            else:
                raise AssertionError('Prior task spend excluded from guard')
    checks.append('task_warning_includes_prior_task_occupied_cost')

    with tempfile.TemporaryDirectory(prefix='e6-v2-guard-checks-') as temporary:
        root = Path(temporary)
        budget = root / 'budget'
        write(budget, 'attempt-01/data-query/model/decision-0001-attempt-01.json',
              {'role': 'planner', 'status': 'failed_or_cancelled', 'error_type': 'BudgetExceeded',
               'started_at': '2026-10-10T00:00:00Z'})
        assert not list(budget.rglob('*-end.json'))
        assert helpers.terminal_reason({'status': 'blocked'}, budget, ledger_before) == 'task_or_shared_budget_boundary'
        checks.append('budget_failure_without_call_end_stops_matrix')

        recovered = root / 'recovered'
        write(recovered, 'attempt-01/data-query/model/decision-0001-attempt-01.json',
              {'role': 'planner', 'status': 'failed_or_cancelled', 'error_type': 'APIConnectionError',
               'retry_scheduled': True, 'started_at': '2026-10-10T00:00:00Z'})
        write(recovered, 'attempt-01/data-query/model/decision-0001-attempt-02.json',
              {'role': 'planner', 'status': 'decision_returned', 'started_at': '2026-10-10T00:00:01Z'})
        write(recovered, 'attempt-01/data-query/model/calls/failed-end.json',
              {'status': 'failed', 'error_type': 'APIConnectionError'})
        assert helpers.terminal_reason({'status': 'reviewed_data_ready'}, recovered, ledger_before) is None
        checks.append('prior_recovered_network_failure_does_not_stop_matrix')

        unrecovered = root / 'unrecovered'
        write(unrecovered, 'attempt-01/data-query/model/decision-0001-attempt-01.json',
              {'role': 'planner', 'status': 'failed_or_cancelled', 'error_type': 'APIConnectionError',
               'retry_scheduled': True, 'started_at': '2026-10-10T00:00:00Z'})
        write(unrecovered, 'attempt-01/data-query/model/decision-0001-attempt-02.json',
              {'role': 'planner', 'status': 'timed_out', 'error_type': 'APITimeoutError',
               'started_at': '2026-10-10T00:00:01Z'})
        assert helpers.terminal_reason({'status': 'blocked'}, unrecovered, ledger_before) == 'bounded_infrastructure_failure_unrecovered'
        checks.append('final_bounded_network_failure_stops_matrix')

        content = root / 'content'
        content.mkdir()
        assert helpers.terminal_reason({'status': 'blocked_by_review_failure'}, content, ledger_before) is None
        checks.append('content_failure_does_not_stop_fixed_sampling')

    ledger_after = helpers.ledger(config)
    assert ledger_before == ledger_after
    return {'zero_api': True, 'shared_ledger_read_only_unchanged': True, 'checks': checks,
            'boundary': 'Synthetic transport and guard classification only; no model-quality evidence.'}


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False))
