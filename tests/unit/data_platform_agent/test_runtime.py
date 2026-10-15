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

    async def test_native_runner_executes_six_shared_tools_and_only_validated_delivery(self):
        model=F['ScriptedModel']()
        with patch('socket.socket.connect',side_effect=AssertionError('offline test attempted network')):
            result=await run_offline(self.case.service,self.case.context,profile(),model=model,max_turns=12)
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual({e['tool'] for e in result['tool_events'] if e['type']=='tool_handler_return'},
            {'find_assets','get_asset_schema','request_asset_update','search_asset','read_evidence','query_records','deliver'})
        delivery=result['delivery']['delivery']
        self.assertEqual(delivery['calculations'][0]['value'],'-2.250000000000000000')
        self.assertEqual(len(delivery['records']),2)
        self.assertEqual(self.case.service.read_delivery(self.case.context),delivery)
        self.assertTrue(any(e['type']=='observed_tool_result' for e in result['tool_events']))
        self.assertEqual(len(model.inputs),8)

    async def test_invalid_arguments_tool_error_forged_delivery_and_free_text_fail(self):
        for scenario in ['invalid_arguments','tool_error','forged_delivery','free_text']:
            with self.subTest(scenario=scenario):
                c=F['case']()
                try:
                    result=await run_offline(c.service,c.context,profile(),model=F['ScriptedModel'](scenario),max_turns=3)
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
            await run_offline(self.case.service,self.case.context,profile(),model=model,max_turns=2)


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
