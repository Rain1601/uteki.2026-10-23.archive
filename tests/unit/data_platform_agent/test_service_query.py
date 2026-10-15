"""Application callers use the real Runner through the configured DataService."""
import asyncio
from copy import deepcopy
from functools import partial
from pathlib import Path
import runpy
import time
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.run import RunQueryResult
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class ServiceQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case=F['case']();self.addCleanup(self.case.doCleanups)
        self.profile=load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
            config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')

    def service(self,model):
        return DataService(self.case.catalog,query_runtime=partial(run_offline,
            profile=self.profile,model=model,limits=F['runtime_limits']()))

    async def test_shared_service_completes_and_replays_same_durable_result(self):
        model=F['ScriptedModel']();service=self.service(model)
        result=await service.run_query(self.case.context)
        self.assertEqual(RunQueryResult.model_validate(result).status,'completed')
        self.assertEqual(len(model.inputs),8)
        self.assertEqual(service.read_run_result(self.case.context),result)
        unused=F['ScriptedModel']()
        self.assertEqual(await self.service(unused).run_query(self.case.context),result)
        self.assertEqual(unused.inputs,[])

    async def test_disconnected_caller_cancels_shared_run_and_both_wait_for_cleanup(self):
        entered=asyncio.Event()
        class Waiting(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                entered.set();await asyncio.Event().wait()
        service=self.service(Waiting())
        original=asyncio.create_task(service.run_query(self.case.context))
        await asyncio.wait_for(entered.wait(),5)
        joined=asyncio.create_task(service.run_query(self.case.context));await asyncio.sleep(0)
        joined.cancel();joined.cancel()
        first,second=await asyncio.wait_for(asyncio.gather(original,joined),10)
        self.assertEqual(first,second)
        self.assertEqual(first['status'],'cancelled')
        self.assertEqual(first['delivery']['delivery']['usage']['model_calls'],1)
        self.assertEqual(first['delivery']['delivery']['usage']['unknown_requests'],1)
        self.assertEqual(service.read_run_result(self.case.context),first)
        self.assertEqual(self.case.catalog._native_executions,{})

    async def test_application_admission_time_counts_before_any_model_request(self):
        request=deepcopy(self.case.request);request['run_policy']['max_wall_seconds']=1
        context=self.case.service.create_context(request,request_key='host-admission')['context_ref']
        model=F['ScriptedModel']();service=self.service(model);configured=service.query_runtime
        async def slow(*args,**kwargs):
            time.sleep(1.05)
            return await configured(*args,**kwargs)
        service.query_runtime=slow
        result=await service.run_query(context)
        self.assertEqual(result['status'],'partial',result['error'])
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'wall_time')
        self.assertEqual(model.inputs,[])
        self.assertGreaterEqual(Session(self.case.catalog,context).data['wall_seconds'],1.05)

    async def test_clarification_answer_uses_same_root_through_service_entry(self):
        service=self.service(F['ScriptedModel']('clarify'))
        parent=await service.run_query(self.case.context)
        self.assertEqual(parent['kind'],'needs_clarification')
        request=deepcopy(self.case.request)|dict(revises_context_ref=self.case.context,
            clarification_response=dict(clarification_id=parent['clarification']['clarification']['clarification_id'],
                answer='Use the same scope.'))
        child=service.create_context(request,request_key='host-answer')
        result=await self.service(F['ScriptedModel']('after_clarification')).run_query(child['context_ref'])
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertEqual(result['runtime']['root_run_id'],parent['runtime']['root_run_id'])
        self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],9)
        self.assertEqual(service.read_run_result(self.case.context),parent)


if __name__=='__main__':unittest.main()
