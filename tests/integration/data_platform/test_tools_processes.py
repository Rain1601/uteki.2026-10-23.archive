"""Real exits preserve old data and distinguish interrupted from committed output."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.build.pipeline import build_html, html_recipe
from uteki.data_platform.contracts.common import canonical
from uteki.data_platform.retrieval.content import HtmlReader
from uteki.data_platform.retrieval.index import DerivedIndex
from uteki.data_platform.service import DataService

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/data_platform'
C=runpy.run_path(str(FIXTURES/'catalog_worker.py'))
F=runpy.run_path(str(FIXTURES/'html_fixture.py'))


class ToolProcessTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='uteki-tools-process-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        with Catalog.initialize(self.root) as catalog:
            setup=C['setup'](catalog,main=F['source']().replace(b'<img src="chart.png" alt="Synthetic chart">',b''))
            recipe=html_recipe(catalog,encoding='utf-8',form_type='synthetic',profile_ref='fixture',taxonomy_ref='source')
            self.reference=build_html(catalog,snapshot_id=setup['snapshot_id'],representation_id=setup['representation_id'],recipe=recipe,run_id=setup['run_id'])
            reader=HtmlReader(catalog,self.reference)
            self.old=DerivedIndex(catalog,reader).build()
            catalog.register_policy('read',definition=canonical(dict(schema_version='uteki-read-policy-v1',source_kinds=['user_file'])).decode(),run_id=setup['run_id'])
            service=DataService(catalog)
            self.context=service.create_context(dict(question='Check process boundaries',caller={'kind':'user'},
                entities={'company_ids':[setup['company_id']]},source_policy_ref='read',expansion=dict(mode='controlled',allow=['process'],deny=['acquire']),
                run_policy=dict(max_usd='0',max_turns=10,max_wall_seconds=120,max_no_progress_turns=10)),request_key='context')
            state=dict(plan_update=dict(base_version=0,needs=[dict(need_id='source',description='Read source',required=True)]),
                satisfied=[],gaps=[dict(need_id='source',missing='Not yet read')],next_action='read_evidence',reason='Initial source read')
            block=next(b for b in reader.inventory()['blocks'] if 'Exact source' in b['text'])
            result=service.read_evidence(self.context['context_ref'],dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':block['id']}]),state=state,request_key='read')
            self.assertEqual(result['status'],'ok',result)
            self.ref=result['items'][0]['result_ref']

    def interrupted(self,phase,*,delivery=False):
        state=dict(next_action='deliver' if delivery else 'request_asset_update',reason='Explicit process boundary test',
            satisfied=[dict(need_id='source',result_refs=[self.ref])],gaps=[])
        if delivery:
            request=dict(needs=[dict(need_id='source',status='supported',result_refs=[self.ref],gaps=[])])
        else:
            request=dict(need_id='source',action='process',process=dict(asset_ref=self.reference.model_dump(mode='json'),capabilities=['text_search']),reason='Rebuild explicitly')
        invocation=dict(method='deliver' if delivery else 'call',context_ref=self.context['context_ref'],request=request,state=state,request_key='interrupt')
        if not delivery:
            invocation['tool']='request_asset_update'
        path=self.root/'invocation.json'
        path.write_text(json.dumps(invocation))
        child=subprocess.run([sys.executable,'-I',str(FIXTURES/'tools_worker.py'),str(self.root),str(path),phase],
            cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,73,child.stderr)
        self.assertEqual(child.stdout,'')
        with Catalog.open(self.root) as catalog:
            reader=HtmlReader(catalog,self.reference)
            self.assertTrue(reader.inventory()['records'])
            index=DerivedIndex(catalog,reader)
            current=index.current()[1]
            service=DataService(catalog)
            inspected=service.inspect_context(self.context['context_ref'])
            operation=next(o for o in inspected['operations'].values() if o['request_key']=='interrupt')
            args={k:v for k,v in invocation.items() if k!='method'}
            if phase in {'response_committed','delivery_response_committed'}:
                self.assertEqual(operation['status'],'completed')
                replay=(service.deliver if delivery else service.call)(**args)
                self.assertEqual(replay,operation['response'])
                if delivery:
                    self.assertEqual(service.read_delivery(self.context['context_ref']),replay['delivery'])
                    self.assertEqual(catalog._get('runs','run_id',self.context['run_id'])['status'],'completed')
            else:
                self.assertEqual(operation['status'],'accepted')
                replay=service.call(**args)
                self.assertEqual(replay['error']['code'],'OPERATION_INTERRUPTED')
                self.assertEqual(operation['response'],None)
            if not delivery:
                self.assertEqual(current['generation']==self.old['generation'],phase in {'tool_started','index_before_head'})
                self.assertTrue((index.base/self.old['generation']/'fts.sqlite').exists())
                self.assertEqual(index.current()[1]['generation'],current['generation'])

    def test_exit_after_acceptance_keeps_old_index_and_does_not_repeat(self):
        self.interrupted('tool_started')

    def test_exit_before_index_activation_preserves_old_head(self):
        self.interrupted('index_before_head')

    def test_exit_after_index_activation_reports_uncertain_response(self):
        self.interrupted('index_after_head')

    def test_exit_after_response_commit_replays_without_new_generation(self):
        self.interrupted('response_committed')

    def test_delivery_commit_before_catalog_finish_reconciles_on_exact_replay(self):
        self.interrupted('delivery_response_committed',delivery=True)


if __name__=='__main__':
    unittest.main()
