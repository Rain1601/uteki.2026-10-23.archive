"""Existing official publication is recovered; missing/damaged effects are not retried."""
from copy import deepcopy
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from uteki.data_platform.application.session import Session
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.assets import Acquisition
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.content.publication import Publication

A = runpy.run_path(str(Path(__file__).with_name('test_tool_acquisition.py')))


class ControlledExit(BaseException):
    pass


class AcquisitionRecoveryTests(unittest.TestCase):
    def fixture(self, *, missing=False):
        f=A['ToolAcquisitionTests']();f.setUp();self.addCleanup(f.doCleanups)
        def fetch(url,**kwargs):
            if url==A['F']['MAIN_URL']:return A['F']['source']()
            if missing:raise HTTPError(url,404,'Synthetic missing',{},io.BytesIO(b'absent'))
            return b'synthetic image'
        transport=Mock(side_effect=fetch)
        service,context=f.service(transport)
        args=dict(context_ref=context,tool='request_asset_update',request=f.request,state=f.state,request_key='interrupted')
        return f,service,args,transport

    def interrupt(self,service,args,phase):
        def stop(at):
            if at==phase:raise ControlledExit('controlled host exit')
        with self.assertRaises(ControlledExit):service.call(**args,checkpoint=stop)

    def test_existing_publication_keeps_identity_gaps_receipts_and_no_new_work(self):
        for phase,missing in [('before_build_commit',False),('after_build_commit',True),('acquisition_build_published',False)]:
            with self.subTest(phase=phase):
                f,service,args,transport=self.fixture(missing=missing)
                self.interrupt(service,args,phase)
                build=dict(f.catalog._db.execute('SELECT * FROM asset_builds').fetchone())
                other_run=f.catalog.start_run('unrelated-work',purpose='unrelated pending snapshot',kind='build')['run_id']
                metadata=json.loads(f.catalog.get_snapshot(build['snapshot_id'])['payload'])
                other=f.catalog.begin_snapshot('unrelated-snapshot',asset_id=f.plan['asset_id'],
                    acquisition=Acquisition.model_validate_json(json.dumps(metadata['acquisition'])),
                    completeness='unknown',version_consistency='unknown',revision_of_snapshot_id=None,revision_basis=None,run_id=other_run)
                with patch('uteki.data_platform.connectors.updates.acquire_html',side_effect=AssertionError('transport repeated')), \
                        patch('uteki.data_platform.connectors.updates.build_html',side_effect=AssertionError('build repeated')):
                    result=service.call(**args,recover=True)
                    self.assertEqual(service.call(**args,recover=True),result)
                self.assertEqual(transport.call_count,2)
                item=result['items'][0]
                self.assertEqual(item['update_id'],build['job_id'])
                self.assertEqual(item['new_asset_refs'],[f.catalog.asset_ref(build).model_dump(mode='json')])
                self.assertEqual(item['status'],'partial' if missing else 'completed')
                self.assertEqual(bool(item['gaps']),missing)
                self.assertEqual(f.catalog.get_build(build['build_id'])['status'],'published')
                self.assertEqual(f.catalog._get('runs','run_id',build['run_id'])['status'],'completed')
                self.assertEqual(f.catalog.get_snapshot(other)['status'],'collecting')
                self.assertEqual(f.catalog._get('runs','run_id',other_run)['status'],'running')
                self.assertIsNone(result['resource_usage']['elapsed_ms'])
                self.assertEqual(result['resource_usage']['transport_requests'],2)
                session=Session(f.catalog,args['context_ref'])
                self.assertTrue(session.data['execution_time_uncertain'])
                self.assertEqual(session.data['turns'],1)

    def test_received_inputs_without_publication_are_retained_not_activated(self):
        f,service,args,transport=self.fixture()
        self.interrupt(service,args,'acquisition_received')
        before=Session(f.catalog,args['context_ref'])
        operation=next(iter(before.data['operations'].values()))
        target=operation['effect_intent']['target']
        inputs=f.catalog.content.read_manifest(ObjectRef.model_validate(target['input_ref']))
        self.assertEqual(f.catalog.content.read_object(inputs.main),A['F']['source']())
        with self.assertRaises(CatalogError) as caught:service.call(**args,recover=True)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(Session(f.catalog,args['context_ref']).head_ref,before.head_ref)
        self.assertEqual(f.catalog._db.execute('SELECT count(*) FROM asset_builds').fetchone()[0],0)
        self.assertEqual(transport.call_count,2)

    def test_changed_plan_and_corrupt_original_build_cannot_be_adopted(self):
        f,service,args,transport=self.fixture()
        self.interrupt(service,args,'after_build_commit')
        plan=deepcopy(f.plan);plan['config']['limits']['max_requests']=4
        service.acquisition_adapter=OfficialAcquisitionAdapter([plan],settings_root=f.root,fetch=transport)
        self.assertEqual(service.call(**args,recover=True)['error']['code'],'IDEMPOTENCY_CONFLICT')
        service.acquisition_adapter=OfficialAcquisitionAdapter([f.plan],settings_root=f.root,fetch=transport)
        build=dict(f.catalog._db.execute('SELECT * FROM asset_builds').fetchone())
        path=Publication(f.catalog).build_path(build,final=True)/'blocks.jsonl'
        path.chmod(0o600);path.write_bytes(b'corrupt')
        with self.assertRaises(CatalogError) as caught:service.call(**args,recover=True)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(path.read_bytes(),b'corrupt')
        self.assertEqual(transport.call_count,2)

    def test_recovery_interrupted_after_response_intent_preserves_exact_response(self):
        f,service,args,transport=self.fixture()
        self.interrupt(service,args,'before_build_commit')
        def stop(phase):
            if phase=='tool_response_prepared':raise ControlledExit()
        with self.assertRaises(ControlledExit):service.call(**args,recover=True,checkpoint=stop)
        before=Session(f.catalog,args['context_ref'])
        operation=next(iter(before.data['operations'].values()))
        result=service.call(**args,recover=True)
        self.assertEqual(result,operation['response_intent']['response'])
        self.assertEqual(Session(f.catalog,args['context_ref']).data['wall_seconds'],operation['response_intent']['wall_seconds'])
        self.assertEqual(transport.call_count,2)

    def test_receipt_persistence_failure_is_fatal_not_a_missing_attachment(self):
        f,service,args,transport=self.fixture()
        from uteki.data_platform.application.tools import ToolExecution
        original=ToolExecution.prepare_acquisition
        def fail(executor,**target):
            if 'receipt_ref' in target and transport.call_count==2:
                raise OSError('synthetic receipt write failure')
            return original(executor,**target)
        with patch.object(ToolExecution,'prepare_acquisition',fail):
            with self.assertRaises(CatalogError) as caught:service.call(**args)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(transport.call_count,2)
        self.assertEqual(f.catalog._db.execute('SELECT count(*) FROM asset_builds').fetchone()[0],0)
        operation=next(iter(Session(f.catalog,args['context_ref']).data['operations'].values()))
        self.assertEqual(operation['status'],'accepted')
        self.assertIsNone(operation['response'])


if __name__=='__main__':unittest.main()
