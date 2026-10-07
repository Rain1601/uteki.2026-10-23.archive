"""Loopback-only companion server. No private directory is ever served as files."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
from datetime import datetime, timezone
import hashlib
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from scripts.claude_dialogue import DialogueError
from .service import DialogueService

ASSETS = Path(__file__).resolve().parent
MAX_POST_BYTES = 160_000
ERRORS = {
    'session_locked': '会话正在被使用，请等待当前请求完成。',
    'revision_conflict': '对话已更新，请刷新后再发送；输入已保留。',
    'history_revision_conflict': '对话已更新，请刷新后再发送；输入已保留。',
    'request_or_cumulative_budget_exceeded': '剩余额度不足以预留完整上下文和回答费用。请查看额度设置。',
    'session_budget_exhausted': '会话额度不足，请查看额度设置。',
    'previous_turn_failed_or_interrupted': '上一轮未完整完成。请先核对该轮结果与费用；系统不会自动重试。',
    'failed_turn_not_recoverable': '所选失败轮次尚不能续发。只允许显式选择最后一轮、已经结束且用量费用已知的响应。',
    'invalid_max_tokens': '输出上限必须是 1 至 16000 的整数。',
    'advisor_prompt_unavailable': '顾问协作规则文件缺失或内容无效。历史仍可查看；请修复规则文件后发送。',
    'unauthorized': '本地会话连接已失效，请刷新页面。',
    'origin_rejected': '请求来源与此本地窗口不一致。',
    'request_in_progress': '已有一条消息正在处理，请等待完成。',
    'idempotency_conflict': '这条提交的编号已被另一段内容使用，请重新发送。',
    'invalid_request': '消息或配置格式不正确。',
    'message_empty_or_too_large': '请输入消息，并将消息控制在 120 KB 以内。',
    'submission_delivery_unknown': '服务在保存最终状态前退出，请核对历史和费用。原提交不会自动重发。',
    'unknown_error': '请求未完成。记录已保留，请核对状态后继续。',
}


def now(): return datetime.now(timezone.utc).isoformat()
def encode(value): return json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
def digest(value): return hashlib.sha256(encode(value)).hexdigest()
def error(code):
    code = code if isinstance(code,str) and re.fullmatch(r'[a-z0-9_]{1,100}',code) else 'unknown_error'
    message=ERRORS.get(code)
    if not message and 'budget' in code:message=ERRORS['session_budget_exhausted']
    if not message and 'revision' in code:message=ERRORS['revision_conflict']
    return {'code':code,'message':message or '无法完成请求，具体原因：'+code+'。输入和已有记录已保留。'}

def save_private(path,value,*,exclusive=False):
    flags=os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC)
    flags|=getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,'wb') as stream:
        os.fchmod(stream.fileno(),0o600);stream.write(encode(value));stream.flush();os.fsync(stream.fileno())


def project_history(raw):
    """Only the explicit safe service projection reaches a browser."""
    summary=raw.get('summary',{})
    config=raw.get('configuration',{})
    prompt=config.get('advisor_prompt',{})
    prompt_hash=lambda value:value if isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) else None
    prompt_view={'status':prompt.get('status') if prompt.get('status') in {'ready','unavailable'} else 'not_recorded',
        'snapshot_sha256':prompt_hash(prompt.get('snapshot_sha256')),
        'effective_system_sha256':prompt_hash(prompt.get('effective_system_sha256')),
        'component_sha256':{name:prompt_hash(prompt.get('component_sha256',{}).get(name))
            for name in ('advisor','collaboration_focus')}}
    budget=raw.get('budget',{})
    limit=budget.get('limit_usd',summary.get('budget_usd'))
    return {'revision':raw['revision'], 'model':raw.get('model',summary.get('model','claude-opus-5-5')),
        'configuration':{'provider':'aihubmix','thinking':{'type':'adaptive'},'effort':'high',
            'max_tokens':config.get('max_tokens',4096),'stream':False,'advisor_prompt':prompt_view},
        'budget':{'limit_usd':limit,'spent_usd':budget.get('spent_usd',summary.get('estimated_spent_usd')),
            'held_usd':budget.get('held_usd',summary.get('held_usd','0')),
            'remaining_usd':budget.get('remaining_usd',summary.get('remaining_usd')),
            'minimum_next_turn_reserved_usd':summary.get('minimum_next_turn_reserved_usd'),
            'send_blocked_reason':summary.get('send_blocked_reason'),
            'estimated':True},
        'blocked':raw.get('blocked',summary.get('blocked',False)),
        'turns':[{k:turn.get(k) for k in ('number','actor','actor_recorded','status','user','answer','started_at','ended_at','model','estimated_usd','error_code','stop_reason','request_id','max_tokens','continued_after_failed_turn','system_prompt_snapshot_sha256')}
                  for turn in raw.get('turns',[])],
        'price':{k:v for k,v in raw.get('price',{}).items() if k in ('input_per_million','output_per_million','cache_read_per_million','source_url','checked_date')}}


class ChatServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

    def __init__(self,address,service,window):
        if address[0]!='127.0.0.1':raise ValueError('loopback_only')
        self.service=service;self.window=Path(window)
        self.window.mkdir(mode=0o700,exist_ok=True)
        if self.window.is_symlink() or self.window.stat().st_mode&0o777!=0o700:
            raise ValueError('private_window_required')
        self.guard=threading.RLock();self.sessions={};self.pending=None;self.last_submission=None
        self.cli_token=secrets.token_urlsafe(32)
        self.cached=project_history(service.history())
        self.submissions=self.window/'submissions'
        self.submissions.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.submissions.is_symlink() or self.submissions.stat().st_mode&0o777!=0o700:
            raise ValueError('private_submissions_required')
        self.instance_fd=os.open(self.window/'.server.lock',os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            fcntl.flock(self.instance_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            os.close(self.instance_fd);self.instance_fd=None
            raise DialogueError('window_already_running') from None
        try:
            super().__init__(address,Handler)
            self.origin=f'http://127.0.0.1:{self.server_port}'
            # An old process cannot still own this window. A stale submission
            # has unknown delivery, not proof of provider failure or zero cost.
            for path in sorted(self.submissions.glob('*.json')):
                job=json.loads(path.read_bytes())
                if job.get('status')=='running':
                    job={**job,'status':'interrupted','error_code':'submission_delivery_unknown','ended_at':now()}
                    save_private(path,job);self.last_submission=job
            save_private(self.window/'connection.json',{'schema_version':'local-claude-window-v1','url':self.origin,
                'token':self.cli_token,'pid':os.getpid(),'started_at':now()})
        except BaseException:
            self.server_close();raise

    def server_close(self):
        if getattr(self,'socket',None) is not None:super().server_close()
        if self.instance_fd is not None:
            fcntl.flock(self.instance_fd,fcntl.LOCK_UN);os.close(self.instance_fd);self.instance_fd=None

    def snapshot(self):
        with self.guard:
            try:self.cached=project_history(self.service.history())
            except DialogueError as exc:
                if str(exc)!='session_locked':raise
            return {**self.cached,'pending':dict(self.pending) if self.pending else None,
                    'last_submission':dict(self.last_submission) if self.last_submission else None}

    def submission(self,rid):
        if not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,100}',rid):
            raise DialogueError('invalid_request')
        with self.guard:
            path=self.submissions/(rid+'.json')
            if not path.is_file():raise DialogueError('submission_not_found')
            return json.loads(path.read_bytes())

    def submit(self,payload,actor):
        required={'message','expected_revision','client_request_id'}
        if not required<=set(payload) or set(payload)-required-{'max_tokens','continue_after_failed_turn'}:
            raise DialogueError('invalid_request')
        options={k:payload[k] for k in ('max_tokens','continue_after_failed_turn') if k in payload}
        message,revision,rid=(payload[k] for k in ('message','expected_revision','client_request_id'))
        if not isinstance(message,str) or not message.strip() or len(message.encode())>120_000:
            raise DialogueError('message_empty_or_too_large')
        if not isinstance(revision,str) or not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,100}',rid):
            raise DialogueError('invalid_request')
        path=self.submissions/(rid+'.json')
        fingerprint=digest({'message':message,'actor':actor,**({'options':options} if options else {})})
        with self.guard:
            if path.exists():
                prior=json.loads(path.read_bytes())
                if prior['message_sha256']!=fingerprint:raise DialogueError('idempotency_conflict')
                # Reusing an ID never launches another paid request, even after restart.
                return {'accepted':True,'replayed':True,'client_request_id':rid,'submission':prior}
            if self.pending:raise DialogueError('request_in_progress')
            check=self.service.preflight(message,revision,**options)
            if not check['allowed']:raise DialogueError(check.get('reason') or 'session_budget_exhausted')
            job={'client_request_id':rid,'actor':actor,'message_sha256':fingerprint,'expected_revision':revision,
                 'started_at':now(),'status':'running','reserve_usd':check.get('reserve_usd'),
                 **({'options':options} if options else {})}
            save_private(path,job,exclusive=True)
            self.pending={k:job[k] for k in ('client_request_id','actor','started_at','status')}
            self.pending['message']=message
            self.last_submission=dict(job)
            worker=threading.Thread(target=self.execute,args=(job,path,message,revision,actor,options),daemon=True)
            worker.start()
            return {'accepted':True,'client_request_id':rid,'replayed':False}

    def execute(self,job,path,message,revision,actor,options):
        projected=None
        result={**job,'status':'failed','error_code':'unknown_error','ended_at':now()}
        try:
            value=asyncio.run(self.service.send(message,revision,actor=actor,**options))
            projected=project_history(value)
            last=projected['turns'][-1] if projected['turns'] else {}
            result={**job,'status':last.get('status','failed'),'turn_number':last.get('number'),
                    'error_code':last.get('error_code'),'ended_at':now()}
        except BaseException as exc:
            code=str(exc) if isinstance(exc,DialogueError) else 'unknown_error'
            result={**job,'status':'failed','error_code':error(code)['code'],'ended_at':now()}
            projected=None
        finally:
            with self.guard:
                try:save_private(path,result)
                except OSError:
                    result={**result,'status':'failed','error_code':'submission_receipt_write_failed'}
                finally:
                    if projected is not None:self.cached=projected
                    self.last_submission=result;self.pending=None


class Handler(BaseHTTPRequestHandler):
    server_version='UtekiLocalChat'
    def log_message(self,*args):pass

    def valid_origin(self):
        if self.headers.get('Host')!=urlsplit(self.server.origin).netloc:return False
        origin=self.headers.get('Origin')
        if origin and origin!=self.server.origin:return False
        return self.headers.get('Sec-Fetch-Site') not in ('cross-site','same-site')

    def respond(self,status,data,content_type='application/json; charset=utf-8',cookie=None):
        raw=data if isinstance(data,bytes) else encode(data)
        self.send_response(status)
        self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass

    def browser_session(self):
        try:
            parsed=cookies.SimpleCookie();parsed.load(self.headers.get('Cookie',''))
            item=parsed.get('uteki_claude')
            return self.server.sessions.get(item.value) if item else None
        except cookies.CookieError:return None

    def cli_authorized(self):
        auth=self.headers.get('Authorization','')
        return secrets.compare_digest(auth,'Bearer '+self.server.cli_token)

    def require_browser(self,write=False):
        token=self.browser_session()
        return bool(token and (not write or secrets.compare_digest(self.headers.get('X-CSRF-Token',''),token)))

    def do_GET(self):
        if not self.valid_origin():return self.respond(403,{'error':error('origin_rejected')})
        path=urlsplit(self.path).path
        if path in ('/','/chat.js','/chat.css'):
            file=ASSETS/({'/':'index.html','/chat.js':'chat.js','/chat.css':'chat.css'}[path])
            content_type={'/':'text/html; charset=utf-8','/chat.js':'text/javascript; charset=utf-8','/chat.css':'text/css; charset=utf-8'}[path]
            return self.respond(200,file.read_bytes(),content_type)
        if path=='/api/session':
            with self.server.guard:
                csrf=self.browser_session()
                sid=None
                if not csrf:
                    sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
                    if len(self.server.sessions)>100:self.server.sessions.clear()
                    self.server.sessions[sid]=csrf
            cookie=f'uteki_claude={sid}; HttpOnly; SameSite=Strict; Path=/' if sid else None
            return self.respond(200,{'csrf_token':csrf},cookie=cookie)
        if not (self.require_browser() or self.cli_authorized()):return self.respond(401,{'error':error('unauthorized')})
        if path=='/api/conversation':
            try:return self.respond(200,self.server.snapshot())
            except DialogueError as exc:return self.respond(409,{'error':error(str(exc))})
        if path.startswith('/api/submissions/'):
            try:return self.respond(200,{'submission':self.server.submission(path.removeprefix('/api/submissions/'))})
            except DialogueError as exc:return self.respond(404 if str(exc)=='submission_not_found' else 400,{'error':error(str(exc))})
        return self.respond(404,{'error':error('not_found')})

    def do_POST(self):
        if not self.valid_origin():return self.respond(403,{'error':error('origin_rejected')})
        path=urlsplit(self.path).path
        codex=path=='/api/codex/messages'
        if not (self.cli_authorized() if codex else self.require_browser(write=True)):
            return self.respond(401,{'error':error('unauthorized')})
        if path not in ('/api/messages','/api/codex/messages','/api/budget'):
            return self.respond(404,{'error':error('not_found')})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_POST_BYTES or self.headers.get('Transfer-Encoding'):
                raise DialogueError('invalid_request')
            if self.headers.get_content_type()!='application/json':raise DialogueError('invalid_request')
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict):raise DialogueError('invalid_request')
            if path=='/api/budget':
                if set(payload)!={'limit_usd','expected_revision'}:raise DialogueError('invalid_request')
                with self.server.guard:
                    if self.server.pending:raise DialogueError('request_in_progress')
                    value=self.server.service.set_budget(payload['limit_usd'],payload['expected_revision'],actor='user')
                    self.server.cached=project_history(value)
                return self.respond(200,self.server.snapshot())
            return self.respond(202,self.server.submit(payload,'codex' if codex else 'user'))
        except DialogueError as exc:
            return self.respond(409,{'error':error(str(exc))})
        except (ValueError,TypeError,KeyError,json.JSONDecodeError):
            return self.respond(400,{'error':error('invalid_request')})
        except Exception:
            return self.respond(500,{'error':error('unknown_error')})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation-root',type=Path,required=True)
    parser.add_argument('--credentials-root',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args(argv)
    service=DialogueService(args.conversation_root,credentials_root=args.credentials_root)
    server=ChatServer(('127.0.0.1',args.port),service,args.conversation_root/'window')
    print(f'Claude conversation: {server.origin}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
