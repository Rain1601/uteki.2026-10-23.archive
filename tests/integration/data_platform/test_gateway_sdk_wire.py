"""Actual SDK HTTP paths with synthetic responses and one shared cost ledger.

This does not run RuntimeJournal or prove model-selected business tool use.
"""
import argparse
import asyncio
import base64
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from uteki.data_platform.agent.binding import DESCRIPTIONS, ENVELOPES
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP, GatewayProxy
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, reconcile_response, response_bytes
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'config/data_platform'
CONTRACT=json.loads((CONFIG/'gateway-contract.draft.v1.json').read_text())
EVIDENCE=None


def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def profile(kernel):
    return load_profile(CONFIG/f'model-profiles/{kernel}/deepseek-v4.1-flash/query.json',
        config_root=CONFIG,kernel=kernel,model_id=CONTRACT['model']['gateway_id'],role='query')


def native_response(model):
    message=dict(id='msg_synthetic_wire',type='message',role='assistant',model=model,content=[],
        stop_reason=None,stop_sequence=None,usage=dict(input_tokens=10,output_tokens=1))
    events=[('message_start',dict(type='message_start',message=message)),
        ('content_block_start',dict(type='content_block_start',index=0,content_block=dict(type='text',text=''))),
        ('content_block_delta',dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text='Synthetic wire response.'))),
        ('content_block_stop',dict(type='content_block_stop',index=0)),
        ('message_delta',dict(type='message_delta',delta=dict(stop_reason='end_turn',stop_sequence=None),usage=dict(output_tokens=5))),
        ('message_stop',dict(type='message_stop'))]
    return ''.join('event: '+kind+'\ndata: '+json.dumps(value)+'\n\n' for kind,value in events).encode()


class NativeWireTests(unittest.TestCase):
    def test_both_actual_sdks_share_physical_request_and_billing_boundary(self):
        with tempfile.TemporaryDirectory(prefix='uteki-native-wire-') as temporary:
            work=Path(temporary);directory=EVIDENCE or work
            directory.mkdir(exist_ok=True)
            received=[];attempts=[];observations={};bodies={};proxies={}
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw)
                    generation=f'gen-synthetic-{len(received)+1}'
                    if self.path=='/v1/chat/completions':
                        payload=json.dumps(dict(id=generation,object='chat.completion',created=1,model=body['model'],provider='Synthetic',
                            choices=[dict(index=0,finish_reason='stop',message=dict(role='assistant',content='Synthetic wire response.'))],
                            usage=dict(prompt_tokens=10,completion_tokens=5,total_tokens=15,cost=.04))).encode()
                        media='application/json'
                    elif self.path in {'/v1/messages','/v1/messages?beta=true'}:
                        payload=native_response(body['model']);media='text/event-stream'
                    else:self.send_error(403);return
                    received.append(dict(path=self.path,request_base64=base64.b64encode(raw).decode(),
                        response_base64=base64.b64encode(payload).decode(),generation=generation))
                    self.send_response(200);self.send_header('Content-Type',media)
                    self.send_header('Content-Length',str(len(payload)));self.send_header('X-Generation-Id',generation)
                    self.end_headers();self.wfile.write(payload)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            peer=threading.Thread(target=server.serve_forever,daemon=True);peer.start()
            budget=RunBudget(work/'batch.sqlite','2')
            budget.bind_root('synthetic-sdk-batch',mode='remote',max_requests=2,max_in_flight_requests=1,
                scope_ids=['openai','claude'],policy={'synthetic':True})
            try:
                for kernel in ('openai','claude'):
                    loaded=profile(kernel)
                    budget.bind_scope(kernel,max_requests=1,policy=dict(profile=loaded.metadata(),
                        context_ref='synthetic-'+kernel,business_root_run_id='synthetic-business-'+kernel,
                        transport=dict(max_request_bytes=131072,max_response_bytes=2097152,request_timeout_seconds=45,reserve_usd='.8')))
                    wire=GatewayHTTP(budget,kernel,endpoint='http://127.0.0.1:'+str(server.server_port),
                        origin='synthetic',credential='uteki-synthetic-gateway',deadline=time.monotonic()+55,
                        before_request=lambda req:bodies.update({kernel:req}))
                    validate=wire.validate_request
                    def capture(path,raw,headers):
                        attempts.append(dict(kernel=kernel,path=path))
                        return validate(path,raw,headers)
                    wire.validate_request=capture
                    with GatewayProxy(wire) as proxy:
                        proxies[kernel]=proxy.events
                        if kernel=='openai':observations[kernel]=asyncio.run(self.openai(proxy,loaded))
                        else:observations[kernel]=self.claude(proxy,work,directory)
                    self.assertEqual(len(received),1 if kernel=='openai' else 2)
                    self.assertEqual(len(proxy.events),1)
                    key=proxy.events[0]['request_key'];saved=budget.inspect_request(key)
                    self.assertEqual(saved['control_scope_id'],kernel)
                    self.assertEqual(saved['request']['body_base64'],received[-1]['request_base64'])
                    self.assertEqual(base64.b64encode(response_bytes(saved['response_event']['response']['http'])).decode(),received[-1]['response_base64'])
                    if kernel=='claude':
                        self.assertEqual(saved['cost_state'],'unknown')
                        bill=capture_response('generation',200,[('Content-Type','application/json')],
                            [json.dumps(dict(data=dict(id=received[-1]['generation'],total_cost=.04))).encode()],max_bytes=1000)
                        reconcile_response(budget,key,bill,origin='synthetic')
                    self.assertEqual(budget.inspect_request(key)['settled_usd'],'0.04')
                    body=bodies[kernel]
                    self.assertEqual(body['model'],loaded.profile.model_id)
                    self.assertEqual(body['max_tokens'],loaded.profile.max_output_tokens)
                    if kernel=='openai':
                        self.assertEqual(body['messages'][0]['content'],loaded.text)
                        tool_schemas={t['function']['name']:t['function']['parameters'] for t in body['tools']}
                    else:
                        self.assertIn(loaded.text,[entry.get('text','') for entry in body['system']])
                        tool_schemas={t['name'].removeprefix('mcp__data__'):t['input_schema'] for t in body['tools']}
                    self.assertEqual(tool_schemas,{name:schema.model_json_schema() for name,schema in ENVELOPES.items()})
                self.assertNotEqual(profile('openai').text,profile('claude').text)
                summary=budget.summary()
                self.assertEqual(summary['requests'],2)
                self.assertEqual(Decimal(summary['held_usd']),Decimal(0))
                self.assertEqual(Decimal(summary['estimated_spent_usd']),Decimal('.08'))
                self.assertEqual(Decimal(budget.inspect_root()['cost']['known_billed_usd']),Decimal('.08'))
                observations['status']='passed_actual_sdk_wire_only'
            finally:
                server.shutdown();server.server_close();peer.join(timeout=5)
                save(directory/'wire-result.json',dict(observations=observations,requests=received,attempts=attempts,
                    proxies=proxies,summary=budget.summary(),real_model_calls=0,
                    not_verified=['RuntimeJournal binding','real model-selected tools','OpenRouter compatibility or billing']))
            self.assertFalse(peer.is_alive())

    async def openai(self,proxy,loaded):
        import httpx2 as httpx
        from openai import AsyncOpenAI
        from agents import FunctionTool,ModelSettings,set_tracing_disabled
        from agents.models.interface import ModelTracing
        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        set_tracing_disabled(True)
        async def prohibited(*args,**kwargs):raise AssertionError('Wire fixture cannot execute business tools')
        sdk_tools=[FunctionTool(name=name,description=DESCRIPTIONS[name],params_json_schema=schema.model_json_schema(),
            on_invoke_tool=prohibited,strict_json_schema=False) for name,schema in ENVELOPES.items()]
        async with httpx.AsyncClient(trust_env=False) as http:
            async with AsyncOpenAI(api_key=proxy.token,base_url=proxy.base_url+'/v1',http_client=http,max_retries=0) as client:
                response=await OpenAIChatCompletionsModel(loaded.profile.model_id,client).get_response(
                    system_instructions=loaded.text,input='Offline wire fixture. Return the synthetic peer response.',
                    model_settings=ModelSettings(**CONTRACT['openai']['model_settings']),tools=sdk_tools,
                    output_schema=None,handoffs=[],tracing=ModelTracing.DISABLED)
        self.assertEqual(response.output[0].content[0].text,'Synthetic wire response.')
        self.assertEqual(response.raw_usage['cost'],.04)
        return dict(response_id=response.response_id,raw_usage=response.raw_usage)

    def claude(self,proxy,work,directory):
        env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
            CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=proxy.base_url,
            ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN=proxy.token,
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',
            HTTP_PROXY=proxy.base_url,HTTPS_PROXY=proxy.base_url,ALL_PROXY=proxy.base_url,NO_PROXY='127.0.0.1,localhost')
        result=directory/'claude-native.json'
        with (directory/'claude.stdout').open('w') as stdout,(directory/'claude.stderr').open('w') as stderr:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_sdk_worker.py'),
                str(CONFIG),str(result)],cwd=work,env=env,stdout=stdout,stderr=stderr)
            observation=worker.wait(timeout=50)
        save(directory/'claude-process.json',dict(observation=observation,cleanup=worker.cleanup))
        self.assertEqual(worker.child.returncode,0,'Inspect retained Claude stderr')
        self.assertTrue(observation['process_group_empty'])
        native=json.loads(result.read_text())
        self.assertTrue(any(event['type']=='ResultMessage' and not event['data']['is_error'] for event in native['events']))
        return dict(process_group_empty=True,tool_handlers_executed=native['tool_handlers_executed'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence-dir',type=Path)
    args,remaining=parser.parse_known_args();EVIDENCE=args.evidence_dir
    unittest.main(argv=[sys.argv[0]]+remaining)
