"""An interrupted, never-dispatched root can finish its original initialization."""
from pathlib import Path
from copy import deepcopy
import runpy
import sys
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.service import DataService
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)
PROFILE=dict(kernel='clock_fixture')

class RuntimeInitializationTests(unittest.TestCase):
    def fixture(self):
        case=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']()
        case.setUp();self.addCleanup(case.doCleanups);case.catalog.close()
        return case

    def interrupted(self,case,phase,*,recover=False,returncode=79):
        path=case.root/(phase+'.log')
        with path.open('w') as log:
            command=[sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_initialization_worker.py'),
                str(case.root),case.context,phase]+(['recover'] if recover else [])
            worker=ObservedWorker(command,cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=20)
        self.assertEqual(observed['returncode'],returncode,path.read_text())
        return worker

    def test_initialization_intents_resume_same_identity_without_model_request(self):
        for phase in ('native_initialization_saved','root_initialization_saved',
                'runtime_ledger_image_created','runtime_ledger_image_saved','runtime_ledger_temporary_written',
                'runtime_ledger_linked','runtime_ledger_published','root_initialization_ready'):
            with self.subTest(phase=phase):
                case=self.fixture();worker=self.interrupted(case,phase)
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    # Before link these are private unfinished inputs. After
                    # link, an unremoved temporary name aliases the ledger;
                    # writing it is ledger corruption, covered separately.
                    residuals=(list((case.root/Path(before['native_execution']['ledger_path']).parent).glob('.initial-ledger-*'))
                        if phase=='runtime_ledger_temporary_written' else [])
                    for residual in residuals:residual.write_bytes(b'ignored interrupted temporary input')
                    worker.record(catalog,case.context)
                    journal=RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
                    after=Session(catalog,case.context).data
                    self.assertIsNone(journal.cached)
                    self.assertEqual(after['native_execution']['native_session_id'],before['native_execution']['native_session_id'])
                    self.assertEqual(after['context'],before['context'])
                    self.assertEqual(after['native_execution']['phase'],'active')
                    self.assertGreater(after['wall_seconds'],before['wall_seconds'])
                    self.assertEqual(journal.budget.summary()['requests'],0)
                    self.assertEqual(journal.budget.inspect_root()['root_run_id'],before['context']['root_run_id'])
                    image=ObjectRef.model_validate(after['native_execution']['initialization']['ledger_image'])
                    raw=catalog.content.read_object(image)
                    journal.budget.prepare_request('first',{'context_ref':case.context},reserve_usd='0')
                    self.assertEqual(catalog.content.read_object(image),raw,'writable ledger must not alias immutable input')
                    self.assertEqual(len(list((case.root/'runs').rglob('budget.sqlite'))),1)
                    for residual in residuals:self.assertEqual(residual.read_bytes(),b'ignored interrupted temporary input')

    def test_controlled_publication_failure_can_confirm_same_frozen_input(self):
        for phase in ('runtime_ledger_temporary_written','runtime_ledger_linked'):
            with self.subTest(phase=phase):
                case=self.fixture();worker=self.interrupted(case,'failure:'+phase,returncode=1)
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    image=before['native_execution']['initialization']['ledger_image']
                    raw=catalog.content.read_object(ObjectRef.model_validate(image))
                    worker.record(catalog,case.context)
                    journal=RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
                    self.assertIsNone(journal.cached)
                    self.assertEqual(journal.state()['initialization']['ledger_image'],image)
                    self.assertEqual(catalog.content.read_object(ObjectRef.model_validate(image)),raw)
                    self.assertEqual(journal.budget.summary()['requests'],0)

    def test_old_initialization_without_creation_proof_cannot_create_a_ledger(self):
        case=self.fixture();worker=self.interrupted(case,'native_initialization_saved')
        with Catalog.open(case.root) as catalog:
            worker.record(catalog,case.context)
            session=Session(catalog,case.context)
            session.data['native_execution'].pop('initialization');session.save()
            with self.assertRaises(CatalogError) as caught:
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertIn('legacy initialization',str(caught.exception))
            self.assertFalse((case.root/session.data['native_execution']['ledger_path']).exists())
            self.assertEqual(Session(catalog,case.context).head_ref,session.head_ref)

    def test_corrupt_frozen_initial_image_is_not_rebuilt_or_published(self):
        case=self.fixture();worker=self.interrupted(case,'runtime_ledger_image_saved')
        with Catalog.open(case.root) as catalog:
            data=Session(catalog,case.context).data
            reference=ObjectRef.model_validate(data['native_execution']['initialization']['ledger_image'])
            image=case.root/'objects/sha256'/reference.sha256[:2]/reference.sha256
            image.chmod(0o600);image.write_bytes(b'corrupt original initialization input')
            worker.record(catalog,case.context)
            with self.assertRaises(ValueError) as caught:
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertIn('OBJECT_CORRUPT',str(caught.exception))
            self.assertFalse((case.root/data['native_execution']['ledger_path']).exists())
            self.assertEqual(image.read_bytes(),b'corrupt original initialization input')

    def test_linked_unconfirmed_ledger_damage_is_not_replaced_from_initial_image(self):
        case=self.fixture();worker=self.interrupted(case,'runtime_ledger_linked')
        with Catalog.open(case.root) as catalog:
            data=Session(catalog,case.context).data
            ledger=case.root/data['native_execution']['ledger_path']
            residuals=list(ledger.parent.glob('.initial-ledger-*'))
            self.assertEqual(len(residuals),1)
            self.assertEqual(ledger.stat().st_ino,residuals[0].stat().st_ino)
            reference=ObjectRef.model_validate(data['native_execution']['initialization']['ledger_image'])
            original=catalog.content.read_object(reference)
            residuals[0].write_bytes(b'damaged published ledger through its temporary alias')
            worker.record(catalog,case.context)
            with self.assertRaises(CatalogError) as caught:
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertIn('unconfirmed initial ledger differs',str(caught.exception))
            self.assertEqual(ledger.read_bytes(),b'damaged published ledger through its temporary alias')
            self.assertEqual(catalog.content.read_object(reference),original)

    def test_missing_observation_and_unrelated_existing_ledger_never_initialize(self):
        case=self.fixture();worker=self.interrupted(case,'native_initialization_saved')
        with Catalog.open(case.root) as catalog:
            original=Session(catalog,case.context)
            path=case.root/original.data['native_execution']['ledger_path']
            with self.assertRaises(CatalogError):
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertEqual(Session(catalog,case.context).head_ref,original.head_ref)
            self.assertFalse(path.exists())
            worker.record(catalog,case.context)
            path.write_bytes(b'unrelated ledger')
            with self.assertRaises(CatalogError):
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertEqual(path.read_bytes(),b'unrelated ledger')
            self.assertNotIn('root_budget',Session(catalog,case.context).data)

    def test_enabled_ledger_missing_corrupt_or_already_used_cannot_reset(self):
        for alteration in ('missing','corrupt','used'):
            with self.subTest(alteration=alteration):
                case=self.fixture();worker=self.interrupted(case,'root_initialization_ready')
                with Catalog.open(case.root) as catalog:
                    before=Session(catalog,case.context).data
                    path=case.root/before['native_execution']['ledger_path']
                    if alteration=='missing':path.unlink()
                    elif alteration=='corrupt':path.write_bytes(b'damaged activated ledger')
                    else:
                        ledger=RunBudget.open_existing(path,'0',root_run_id=before['context']['root_run_id'])
                        ledger.prepare_request('uncertain-original',{'context_ref':case.context},reserve_usd='0')
                        ledger.begin_request('uncertain-original')
                    raw=path.read_bytes() if path.exists() else None
                    worker.record(catalog,case.context)
                    with self.assertRaises(CatalogError):
                        RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
                    self.assertEqual(path.read_bytes() if path.exists() else None,raw)
                    self.assertEqual(Session(catalog,case.context).data['native_execution']['native_session_id'],
                        before['native_execution']['native_session_id'])

    def test_recovery_host_exit_requires_its_own_observation_and_keeps_original_root(self):
        case=self.fixture();original=self.interrupted(case,'native_initialization_saved')
        with Catalog.open(case.root) as catalog:original.record(catalog,case.context)
        recovery=self.interrupted(case,'root_initialization_ready',recover=True)
        with Catalog.open(case.root) as catalog:
            before=Session(catalog,case.context)
            ledger_path=case.root/before.data['native_execution']['ledger_path']
            raw=ledger_path.read_bytes()
            with self.assertRaises(CatalogError):
                RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertEqual(Session(catalog,case.context).head_ref,before.head_ref)
            recovery.record(catalog,case.context)
            journal=RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            self.assertIsNone(journal.cached)
            self.assertEqual(ledger_path.read_bytes(),raw)
            self.assertEqual(journal.budget.summary()['requests'],0)
            native=journal.state()
            self.assertEqual(native['native_session_id'],before.data['native_execution']['native_session_id'])
            attempts=native['execution_segments'][-1]['recovery_attempts']
            self.assertEqual([a['status'] for a in attempts],['reconciled','completed'])

    def test_first_sdk_child_can_finish_root_initialization_without_changing_parent(self):
        case=self.fixture()
        with Catalog.open(case.root) as catalog:
            service=DataService(catalog)
            state=dict(satisfied=[],gaps=[dict(need_id='cash',missing='Explicit scope needed')],
                next_action='clarify',reason='Synthetic scope question',
                plan_update=dict(base_version=0,needs=[dict(need_id='cash',description='Synthetic cash',required=True)]))
            parent=case.context
            question=service.clarify(parent,dict(question='Use this scope?',blocking_need_ids=['cash']),
                state=state,request_key='ask')
            request=deepcopy(case.request)|dict(revises_context_ref=parent,
                clarification_response=dict(clarification_id=question['clarification']['clarification_id'],answer='Yes.'))
            case.context=service.create_context(request,request_key='child')['context_ref']
        worker=self.interrupted(case,'runtime_ledger_linked')
        with Catalog.open(case.root) as catalog:
            worker.record(catalog,case.context)
            journal=RuntimeJournal(DataService(catalog),case.context,PROFILE,LIMITS,recover=True)
            root=Session(catalog,parent).data
            self.assertNotIn('native_execution',root)
            self.assertEqual(journal.budget.inspect_root()['root_run_id'],root['context']['run_id'])
            self.assertEqual(root['root_budget']['initialization']['context_ref'],case.context)
            self.assertEqual(root['root_budget']['initialization']['status'],'ready')
            self.assertEqual(len(list((case.root/'runs').rglob('budget.sqlite'))),1)

if __name__=='__main__':unittest.main()
