"""Accepted invocation time and cancellation apply before the native SDK starts."""
import asyncio
import os
from copy import deepcopy
from pathlib import Path
import runpy
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import LoadedProfile,load_profile
from uteki.data_platform.application.session import Session

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
def profile():
    return load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
        config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')

class HostLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case=F['case']();self.addCleanup(self.case.doCleanups)

    async def test_valid_profile_preflight_time_counts_before_first_request(self):
        request=deepcopy(self.case.request);request['run_policy']['max_wall_seconds']=1
        context=self.case.service.create_context(request,request_key='slow-profile')['context_ref']
        validate=LoadedProfile.validate;seen=False
        def slow(loaded,**kwargs):
            nonlocal seen
            if not seen:seen=True;time.sleep(1.05)
            return validate(loaded,**kwargs)
        model=F['ScriptedModel']()
        with patch.object(LoadedProfile,'validate',slow):
            result=await run_offline(self.case.service,context,profile(),model=model,limits=F['runtime_limits']())
        self.assertEqual(model.inputs,[])
        self.assertEqual(result['status'],'partial',result)
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'wall_time')
        self.assertGreaterEqual(Session(self.case.catalog,context).data['wall_seconds'],1.05)

    async def test_cancel_after_host_acceptance_before_sdk_task_enters_returns_partial(self):
        create=asyncio.create_task;cancelled=False
        def before_start(coroutine,**kwargs):
            nonlocal cancelled
            task=create(coroutine,**kwargs)
            if not cancelled:
                cancelled=True;asyncio.current_task().cancel()
            return task
        model=F['ScriptedModel']()
        async def exercise():
            with patch('asyncio.create_task',before_start):
                return await run_offline(self.case.service,self.case.context,profile(),model=model,limits=F['runtime_limits']())
        result=await create(exercise())
        self.assertEqual(result['status'],'cancelled',result)
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'cancelled')
        self.assertEqual(model.inputs,[])
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)

    async def test_sdk_assembly_failure_is_durable_without_model_request(self):
        for target in ('make_agent','ToolBinding'):
            with self.subTest(target=target):
                context=self.case.service.create_context(self.case.request,request_key=target)['context_ref']
                model=F['ScriptedModel']()
                with patch('uteki.data_platform.agent.openai_runtime.'+target,side_effect=RuntimeError('synthetic SDK assembly failure')):
                    result=await run_offline(self.case.service,context,profile(),model=model,limits=F['runtime_limits']())
                self.assertEqual(result['kind'],'failed',result)
                self.assertIn('synthetic SDK assembly failure',result['error'])
                self.assertEqual(self.case.service.read_run_result(context),result)
                self.assertEqual(model.inputs,[])

    def claude_fixture(self):
        loaded=load_profile(ROOT/'config/data_platform/model-profiles/claude/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='claude',model_id='fixture/claude-query-v1',role='query')
        cwd=self.case.root/'claude-test';cwd.mkdir()
        base='http://127.0.0.1:1'
        env=dict(PATH='/usr/bin:/bin',CLAUDE_CONFIG_DIR=str(cwd/'claude-config'),
            ANTHROPIC_BASE_URL=base,ANTHROPIC_API_KEY='',ANTHROPIC_AUTH_TOKEN='uteki-offline-fixture',
            CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(loaded.profile.max_output_tokens),
            HTTP_PROXY=base,HTTPS_PROXY=base,ALL_PROXY=base)
        return loaded,cwd,env

    async def test_claude_preflight_deadline_prevents_cli_assembly(self):
        from uteki.data_platform.agent.claude_runtime import run_offline as run_claude
        loaded,cwd,env=self.claude_fixture()
        request=deepcopy(self.case.request);request['run_policy']['max_wall_seconds']=1
        context=self.case.service.create_context(request,request_key='slow-claude-profile')['context_ref']
        validate=LoadedProfile.validate;seen=False
        def slow(value,**kwargs):
            nonlocal seen
            if not seen:seen=True;time.sleep(1.05)
            return validate(value,**kwargs)
        with (patch.dict(os.environ,env,clear=True),patch.object(LoadedProfile,'validate',slow),
                patch('uteki.data_platform.agent.claude_runtime.make_options') as assembly):
            result=await run_claude(self.case.service,context,loaded,cwd=str(cwd),
                cli_path='/synthetic-not-launched-claude',limits=F['runtime_limits']())
        assembly.assert_not_called()
        self.assertEqual(result['status'],'partial',result)
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'wall_time')
        self.assertGreaterEqual(Session(self.case.catalog,context).data['wall_seconds'],1.05)

    async def test_claude_assembly_failure_is_saved_before_cli_or_http_start(self):
        from uteki.data_platform.agent.claude_runtime import run_offline as run_claude
        loaded,cwd,env=self.claude_fixture()
        with (patch.dict(os.environ,env,clear=True),
                patch('socket.socket.connect',side_effect=AssertionError('unexpected HTTP')),
                patch('uteki.data_platform.agent.claude_runtime.make_options',side_effect=RuntimeError('synthetic Claude assembly failure'))):
            result=await run_claude(self.case.service,self.case.context,loaded,cwd=str(cwd),
                cli_path='/synthetic-not-launched-claude',limits=F['runtime_limits']())
        self.assertEqual(result['kind'],'failed',result)
        self.assertIn('synthetic Claude assembly failure',result['error'])
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)

    async def test_unconfirmed_final_timing_cannot_be_skipped_by_clarification(self):
        def checkpoint(phase):
            if phase=='native_outcome_committed':raise OSError('synthetic completion acknowledgement failure')
        with self.assertRaises(OSError):
            await run_offline(self.case.service,self.case.context,profile(),model=F['ScriptedModel']('clarify'),
                limits=F['runtime_limits'](),checkpoint=checkpoint)
        result=self.case.service.read_run_result(self.case.context)
        question=result['clarification']['clarification']
        request=deepcopy(self.case.request)|dict(revises_context_ref=self.case.context,
            clarification_response=dict(clarification_id=question['clarification_id'],answer='Same scope.'))
        from uteki.data_platform.contracts.common import CatalogError
        with self.assertRaises(CatalogError):self.case.service.create_context(request,request_key='pending-tail-answer')
        self.assertEqual(self.case.service.inspect_context(self.case.context)['completion_clock']['status'],'pending')

if __name__=='__main__':unittest.main()
