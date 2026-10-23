"""Bounded generation observations never become another model request."""
from decimal import Decimal
import json
from pathlib import Path
import runpy
import time
import unittest

from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
from uteki.data_platform.application.gateway_batch import load_gateway_binding
from uteki.data_platform.application.session import Session
from uteki.data_platform.application.run_budget import BudgetExceeded,RequestIdentityConflict,RequestRecoveryRequired,RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayBillingTests(unittest.TestCase):
    def setUp(self):
        self.case,self.args,self.bindings=F['fixture']();self.addCleanup(self.case.doCleanups)
        self.scope=self.args['scopes'][1]
        self.budget=load_gateway_binding(Session(self.case.catalog,self.scope['context_ref']),
            self.bindings[self.scope['scope_id']],self.scope['profile'],self.scope['limits'])['budget']

    def wire(self,peer,**options):
        wire=GatewayHTTP(self.budget,self.scope['scope_id'],endpoint=peer.endpoint,origin='synthetic',
            credential='uteki-synthetic-gateway',deadline=time.monotonic()+15,before_request=lambda req:None,**options)
        self.addCleanup(wire.close);return wire

    def request(self,wire):
        body=dict(model=self.scope['profile']['model_id'],max_tokens=4096,stream=True,
            messages=[dict(role='user',content='Synthetic query')])
        return wire.exchange('/v1/messages?beta=true',json.dumps(body).encode(),{})[0]

    def reopen(self):
        self.budget=RunBudget.open_existing(self.budget.path,'3.00',root_run_id=self.args['batch_id'])

    def test_generation_get_settles_original_bill_without_another_model_request(self):
        with F['MessagesPeer']() as peer:
            wire=self.wire(peer);key=self.request(wire)
            original=self.budget.inspect_request(key)['response_event']
            with self.assertRaises(RequestRecoveryRequired):
                self.budget.prepare_request('other-scope',{'synthetic':True},reserve_usd='.8',scope_id=self.args['scopes'][0]['scope_id'])
            observed=wire.observe_bill(key)
            self.assertEqual(observed['response_event'],original)
            self.assertEqual(Decimal(observed['settled_usd']),Decimal('.01'))
            self.assertEqual(wire.observe_bill(key),observed)
            self.assertEqual(len(peer.lookups),1);self.assertEqual(len(peer.requests),1)
            self.assertEqual(self.budget.summary()['requests'],1)
            self.assertEqual(len(self.budget.inspect_billing_observations(key)),1)

    def test_missing_bill_stays_unknown_and_two_observations_survive_reopen(self):
        with F['MessagesPeer'](missing_bill=True) as peer:
            wire=self.wire(peer);key=self.request(wire)
            with self.assertRaises(RequestIdentityConflict):wire.observe_bill(key)
            self.reopen();wire=self.wire(peer)
            with self.assertRaises(RequestIdentityConflict):wire.observe_bill(key)
            self.reopen();wire=self.wire(peer)
            with self.assertRaises(BudgetExceeded):wire.observe_bill(key)
            self.assertEqual(len(peer.lookups),2);self.assertEqual(len(peer.requests),1)
            self.assertEqual(self.budget.inspect_request(key)['cost_state'],'unknown')
            self.assertEqual(self.budget.inspect_root()['cost']['unknown_reserved_usd'],'0.8')

    def test_interruption_before_get_consumes_observation_without_guessing_its_result(self):
        def interrupt(phase):
            if phase=='gateway_billing_observation_started':raise RuntimeError('controlled observation interruption')
        with F['MessagesPeer']() as peer:
            wire=self.wire(peer,checkpoint=interrupt);key=self.request(wire)
            with self.assertRaises(RuntimeError):wire.observe_bill(key)
            self.reopen();wire=self.wire(peer);wire.observe_bill(key)
            observations=self.budget.inspect_billing_observations(key)
            self.assertEqual(len(observations),2);self.assertIsNone(observations[0]['observation'])
            self.assertEqual(len(peer.lookups),1);self.assertEqual(len(peer.requests),1)

    def test_interruption_after_receipt_reuses_exact_bytes_without_second_get(self):
        def interrupt(phase):
            if phase=='gateway_billing_observation_committed':raise RuntimeError('controlled receipt interruption')
        with F['MessagesPeer']() as peer:
            wire=self.wire(peer,checkpoint=interrupt);key=self.request(wire)
            with self.assertRaises(RuntimeError):wire.observe_bill(key)
            self.assertEqual(self.budget.inspect_request(key)['cost_state'],'unknown')
            self.reopen();wire=self.wire(peer);wire.observe_bill(key)
            self.assertEqual(self.budget.inspect_request(key)['cost_state'],'settled')
            self.assertEqual(len(peer.lookups),1);self.assertEqual(len(peer.requests),1)

    def test_missing_generation_cannot_guess_id_or_query(self):
        with F['MessagesPeer'](missing_identity=True) as peer:
            wire=self.wire(peer);key=self.request(wire)
            with self.assertRaises(ValueError):wire.observe_bill(key)
            self.assertEqual(peer.lookups,[]);self.assertEqual(self.budget.inspect_billing_observations(key),[])

    def test_scope_cannot_lookup_another_scopes_response(self):
        with F['MessagesPeer']() as peer:
            wire=self.wire(peer);key=self.request(wire)
            other=GatewayHTTP(self.budget,self.args['scopes'][0]['scope_id'],endpoint=peer.endpoint,origin='synthetic',
                credential='uteki-synthetic-gateway',deadline=time.monotonic()+10,before_request=lambda req:None)
            self.addCleanup(other.close)
            with self.assertRaises(RequestIdentityConflict):other.observe_bill(key)
            self.assertEqual(peer.lookups,[])

    def test_stopped_scope_can_reconcile_cost_but_cannot_dispatch_again(self):
        with F['MessagesPeer']() as peer:
            wire=self.wire(peer);key=self.request(wire)
            self.budget.stop_scope(self.scope['scope_id'],'cancelled')
            wire.observe_bill(key)
            with self.assertRaises(BudgetExceeded):self.request(wire)
            self.assertEqual(len(peer.lookups),1);self.assertEqual(len(peer.requests),1)
