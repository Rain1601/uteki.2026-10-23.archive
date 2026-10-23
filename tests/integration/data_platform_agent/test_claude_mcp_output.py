"""The real Claude CLI must forward large MCP outputs without losing evidence."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from uteki.data_platform.agent.profiles import load_profile, LoadedProfile, Profile
from uteki.data_platform.contracts.common import canonical

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'config/data_platform'


class ClaudeMCPOutputTests(unittest.TestCase):
    def test_threshold_is_explicit_bounded_and_absent_from_historical_profiles(self):
        path=CONFIG/'model-profiles/claude/live-B-deepseek-claude/query.json'
        loaded=load_profile(path,config_root=CONFIG,kernel='claude',model_id='deepseek-flash',role='query')
        self.assertEqual(loaded.metadata()['mcp_max_result_chars'],200000)
        legacy=loaded.metadata();legacy.pop('mcp_max_result_chars')
        self.assertEqual(LoadedProfile(Profile.model_validate_json(json.dumps(legacy)),loaded.text).metadata(),legacy)
        for value in (0,-1,500001,True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                Profile.model_validate_json(json.dumps(loaded.metadata() | {'mcp_max_result_chars':value}))
        openai=json.loads((CONFIG/'model-profiles/openai/live-A-deepseek-openai/query.json').read_text())
        with self.assertRaisesRegex(ValueError,'requires the Claude SDK'):
            Profile.model_validate_json(json.dumps(openai | {'mcp_max_result_chars':200000}))

    def test_native_default_persists_large_result(self):
        self.run_cases([(None,69000,False)])

    def test_native_annotation_preserves_large_result(self):
        self.run_cases([(200000,69000,True)])

    def test_native_annotation_keeps_upper_bound(self):
        self.run_cases([(200000,210000,False)])

    def run_cases(self,cases):
        reports=[]
        for threshold,chars,expected_inline in cases:
            with self.subTest(threshold=threshold,chars=chars):
                requests=[];request_bytes=[];token_requests=[];paths=[];errors=[]
                tool_output=dict(status='ok',items=[dict(snippet='synthetic-'+('x'*chars),marker='END-OF-SYNTHETIC-RESULT')])
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_CONNECT(self):self.send_error(403)
                    def do_GET(self):self.send_error(403)
                    def do_POST(self):
                        try:
                            raw_request=self.rfile.read(int(self.headers['Content-Length']))
                            body=json.loads(raw_request);paths.append(self.path)
                            # The CLI may count a large result before persisting it.
                            # This endpoint is not a model-generation turn.
                            if self.path.split('?')[0]=='/v1/messages/count_tokens':
                                token_requests.append(dict(model=body.get('model'),bytes=len(raw_request)))
                                raw=json.dumps(dict(input_tokens=10000)).encode()
                                self.send_response(200);self.send_header('Content-Type','application/json')
                                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                                return
                            if self.path.split('?')[0]!='/v1/messages':
                                raise AssertionError('Unexpected endpoint: '+self.path)
                            request_bytes.append(len(raw_request))
                            requests.append(body);number=len(requests)
                            if number>2:raise AssertionError('Unexpected additional request')
                            first=number==1
                            # Model-facing progress delta; next_action is host-owned and not advertised.
                            args=dict(request=dict(filters={}),state=dict(satisfied=[],gaps=[],
                                reason='Synthetic transfer fixture'))
                            block=(dict(type='tool_use',id='synthetic-call',name='mcp__data__find_assets',input={})
                                   if first else dict(type='text',text=''))
                            delta=(dict(type='input_json_delta',partial_json=json.dumps(args))
                                   if first else dict(type='text_delta',text='Synthetic transfer complete.'))
                            events=[dict(type='message_start',message=dict(id='msg_'+str(number),type='message',
                                role='assistant',model='deepseek-flash',content=[],stop_reason=None,
                                stop_sequence=None,usage=dict(input_tokens=10,output_tokens=1))),
                                dict(type='content_block_start',index=0,content_block=block),
                                dict(type='content_block_delta',index=0,delta=delta),
                                dict(type='content_block_stop',index=0),
                                dict(type='message_delta',delta=dict(stop_reason='tool_use' if first else 'end_turn',
                                    stop_sequence=None),usage=dict(output_tokens=10)),dict(type='message_stop')]
                            raw=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                            self.send_response(200);self.send_header('Content-Type','text/event-stream')
                            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                        except Exception as error:
                            errors.append(repr(error));self.send_error(400)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with tempfile.TemporaryDirectory(prefix='uteki-mcp-output-') as temporary:
                        work=Path(temporary);endpoint='http://127.0.0.1:'+str(server.server_port)
                        spec=dict(config=str(CONFIG),threshold=threshold,tool_output=tool_output,output=str(work/'result.json'))
                        path=work/'spec.json';path.write_text(json.dumps(spec))
                        env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',LANG='C.UTF-8',PYTHONNOUSERSITE='1',
                            CLAUDE_CONFIG_DIR=str(work/'claude-config'),ANTHROPIC_BASE_URL=endpoint,ANTHROPIC_API_KEY='',
                            ANTHROPIC_AUTH_TOKEN='synthetic',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                            CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096',HTTP_PROXY=endpoint,HTTPS_PROXY=endpoint,
                            ALL_PROXY=endpoint,NO_PROXY='127.0.0.1,localhost')
                        process=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/claude_mcp_output_worker.py'),
                            str(path)],cwd=work,env=env,capture_output=True,text=True,timeout=50)
                        result_path=work/'result.json'
                        result=json.loads(result_path.read_text()) if result_path.exists() else None
                        diagnostic=dict(threshold_chars=threshold,source_chars=len(canonical(tool_output).decode()),
                            synthetic_post_count=len(requests),request_bytes=request_bytes,server_errors=errors,
                            request_paths=paths,synthetic_token_count_requests=token_requests,
                            worker_returncode=process.returncode,worker_stderr=process.stderr,
                            worker=result,passed=False,real_model_calls=0)
                        evidence=None
                        if os.environ.get('UTEKI_MCP_OUTPUT_EVIDENCE'):
                            directory=Path(os.environ['UTEKI_MCP_OUTPUT_EVIDENCE']);directory.mkdir(parents=True,exist_ok=True)
                            evidence=directory/f'{threshold}-{chars}.json'
                            with evidence.open('x') as file:json.dump(diagnostic,file,indent=2);file.write('\n')
                        self.assertEqual(process.returncode,0,diagnostic)
                        self.assertIsNotNone(result,diagnostic)
                        self.assertEqual(len(result['calls']),1,result)
                        self.assertEqual(len(requests),2,errors)
                        self.assertEqual(errors,[])
                        self.assertLessEqual(max(request_bytes),200000)
                        self.assertTrue(result['result_events'])
                        self.assertFalse(result['result_events'][-1]['is_error'],result)
                        outputs=[b for m in requests[1]['messages'] if isinstance(m['content'],list)
                                 for b in m['content'] if b.get('type')=='tool_result']
                        self.assertEqual(len(outputs),1)
                        content=outputs[0]['content']
                        text=content if isinstance(content,str) else ''.join(b.get('text','') for b in content)
                        if expected_inline:self.assertEqual(json.loads(text),tool_output)
                        else:self.assertTrue(text.startswith('<persisted-output>'),text[:200])
                        reports.append(dict(threshold_chars=threshold,source_chars=len(canonical(tool_output).decode()),
                            forwarded_chars=len(text),inline_exact=expected_inline,synthetic_post_count=2,
                            first_request_bytes=request_bytes[0],second_request_bytes=request_bytes[1],
                            native_tool_calls=1,real_model_calls=0))
                        if evidence:
                            evidence.write_text(json.dumps(diagnostic | reports[-1] | {'passed':True},indent=2)+'\n')
                finally:
                    server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
