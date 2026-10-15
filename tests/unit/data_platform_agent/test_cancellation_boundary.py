"""A cancellation request must survive a native adapter suppressing its signal."""
import asyncio
from pathlib import Path
import runpy
import unittest

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.application.session import Session
from uteki.infrastructure.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))

def profile():
    return load_profile(ROOT/'config/data_platform/model-profiles/openai/fixture-query/query.json',
        config_root=ROOT/'config/data_platform',kernel='openai',model_id='fixture/openai-query-v1',role='query')

class CancellationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case=F['case']();self.addCleanup(self.case.doCleanups)

    async def test_adapter_suppressing_cancel_cannot_resume_model_or_business_actions(self):
        entered=asyncio.Event()
        class Suppressing(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                if not self.inputs:
                    entered.set()
                    try:await asyncio.Event().wait()
                    except asyncio.CancelledError:pass
                return await super().get_response(*args,**kwargs)
        model=Suppressing()
        task=asyncio.create_task(run_offline(self.case.service,self.case.context,profile(),
            model=model,limits=F['runtime_limits']()))
        await asyncio.wait_for(entered.wait(),5)
        task.cancel()
        result=await asyncio.wait_for(task,10)
        self.assertEqual(result['status'],'cancelled',result.get('error'))
        self.assertEqual(len(model.inputs),1)
        data=Session(self.case.catalog,self.case.context).data
        self.assertEqual({op['tool'] for op in data['operations'].values()},{'deliver'})
        ledger=RunBudget.open_existing(self.case.root/data['native_execution']['ledger_path'],'0',
            root_run_id=data['context']['root_run_id'])
        self.assertEqual(ledger.summary()['requests'],1)
        self.assertEqual(ledger.inspect_root()['stop_reason'],'cancelled')

    async def test_repeated_cancellation_waits_for_same_cleanup_and_root_stops_immediately(self):
        entered,cleaning,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
        class Cleaning(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                entered.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleaning.set()
                    await release.wait()
                    raise
        task=asyncio.create_task(run_offline(self.case.service,self.case.context,profile(),
            model=Cleaning(),limits=F['runtime_limits']()))
        try:
            await asyncio.wait_for(entered.wait(),5);task.cancel()
            await asyncio.wait_for(cleaning.wait(),5)
            data=Session(self.case.catalog,self.case.context).data
            ledger=RunBudget.open_existing(self.case.root/data['native_execution']['ledger_path'],'0',
                root_run_id=data['context']['root_run_id'])
            stopped=ledger.inspect_root()['stop_reason']
            task.cancel();await asyncio.sleep(0)
        finally:
            release.set()
        result=await asyncio.wait_for(task,10)
        self.assertEqual(stopped,'cancelled')
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(ledger.summary()['requests'],1)
        self.assertEqual(self.case.catalog._native_executions,{})
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)

    async def test_cancelling_one_joined_caller_stops_the_shared_execution(self):
        entered=asyncio.Event()
        class Waiting(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                entered.set()
                await asyncio.Event().wait()
        model=Waiting()
        async def invoke():
            return await run_offline(self.case.service,self.case.context,profile(),
                model=model,limits=F['runtime_limits']())
        original=asyncio.create_task(invoke())
        await asyncio.wait_for(entered.wait(),5)
        joined=asyncio.create_task(invoke())
        await asyncio.sleep(0)
        joined.cancel()
        first,second=await asyncio.wait_for(asyncio.gather(original,joined),10)
        self.assertEqual(first['status'],'cancelled')
        self.assertEqual(second,first)
        self.assertEqual(self.case.service.read_run_result(self.case.context),first)
        self.assertEqual(first['delivery']['delivery']['usage']['model_calls'],1)

if __name__=='__main__':unittest.main()
