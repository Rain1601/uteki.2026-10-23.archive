"""Read or continue the same local Claude window from Codex; no separate history."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import stat
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4


def connection(root):
    path=Path(root)/'window/connection.json'
    mode=path.lstat().st_mode
    if path.is_symlink() or not stat.S_ISREG(mode) or stat.S_IMODE(mode)!=0o600:
        raise ValueError('private_connection_file_required')
    value=json.loads(path.read_bytes())
    parsed=urlsplit(value['url'])
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port
        or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment
        or not isinstance(value.get('token'),str) or len(value['token'])<32):
        raise ValueError('invalid_local_connection')
    return value


def call(conn,path,payload=None):
    headers={'Authorization':'Bearer '+conn['token']}
    data=None
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode();headers['Content-Type']='application/json'
    req=urllib.request.Request(conn['url']+path,data=data,headers=headers)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:return {'request_failed':True,**json.load(exc)}
        except (ValueError,TypeError):return {'request_failed':True,'error':{'code':'http_error','message':str(exc.code)}}


def public_state(state,full=False):
    if full:return state
    return {**{k:state.get(k) for k in ('revision','model','configuration','budget','blocked','pending','last_submission')},
            'turns':[{k:t.get(k) for k in ('number','actor','status','model','estimated_usd','error_code','max_tokens','continued_after_failed_turn')} for t in state.get('turns',[])]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation-root',required=True,type=Path)
    sub=parser.add_subparsers(dest='command',required=True)
    history=sub.add_parser('history');history.add_argument('--full',action='store_true')
    send=sub.add_parser('send');send.add_argument('--message-file',required=True,type=Path)
    send.add_argument('--expected-revision');send.add_argument('--request-id');send.add_argument('--wait',action='store_true')
    send.add_argument('--max-tokens',type=int,help='Output limit for this request only; default stays 4096.')
    send.add_argument('--continue-after-failed-turn',type=int,
        help='Explicitly acknowledge this last failed turn after checking its terminal response and known cost.')
    args=parser.parse_args(argv)
    conn=connection(args.conversation_root)
    state=call(conn,'/api/conversation')
    if state.get('request_failed'):
        print(json.dumps(state,ensure_ascii=False));return 1
    if args.command=='history':
        print(json.dumps(public_state(state,args.full),ensure_ascii=False,indent=2));return 0
    if args.message_file.is_symlink() or not args.message_file.is_file():raise ValueError('regular_message_file_required')
    message=args.message_file.read_text(encoding='utf-8')
    if not message.strip() or len(message.encode())>120_000:raise ValueError('message_empty_or_too_large')
    rid=args.request_id or str(uuid4())
    print(json.dumps({'client_request_id':rid,'status':'submitting'},ensure_ascii=False),flush=True)
    try:
        options={k:getattr(args,k) for k in ('max_tokens','continue_after_failed_turn') if getattr(args,k) is not None}
        result=call(conn,'/api/codex/messages',{'message':message,'expected_revision':args.expected_revision or state['revision'],
            'client_request_id':rid,**options})
    except (OSError,ValueError,urllib.error.URLError):
        print(json.dumps({'client_request_id':rid,'status':'delivery_unknown',
            'detail':'Check this request ID before continuing. Do not submit a new ID blindly.'}));return 2
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if result.get('request_failed'):return 1
    if not args.wait:return 0
    deadline=time.monotonic()+270
    prior=result.get('submission')
    while True:
        state=call(conn,'/api/conversation')
        if state.get('request_failed'):
            print(json.dumps(state,ensure_ascii=False));return 1
        job=state.get('last_submission')
        if not job or job.get('client_request_id')!=rid:
            receipt=call(conn,'/api/submissions/'+rid)
            if receipt.get('request_failed'):
                print(json.dumps({'client_request_id':rid,**receipt},ensure_ascii=False));return 1
            job=receipt.get('submission') or prior
        if job and job.get('client_request_id')==rid and job.get('status')!='running':
            turn=next((t for t in state['turns'] if t.get('number')==job.get('turn_number')),None)
            print(json.dumps({'submission':job,'turn':turn,'budget':state['budget']},ensure_ascii=False,indent=2))
            return 0 if job.get('status')=='completed' else 1
        if time.monotonic()>=deadline:
            print(json.dumps({'client_request_id':rid,'status':'wait_timeout','detail':'The request may still be running. Reuse this request ID; do not submit a new one blindly.'}));return 2
        time.sleep(2)

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,urllib.error.URLError) as exc:
        # Never print connection contents, auth headers, or exception network URLs.
        code=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else type(exc).__name__
        print(json.dumps({'error':{'code':code}},ensure_ascii=False));raise SystemExit(1)
