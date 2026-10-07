"""Real HTTP, shared disk service and Codex CLI; provider transport is mocked."""
from contextlib import redirect_stdout
from http.client import HTTPConnection
import io
import json
import threading
import time
import unittest
from unittest.mock import patch

from apps.claude_dialogue.app import ChatServer, save_private
from scripts import claude_chat
from tests.unit import test_claude_dialogue_service as service_fixtures


class SharedWindowIntegrationTests(unittest.TestCase):
    def test_cli_explicit_failure_recovery_uses_one_new_request_and_bound_options(self):
        fixture=service_fixtures.DialogueServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.payload['stop_reason']='max_tokens'
        fixture.payload['content']=[{'type':'thinking','thinking':'PRIVATE_THINKING'}]
        failed=fixture.send('Question with no visible response.')
        self.assertEqual(failed['turns'][-1]['answer'],'')
        fixture.payload['stop_reason']='end_turn'
        fixture.payload['content']=[{'type':'text','text':'Recovered visible answer.'}]
        server=ChatServer(('127.0.0.1',0),fixture.service,fixture.base/'window')
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        message=fixture.root/'continue.txt'
        message.write_text('Continue after the reviewed failed response.')
        args=['--conversation-root',str(fixture.base),'send','--message-file',str(message),
            '--request-id','recovered-cli-request-01','--continue-after-failed-turn','1','--max-tokens','8192','--wait']
        output=io.StringIO()
        with redirect_stdout(output):
            code=claude_chat.main(args)
        self.assertEqual(code,0,output.getvalue())
        self.assertEqual(len(fixture.requests),2)
        self.assertEqual(json.loads(fixture.requests[-1].content)['max_tokens'],8192)
        snapshot=server.snapshot()
        self.assertEqual([t['status'] for t in snapshot['turns']],['failed','completed'])
        self.assertEqual(snapshot['turns'][-1]['continued_after_failed_turn'],1)
        self.assertEqual(snapshot['turns'][-1]['max_tokens'],8192)
        self.assertEqual(snapshot['last_submission']['options'],{'continue_after_failed_turn':1,'max_tokens':8192})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(claude_chat.main(args),0)
        changed=args[:]
        changed[changed.index('8192')]='4096'
        conflict=io.StringIO()
        with redirect_stdout(conflict):
            self.assertEqual(claude_chat.main(changed),1)
        self.assertIn('idempotency_conflict',conflict.getvalue())
        self.assertEqual(len(fixture.requests),2)
        self.assertNotIn('PRIVATE_THINKING',output.getvalue())

    def test_browser_then_codex_share_context_and_restart_keeps_deduplication(self):
        fixture = service_fixtures.DialogueServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.legacy('Original preserved question.')
        original = {p: p.read_bytes() for p in (fixture.base/'session').rglob('*') if p.is_file()}
        server = ChatServer(('127.0.0.1', 0), fixture.service, fixture.base/'window')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual((fixture.base/'window').stat().st_mode & 0o777, 0o700)
        conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        conn.request('GET', '/api/session')
        response = conn.getresponse()
        cookie = response.getheader('Set-Cookie').split(';')[0]
        csrf = json.loads(response.read())['csrf_token']
        manual = {'message':'Manual question.\n原文完整。',
                  'expected_revision':fixture.service.history()['revision'],
                  'client_request_id':'integration-manual-01'}
        conn.request('POST', '/api/messages', body=json.dumps(manual), headers={
            'Content-Type':'application/json', 'Cookie':cookie,
            'X-CSRF-Token':csrf, 'Origin':server.origin})
        response = conn.getresponse()
        self.assertEqual(response.status, 202)
        response.read()
        conn.close()
        deadline = time.monotonic() + 3
        while server.pending and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(server.pending)
        self.assertEqual(server.snapshot()['last_submission']['status'], 'completed')

        message = fixture.root/'codex-message.txt'
        message.write_text('Codex follows the manual message.', encoding='utf-8')
        output = io.StringIO()
        original_call = claude_chat.call
        calls = []
        def intervening_submission(conn, path, payload=None):
            calls.append(path)
            result = original_call(conn, path, payload)
            if path == '/api/conversation':
                result['last_submission'] = {'client_request_id':'some-other-request', 'status':'completed'}
            return result
        with redirect_stdout(output), patch.object(claude_chat, 'call', side_effect=intervening_submission):
            code = claude_chat.main(['--conversation-root', str(fixture.base), 'send',
                '--message-file', str(message), '--request-id', 'integration-codex-01', '--wait'])
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn('/api/submissions/integration-codex-01', calls)
        state = server.snapshot()
        self.assertEqual([t['actor'] for t in state['turns']], ['codex','user','codex'])
        self.assertEqual(len(fixture.requests), 3)
        sent = json.loads(fixture.requests[-1].content)
        self.assertEqual([m['content'] for m in sent['messages']], [
            'Original preserved question.', 'Visible reply.\n第二行。',
            manual['message'], 'Visible reply.\n第二行。', message.read_text()])
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)
        for secret in (fixture.secret, 'PRIVATE_SYSTEM_INSTRUCTIONS', 'PRIVATE_THINKING'):
            self.assertNotIn(secret, json.dumps(state))
            self.assertNotIn(secret, output.getvalue())

        server.shutdown()
        server.server_close()
        thread.join(2)
        interrupted_job = {**json.loads((fixture.base/'window/submissions/integration-manual-01.json').read_bytes()),
                           'status':'running','client_request_id':'old-process-incomplete'}
        save_private(fixture.base/'window/submissions/old-process-incomplete.json', interrupted_job)
        restarted = ChatServer(('127.0.0.1', 0), fixture.service, fixture.base/'window')
        self.addCleanup(restarted.server_close)
        self.assertEqual(restarted.submission('old-process-incomplete')['status'], 'interrupted')
        self.assertEqual(restarted.submission('old-process-incomplete')['error_code'], 'submission_delivery_unknown')
        with self.assertRaisesRegex(Exception, 'window_already_running'):
            ChatServer(('127.0.0.1', 0), fixture.service, fixture.base/'window')
        result = restarted.submit(manual, 'user')
        self.assertTrue(result['replayed'])
        self.assertEqual(result['submission']['status'], 'completed')
        self.assertEqual(len(fixture.requests), 3)
        self.assertIsNone(restarted.pending)

    def test_lost_submit_response_preserves_request_id_without_retry(self):
        fixture = service_fixtures.DialogueServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        message = fixture.root/'question.txt'
        message.write_text('A question.', encoding='utf-8')
        output = io.StringIO()
        with patch.object(claude_chat, 'connection', return_value={}), patch.object(
            claude_chat, 'call', side_effect=[{'revision':'rev-1'}, TimeoutError('secret transport detail')]
        ) as call, redirect_stdout(output):
            code = claude_chat.main(['--conversation-root', str(fixture.base), 'send',
                '--message-file', str(message)])
        self.assertEqual(code, 2)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0]['status'], 'submitting')
        self.assertEqual(records[1]['status'], 'delivery_unknown')
        self.assertEqual(records[0]['client_request_id'], records[1]['client_request_id'])
        self.assertEqual(call.call_count, 2)
        self.assertNotIn('secret transport detail', output.getvalue())


if __name__ == '__main__':
    unittest.main()
