"""Clarification preserves identity, scope, history and cumulative root controls."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.content.store import ContentStoreError


class ClarificationTests(unittest.TestCase):
    def setUp(self):
        self.f=runpy.run_path(str(Path(__file__).with_name('test_queries.py')))['DataToolTests']()
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.question=dict(question='Which explicit period should this comparison use?',blocking_need_ids=['need-1'])
        self.state=self.f.state('clarify')

    def clarify(self,**options):
        return self.f.service.clarify(self.f.context,self.question,state=self.state,request_key='clarification',**options)

    def answer(self,response=None):
        response=response or self.clarify()
        return deepcopy(self.f.request) | dict(revises_context_ref=self.f.context,
            clarification_response=dict(clarification_id=response['clarification']['clarification_id'],answer='Use the same explicit scope.'))

    def test_clarification_is_immutable_and_duplicate_answers_share_one_successor(self):
        response=self.clarify();self.assertEqual(response['kind'],'needs_clarification')
        self.assertEqual(self.clarify(),response)
        before=Session(self.f.catalog,self.f.context).head_ref
        answer=self.answer(response)
        first=self.f.service.create_context(answer,request_key='answer-one')
        second=self.f.service.create_context(answer,request_key='answer-two')
        self.assertEqual(first,second)
        self.assertEqual(Session(self.f.catalog,self.f.context).head_ref,before)
        self.assertEqual(self.f.catalog.content.read_object(ObjectRef.model_validate(response['clarification_object'])),canonical(response['clarification']))
        parent=self.f.service.inspect_context(self.f.context)
        child=self.f.service.inspect_context(first['context_ref'])
        self.assertEqual(first['root_run_id'],parent['context']['root_run_id'])
        self.assertNotEqual(first['run_id'],parent['context']['run_id'])
        self.assertEqual(child['plan'],parent['plan'])
        self.assertEqual(child['plan_history'],parent['plan_history'])
        self.assertEqual(child['turns'],parent['turns'])
        self.assertEqual(child['wall_seconds'],parent['wall_seconds'])
        self.assertEqual(child['no_progress_turns'],parent['no_progress_turns'])
        self.assertEqual(child['context']['request']['question'],self.f.request['question'])
        self.assertEqual(self.f.catalog._get('runs','run_id',first['run_id'])['parent_run_id'],parent['context']['run_id'])

    def test_answer_cannot_change_original_question_answer_or_reuse_another_caller_key(self):
        answer=self.answer();self.f.service.create_context(answer,request_key='answer')
        changed=deepcopy(answer);changed['clarification_response']['answer']='A different answer'
        with self.assertRaises(CatalogError) as caught:self.f.service.create_context(changed,request_key='different')
        self.assertEqual(caught.exception.code,'CLARIFICATION_MISMATCH')
        changed=deepcopy(answer);changed['question']='Replace original question'
        with self.assertRaises(CatalogError):self.f.service.create_context(changed,request_key='changed-question')
        with self.assertRaises(CatalogError):self.f.service.create_context(self.f.request,request_key='answer')

    def test_clock_and_elapsed_time_do_not_advance_while_waiting_for_answer(self):
        response=self.clarify();parent=self.f.service.inspect_context(self.f.context)
        with patch('uteki.data_platform.service.utc_now',return_value='2040-01-01T00:00:00+00:00'):
            child=self.f.service.create_context(self.answer(response),request_key='late-answer')
        self.assertEqual(child['clock'],parent['context']['clock'])
        self.assertNotEqual(child['created_at'],child['clock'])
        self.assertEqual(self.f.service.inspect_context(child['context_ref'])['wall_seconds'],parent['wall_seconds'])

    def test_larger_limits_or_permissions_are_rejected_before_creating_a_child(self):
        answer=self.answer()
        for field in ('max_usd','max_turns','max_wall_seconds','max_no_progress_turns'):
            value=deepcopy(answer)
            value['run_policy'][field]=str(int(value['run_policy'][field])+1) if field=='max_usd' else value['run_policy'][field]+1
            with self.subTest(field=field),self.assertRaises(CatalogError) as caught:
                self.f.service.create_context(value,request_key=field)
            self.assertEqual(caught.exception.code,'SCOPE_VIOLATION')
        value=deepcopy(answer);value['expansion']['allow'].append('acquire');value['expansion']['deny']=[]
        with self.assertRaises(CatalogError):self.f.service.create_context(value,request_key='expand')
        value=deepcopy(answer);value['run_policy']['max_turns']=10;value['expansion']['mode']='disabled'
        child=self.f.service.create_context(value,request_key='narrow')
        self.assertEqual(child['request']['run_policy']['max_turns'],10)

    def test_source_policy_company_and_cutoff_cannot_expand(self):
        self.f.request['as_of']='2025-12-31T00:00:00+00:00'
        self.f.context=self.f.service.create_context(self.f.request,request_key='historical')['context_ref']
        self.state=self.f.state('clarify');answer=self.answer()
        for cutoff in (None,'2026-01-01T00:00:00+00:00'):
            value=deepcopy(answer);value['as_of']=cutoff
            with self.assertRaises(CatalogError):self.f.service.create_context(value,request_key='cutoff')
        self.f.catalog.register_policy('expanded-policy',definition=canonical(dict(schema_version='uteki-read-policy-v1',
            source_kinds=['user_file','official_site'],source_ids=[])).decode(),run_id=self.f.setup['run_id'])
        value=deepcopy(answer);value['source_policy_ref']='expanded-policy'
        with self.assertRaises(CatalogError):self.f.service.create_context(value,request_key='policy')
        fixture=runpy.run_path(str(Path(__file__).resolve().parents[2]/'fixtures/data_platform/catalog_worker.py'))
        other=self.f.catalog.register_company('other-company',fixture['company']('other'),run_id=self.f.setup['run_id'])
        value=deepcopy(answer);value['entities']['company_ids'].append(other)
        with self.assertRaises(CatalogError) as caught:self.f.service.create_context(value,request_key='company')
        self.assertEqual(caught.exception.code,'SCOPE_VIOLATION')

    def test_second_clarification_preserves_root_and_cannot_undo_first_narrowing(self):
        answer=self.answer();answer['run_policy']['max_turns']=25
        child=self.f.service.create_context(answer,request_key='first-narrowing')
        root=self.f.context
        self.f.context=child['context_ref'];self.f.request=child['request'];self.state=self.f.state('clarify')
        next_answer=self.answer();next_answer['run_policy']['max_turns']=26
        with self.assertRaises(CatalogError) as caught:self.f.service.create_context(next_answer,request_key='expand-child')
        self.assertEqual(caught.exception.code,'SCOPE_VIOLATION')
        next_answer['run_policy']['max_turns']=24
        successor=self.f.service.create_context(next_answer,request_key='second-narrowing')
        self.assertEqual(successor['continuation']['root_context_ref'],root)
        self.assertEqual(successor['root_run_id'],child['root_run_id'])
        self.assertEqual(self.f.service.inspect_context(successor['context_ref'])['turns'],2)

    def test_missing_clarification_object_cannot_be_reconstructed_by_answering(self):
        response=self.clarify();reference=ObjectRef.model_validate(response['clarification_object'])
        # Remove only this immutable object, leaving its committed reference.
        path=self.f.catalog.content._path(reference)
        path.unlink()
        with self.assertRaises(ContentStoreError) as caught:
            self.f.service.create_context(self.answer(response),request_key='lost-question')
        self.assertEqual(caught.exception.code,'OBJECT_MISSING')

    def test_unknown_period_can_be_clarified_but_known_period_cannot_be_replaced(self):
        period=dict(label='FY2024',fiscal_year=2024,fiscal_quarter=None,start=None,end=None,basis='unknown')
        answer=self.answer();answer['periods']=[period]
        child=self.f.service.create_context(answer,request_key='year-answer')
        self.f.context=child['context_ref'];self.f.request=child['request'];self.state=self.f.state('clarify')
        response=self.clarify();second=self.answer(response);second['periods'][0]['fiscal_year']=2025
        with self.assertRaises(CatalogError):self.f.service.create_context(second,request_key='other-year')

    def test_old_result_references_are_hints_and_cannot_support_child_delivery(self):
        block=next(b for b in self.f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        result=self.f.call('read_evidence',dict(asset_ref=self.f.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])]))
        ref=result['items'][0]['result_ref'];self.state=self.f.state('clarify',[ref])
        answer=self.answer();child=self.f.service.create_context(answer,request_key='read-again')
        session=Session(self.f.catalog,child['context_ref'])
        self.assertEqual(session.data['results'],{})
        self.assertEqual(session.data['state']['satisfied'],[])
        self.assertEqual(session.data['state']['gaps'][0]['result_refs'],[])
        self.assertEqual(session.data['inherited_state']['gaps'][0]['result_refs'],[ref])
        with self.assertRaises(CatalogError):session.lookup(ref)

    def test_answer_binding_interruption_requires_explicit_recovery_and_keeps_identity(self):
        answer=self.answer()
        def checkpoint(phase):
            if phase=='clarification_answer_registered':raise OSError('controlled interruption')
        with self.assertRaises(OSError):self.f.service.create_context(answer,request_key='first-answer',checkpoint=checkpoint)
        with self.assertRaises(CatalogError) as caught:self.f.service.create_context(answer,request_key='repeated-answer')
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        child=self.f.service.create_context(answer,request_key='repeated-answer',recover=True)
        self.assertEqual(self.f.service.create_context(answer,request_key='first-answer'),child)

    def test_clarification_recovery_keeps_id_after_object_write(self):
        def checkpoint(phase):
            if phase=='clarification_object_written':raise OSError('controlled interruption')
        with self.assertRaises(OSError):self.clarify(checkpoint=checkpoint)
        session=Session(self.f.catalog,self.f.context)
        intended=next(iter(session.data['operations'].values()))['terminal_intent']['package']
        with self.assertRaises(CatalogError):self.clarify()
        result=self.clarify(recover=True)
        self.assertEqual(result['clarification'],intended)
        self.assertEqual(self.clarify(),result)


if __name__=='__main__':unittest.main()
