"""Real SDK + bundled native CLI, with a synthetic loopback Messages peer."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[3]
FIXTURES=ROOT/'tests/fixtures/data_platform'
F=runpy.run_path(str(FIXTURES/'sdk_fixture.py'))


def outputs(messages):
    values=[]
    for message in messages:
        content=message.get('content',[])
        if not isinstance(content,list):continue
        for block in content:
            if block.get('type')!='tool_result':continue
            content=block.get('content','')
            pieces=[content] if isinstance(content,str) else [p.get('text','') for p in content if p.get('type')=='text']
            for text in pieces:
                try:values.append(json.loads(text))
                except ValueError:pass
    return values


def run_scenario(scenario, *, evidence_directory=None):
    if evidence_directory is None and os.environ.get('UTEKI_SDK_TEST_EVIDENCE_DIR'):
        evidence_directory=Path(os.environ['UTEKI_SDK_TEST_EVIDENCE_DIR'])
        evidence_directory.mkdir(parents=True,exist_ok=True)
    c=F['case']();c.catalog.close()
    script=F['Script'](scenario);requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_CONNECT(self):
            requests.append(dict(blocked_external=self.path));self.send_error(403)
        def do_GET(self):self.send_error(404)
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            if self.path.split('?')[0].rstrip('/').endswith('/messages'):
                requests.append(body)
                if len(requests)>15:self.send_error(400);return
                try:action=script.next(outputs(body.get('messages',[])))
                except Exception as error:
                    requests[-1]['fixture_error']=repr(error);self.send_error(400);return
                message=dict(id='msg_'+str(script.count),type='message',role='assistant',model=body['model'],content=[],stop_reason=None,stop_sequence=None,usage=dict(input_tokens=10,output_tokens=1))
                if action:
                    name,arguments=action
                    block=dict(type='tool_use',id='tool_'+str(script.count),name='mcp__data__'+name,input={})
                    delta=dict(type='input_json_delta',partial_json=json.dumps(arguments));reason='tool_use'
                else:
                    block=dict(type='text',text='');delta=dict(type='text_delta',text='Synthetic terminal text');reason='end_turn'
                events=[('message_start',dict(type='message_start',message=message)),
                    ('content_block_start',dict(type='content_block_start',index=0,content_block=block)),
                    ('content_block_delta',dict(type='content_block_delta',index=0,delta=delta)),
                    ('content_block_stop',dict(type='content_block_stop',index=0)),
                    ('message_delta',dict(type='message_delta',delta=dict(stop_reason=reason,stop_sequence=None),usage=dict(output_tokens=20))),
                    ('message_stop',dict(type='message_stop'))]
                payload=''.join('event: '+kind+'\ndata: '+json.dumps(value)+'\n\n' for kind,value in events).encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            else:
                self.send_error(404)
    try:
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix='uteki-sdk-cli-') as temp:
                work=Path(temp);base='http://127.0.0.1:'+str(server.server_port)
                env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                    CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=base,
                    ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-offline-fixture',
                    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',
                    HTTP_PROXY=base,HTTPS_PROXY=base,ALL_PROXY=base,NO_PROXY='127.0.0.1,localhost')
                result_path=work/'result.json'
                child=subprocess.run([sys.executable,'-I',str(FIXTURES/'sdk_native_worker.py'),str(c.root),c.context,str(ROOT/'config/data_platform'),str(result_path)],
                    env=env,cwd=work,text=True,capture_output=True,timeout=110)
                result=json.loads(result_path.read_text()) if result_path.exists() else None
                report=dict(scenario=scenario,exit_code=child.returncode,stdout=child.stdout,stderr=child.stderr,result=result,requests=requests,
                    real_model_calls=0,openrouter_requests=0,native_cli=True)
                if evidence_directory is not None:
                    (evidence_directory/(scenario+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                return report
        finally:
            server.shutdown();server.server_close();thread.join()
    finally:c.doCleanups()


class NativeClaudeTests(unittest.TestCase):
    def test_native_cli_six_tools_full_message_boundary_and_delivery(self):
        report=run_scenario('success')
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        result=report['result'];self.assertEqual(result['status'],'completed',result['error'])
        init=next(e['data']['data'] for e in result['native_events'] if e['type']=='SystemMessage' and e['data']['subtype']=='init')
        self.assertEqual(init['permissionMode'],'default')
        self.assertEqual(set(init['tools']),{'mcp__data__'+name for name in ['find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver']})
        self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
        self.assertEqual({e['tool'] for e in result['tool_events'] if e['type']=='tool_handler_return'},
            {'find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver'})
        actual=[v for r in report['requests'] for v in outputs(r.get('messages',[]))]
        observed=[e['output'] for e in result['tool_events'] if e['type']=='observed_tool_result']
        self.assertTrue(observed)
        self.assertTrue(all(value in actual for value in observed))
        self.assertTrue(all(r.get('model')=='fixture/claude-query-v1' for r in report['requests']))
        self.assertTrue(all(r.get('max_tokens')==4096 for r in report['requests']))

    def test_native_cli_illegal_deliver_cannot_become_success(self):
        for scenario in ['forged_delivery','invalid_arguments','tool_error','free_text']:
            with self.subTest(scenario=scenario):
                report=run_scenario(scenario)
                self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
                self.assertEqual(report['result']['status'],'failed',report['result']['error'])
                self.assertIsNone(report['result']['delivery'])
                self.assertTrue(report['requests'])
                self.assertFalse(any('fixture_error' in r or 'blocked_external' in r for r in report['requests']))
                terminal=next(e['data'] for e in reversed(report['result']['native_events']) if e['type']=='ResultMessage')
                self.assertFalse(terminal['is_error'],terminal)


if __name__=='__main__':unittest.main()
