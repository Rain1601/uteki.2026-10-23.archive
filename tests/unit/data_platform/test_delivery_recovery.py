"""Interrupted immutable delivery commits are explicitly recoverable, not rerun."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError, canonical


class DeliveryRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f=fixture
        self.request=dict(needs=[dict(need_id='need-1',status='unresolved',result_refs=[],gaps=['not yet read'])])
        self.state=fixture.state('deliver')
        self.state['gaps'][0]['missing']='not yet read'

    def deliver(self,**options):
        return self.f.service.deliver(self.f.context,self.request,state=self.state,request_key='delivery',**options)

    def fail_at(self,phase):
        def checkpoint(actual):
            if actual==phase:raise OSError('controlled interrupted acknowledgement')
        with self.assertRaises(OSError):self.deliver(checkpoint=checkpoint)

    def test_object_write_failure_recovery_keeps_original_identity_and_bytes(self):
        self.fail_at('delivery_accepted')
        session=Session(self.f.catalog,self.f.context)
        intended=next(iter(session.data['operations'].values()))['terminal_intent']['package']
        turns=session.data['turns']
        with patch.object(self.f.catalog.content,'put_object',side_effect=OSError('controlled object write failure')):
            with self.assertRaises(OSError):self.deliver(recover=True)
        self.assertIsNone(self.f.service.inspect_context(self.f.context)['delivery'])
        response=self.deliver(recover=True)
        self.assertEqual(canonical(response['delivery']),canonical(intended))
        self.assertEqual(self.deliver(),response)
        self.assertEqual(self.f.service.inspect_context(self.f.context)['turns'],turns)

    def test_recovery_requires_same_request_and_explicit_opt_in(self):
        self.fail_at('delivery_object_written')
        before=Session(self.f.catalog,self.f.context).head_ref
        with self.assertRaises(CatalogError) as caught:self.deliver()
        self.assertEqual(caught.exception.code,'OPERATION_INTERRUPTED')
        self.request['needs'][0]['note']='changed after crash'
        with self.assertRaises(CatalogError) as caught:self.deliver(recover=True)
        self.assertEqual(caught.exception.code,'IDEMPOTENCY_CONFLICT')
        self.assertEqual(Session(self.f.catalog,self.f.context).head_ref,before)

    def test_legacy_interrupted_delivery_without_saved_package_is_not_regenerated(self):
        self.fail_at('delivery_accepted')
        session=Session(self.f.catalog,self.f.context)
        next(iter(session.data['operations'].values())).pop('terminal_intent')
        session.save()
        before=session.head_ref
        with self.assertRaises(CatalogError) as caught:self.deliver(recover=True)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(Session(self.f.catalog,self.f.context).head_ref,before)

    def test_catalog_finish_failure_replays_same_committed_delivery(self):
        with patch.object(self.f.catalog,'finish_run',side_effect=OSError('controlled catalog acknowledgement failure')):
            with self.assertRaises(OSError):self.deliver()
        before=self.f.service.read_delivery(self.f.context)
        response=self.deliver(recover=True)
        self.assertEqual(response['delivery'],before)
        context=self.f.service.inspect_context(self.f.context)['context']
        self.assertEqual(self.f.catalog._get('runs','run_id',context['run_id'])['status'],'completed')

    def test_forced_stop_before_plan_preserves_question_as_unresolved_without_a_tool_turn(self):
        result=self.f.service.force_delivery(self.f.context,stop_reason='cancelled',visible_results=[])
        package=result['delivery']
        self.assertEqual(package['needs_plan']['needs'][0]['description'],self.f.request['question'])
        self.assertEqual(package['needs'][0]['status'],'unresolved')
        self.assertEqual(package['business_status'],'cancelled')
        inspected=self.f.service.inspect_context(self.f.context)
        self.assertEqual(inspected['turns'],0)
        self.assertEqual(inspected['status'],'cancelled')
        self.assertEqual(self.f.service.force_delivery(self.f.context,stop_reason='cancelled',visible_results=[]),result)
        with self.assertRaises(CatalogError):
            self.f.service.force_delivery(self.f.context,stop_reason='wall_time',visible_results=[])

    def test_stopped_delivery_does_not_promote_unjudged_new_results(self):
        block=next(b for b in self.f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        read=self.f.call('read_evidence',dict(asset_ref=self.f.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])]))
        ref=read['items'][0]['result_ref']
        result=self.f.service.force_delivery(self.f.context,stop_reason='model_budget',visible_results=[ref])
        self.assertEqual(result['delivery']['needs'][0]['status'],'unresolved')
        self.assertEqual(result['delivery']['evidence'],[])
        self.assertEqual(self.f.service.inspect_context(self.f.context)['turns'],1)

    def test_stopped_delivery_preserves_judged_visible_evidence(self):
        block=next(b for b in self.f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        read=self.f.call('read_evidence',dict(asset_ref=self.f.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])]))
        ref=read['items'][0]['result_ref']
        self.f.service.find_assets(self.f.context,dict(filters={}),state=self.f.state('find_assets',[ref],supported=True),request_key='judge')
        result=self.f.service.force_delivery(self.f.context,stop_reason='max_turns',visible_results=[ref])
        self.assertEqual(result['delivery']['business_status'],'partial')
        self.assertEqual(result['delivery']['needs'][0]['status'],'supported')
        self.assertEqual(result['delivery']['evidence'][0]['result_ref'],ref)
        self.assertEqual(self.f.service.inspect_context(self.f.context)['turns'],2)

    def test_stopped_delivery_downgrades_evidence_not_visible_in_the_native_execution(self):
        block=next(b for b in self.f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        read=self.f.call('read_evidence',dict(asset_ref=self.f.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])]))
        ref=read['items'][0]['result_ref']
        self.f.service.find_assets(self.f.context,dict(filters={}),state=self.f.state('find_assets',[ref],supported=True),request_key='judge')
        result=self.f.service.force_delivery(self.f.context,stop_reason='max_turns',visible_results=[])
        self.assertEqual(result['delivery']['needs'][0]['status'],'unresolved')
        self.assertEqual(result['delivery']['evidence'],[])

    def test_forced_stop_does_not_mask_unconfirmed_business_effects(self):
        self.fail_at('delivery_accepted')
        before=Session(self.f.catalog,self.f.context).head_ref
        with self.assertRaises(CatalogError) as caught:
            self.f.service.force_delivery(self.f.context,stop_reason='wall_time',visible_results=[])
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(Session(self.f.catalog,self.f.context).head_ref,before)


if __name__=='__main__':unittest.main()
