"""Recover existing responses/effects without creating evidence or side effects."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError


class ControlledExit(BaseException):
    """Simulate a host exit that cannot be mistaken for a tool error."""


class OperationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
        self.f.setUp();self.addCleanup(self.f.doCleanups)

    def process_args(self):
        return dict(need_id='need-1',action='process',process=dict(asset_ref=self.f.reference.model_dump(mode='json'),
            capabilities=['text_search','records']),reason='Explicit synthetic index')

    def interrupt(self,tool,request,phase):
        state=self.f.state(tool)
        def stop(at):
            if at==phase:raise ControlledExit('controlled host interruption')
        with self.assertRaises(ControlledExit):
            self.f.service.call(self.f.context,tool,request,state=state,request_key='original',checkpoint=stop)
        return dict(context_ref=self.f.context,tool=tool,request=request,state=state,request_key='original')

    def test_durable_response_keeps_same_result_refs_and_time_without_reading_again(self):
        block=next(b for b in self.f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        args=self.interrupt('read_evidence',dict(asset_ref=self.f.reference.model_dump(mode='json'),
            targets=[dict(block_id=block['id'])]),'tool_response_prepared')
        session=Session(self.f.catalog,self.f.context)
        operation=next(iter(session.data['operations'].values()))
        intent=deepcopy(operation['response_intent'])
        with patch('uteki.data_platform.application.tools.ToolExecution.execute',side_effect=AssertionError('tool repeated')):
            result=self.f.service.call(**args,recover=True)
            self.assertEqual(self.f.service.call(**args,recover=True),result)
        self.assertEqual(result,intent['response'])
        after=Session(self.f.catalog,self.f.context)
        self.assertEqual(after.data['wall_seconds'],intent['wall_seconds'])
        self.assertEqual(after.data['results'],session.data['results'])
        self.assertEqual(after.lookup(result['items'][0]['result_ref']),result['items'][0])

    def test_response_recovery_rejects_changed_parameters_and_new_request_keys(self):
        args=self.interrupt('find_assets',dict(filters={}),'tool_response_prepared')
        changed=dict(args,request=dict(filters={},limit=1))
        result=self.f.service.call(**changed,recover=True)
        self.assertEqual(result['error']['code'],'IDEMPOTENCY_CONFLICT')
        with self.assertRaises(CatalogError) as caught:self.f.service.call(**dict(args,request_key='new'),recover=True)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(len(self.f.service.inspect_context(self.f.context)['operations']),1)

    def test_visible_index_is_confirmed_without_new_generation_and_unknown_time_blocks_new_work(self):
        args=self.interrupt('request_asset_update',self.process_args(),'index_after_head')
        before=self.f.index.current()[1]['generation']
        with patch('uteki.data_platform.retrieval.index.DerivedIndex.build',side_effect=AssertionError('index rebuilt')):
            result=self.f.service.call(**args,recover=True)
        self.assertEqual(result['items'][0]['derived_generation'],before)
        self.assertEqual(self.f.index.current()[1]['generation'],before)
        self.assertIsNone(result['resource_usage']['elapsed_ms'])
        self.assertTrue(result['resource_usage']['execution_time_uncertain'])
        with self.assertRaises(CatalogError) as caught:self.f.call('find_assets',dict(filters={}))
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')

    def test_changed_or_damaged_index_cannot_be_adopted_or_silently_rebuilt(self):
        for damage in ('new_head','corrupt_file'):
            with self.subTest(damage=damage):
                f=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
                f.setUp()
                try:
                    state=f.state('request_asset_update')
                    request=dict(need_id='need-1',action='process',process=dict(asset_ref=f.reference.model_dump(mode='json'),capabilities=['records']),reason='Explicit index')
                    def stop(phase):
                        if phase=='index_after_head':raise ControlledExit('controlled interruption')
                    with self.assertRaises(ControlledExit):f.service.call(f.context,'request_asset_update',request,state=state,request_key='original',checkpoint=stop)
                    if damage=='new_head':f.index.build()
                    else:(f.index.current()[0]/'records.duckdb').write_bytes(b'corrupt')
                    before=(f.index.base/'head.json').read_bytes()
                    with self.assertRaises(CatalogError) as caught:f.service.call(f.context,'request_asset_update',request,state=state,request_key='original',recover=True)
                    self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                    self.assertEqual((f.index.base/'head.json').read_bytes(),before)
                finally:f.doCleanups()


if __name__=='__main__':unittest.main()
