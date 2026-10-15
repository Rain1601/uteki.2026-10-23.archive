"""Another owner may persist cancellation before the SDK signals its outcome."""
import unittest
from pathlib import Path
import runpy

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.application.session import Session
from uteki.infrastructure.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
P=runpy.run_path(str(Path(__file__).with_name('test_runtime.py')))['profile']


class PersistedStopTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,timeout):
        case=F['case']();self.addCleanup(case.doCleanups)
        class Stopped(F['ScriptedModel']):
            async def get_response(self,*args,**kwargs):
                response=await super().get_response(*args,**kwargs)
                data=Session(case.catalog,case.context).data
                budget=RunBudget.open_existing(case.root/data['native_execution']['ledger_path'],'0',
                    root_run_id=data['context']['root_run_id'])
                budget.stop_root('cancelled')
                if timeout:raise TimeoutError('synthetic later timeout after persisted cancellation')
                return response
        model=Stopped()
        result=await run_offline(case.service,case.context,P(),model=model,limits=F['runtime_limits']())
        self.assertEqual(result['status'],'cancelled',result['error'])
        self.assertEqual(result['delivery']['delivery']['stop_reason'],'cancelled')
        self.assertEqual(len(model.inputs),1)
        data=Session(case.catalog,case.context).data
        self.assertEqual(data['turns'],0)
        self.assertEqual([v['tool'] for v in data['operations'].values()],['deliver'])
        usage=result['delivery']['delivery']['usage']
        self.assertEqual(usage['unknown_requests'],1 if timeout else 0)

    async def test_persisted_cancel_blocks_tools_in_an_arriving_response(self):
        await self.exercise(False)

    async def test_first_persisted_cancel_is_not_replaced_by_later_timeout(self):
        await self.exercise(True)


if __name__=='__main__':unittest.main()
