"""Abrupt exits around index publication and response acknowledgement."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch

from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.retrieval.content import HtmlReader
from uteki.data_platform.retrieval.index import DerivedIndex
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]


class OperationRecoveryProcessTests(unittest.TestCase):
    def test_existing_index_and_prepared_response_recover_without_repeating_effect(self):
        cls=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']
        for phase in ('index_intent_prepared','index_head_visible','index_after_head','tool_response_prepared','response_committed'):
            with self.subTest(phase=phase):
                f=cls();f.setUp()
                try:
                    old=f.index.build()['generation']
                    request=dict(need_id='need-1',action='process',process=dict(asset_ref=f.reference.model_dump(mode='json'),
                        capabilities=['text_search','records']),reason='Explicit synthetic rebuild')
                    args=dict(context_ref=f.context,tool='request_asset_update',request=request,state=f.state('request_asset_update'),request_key='original')
                    invocation=f.root/'invocation.json';invocation.write_text(json.dumps(dict(method='call',**args)))
                    f.catalog.close()
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/tools_worker.py'),
                        str(f.root),str(invocation),phase],cwd=f.root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(child.returncode,73,child.stderr[-3000:])
                    with Catalog.open(f.root) as catalog:
                        service=DataService(catalog);index=DerivedIndex(catalog,HtmlReader(catalog,f.reference))
                        session=Session(catalog,f.context);operation=next(iter(session.data['operations'].values()))
                        before=index.current()[1]['generation']
                        directories=set(p.name for p in index.base.iterdir())
                        if phase=='index_intent_prepared':
                            self.assertEqual(before,old)
                            with self.assertRaises(CatalogError) as caught:service.call(**args,recover=True)
                            self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                        else:
                            with patch.object(DerivedIndex,'build',side_effect=AssertionError('index rebuilt')):
                                result=service.call(**args,recover=True)
                                self.assertEqual(service.call(**args,recover=True),result)
                            self.assertEqual(result['items'][0]['derived_generation'],before)
                            self.assertNotEqual(before,old)
                            after=Session(catalog,f.context)
                            self.assertEqual(after.data['turns'],session.data['turns'])
                            if phase in ('tool_response_prepared','response_committed'):
                                self.assertEqual(result,operation['response_intent']['response'])
                                self.assertEqual(after.data['wall_seconds'],operation['response_intent']['wall_seconds'])
                            else:
                                self.assertTrue(after.data['execution_time_uncertain'])
                                self.assertIsNone(result['resource_usage']['elapsed_ms'])
                        self.assertEqual(index.current()[1]['generation'],before)
                        self.assertEqual(set(p.name for p in index.base.iterdir()),directories)
                finally:f.doCleanups()


if __name__=='__main__':unittest.main()
