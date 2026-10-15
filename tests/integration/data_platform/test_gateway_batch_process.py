"""True process exits retain the one batch ledger and exact native identity."""
import json
from pathlib import Path
import runpy
import sys
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_batch import create_gateway_batch, load_gateway_binding
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]


class GatewayBatchProcessTests(unittest.TestCase):
    def fixture(self):
        case,args=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_gateway_batch.py'))['fixture']()
        self.addCleanup(case.doCleanups)
        return case,args

    def interrupted(self,case,args,mode,phase):
        spec=case.root/'batch-spec.json';spec.write_text(json.dumps(args))
        case.catalog.close()
        with (case.root/'worker.log').open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/gateway_batch_worker.py'),
                str(case.root),str(spec),mode,phase],cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=20)
        self.assertEqual(observed['returncode'],87,(case.root/'worker.log').read_text())
        self.assertTrue(observed['process_group_empty'])
        return worker

    def test_batch_creation_interruptions_finish_same_frozen_empty_ledger(self):
        for phase in ('gateway_batch_intent_saved','runtime_ledger_temporary_written',
                'gateway_batch_ledger_published','gateway_batch_ready'):
            with self.subTest(phase=phase):
                case,args=self.fixture();self.interrupted(case,args,'batch',phase)
                with Catalog.open(case.root) as catalog:
                    if phase!='gateway_batch_ready':
                        with self.assertRaises(CatalogError):create_gateway_batch(catalog,**args)
                    bindings=create_gateway_batch(catalog,**args,recover=True)
                    scope=args['scopes'][0]
                    gateway=load_gateway_binding(Session(catalog,scope['context_ref']),bindings[scope['scope_id']],scope['profile'],scope['limits'])
                    self.assertEqual(gateway['budget'].summary()['requests'],0)
                    self.assertEqual(gateway['budget'].inspect_root()['root_run_id'],args['batch_id'])
                    self.assertEqual(len(list((case.root/'gateway-batches').rglob('budget.sqlite'))),1)
                    self.assertNotIn('native_execution',Session(catalog,scope['context_ref']).data)

    def test_business_initialization_recovers_original_identity_without_creating_a_ledger(self):
        for phase in ('native_initialization_saved','root_initialization_saved','root_initialization_ready'):
            with self.subTest(phase=phase):
                case,args=self.fixture();bindings=create_gateway_batch(case.catalog,**args)
                worker=self.interrupted(case,args,'journal',phase)
                with Catalog.open(case.root) as catalog:
                    scope=args['scopes'][0];before=Session(catalog,scope['context_ref']).data
                    worker.record(catalog,scope['context_ref'])
                    journal=RuntimeJournal(DataService(catalog),scope['context_ref'],scope['profile'],scope['limits'],
                        gateway_binding=bindings[scope['scope_id']],recover=True)
                    self.assertIsNone(journal.cached);self.assertEqual(journal.state()['phase'],'active')
                    self.assertEqual(journal.state()['native_session_id'],before['native_execution']['native_session_id'])
                    self.assertEqual(journal.budget.summary()['requests'],0)
                    self.assertEqual(len(list(case.root.rglob('budget.sqlite'))),1)
                    self.assertNotIn('native_execution',Session(catalog,args['scopes'][1]['context_ref']).data)

    def test_dispatched_request_recovers_unknown_in_original_scope_and_ledger(self):
        case,args=self.fixture();bindings=create_gateway_batch(case.catalog,**args)
        worker=self.interrupted(case,args,'request','physical_request_dispatched')
        with Catalog.open(case.root) as catalog:
            scope=args['scopes'][0];before=Session(catalog,scope['context_ref']).data
            worker.record(catalog,scope['context_ref'])
            journal=RuntimeJournal(DataService(catalog),scope['context_ref'],scope['profile'],scope['limits'],
                gateway_binding=bindings[scope['scope_id']],recover=True)
            request=journal.budget.inspect_request('interrupted-physical-request')
            self.assertEqual(request['stage'],'outcome_unknown');self.assertEqual(request['cost_state'],'unknown')
            self.assertEqual(request['control_scope_id'],scope['scope_id'])
            self.assertEqual(journal.state()['native_session_id'],before['native_execution']['native_session_id'])
            self.assertEqual(journal.budget.summary()['held_usd'],'0.8')
            self.assertEqual(journal.cached['kind'],'recovery_required')
            self.assertEqual(journal.budget.summary()['requests'],1)


if __name__=='__main__':unittest.main()
