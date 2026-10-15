"""The application entry does not infer a model or bypass host admission."""
from pathlib import Path
import runpy
import unittest

from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

F=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))


class QueryAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case=F['DataToolTests']();self.case.setUp();self.addCleanup(self.case.doCleanups)

    async def test_unconfigured_query_has_no_implicit_model_or_native_execution(self):
        before=Session(self.case.catalog,self.case.context).head_ref
        with self.assertRaises(CatalogError) as raised:
            await self.case.service.run_query(self.case.context)
        self.assertEqual(raised.exception.code,'CAPABILITY_UNSUPPORTED')
        self.assertEqual(Session(self.case.catalog,self.case.context).head_ref,before)
        self.assertNotIn('native_execution',Session(self.case.catalog,self.case.context).data)

    async def test_invalid_recovery_or_closed_catalog_cannot_invoke_runtime(self):
        called=[]
        async def unexpected(*args,**kwargs):called.append(True);raise AssertionError('runtime was invoked')
        service=DataService(self.case.catalog,query_runtime=unexpected)
        with self.assertRaises(CatalogError) as raised:await service.run_query(self.case.context,recover='yes')
        self.assertEqual(raised.exception.code,'INVALID_REQUEST')
        with self.assertRaises(CatalogError):DataService(self.case.catalog,query_runtime=object())
        self.case.catalog.close()
        with self.assertRaises(CatalogError) as raised:await service.run_query(self.case.context)
        self.assertEqual(raised.exception.code,'INVALID_STATE')
        self.assertEqual(called,[])


if __name__=='__main__':unittest.main()
