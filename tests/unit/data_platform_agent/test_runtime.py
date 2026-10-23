"""Installed-package checks of business binding and the real OpenAI Runner."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.binding import ToolBinding
from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile, validate_distinct_prompts
from uteki.data_platform.agent.providers.openrouter import configuration
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


def profile(kernel='openai'):
    root=ROOT/'config/data_platform'
    return load_profile(root/'model-profiles'/kernel/'fixture-query/query.json',config_root=root,
        kernel=kernel,model_id='fixture/'+kernel+'-query-v1',role='query')


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case=F['case']()
        self.addCleanup(self.case.doCleanups)

    async def test_committed_business_question_survives_later_native_failure(self):
        journal=RuntimeJournal(self.case.service,self.case.context,profile().metadata(),F['runtime_limits']())
        binding=ToolBinding(self.case.service,self.case.context,journal=journal)
        state=self.case.state('clarify')
        need=state['plan_update']['needs'][0]['need_id']
        response=json.loads(await binding.invoke('clarify',dict(request=dict(question='Which scope?',
            blocking_need_ids=[need]),state=state),call_id='native-question'))
        result=journal.finish(binding.outcome(native_success=False,events=[],profile=profile(),error='native cleanup failed'))
        self.assertEqual(result['kind'],'needs_clarification')
        self.assertEqual(result['clarification'],response)
        self.assertFalse(result['native_success']);self.assertEqual(result['native_error'],'native cleanup failed')
        self.assertIsNone(result['error']);self.assertTrue(result['terminal'])
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)

    async def test_durable_response_keeps_wire_aliases_and_omitted_sdk_fields(self):
        from agents import ModelResponse,Usage
        from openai.types.responses import ResponseFunctionToolCall
        from pydantic import TypeAdapter
        from uteki.data_platform.agent.metering import json_value
        original=ResponseFunctionToolCall(type='function_call',name='synthetic',arguments='{}',call_id='one',
                                         **{'async':True})
        response=ModelResponse(output=[original],usage=Usage(requests=1),response_id='one')
        saved=json_value(response)
        self.assertIn('async',saved['output'][0]);self.assertNotIn('async_',saved['output'][0])
        self.assertNotIn('status',saved['output'][0])
        restored=TypeAdapter(ModelResponse).validate_python(saved).output[0]
        self.assertEqual(restored.model_extra,{})
        self.assertEqual(restored.model_fields_set,original.model_fields_set)

    async def test_unavailable_boot_metadata_does_not_block_normal_offline_execution(self):
        with patch('uteki.data_platform.application.execution_clock.clock_domain',
                side_effect=CatalogError('RECOVERY_REQUIRED','synthetic boot metadata permission denial')):
            result=await run_offline(self.case.service,self.case.context,profile(),model=F['ScriptedModel'](),limits=F['runtime_limits']())
        self.assertEqual(result['status'],'completed',result['error'])
        clock=Session(self.case.catalog,self.case.context).data['native_execution']['execution_clock']
        self.assertIsNone(clock['domain'])
        self.assertIn('permission denial',clock['domain_unavailable'])
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],8)

    async def test_native_runner_executes_six_shared_tools_and_only_validated_delivery(self):
        model=F['ScriptedModel']()
        with patch('socket.socket.connect',side_effect=AssertionError('offline test attempted network')):
            result=await run_offline(self.case.service,self.case.context,profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual({e['tool'] for e in result['tool_events'] if e['type']=='tool_handler_return'},
            {'find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver'})
        delivery=result['delivery']['delivery']
        self.assertEqual(delivery['calculations'][0]['value'],'-2.250000000000000000')
        self.assertEqual(len(delivery['records']),2)
        self.assertEqual(self.case.service.read_delivery(self.case.context),delivery)
        self.assertTrue(any(e['type']=='observed_tool_result' for e in result['tool_events']))
        self.assertEqual(len(model.inputs),8)
        self.assertEqual(delivery['usage']['model_calls'],8)
        self.assertEqual(delivery['usage']['real_model_calls'],0)
        self.assertIsNone(delivery['usage']['cost_usd'])
        ledger=self.ledger()
        self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':8})
        self.assertEqual(len(Session(self.case.catalog,self.case.context).data['native_execution']['tool_calls']),8)
        self.assertTrue(all(r['response_event']['response']['complete'] for r in ledger.inspect_requests()))

    def ledger(self):
        native=Session(self.case.catalog,self.case.context).data['native_execution']
        context=Session(self.case.catalog,self.case.context).data['context']
        return RunBudget.open_existing(self.case.root/native['ledger_path'],'0',root_run_id=context['root_run_id'])

    async def clarified_child(self, *, limits=None):
        model=F['ScriptedModel']('clarify')
        result=await run_offline(self.case.service,self.case.context,profile(),model=model,limits=limits or F['runtime_limits']())
        self.assertEqual(result['kind'],'needs_clarification')
        self.assertEqual(len(model.inputs),1)
        request=deepcopy(self.case.request) | dict(revises_context_ref=self.case.context,
            clarification_response=dict(clarification_id=result['clarification']['clarification']['clarification_id'],answer='Use the same scope.'))
        child=self.case.service.create_context(request,request_key='answer')
        return result,child

    async def test_clarification_stops_natively_and_child_inherits_one_root_ledger(self):
        first,child=await self.clarified_child()
        parent=self.case.service.inspect_context(self.case.context)
        before=self.case.service.inspect_context(child['context_ref'])
        self.assertEqual(before['turns'],parent['turns'])
        self.assertEqual(before['wall_seconds'],parent['wall_seconds'])
        model=F['ScriptedModel']('after_clarification')
        result=await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual(len(model.inputs),8)
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],9)
        self.assertEqual(self.ledger().inspect_root()['request_stages'],{'responded':9})
        self.assertEqual(len(list((self.case.root/'runs').rglob('budget.sqlite'))),1)
        self.assertNotEqual(first['runtime']['native_session_id'],result['runtime']['native_session_id'])
        self.assertEqual(first['runtime']['root_run_id'],result['runtime']['root_run_id'])
        payload=json.loads(next(i['content'] for i in model.inputs[0] if isinstance(i,dict) and i.get('role')=='user'))
        self.assertEqual(payload['task_state']['plan'],parent['plan'])
        self.assertEqual(payload['request']['clarification_response']['answer'],'Use the same scope.')

    async def test_clarification_does_not_reset_physical_request_allowance(self):
        limits=F['runtime_limits'](max_model_requests=2)
        first,child=await self.clarified_child(limits=limits)
        model=F['ScriptedModel']('after_clarification')
        result=await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=limits)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(model.inputs),1)
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],2)
        self.assertEqual(self.ledger().inspect_root()['request_stages'],{'responded':2})

    async def test_first_sdk_execution_after_deterministic_clarification_uses_original_root_limit(self):
        request=deepcopy(self.case.request);request['run_policy']['max_usd']='3'
        root=self.case.service.create_context(request,request_key='positive-root')
        state=dict(satisfied=[],gaps=[dict(need_id='cash',missing='Explicit scope needed')],
            next_action='clarify',reason='Synthetic caller needs scope',
            plan_update=dict(base_version=0,needs=[dict(need_id='cash',description='Synthetic cash comparison and source',required=True)]))
        question=self.case.service.clarify(root['context_ref'],
            dict(question='Use this scope?',blocking_need_ids=['cash']),state=state,request_key='ask')
        answer=deepcopy(request) | dict(revises_context_ref=root['context_ref'],
            clarification_response=dict(clarification_id=question['clarification']['clarification_id'],answer='Yes, offline only.'))
        answer['run_policy']['max_usd']='0'
        child=self.case.service.create_context(answer,request_key='zero-cost-child')
        model=F['ScriptedModel']('after_clarification')
        result=await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],8)
        parent=Session(self.case.catalog,root['context_ref'])
        self.assertNotIn('native_execution',parent.data)
        ledger=RunBudget.open_existing(self.case.root/parent.data['root_budget']['ledger_path'],'3',root_run_id=root['run_id'])
        self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':8})
        self.assertEqual(len(list((self.case.root/'runs').rglob('budget.sqlite'))),1)

    async def test_child_cannot_dispatch_while_root_has_unknown_cost_or_response(self):
        first,child=await self.clarified_child()
        ledger=self.ledger()
        ledger.prepare_request('unknown-original',{'fixture':'lost response'},reserve_usd='0')
        ledger.begin_request('unknown-original');ledger.recover_requests()
        model=F['ScriptedModel']('after_clarification')
        result=await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['kind'],'recovery_required')
        self.assertEqual(model.inputs,[])
        self.assertEqual(ledger.summary()['unknown_requests'],1)

    async def test_child_cannot_expand_root_transport_limits_or_recreate_missing_ledger(self):
        first,child=await self.clarified_child()
        model=F['ScriptedModel']('after_clarification')
        with self.assertRaises(CatalogError) as caught:
            await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=F['runtime_limits'](max_model_requests=13))
        self.assertEqual(caught.exception.code,'SCOPE_VIOLATION')
        path=self.ledger().path;path.rename(path.with_suffix('.preserved'))
        with self.assertRaises((ValueError,OSError)):
            await run_offline(self.case.service,child['context_ref'],profile(),model=model,limits=F['runtime_limits']())
        self.assertFalse(path.exists());self.assertEqual(model.inputs,[])

    async def test_terminal_replay_is_same_result_without_another_model_or_tool_action(self):
        first=await run_offline(self.case.service,self.case.context,profile(),model=F['ScriptedModel'](),limits=F['runtime_limits']())
        count=len(self.case.service.inspect_context(self.case.context)['operations'])
        unused=F['ScriptedModel']()
        second=await run_offline(self.case.service,self.case.context,profile(),model=unused,limits=F['runtime_limits']())
        self.assertEqual(first,second)
        self.assertEqual(unused.inputs,[])
        self.assertEqual(len(self.case.service.inspect_context(self.case.context)['operations']),count)
        with self.assertRaises(CatalogError):
            await run_offline(self.case.service,self.case.context,profile(),model=unused,
                limits=F['runtime_limits'](max_model_requests=13))

    async def test_same_live_context_waits_for_one_execution(self):
        entered,release=asyncio.Event(),asyncio.Event()
        class Delayed(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                if not self.inputs:
                    entered.set();await release.wait()
                return await super().get_response(*args,**kwargs)
        first_model=Delayed();unused=F['ScriptedModel']()
        first=asyncio.create_task(run_offline(self.case.service,self.case.context,profile(),
            model=first_model,limits=F['runtime_limits']()))
        await asyncio.wait_for(entered.wait(),5)
        second=asyncio.create_task(run_offline(self.case.service,self.case.context,profile(),
            model=unused,limits=F['runtime_limits']()))
        await asyncio.sleep(0)
        release.set()
        a,b=await asyncio.gather(first,second)
        self.assertEqual(a,b)
        self.assertEqual(len(first_model.inputs),8)
        self.assertEqual(unused.inputs,[])

    async def test_physical_request_limit_blocks_before_second_model_invocation(self):
        model=F['ScriptedModel']()
        result=await run_offline(self.case.service,self.case.context,profile(),model=model,
            limits=F['runtime_limits'](max_model_requests=1))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['kind'],'delivery')
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'model_budget')
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],1)
        self.assertEqual(len(model.inputs),1)
        self.assertEqual(self.ledger().inspect_root()['request_stages'],{'responded':1})

    async def test_cancel_inflight_model_preserves_unknown_response_and_does_not_run_tool(self):
        entered=asyncio.Event()
        class Waiting(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                entered.set()
                await asyncio.Event().wait()
        task=asyncio.create_task(run_offline(self.case.service,self.case.context,profile(),
            model=Waiting(),limits=F['runtime_limits']()))
        await asyncio.wait_for(entered.wait(),5)
        task.cancel()
        result=await asyncio.wait_for(task,5)
        self.assertIsNone(result['error'])
        self.assertEqual(result['native_error'],'CANCELLED')
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['delivery']['delivery']['needs'][0]['status'],'unresolved')
        inspected=self.case.service.inspect_context(self.case.context)
        self.assertEqual(inspected['turns'],0)
        self.assertEqual({o['tool'] for o in inspected['operations'].values()},{'deliver'})
        self.assertEqual(result['delivery']['delivery']['usage']['unknown_requests'],1)
        saved=self.ledger().inspect_requests()
        self.assertEqual(len(saved),1)
        self.assertEqual(saved[0]['cost_state'],'unknown')
        self.assertFalse(saved[0]['response_event']['response']['complete'])
        self.assertEqual(self.ledger().inspect_root()['stop_reason'],'cancelled')

    async def test_native_turn_limit_forces_partial_without_another_call(self):
        model=F['ScriptedModel']()
        result=await run_offline(self.case.service,self.case.context,profile(),model=model,
                                limits=F['runtime_limits'](native_max_turns=1))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'native_max_turns')
        self.assertEqual(len(model.inputs),1)

    async def test_business_turn_and_no_progress_stops_preserve_last_state(self):
        # New discovery metadata is progress; only the identical repeat counts toward no_progress.
        for policy,reason,scenario,turns in [('max_turns','max_turns','success',1),
                                             ('max_no_progress_turns','no_progress','repeat_discovery',2)]:
            with self.subTest(policy=policy):
                request=deepcopy(self.case.request)
                request['run_policy'][policy]=1
                context=self.case.service.create_context(request,request_key=policy)['context_ref']
                model=F['ScriptedModel'](scenario)
                result=await run_offline(self.case.service,context,profile(),model=model,limits=F['runtime_limits']())
                self.assertEqual(result['status'],'partial')
                self.assertEqual(result['delivery']['delivery']['stop_reason'],reason)
                self.assertEqual(len(model.inputs),turns)
                self.assertEqual(self.case.service.inspect_context(context)['turns'],turns)

    async def test_wall_deadline_does_not_request_a_model_written_summary(self):
        request=deepcopy(self.case.request)
        request['run_policy']['max_wall_seconds']=1
        context=self.case.service.create_context(request,request_key='deadline')['context_ref']
        class Slow(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                self.inputs.append('entered')
                await asyncio.sleep(10)
                raise AssertionError('deadline did not interrupt the synthetic response')
        model=Slow()
        result=await run_offline(self.case.service,context,profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'wall_time')
        self.assertEqual(result['delivery']['delivery']['usage']['unknown_requests'],1)
        self.assertEqual(model.inputs,['entered'])
        self.assertEqual(self.case.service.inspect_context(context)['turns'],0)

    async def test_request_and_response_byte_bounds_are_enforced_without_extra_calls(self):
        for field,calls in [('max_request_bytes',0),('max_response_bytes',1)]:
            c=F['case']()
            try:
                model=F['ScriptedModel']()
                result=await run_offline(c.service,c.context,profile(),model=model,
                    limits=F['runtime_limits'](**{field:1}))
                self.assertEqual(result['status'],'failed')
                self.assertEqual(len(model.inputs),calls)
                self.assertFalse(c.service.inspect_context(c.context)['operations'])
            finally:c.doCleanups()

    async def test_native_tool_identity_replay_and_conflict_do_not_duplicate_business_action(self):
        journal=RuntimeJournal(self.case.service,self.case.context,profile().metadata(),F['runtime_limits']())
        binding=ToolBinding(self.case.service,self.case.context,journal=journal)
        args=dict(request=dict(filters={}),state=self.case.state('find_assets'))
        first=await binding.invoke('find_assets',args,call_id='native-tool-one')
        second=await binding.invoke('find_assets',args,call_id='native-tool-one')
        self.assertEqual(first,second)
        changed=deepcopy(args);changed['request']['limit']=3
        conflict=json.loads(await binding.invoke('find_assets',changed,call_id='native-tool-one'))
        self.assertEqual(conflict['error']['code'],'IDEMPOTENCY_CONFLICT')
        self.assertEqual(len(self.case.service.inspect_context(self.case.context)['operations']),1)

    async def test_missing_completed_ledger_is_not_silently_recreated_for_replay(self):
        await run_offline(self.case.service,self.case.context,profile(),model=F['ScriptedModel']('free_text'),limits=F['runtime_limits']())
        path=self.ledger().path
        path.rename(path.with_suffix('.preserved'))
        unused=F['ScriptedModel']()
        with self.assertRaises((OSError,ValueError)):
            await run_offline(self.case.service,self.case.context,profile(),model=unused,limits=F['runtime_limits']())
        self.assertFalse(path.exists())
        self.assertEqual(unused.inputs,[])

    async def test_invalid_arguments_tool_error_forged_delivery_and_free_text_fail(self):
        for scenario in ['invalid_arguments','tool_error','forged_delivery','free_text']:
            with self.subTest(scenario=scenario):
                c=F['case']()
                try:
                    result=await run_offline(c.service,c.context,profile(),model=F['ScriptedModel'](scenario),limits=F['runtime_limits'](native_max_turns=3))
                    self.assertEqual(result['status'],'failed',result)
                    self.assertIsNone(result['delivery'])
                    self.assertIsNone(c.service.inspect_context(c.context)['delivery'])
                    if scenario != 'free_text':
                        returned=[e for e in result['tool_events'] if e['type']=='tool_handler_return']
                        if scenario=='tool_error':
                            self.assertEqual(returned[0]['output']['status'],'ok')
                            self.assertEqual(returned[1]['output']['status'],'error')
                            self.assertNotEqual(returned[1]['output']['error']['code'],'INVALID_REQUEST')
                        else:
                            expected='RESULT_REF_INVALID' if scenario=='forged_delivery' else 'INVALID_REQUEST'
                            self.assertEqual(returned[0]['output']['error']['code'],expected)
                finally:
                    c.doCleanups()

    async def test_handler_only_or_truncated_evidence_cannot_be_used_in_state(self):
        binding=ToolBinding(self.case.service,self.case.context)
        block=next(b for b in self.case.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        args=dict(request=dict(asset_ref=self.case.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])]),state=self.case.state('read_evidence'))
        raw=await binding.invoke('read_evidence',args)
        response=json.loads(raw)
        ref=response['items'][0]['result_ref']
        request=dict(request=dict(needs=[dict(need_id='need-1',status='supported',result_refs=[ref],gaps=[])]),state=self.case.state('deliver',[ref],supported=True))
        binding.observe(raw[:100],boundary='synthetic_truncated_message')
        self.assertEqual(json.loads(await binding.invoke('deliver',request))['error']['code'],'RESULT_REF_INVALID')
        binding.observe(raw,boundary='synthetic_full_message')
        self.assertEqual(json.loads(await binding.invoke('deliver',request))['kind'],'delivery')

    async def test_model_injection_must_be_explicitly_offline(self):
        model=F['ScriptedModel']();model.offline_fixture=False
        with self.assertRaisesRegex(ValueError,'scripted'):
            await run_offline(self.case.service,self.case.context,profile(),model=model,limits=F['runtime_limits'](native_max_turns=2))


class ProfileTests(unittest.TestCase):
    def test_unverified_capabilities_sdk_versions_and_reused_prompt_fail(self):
        for update in [dict(capabilities=()),dict(sdk_version='0.0.0'),dict(status='unverified'),dict(reasoning_effort='high')]:
            p=profile();p.profile=p.profile.model_copy(update=update)
            with self.assertRaises(ValueError):p.validate(kernel='openai')
        a,b=profile('openai'),profile('claude')
        b.profile=b.profile.model_copy(update={'prompt':a.profile.prompt})
        b.text=a.text
        with self.assertRaisesRegex(ValueError,'separate prompt'):
            validate_distinct_prompts([a,b])

    def test_profiles_and_explicit_route_are_distinct_and_offline(self):
        profiles=[profile(k) for k in ['openai','claude']]
        validate_distinct_prompts(profiles)
        for p in profiles:
            p.validate(kernel=p.profile.kernel)
            route=configuration(p)
            self.assertFalse(route['routing']['allow_fallbacks'])
            self.assertTrue(route['routing']['require_parameters'])
            with self.assertRaises(ValueError):p.validate(kernel=p.profile.kernel,mode='live')

    def test_wrong_model_role_changed_prompt_or_escape_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work);text='An explicit synthetic prompt.'
            (root/'prompt.md').write_text(text)
            data=profile().metadata();data['prompt'].update(path='prompt.md',sha256=hashlib.sha256(text.encode()).hexdigest())
            path=root/'profile.json';path.write_text(json.dumps(data))
            def load(**updates):
                return load_profile(path,config_root=root,**(dict(kernel='openai',model_id=data['model_id'],role='query')|updates))
            load()
            for change in [dict(model_id='fixture/another'),dict(role='plan'),dict(kernel='claude')]:
                with self.assertRaises(ValueError):load(**change)
            (root/'prompt.md').write_text('Modified without a new hash')
            with self.assertRaises(ValueError):load()
            data['prompt']['path']='../outside.md';path.write_text(json.dumps(data))
            with self.assertRaises((ValueError,FileNotFoundError)):load()


if __name__=='__main__':unittest.main()
