"""Review regressions using installed code, synthetic sources and bounded failures."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from uteki.data_platform.application import session as sessions
from uteki.data_platform.application import limits
from uteki.data_platform.application.tools import ToolExecution
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.retrieval.index import DerivedIndex, sql_connection
from uteki.data_platform.service import DataService

HERE = Path(__file__).resolve().parent
Q = runpy.run_path(str(HERE/'test_queries.py'))
A = runpy.run_path(str(HERE/'test_tool_acquisition.py'))


class ReviewFixTests(unittest.TestCase):
    def fixture(self, acquisition=False):
        fixture = (A['ToolAcquisitionTests'] if acquisition else Q['DataToolTests'])()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_original_slow_fetch_stops_before_attachment_or_publication(self):
        f = self.fixture(True)
        requests = []
        def fetch(url, **kwargs):
            requests.append((url,kwargs['timeout']))
            time.sleep(1.25)
            return A['F']['source']()
        request = deepcopy(f.context_request)
        request['run_policy']['max_wall_seconds'] = 1
        service,context = f.service(fetch,request)
        result = f.call(service,context)
        self.assertEqual(result['error']['code'],'BUDGET_EXCEEDED',result)
        self.assertEqual(len(requests),1)
        self.assertLessEqual(requests[0][1],1)
        self.assertGreater(requests[0][1],0)
        self.assertEqual(f.catalog._db.execute("SELECT count(*) FROM asset_builds WHERE status='published'").fetchone()[0],0)
        self.assertEqual(result['resource_usage']['transport_requests'],1)
        self.assertEqual(result['error']['details']['effects'][0]['kind'],'acquisition_receipt')
        self.assertEqual(f.call(service,context),result)
        state=deepcopy(f.state);state.pop('plan_update')
        exhausted=service.request_asset_update(context,f.request,state=state,request_key='second')
        self.assertEqual(exhausted['error']['code'],'BUDGET_EXCEEDED')
        self.assertEqual(len(requests),1)

    def test_preflight_time_is_charged_without_accepting_plan(self):
        f = self.fixture()
        original = ToolExecution.preflight
        clock = [time.monotonic()]
        def slow(execution):
            original(execution)
            clock[0] += 121
        with patch.object(limits,'time',SimpleNamespace(monotonic=lambda:clock[0])), patch.object(ToolExecution,'preflight',slow):
            result=f.call('find_assets',dict(filters={'company_ids':[f.setup['company_id']]}))
        self.assertEqual(result['error']['code'],'BUDGET_EXCEEDED',result)
        self.assertEqual(f.service.inspect_context(f.context)['plan']['version'],0)
        self.assertGreaterEqual(sessions.Session(f.catalog,f.context).data['wall_seconds'],120)
        result=f.call('find_assets',dict(filters={'company_ids':[f.setup['company_id']]}))
        self.assertEqual(result['error']['code'],'BUDGET_EXCEEDED')

    def test_index_cancellation_and_deadline_preserve_old_head(self):
        for cause in ('cancel','deadline'):
            with self.subTest(cause=cause):
                f=self.fixture(); f.process(); old=f.index.current()[1]
                cancelled=[False]; clock=[time.monotonic()]
                def stop(phase):
                    if phase=='index_before_head':
                        if cause=='cancel':cancelled[0]=True
                        else:clock[0]+=121
                with patch.object(limits,'time',SimpleNamespace(monotonic=lambda:clock[0])):
                    result=f.call('request_asset_update',dict(need_id='need-1',action='process',process=dict(asset_ref=f.reference.model_dump(mode='json'),capabilities=['text_search']),reason='Explicit rebuild'),
                        checkpoint=stop,should_cancel=lambda:cancelled[0])
                self.assertEqual(result['error']['code'],'CANCELLED' if cause=='cancel' else 'BUDGET_EXCEEDED',result)
                self.assertEqual(f.index.current()[1]['generation'],old['generation'])

    def test_cancel_after_index_commit_reports_effect_and_replays(self):
        f=self.fixture();f.process();old=f.index.current()[1]
        cancelled=[False]
        def stop(phase):
            if phase=='index_after_head':cancelled[0]=True
        args=dict(need_id='need-1',action='process',process=dict(asset_ref=f.reference.model_dump(mode='json'),capabilities=['text_search']),reason='Explicit rebuild')
        state=f.state('request_asset_update')
        result=f.service.request_asset_update(f.context,args,state=state,request_key='commit-stop',checkpoint=stop,should_cancel=lambda:cancelled[0])
        self.assertEqual(result['error']['code'],'CANCELLED',result)
        effect=result['error']['details']['effects'][0]
        self.assertEqual(effect['status'],'committed')
        self.assertNotEqual(effect['generation'],old['generation'])
        self.assertEqual(effect['generation'],f.index.current()[1]['generation'])
        self.assertEqual(f.service.request_asset_update(f.context,args,state=state,request_key='commit-stop'),result)

    def test_index_sync_failure_reports_uncertain_not_success(self):
        f=self.fixture();f.process()
        import uteki.data_platform.retrieval.index as indexes
        write=indexes.write_control
        def failure(path,*args,**kwargs):
            write(path,*args,**kwargs)
            raise OSError('synthetic sync acknowledgement lost')
        with patch.object(indexes,'write_control',failure):
            with self.assertRaises(CatalogError) as caught:
                f.call('request_asset_update',dict(need_id='need-1',action='process',process=dict(asset_ref=f.reference.model_dump(mode='json'),capabilities=['text_search']),reason='Explicit rebuild'))
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(caught.exception.details['effects'][0]['status'],'uncertain')
        operation=next(o for o in f.service.inspect_context(f.context)['operations'].values() if o['status']=='accepted')
        recovered=f.service.call(f.context,operation['tool'],operation['request'],state=operation['state'],
            request_key=operation['request_key'],recover=True)
        self.assertEqual(recovered['items'][0]['derived_generation'],f.index.current()[1]['generation'])
        self.assertTrue(recovered['resource_usage']['execution_time_uncertain'])

    def test_acquisition_cancel_at_publication_boundaries_reports_actual_state(self):
        for phase,published in [('before_build_commit',0),('after_build_commit',1)]:
            with self.subTest(phase=phase):
                f=self.fixture(True);cancelled=[False]
                def stop(value):
                    if value==phase:cancelled[0]=True
                service,context=f.service(lambda url,**kw:A['F']['source']() if url==A['F']['MAIN_URL'] else b'synthetic image')
                if not published:
                    with self.assertRaises(CatalogError) as caught:
                        service.request_asset_update(context,f.request,state=f.state,request_key='cancel-publication',checkpoint=stop,should_cancel=lambda:cancelled[0])
                    self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
                    effects=caught.exception.details['effects']
                else:
                    result=service.request_asset_update(context,f.request,state=f.state,request_key='cancel-publication',checkpoint=stop,should_cancel=lambda:cancelled[0])
                    self.assertEqual(result['error']['code'],'CANCELLED',result)
                    effects=result['error']['details']['effects']
                self.assertEqual(f.catalog._db.execute("SELECT count(*) FROM asset_builds WHERE status='published'").fetchone()[0],published)
                builds=[e for e in effects if e['kind']=='build']
                self.assertEqual(builds[0]['status'],'published' if published else 'staging')
                if not published:
                    result=service.request_asset_update(context,f.request,state=f.state,request_key='cancel-publication',recover=True)
                    self.assertEqual(result['items'][0]['status'],'completed')
                    self.assertTrue(result['resource_usage']['execution_time_uncertain'])
                self.assertEqual(service.request_asset_update(context,f.request,state=f.state,request_key='cancel-publication'),result)

    def test_native_query_obeys_deadline_and_cancellation(self):
        for cause in ('deadline','cancel'):
            with self.subTest(cause=cause):
                cancelled=threading.Event()
                timer=threading.Timer(.05,cancelled.set)
                limit=limits.ExecutionLimit(.05 if cause=='deadline' else 10,should_cancel=cancelled.is_set)
                if cause=='cancel':timer.start()
                try:
                    with self.assertRaises(CatalogError) as failure:
                        with sql_connection(':memory:',readonly=False,limit=limit) as db:
                            db.execute('SELECT sum(sin(i)) FROM range(100000000) AS t(i)').fetchall()
                    self.assertEqual(failure.exception.code,'BUDGET_EXCEEDED' if cause=='deadline' else 'CANCELLED')
                finally:
                    if cause=='cancel':timer.cancel();timer.join()

    def test_current_title_affects_discovery_but_candidates_and_history_do_not(self):
        f=self.fixture();asset=f.setup['asset_id'];old=f.catalog.get_asset(asset)
        revision=next(r for r in f.catalog.revisions('asset',asset) if r['field']=='title' and r['status']=='current')
        base=dict(object_type='asset',object_id=asset,field='title',reason='Synthetic correction',evidence=Q['C']['evidence'](),run_id=f.setup['run_id'])
        for status in ('candidate','conflict'):
            f.catalog.record_revision(**base,value=status+'Needle',status=status,supersedes_revision_id=None)
            found=f.call('find_assets',dict(query=status+'Needle'))
            self.assertEqual(found['items'],[])
        f.catalog.record_revision(**base,value='RevisedTitleNeedle report',status='current',supersedes_revision_id=revision['revision_id'])
        found=f.call('find_assets',dict(query='RevisedTitleNeedle'))
        self.assertEqual([r['title'] for r in found['items']],['RevisedTitleNeedle report'])
        self.assertEqual(found['items'][0]['asset_ref'],f.reference.model_dump(mode='json'))
        self.assertEqual(f.catalog.get_asset(asset)['payload'],old['payload'])
        self.assertEqual(f.catalog.content.read_object(f.reader.inputs.main),Q['F']['source']('<p>投资研究 waterfall running 现金流。 Straße.</p>').replace(b'<img src="chart.png" alt="Synthetic chart">',b''))

    def test_mapping_failure_requires_explicit_recovery_of_same_identity(self):
        f=self.fixture();write=sessions.write_control
        def fail(path,*args,**kwargs):
            if Path(path).parent.name=='contexts':raise OSError('synthetic mapping write failure')
            return write(path,*args,**kwargs)
        with patch.object(sessions,'write_control',fail),self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='mapping-failure')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        run=f.catalog._db.execute("SELECT * FROM runs WHERE request_key=?",('data-context:mapping-failure',)).fetchone()
        head=json.loads((f.root/'runs'/run['run_id']/'head.json').read_bytes())
        from uteki.data_platform.contracts.content import ObjectRef
        original=json.loads(f.catalog.content.read_object(ObjectRef.model_validate(head)))['context']
        f.catalog.close();catalog=Catalog.open(f.root);self.addCleanup(catalog.close);service=DataService(catalog)
        with self.assertRaises(CatalogError) as failure:service.create_context(f.request,request_key='mapping-failure')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        recovered=service.create_context(f.request,request_key='mapping-failure',recover=True)
        self.assertEqual(recovered,original)
        self.assertEqual(service.create_context(f.request,request_key='mapping-failure'),original)
        self.assertTrue(service.inspect_context(f.context))

    def test_recovery_rejects_changed_request_and_does_not_reset_completed_head(self):
        f=self.fixture();write=sessions.write_control
        def fail(path,*args,**kwargs):
            if Path(path).parent.name=='contexts':raise OSError('synthetic mapping failure')
            return write(path,*args,**kwargs)
        with patch.object(sessions,'write_control',fail),self.assertRaises(CatalogError):
            f.service.create_context(f.request,request_key='recovery-guard')
        changed=deepcopy(f.request);changed['run_policy']['max_turns']=99
        with self.assertRaises(CatalogError) as failure:
            f.service.create_context(changed,request_key='recovery-guard',recover=True)
        self.assertEqual(failure.exception.code,'IDEMPOTENCY_CONFLICT')
        context=f.service.create_context(f.request,request_key='recovery-guard',recover=True)
        run_path=f.root/'runs'/context['run_id']
        head=(run_path/'head.json').read_bytes()
        (run_path/'head.json').unlink()
        with self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='recovery-guard',recover=True)
        self.assertEqual(failure.exception.code,'CONTEXT_INVALID')
        self.assertFalse((run_path/'head.json').exists())
        (run_path/'head.json').write_bytes(head)
        self.assertEqual(f.service.create_context(f.request,request_key='recovery-guard'),context)

    def test_initial_head_write_failure_recovers_the_prepared_context(self):
        f=self.fixture();write=sessions.write_control
        def fail(path,*args,**kwargs):
            if Path(path).name=='head.json':raise OSError('synthetic head write failure')
            return write(path,*args,**kwargs)
        with patch.object(sessions,'write_control',fail),self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='head-failure')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        run=f.catalog._db.execute('SELECT * FROM runs WHERE request_key=?',('data-context:head-failure',)).fetchone()
        from uteki.data_platform.contracts.content import ObjectRef
        initial=ObjectRef.model_validate_json((f.root/'runs'/run['run_id']/'creation.json').read_bytes())
        saved=json.loads(f.catalog.content.read_object(initial))['context']
        self.assertEqual(f.service.create_context(f.request,request_key='head-failure',recover=True),saved)

    def test_first_control_write_failure_recovers_durable_creation_intent(self):
        f=self.fixture();write=sessions.write_control
        def fail(path,*args,**kwargs):
            if Path(path).name=='creation.json':raise OSError('synthetic first control write failure')
            return write(path,*args,**kwargs)
        with patch.object(sessions,'write_control',fail),self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='first-control-failure')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        row=f.catalog._db.execute('SELECT result_id FROM registrations WHERE namespace=? AND request_key=?',('data-context-creation','first-control-failure')).fetchone()
        from uteki.data_platform.contracts.content import ObjectRef
        initial=ObjectRef.model_validate_json(row['result_id'])
        saved=json.loads(f.catalog.content.read_object(initial))['context']
        with self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='first-control-failure')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        self.assertEqual(f.service.create_context(f.request,request_key='first-control-failure',recover=True),saved)

    def test_visible_mapping_without_sync_ack_is_reacknowledged_before_success(self):
        f=self.fixture();write=sessions.write_control
        def uncertain(path,*args,**kwargs):
            write(path,*args,**kwargs)
            if Path(path).parent.name=='contexts':raise OSError('synthetic mapping sync acknowledgement failure')
        with patch.object(sessions,'write_control',uncertain),self.assertRaises(CatalogError) as failure:
            f.service.create_context(f.request,request_key='mapping-sync')
        self.assertEqual(failure.exception.code,'RECOVERY_REQUIRED')
        with patch.object(sessions,'write_control',wraps=write) as observed:
            context=f.service.create_context(f.request,request_key='mapping-sync',recover=True)
        writes=[Path(c.args[0]) for c in observed.call_args_list]
        self.assertIn(f.root/'contexts'/context['context_ref'],writes)
        self.assertLess(next(i for i,p in enumerate(writes) if p.parent.name=='contexts'),next(i for i,p in enumerate(writes) if p.name=='creation-complete.json'))
        self.assertEqual(f.service.create_context(f.request,request_key='mapping-sync'),context)

    def test_metadata_revision_and_rebuild_leave_old_delivery_and_reference_readable(self):
        f=self.fixture()
        block=next(b for b in f.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        read=f.call('read_evidence',dict(asset_ref=f.reference.model_dump(mode='json'),targets=[{'block_id':block['id']}]))
        refs=[read['items'][0]['result_ref']]
        delivered=f.service.deliver(f.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=refs,gaps=[])]),
            state=f.state('deliver',refs,supported=True),request_key='old-delivery')
        frozen=canonical(delivered['delivery']);old_context=f.context
        revision=next(r for r in f.catalog.revisions('asset',f.setup['asset_id']) if r['field']=='title' and r['status']=='current')
        f.catalog.record_revision(object_type='asset',object_id=f.setup['asset_id'],field='title',value='RevisedNeedle source',status='current',
            reason='Synthetic corrected title',evidence=Q['C']['evidence'](),run_id=f.setup['run_id'],supersedes_revision_id=revision['revision_id'])
        f.context=f.service.create_context(f.request,request_key='new-reading')['context_ref']
        f.process()
        self.assertEqual(f.call('find_assets',dict(query='RevisedNeedle'))['items'][0]['asset_ref'],f.reference.model_dump(mode='json'))
        f.catalog.close();catalog=Catalog.open(f.root);self.addCleanup(catalog.close)
        self.assertEqual(canonical(DataService(catalog).read_delivery(old_context)),frozen)
        restored=Q['HtmlReader'](catalog,f.reference).inventory()['blocks']
        self.assertEqual(next(b['text'] for b in restored if b['id']==block['id']),block['text'])

    def test_ranking_relevance_ties_and_cursor_readiness(self):
        f=self.fixture()
        references=[]
        for label in ('first','second','third'):
            reference,_=f.another_asset(label,Q['F']['source']());references.append(reference)
        titles=['waterfall','waterfall','waterfall '+'unrelated '*80]
        for reference,title in zip(references,titles):
            revision=next(r for r in f.catalog.revisions('asset',reference.asset_id) if r['field']=='title' and r['status']=='current')
            f.catalog.record_revision(object_type='asset',object_id=reference.asset_id,field='title',value=title,status='current',reason='Synthetic ranking title',
                evidence=Q['C']['evidence'](),run_id=f.setup['run_id'],supersedes_revision_id=revision['revision_id'])
        expected=sorted([r.model_dump(mode='json') for r in references[:2]],key=canonical)+[references[2].model_dump(mode='json')]
        args=dict(query='waterfall',limit=1);seen=[];views=[]
        while True:
            response=f.call('find_assets',args)
            self.assertEqual(response['status'],'ok',response)
            seen.extend(r['asset_ref'] for r in response['items']);views.append(response['coverage']['catalog_view'])
            if not response['next_cursor']:break
            args=args|{'cursor':response['next_cursor']}
        self.assertEqual(seen,expected)
        self.assertEqual(len(set(views)),1)
        # Real-time readiness is not a ranking/filter field. Its failure does
        # not mutate the candidate identity/order bound by the catalog cursor.
        first=f.call('find_assets',dict(query='waterfall',limit=1))
        from uteki.data_platform.contracts.assets import AssetRef
        reader=Q['HtmlReader'](f.catalog,AssetRef.model_validate(expected[1]))
        index=DerivedIndex(f.catalog,reader);directory,_,_=index.current()
        (directory/'records.duckdb').write_bytes(b'synthetic corrupt index')
        second=f.call('find_assets',dict(query='waterfall',limit=1,cursor=first['next_cursor']))
        self.assertEqual(second['items'][0]['asset_ref'],expected[1])
        self.assertEqual(second['items'][0]['readiness']['text_search'],'not_ready')
        self.assertEqual(second['coverage']['catalog_view'],first['coverage']['catalog_view'])


if __name__=='__main__':
    unittest.main()
