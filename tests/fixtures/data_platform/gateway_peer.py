"""Local synthetic peer only; scripted actions never enter production inputs."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import threading
import uuid

from uteki.data_platform.agent.profiles import LoadedProfile, Profile, load_profile
from uteki.data_platform.application.gateway_batch import create_gateway_batch
from uteki.data_platform.contracts.common import canonical, digest

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'config/data_platform'
CONTRACT=json.loads((CONFIG/'gateway-contract.draft.v1.json').read_text())
F=runpy.run_path(str(Path(__file__).with_name('sdk_fixture.py')))


def profile(kernel, *, skills=False):
    loaded=load_profile(CONFIG/f'model-profiles/{kernel}/deepseek-v4.1-flash/query.json',config_root=CONFIG,
        kernel=kernel,model_id=CONTRACT['model']['gateway_id'],role='query')
    if not skills:return loaded
    if kernel!='openai':raise ValueError('this synthetic wire fixture covers OpenAI Chat Skills only')
    selected=load_profile(CONFIG/'model-profiles/openai/fixture-skill-query/query.json',config_root=CONFIG,
        kernel='openai',model_id='fixture/openai-skill-query-v1',role='query')
    value=loaded.metadata() | dict(skills=list(selected.profile.skills),prompt=selected.profile.prompt.model_dump(mode='json'),
        request_controls=dict(reasoning={'enabled':False}),parallel_tool_calls=None)
    return LoadedProfile(Profile.model_validate_json(json.dumps(value)),selected.text,config_root=CONFIG)


def fixture(case_id='G01-normal', *, origin='synthetic', request_timeout_seconds=None, all_cases=False, profile_overrides=None, max_request_bytes=None):
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
    definitions=CONTRACT['execution']['cases_per_sdk'] if all_cases else [definition]
    for kernel,definition in ((kernel,definition) for kernel in ('openai','claude') for definition in definitions):
        case_id=definition['id'];request['question']=definition['input']
        context=case.service.create_context(request,request_key=kernel+'-'+case_id)['context_ref']
        limits=dict(native_max_turns=execution['native_max_turns_per_run'],max_model_requests=definition['max_requests'],
            max_request_bytes=execution['max_serialized_request_bytes'],max_response_bytes=execution['max_response_bytes'])
        if max_request_bytes is not None:limits['max_request_bytes']=max_request_bytes
        frozen_profile=profile(kernel).metadata() | (profile_overrides or {}).get(kernel,{})
        scopes.append(dict(scope_id=kernel+'-'+case_id,context_ref=context,profile=frozen_profile,limits=limits,
            transport=dict(max_request_bytes=limits['max_request_bytes'],max_response_bytes=limits['max_response_bytes'],
                request_timeout_seconds=(execution['request_timeout_seconds'] if request_timeout_seconds is None
                    else request_timeout_seconds),reserve_usd='.8')))
    args=dict(batch_id=str(uuid.uuid4()),scopes=scopes,limit_usd=request['run_policy']['max_usd'],
        max_requests=sum(s['limits']['max_model_requests'] for s in scopes),origin=origin,contract_sha256=digest(canonical(CONTRACT)))
    bindings=create_gateway_batch(case.catalog,**args)
    return case,args,bindings


class ChatPeer:
    def __init__(self, *, missing_usage=False, hold_response=False, stop_after_error=False, reasoning_details=None,
                 native_actions=()):
        self.script=F['Script']();self.requests=[];self.responses=[];self.errors=[]
        self.prefix=uuid.uuid4().hex;self.lookups=[];self.generations={}
        self.missing_usage=missing_usage
        self.hold_response=hold_response;self.stop_after_error=stop_after_error
        self.received=threading.Event();self.release=threading.Event()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                from urllib.parse import urlsplit,parse_qs
                parsed=urlsplit(self.path);query=parse_qs(parsed.query)
                if parsed.path!='/v1/generation' or set(query)!={'id'} or len(query['id'])!=1:
                    self.send_error(400);return
                identity=query['id'][0]
                if identity not in owner.generations:self.send_error(404);return
                payload=json.dumps(dict(data=dict(id=identity,model=owner.generations[identity],
                    provider_name='Synthetic',total_cost=.01))).encode()
                owner.lookups.append(dict(path=self.path,body=payload.decode()))
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def do_POST(self):
                try:
                    if self.path!='/v1/chat/completions':raise AssertionError('unexpected peer path')
                    raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw)
                    number=len(owner.requests)+1
                    native_names={name for name,_ in native_actions}
                    native_ids={call['id'] for message in body['messages'] for call in (message.get('tool_calls') or [])
                        if call['function']['name'] in native_names}
                    outputs=[]
                    for message in body['messages']:
                        if message['role']!='tool':continue
                        if message['tool_call_id'] in native_ids:continue
                        outputs.append(json.loads(message['content']))
                    action=(deepcopy(native_actions[number-1]) if number<=len(native_actions) else
                        None if owner.stop_after_error and owner.requests else owner.script.next(outputs))
                    generation='gen-synthetic-'+owner.prefix+'-'+str(number)
                    owner.generations[generation]=body['model']
                    if action:
                        name,args=action
                        message=dict(role='assistant',content=None,tool_calls=[dict(id='call-gateway-'+str(number),
                            type='function',function=dict(name=name,arguments=json.dumps(args)))])
                    else:message=dict(role='assistant',content='Synthetic terminal text')
                    if action and reasoning_details is not None:
                        message['reasoning_details']=deepcopy(reasoning_details)
                        message['reasoning']='Synthetic protocol fixture.'
                    payload=json.dumps(dict(id=generation,object='chat.completion',created=1,
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


class MessagesPeer:
    def __init__(self, *, missing_identity=False, missing_bill=False, stop_after_error=False):
        self.script=F['Script']();self.requests=[];self.responses=[];self.errors=[];self.lookups=[]
        self.missing_identity=missing_identity;self.missing_bill=missing_bill
        self.stop_after_error=stop_after_error;self.prefix=uuid.uuid4().hex
        self.generations={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,media,payload,headers=()):
                self.send_response(status);self.send_header('Content-Type',media)
                self.send_header('Content-Length',str(len(payload)))
                for key,value in headers:self.send_header(key,value)
                self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                from urllib.parse import urlsplit,parse_qs
                parsed=urlsplit(self.path);query=parse_qs(parsed.query)
                if parsed.path!='/v1/generation' or set(query)!={'id'} or len(query['id'])!=1:
                    self.send_error(400);return
                identity=query['id'][0]
                if identity not in owner.generations:self.send_error(404);return
                payload=json.dumps(dict(data=dict(id=identity,model=owner.generations[identity],
                    provider_name='Synthetic',**({} if owner.missing_bill else {'total_cost':.01})))).encode()
                owner.lookups.append(dict(path=self.path,body=payload.decode()))
                self.reply(200,'application/json',payload)
            def do_POST(self):
                try:
                    if self.path not in {'/v1/messages','/v1/messages?beta=true'}:
                        raise AssertionError('unexpected native Messages path')
                    raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw)
                    outputs=[]
                    for message in body['messages']:
                        blocks=message.get('content',[])
                        if not isinstance(blocks,list):continue
                        for block in blocks:
                            if block.get('type')=='tool_result':
                                content=block.get('content',[])
                                pieces=[content] if isinstance(content,str) else [p.get('text','') for p in content if p.get('type')=='text']
                                outputs.extend(json.loads(text) for text in pieces)
                    action=None if owner.stop_after_error and owner.requests else owner.script.next(outputs)
                    number=len(owner.requests)+1;identity=owner.prefix+'-'+str(number)
                    generation='gen-synthetic-'+identity
                    owner.generations[generation]=body['model']
                    message=dict(id='msg_'+identity,type='message',role='assistant',model=body['model'],
                        content=[],stop_reason=None,stop_sequence=None,usage=dict(input_tokens=10,output_tokens=1))
                    if action:
                        name,args=action
                        block=dict(type='tool_use',id='tool_'+identity,name='mcp__data__'+name,input={})
                        delta=dict(type='input_json_delta',partial_json=json.dumps(args));reason='tool_use'
                    else:
                        block=dict(type='text',text='');delta=dict(type='text_delta',text='Synthetic terminal text');reason='end_turn'
                    events=[dict(type='message_start',message=message),
                        dict(type='content_block_start',index=0,content_block=block),
                        dict(type='content_block_delta',index=0,delta=delta),dict(type='content_block_stop',index=0),
                        dict(type='message_delta',delta=dict(stop_reason=reason,stop_sequence=None),usage=dict(output_tokens=20)),
                        dict(type='message_stop')]
                    payload=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                    owner.requests.append(raw);owner.responses.append(payload)
                    self.reply(200,'text/event-stream',payload,[] if owner.missing_identity else [('X-Generation-Id',generation)])
                except Exception as error:
                    owner.errors.append(repr(error))
                    try:self.send_error(500)
                    except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_port)

    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join()
