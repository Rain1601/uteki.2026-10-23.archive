"""Actual process exits preserve source receipts and the original publication."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]


class AcquisitionRecoveryProcessTests(unittest.TestCase):
    def test_process_exit_receipts_publication_and_response_recovery(self):
        cls=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_tool_acquisition.py'))['ToolAcquisitionTests']
        early={'before_acquisition':0,'acquisition_main_receipt':1,'acquisition_received':2,'acquisition_snapshot_frozen':2}
        for phase in (*early,'before_build_commit','after_build_commit','acquisition_build_published','tool_response_prepared','response_committed'):
            with self.subTest(phase=phase):
                f=cls();f.setUp()
                try:
                    transport=Mock(side_effect=AssertionError('recovery fetched again'))
                    _,context=f.service(transport)
                    args=dict(context_ref=context,tool='request_asset_update',request=f.request,state=f.state,request_key='original')
                    invocation=f.root/'invocation.json';invocation.write_text(json.dumps(dict(plan=f.plan,**args)))
                    f.catalog.close()
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/acquisition_worker.py'),
                        str(f.root),str(invocation),phase],cwd=f.root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(child.returncode,73,child.stderr[-3000:])
                    count=len(json.loads((f.root/'fixture-transport.json').read_text())) if (f.root/'fixture-transport.json').exists() else 0
                    self.assertEqual(count,early.get(phase,2))
                    with Catalog.open(f.root) as catalog:
                        service=DataService(catalog,acquisition_adapter=OfficialAcquisitionAdapter([f.plan],settings_root=f.root,fetch=transport))
                        before=Session(catalog,context);operation=next(iter(before.data['operations'].values()))
                        identities=list(catalog._db.execute('SELECT build_id,snapshot_id,job_id FROM asset_builds'))
                        with patch('uteki.data_platform.connectors.updates.build_html',side_effect=AssertionError('recovery rebuilt')):
                            if phase in early:
                                with self.assertRaises(CatalogError) as caught:service.call(**args,recover=True)
                                self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                                self.assertEqual(Session(catalog,context).head_ref,before.head_ref)
                                if phase=='acquisition_main_receipt':
                                    receipt=json.loads(catalog.content.read_object(ObjectRef.model_validate(operation['effect_intent']['target']['receipt_ref'])))
                                    self.assertEqual(receipt['requests'],1)
                                    self.assertEqual(len([r for r in receipt['discovery'] if r['status']=='fetched']),1)
                            else:
                                result=service.call(**args,recover=True)
                                self.assertEqual(service.call(**args,recover=True),result)
                                self.assertEqual(result['items'][0]['update_id'],identities[0]['job_id'])
                                self.assertEqual(result['items'][0]['new_asset_refs'][0]['build_id'],identities[0]['build_id'])
                                after=Session(catalog,context)
                                self.assertEqual(after.data['turns'],before.data['turns'])
                                if phase in {'tool_response_prepared','response_committed'}:
                                    self.assertEqual(result,operation['response_intent']['response'])
                                    self.assertEqual(after.data['wall_seconds'],operation['response_intent']['wall_seconds'])
                                else:
                                    self.assertTrue(after.data['execution_time_uncertain'])
                                    self.assertIsNone(result['resource_usage']['elapsed_ms'])
                            self.assertEqual([tuple(r) for r in catalog._db.execute('SELECT build_id,snapshot_id,job_id FROM asset_builds')],[tuple(r) for r in identities])
                        transport.assert_not_called()
                finally:f.doCleanups()


if __name__=='__main__':unittest.main()
