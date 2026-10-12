"""Capacity and network retries are independent bounded state, over mocked HTTP."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx2 as httpx

from tests.unit import test_autonomous_model as fixtures
from tests.unit import test_retrieval_cycle as cycle_fixtures
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.runtime.output_limit import (ModelOutputLimitExceeded,
    validate_capacity_recovery, validate_capacity_settlement)
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


POLICY={'version':'output-capacity-recovery-v1','max_tokens':16384,'max_recoveries':1}


class OutputCapacityRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AutonomousModelTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sent=[]

    def response(self, request, *, finish='stop', usage=True, output_tokens=None):
        body=json.loads(request.content);self.sent.append(body)
        cap=body['max_tokens'] if output_tokens is None else output_tokens
        value={'id':'mock-'+str(len(self.sent)),'object':'chat.completion','created':1,
            'model':'deepseek-flash','choices':[{'index':0,'finish_reason':finish,
                'message':{'role':'assistant','content':'{"action":"finish"}' if finish=='stop'
                    else '{"partial":"UNTRUSTED_PARTIAL_DO_NOT_CONTINUE"}'}}]}
        if usage:value['usage']={'prompt_tokens':100,'completion_tokens':cap,'total_tokens':100+cap}
        return httpx.Response(200,json=value)

    def planner(self, handler, **kwargs):
        return self.fixture.planner(handler,max_tokens=256,output_capacity_recovery=POLICY,**kwargs)

    def attempts(self, planner):
        return [json.loads(path.read_text()) for path in sorted(planner.output.glob('decision-*-attempt-*.json'))]

    def test_promotes_actual_wire_once_keeps_base_frozen_and_persists_later_decisions(self):
        def handler(request):return self.response(request,finish='length' if not self.sent else 'stop')
        planner=self.planner(handler)
        original=planner.frozen_config
        packet={'question':'Read only frozen selected evidence.'}
        async def run():
            try:
                self.assertEqual((await planner.decide(packet)).action,'finish')
                self.assertEqual((await planner.decide(packet)).action,'finish')
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual([r['max_tokens'] for r in self.sent],[256,16384,16384])
        self.assertEqual(planner.frozen_config,original)
        self.assertEqual(planner.frozen_config['max_tokens'],256)
        for body in self.sent:
            self.assertNotIn('UNTRUSTED_PARTIAL',json.dumps(body))
        normalized=[{k:v for k,v in r.items() if k!='max_tokens'} for r in self.sent]
        self.assertEqual(normalized[0],normalized[1])
        attempts=self.attempts(planner)
        self.assertEqual([r['attempt'] for r in attempts],[1,2,1])
        self.assertEqual([r['effective_max_tokens'] for r in attempts],[256,16384,16384])
        self.assertEqual([r['capacity_recovery'] for r in attempts],[False,True,False])
        self.assertEqual(attempts[1]['prior_terminal']['settlement']['state'],'settled')
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['requests'],3)

    def test_repeated_length_fails_and_instance_opportunity_never_resets(self):
        planner=self.planner(lambda request:self.response(request,finish='length'))
        async def run():
            try:
                for _ in range(2):
                    with self.assertRaises(ModelOutputLimitExceeded):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual([r['max_tokens'] for r in self.sent],[256,16384,16384])
        self.assertEqual(planner._capacity_recoveries,1)

    def test_missing_usage_and_output_not_at_cap_do_not_promote(self):
        for name,usage,count in (('unknown',False,None),('short',True,255)):
            planner=self.planner(lambda request:self.response(request,finish='length',usage=usage,output_tokens=count),
                name=name)
            async def run():
                try:
                    with self.assertRaises(ModelOutputLimitExceeded):await planner.decide({'question':'same'})
                finally:await planner.aclose()
            before=len(self.sent);asyncio.run(run())
            self.assertEqual(len(self.sent),before+1)
            self.assertEqual(planner._capacity_recoveries,0)
            gate=json.loads(next(planner.output.glob('decision-*-capacity-*.json')).read_text())
            self.assertEqual(gate['reason'],'settlement_or_usage_not_verified')

    def test_promotion_budget_block_consumes_opportunity_without_dispatch(self):
        budget=RunBudget(self.fixture.root/'small.sqlite','.03',enforce=True)
        planner=self.planner(lambda request:self.response(request,finish='length'),budget=budget)
        async def run():
            try:
                with self.assertRaises(BudgetExceeded):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.sent),1)
        self.assertEqual(planner._capacity_recoveries,1)
        self.assertEqual(self.attempts(planner)[1]['effective_max_tokens'],16384)
        self.assertNotIn('visible_output',self.attempts(planner)[1])

    def test_network_retry_count_does_not_reset_after_promotion(self):
        statuses=iter(['network','length','network'])
        def handler(request):
            status=next(statuses)
            if status=='network':
                self.sent.append(json.loads(request.content))
                return httpx.Response(500,json={'error':{'message':'temporary','type':'server_error'}})
            return self.response(request,finish='length')
        planner=self.planner(handler,max_retries=1)
        async def run():
            try:
                from openai import InternalServerError
                with self.assertRaises(InternalServerError):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual([r['max_tokens'] for r in self.sent],[256,256,16384])
        self.assertEqual([r['network_retry_index'] for r in self.attempts(planner)],[0,1,1])
        self.assertEqual([r['attempt'] for r in self.attempts(planner)],[1,2,3])

    def test_promoted_network_retry_is_still_bounded_and_keeps_target(self):
        statuses=iter(['length','network','stop'])
        def handler(request):
            status=next(statuses)
            if status=='network':
                self.sent.append(json.loads(request.content))
                return httpx.Response(500,json={'error':{'message':'temporary','type':'server_error'}})
            return self.response(request,finish=status)
        planner=self.planner(handler,max_retries=1)
        async def run():
            try:self.assertEqual((await planner.decide({'question':'same'})).action,'finish')
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual([r['max_tokens'] for r in self.sent],[256,16384,16384])
        self.assertEqual([r['network_retry_index'] for r in self.attempts(planner)],[0,0,1])

    def test_cancel_promoted_request_stops_and_does_not_refund_opportunity(self):
        async def handler(request):
            if not self.sent:return self.response(request,finish='length')
            self.sent.append(json.loads(request.content))
            await asyncio.sleep(30)
        planner=self.planner(handler)
        async def run():
            try:
                task=asyncio.create_task(planner.decide({'question':'same'}))
                for _ in range(500):
                    if len(self.sent)==2:break
                    await asyncio.sleep(.001)
                self.assertEqual(len(self.sent),2);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual(planner._capacity_recoveries,1)
        self.assertEqual(self.attempts(planner)[1]['error_type'],'CancelledError')
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['unknown_requests'],1)

    def test_worker_instance_promotes_independently_on_same_ledger(self):
        budget=RunBudget(self.fixture.root/'shared.sqlite','1',enforce=False)
        def make(name,role):
            seen=[]
            def handler(request):
                finish='length' if not seen else 'stop';seen.append(True)
                return self.response(request,finish=finish)
            return self.planner(handler,budget=budget,name=name,role=role,maximum=5)
        planner,worker=make('parent','planner'),make('child','worker')
        async def run():
            try:
                await planner.decide({'question':'parent'})
                await worker.decide({'question':'worker'})
            finally:await planner.aclose();await worker.aclose()
        asyncio.run(run())
        self.assertEqual(planner._capacity_recoveries,1);self.assertEqual(worker._capacity_recoveries,1)
        self.assertEqual(budget.summary()['requests'],4)

    def test_unconfigured_and_explicit_none_preserve_legacy_stop_and_no_config_field(self):
        for name,options in (('old',{}),('none',{'output_capacity_recovery':None})):
            planner=self.fixture.planner(lambda request:self.response(request,finish='length'),name=name,
                max_tokens=256,**options)
            async def run():
                try:
                    with self.assertRaises(ModelOutputLimitExceeded):await planner.decide({'question':'same'})
                finally:await planner.aclose()
            asyncio.run(run())
            self.assertNotIn('output_capacity_recovery',planner.frozen_config)
            self.assertEqual(len(self.attempts(planner)),1)

    def test_policy_strict_provider_model_and_cap_validation(self):
        for change in ({'max_tokens':True},{'max_tokens':256},{'max_tokens':16385},
                       {'max_recoveries':True},{'max_recoveries':2},{'version':'other'},{'unknown':1}):
            with self.assertRaises(ValueError):validate_capacity_recovery({**POLICY,**change},
                provider='deepseek',model='deepseek-flash',base_max_tokens=256)
        for provider,model in (('aihubmix','deepseek-flash'),('deepseek','deepseek-v4-pro')):
            with self.assertRaises(ValueError):validate_capacity_recovery(POLICY,
                provider=provider,model=model,base_max_tokens=256)

    def test_settlement_unknown_wrong_amount_other_ledger_and_multiple_end_fail_closed(self):
        planner=self.fixture.planner(lambda request:self.response(request,finish='length'),max_tokens=256)
        error=None
        async def run():
            nonlocal error
            try:await planner.decide({'question':'same'})
            except ModelOutputLimitExceeded as caught:error=caught
            finally:await planner.aclose()
        asyncio.run(run())
        paths=set((planner.output/'calls').glob('*.json'))
        def validate():return validate_capacity_settlement(paths,budget=planner._budget,
            expected_ledger=planner.frozen_config['budget_ledger'],effective_max_tokens=256,
            diagnostic=error.diagnostic,artifact_root=planner.output)
        evidence=validate();reservation=evidence['settlement']['reservation_id']
        end=next(path for path in paths if str(path).endswith('-end.json'))
        duplicate=end.with_name('extra-end.json');duplicate.write_bytes(end.read_bytes())
        with self.assertRaises(ValueError):validate_capacity_settlement(paths|{duplicate},
            budget=planner._budget,expected_ledger=planner.frozen_config['budget_ledger'],
            effective_max_tokens=256,diagnostic=error.diagnostic,artifact_root=planner.output)
        with planner._budget._transaction() as db:
            db.execute("UPDATE reservations SET state='unknown' WHERE id=?",(reservation,))
        with self.assertRaises(ValueError):validate()
        with planner._budget._transaction() as db:
            db.execute("UPDATE reservations SET state='settled',actual='0' WHERE id=?",(reservation,))
        with self.assertRaises(ValueError):validate()
        with self.assertRaises(ValueError):validate_capacity_settlement(paths,budget=planner._budget,
            expected_ledger=self.fixture.root/'other.sqlite',effective_max_tokens=256,
            diagnostic=error.diagnostic,artifact_root=planner.output)

    def test_coordinator_passes_explicit_policy_and_reviewer_rejects_even_none(self):
        fixture=cycle_fixtures.RetrievalCycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=deepcopy(fixture.config)
        config['planner']['output_capacity_recovery']=POLICY
        cycle.validate(config,fixture.output)
        with patch('uteki.agents.data_query.autonomous_model.SdkAutonomousPlanner') as constructor:
            CompanyDataCoordinator._planner(config['planner'],fixture.root/'model',fixture.root)
        self.assertEqual(constructor.call_args.kwargs['output_capacity_recovery'],POLICY)
        for value in (None,POLICY):
            config['reviewer']['output_capacity_recovery']=value
            with self.assertRaisesRegex(ValueError,'review roles do not support'):
                cycle.validate(config,fixture.output)
            with self.assertRaisesRegex(ValueError,'review roles do not support'):
                cycle.reviewer_factory(config)

    def test_failed_attempt_sealing_does_not_consume_capacity_opportunity(self):
        from uteki.agents.data_query import autonomous_model as runtime
        original=runtime.write_new
        def writing(path,value):
            if Path(path).name.endswith('-attempt-01.json'):
                raise OSError('offline sealing failure')
            return original(path,value)
        planner=self.planner(lambda request:self.response(request,finish='length'))
        async def run():
            try:
                with patch.object(runtime,'write_new',side_effect=writing):
                    with self.assertRaises(OSError):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.sent),1)
        self.assertEqual(planner._capacity_recoveries,0)
        self.assertEqual(planner._effective_max_tokens,256)
        self.assertFalse(list(planner.output.glob('decision-*-capacity-*.json')))

    def test_financial_extractor_config_does_not_silently_ignore_policy(self):
        fixture=cycle_fixtures.RetrievalCycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner
        request=deepcopy(fixture.config['request'])
        request['financial_tasks']=[dict(task_id='task',job={},task_profile='financial-v1',
            task_profile_sha256='0'*64,max_new_batches=1)]
        coordinator=CompanyDataCoordinator(fixture.root/'workspace')
        for value in (None,POLICY):
            config={**fixture.config['planner'],'output_capacity_recovery':value}
            async def run():
                with self.assertRaisesRegex(ValueError,'financial extractor does not support'):
                    await coordinator._query(request,output=fixture.output,
                        planner=ScriptedPlanner([]),credential_root=fixture.root,
                        method_root=fixture.root,extractor_model_config=config)
            asyncio.run(run())
        self.assertFalse(fixture.output.exists())

    def test_exported_nonplanner_entries_reject_policy_presence_before_work(self):
        from scripts import run_data_handoff as driver
        from uteki.infrastructure.research_data.financial_tasks import FinancialTaskGateway
        from uteki.infrastructure.research_data import direct_extraction
        for value in (None,POLICY):
            model={'output_capacity_recovery':value}
            for role in ('reviewer','analyst'):
                config={role:model}
                with self.assertRaisesRegex(ValueError,'does not support output_capacity_recovery'):
                    driver.validate(config,self.fixture.root/'invalid')
                with self.assertRaisesRegex(ValueError,'does not support output_capacity_recovery'):
                    driver.role_factory(config,role,'prompt',dict)
            with self.assertRaisesRegex(ValueError,'does not support output_capacity_recovery'):
                FinancialTaskGateway(None,None,None,method_root=None,output=None,
                    model_config=model,credentials_root=None)
            async def run():
                for entry in (direct_extraction.run_direct_extraction,direct_extraction._run_direct_extraction):
                    with patch.object(direct_extraction,'build_extraction_packet') as build:
                        with self.assertRaisesRegex(ValueError,'does not support output_capacity_recovery'):
                            await entry(None,{},self.fixture.root/'invalid',strategy='direct',model_config=model)
                        build.assert_not_called()
            asyncio.run(run())
        self.assertFalse((self.fixture.root/'invalid').exists())

    def test_shared_request_limit_blocks_promoted_dispatch_and_keeps_consumed_opportunity(self):
        planner=self.planner(lambda request:self.response(request,finish='length'),maximum=1)
        async def run():
            try:
                with self.assertRaises(BudgetExceeded):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.sent),1)
        self.assertEqual(planner._capacity_recoveries,1)
        self.assertEqual(planner.snapshot_usage()['summary']['shared_budget']['requests'],1)

    def test_cancellation_during_failed_attempt_sealing_stops_before_promotion(self):
        from uteki.agents.data_query import autonomous_model as runtime
        original=runtime.write_new
        def writing(path,value):
            if Path(path).name.endswith('-attempt-01.json'):
                raise asyncio.CancelledError()
            return original(path,value)
        planner=self.planner(lambda request:self.response(request,finish='length'))
        async def run():
            try:
                with patch.object(runtime,'write_new',side_effect=writing):
                    with self.assertRaises(asyncio.CancelledError):await planner.decide({'question':'same'})
            finally:await planner.aclose()
        asyncio.run(run())
        self.assertEqual(len(self.sent),1)
        self.assertEqual(planner._capacity_recoveries,0)
        self.assertFalse(list(planner.output.glob('decision-*-capacity-*.json')))


if __name__=='__main__':unittest.main()
