"""Local synthetic peer only; scripted actions never enter production inputs."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import threading
import uuid

from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.gateway_batch import create_gateway_batch
from uteki.data_platform.contracts.common import canonical, digest

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'config/data_platform'
CONTRACT=json.loads((CONFIG/'gateway-contract.draft.v1.json').read_text())
F=runpy.run_path(str(Path(__file__).with_name('sdk_fixture.py')))


def profile(kernel):
    return load_profile(CONFIG/f'model-profiles/{kernel}/deepseek-v4.1-flash/query.json',config_root=CONFIG,
        kernel=kernel,model_id=CONTRACT['model']['gateway_id'],role='query')


def fixture(case_id='G01-normal', *, origin='synthetic'):
    case=F['case']()
    definition=next(item for item in CONTRACT['execution']['cases_per_sdk'] if item['id']==case_id)
    request=deepcopy(case.request)
    request.update(question=definition['input'],periods=[
        dict(label='FY2024',fiscal_year=2024,fiscal_quarter=None,start='2023-07-02',end='2024-06-29',basis='source'),
        dict(label='FY2023',fiscal_year=2023,fiscal_quarter=None,start='2022-07-03',end='2023-07-01',basis='source')])
    execution=CONTRACT['execution']
    request['run_policy'].update(max_usd=CONTRACT['authorization']['proposed_root_limit_usd'],
        max_turns=execution['business_max_turns_per_run'],max_wall_seconds=execution['run_timeout_seconds'],
        max_no_progress_turns=execution['max_no_progress_turns'])
    scopes=[]
    for kernel in ('openai','claude'):
        context=case.service.create_context(request,request_key=kernel+'-'+case_id)['context_ref']
        limits=dict(native_max_turns=execution['native_max_turns_per_run'],max_model_requests=definition['max_requests'],
            max_request_bytes=execution['max_serialized_request_bytes'],max_response_bytes=execution['max_response_bytes'])
        scopes.append(dict(scope_id=kernel+'-'+case_id,context_ref=context,profile=profile(kernel).metadata(),limits=limits,
            transport=dict(max_request_bytes=limits['max_request_bytes'],max_response_bytes=limits['max_response_bytes'],
                request_timeout_seconds=execution['request_timeout_seconds'],reserve_usd='.8')))
    args=dict(batch_id=str(uuid.uuid4()),scopes=scopes,limit_usd=request['run_policy']['max_usd'],
        max_requests=sum(s['limits']['max_model_requests'] for s in scopes),origin=origin,contract_sha256=digest(canonical(CONTRACT)))
    bindings=create_gateway_batch(case.catalog,**args)
    return case,args,bindings


class ChatPeer:
    def __init__(self, *, missing_usage=False, hold_response=False, stop_after_error=False):
        self.script=F['Script']();self.requests=[];self.responses=[];self.errors=[]
        self.missing_usage=missing_usage
        self.hold_response=hold_response;self.stop_after_error=stop_after_error
        self.received=threading.Event();self.release=threading.Event()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                try:
                    if self.path!='/v1/chat/completions':raise AssertionError('unexpected peer path')
                    raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw)
                    outputs=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
                    action=None if owner.stop_after_error and owner.requests else owner.script.next(outputs)
                    number=len(owner.requests)+1
                    if action:
                        name,args=action
                        message=dict(role='assistant',content=None,tool_calls=[dict(id='call-gateway-'+str(number),
                            type='function',function=dict(name=name,arguments=json.dumps(args)))])
                    else:message=dict(role='assistant',content='Synthetic terminal text')
                    payload=json.dumps(dict(id='gen-synthetic-gateway-'+str(number),object='chat.completion',created=1,
                        model=body['model'],provider='Synthetic',choices=[dict(index=0,
                            finish_reason='tool_calls' if action else 'stop',message=message)],
                        usage=dict(prompt_tokens=10,completion_tokens=10,total_tokens=20,**({} if owner.missing_usage else {'cost':.01})))).encode()
                    owner.requests.append(raw);owner.responses.append(payload)
                    owner.received.set()
                    if owner.hold_response and not owner.release.wait(timeout=15):
                        raise TimeoutError('test did not release the held response')
                    self.send_response(200);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                except Exception as error:
                    owner.errors.append(repr(error))
                    try:self.send_error(500)
                    except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_port)

    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join()
