"""Behavioral regressions for model-visible state and bounded search results."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import runpy
import unittest

from uteki.data_platform.agent.binding import ToolBinding
from uteki.data_platform.application.session import Session
from uteki.data_platform.contracts.common import canonical

FIXTURE = runpy.run_path(str(Path(__file__).with_name('test_queries.py')))


class ToolContractFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = FIXTURE['DataToolTests']()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def test_rejected_plan_feedback_allows_correction_without_guessing_commit_state(self):
        c = self.case
        binding = ToolBinding(c.service,c.context)
        def invoke(request,state):
            return json.loads(asyncio.run(binding.invoke('find_assets',dict(request=request,state=state))))
        state = c.state('find_assets')
        bad = deepcopy(state);bad['next_action']='Search for the report.'
        reply = invoke({'filters':{}},bad)
        self.assertIn('find_assets',reply['error']['message'])
        self.assertEqual(reply['error']['current_task_state'],dict(plan={'version':0,'needs':[]},state=None,operation_accepted=False))
        bad = deepcopy(state);bad['gaps']=[]
        reply = invoke({'filters':{}},bad)
        self.assertIn('missing=["need-1"]',reply['error']['message'])
        reply = invoke({'filters':{'material_types':['invented form name']}},state)
        self.assertEqual(reply['error']['code'],'INVALID_REQUEST')
        self.assertIn('filters.material_types',reply['error']['message'])
        self.assertIn('registered names',reply['error']['message'])
        self.assertEqual(reply['error']['current_task_state']['plan']['version'],0)
        bad = deepcopy(state);bad.pop('plan_update')
        reply = invoke({'filters':{}},bad)
        self.assertIn('do not commit',reply['error']['message'])
        reply = invoke({'filters':{}},state)
        self.assertEqual(reply['status'],'ok',reply)
        self.assertEqual(c.service.inspect_context(c.context)['plan']['version'],1)
        # A later rejected update must report the real committed version.
        reply = invoke({'filters':{}},state)
        self.assertEqual(reply['error']['code'],'PLAN_VERSION_MISMATCH')
        self.assertEqual(reply['error']['current_task_state']['plan']['version'],1)

    def test_optional_cutoff_is_distinct_from_clock_and_explicit_cutoff_is_never_dropped(self):
        c = self.case
        clock = c.service.inspect_context(c.context)['context']['clock']
        narrowed = c.call('find_assets',dict(filters={},as_of=clock))
        self.assertEqual(narrowed['items'],[])
        self.assertIn('SCOPE_TIME_UNKNOWN',[i['code'] for i in narrowed['issues']])
        ordinary = c.call('find_assets',dict(filters={}))
        self.assertTrue(ordinary['items'])
        historical = c.service.create_context(c.request | {'as_of':clock},request_key='explicit-cutoff')['context_ref']
        inherited = c.call('find_assets',dict(filters={}),context=historical)
        self.assertEqual(inherited['items'],[])
        self.assertIn('SCOPE_TIME_UNKNOWN',[i['code'] for i in inherited['issues']])
        denied = c.call('get_asset_schema',dict(asset_ref=c.reference.model_dump(mode='json')),context=historical)
        self.assertEqual(denied['error']['code'],'SCOPE_TIME_UNKNOWN')

    def search_args(self):
        return dict(asset_ref=self.case.reference.model_dump(mode='json'),mode='text',
            text=dict(match='regex',value='.+'),include=['snippet','section_title','table_header','units'],limit=20)

    def test_prefixed_concept_is_an_invalid_query_not_absent_source_data(self):
        c=self.case;c.process()
        request=dict(asset_ref=c.reference.model_dump(mode='json'),select={'concepts':['ex:Cash']})
        rejected=c.call('query_records',request)
        self.assertEqual(rejected['error']['code'],'INVALID_REQUEST')
        self.assertIn('get_asset_schema',rejected['error']['message'])
        actual=c.call('query_records',request | {'select':{'concepts':['{https://example.com/taxonomy}Cash']}})
        self.assertEqual(len(actual['items']),3)
        other=c.call('query_records',request | {'select':{'concepts':['{https://example.com/other}Cash']}})
        self.assertEqual(other['items'],[])
        self.assertEqual(other['status'],'ok')
        invalid_fields=c.call('query_records',request | {'select':{'fields':['entity_scope','source_locator']}})
        self.assertEqual(invalid_fields['error']['code'],'INVALID_REQUEST')
        self.assertIn('entity_scope',invalid_fields['error']['message'])
        self.assertIn('source_locator',invalid_fields['error']['message'])
        self.assertIn("'locator'",invalid_fields['error']['message'])
        self.assertTrue(c.call('query_records',request | {'select':{'fields':['period']}})['items'])

    def test_byte_pagination_preserves_every_hit_dependency_and_old_reference(self):
        c = self.case;c.process();args=self.search_args()
        def collect(budget):
            cursor=None;found=[];oversized=0;saved=None
            for _ in range(50):
                reply=c.call('search_asset',args | {'max_bytes':budget,'cursor':cursor})
                self.assertIn(reply['status'],{'ok','partial'},reply)
                self.assertLessEqual(len(canonical(reply)),budget)
                for item in reply['items']:
                    found.append(item['block_id'])
                    bundle=[item['evidence'],*item.get('context_evidence',[])]
                    available={canonical(v['result_ref']) for v in bundle}
                    for value in bundle:
                        self.assertEqual(Session(c.catalog,c.context).lookup(value['result_ref']),value)
                        self.assertTrue(all(canonical(ref) in available for ref in value['dependency_refs']))
                    saved=saved or item['evidence']
                too_large=next((i for i in reply['issues'] if i['code']=='ITEM_TOO_LARGE'),None)
                if too_large:
                    oversized+=1
                    self.assertFalse(reply['items'])
                    self.assertTrue(too_large['target']['block_id'])
                    self.assertIsNotNone(reply['next_cursor'])
                    budget=200000  # Same position, larger output budget, no skipped hit.
                else:budget=6000 if budget!=200000 or oversized else budget
                cursor=reply['next_cursor']
                if cursor is None:break
            else:self.fail('pagination failed to terminate')
            return found,oversized,saved
        expected,_,_=collect(200000)
        actual,oversized,saved=collect(6000)
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),len(set(actual)))
        self.assertGreater(oversized,0)
        self.assertEqual(Session(c.catalog,c.context).lookup(saved['result_ref']),saved)

    def test_too_small_page_registers_no_partial_bundle_and_query_change_cannot_reuse_cursor(self):
        c=self.case;c.process();args=self.search_args()
        before=deepcopy(Session(c.catalog,c.context).data['results'])
        reply=c.call('search_asset',args | {'max_bytes':2000})
        self.assertEqual(reply['items'],[])
        self.assertEqual(reply['issues'][0]['code'],'ITEM_TOO_LARGE')
        self.assertEqual(Session(c.catalog,c.context).data['results'],before)
        changed=c.call('search_asset',args | {'max_bytes':24000,'cursor':reply['next_cursor'],
            'text':dict(match='phrase',value='other')})
        self.assertEqual(changed['error']['code'],'CURSOR_MISMATCH')
        resumed=c.call('search_asset',args | {'max_bytes':200000,'cursor':reply['next_cursor']})
        self.assertTrue(resumed['items'],resumed)
        c.process()
        stale=c.call('search_asset',args | {'max_bytes':24000,'cursor':reply['next_cursor']})
        self.assertEqual(stale['error']['code'],'CURSOR_EXPIRED')


if __name__ == '__main__':unittest.main()
