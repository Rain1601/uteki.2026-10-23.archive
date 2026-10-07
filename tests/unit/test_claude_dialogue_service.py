"""Shared local conversation service: every transport is an injected mock."""
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

from apps.claude_dialogue.service import DialogueService, DialogueError, MAX_TOKENS
from scripts import claude_dialogue as d


class DialogueServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root/'private-dialogue'
        self.base.mkdir(mode=0o700)
        system, price = self.root/'system.txt', self.root/'price.json'
        system.write_text('PRIVATE_SYSTEM_INSTRUCTIONS')
        price.write_text(json.dumps({'model':d.MODEL,'input_per_million':'4','output_per_million':'20',
            'cache_read_per_million':'0.2','source_url':'https://example.invalid/frozen-price','checked_date':'2026-10-07'}))
        d.init_session(self.base/'session',system_file=system,model=d.MODEL,budget_usd='1.5',
            max_calls=3,max_tokens=8192,price_file=price)
        self.requests,self.options,self.clients = [],[],[]
        self.secret='PRIVATE_FAKE_KEY'
        env=patch.dict(os.environ,{'AIHUBMIX_API_KEY':self.secret},clear=True)
        env.start()
        self.addCleanup(env.stop)
        credentials=patch.object(d,'load_provider_key')
        self.credential_loader=credentials.start()
        self.addCleanup(credentials.stop)
        self.payload={'id':'msg_fixture','model':d.MODEL,'stop_reason':'end_turn',
            'usage':{'input_tokens':900,'output_tokens':75,'cache_read_input_tokens':10},
            'content':[{'type':'thinking','thinking':'PRIVATE_THINKING','signature':'PRIVATE_SIGNATURE'},
                       {'type':'text','text':'Visible reply.\n第二行。'}]}
        self.service=DialogueService(self.base,credentials_root=self.root,client_factory=self.factory)

    def respond(self,request):
        self.requests.append(request)
        return d.httpx.Response(200,json=self.payload)

    def factory(self,**options):
        self.options.append(options.copy())
        options['transport']=d.httpx.MockTransport(self.respond)
        client=d.httpx.AsyncClient(**options)
        self.clients.append(client)
        return client

    def send(self,text='A question.',actor='user'):
        return asyncio.run(self.service.send(text,self.service.history()['revision'],actor=actor))

    def legacy(self,text):
        message=self.root/'legacy-message.txt'
        message.write_text(text)
        return asyncio.run(d.turn(self.base/'session',message_file=message,credentials_root=self.root,client_factory=self.factory))

    def stored_text(self):
        return '\n'.join(p.read_text() for p in self.base.rglob('*') if p.is_file())

    def test_history_is_readonly_and_original_turns_are_labeled_as_codex(self):
        self.legacy('Old question.')
        before={str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        history=self.service.history()
        self.assertEqual(len(history['turns']),1)
        self.assertEqual(history['turns'][0]['actor'],'codex')
        self.assertFalse(history['turns'][0]['actor_recorded'])
        self.assertEqual(history['messages'][0]['content'],'Old question.')
        self.assertFalse((self.base/'window').exists())
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()})
        output=json.dumps(history)
        for value in ('PRIVATE_SYSTEM_INSTRUCTIONS',str(self.base),self.secret,'PRIVATE_THINKING','PRIVATE_SIGNATURE'):
            self.assertNotIn(value,output)

    def test_user_and_codex_share_full_history_exact_request_and_append_only_costs(self):
        self.legacy('Original user text.')
        old_files={p:p.read_bytes() for p in (self.base/'session').rglob('*') if p.is_file()}
        first=self.send('Manual message.\n完整内容。','user')
        first_folder=self.base/'continuations/0002'
        immutable={p:p.read_bytes() for p in first_folder.iterdir()}
        second=self.send('Codex follows up.','codex')
        body=json.loads(self.requests[-1].content)
        self.assertEqual(body['messages'],[
            {'role':'user','content':'Original user text.'},{'role':'assistant','content':'Visible reply.\n第二行。'},
            {'role':'user','content':'Manual message.\n完整内容。'},{'role':'assistant','content':'Visible reply.\n第二行。'},
            {'role':'user','content':'Codex follows up.'}])
        self.assertEqual(body['max_tokens'],4096)
        self.assertEqual(body['thinking'],{'type':'adaptive'})
        self.assertEqual(body['output_config'],{'effort':'high'})
        self.assertFalse(body['stream'])
        self.assertEqual(set(body),{'model','system','messages','max_tokens','thinking','output_config','stream'})
        self.assertEqual([t['actor'] for t in second['turns']],['codex','user','codex'])
        self.assertNotEqual(first['revision'],second['revision'])
        self.assertEqual(Decimal(second['summary']['estimated_spent_usd']),Decimal('0.015306'))
        for path,value in {**old_files,**immutable}.items():
            self.assertEqual(path.read_bytes(),value)
        for path in [self.base,*self.base.rglob('*')]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o700 if path.is_dir() else 0o600)
        receipt=json.loads((self.base/'continuations/0003/receipt.json').read_bytes())
        self.assertEqual(receipt['reservation_basis']['method'],'verified_prefix_reported_tokens_plus_suffix_utf8_bytes')
        self.assertEqual(receipt['reservation_basis']['prefix_input_tokens'],910)
        self.assertEqual(receipt['request_sha256'],d._sha(self.requests[-1].content))
        self.assertEqual((self.base/'continuations/0003/request.json').read_bytes(),self.requests[-1].content)
        for value in (self.secret,'PRIVATE_THINKING','PRIVATE_SIGNATURE'):
            self.assertNotIn(value,self.stored_text())
        self.assertTrue(all(c.is_closed for c in self.clients))
        for options in self.options:
            self.assertEqual(options['timeout'],240)
            self.assertFalse(options['follow_redirects'])
            self.assertFalse(options['trust_env'])

    def test_legacy_three_plus_six_continuations_are_validated_as_one_nine_turn_chain(self):
        for number in range(1,4):
            self.legacy(f'Legacy {number}')
        for number in range(4,10):
            self.send(f'Continuation {number}','codex')
            # Historical continuation runners did not record an actor field.
            folder=self.base/'continuations'/f'{number:04d}'
            receipt=json.loads((folder/'receipt.json').read_bytes())
            receipt.pop('actor')
            authorization=json.loads((folder/'authorization.json').read_bytes())
            for field in ('actor','expected_revision','window_event_sha256'):
                authorization.pop(field)
            auth_raw=d._json(authorization)
            (folder/'authorization.json').write_bytes(auth_raw)
            receipt['authorization_sha256']=d._sha(auth_raw)
            raw=d._json(receipt)
            (folder/'receipt.json').write_bytes(raw)
            (folder/'receipt.sha256').write_text(d._sha(raw))
        history=self.service.history()
        self.assertEqual(len(history['turns']),9)
        self.assertEqual(len(history['messages']),18)
        self.assertTrue(all(t['actor']=='codex' and not t['actor_recorded'] for t in history['turns']))
        self.send('Tenth append.','user')
        self.assertTrue((self.base/'continuations/0010/receipt.json').exists())
        self.assertEqual(len(json.loads(self.requests[-1].content)['messages']),19)

    def test_budget_event_changes_only_window_and_stale_revision_cannot_send(self):
        history=self.service.history()
        session_bytes=(self.base/'session/session.json').read_bytes()
        changed=self.service.set_budget('2',history['revision'],actor='user')
        self.assertEqual(changed['summary']['budget_usd'],'2')
        self.assertEqual(changed['summary']['original_budget_usd'],'1.5')
        self.assertEqual((self.base/'session/session.json').read_bytes(),session_bytes)
        self.assertEqual(len(changed['budget_events']),1)
        with self.assertRaisesRegex(DialogueError,'revision_conflict'):
            asyncio.run(self.service.send('Stale request.',history['revision']))
        with self.assertRaisesRegex(DialogueError,'budget_requires_explicit_user'):
            self.service.set_budget('3',changed['revision'],actor='codex')
        d._write(self.base/'window/connection.json',b'{"opaque":"connection-owned-by-http"}')
        self.assertEqual(self.service.history()['revision'],changed['revision'])
        self.assertEqual(self.requests,[])

    def test_budget_preflight_does_not_reserve_write_or_load_credentials(self):
        current=self.service.history()
        self.service.set_budget('0.01',current['revision'])
        history=self.service.history()
        before={p:p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        result=self.service.preflight('More words.',history['revision'])
        self.assertEqual((result['allowed'],result['reason']),(False,'budget_insufficient'))
        with self.assertRaisesRegex(DialogueError,'budget_insufficient'):
            asyncio.run(self.service.send('More words.',history['revision']))
        self.assertEqual(before,{p:p.read_bytes() for p in self.base.rglob('*') if p.is_file()})
        self.assertEqual(self.requests,[])
        self.credential_loader.assert_not_called()
        self.assertEqual(self.service.history()['summary']['held_usd'],'0')

    def test_reservation_falls_back_when_fixed_request_configuration_does_not_match(self):
        self.legacy('Original 8192 token config.')
        check=self.service.preflight('New 4096 token config.',self.service.history()['revision'])
        self.assertEqual(check['reservation_basis']['method'],'full_request_utf8_bytes')
        self.assertEqual(check['reservation_basis']['input_token_reservation'],check['request_bytes']+4096)
        self.send()
        check=self.service.preflight('Matched prefix.',self.service.history()['revision'])
        self.assertEqual(check['reservation_basis']['method'],'verified_prefix_reported_tokens_plus_suffix_utf8_bytes')
        self.assertEqual(check['reservation_basis']['output_token_reservation'],MAX_TOKENS)

    def test_timeout_retains_unknown_cost_blocks_followup_and_redacts_error_body(self):
        def timeout(request):
            self.requests.append(request)
            raise d.httpx.ReadTimeout('PRIVATE_PROVIDER_ERROR '+self.secret,request=request)
        self.respond=timeout
        result=self.send()
        self.assertEqual(result['turns'][-1]['status'],'failed')
        self.assertEqual(result['turns'][-1]['error_code'],'timeout')
        self.assertIsNone(result['turns'][-1]['estimated_usd'])
        self.assertGreater(Decimal(result['summary']['held_usd']),0)
        self.assertEqual(result['summary']['completed_turns'],0)
        with self.assertRaisesRegex(DialogueError,'previous_turn_failed_or_interrupted'):
            self.send('No automatic retry.')
        self.assertEqual(len(self.requests),1)
        self.assertNotIn('PRIVATE_PROVIDER_ERROR',self.stored_text()+json.dumps(result))
        self.assertNotIn(self.secret,self.stored_text()+json.dumps(result))

    def test_truncated_visible_answer_is_displayed_but_never_committed_to_context(self):
        self.payload['stop_reason']='max_tokens'
        result=self.send()
        self.assertEqual(result['turns'][-1]['answer'],'Visible reply.\n第二行。')
        self.assertEqual(result['turns'][-1]['status'],'failed')
        self.assertEqual(result['summary']['completed_turns'],0)
        self.assertEqual(Decimal(result['summary']['estimated_spent_usd']),Decimal('0.005102'))
        self.assertEqual(result['summary']['held_usd'],'0')
        with self.assertRaises(DialogueError):
            self.send('Do not advance.')
        self.assertEqual(len(self.requests),1)

    def test_unknown_usage_cache_cost_and_secret_response_are_fail_closed(self):
        original=json.loads(json.dumps(self.payload))
        for failure in ('missing_usage','malformed_usage','cache_write','secret_response'):
            with self.subTest(failure=failure):
                base=self.root/failure
                base.mkdir(mode=0o700)
                shutil.copytree(self.base/'session',base/'session')
                service=DialogueService(base,credentials_root=self.root,client_factory=self.factory)
                self.payload=json.loads(json.dumps(original))
                if failure=='missing_usage':
                    self.payload.pop('usage')
                elif failure=='malformed_usage':
                    self.payload['usage']['input_tokens']=True
                elif failure=='cache_write':
                    self.payload['usage']['cache_creation_input_tokens']=3
                else:
                    self.payload['content']=[{'type':'text','text':self.secret}]
                result=asyncio.run(service.send('Question.',service.history()['revision']))
                self.assertEqual(result['turns'][-1]['status'],'failed')
                self.assertEqual(result['summary']['completed_turns'],0)
                if failure!='secret_response':
                    self.assertIsNone(result['turns'][-1]['estimated_usd'])
                    self.assertGreater(Decimal(result['summary']['held_usd']),0)
                else:
                    self.assertEqual(result['turns'][-1]['answer'],'')
                    self.assertEqual(result['turns'][-1]['error_code'],'credential_in_response')
                combined=''.join(p.read_text() for p in base.rglob('*') if p.is_file())+json.dumps(result)
                self.assertNotIn(self.secret,combined)
                self.assertNotIn('PRIVATE_THINKING',combined)
        self.assertEqual(len(self.requests),4)

    def test_configuration_projection_is_not_mutable_service_state_and_missing_key_is_safe(self):
        result=self.service.history()
        result['configuration']['thinking']['type']='changed-by-caller'
        self.assertEqual(self.service.history()['configuration']['thinking'],{'type':'adaptive'})
        self.credential_loader.side_effect=ValueError('PRIVATE_LOCAL_PATH '+str(self.base))
        with self.assertRaisesRegex(DialogueError,'^credentials_unavailable$'):
            self.send()
        self.assertFalse((self.base/'continuations').exists())
        self.assertEqual(self.requests,[])

    def test_missing_receipt_is_visible_interrupted_user_and_blocks_continuation(self):
        self.legacy('First finished.')
        parent=self.base/'continuations'
        parent.mkdir(mode=0o700)
        folder=parent/'0002'
        folder.mkdir(mode=0o700)
        d._write(folder/'user.md',b'Interrupted user text.')
        d._write(folder/'started.json',d._json({'actor':'user','reserved_usd':'0.2','started_at':d._now()}))
        result=self.service.history()
        self.assertEqual(result['turns'][-1]['status'],'interrupted')
        self.assertEqual(result['turns'][-1]['user'],'Interrupted user text.')
        self.assertEqual(result['summary']['held_usd'],'0.2')
        with self.assertRaisesRegex(DialogueError,'previous_turn_failed_or_interrupted'):
            self.send()
        with self.assertRaisesRegex(DialogueError,'failed_turn_not_recoverable'):
            self.service.preflight('Cannot acknowledge an interrupted request.',result['revision'],
                continue_after_failed_turn=2,max_tokens=8192)

    def test_same_lock_and_revision_prevent_overlapping_user_codex_calls(self):
        async def exercise():
            entered,release=asyncio.Event(),asyncio.Event()
            async def respond(request):
                self.requests.append(request)
                entered.set()
                await release.wait()
                return d.httpx.Response(200,json=self.payload)
            self.respond=respond
            revision=self.service.history()['revision']
            task=asyncio.create_task(self.service.send('First.',revision,actor='user'))
            await asyncio.wait_for(entered.wait(),2)
            try:
                with self.assertRaisesRegex(DialogueError,'session_locked'):
                    await self.service.send('Concurrent.',revision,actor='codex')
                with self.assertRaisesRegex(DialogueError,'session_locked'):
                    self.service.history()
            finally:
                release.set()
                await task
            with self.assertRaisesRegex(DialogueError,'revision_conflict'):
                await self.service.send('Stale.',revision,actor='codex')
        asyncio.run(exercise())
        self.assertEqual(len(self.requests),1)

    def test_changed_ancestor_history_or_receipt_chain_is_rejected(self):
        self.send('First.')
        self.send('Second.')
        folder=self.base/'continuations/0001'
        (folder/'answer.md').write_text('Edited old answer.')
        with self.assertRaisesRegex(DialogueError,'turn_artifact_changed'):
            self.service.history()

    def test_later_budget_edit_cannot_rewrite_an_existing_turn_authorization(self):
        state=self.service.history()
        self.service.set_budget('2',state['revision'])
        self.send('Authorized under two dollars.')
        path=self.base/'window/events/0001.json'
        event=json.loads(path.read_bytes())
        event['cumulative_budget_usd']='3'
        path.write_bytes(d._json(event))
        with self.assertRaisesRegex(DialogueError,'continuation_window_event_missing'):
            self.service.history()

    def test_explicit_known_cost_recovery_keeps_failed_files_and_labels_context(self):
        self.legacy('First complete question.')
        self.payload['stop_reason']='max_tokens'
        failed=self.send('Keep this failed question.')
        folder=self.base/'continuations/0002'
        frozen={p:p.read_bytes() for p in folder.iterdir()}
        revision=failed['revision']
        with self.assertRaisesRegex(DialogueError,'failed_turn_not_recoverable'):
            self.service.preflight('Wrong turn.',revision,continue_after_failed_turn=1,max_tokens=8192)
        check=self.service.preflight('Continue explicitly.',revision,continue_after_failed_turn=2,max_tokens=8192)
        self.assertTrue(check['allowed'])
        self.assertEqual(check['reservation_basis']['output_token_reservation'],8192)
        self.payload['stop_reason']='end_turn'
        recovered=asyncio.run(self.service.send('Continue explicitly.',revision,actor='codex',
            continue_after_failed_turn=2,max_tokens=8192))
        self.assertEqual([t['status'] for t in recovered['turns']],['completed','failed','completed'])
        self.assertEqual(recovered['summary']['completed_turns'],2)
        self.assertFalse(recovered['summary']['blocked'])
        self.assertEqual(recovered['summary']['held_usd'],'0')
        self.assertEqual(recovered['configuration']['max_tokens'],4096)
        self.assertEqual(recovered['turns'][-1]['max_tokens'],8192)
        self.assertEqual(recovered['turns'][-1]['continued_after_failed_turn'],2)
        self.assertEqual(Decimal(recovered['summary']['estimated_spent_usd']),Decimal('0.015306'))
        body=json.loads(self.requests[-1].content)
        self.assertEqual(body['max_tokens'],8192)
        self.assertEqual([m['role'] for m in body['messages']],['user','assistant','user','user'])
        self.assertIn('previous attempt failed',body['messages'][-2]['content'])
        self.assertIn('Keep this failed question.',body['messages'][-2]['content'])
        self.assertIn('visible_partial_answer',body['messages'][-2]['content'])
        event=json.loads((self.base/'continuations/0003/failure-recovery.json').read_bytes())
        self.assertEqual(event['failed_receipt_sha256'],d._sha(frozen[folder/'receipt.json']))
        self.assertEqual(event['max_tokens'],8192)
        self.assertEqual(event['actor'],'codex')
        self.assertEqual({p:p.read_bytes() for p in frozen},frozen)
        followed=self.send('Next regular turn.')
        self.assertEqual(followed['summary']['completed_turns'],3)
        self.assertEqual(json.loads(self.requests[-1].content)['max_tokens'],4096)
        self.assertEqual(sum('previous attempt failed' in m['content'] for m in json.loads(self.requests[-1].content)['messages']),1)
        with self.assertRaisesRegex(DialogueError,'failed_turn_not_recoverable'):
            self.service.preflight('No replay.',followed['revision'],continue_after_failed_turn=2)
        self.assertNotIn('PRIVATE_THINKING',self.stored_text())

    def test_unknown_cost_cannot_be_overridden_by_explicit_failed_turn(self):
        def timeout(request):
            self.requests.append(request)
            raise d.httpx.ReadTimeout('private failure',request=request)
        self.respond=timeout
        state=self.send()
        before={p:p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(DialogueError,'failed_turn_not_recoverable'):
            asyncio.run(self.service.send('Cannot bypass.',state['revision'],
                continue_after_failed_turn=1,max_tokens=8192))
        self.assertEqual(len(self.requests),1)
        self.assertEqual(before,{p:p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_recovery_is_still_subject_to_revision_budget_and_integer_options(self):
        self.payload['stop_reason']='max_tokens'
        failed=self.send()
        changed=self.service.set_budget('0.15',failed['revision'])
        with self.assertRaisesRegex(DialogueError,'revision_conflict'):
            self.service.preflight('Stale review.',failed['revision'],continue_after_failed_turn=1,max_tokens=8192)
        check=self.service.preflight('Continue.',changed['revision'],continue_after_failed_turn=1,max_tokens=8192)
        self.assertFalse(check['allowed'])
        self.assertEqual(check['reason'],'budget_insufficient')
        with self.assertRaisesRegex(DialogueError,'budget_insufficient'):
            asyncio.run(self.service.send('Continue.',changed['revision'],continue_after_failed_turn=1,max_tokens=8192))
        for maximum in (True,0,16001,'8192'):
            with self.subTest(maximum=maximum),self.assertRaisesRegex(DialogueError,'invalid_max_tokens'):
                self.service.preflight('Invalid.',changed['revision'],max_tokens=maximum)
        for turn in (True,0,'1'):
            with self.subTest(turn=turn),self.assertRaisesRegex(DialogueError,'invalid_failed_turn_selection'):
                self.service.preflight('Invalid.',changed['revision'],continue_after_failed_turn=turn)
        self.assertEqual(len(self.requests),1)

    def test_recovery_audit_event_is_immutable_and_bound_to_request(self):
        self.payload['stop_reason']='max_tokens'
        failed=self.send()
        self.payload['stop_reason']='end_turn'
        asyncio.run(self.service.send('Explicit continuation.',failed['revision'],
            continue_after_failed_turn=1,max_tokens=8192))
        path=self.base/'continuations/0002/failure-recovery.json'
        event=json.loads(path.read_bytes())
        event['max_tokens']=4096
        path.write_bytes(d._json(event))
        with self.assertRaisesRegex(DialogueError,'failure_recovery_changed'):
            self.service.history()


if __name__=='__main__':
    unittest.main()
