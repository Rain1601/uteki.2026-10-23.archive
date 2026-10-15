"""Real SDK + bundled native CLI, with a synthetic loopback Messages peer."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import subprocess
import signal
import sys
import tempfile
import threading
import time
import unittest
import base64
import hashlib

from uteki.data_platform.application.session import Session
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.content import ObjectRef
from uteki.infrastructure.run_budget import RunBudget
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
FIXTURES=ROOT/'tests/fixtures/data_platform'
F=runpy.run_path(str(FIXTURES/'sdk_fixture.py'))


def group_members(pgid):
    """Read actual membership; killpg(..., 0) is not a portable exit probe."""
    rows=subprocess.check_output(['/bin/ps','-axo','pid=,pgid=,stat='],text=True)
    return [dict(pid=int(pid),state=state) for pid,group,state in
            (line.split() for line in rows.splitlines()) if int(group)==pgid]


def close_group(child):
    """Only signal the new session owned by this fixture host."""
    before=group_members(child.pid)
    for sig in (signal.SIGTERM,signal.SIGKILL):
        if not group_members(child.pid):break
        try:os.killpg(child.pid,sig)
        except ProcessLookupError:pass
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            child.poll()  # reap our worker before observing membership
            if not group_members(child.pid):
                return dict(pgid=child.pid,before=before,after=[],last_signal=sig.name)
            time.sleep(.05)
    remaining=group_members(child.pid)
    if remaining:
        raise AssertionError(f'owned native process group {child.pid} remains: {remaining}')
    return dict(pgid=child.pid,before=before,after=[])


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


def compaction_request(body):
    """Recognize the pinned CLI's observed synthetic summarization request."""
    return any('Your task is to create a detailed summary of the conversation so far' in block.get('text','')
        for message in body.get('messages',[]) if isinstance(message.get('content'),list)
        for block in message['content'] if block.get('type')=='text')


def run_scenario(scenario, *, evidence_directory=None, options=None):
    if evidence_directory is None and os.environ.get('UTEKI_SDK_TEST_EVIDENCE_DIR'):
        evidence_directory=Path(os.environ['UTEKI_SDK_TEST_EVIDENCE_DIR'])
        evidence_directory.mkdir(parents=True,exist_ok=True)
    c=F['acquisition_case']() if scenario=='acquisition' else F['case']();c.catalog.close()
    script=F['Script']('clarify' if scenario=='clarify_continue' else scenario);requests=[]
    if scenario=='acquisition':
        script=F['AcquisitionScript'](json.loads((c.root/'fixture-acquisition.json').read_text()))
        options=dict(options or {},acquisition=True)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_CONNECT(self):
            requests.append(dict(blocked_external=self.path));self.send_error(403)
        def do_GET(self):self.send_error(404)
        def do_POST(self):
            nonlocal script
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            if self.path.split('?')[0].rstrip('/').endswith('/messages'):
                if scenario=='clarify_continue' and len(requests)==1:
                    script=F['Script']('after_clarification')
                requests.append(body)
                if len(requests)>15:self.send_error(400);return
                compact=bool((options or {}).get('compact_response') and compaction_request(body))
                try:action=None if compact else script.next(outputs(body.get('messages',[])))
                except Exception as error:
                    requests[-1]['fixture_error']=repr(error);self.send_error(400);return
                message=dict(id=('msg_compact_'+str(len(requests)) if compact else 'msg_'+str(script.count)),type='message',role='assistant',model=body['model'],content=[],stop_reason=None,stop_sequence=None,
                    usage=dict(input_tokens=(options or {}).get('first_input_tokens',10) if len(requests)==1 else 10,output_tokens=1))
                if action:
                    name,arguments=action
                    block=dict(type='tool_use',id='tool_'+str(script.count),name='mcp__data__'+name,input={})
                    delta=dict(type='input_json_delta',partial_json=json.dumps(arguments));reason='tool_use'
                else:
                    text=('<summary>The user requested a synthetic Data task. find_assets completed. '
                        'No final delivery has been accepted. Continue under the same host budget.</summary>'
                        if compact else 'Synthetic terminal text')
                    block=dict(type='text',text='');delta=dict(type='text_delta',text=text);reason='end_turn'
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
                command=[sys.executable,'-I',str(FIXTURES/'sdk_native_worker.py'),str(c.root),c.context,str(ROOT/'config/data_platform'),str(result_path),json.dumps(options or {})]
                stdout_path,stderr_path=work/'stdout.log',work/'stderr.log'
                # A native child can retain inherited pipes after its Python
                # parent dies. Files plus an owned process group let the host
                # observe the worker's actual exit and clean its descendants.
                with stdout_path.open('w') as stdout,stderr_path.open('w') as stderr:
                    observed=None
                    if options and options.get('observe_exit'):
                        watcher=ObservedWorker(command,env=env,cwd=work,stdout=stdout,stderr=stderr)
                        if options.get('supervisor_at_phase'):
                            marker=c.root/'fixture-host-blocked';deadline=time.monotonic()+15
                            while not marker.exists() and watcher.child.poll() is None and time.monotonic()<deadline:
                                time.sleep(.02)
                            observed=watcher.wait(timeout=.05)
                            if not marker.exists():raise AssertionError('worker did not reach the supervised fixture boundary')
                        else:
                            observed=watcher.wait(timeout=110)
                        child,cleanup=watcher.child,watcher.cleanup
                        with Catalog.open(c.root) as catalog:watcher.record(catalog,c.context)
                    else:
                        child=subprocess.Popen(command,env=env,cwd=work,stdout=stdout,stderr=stderr,start_new_session=True)
                        try:
                            child.wait(timeout=110)
                        finally:
                            cleanup=close_group(child)
                child=subprocess.CompletedProcess(command,child.returncode,stdout_path.read_text(),stderr_path.read_text())
                recovery=None
                before_recovery=None
                host_resolution=None
                if options and options.get('host_resolution'):
                    if not options.get('observe_exit'):raise AssertionError('host resolution needs an observed original exit')
                    with Catalog.open(c.root) as catalog:before_recovery=Session(catalog,c.context).data
                    host_resolution=F['resolve_acquisition_worker'](c.root,c.context,options['host_resolution'])
                if options and options.get('recover_after_exit'):
                    with Catalog.open(c.root) as catalog:
                        before_recovery=Session(catalog,c.context).data
                        if options.get('stop_root_before_recovery'):
                            ledger=RunBudget.open_existing(c.root/before_recovery['native_execution']['ledger_path'],'0',
                                root_run_id=before_recovery['context']['root_run_id'])
                            ledger.stop_root(options['stop_root_before_recovery'])
                    history_fault=options.get('history_fault')
                    if history_fault:
                        sid=before_recovery['native_execution']['native_session_id']
                        transcripts=list((work/'claude-config').rglob(sid+'.jsonl'))
                        if len(transcripts)!=1:raise AssertionError('fixture requires one native transcript')
                        path=transcripts[0]
                        rows=[json.loads(line) for line in path.read_text().splitlines()]
                        if history_fault=='missing':path.unlink()
                        elif history_fault in {'tool_output','assistant'}:
                            changed=False
                            for row in rows:
                                content=row.get('message',{}).get('content',[])
                                if not isinstance(content,list):continue
                                for block in content:
                                    if history_fault=='tool_output' and block.get('type')=='tool_result':
                                        block['content']=[dict(type='text',text='{"status":"ok","items":[]}')];changed=True
                                    elif history_fault=='assistant' and block.get('type')=='tool_use':
                                        block['input']={};changed=True
                            if not changed:raise AssertionError('no fixture transcript block to corrupt')
                            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                        else:raise AssertionError('unknown synthetic history fault')
                    recovery_options={k:v for k,v in options.items() if k not in {'stop_phase','recover_after_exit','supervisor_at_phase','stop_root_before_recovery'}} | {'recover':True}
                    recovery_command=command[:-1]+[json.dumps(recovery_options)]
                    with (work/'recovery.stdout').open('w') as stdout,(work/'recovery.stderr').open('w') as stderr:
                        recovered=subprocess.Popen(recovery_command,env=env,cwd=work,stdout=stdout,stderr=stderr,start_new_session=True)
                        try:recovered.wait(timeout=30)
                        finally:recovery_cleanup=close_group(recovered)
                    recovery=dict(exit_code=recovered.returncode,stdout=(work/'recovery.stdout').read_text(),
                        stderr=(work/'recovery.stderr').read_text(),process_cleanup=recovery_cleanup)
                closed=None
                if options and options.get('host_close_run'):
                    with Catalog.open(c.root) as catalog:
                        prior=Session(catalog,c.context).data
                        service=DataService(catalog)
                        closed=service.close_run(c.context,request_key='fixture-close',reason='native history unavailable')
                        if service.read_run_result(c.context)!=closed:raise AssertionError('closed result replay differs')
                        if Session(catalog,c.context).data['native_execution']['tool_calls']!=prior['native_execution']['tool_calls']:
                            raise AssertionError('closure rewrote native tool history')
                result=json.loads(result_path.read_text()) if result_path.exists() else None
                with Catalog.open(c.root) as reopened:
                    session=Session(reopened,(result or {}).get('fixture_child_context_ref',c.context))
                    journal=session.data.get('native_execution')
                    ledger=RunBudget(c.root/journal['ledger_path'],'0',allow_zero_limit=True)
                    ledger_summary=ledger.inspect_root()
                    ledger_requests=ledger.inspect_requests()
                    operations=session.data['operations']
                    audit_objects={}
                    for event in journal.get('events',[]):
                        if event.get('type')=='claude_resume_request_rejected':
                            audit_objects[event['request_ref']['sha256']]=json.loads(reopened.content.read_object(ObjectRef.model_validate(event['request_ref'])))
                report=dict(scenario=scenario,exit_code=child.returncode,stdout=child.stdout,stderr=child.stderr,result=result,requests=requests,
                    real_model_calls=0,openrouter_requests=0,native_cli=True,journal=journal,
                    ledger=ledger_summary,ledger_requests=ledger_requests,operations=operations,
                    before_recovery=before_recovery,host_resolution=host_resolution,closed_run=closed,
                    claude_audit_objects=audit_objects,
                    owned_process_group_exited=True,process_cleanup=cleanup,recovery=recovery,exit_observation=observed)
                if scenario=='acquisition':
                    report['acquisition_requests']=json.loads((c.root/'fixture-native-acquisition-requests.json').read_text())
                if evidence_directory is not None:
                    suffix=''
                    if options:
                        suffix='-'+('exit-'+options['stop_phase'] if options.get('stop_phase') else
                            'cancel-'+options['cancel_phase'] if options.get('cancel_phase') else
                            'limit-'+hashlib.sha256(json.dumps(options['limits'],sort_keys=True).encode()).hexdigest()[:8]
                            if options.get('limits') else 'replay')
                        # Recovery/closure variants may share the same exit
                        # point. Preserve each variant's actual native record.
                        suffix+='-'+hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()[:12]
                    (evidence_directory/(scenario+suffix+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                return report
        finally:
            server.shutdown();server.server_close();thread.join()
    finally:c.doCleanups()


class NativeClaudeTests(unittest.TestCase):
    def test_observed_clarification_exit_continues_child_with_cumulative_budget(self):
        report=run_scenario('clarify_continue',options=dict(stop_phase='clarification_object_written',
            recover_after_exit=True,observe_exit=True,continue_answer=True))
        self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
        self.assertEqual(len(report['requests']),9)
        self.assertEqual(report['result']['status'],'completed')
        parent=report['result']['fixture_parent_result']
        self.assertEqual(parent['kind'],'needs_clarification')
        self.assertFalse(parent['runtime']['execution_time_uncertain'])
        self.assertEqual(parent['runtime']['time_reconciliation']['kind'],'supervised_upper_bound')
        self.assertEqual(report['result']['delivery']['delivery']['usage']['model_calls'],9)
        self.assertEqual(len(report['result']['delivery']['delivery']['usage']['time_reconciliations']),1)
        self.assertTrue(report['exit_observation']['process_group_empty'])

    def test_native_cli_six_tools_full_message_boundary_and_delivery(self):
        report=run_scenario('success')
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        result=report['result'];self.assertEqual(result['status'],'completed',result['error'])
        init=next(e['data']['data'] for e in result['native_events'] if e['type']=='SystemMessage' and e['data']['subtype']=='init')
        self.assertEqual(init['permissionMode'],'default')
        self.assertEqual(set(init['tools']),{'mcp__data__'+name for name in ['find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver','clarify']})
        self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')
        self.assertEqual({e['tool'] for e in result['tool_events'] if e['type']=='tool_handler_return'},
            {'find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver'})
        actual=[v for r in report['requests'] for v in outputs(r.get('messages',[]))]
        observed=[e['output'] for e in result['tool_events'] if e['type']=='observed_tool_result']
        self.assertTrue(observed)
        self.assertTrue(all(value in actual for value in observed))
        self.assertTrue(all(r.get('model')=='fixture/claude-query-v1' for r in report['requests']))
        self.assertTrue(all(r.get('max_tokens')==4096 for r in report['requests']))
        self.assertEqual(len(report['requests']),8, 'accepted deliver must not cause another model request')
        self.assertEqual(len([e for e in result['tool_events'] if e['type']=='native_stop_requested']),1)
        self.assertEqual(report['ledger']['request_stages'],{'responded':8})
        self.assertEqual(len(report['journal']['tool_calls']),8)
        for saved,actual_request in zip(report['ledger_requests'],report['requests']):
            self.assertEqual(json.loads(base64.b64decode(saved['request']['request']['body_base64'])),actual_request)
            self.assertEqual(saved['cost_state'],'settled')
            self.assertTrue(saved['response_event']['response']['complete'])

    def test_native_request_limit_blocks_upstream_and_terminal_replay_is_free(self):
        limits=F['runtime_limits'](max_model_requests=1)
        report=run_scenario('success',options={'limits':limits})
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        self.assertEqual(report['result']['status'],'partial')
        self.assertEqual(report['result']['delivery']['delivery']['stop_reason'],'model_budget')
        self.assertEqual(len(report['requests']),1)
        self.assertEqual(report['ledger']['request_stages'],{'responded':1})
        repeated=run_scenario('success',options={'replay':True})
        self.assertTrue(repeated['result']['fixture_replay_equal'])
        self.assertEqual(len(repeated['requests']),8)

    def test_native_process_exit_after_response_before_commit_keeps_unknown_identity(self):
        report=run_scenario('success',options={'stop_phase':'model_response_received'})
        self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
        self.assertEqual(len(report['requests']),1)
        self.assertEqual(report['ledger']['request_stages'],{'dispatched':1})
        self.assertIsNone(report['ledger_requests'][0]['response_event'])
        self.assertFalse(report['operations'])
        self.assertIsNone(report['result'])

    def test_native_delivery_process_exit_recovers_exact_package_without_another_request(self):
        for phase in ('delivery_accepted','delivery_object_written','delivery_response_committed'):
            with self.subTest(phase=phase):
                report=run_scenario('success',options={'stop_phase':phase,'recover_after_exit':True})
                self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
                self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
                self.assertEqual(len(report['requests']),8)
                operation=next(o for o in report['operations'].values() if o['tool']=='deliver')
                self.assertEqual(report['result']['delivery']['delivery'],operation['terminal_intent']['package'])
                self.assertFalse(report['result']['native_success'])
                self.assertTrue(report['result']['runtime']['execution_time_uncertain'])
                self.assertEqual(report['ledger']['request_stages'],{'responded':8})

    def test_native_tool_response_and_index_effect_recover_without_another_model_request(self):
        for phase,calls in [('tool_response_prepared',1),('index_after_head',3)]:
            with self.subTest(phase=phase):
                report=run_scenario('success',options={'stop_phase':phase,'recover_after_exit':True})
                self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
                self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
                self.assertEqual(len(report['requests']),calls)
                self.assertEqual(report['result']['kind'],'recovery_required')
                self.assertFalse(report['result']['native_success'])
                self.assertTrue(report['result']['runtime']['execution_time_uncertain'])
                self.assertEqual(report['ledger']['request_stages'],{'responded':calls})
                self.assertTrue(all(o['status']=='completed' for o in report['operations'].values()))
                self.assertTrue(all(t['output'] is not None for t in report['journal']['tool_calls'].values()))
                if phase=='index_after_head':
                    operation=next(o for o in report['operations'].values() if o['tool']=='request_asset_update')
                    self.assertEqual(operation['response']['items'][0]['derived_generation'],operation['effect_intent']['target']['generation'])

    def test_native_acquisition_publication_recovers_without_model_or_source_retry(self):
        for phase in ('before_build_commit','after_build_commit'):
            with self.subTest(phase=phase):
                report=run_scenario('acquisition',options={'stop_phase':phase,'recover_after_exit':True})
                self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
                self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
                self.assertEqual(len(report['requests']),1)
                self.assertEqual(len(report['acquisition_requests']),2)
                self.assertEqual(report['result']['kind'],'recovery_required')
                operation=next(iter(report['operations'].values()))
                self.assertEqual(operation['status'],'completed')
                self.assertEqual(operation['response']['items'][0]['new_asset_refs'][0]['snapshot_id'],operation['effect_intent']['target']['snapshot_id'])
                self.assertEqual(operation['response']['recovery']['kind'],'verified_existing_acquisition')
                self.assertEqual(report['ledger']['request_stages'],{'responded':1})
                self.assertTrue(all(t['output'] is not None for t in report['journal']['tool_calls'].values()))

    def test_native_cancel_preserves_response_and_closes_cli_without_another_call(self):
        report=run_scenario('success',options={'cancel_phase':'model_response_received'})
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        self.assertEqual(len(report['requests']),1)
        self.assertEqual(report['result']['status'],'cancelled')
        self.assertEqual(report['result']['delivery']['delivery']['business_status'],'cancelled')
        self.assertEqual(report['process_cleanup']['before'],[], 'SDK shutdown left a live native descendant')
        self.assertEqual(sum(report['ledger']['request_stages'].values()),1)
        self.assertFalse(any(o['tool']!='deliver' for o in report['operations'].values()))

    def test_native_turn_limit_forces_partial_delivery_without_summary_request(self):
        report=run_scenario('success',options={'limits':F['runtime_limits'](native_max_turns=1)})
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        self.assertEqual(report['result']['status'],'partial')
        self.assertEqual(report['result']['delivery']['delivery']['stop_reason'],'native_max_turns')
        self.assertEqual(len(report['requests']),1)

    def test_native_clarification_and_child_share_root_budget_without_reusing_session(self):
        report=run_scenario('clarify_continue',options={'continue_answer':True})
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        self.assertEqual(len(report['requests']),9)
        result=report['result'];parent=result['fixture_parent_result']
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual(parent['kind'],'needs_clarification')
        self.assertEqual(parent['runtime']['budget']['request_stages'],{'responded':1})
        self.assertEqual(result['runtime']['root_run_id'],parent['runtime']['root_run_id'])
        self.assertNotEqual(result['runtime']['native_session_id'],parent['runtime']['native_session_id'])
        self.assertEqual(report['ledger']['request_stages'],{'responded':9})
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],9)

    def test_native_clarification_recovery_keeps_original_question_and_request_count(self):
        for phase in ('clarification_accepted','clarification_object_written','clarification_response_committed'):
            with self.subTest(phase=phase):
                report=run_scenario('clarify',options={'stop_phase':phase,'recover_after_exit':True})
                self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
                self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
                self.assertEqual(len(report['requests']),1)
                result=report['result'];operation=next(o for o in report['operations'].values() if o['tool']=='clarify')
                self.assertEqual(result['kind'],'needs_clarification')
                self.assertEqual(result['clarification']['clarification'],operation['terminal_intent']['package'])
                self.assertTrue(result['runtime']['execution_time_uncertain'])

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
