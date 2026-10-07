import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from uteki.agents.runtime.bounded_retry import metered_response, transient_failure
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def test_only_proven_preconnect_failures_release_unknown_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            budget=RunBudget(Path(temp)/'budget.sqlite','1')
            token=budget.reserve('.4');budget.settle(token,None)
            metadata=dict(transport_error_type='ConnectError',headers_received=False,
                transport_phase='awaiting_headers',usage_presence='absent',http_status=None,
                response_id=None,raw_usage=None)
            for wrong in ({'transport_error_type':'RemoteProtocolError'},
                          {'transport_error_type':'ReadTimeout'}, {'headers_received':True},
                          {'response_id':'received-id'}, {'raw_usage':{'output_tokens':1}}):
                with self.assertRaises(ValueError):
                    budget.reconcile_preconnect_failure(token,metadata|wrong,evidence_sha256='a'*64)
            self.assertTrue(budget.reconcile_preconnect_failure(token,metadata,evidence_sha256='a'*64))
            self.assertFalse(budget.reconcile_preconnect_failure(token,metadata,evidence_sha256='a'*64))
            self.assertEqual(budget.summary()['held_usd'],'0')
            self.assertEqual(budget.summary()['unknown_requests'],0)

    async def test_partial_reply_is_preserved_not_joined_and_unknown_cost_stays_held(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            budget = RunBudget(root/'budget.sqlite', '1', allow_unknown_reservations=True)
            native = SimpleNamespace(response_metadata=None, response_text=None)
            calls = []
            async def get_response(**kwargs):
                native.response_metadata = None
                token = budget.reserve('.4')
                calls.append(kwargs)
                if len(calls) == 1:
                    native.response_metadata = {'transport_error_type':'RemoteProtocolError'}
                    native.response_text = '{"partial'
                    budget.settle(token, None)
                    raise RuntimeError('transport')
                native.response_metadata = {'stop_reason':'end_turn'}
                native.response_text = '{"complete":true}'
                budget.settle(token, '.1')
                return native.response_text
            meter = SimpleNamespace(inner=native,budget=budget,get_response=get_response)
            result = await metered_response(meter,folder=root/'tries',kwargs={'input':'same'},delay_seconds=0)
            self.assertEqual(result, '{"complete":true}')
            self.assertEqual(calls,[{'input':'same'}]*2)
            self.assertEqual((root/'tries/001/response.txt').read_text(), '{"partial')
            self.assertEqual(budget.summary()['unknown_requests'],1)
            self.assertEqual(budget.summary()['held_usd'],'0.4')
            with self.assertRaises(BudgetExceeded): budget.reserve('.51')

    async def test_budget_and_cancellation_never_retry(self):
        for error in (BudgetExceeded('cap'), asyncio.CancelledError()):
            with tempfile.TemporaryDirectory() as temp:
                calls=[]
                async def get_response():
                    calls.append(True)
                    raise error
                meter=SimpleNamespace(inner=SimpleNamespace(response_metadata={'transport_error_type':'ReadTimeout'},response_text=None),
                                      budget=None,get_response=get_response)
                with self.assertRaises(type(error)):
                    await metered_response(meter,folder=Path(temp)/'tries',kwargs={},delay_seconds=0)
                self.assertEqual(len(calls),1)
                outcome=json.loads((Path(temp)/'tries/001/outcome.json').read_text())
                self.assertFalse(outcome['will_retry'])
                if isinstance(error, asyncio.CancelledError):
                    self.assertEqual(outcome['status'],'cancelled')

    def test_only_transient_categories_and_default_budget_remains_strict(self):
        for metadata in ({'stop_reason':'max_tokens'}, {'http_status':400}, {'http_status':401},
                         {'stream_error_type':'invalid_block_sequence'}, {'transport_error_type':'LocalProtocolError'}):
            self.assertFalse(transient_failure(metadata))
        for metadata in ({'http_status':429}, {'http_status':503},
                         {'stream_error_type':'incomplete_stream'}, {'transport_error_type':'ReadTimeout'}):
            self.assertTrue(transient_failure(metadata))
        with tempfile.TemporaryDirectory() as temp:
            budget=RunBudget(Path(temp)/'budget.sqlite','1')
            budget.settle(budget.reserve('.2'),None)
            with self.assertRaises(BudgetExceeded): budget.reserve('.2')

    async def test_repeated_failure_stops_at_two_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            native=SimpleNamespace(response_metadata=None,response_text=None)
            async def get_response():
                calls.append(True)
                native.response_metadata={'transport_error_type':'ReadTimeout'}
                raise TimeoutError('timeout')
            meter=SimpleNamespace(inner=native,budget=None,get_response=get_response)
            with self.assertRaises(TimeoutError):
                await metered_response(meter,folder=Path(temp)/'tries',kwargs={},delay_seconds=0)
            self.assertEqual(len(calls),2)
            outcome=json.loads((Path(temp)/'tries/002/outcome.json').read_text())
            self.assertFalse(outcome['will_retry'])
