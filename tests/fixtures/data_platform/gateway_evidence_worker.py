"""Exit at synthetic response/billing persistence boundaries; no network."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys

from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response, reconcile_response
from uteki.infrastructure.run_budget import RunBudget

budget = RunBudget.open_existing(Path(sys.argv[1]), '2', root_run_id='synthetic-evidence-process')
phase = sys.argv[2]
raw = b'{"id":"gen-synthetic-a","model":"synthetic/model","provider":"Synthetic","object":"chat.completion","choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"synthetic"}}],"usage":{"cost":0.04}}'
headers = [('content-type','application/json'),('x-generation-id','gen-synthetic-a')]
budget.prepare_request('first',{'synthetic':'wire request'},reserve_usd='.8',scope_id='first-case')
budget.begin_request('first')
captured = capture_response('chat_completions',200,headers,[raw],max_bytes=32 if phase in {'partial','bill'} else 10000)
if phase == 'received': os._exit(79)
if phase == 'transaction':
    transaction = budget._transaction
    @contextmanager
    def interrupted():
        with transaction() as db:
            db.create_function('synthetic_exit',0,lambda:os._exit(79))
            yield db
    budget._transaction = interrupted
record_response(budget,'first',captured,origin='synthetic')
if phase == 'bill':
    receipt = capture_response('generation',200,[('content-type','application/json')],
        [b'{"data":{"id":"gen-synthetic-a","model":"synthetic/model","provider_name":"Synthetic","total_cost":0.04}}'],max_bytes=10000)
    reconcile_response(budget,'first',receipt,origin='synthetic')
os._exit(79)
