"""Transport bytes and actual-account billing are separate durable facts."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from uteki.data_platform.agent.providers.openrouter_evidence import (
    capture_response, observe_response, record_response, reconcile_response, response_bytes)
from uteki.infrastructure.run_budget import RunBudget, RequestIdentityConflict, RequestRecoveryRequired


MODEL = 'synthetic/model'


def chat(cost='0.123456789012345678901', generation='gen-synthetic-a'):
    return (json.dumps(dict(id=generation, model=MODEL, provider='Synthetic', object='chat.completion',
        choices=[dict(index=0,finish_reason='stop',message=dict(role='assistant',content='synthetic'))],
        usage=dict(prompt_tokens=12,completion_tokens=3,total_tokens=15,
                   cost_details={'upstream_inference_cost':0.00001},cost='PLACEHOLDER')))
        .replace('"PLACEHOLDER"',cost).encode())


def capture(raw, protocol='chat_completions', *, status=200, media='application/json', headers=(), maximum=10000):
    return capture_response(protocol,status,[('Content-Type',media),*headers],[raw],max_bytes=maximum)


def generation(*, identity='gen-synthetic-a', cost='0.04'):
    return capture((json.dumps(dict(data=dict(id=identity, model=MODEL, provider_name='Synthetic',
        total_cost='COST', usage=999, upstream_inference_cost=999,native_tokens_prompt=12)))
        .replace('"COST"',cost)).encode(), 'generation')


class GatewayEvidenceTests(unittest.TestCase):
    def test_messages_optional_done_is_framing_not_json_or_proof_of_completion(self):
        events=[dict(type='message_start',message=dict(id='msg_native',model=MODEL,
                    type='message',usage=dict(input_tokens=4,output_tokens=0))),
                dict(type='message_delta',delta=dict(stop_reason='tool_use'),usage=dict(output_tokens=5)),
                dict(type='message_stop')]
        raw=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
        for suffix in (b'',b'data: [DONE]\n\n',b'event: data\ndata: [DONE]\n\n: comment\n\n'):
            cap=capture(raw+suffix,'anthropic_messages',media='text/event-stream')
            with self.subTest(suffix=suffix):
                self.assertTrue(observe_response(cap)['protocol_complete'])
                self.assertEqual(response_bytes(cap),raw+suffix)
        done=b'event: data\ndata: [DONE]\n\n'
        for bad in (done,raw[:raw.index(b'event: message_stop')]+done,
                    raw+done+done,raw+done+b'event: ping\ndata: {"type":"ping"}\n\n',
                    raw+done[:-2]):
            with self.subTest(bad=bad):
                self.assertFalse(observe_response(capture(bad,'anthropic_messages',media='text/event-stream'))['protocol_complete'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uteki-gateway-evidence-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'budget.sqlite'
        self.budget=RunBudget(self.path,'2')
        self.budget.bind_root('synthetic-gateway',mode='remote',max_requests=4,
            scope_ids=['case-a','case-b'],max_in_flight_requests=1,policy={'synthetic':True})
        for name in ('case-a','case-b'):
            self.budget.bind_scope(name,max_requests=2,policy={'context':name})
        self.budget.prepare_request('first',{'synthetic':'request'},reserve_usd='.8',scope_id='case-a')
        self.budget.begin_request('first')

    def record(self, cap, **kwargs):
        return record_response(self.budget,'first',cap,origin='synthetic',**kwargs)

    def next_request(self):
        return self.budget.prepare_request('second',{'synthetic':'other SDK'},reserve_usd='.8',scope_id='case-b')

    def test_raw_decimal_charge_survives_reopen_without_upstream_or_sdk_cost_substitution(self):
        raw=chat(); cap=capture(raw); first=self.record(cap)
        self.budget=RunBudget.open_existing(self.path,'2',root_run_id='synthetic-gateway')
        saved=self.budget.inspect_request('first')
        self.assertEqual(saved, first)
        self.assertEqual(response_bytes(saved['response_event']['response']['http']),raw)
        self.assertEqual(saved['settled_usd'],'0.123456789012345678901')
        self.assertEqual(saved['bill']['receipt']['source'],'synthetic:chat.usage.cost')
        self.assertEqual(self.record(cap),saved)
        self.next_request()

    def test_zero_is_a_bill_but_absent_null_tokens_and_estimates_are_not(self):
        self.assertEqual(observe_response(capture(chat('0')))['billed_usd'],'0')
        for value in ('null','true','-1','"0.2"','NaN','Infinity'):
            with self.subTest(value=value):
                result=observe_response(capture(chat(value)))
                self.assertIsNone(result['billed_usd'])
        value=json.loads(chat());del value['usage']['cost']
        self.assertIsNone(observe_response(capture(json.dumps(value).encode()))['billed_usd'])

    def test_missing_cost_blocks_both_scopes_and_lookup_releases_only_original_hold(self):
        cap=capture(chat('null')); stored=self.record(cap)
        with self.assertRaises(RequestRecoveryRequired): self.next_request()
        self.budget.stop_scope('case-a','cancelled')
        with self.assertRaises(RequestIdentityConflict):
            reconcile_response(self.budget,'first',generation(identity='gen-other'),origin='synthetic')
        self.assertEqual(self.budget.inspect_request('first'),stored)
        receipt=generation(cost='0.04')
        final=reconcile_response(self.budget,'first',receipt,origin='synthetic')
        self.assertEqual(final['response_event'],stored['response_event'])
        self.assertEqual(final['settled_usd'],'0.04')
        self.assertEqual(reconcile_response(self.budget,'first',receipt,origin='synthetic'),final)
        self.assertEqual(self.budget.summary()['requests'],1)
        self.next_request()

    def test_withholding_billing_retains_raw_bill_and_never_uses_zero(self):
        cap=capture(chat('0.04')); saved=self.record(cap,withhold_billing=True)
        self.assertEqual(response_bytes(saved['response_event']['response']['http']),response_bytes(cap))
        self.assertEqual(saved['cost_state'],'unknown')
        with self.assertRaises(RequestRecoveryRequired): self.next_request()
        reconcile_response(self.budget,'first',generation(),origin='synthetic')
        self.assertEqual(self.budget.inspect_request('first')['settled_usd'],'0.04')

    def test_duplicate_json_or_conflicting_generation_identity_cannot_settle(self):
        raw=chat().replace(b'"cost":',b'"cost": 0, "cost":')
        result=observe_response(capture(raw))
        self.assertFalse(result['protocol_complete']);self.assertIsNone(result['billed_usd'])
        cap=capture(chat(),headers=[('X-Generation-Id','gen-other')])
        result=observe_response(cap)
        self.assertFalse(result['protocol_complete']);self.assertIsNone(result['generation_id'])
        saved=self.record(cap)
        self.assertEqual(saved['stage'],'outcome_unknown')
        with self.assertRaises(RequestIdentityConflict):
            reconcile_response(self.budget,'first',generation(identity='gen-other'),origin='synthetic')

    def test_http_error_is_preserved_but_not_assumed_free_or_a_model_success(self):
        cap=capture(b'{"error":{"message":"synthetic rejection"}}',status=429,
                    headers=[('x-generation-id','gen-synthetic-a')])
        saved=self.record(cap)
        self.assertEqual(saved['stage'],'responded')
        self.assertEqual(saved['cost_state'],'unknown')
        self.assertFalse(saved['response_event']['response']['observation']['protocol_complete'])
        with self.assertRaises(RequestRecoveryRequired): self.next_request()

    def test_incomplete_read_preserves_prefix_and_bill_does_not_invent_missing_response(self):
        full=chat('0.04')
        def chunks():
            yield full[:17]
            raise http.client.IncompleteRead(full[17:32],len(full)-32)
        cap=capture_response('chat_completions',200,
            [('Content-Type','application/json'),('x-generation-id','gen-synthetic-a')],chunks(),max_bytes=10000)
        self.assertEqual(response_bytes(cap),full[:32])
        self.assertFalse(cap['transport_complete'])
        before=self.record(cap)
        reconcile_response(self.budget,'first',generation(),origin='synthetic')
        self.assertEqual(self.budget.inspect_request('first')['stage'],'outcome_unknown')
        with self.assertRaises(RequestRecoveryRequired): self.next_request()
        recovered=capture(full,headers=[('x-generation-id','gen-synthetic-a')])
        final=self.record(recovered)
        self.assertEqual(final['stage'],'responded')
        self.assertEqual(final['settled_usd'],'0.04')
        self.assertEqual(final['response_event']['prior_response_events'],[before['response_event']])
        self.assertEqual(self.record(recovered),final)
        self.next_request()

    def test_unknown_recovery_rejects_changed_prefix_status_or_headers(self):
        raw=chat('null');self.record(capture(raw,maximum=32))
        for cap in (capture(raw.replace(b'gen-synthetic-a',b'gen-synthetic-b')),
                    capture(raw,status=201),capture(raw,headers=[('x-generation-id','gen-synthetic-a')])):
            with self.subTest(cap=cap['status']),self.assertRaises(RequestIdentityConflict):self.record(cap)
        self.assertEqual(self.budget.inspect_request('first')['stage'],'outcome_unknown')

    def test_bound_and_network_error_do_not_discard_observed_bytes(self):
        raw=chat()
        cap=capture(raw,maximum=19)
        self.assertEqual(response_bytes(cap),raw[:19]);self.assertEqual(cap['error'],'response_too_large')
        def chunks():
            yield b'prefix'
            raise TimeoutError('synthetic')
        cap=capture_response('chat_completions',200,[],chunks(),max_bytes=100)
        self.assertEqual(response_bytes(cap),b'prefix');self.assertEqual(cap['error'],'TimeoutError')
        exact=capture(b'x'*19,maximum=19)
        self.assertTrue(exact['transport_complete'])

    def test_raw_response_and_charge_commit_atomically_or_remain_recoverable(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER synthetic_fail BEFORE UPDATE OF response_event ON metered_requests "
                       "BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END");db.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.record(capture(chat()))
        saved=self.budget.inspect_request('first')
        self.assertEqual(saved['stage'],'dispatched');self.assertIsNone(saved['response_event'])
        self.assertEqual(Decimal(self.budget.summary()['held_usd']),Decimal('.8'))
        self.budget.recover_requests(scope_id='case-a')
        with self.assertRaises(RequestRecoveryRequired): self.next_request()

    def test_tampered_bytes_cannot_be_parsed_or_used_for_billing(self):
        cap=capture(chat());cap['body_base64']=base64.b64encode(chat('0')).decode()
        with self.assertRaises(ValueError):self.record(cap)
        self.assertEqual(self.budget.inspect_request('first')['stage'],'dispatched')

    def test_header_allowlist_excludes_credentials_and_rejects_identity_ambiguity(self):
        cap=capture(chat(),headers=[('Authorization','secret'),('Set-Cookie','private'),
                    ('X-Generation-Id','gen-synthetic-a'),('x-generation-id','gen-other')])
        self.assertNotIn('secret',json.dumps(cap));self.assertNotIn('private',json.dumps(cap))
        result=observe_response(cap)
        self.assertIsNone(result['billed_usd']);self.assertFalse(result['protocol_complete'])

    def test_native_messages_account_cost_requires_generation_and_not_session_estimate(self):
        raw=json.dumps(dict(id='msg_native',type='message',model=MODEL,stop_reason='end_turn',
            content=[dict(type='text',text='synthetic')],usage=dict(input_tokens=10,output_tokens=5,cost=.01),
            total_cost_usd=.02)).encode()
        no_id=observe_response(capture(raw,'anthropic_messages'))
        self.assertIsNone(no_id['generation_id']);self.assertIsNone(no_id['billed_usd'])
        cap=capture(raw,'anthropic_messages',headers=[('X-Generation-Id','gen-synthetic-a')])
        saved=self.record(cap);self.assertEqual(saved['settled_usd'],'0.01')
        self.assertEqual(saved['bill']['receipt']['source'],'synthetic:messages.usage.cost')
        value=json.loads(raw);del value['usage']['cost']
        self.assertIsNone(observe_response(capture(json.dumps(value).encode(),'anthropic_messages',
            headers=[('X-Generation-Id','gen-synthetic-a')]))['billed_usd'])

    def test_messages_final_usage_decimal_string_is_an_account_charge(self):
        def stream(cost):
            events=[dict(type='message_start',message=dict(id='msg_native',type='message',model=MODEL,
                usage=dict(input_tokens=1,output_tokens=0,cost=999))),
                dict(type='message_delta',delta=dict(stop_reason='tool_use'),usage=dict(output_tokens=21,cost=cost)),
                dict(type='message_stop')]
            raw=b''.join(('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode() for e in events)+b'event: data\ndata: [DONE]\n\n'
            return capture(raw,'anthropic_messages',media='text/event-stream',headers=[('X-Generation-Id','gen-synthetic-a')])
        cap=stream('0.0033128');saved=self.record(cap)
        self.assertEqual(saved['settled_usd'],'0.0033128')
        self.assertEqual(response_bytes(saved['response_event']['response']['http']),response_bytes(cap))
        for cost in (True,'NaN','-1',' 0.1','1e2',None):
            with self.subTest(cost=cost):self.assertIsNone(observe_response(stream(cost))['billed_usd'])
        incomplete=stream('0.0033128');incomplete['transport_complete']=False;incomplete['error']='interrupted'
        self.assertIsNone(observe_response(incomplete)['billed_usd'])

    def test_native_sse_envelopes_preserve_usage_and_require_real_terminal_events(self):
        events=[dict(type='message_start',message=dict(id='msg_native',model=MODEL,type='message',
            usage=dict(input_tokens=10,output_tokens=0))),
            dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text='original')),
            dict(type='message_delta',delta=dict(stop_reason='end_turn'),usage=dict(output_tokens=5)),
            dict(type='message_stop')]
        raw=b''.join(('event: '+e['type']+'\r\ndata: '+json.dumps(e)+'\r\n\r\n').encode() for e in events)
        cap=capture(raw,'anthropic_messages',media='text/event-stream',headers=[('x-generation-id','gen-synthetic-a')])
        observed=observe_response(cap)
        self.assertTrue(observed['protocol_complete']);self.assertIsNone(observed['billed_usd'])
        self.assertEqual(observed['usage_observations'],[{'input_tokens':10,'output_tokens':0},{'output_tokens':5}])
        for bad in (raw[:-2],raw[:raw.index(b'event: message_stop')],raw+raw):
            result=observe_response(capture(bad,'anthropic_messages',media='text/event-stream'))
            self.assertFalse(result['protocol_complete']);self.assertIsNone(result['billed_usd'])

    def test_wrong_route_charge_remains_observable_without_claiming_profile_match(self):
        cap=capture(chat('0.1').replace(MODEL.encode(),b'different/model'))
        saved=self.record(cap)
        self.assertEqual(saved['settled_usd'],'0.1')
        self.assertEqual(saved['response_event']['response']['observation']['model'],'different/model')
        self.assertNotIn('route_verified',saved['response_event']['response']['observation'])

    def test_generation_lookup_requires_its_own_exact_id_not_a_different_body_with_matching_header(self):
        self.record(capture(chat('null')))
        bad=generation(identity='msg_other')
        bad['headers'].append(['x-generation-id','gen-synthetic-a'])
        with self.assertRaises(RequestIdentityConflict):
            reconcile_response(self.budget,'first',bad,origin='synthetic')
        self.assertEqual(self.budget.inspect_request('first')['cost_state'],'unknown')

    def test_one_generation_bill_cannot_be_attached_to_two_physical_requests(self):
        cap=capture(chat('0.04'));self.record(cap)
        self.next_request();self.budget.begin_request('second')
        with self.assertRaises(RequestIdentityConflict):
            record_response(self.budget,'second',cap,origin='synthetic')
        self.assertEqual(self.budget.inspect_request('second')['stage'],'dispatched')
        self.assertIsNone(self.budget.inspect_request('second')['bill'])
        self.assertEqual(self.budget.inspect_request('first')['settled_usd'],'0.04')

    def test_generation_uniqueness_is_atomic_under_concurrent_observations(self):
        budget=RunBudget(self.path.with_name('concurrent.sqlite'),'2')
        budget.bind_root('concurrent-root',mode='remote',max_requests=2,
            max_in_flight_requests=2,policy={'synthetic':True})
        for key in ('a','b'):
            budget.prepare_request(key,{'synthetic':key},reserve_usd='.8');budget.begin_request(key)
        def finish(key):
            try:
                record_response(budget,key,capture(chat('0.04')),origin='synthetic')
                return 'settled'
            except RequestIdentityConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(finish,('a','b'))),['settled','conflict'])
        self.assertEqual(Decimal(budget.summary()['estimated_spent_usd']),Decimal('0.04'))
        self.assertEqual(Decimal(budget.summary()['held_usd']),Decimal('.8'))

    def test_recovered_inline_cost_conflict_does_not_replace_original_or_reconciled_bill(self):
        raw=chat('0.05')
        headers=[('x-generation-id','gen-synthetic-a')]
        self.record(capture(raw,headers=headers,maximum=32))
        reconcile_response(self.budget,'first',generation(cost='0.04'),origin='synthetic')
        before=self.budget.inspect_request('first')
        with self.assertRaises(RequestIdentityConflict):self.record(capture(raw,headers=headers))
        self.assertEqual(self.budget.inspect_request('first'),before)

    def test_generation_error_null_or_wrong_origin_does_not_release_unknown_hold(self):
        self.record(capture(chat('null')))
        original=self.budget.inspect_request('first')
        for cap,origin in [(generation(cost='null'),'synthetic'),(generation(),'openrouter'),
                (capture(b'{"error":{"code":404}}','generation',status=404),'synthetic')]:
            with self.subTest(origin=origin),self.assertRaises(RequestIdentityConflict):
                reconcile_response(self.budget,'first',cap,origin=origin)
            self.assertEqual(self.budget.inspect_request('first'),original)

    def test_valid_json_with_incomplete_http_content_length_is_still_unknown(self):
        raw=chat('0.04')
        for length in (str(len(raw)+1),'-1','invalid'):
            with self.subTest(length=length):
                cap=capture(raw,headers=[('Content-Length',length)])
                self.assertFalse(cap['transport_complete'])
                self.assertEqual(response_bytes(cap),raw)
                self.assertIsNone(observe_response(cap)['billed_usd'])
        good=capture(raw,headers=[('Content-Length',str(len(raw)))])
        self.assertEqual(observe_response(good)['billed_usd'],'0.04')
        conflict=capture(raw,headers=[('Content-Length',str(len(raw))),('Content-Length','1')])
        self.assertFalse(conflict['transport_complete'])

    def test_content_encoding_is_not_silently_ignored(self):
        cap=capture(chat('0.04'),headers=[('Content-Encoding','gzip')])
        observed=observe_response(cap)
        self.assertFalse(observed['protocol_complete']);self.assertIsNone(observed['billed_usd'])


if __name__=='__main__':unittest.main()
