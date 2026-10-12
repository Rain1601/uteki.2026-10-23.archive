import json,time
from pathlib import Path
from budget import TaskBudget,BASE
from scripts.claude_chat import connection,call
ROOT=Path('/Users/rain/.codex/visualizations/2026/10/06/01a110b1-5b89-71a2-9e33-25b63fd06f2b/private/claude-data-products')
rid='figure-materials-20261012-plan-v1'
receipt=BASE/'advisor-reservation.json'
budget=TaskBudget();conn=connection(ROOT);s=call(conn,'/api/conversation')
if s.get('request_failed'):raise RuntimeError('shared conversation unavailable')
if receipt.exists():token=json.loads(receipt.read_text())['token']
else:
    token=budget.reserve('1.20');receipt.write_text(json.dumps({'token':token,'request_id':rid,'reserved':'1.20'}))
    result=call(conn,'/api/codex/messages',{'message':(BASE/'advisor-request.txt').read_text(),'expected_revision':s['revision'],'client_request_id':rid,'max_tokens':4096})
    (BASE/'advisor-submit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('request_failed'):budget.settle(token,'0');raise RuntimeError('advisor submission rejected')
for _ in range(120):
    job=call(conn,'/api/submissions/'+rid).get('submission',{})
    if job.get('status') not in (None,'running'):
        s=call(conn,'/api/conversation');turn=next(t for t in s['turns'] if t['number']==job['turn_number'])
        (BASE/'advisor-result.json').write_text(json.dumps({'submission':job,'turn':turn},ensure_ascii=False,indent=2))
        budget.settle(token,turn.get('estimated_usd'));print(json.dumps({'status':job['status'],'estimated_usd':turn.get('estimated_usd'),'answer':turn.get('answer')},ensure_ascii=False));break
    time.sleep(2)
else:raise RuntimeError('advisor still pending; preserve reservation and request id')
