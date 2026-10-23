"""An authorized cumulative increase retains old costs, stops and results."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import unittest

from uteki.data_platform.application.gateway_batch import create_gateway_batch, load_gateway_binding, prepare_gateway_attempt
from uteki.data_platform.application.gateway_extension import extend_gateway_batch
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.run_completion import read_result
from uteki.data_platform.application.session import Session
from uteki.data_platform.agent.providers.openrouter_evidence import capture_response, record_response
from uteki.data_platform.contracts.common import CatalogError, canonical, digest
from uteki.infrastructure.run_budget import BudgetExceeded, RequestRecoveryRequired

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayExtensionTests(unittest.TestCase):
    def setup_case(self,origin='synthetic'):
        case=F['F']['case']();self.addCleanup(case.doCleanups)
        scopes=[]
        for kernel in ('openai','claude'):
            request=deepcopy(case.request);request['run_policy']['max_usd']='1'
            ref=case.service.create_context(request,request_key='extension-'+kernel)['context_ref']
            scopes.append(dict(scope_id=kernel,context_ref=ref,profile=F['profile'](kernel).metadata(),
                limits=dict(native_max_turns=3,max_model_requests=3,max_request_bytes=200000,max_response_bytes=1000000),
                transport=dict(max_request_bytes=200000,max_response_bytes=1000000,request_timeout_seconds=10,reserve_usd='.8')))
        contract=dict(limit_usd='1',max_requests=6,scopes={s['scope_id']:dict(profile=s['profile'],transport=s['transport'],max_requests=3) for s in scopes})
        bindings=create_gateway_batch(case.catalog,batch_id='00000000-0000-4000-8000-000000000001',scopes=scopes,
            limit_usd='1',max_requests=6,origin=origin,contract_sha256=digest(canonical(contract)))
        old=scopes[0];binding=bindings[old['scope_id']]
        budget=load_gateway_binding(Session(case.catalog,old['context_ref']),binding,old['profile'],old['limits'])['budget']
        auth=dict(authorized_by='user',authorization_id='synthetic-extension',confirmation='Synthetic user approval',scope='same batch',
            old_limit_usd='1',new_limit_usd='3',old_max_requests=6,new_max_requests=12,new_scope_requests={'openai':6,'claude':6})
        args=dict(catalog=case.catalog,base_ref=binding['batch_ref'],profiles={s['scope_id']:s['profile'] for s in scopes},contract=contract,authorization=auth)
        return case,scopes,bindings,budget,args

    def recorded(self,budget,scope,key,known):
        budget.prepare_request(key,dict(context_ref=scope['context_ref']),reserve_usd='.2',scope_id=scope['scope_id'])
        budget.begin_request(key)
        payload=dict(id='gen-synthetic-'+key,object='chat.completion',choices=[dict(finish_reason='stop')],usage={'cost':.02} if known else {})
        record_response(budget,key,capture_response('chat_completions',200,[('Content-Type','application/json')],
            [json.dumps(payload).encode()],max_bytes=10000),origin='synthetic')
        if not known:budget.retain_response_reservation(key,confirmation='Retain the full synthetic reservation')

    def test_extension_keeps_history_and_supports_a_new_native_binding(self):
        case,scopes,bindings,budget,args=self.setup_case(origin='live');old=scopes[0]
        journal=RuntimeJournal(case.service,old['context_ref'],old['profile'],old['limits'],gateway_binding=bindings['openai'])
        self.recorded(budget,old,'billed',True);self.recorded(budget,scopes[1],'held',False)
        result=journal.finish(dict(kind='failed',status='failed',error='synthetic prior failure',native_success=False,
            delivery=None,committed_delivery=None,clarification=None,committed_clarification=None,
            native_events=[],tool_events=[],profile=old['profile'],mode='offline',real_model_calls=0,gateway_cost_usd=None))
        before=budget.inspect_requests();budget.stop_scope('claude','native_max_turns')
        revised=extend_gateway_batch(**args)
        self.assertEqual(revised,extend_gateway_batch(**args))
        self.assertEqual(budget.inspect_requests(),before)
        self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'2.78')
        self.assertEqual(budget.inspect_scope('claude')['request_stages'],{'responded':1})
        self.assertIsNone(budget.inspect_scope('claude')['stop_reason'])
        self.assertEqual(read_result(Session(case.catalog,old['context_ref'])),result)
        load_gateway_binding(Session(case.catalog,old['context_ref']),bindings['openai'],old['profile'],old['limits'])
        with self.assertRaises(CatalogError):prepare_gateway_attempt(case.catalog,bindings['openai'],old['profile'],request_key='stale')
        new=revised['scopes'][0]
        journal=RuntimeJournal(case.service,new['context_ref'],new['profile'],new['limits'],gateway_binding=revised['bindings'][new['scope_id']])
        self.assertEqual(journal.budget.inspect_root()['limit_usd'],'3')
        self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)
        for i in range(5):self.recorded(budget,new,'new-'+str(i),True)
        with self.assertRaises(BudgetExceeded):
            budget.prepare_request('seventh',{'context_ref':new['context_ref']},reserve_usd='.01',scope_id=new['scope_id'])
        self.assertEqual(budget.inspect_scope(new['scope_id'])['request_stages'],{'responded':6})
        outcome={k:result[k] for k in ('kind','status','error','native_success','delivery','committed_delivery',
            'clarification','committed_clarification','native_events','tool_events','mode','real_model_calls','gateway_cost_usd')}
        current=journal.finish(outcome | {'profile':new['profile']})
        self.assertEqual(current['real_model_calls'],5)  # Synthetic receipts; no external model was called.
        self.assertEqual(current['gateway_cost_usd'],'0.10')

    def test_interruption_repeats_the_exact_revision_without_resetting_cost(self):
        for phase in ('allowance_intent_saved','allowance_committed'):
            with self.subTest(phase=phase):
                case,scopes,bindings,budget,args=self.setup_case();self.recorded(budget,scopes[0],'billed',True)
                before=budget.inspect_requests()
                def stop(at):
                    if at==phase:raise RuntimeError('controlled interruption')
                with self.assertRaises(RuntimeError):extend_gateway_batch(**args,checkpoint=stop)
                revised=extend_gateway_batch(**args)
                self.assertEqual(budget.inspect_requests(),before)
                self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'2.98')
                self.assertEqual(revised,extend_gateway_batch(**args))

    def test_unknown_transport_or_cancellation_is_not_reopened(self):
        for reason in ('pending','cancelled'):
            with self.subTest(reason=reason):
                case,scopes,bindings,budget,args=self.setup_case()
                if reason=='pending':
                    budget.prepare_request('pending',{'context_ref':scopes[0]['context_ref']},reserve_usd='.2',scope_id='openai')
                    budget.begin_request('pending')
                else:budget.stop_scope('claude','cancelled')
                before=budget.inspect_root()
                with self.assertRaises((ValueError,RequestRecoveryRequired,BudgetExceeded)):
                    extend_gateway_batch(**args)
                self.assertEqual(budget.inspect_root(),before)

    def test_profile_and_authorization_changes_do_not_expand_allowance(self):
        case,scopes,bindings,budget,args=self.setup_case();before=budget.inspect_root()
        wrong=deepcopy(args['authorization']);wrong['authorized_by']='model'
        with self.assertRaises(ValueError):extend_gateway_batch(**(args | {'authorization':wrong}))
        self.assertEqual(budget.inspect_root(),before)
        args['authorization']['authorization_id']='different-profile'
        args['profiles']['openai']['model_id']='a-different-model'
        with self.assertRaises(ValueError):extend_gateway_batch(**args)
        self.assertEqual(budget.inspect_root(),before)

    def test_explicit_skill_revision_keeps_money_history_and_old_binding(self):
        case,scopes,bindings,budget,args=self.setup_case()
        self.recorded(budget,scopes[0],'previous',True)
        before=budget.inspect_requests()
        old=deepcopy(args['profiles']['openai'])
        current=deepcopy(old)
        current['skills']=['financial-data-query']
        current['prompt']=F['profile']('openai',skills=True).metadata()['prompt']
        args['profiles']['openai']=current
        args['authorization'].update(new_limit_usd='1',profile_revisions={'openai':dict(
            previous_sha256=digest(canonical(old)),current_sha256=digest(canonical(current)))})
        revised=extend_gateway_batch(**args)
        self.assertEqual(revised,extend_gateway_batch(**args))
        self.assertEqual(budget.inspect_root()['limit_usd'],'1')
        self.assertEqual(budget.inspect_requests(),before)
        self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'0.98')
        new=next(s for s in revised['scopes'] if s['scope_id']=='openai')
        self.assertEqual(new['profile'],current)
        load_gateway_binding(Session(case.catalog,new['context_ref']),revised['bindings']['openai'],current,new['limits'])
        load_gateway_binding(Session(case.catalog,scopes[0]['context_ref']),bindings['openai'],old,scopes[0]['limits'])
        self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)

    def test_guidance_revision_cannot_change_model_or_use_wrong_fingerprints(self):
        for change in ('unapproved','fingerprint','model','reduced_money'):
            with self.subTest(change=change):
                case,scopes,bindings,budget,args=self.setup_case()
                old=deepcopy(args['profiles']['openai']);current=deepcopy(old)
                current['skills']=['financial-data-query']
                if change=='model':current['model_id']='different-model'
                args['profiles']['openai']=current
                if change!='unapproved':
                    args['authorization']['profile_revisions']={'openai':dict(
                        previous_sha256=digest(canonical(old)),current_sha256=digest(canonical(current)))}
                if change=='fingerprint':
                    args['authorization']['profile_revisions']['openai']['current_sha256']='0'*64
                if change=='reduced_money':args['authorization']['new_limit_usd']='0.9'
                before=budget.inspect_root()
                with self.assertRaises(ValueError):extend_gateway_batch(**args)
                self.assertEqual(budget.inspect_root(),before)

    def comparison_args(self,args,scopes):
        profile=deepcopy(scopes[0]['profile']);profile['model_id']='synthetic-comparison-model'
        addition=dict(scope_id='comparison',source_scope_id='openai',profile=profile,
            limits=deepcopy(scopes[0]['limits']),transport=deepcopy(scopes[0]['transport']),
            pricing=dict(currency='USD',input_per_million='1',output_per_million='2',source='synthetic',observed_at='synthetic'))
        args['additional_scopes']=[addition]
        args['authorization'].update(new_scope_requests={'openai':3,'claude':3,'comparison':3},
            new_scope_ids=['comparison'],additional_scopes_sha256=digest(canonical([addition])))

    def test_new_model_scope_shares_history_money_and_business_input(self):
        for interruption in (None,'allowance_intent_saved','allowance_committed'):
            with self.subTest(interruption=interruption):
                case,scopes,bindings,budget,args=self.setup_case()
                self.recorded(budget,scopes[0],'old',True)
                before=budget.inspect_requests();self.comparison_args(args,scopes)
                if interruption:
                    def stop(phase):
                        if phase==interruption:raise RuntimeError('controlled interruption')
                    with self.assertRaises(RuntimeError):extend_gateway_batch(**args,checkpoint=stop)
                revised=extend_gateway_batch(**args)
                self.assertEqual(revised,extend_gateway_batch(**args))
                self.assertEqual(budget.inspect_requests(),before)
                self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)
                new=next(s for s in revised['scopes'] if s['scope_id']=='comparison')
                new_session=Session(case.catalog,new['context_ref'])
                old_request=deepcopy(Session(case.catalog,scopes[0]['context_ref']).data['context']['request'])
                old_request['run_policy']['max_usd']='3'
                self.assertEqual(new_session.data['context']['request'],old_request)
                load_gateway_binding(new_session,revised['bindings']['comparison'],new['profile'],new['limits'])
                load_gateway_binding(Session(case.catalog,scopes[0]['context_ref']),bindings['openai'],scopes[0]['profile'],scopes[0]['limits'])
                self.recorded(budget,new,'new',True)
                self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'2.96')
                self.assertEqual(budget.inspect_scope('openai')['request_stages'],{'responded':1})
                self.assertEqual(budget.inspect_scope('comparison')['request_stages'],{'responded':1})

    def test_new_explicit_input_and_additional_cost_ceiling_share_original_ledger(self):
        case,scopes,bindings,budget,args=self.setup_case()
        self.recorded(budget,scopes[0],'historical',True)
        before=budget.inspect_requests()
        self.comparison_args(args,scopes)
        request=deepcopy(case.request)
        request['question']='Different explicitly authorized source question'
        ref=case.service.create_context(request,request_key='new-input')['context_ref']
        item=args['additional_scopes'][0]
        item.pop('source_scope_id');item['context_ref']=ref
        args['authorization'].update(additional_scopes_sha256=digest(canonical(args['additional_scopes'])),additional_limit_usd='.25')
        args['authorization'].update(preserve_existing_scopes=True,new_limit_usd='1',new_max_requests=6)
        budget.stop_scope('claude','no_progress')
        revised=extend_gateway_batch(**args)
        new=next(s for s in revised['scopes'] if s['scope_id']=='comparison')
        self.assertEqual(Session(case.catalog,new['context_ref']).data['context']['request']['question'],request['question'])
        self.assertEqual(budget.inspect_requests(),before)
        self.assertEqual(budget.inspect_scope('claude')['stop_reason'],'no_progress')
        self.assertEqual(budget.inspect_root()['max_requests'],6)
        self.recorded(budget,new,'new-held',False)
        with self.assertRaises(BudgetExceeded):
            budget.prepare_request('over-additional-limit',{'context_ref':new['context_ref']},reserve_usd='.06',scope_id='comparison')
        self.assertEqual(budget.inspect_scope('comparison')['request_stages'],{'responded':1})
        self.assertEqual(revised,extend_gateway_batch(**args))
        self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)

    def test_new_scope_requires_matching_authorization_and_cannot_remove_history(self):
        for change in ('missing_authorization','changed_model','reused_scope','cancelled'):
            with self.subTest(change=change):
                case,scopes,bindings,budget,args=self.setup_case();self.comparison_args(args,scopes)
                if change=='missing_authorization':args['authorization'].pop('new_scope_ids')
                if change=='changed_model':args['additional_scopes'][0]['profile']['model_id']='unapproved'
                if change=='reused_scope':args['additional_scopes'][0]['scope_id']='openai'
                if change=='cancelled':budget.stop_scope('openai','cancelled')
                before=budget.inspect_root()
                with self.assertRaises((ValueError,BudgetExceeded)):extend_gateway_batch(**args)
                self.assertEqual(budget.inspect_root(),before)

    def test_money_only_revision_preserves_sessions_requests_stops_and_full_reservations(self):
        for interruption in (None,'allowance_intent_saved','allowance_committed'):
            with self.subTest(interruption=interruption):
                case,scopes,bindings,budget,args=self.setup_case()
                self.recorded(budget,scopes[0],'historical',True)
                self.comparison_args(args,scopes)
                args['authorization'].update(preserve_existing_scopes=True,new_limit_usd='1',
                    new_max_requests=6,additional_limit_usd='.25')
                budget.stop_scope('claude','no_progress')
                first=extend_gateway_batch(**args)
                new=next(s for s in first['scopes'] if s['scope_id']=='comparison')
                self.recorded(budget,new,'full-held',False)
                before=budget.inspect_requests()
                heads={s['context_ref']:Session(case.catalog,s['context_ref']).head_ref for s in first['scopes']}
                auth=dict(authorized_by='user',authorization_id='money-only',confirmation='Synthetic monetary approval',
                    scope='same questions and request limits',old_limit_usd='1',new_limit_usd='3',
                    old_max_requests=6,new_max_requests=6,new_scope_requests={s['scope_id']:3 for s in first['scopes']},
                    preserve_existing_scopes=True,spending_limit_revisions=[dict(scope_ids=['comparison'],old_limit_usd='0.25',new_limit_usd='.5')])
                update=dict(catalog=case.catalog,base_ref=first['bindings']['openai']['batch_ref'],
                    profiles={s['scope_id']:s['profile'] for s in first['scopes']},contract=first['contract'],authorization=auth)
                wrong=deepcopy(auth);wrong['spending_limit_revisions'][0]['old_limit_usd']='.3'
                with self.assertRaises(ValueError):extend_gateway_batch(**(update|{'authorization':wrong}))
                wrong=deepcopy(auth);wrong['new_scope_requests']['openai']=4
                with self.assertRaises(ValueError):extend_gateway_batch(**(update|{'authorization':wrong}))
                self.assertEqual(budget.inspect_root()['limit_usd'],'1')
                if interruption:
                    def stop(phase):
                        if phase==interruption:raise RuntimeError('controlled interruption')
                    with self.assertRaises(RuntimeError):extend_gateway_batch(**update,checkpoint=stop)
                revised=extend_gateway_batch(**update)
                self.assertEqual(revised,extend_gateway_batch(**update))
                self.assertEqual(revised['scopes'],first['scopes'])
                self.assertEqual(budget.inspect_requests(),before)
                self.assertEqual(budget.inspect_scope('claude')['stop_reason'],'no_progress')
                self.assertEqual(budget.inspect_root()['max_requests'],6)
                self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'2.78')
                self.assertEqual(budget.inspect_request('full-held')['reserved_usd'],'0.2')
                self.assertEqual({ref:Session(case.catalog,ref).head_ref for ref in heads},heads)
                self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)
                load_gateway_binding(Session(case.catalog,new['context_ref']),revised['bindings']['comparison'],new['profile'],new['limits'])
                budget.prepare_request('higher-bill',{'context_ref':scopes[0]['context_ref']},reserve_usd='.8',scope_id='openai')
                budget.begin_request('higher-bill')
                payload=dict(id='gen-synthetic-higher-bill',object='chat.completion',choices=[dict(finish_reason='stop')],usage={'cost':1.1})
                record_response(budget,'higher-bill',capture_response('chat_completions',200,[('Content-Type','application/json')],
                    [json.dumps(payload).encode()],max_bytes=10000),origin='synthetic')
                with self.assertRaises(BudgetExceeded):
                    budget.prepare_request('still-over-group',{'context_ref':new['context_ref']},reserve_usd='.31',scope_id='comparison')
                budget.prepare_request('newly-admitted',{'context_ref':new['context_ref']},reserve_usd='.3',scope_id='comparison')

    def test_add_comparison_after_money_revision_preserves_old_contexts_and_costs(self):
        case,scopes,bindings,budget,args=self.setup_case()
        self.recorded(budget,scopes[0],'billed-before',True)
        self.recorded(budget,scopes[0],'held-before',False)
        budget.stop_scope('claude','no_progress')
        args['authorization'].update(preserve_existing_scopes=True,new_max_requests=6,
            new_scope_requests={'openai':3,'claude':3})
        first=extend_gateway_batch(**args)
        before=budget.inspect_requests()
        heads={s['context_ref']:Session(case.catalog,s['context_ref']).head_ref for s in scopes}
        update=dict(catalog=case.catalog,base_ref=first['bindings']['openai']['batch_ref'],
            profiles={s['scope_id']:s['profile'] for s in first['scopes']},
            contract=first['contract'],authorization=deepcopy(args['authorization']))
        self.comparison_args(update,scopes)
        update['authorization'].update(authorization_id='comparison-after-money',old_limit_usd='3',
            new_max_requests=9,additional_limit_usd='.5')
        wrong=deepcopy(update['authorization'])
        wrong.update(authorization_id='excess-comparison-requests',new_max_requests=10)
        root_before=budget.inspect_root()
        with self.assertRaises(ValueError):
            extend_gateway_batch(**(update | {'authorization':wrong}))
        self.assertEqual(budget.inspect_root(),root_before)
        revised=extend_gateway_batch(**update)
        self.assertEqual(revised,extend_gateway_batch(**update))
        self.assertEqual(budget.inspect_requests(),before)
        self.assertEqual(budget.inspect_root()['cost']['remaining_usd'],'2.78')
        self.assertEqual(budget.inspect_scope('claude')['stop_reason'],'no_progress')
        for old in scopes:
            session=Session(case.catalog,old['context_ref'])
            self.assertEqual(session.head_ref,heads[old['context_ref']])
            self.assertEqual(session.data['context']['request']['run_policy']['max_usd'],'1')
            load_gateway_binding(session,revised['bindings'][old['scope_id']],old['profile'],old['limits'])
        new=next(s for s in revised['scopes'] if s['scope_id']=='comparison')
        self.assertEqual(Session(case.catalog,new['context_ref']).data['context']['request']['run_policy']['max_usd'],'3')
        self.recorded(budget,new,'new-held',False)
        with self.assertRaises(BudgetExceeded):
            budget.prepare_request('above-group',{'context_ref':new['context_ref']},reserve_usd='.31',scope_id='comparison')
        self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)

    def test_unstarted_runtime_uses_explicitly_revised_pool_without_rewriting_its_context(self):
        case,scopes,bindings,budget,args=self.setup_case()
        args['authorization'].update(preserve_existing_scopes=True,new_max_requests=6,
            new_scope_requests={'openai':3,'claude':3})
        old=deepcopy(Session(case.catalog,scopes[1]['context_ref']).data['context'])
        revised=extend_gateway_batch(**args)
        journal=RuntimeJournal(case.service,scopes[1]['context_ref'],scopes[1]['profile'],scopes[1]['limits'],
            gateway_binding=revised['bindings']['claude'])
        budget.prepare_request('higher-bill',{'context_ref':scopes[0]['context_ref']},reserve_usd='.8',scope_id='openai')
        budget.begin_request('higher-bill')
        payload=dict(id='gen-synthetic-higher-bill',object='chat.completion',choices=[dict(finish_reason='stop')],usage={'cost':1.1})
        record_response(budget,'higher-bill',capture_response('chat_completions',200,[('Content-Type','application/json')],
            [json.dumps(payload).encode()],max_bytes=10000),origin='synthetic')
        journal.guard_action()  # Old context ceiling is 1; authorized shared pool is now 3.
        self.assertEqual(Session(case.catalog,scopes[1]['context_ref']).data['context'],old)
        self.assertIsNone(budget.inspect_scope('claude')['stop_reason'])

    def test_selected_request_extension_preserves_other_stops_and_history(self):
        for interruption in (None,'allowance_intent_saved','allowance_committed'):
            with self.subTest(interruption=interruption):
                case,scopes,bindings,budget,args=self.setup_case()
                for i in range(3):self.recorded(budget,scopes[0],f'old-{i}',False)
                budget.stop_scope('openai','native_max_turns');budget.stop_scope('claude','no_progress')
                before=budget.inspect_requests()
                heads={s['context_ref']:Session(case.catalog,s['context_ref']).head_ref for s in scopes}
                args['authorization'].update(preserve_existing_scopes=True,new_limit_usd='1',new_max_requests=9,
                    new_scope_requests={'openai':6,'claude':3},
                    request_limit_revisions={'openai':dict(old_max_requests=3,new_max_requests=6)})
                if interruption:
                    def stop(phase):
                        if phase==interruption:raise RuntimeError('controlled interruption')
                    with self.assertRaises(RuntimeError):extend_gateway_batch(**args,checkpoint=stop)
                revised=extend_gateway_batch(**args)
                self.assertEqual(revised,extend_gateway_batch(**args))
                self.assertEqual(budget.inspect_requests(),before)
                self.assertEqual(budget.inspect_scope('claude')['stop_reason'],'no_progress')
                self.assertIsNone(budget.inspect_scope('openai')['stop_reason'])
                self.assertEqual({ref:Session(case.catalog,ref).head_ref for ref in heads},heads)
                new=next(s for s in revised['scopes'] if s['scope_id']=='openai')
                attempt=prepare_gateway_attempt(case.catalog,revised['bindings']['openai'],new['profile'],request_key='fresh')
                self.assertNotEqual(attempt['context_ref'],new['context_ref'])
                load_gateway_binding(Session(case.catalog,attempt['context_ref']),attempt['binding'],new['profile'],new['limits'])
                for i in range(3):self.recorded(budget,new,f'new-{i}',True)
                with self.assertRaises(BudgetExceeded):budget.prepare_request('seventh',{'context_ref':attempt['context_ref']},reserve_usd='.01',scope_id='openai')

    def test_selected_request_extension_rejects_mismatched_caps_and_other_stops(self):
        for bad in ('root_count','old_count','unlisted_lane','cancelled'):
            with self.subTest(bad=bad):
                case,scopes,bindings,budget,args=self.setup_case()
                args['authorization'].update(preserve_existing_scopes=True,new_limit_usd='1',new_max_requests=9,
                    new_scope_requests={'openai':6,'claude':3},
                    request_limit_revisions={'openai':dict(old_max_requests=3,new_max_requests=6)})
                if bad=='root_count':args['authorization']['new_max_requests']=10
                if bad=='old_count':args['authorization']['request_limit_revisions']['openai']['old_max_requests']=2
                if bad=='unlisted_lane':args['authorization']['new_scope_requests']['claude']=6
                if bad=='cancelled':budget.stop_scope('openai','cancelled')
                before=budget.inspect_root()
                with self.assertRaises(ValueError):extend_gateway_batch(**args)
                self.assertEqual(budget.inspect_root(),before)

    def test_observed_failed_worker_does_not_block_independent_comparison(self):
        for invalid in (None,'missing_exit','live_group','pending_operation','active_recovery'):
            with self.subTest(invalid=invalid):
                case,scopes,bindings,budget,args=self.setup_case();self.comparison_args(args,scopes)
                session=Session(case.catalog,scopes[0]['context_ref'])
                native=dict(phase='recovery_required',outcome={'status':'failed'},owner_pid=123,
                    native_session_id='synthetic-old-session',execution_clock={'domain':'previous-boot','started_monotonic':2})
                observation=dict(schema_version='uteki-observed-exit-v1',context_ref=scopes[0]['context_ref'],
                    native_session_id=native['native_session_id'],owner_pid=123,clock=native['execution_clock'],
                    clock_domain='previous-boot',process_group_empty=invalid!='live_group',returncode=0,
                    launched_monotonic=1,exited_monotonic=3)
                if invalid!='missing_exit':native['exit_observation']=case.catalog.content.put_object(canonical(observation)).model_dump(mode='json')
                if invalid=='active_recovery':native['recovery_attempts']=[{'status':'active'}]
                session.data['native_execution']=native
                if invalid=='pending_operation':session.data['operations']['pending']={'status':'accepted'}
                session.save();before=session.head_ref
                if invalid:
                    with self.assertRaises(CatalogError):extend_gateway_batch(**args)
                else:
                    revised=extend_gateway_batch(**args)
                    self.assertIn('comparison',revised['bindings'])
                self.assertEqual(Session(case.catalog,scopes[0]['context_ref']).head_ref,before)
