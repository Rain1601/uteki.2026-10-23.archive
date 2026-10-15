"""Business terminal results survive interrupted commits without an SDK restart."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch
from copy import deepcopy
from pydantic import ValidationError

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.run import RunQueryResult

def make_case():
    return runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
LIMITS = dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)
PROFILE = dict(kernel='completion_fixture')


def failure():
    return dict(kind='failed',status='failed',error='synthetic native failure',native_success=False,
        delivery=None,committed_delivery=None,clarification=None,committed_clarification=None,
        profile=PROFILE,native_events=[],tool_events=[],mode='offline',real_model_calls=0,gateway_cost_usd=None)


class RunCompletionTests(unittest.TestCase):
    def setUp(self):
        self.case=make_case();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_failure_after_session_terminal_can_finish_original_catalog_and_result(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        with patch.object(self.case.catalog,'finish_run',side_effect=CatalogError('RECOVERY_REQUIRED','injected commit failure')):
            with self.assertRaises(CatalogError):journal.finish(failure())
        recovered=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS,recover=True)
        self.assertEqual(recovered.cached['kind'],'failed',recovered.cached)
        self.assertEqual(recovered.cached['error'],'synthetic native failure')
        self.assertEqual(self.case.catalog._get('runs','run_id',recovered.context['run_id'])['status'],'failed')

    def test_unknown_response_can_end_failed_but_keeps_reconciliation_and_original_requests(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        journal.prepare_model(dict(input='synthetic'))
        result=journal.finish(failure())
        self.assertTrue(result['terminal']);self.assertTrue(result['reconciliation_required'])
        self.assertEqual(result['runtime']['budget']['request_stages'],{'outcome_unknown':1})
        self.assertEqual(journal.budget.summary()['unknown_requests'],1)
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)
        self.assertEqual(RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS,recover=True).cached,result)

    def test_recovery_result_is_nonterminal_and_lifecycle_does_not_claim_process_liveness(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        result=journal.finish(failure()|dict(kind='recovery_required'))
        self.assertFalse(result['terminal']);self.assertTrue(result['reconciliation_required'])
        state=self.case.service.inspect_context(self.case.context)
        self.assertEqual(state['status'],'open')
        self.assertEqual(state['lifecycle'],dict(catalog_status='running',native_phase='recovery_required',
            result_kind='recovery_required',completion_pending=False,closure_requested=False))

    def test_frozen_result_cannot_be_replaced_or_silently_repaired(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        result=journal.finish(failure())
        session=Session(self.case.catalog,self.case.context)
        session.data['native_execution']['outcome']['error']='different error'
        session.save()
        with self.assertRaises(CatalogError) as caught:self.case.service.read_run_result(self.case.context)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(result['error'],'synthetic native failure')

    def test_result_read_rejects_a_reopened_business_state(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        journal.finish(failure())
        session=Session(self.case.catalog,self.case.context);session.data['status']='open';session.save()
        with self.assertRaises(CatalogError) as caught:self.case.service.read_run_result(self.case.context)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')

    def test_completion_intent_blocks_new_business_actions_before_terminal_commit(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        def interrupt(phase):
            if phase=='native_outcome_prepared':raise RuntimeError('controlled interruption')
        journal.checkpoint=interrupt
        with self.assertRaises(RuntimeError):journal.finish(failure())
        with self.assertRaises(CatalogError) as caught:
            self.case.service.find_assets(self.case.context,dict(filters={}),state=self.case.state('find_assets'),request_key='new')
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(self.case.service.inspect_context(self.case.context)['operations'],{})
        self.assertEqual(RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS,recover=True).cached['kind'],'failed')

    def test_host_close_requires_real_exit_and_cannot_revoke_completed_result(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        with self.assertRaises(CatalogError) as caught:
            self.case.service.close_run(self.case.context,request_key='close',reason='stop')
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertNotIn('close_intent',journal.state())
        result=journal.finish(failure())
        with self.assertRaises(CatalogError) as caught:
            self.case.service.close_run(self.case.context,request_key='close',reason='stop')
        self.assertEqual(caught.exception.code,'INVALID_STATE')
        self.assertEqual(self.case.service.read_run_result(self.case.context),result)

    def test_result_contract_rejects_inconsistent_success_and_terminal_flags(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        original=journal.finish(failure())
        for change in [dict(terminal=False),dict(kind='delivery',status='completed'),dict(error=None),
                       dict(kind='recovery_required',terminal=False,reconciliation_required=False)]:
            with self.subTest(change=change),self.assertRaises(ValidationError):RunQueryResult.model_validate(original|change)

    def test_old_saved_result_is_read_back_without_new_fields(self):
        journal=RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS)
        original=journal.finish(failure())
        old=deepcopy(original)
        for key in ('schema_version','terminal','reconciliation_required'):old.pop(key)
        session=Session(self.case.catalog,self.case.context)
        session.data['native_execution']['outcome']=old
        for key in ('outcome_intent','outcome_object'):session.data['native_execution'].pop(key)
        session.save()
        self.assertEqual(self.case.service.read_run_result(self.case.context),old)
        self.assertEqual(RuntimeJournal(self.case.service,self.case.context,PROFILE,LIMITS).cached,old)


if __name__=='__main__':unittest.main()
