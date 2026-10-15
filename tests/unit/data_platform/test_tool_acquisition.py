"""Sixth-tool acquisition through real source adapter and controlled transport."""
from copy import deepcopy
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.contracts.assets import SourceInput
from uteki.data_platform.contracts.common import canonical
from uteki.data_platform.retrieval.content import HtmlReader
from uteki.data_platform.contracts.query import parse
from uteki.data_platform.contracts.assets import AssetRef
from uteki.data_platform.service import DataService

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/data_platform'
C=runpy.run_path(str(FIXTURES/'catalog_worker.py'))
F=runpy.run_path(str(FIXTURES/'html_fixture.py'))


class ToolAcquisitionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='uteki-acquire-tool-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.catalog=Catalog.initialize(self.root)
        self.addCleanup(self.catalog.close)
        setup=C['setup'](self.catalog)
        source=self.catalog.register_source('official',SourceInput(source_kind='official_site',publisher_name='Synthetic official source',
            publisher_company_id=setup['company_id'],platform_name=None,canonical_url=F['MAIN_URL'],policy_ref='synthetic-policy-v1'),run_id=setup['run_id'])
        self.catalog.register_policy('official-read',definition=canonical(dict(schema_version='uteki-read-policy-v1',source_kinds=['official_site'],source_ids=[source])).decode(),run_id=setup['run_id'])
        self.acquire=dict(company_id=setup['company_id'],material_types=['synthetic-document'],periods=[],
            source_hints=[dict(connector='official_html',url=F['MAIN_URL'])])
        unknown=dict(value=None,basis=None,unknown_reason='not_processed')
        self.plan=dict(request=self.acquire,asset_id=setup['asset_id'],source_id=source,
            relation=dict(company_id=setup['company_id'],role='issuer',basis='source_metadata',status='confirmed',evidence=C['evidence']().model_dump(mode='json')),
            published_at=unknown,available_at=unknown,source_revised_at=unknown,version_consistency='consistent',
            revision_of_snapshot_id=None,revision_basis=None,main_url=F['MAIN_URL'],allowed_urls=[F['MAIN_URL'],F['IMAGE_URL']],max_seconds=5,
            config=dict(symbol='SYN',cik='0000000001',market='US',as_of='2024-06-30',
                filing_selection=dict(mode='filing_period',form_type='10-K',report_period_end='2024-06-29'),
                source_policy={'official':[],'third_party':[]},limits=dict(max_requests=3,max_documents=3,max_total_bytes=100000,
                    max_bytes_per_document=50000,timeout_seconds=2,retries=0,min_request_interval_seconds=0)),
            form_type='synthetic',profile_ref='synthetic',taxonomy_ref='source')
        self.context_request=dict(question='Explicit source update',caller={'kind':'user'},entities={'company_ids':[setup['company_id']]},
            source_policy_ref='official-read',expansion=dict(mode='controlled',allow=['acquire','process'],deny=[]),
            run_policy=dict(max_usd='0',max_turns=10,max_wall_seconds=120,max_no_progress_turns=10))
        self.state=dict(plan_update=dict(base_version=0,needs=[dict(need_id='source',description='Obtain explicit official HTML',required=True)]),
            satisfied=[],gaps=[dict(need_id='source',missing='Not yet obtained')],next_action='request_asset_update',reason='Explicit source request')
        self.request=dict(need_id='source',action='acquire',acquire=self.acquire,reason='Explicit approved acquisition')
        contact=patch('uteki.data_platform.connectors.official.resolve_sec_contact',return_value=('Synthetic fixture test@example.com','synthetic_fixture'))
        contact.start();self.addCleanup(contact.stop)

    def service(self,fetch,request=None):
        adapter=OfficialAcquisitionAdapter([self.plan],settings_root=self.root,fetch=fetch)
        service=DataService(self.catalog,acquisition_adapter=adapter)
        context=service.create_context(request or self.context_request,request_key='acquire-context')
        return service,context['context_ref']

    def call(self,service,context):
        return service.request_asset_update(context,self.request,state=self.state,request_key='acquisition-one')

    def test_controlled_transport_publishes_and_exact_replay_does_not_fetch_again(self):
        fetch=Mock(side_effect=lambda url,**kw:F['source']() if url==F['MAIN_URL'] else b'synthetic image')
        service,context=self.service(fetch)
        result=self.call(service,context)
        self.assertEqual(result['status'],'ok',result)
        item=result['items'][0]
        self.assertEqual(item['status'],'completed')
        self.assertTrue(item['update_id'].startswith('job_'))
        reader=HtmlReader(self.catalog,parse(AssetRef,item['new_asset_refs'][0]))
        self.assertTrue(reader.inventory()['records'])
        self.assertEqual(self.catalog.content.read_object(reader.inputs.main),F['source']())
        self.assertEqual(result['resource_usage']['transport_requests'],2)
        self.assertEqual(result['resource_usage']['external_calls'],0)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(self.call(service,context),result)
        self.assertEqual(fetch.call_count,2)
        self.assertNotIn('test@example.com',json.dumps(result))

    def test_process_only_expansion_cannot_acquire_with_empty_capability_list(self):
        request=deepcopy(self.context_request)
        request['expansion']={'mode':'controlled','allow':['process'],'deny':[]}
        fetch=Mock()
        service,context=self.service(fetch,request)
        result=self.call(service,context)
        self.assertEqual(result['items'][0]['status'],'denied')
        fetch.assert_not_called()

    def test_no_network_enabled_does_not_open_transport(self):
        service,context=self.service(None)
        with patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener') as opener:
            result=self.call(service,context)
        self.assertEqual(result['error']['code'],'POLICY_DENIED')
        opener.assert_not_called()
        self.assertFalse((self.root/'acquisitions').exists())

    def test_main_failure_has_receipt_no_published_reference_and_no_retry(self):
        fetch=Mock(side_effect=HTTPError(F['MAIN_URL'],403,'Synthetic forbidden',{},io.BytesIO(b'synthetic forbidden')))
        service,context=self.service(fetch)
        result=self.call(service,context)
        self.assertEqual(result['error']['code'],'ACQUISITION_FAILED')
        self.assertEqual(result['items'],[])
        self.assertEqual(result['resource_usage']['transport_requests'],1)
        self.assertEqual(fetch.call_count,1)
        reports=list((self.root/'acquisitions').glob('*/source-runs/*/manifest.json'))
        self.assertEqual(len(reports),1)
        report=json.loads(reports[0].read_text())
        self.assertTrue(any(g['reason']=='main_acquisition_failed' for g in report['gaps']))
        self.assertEqual(self.catalog._db.execute("SELECT count(*) FROM asset_builds WHERE status='published'").fetchone()[0],0)
        self.assertEqual(self.call(service,context),result)
        self.assertEqual(fetch.call_count,1)

    def test_unapproved_url_or_historical_unknown_never_fetches(self):
        fetch=Mock()
        self.context_request['as_of']='2026-01-01T00:00:00Z'
        service,context=self.service(fetch)
        result=self.call(service,context)
        self.assertEqual(result['error']['code'],'SCOPE_TIME_UNKNOWN')
        fetch.assert_not_called()
        self.request['acquire']=deepcopy(self.acquire)
        self.request['acquire']['source_hints'][0]['url']='https://example.com/not-approved'
        result=service.request_asset_update(context,self.request,state=self.state|{'plan_update':None},request_key='unapproved')
        self.assertEqual(result['error']['code'],'POLICY_DENIED')
        fetch.assert_not_called()

    def test_missing_resource_is_partial_and_remains_explicitly_missing(self):
        def transport(url,**kwargs):
            if url==F['MAIN_URL']:
                return F['source']()
            raise HTTPError(url,404,'Synthetic missing',{},io.BytesIO(b'absent'))
        service,context=self.service(transport)
        result=self.call(service,context)
        self.assertEqual(result['status'],'partial',result)
        self.assertEqual(result['items'][0]['status'],'partial')
        reader=HtmlReader(self.catalog,parse(AssetRef,result['items'][0]['new_asset_refs'][0]))
        self.assertEqual(reader.inventory()['images'][0]['status'],'missing')
        self.assertTrue(result['items'][0]['gaps'])

    def test_cancel_after_main_does_not_fetch_images_or_publish(self):
        fetch=Mock(return_value=F['source']())
        service,context=self.service(fetch)
        result=service.request_asset_update(context,self.request,state=self.state,request_key='cancel',should_cancel=lambda:fetch.call_count>0)
        self.assertEqual(result['status'],'error')
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(result['resource_usage']['transport_requests'],1)
        self.assertEqual(self.catalog._db.execute("SELECT count(*) FROM asset_builds WHERE status='published'").fetchone()[0],0)

    def test_changed_host_plan_cannot_reuse_completed_request_key(self):
        fetch=Mock(side_effect=lambda url,**kw:F['source']() if url==F['MAIN_URL'] else b'synthetic image')
        service,context=self.service(fetch)
        result=self.call(service,context)
        self.assertEqual(result['status'],'ok',result)
        self.plan['config']['limits']['max_requests']=4
        service.acquisition_adapter=OfficialAcquisitionAdapter([self.plan],settings_root=self.root,fetch=fetch)
        conflict=self.call(service,context)
        self.assertEqual(conflict['error']['code'],'IDEMPOTENCY_CONFLICT')
        self.assertEqual(fetch.call_count,2)


if __name__=='__main__':
    unittest.main()
