"""Offline contract/runtime tests: these synthetic answers are not model acceptance."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx2 as httpx

from uteki.agents.filing_brief import contract, run
from uteki.agents.filing_brief.consume import render

spec=importlib.util.spec_from_file_location('brief_fixture',Path(__file__).with_name('test_business_only_run.py'))
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def bilingual(text): return dict(zh=text,en=text)


def task(packet):
    return dict(company_id=packet['company_id'],document_id=packet['document_id'],
        period_end=packet['period_end'],cutoff='2026-10-07',source_language='en',
        reading_purpose='Understand the selected Services section.',reading_mode='first_read')


def answer(packet,task,packet_sha):
    return dict(schema_version='filing-brief-v1',company_id=packet['company_id'],
        document_id=packet['document_id'],period_end=packet['period_end'],source_sha256=packet['source_sha256'],
        source_packet_sha256=packet_sha,task_sha256=contract.digest(task),title=bilingual('Selected brief'),
        scope_limitation=bilingual('Selected subsection only; the rest of the report is not assessed.'),
        items=[dict(id='item1',kind='reported_fact',priority='must_read',priority_reason=bilingual('Explains offering.'),
            statement=bilingual(packet['blocks'][3]['text']),attribution=bilingual('The reporting issuer.'),
            period_scope=bilingual(packet['period_end']),qualifications=[],uncertainty='source_statement',
            excerpts=[dict(block_id='product',quote=packet['blocks'][3]['text'])])],
        coverage=[dict(block_id=b['id'],disposition='included' if b['id']=='product' else 'context',
            item_ids=['item1'] if b['id']=='product' else [],reason=bilingual('Fixture context.')) for b in packet['blocks']],gaps=[])


class BriefTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.packet,_=fixture.fixture(self.root,'quartz','2023-09-30')
        self.task=task(self.packet)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'task.json').write_text(json.dumps(self.task))
        (self.root/'skill.md').write_text('Use exact evidence and preserve meaningful qualifications.')
        self.packet_sha=run.base.digest((self.root/'packet.json').read_bytes())
        self.brief=answer(self.packet,self.task,self.packet_sha)
        self.requests=[]
        self.responses=[]
        env=patch.dict(os.environ,{'AIHUBMIX_API_KEY':'offline-test-key'})
        env.start();self.addCleanup(env.stop)
        native=run.ClaudeMessagesModel
        def factory(*args,**kwargs):
            return native(*args,**dict(kwargs,client_factory=self.client))
        mock=patch.object(run,'ClaudeMessagesModel',side_effect=factory)
        mock.start();self.addCleanup(mock.stop)

    def client(self,**kwargs):
        return httpx.AsyncClient(**dict(kwargs,transport=httpx.MockTransport(self.respond)))

    def respond(self,request):
        body=json.loads(request.content);self.requests.append(body)
        response=self.responses.pop(0)
        if isinstance(response,Exception):raise response
        if callable(response):response=response(body)
        message={k:v for k,v in response.items() if k not in ('content','stop_reason')}
        message.update(type='message',content=[])
        events=[dict(type='message_start',message=message),
            dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),
            dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=response['content'][0]['text'])),
            dict(type='content_block_stop',index=0),
            dict(type='message_delta',delta=dict(stop_reason=response['stop_reason']),usage=response.get('usage',{})),
            dict(type='message_stop')]
        raw=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=raw)

    def response(self,value,stop='end_turn',usage=True):
        body=dict(id='brief-message',model='claude-sonnet-5-5',stop_reason=stop,
            content=[dict(type='text',text=json.dumps(value))])
        if usage:body['usage']=dict(input_tokens=300,output_tokens=250)
        return body

    def review(self,brief=None):
        brief=brief or self.brief
        return dict(schema_version='filing-brief-review-v1',brief_sha256=contract.digest(brief),
            claims=[dict(item_id=i['id'],verdict='supported',rationale='Synthetic fixture.') for i in brief['items']],
            coverage=[dict(block_id=b['id'],verdict='adequate',rationale='Synthetic fixture.') for b in self.packet['blocks']],
            gaps=[dict(gap_id=g['id'],verdict='supported',rationale='Synthetic fixture.') for g in brief['gaps']])

    def prepared(self):
        return run.prepare(root=self.root,packet_path='packet.json',task_path='task.json',skill_path='skill.md',
            model='claude-sonnet-5-5',max_tokens=3000)

    async def execute(self,prepared=None,budget='1'):
        return await run.execute(prepared or self.prepared(),output=self.root/'output',
            observation_root=self.root/'observations',budget_usd=budget)

    def valid(self,value=None):
        return contract.validate_brief(value or self.brief,self.packet,self.task,self.packet_sha)

    def test_scope_rejects_missing_company_other_company_and_period(self):
        for key,value in [('company_id',None),('company_id','other'),('period_end','2020-09-30')]:
            t=copy.deepcopy(self.task)
            if value is None:del t[key]
            else:t[key]=value
            with self.assertRaises(ValueError):contract.validate_task(t,self.packet)
        t=dict(self.task,cutoff='2020-01-01')
        with self.assertRaises(ValueError):contract.validate_task(t,self.packet)

    def test_valid_other_scope_and_consumer(self):
        packet,_=fixture.fixture(self.root,'indigo','2024-03-31')
        t=task(packet);sha='a'*64;b=answer(packet,t,sha)
        result=render(b,packet,t,sha,self.root/'read')
        self.assertEqual(result['semantic_acceptance'],'not_evaluated')
        text=(self.root/'read/brief.zh.md').read_text()
        self.assertIn('indigo',text);self.assertIn('evidence.html#product',text)
        self.assertIn('2024-03-31',text)

    def test_wrong_source_hash_and_excerpts_are_rejected(self):
        for key,value in [('source_sha256','0'*64),('source_packet_sha256','1'*64),('task_sha256','2'*64)]:
            with self.assertRaises(ValueError):self.valid(dict(self.brief,**{key:value}))
        b=copy.deepcopy(self.brief);b['items'][0]['excerpts'][0]['block_id']='unselected'
        with self.assertRaises(ValueError):self.valid(b)
        b=copy.deepcopy(self.brief);b['items'][0]['excerpts'][0]['quote']='Invented quote.'
        with self.assertRaises(ValueError):self.valid(b)

    def test_missing_duplicate_or_false_coverage_is_rejected(self):
        for edit in ('missing','duplicate','wrong_mapping','missing_item'):
            b=copy.deepcopy(self.brief)
            if edit=='missing':b['coverage'].pop()
            if edit=='duplicate':b['coverage'].append(b['coverage'][0])
            if edit=='wrong_mapping':b['coverage'][0].update(disposition='included',item_ids=['item1'])
            if edit=='missing_item':b['coverage'][3].update(disposition='compressed',item_ids=[])
            with self.assertRaises(ValueError):self.valid(b)

    def test_forecasts_interpretations_and_absence_have_explicit_boundaries(self):
        for kind in ('interpretation','forecast_or_target'):
            b=copy.deepcopy(self.brief);b['items'][0]['kind']=kind
            with self.assertRaises(ValueError):self.valid(b)
        b=copy.deepcopy(self.brief);b['gaps']=[dict(id='g',status='not_disclosed',question=bilingual('Revenue?'),
            explanation=bilingual('No search result.'),block_ids=[],excerpts=[])]
        with self.assertRaises(ValueError):self.valid(b)
        b['gaps'][0]['status']='unknown';self.valid(b)

    def test_review_is_exhaustive_and_candidate_bound(self):
        review=self.review();review['coverage'].pop()
        with self.assertRaises(ValueError):contract.validate_review(review,self.brief,self.packet)
        review=self.review();review['claims'][0]['verdict']='partial'
        self.assertEqual(contract.validate_review(review,self.brief,self.packet)['computed_status'],'needs_revision')
        review=self.review();review['brief_sha256']='0'*64
        with self.assertRaises(ValueError):contract.validate_review(review,self.brief,self.packet)

    async def test_actual_wire_source_only_then_own_brief_review(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        result=await self.execute()
        self.assertEqual(result['status'],'candidate');self.assertEqual(result['self_review'],'pass')
        self.assertEqual(result['semantic_acceptance'],'not_evaluated')
        self.assertEqual(len(self.requests),2)
        first=json.loads(self.requests[0]['messages'][0]['content'])
        self.assertEqual(set(first),{'task','frozen_source_packet','source_packet_sha256','task_sha256'})
        second=json.loads(self.requests[1]['messages'][0]['content'])
        self.assertEqual(second['own_brief'],self.brief)
        self.assertTrue((self.root/'output/generate/brief.zh.md').is_file())
        self.assertEqual(result['budget']['requests'],2)

    async def test_truncated_complete_http_response_cannot_publish_candidate(self):
        self.responses=[self.response(self.brief,stop='max_tokens')]
        result=await self.execute()
        self.assertEqual(result['status'],'failed');self.assertEqual(len(self.requests),1)
        self.assertFalse((self.root/'output/generate/brief.json').exists())

    async def test_unknown_usage_preserves_cost_and_stops_review(self):
        self.responses=[self.response(self.brief,usage=False)]
        result=await self.execute()
        self.assertEqual(result['status'],'failed');self.assertEqual(result['budget']['unknown_requests'],1)
        self.assertEqual(len(self.requests),1)

    async def test_input_change_after_model_call_cannot_publish_candidate(self):
        def mutate(body):
            (self.root/'source.html').write_text('Changed source')
            return self.response(self.brief)
        self.responses=[mutate]
        result=await self.execute()
        self.assertEqual(result['status'],'failed')
        self.assertFalse((self.root/'output/generate/brief.json').exists())

    async def test_budget_denies_before_http(self):
        result=await self.execute(budget='0.000001')
        self.assertEqual(result['status'],'failed');self.assertEqual(len(self.requests),0)

    async def test_transient_retry_keeps_original_reservation_and_one_task_budget(self):
        self.responses=[httpx.RemoteProtocolError('offline interruption'),self.response(self.brief),self.response(self.review())]
        result=await self.execute()
        self.assertEqual(result['status'],'candidate');self.assertEqual(len(self.requests),3)
        self.assertEqual(result['budget']['requests'],3)
        self.assertEqual(result['budget']['unknown_requests'],1)
        self.assertGreater(float(result['budget']['held_usd']),0)
        self.assertTrue((self.root/'output/generate/transport-attempts/001/outcome.json').exists())
        self.assertTrue((self.root/'output/generate/transport-attempts/002/outcome.json').exists())

    async def failed_generation(self):
        bad=copy.deepcopy(self.brief)
        bad['coverage'][0].update(disposition='compressed',item_ids=['item1'])
        self.responses=[self.response(bad)]
        result=await self.execute()
        self.assertEqual(result['status'],'failed')

    async def test_repair_uses_machine_error_own_answer_shared_budget_and_one_successor(self):
        await self.failed_generation()
        self.responses=[self.response(self.brief),self.response(self.review())]
        result=await run.execute(self.prepared(),output=self.root/'repair',observation_root=self.root/'observations',
            budget_usd='1',repair_run='output')
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['budget']['requests'],3)
        self.assertEqual(result['budget_path'],'output/budget.sqlite')
        self.assertFalse((self.root/'repair/budget.sqlite').exists())
        repair=json.loads(self.requests[1]['messages'][0]['content'])
        self.assertIn('coverage_item_requires_same_block_evidence',repair['machine_validation_error'])
        self.assertIn('own_previous_brief',repair)
        with self.assertRaises(FileExistsError):
            await run.execute(self.prepared(),output=self.root/'duplicate',observation_root=self.root/'observations',
                budget_usd='1',repair_run='output')
        self.assertEqual(len(self.requests),3)

    async def test_repair_cannot_change_budget_or_task(self):
        await self.failed_generation()
        with self.assertRaises(ValueError):
            await run.execute(self.prepared(),output=self.root/'repair',observation_root=self.root/'observations',
                budget_usd='2',repair_run='output')
        self.assertFalse((self.root/'output/repair-claim.json').exists())
        changed=dict(self.task,reading_purpose='Changed purpose')
        (self.root/'task.json').write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            await run.execute(self.prepared(),output=self.root/'repair',observation_root=self.root/'observations',
                budget_usd='1',repair_run='output')
        self.assertEqual(len(self.requests),1)

    async def test_cross_model_audit_revision_and_fresh_review_share_original_budget(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute(budget='3')
        audit=self.review();audit['claims'][0]['verdict']='partial'
        revised=copy.deepcopy(self.brief);revised['title']=bilingual('Revised selected brief')
        self.responses=[self.response(audit),self.response(revised),self.response(self.review(revised))]
        result=await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
            budget_usd='3',audit_run='output',review_model='claude-opus-5-5',review_max_tokens=3000)
        self.assertEqual(result['status'],'candidate');self.assertEqual(result['self_review'],'pass')
        self.assertEqual(result['budget']['requests'],5)
        self.assertEqual(result['budget_path'],'output/budget.sqlite')
        self.assertEqual([r['model'] for r in self.requests[2:]],['claude-opus-5-5','claude-sonnet-5-5','claude-opus-5-5'])
        self.assertEqual(self.requests[2]['thinking']['type'],'adaptive')
        revision=json.loads(self.requests[3]['messages'][0]['content'])
        self.assertEqual(revision['model_audit']['claims'][0]['verdict'],'partial')
        self.assertNotIn('human_feedback',revision)
        final=json.loads(self.requests[4]['messages'][0]['content'])
        self.assertEqual(final['brief_sha256'],contract.digest(revised))
        with self.assertRaises(FileExistsError):
            await run.execute(self.prepared(),output=self.root/'another',observation_root=self.root/'observations',
                budget_usd='3',audit_run='output',review_model='claude-opus-5-5')
        with self.assertRaises(ValueError):
            await run.execute(self.prepared(),output=self.root/'loop',observation_root=self.root/'observations',
                budget_usd='3',audit_run='audit',review_model='claude-opus-5-5')

    async def test_audit_pass_keeps_original_without_extra_generation(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute()
        self.responses=[self.response(self.review())]
        result=await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
            budget_usd='1',audit_run='output',review_model='claude-opus-5-5',review_max_tokens=3000)
        self.assertEqual(result['status'],'candidate');self.assertEqual(len(self.requests),3)
        self.assertEqual(result['brief_path'],'output/generate/brief.json')

    async def test_initial_audit_token_recovery_is_bounded_and_preserves_task_ledger(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute(budget='3')
        self.responses=[self.response(self.review(),stop='max_tokens')]
        failed=await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
            budget_usd='3',audit_run='output',review_model='claude-opus-5-5',review_max_tokens=3000)
        self.assertEqual(failed['status'],'failed')
        self.responses=[self.response(self.review())]
        result=await run.execute(self.prepared(),output=self.root/'recovered',observation_root=self.root/'observations',
            budget_usd='3',resume_audit_run='audit',review_model='claude-opus-5-5',review_max_tokens=6000)
        self.assertEqual(result['status'],'candidate');self.assertEqual(result['budget']['requests'],4)
        self.assertEqual(result['budget_path'],'output/budget.sqlite')
        self.assertEqual(result['audit_recovery_of'],'audit')
        with self.assertRaises(FileExistsError):
            await run.execute(self.prepared(),output=self.root/'another',observation_root=self.root/'observations',
                budget_usd='3',resume_audit_run='audit',review_model='claude-opus-5-5',review_max_tokens=6000)

    async def test_repair_rejects_response_changed_after_original_publication(self):
        await self.failed_generation()
        response=self.root/'output/generate/response.txt'
        response.write_text(response.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'originally_published'):
            await run.execute(self.prepared(),output=self.root/'repair',observation_root=self.root/'observations',
                budget_usd='1',repair_run='output')
        self.assertEqual(len(self.requests),1)

    async def test_audit_rejects_consistently_edited_candidate_and_response(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute()
        changed=copy.deepcopy(self.brief);changed['title']=bilingual('Hand edited')
        for name in ('brief.json','response.txt'):
            (self.root/'output/generate'/name).write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'originally_published'):
            await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
                budget_usd='1',audit_run='output',review_model='claude-opus-5-5')
        self.assertEqual(len(self.requests),2)

    async def test_audit_rejects_another_task_budget_path(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute()
        run.RunBudget(self.root/'other-budget.sqlite','1')
        p=self.root/'output/summary.json';summary=json.loads(p.read_text())
        summary['budget_path']='other-budget.sqlite';p.write_text(json.dumps(summary))
        with self.assertRaisesRegex(ValueError,'budget_lineage'):
            await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
                budget_usd='1',audit_run='output',review_model='claude-opus-5-5')
        self.assertEqual(len(self.requests),2)

    async def test_budget_blocked_final_review_does_not_reuse_old_candidate_verdict(self):
        self.responses=[self.response(self.brief),self.response(self.review())]
        await self.execute(budget='3')
        initial=self.review();initial['claims'][0]['verdict']='partial'
        revised=copy.deepcopy(self.brief);revised['title']=bilingual('New candidate')
        self.responses=[self.response(initial),self.response(revised)]
        reserve=run.RunBudget.reserve
        def guarded(budget,amount):
            if budget.summary()['requests']==4:
                from uteki.agents.runtime.run_budget import BudgetExceeded
                raise BudgetExceeded('Synthetic final review limit')
            return reserve(budget,amount)
        with patch.object(run.RunBudget,'reserve',guarded):
            result=await run.execute(self.prepared(),output=self.root/'audit',observation_root=self.root/'observations',
                budget_usd='3',audit_run='output',review_model='claude-opus-5-5',review_max_tokens=3000)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['self_review'],'pending_final_audit')
        self.assertIsNone(result['reviewed_brief_sha256'])
        self.assertEqual(len(self.requests),4)
