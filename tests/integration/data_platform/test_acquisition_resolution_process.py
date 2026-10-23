"""Explicit local completion/closure after actual observed process exits."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import Mock

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.contracts.assets import AssetRef
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.retrieval.content import HtmlReader
from uteki.data_platform.service import DataService
from uteki.data_platform.application.run_budget import RunBudget

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT/'tests/fixtures/data_platform/acquisition_resolution_worker.py'


class AcquisitionResolutionProcessTests(unittest.TestCase):
    def fixture(self, phase):
        cls = runpy.run_path(str(ROOT/'tests/unit/data_platform/test_tool_acquisition.py'))['ToolAcquisitionTests']
        f = cls();f.setUp();self.addCleanup(f.doCleanups)
        _,f.context = f.service(Mock(side_effect=AssertionError('unexpected fetch')))
        f.invocation = f.root/'invocation.json'
        f.invocation.write_text(json.dumps(dict(plan=f.plan,context_ref=f.context,tool='request_asset_update',
            request=f.request,state=f.state,request_key='original')))
        f.catalog.close()
        self.run_worker(f,'acquire',phase,expected=73)
        return f

    def run_worker(self, f, mode, phase='none', *, expected=0, record=True):
        with (f.root/'worker.log').open('w') as log:
            worker = ObservedWorker([sys.executable,'-I',str(WORKER),str(f.root),str(f.invocation),mode,phase],
                cwd=str(f.root),env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observation = worker.wait(timeout=30)
        self.assertEqual(observation['returncode'],expected,(f.root/'worker.log').read_text()[-4000:])
        with Catalog.open(f.root) as catalog:
            native = Session(catalog,f.context).data['native_execution']
            if record and native['owner_pid']==worker.child.pid:worker.record(catalog,f.context)
        return json.loads((f.root/'resolution-result.json').read_bytes()) if expected==0 else None

    def operation(self, catalog, context):
        return next(iter(Session(catalog,context).data['operations'].values()))

    def assert_original_bytes(self, f, catalog, result):
        fixture = runpy.run_path(str(ROOT/'tests/fixtures/data_platform/html_fixture.py'))
        reader = HtmlReader(catalog,AssetRef.model_validate(result['items'][0]['new_asset_refs'][0]))
        self.assertEqual(catalog.content.read_object(reader.inputs.main),fixture['source']())
        self.assertTrue(reader.inventory()['records'])
        self.assertEqual(len(json.loads((f.root/'fixture-transport.json').read_bytes())),2)

    def test_local_continue_reuses_inputs_identities_and_usage_at_eight_exit_positions(self):
        phases=('acquisition_received','before_snapshot_freeze','snapshot_before_move','acquisition_snapshot_frozen',
                'build_artifact_write_2','before_build_seal','build_before_move','before_build_commit')
        for phase in phases:
            with self.subTest(phase=phase):
                f = self.fixture(phase)
                with Catalog.open(f.root) as catalog:
                    before = Session(catalog,f.context).data
                    op = self.operation(catalog,f.context)
                    identities = [tuple(r) for r in catalog._db.execute('SELECT snapshot_id,build_id,job_id FROM asset_builds')]
                value = self.run_worker(f,'continue_local')
                self.assertIn('result',value,value)
                result = value['result'];self.assertEqual(result['status'],'ok',result)
                with Catalog.open(f.root) as catalog:
                    self.assert_original_bytes(f,catalog,result)
                    after = Session(catalog,f.context)
                    self.assertEqual(after.data['turns'],before['turns'])
                    self.assertEqual(result['operation_id'],op['operation_id'])
                    self.assertEqual(result['resource_usage']['transport_requests'],2)
                    self.assertGreater(after.data['wall_seconds'],before['wall_seconds'])
                    self.assertEqual(len(after.data['native_execution']['execution_segments']),1)
                    newids = [tuple(r) for r in catalog._db.execute('SELECT snapshot_id,build_id,job_id FROM asset_builds')]
                    if identities:self.assertEqual(newids,identities)
                    service=DataService(catalog)
                    self.assertEqual(service.resolve_update(f.context,request_key=op['request_key'],action='continue_local'),result)
                    self.assertEqual(Session(catalog,f.context).head_ref,after.head_ref)

    def test_close_preserves_partial_bytes_and_unknown_transport(self):
        phases=('before_acquisition','transport_inflight','acquisition_main_receipt','acquisition_received',
                'snapshot_representation_write','acquisition_snapshot_frozen','build_artifact_write_2','before_build_seal')
        for phase in phases:
            with self.subTest(phase=phase):
                f=self.fixture(phase)
                frozen={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (f.root/'acquisitions').rglob('*') if p.is_file()}
                value=self.run_worker(f,'close');self.assertIn('result',value,value)
                result=value['result'];self.assertEqual(result['error']['code'],'ACQUISITION_CLOSED')
                self.assertEqual(result['error']['details']['transport_outcome_unknown'],phase=='transport_inflight')
                self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen},frozen)
                with Catalog.open(f.root) as catalog:
                    operation=self.operation(catalog,f.context)
                    self.assertEqual(operation['status'],'completed')
                    self.assertEqual(operation['resolution']['action'],'close')
                    self.assertEqual(catalog._db.execute("SELECT COUNT(*) FROM asset_builds WHERE status='staging'").fetchone()[0],0)
                    self.assertEqual(catalog._db.execute("SELECT COUNT(*) FROM asset_snapshots WHERE status='collecting'").fetchone()[0],0)
                    self.assertEqual(DataService(catalog).resolve_update(f.context,request_key=operation['request_key'],action='close'),result)
                    if phase=='acquisition_main_receipt':self.assertEqual(result['resource_usage']['transport_requests'],1)

    def test_continuation_can_itself_exit_and_resume_same_build_without_new_transport(self):
        f=self.fixture('acquisition_received')
        self.run_worker(f,'continue_local','before_build_seal',expected=73)
        with Catalog.open(f.root) as catalog:
            previous=Session(catalog,f.context).data['wall_seconds']
            identity=tuple(catalog._db.execute('SELECT build_id,job_id FROM asset_builds').fetchone())
        result=self.run_worker(f,'continue_local')['result']
        with Catalog.open(f.root) as catalog:
            self.assert_original_bytes(f,catalog,result)
            self.assertEqual(identity,tuple(catalog._db.execute('SELECT build_id,job_id FROM asset_builds').fetchone()))
            after=Session(catalog,f.context).data
            self.assertGreater(after['wall_seconds'],previous)
            self.assertEqual(len(after['native_execution']['execution_segments']),2)

    def test_close_is_reentrant_after_actual_candidate_close_exit(self):
        f=self.fixture('build_artifact_write_2')
        self.run_worker(f,'close','resolution_build_closed',expected=73)
        result=self.run_worker(f,'close')['result']
        self.assertEqual(result['error']['code'],'ACQUISITION_CLOSED')
        with Catalog.open(f.root) as catalog:
            self.assertEqual(catalog._db.execute("SELECT COUNT(*) FROM runs WHERE kind='build' AND request_key LIKE 'acquisition:%' AND status='failed'").fetchone()[0],1)

    def test_incomplete_inputs_changed_binding_and_stopped_root_cannot_continue(self):
        for case in ('incomplete','changed_binding','stopped','unknown_request','missing_observation','missing_input'):
            with self.subTest(case=case):
                f=self.fixture('acquisition_main_receipt' if case=='incomplete' else 'acquisition_received')
                with Catalog.open(f.root) as catalog:
                    session=Session(catalog,f.context);op=self.operation(catalog,f.context)
                    if case in {'stopped','unknown_request'}:
                        ledger=RunBudget.open_existing(catalog.root/session.data['native_execution']['ledger_path'],'0',
                            root_run_id=session.data['context']['root_run_id'])
                        if case=='stopped':ledger.stop_root('cancelled')
                        else:
                            ledger.prepare_request('unknown-synthetic',dict(synthetic=True),reserve_usd='0')
                            ledger.begin_request('unknown-synthetic')
                    elif case=='missing_observation':
                        session.data['native_execution'].pop('exit_observation');session.save()
                    elif case=='missing_input':
                        inputs=catalog.content.read_manifest(ObjectRef.model_validate(op['effect_intent']['target']['input_ref']))
                        catalog.content._path(inputs.main).unlink()
                if case=='changed_binding':
                    value=json.loads(f.invocation.read_bytes());value['plan']['config']['limits']['max_requests']=4
                    f.invocation.write_text(json.dumps(value))
                value=self.run_worker(f,'continue_local')
                self.assertIn('error',value,value)
                with Catalog.open(f.root) as catalog:
                    self.assertEqual(catalog._db.execute('SELECT COUNT(*) FROM asset_builds').fetchone()[0],0)
                    self.assertEqual(self.operation(catalog,f.context)['status'],'accepted')

    def test_sealed_damage_is_not_rebuilt_and_can_be_explicitly_closed(self):
        f=self.fixture('build_before_move')
        with Catalog.open(f.root) as catalog:
            build=dict(catalog._db.execute('SELECT * FROM asset_builds').fetchone())
            path=catalog.root/'staging'/build['job_id']/'blocks.jsonl'
            path.chmod(0o644);path.write_bytes(b'damaged synthetic artifact')
        value=self.run_worker(f,'continue_local')
        self.assertIn('error',value,value)
        self.assertEqual(path.read_bytes(),b'damaged synthetic artifact')
        result=self.run_worker(f,'close')['result']
        self.assertEqual(result['error']['code'],'ACQUISITION_CLOSED')
        with Catalog.open(f.root) as catalog:
            op=self.operation(catalog,f.context)
            self.assertEqual(op['resolution_history'][0]['action'],'continue_local')
            self.assertEqual(catalog.get_build(build['build_id'])['status'],'failed')

    def test_closure_cannot_revoke_a_final_publication(self):
        f=self.fixture('before_build_commit')
        value=self.run_worker(f,'close')
        self.assertEqual(value['error']['code'],'RECOVERY_REQUIRED')
        with Catalog.open(f.root) as catalog:
            op=self.operation(catalog,f.context)
            fetch=Mock(side_effect=AssertionError('must not fetch'))
            service=DataService(catalog,acquisition_adapter=OfficialAcquisitionAdapter([f.plan],settings_root=f.root,fetch=fetch))
            result=service.call(f.context,op['tool'],op['request'],state=op['state'],request_key=op['request_key'],recover=True)
            self.assert_original_bytes(f,catalog,result)
            fetch.assert_not_called()

    def test_continue_after_published_or_prepared_response_keeps_original_response(self):
        for phase in ('resolution_build_published','resolution_response_prepared','resolution_response_committed'):
            with self.subTest(phase=phase):
                f=self.fixture('acquisition_received')
                self.run_worker(f,'continue_local',phase,expected=73)
                with Catalog.open(f.root) as catalog:
                    op=self.operation(catalog,f.context)
                    intent=deepcopy(op.get('response_intent'))
                    identities=[tuple(r) for r in catalog._db.execute('SELECT snapshot_id,build_id,job_id FROM asset_builds')]
                value=self.run_worker(f,'continue_local');self.assertIn('result',value,value)
                with Catalog.open(f.root) as catalog:
                    self.assert_original_bytes(f,catalog,value['result'])
                    self.assertEqual(identities,[tuple(r) for r in catalog._db.execute('SELECT snapshot_id,build_id,job_id FROM asset_builds')])
                    if intent:self.assertEqual(value['result'],intent['response'])

    def test_legacy_partial_receipt_closes_with_unknown_transport_retained(self):
        f=self.fixture('acquisition_main_receipt')
        with Catalog.open(f.root) as catalog:
            session=Session(catalog,f.context);op=next(iter(session.data['operations'].values()))
            target=op['effect_intent']['target']
            raw=catalog.content.read_object(ObjectRef.model_validate(target['receipt_ref']))
            receipt=json.loads(raw);receipt.pop('transport_journal_version');receipt.pop('transport_state')
            target['receipt_ref']=catalog.content.put_object(canonical(receipt)).model_dump(mode='json')
            target.pop('transport_journal_version');session.save()
        result=self.run_worker(f,'close')['result']
        self.assertTrue(result['error']['details']['transport_outcome_unknown'])
        self.assertEqual(result['resource_usage']['transport_requests'],1)

    def test_close_detects_missing_or_damaged_original_instead_of_claiming_retention(self):
        for damage in ('missing','corrupt'):
            with self.subTest(damage=damage):
                f=self.fixture('acquisition_main_receipt')
                with Catalog.open(f.root) as catalog:
                    op=self.operation(catalog,f.context)
                    receipt=json.loads(catalog.content.read_object(ObjectRef.model_validate(op['effect_intent']['target']['receipt_ref'])))
                    item=next(r for r in receipt['discovery'] if r['status']=='fetched')
                    path=catalog.root/'acquisitions'/op['operation_id']/item['path']
                    if damage=='missing':path.unlink()
                    else:path.chmod(0o644);path.write_bytes(b'corrupt synthetic original')
                value=self.run_worker(f,'close')
                self.assertEqual(value['error']['code'],'RECOVERY_REQUIRED',value)
                with Catalog.open(f.root) as catalog:self.assertEqual(self.operation(catalog,f.context)['status'],'accepted')

    def test_legacy_synchronous_close_charges_lower_bound_once_and_keeps_unknown_time(self):
        cls=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_tool_acquisition.py'))['ToolAcquisitionTests']
        f=cls();f.setUp();self.addCleanup(f.doCleanups)
        _,context=f.service(Mock(side_effect=AssertionError('must not fetch')))
        invocation=f.root/'invocation.json'
        invocation.write_text(json.dumps(dict(plan=f.plan,context_ref=context,tool='request_asset_update',
            request=f.request,state=f.state,request_key='original')))
        f.catalog.close()
        child=subprocess.run([sys.executable,'-I',str(WORKER.with_name('acquisition_worker.py')),
            str(f.root),str(invocation),'acquisition_main_receipt'],cwd=f.root,env={'PATH':'/usr/bin:/bin'},
            capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,73,child.stderr)
        with Catalog.open(f.root) as catalog:
            before=Session(catalog,context).data
            op=self.operation(catalog,context)
            lower=op['elapsed_lower_bound']
            self.assertGreater(lower,0)
            service=DataService(catalog)
            result=service.resolve_update(context,request_key='original',action='close')
            after=Session(catalog,context)
            self.assertTrue(after.data['execution_time_uncertain'])
            self.assertTrue(result['resource_usage']['execution_time_uncertain'])
            self.assertGreaterEqual(after.data['wall_seconds'],before['wall_seconds']+lower)
            self.assertEqual(result['resource_usage']['original_elapsed_lower_bound_ms'],round(lower*1000,3))
            self.assertEqual(service.resolve_update(context,request_key='original',action='close'),result)
            self.assertEqual(Session(catalog,context).head_ref,after.head_ref)


if __name__=='__main__':unittest.main()
