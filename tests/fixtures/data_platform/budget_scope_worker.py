"""Synthetic crash boundaries in the one scoped budget; never network I/O."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys

from uteki.infrastructure.run_budget import RunBudget

budget = RunBudget.open_existing(Path(sys.argv[1]), '1', root_run_id='synthetic-scope-process')
phase = sys.argv[2]
if phase == 'association':
    original = budget._transaction
    @contextmanager
    def transaction():
        with original() as db:
            db.create_function('synthetic_process_exit', 0, lambda: os._exit(79))
            yield db
    budget._transaction = transaction
budget.prepare_request('first', {'synthetic':'original input'}, reserve_usd='.4', scope_id='openai-case')
budget.begin_request('first')
if phase == 'dispatch': os._exit(79)
if phase == 'cancel':
    budget.stop_scope('openai-case', 'caller_cancelled')
    os._exit(79)
budget.record_response('first', {'synthetic':'complete original response'}, billed_usd='.2',
    receipt={'request_id':'synthetic-first','source':'synthetic-process-peer','evidence_sha256':'a'*64})
if phase == 'response': os._exit(79)
raise AssertionError('Unknown synthetic exit boundary')
