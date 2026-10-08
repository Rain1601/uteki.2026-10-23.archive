"""Per-request native retries keep each attempt billable and never repeat host actions."""
import asyncio
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx

from uteki.agents.data_query.autonomous_model import SdkAutonomousPlanner
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.runtime.claude_messages import ClaudeTransientTransportError
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from uteki.agents.runtime.call_costs import summarize


class ClaudeTransientRetryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root=Path(temp.name)
        self.enterContext(patch.dict('os.environ',{'AIHUBMIX_API_KEY':'offline-transient-key'}))
        for module in ('autonomous_model','record_review_model'):
            self.enterContext(patch('uteki.agents.data_query.'+module+'.load_provider_key',return_value='offline_fixture'))
        self.requests=[]

    def client(self,handler):
        def dispatch(request):
            self.requests.append(request.content)
            return handler(request)
        def factory(**kwargs):
            kwargs['transport']=httpx.MockTransport(dispatch)
            return httpx.AsyncClient(**kwargs)
        return factory

    @staticmethod
    def response(*,text=None,status=200,stop='end_turn'):
        value={'action':'load_skill','requirement_ids':[],'reason':None,'payload_json':'"query"'}
        return httpx.Response(status,json={'id':'offline-response','model':'claude-sonnet-5-5','stop_reason':stop,
            'content':[{'type':'text','text':json.dumps(value) if text is None else text}],
            'usage':{'input_tokens':100,'output_tokens':50}})

    def planner(self,handler,*,retries=1,allow_unknown=True,name='model'):
        budget=RunBudget(self.root/(name+'.sqlite'),'3',allow_unknown_reservations=allow_unknown)
        planner=SdkAutonomousPlanner('aihubmix','claude-sonnet-5-5',budget=budget,max_requests_total=5,
            output=self.root/name,credentials_root=self.root,reasoning_effort='high',
            purpose='analysis_evidence',max_retries=retries,client_factory=self.client(handler))
        return planner,budget

    def decide(self,planner):
        async def run():
            try:return await planner.decide({'question':'Same frozen task','input':'unchanged'})
            finally:await planner.aclose()
        return asyncio.run(run())

    def test_ssl_read_timeout_and_temporary_http_retry_same_request_with_separate_costs(self):
        failures=[ssl.SSLError('PRIVATE_TRANSPORT_TEXT'),httpx.ReadError('PRIVATE_TRANSPORT_TEXT'),
            httpx.ReadTimeout('PRIVATE_TRANSPORT_TEXT'),429,503]
        for index,failure in enumerate(failures):
            with self.subTest(failure=type(failure).__name__):
                self.requests=[]
                def handler(request):
                    if len(self.requests)==1:
                        if isinstance(failure,int):return self.response(status=failure)
                        raise failure
                    return self.response()
                planner,budget=self.planner(handler,name=f'model-{index}')
                self.assertEqual(self.decide(planner).skill,'query')
                self.assertEqual(len(self.requests),2)
                self.assertEqual(self.requests[0],self.requests[1])
                usage=summarize(planner.output/'calls')
                self.assertEqual(usage['requests'],2)
                self.assertEqual(usage['unknown_cost_requests'],1)
                self.assertEqual(len({r['call_id'] for r in usage['records']}),2)
                self.assertEqual(budget.summary()['unknown_requests'],1)
                self.assertGreater(float(budget.summary()['held_usd']),0)
                self.assertEqual(budget.summary()['estimated_spent_usd'],'0.0007')
                first=json.loads((planner.output/'decision-0001-attempt-01.json').read_text())
                second=json.loads((planner.output/'decision-0001-attempt-02.json').read_text())
                self.assertTrue(first['retry_scheduled']);self.assertTrue(second['retry'])
                self.assertEqual(second['status'],'decision_returned')
                self.assertNotIn('PRIVATE_TRANSPORT_TEXT',json.dumps(usage))

    def test_default_zero_and_explicit_retry_bound_stop_without_action(self):
        for count in (0,1):
            self.requests=[]
            def handler(request):raise ssl.SSLError('PRIVATE')
            planner,budget=self.planner(handler,retries=count,name=f'bound-{count}')
            with self.assertRaises(ClaudeTransientTransportError):self.decide(planner)
            self.assertEqual(len(self.requests),count+1)
            self.assertEqual(budget.summary()['unknown_requests'],count+1)
            self.assertEqual(len(list(planner.output.glob('decision-0001-attempt-*.json'))),count+1)

    def test_permanent_http_certificate_schema_and_output_limit_are_not_network_retries(self):
        failures=[400,401,ssl.SSLCertVerificationError('PRIVATE_CERTIFICATE'),
            'not JSON','{"action":"load_skill","requirement_ids":[],"reason":null,"payload_json":"123"}', 'max_tokens']
        for index,failure in enumerate(failures):
            self.requests=[]
            def handler(request):
                if isinstance(failure,Exception):raise failure
                if isinstance(failure,int):return self.response(status=failure)
                if failure=='max_tokens':return self.response(stop=failure)
                return self.response(text=failure)
            planner,_=self.planner(handler,name=f'permanent-{index}')
            with self.subTest(index=index),self.assertRaises(Exception):self.decide(planner)
            self.assertEqual(len(self.requests),1)
            self.assertEqual(len(list(planner.output.glob('decision-0001-attempt-*.json'))),1)

    def test_unknown_budget_policy_can_block_second_request_without_erasing_first(self):
        def handler(request):raise ssl.SSLError('PRIVATE')
        planner,budget=self.planner(handler,allow_unknown=False)
        with self.assertRaises(BudgetExceeded):self.decide(planner)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(budget.summary()['unknown_requests'],1)
        second=json.loads((planner.output/'decision-0001-attempt-02.json').read_text())
        self.assertEqual(second['calls'],[])
        self.assertNotIn('visible_output',second)

    def test_cancellation_does_not_retry_or_clear_unknown_reservation(self):
        def handler(request):raise asyncio.CancelledError()
        planner,budget=self.planner(handler)
        with self.assertRaises(asyncio.CancelledError):self.decide(planner)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(budget.summary()['unknown_requests'],1)

    def test_reviewer_uses_same_metered_retry_boundary_and_keeps_failed_attempt(self):
        def handler(request):
            if len(self.requests)==1:raise ssl.SSLError('PRIVATE')
            return self.response(text='{"summary":"Original supported result"}')
        budget=RunBudget(self.root/'review.sqlite','3',allow_unknown_reservations=True)
        reviewer=SdkRecordReviewer('aihubmix','claude-sonnet-5-5',budget=budget,max_requests_total=2,
            output=self.root/'review',credentials_root=self.root,prompt='Review supplied evidence.',
            reasoning_effort='high',max_retries=1,client_factory=self.client(handler))
        async def run():
            try:return await reviewer.review({'facts':['Original source']})
            finally:await reviewer.aclose()
        self.assertEqual(asyncio.run(run()),{'summary':'Original supported result'})
        self.assertEqual(self.requests[0],self.requests[1])
        self.assertEqual(budget.summary()['unknown_requests'],1)
        attempts=sorted(reviewer.output.glob('review-0001-attempt-*.json'))
        self.assertEqual(len(attempts),2)
        self.assertIsNone(json.loads(attempts[0].read_text())['raw_text'])
        self.assertEqual(json.loads(attempts[1].read_text())['status'],'json_returned')

    def test_retry_after_completed_read_does_not_replay_host_actions(self):
        from tests.unit.test_answer_handoff import AnswerHandoffTests
        from tests.unit.test_autonomous_source_evidence import source_plan, context_read
        from tests.unit.test_analysis_evidence_runtime import choose
        from uteki.agents.data_query.autonomous import AutonomousDataAgent
        from uteki.agents.data_query.decision_protocol import ACTION_RULES
        from uteki.infrastructure.research_data.query_service import QueryDataPort
        from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle

        AnswerHandoffTests.setUp(self)
        state = {}
        def handler(request):
            # The first two successful decisions have already planned and read.
            if len(self.requests) == 3:
                raise ssl.SSLError('PRIVATE interrupted third decision')
            ordinal = len(self.requests) - (1 if len(self.requests) > 3 else 0)
            action = {1: source_plan, 2: context_read,
                      3: lambda: choose('b1')(state['packet']), 4: lambda: {'action':'finish'}}[ordinal]()
            field = ACTION_RULES[action['action']].payload
            envelope = {'action':action['action'], 'requirement_ids':action.get('requirement_ids',[]),
                'reason':action.get('reason'), 'payload_json':json.dumps(action[field]) if field else None}
            return self.response(text=json.dumps(envelope))
        planner,budget = self.planner(handler)
        original_decide = planner.decide
        async def capture(packet, **kwargs):
            state['packet'] = packet
            return await original_decide(packet, **kwargs)
        planner.decide = capture
        output = self.root/'query'
        async def run(port):
            try:
                return await AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                    limits={'max_steps':4,'max_packet_bytes':64000}).run(self.request, output=output)
            finally:
                await planner.aclose()
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(run(port))
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertEqual([row['action'] for row in result['trace']],
                         ['plan','read_context','select_evidence','finish'])
        contexts = [row for row in load_evidence_bundle(output)['items'] if row['kind']=='context']
        self.assertEqual(len(contexts),1)
        self.assertEqual(len(self.requests),5)
        self.assertEqual(self.requests[2],self.requests[3])
        self.assertEqual(budget.summary()['unknown_requests'],1)

    def test_coordinator_allows_only_explicit_bounded_retry_counts(self):
        config={'provider':'aihubmix','model':'claude-sonnet-5-5','reasoning_effort':'high',
            'budget_ledger':str(self.root/'config.sqlite'),'budget_usd':None,'budget_policy':'record_only',
            'max_requests_total':None}
        for count in (0,1,3):CompanyDataCoordinator._validate_model_config({**config,'max_retries':count})
        for count in (-1,4,True,None):
            with self.subTest(count=count),self.assertRaises(ValueError):
                CompanyDataCoordinator._validate_model_config({**config,'max_retries':count})
