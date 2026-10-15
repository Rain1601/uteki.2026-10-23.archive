"""Bounded transport behavior; all responses are synthetic, no real network."""
import io
import json
from pathlib import Path
import runpy
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.request import Request

from uteki.data_platform.connectors.official import acquire_html,store_acquisition
from uteki.data_platform.content import ContentStore
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.contracts.content import MissingResource
from uteki.infrastructure.document_sources.company_acquisition import AcquisitionError,_Redirect,prepare_sources

F=runpy.run_path(str(Path(__file__).resolve().parents[2]/'fixtures/data_platform/html_fixture.py'))


class OfficialAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='uteki-official-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.contact=patch('uteki.data_platform.connectors.official.resolve_sec_contact',return_value=('Synthetic Tests test@example.com','synthetic_fixture'))
        self.contact.start();self.addCleanup(self.contact.stop)
        self.config=dict(symbol='SYN',cik='0000000001',market='US',as_of='2024-06-30',filing_selection={'mode':'filing_period','form_type':'10-K','report_period_end':'2024-06-29'},source_policy={'official':[],'third_party':[]},limits=dict(max_requests=8,max_documents=6,max_total_bytes=100000,max_bytes_per_document=50000,timeout_seconds=2,retries=0,min_request_interval_seconds=0))

    def acquire(self,fetch,allowed=None,seconds=5):
        return acquire_html(config=self.config,workspace=self.root,settings_root=self.root,main_url=F['MAIN_URL'],
            allowed_urls=allowed or (F['MAIN_URL'],F['IMAGE_URL']),max_seconds=seconds,fetch=fetch)

    def test_exact_url_policy_and_duplicate_resources(self):
        raw=F['source']('<img src="chart.png"><img src="https://other.example/blocked.png">')
        requests=[]
        def fetch(url,**kwargs):requests.append(url);return raw if url==F['MAIN_URL'] else b'figure'
        acquired=self.acquire(fetch)
        self.assertEqual(requests,[F['MAIN_URL'],F['IMAGE_URL']])
        self.assertEqual(acquired['missing'],{'https://other.example/blocked.png':'not_allowed_by_frozen_source_policy'})
        store=ContentStore(self.root);ref=store_acquisition(store,acquired,main_url=F['MAIN_URL']);inputs=store.read_manifest(ref)
        self.assertEqual(store.read_object(inputs.main),raw)
        self.assertEqual(sum(isinstance(r,MissingResource) for r in inputs.resources),1)
        self.assertNotIn('test@example.com',json.dumps(acquired['report']))

    def test_resource_failure_preserves_response_and_distinguishes_missing(self):
        def fetch(url,**kwargs):
            if url==F['MAIN_URL']:return F['source']()
            raise HTTPError(url,403,'Synthetic denial',{},io.BytesIO(b'synthetic denied page'))
        acquired=self.acquire(fetch)
        self.assertEqual(acquired['report']['requests'],2)
        self.assertIn(F['IMAGE_URL'],acquired['missing'])
        failure=next(d for d in acquired['report']['discovery'] if d['status']=='failed')
        self.assertEqual((self.root/failure['partial_path']).read_bytes(),b'synthetic denied page')
        self.assertFalse(failure['eligible_original'])
        self.assertEqual(acquired['report']['status'],'completed_with_gaps')

    def test_main_403_has_no_success_or_retry(self):
        fetch=Mock(side_effect=HTTPError(F['MAIN_URL'],403,'Synthetic denial',{},io.BytesIO(b'denied')))
        with self.assertRaises(CatalogError) as error:self.acquire(fetch)
        self.assertEqual(error.exception.code,'ACQUISITION_FAILED');self.assertEqual(fetch.call_count,1)
        manifests=list((self.root/'source-runs').glob('*/manifest.json'));self.assertEqual(len(manifests),1)
        report=json.loads(manifests[0].read_text());self.assertTrue(any(g['reason']=='main_acquisition_failed' for g in report['gaps']))

    def test_failed_resource_counts_toward_document_limit(self):
        self.config['limits']['max_documents']=2;second='https://example.com/report/second.png';calls=[]
        def fetch(url,**kwargs):
            calls.append(url)
            if url==F['MAIN_URL']:return F['source']('<img src="second.png">')
            raise HTTPError(url,404,'Synthetic absent',{},io.BytesIO(b'absent'))
        acquired=self.acquire(fetch,allowed=(F['MAIN_URL'],F['IMAGE_URL'],second))
        self.assertEqual(calls,[F['MAIN_URL'],F['IMAGE_URL']]);self.assertEqual(acquired['missing'][second],'document_limit')

    def test_deadline_and_invalid_html_do_not_return_partial_success(self):
        def slow(url,**kwargs):time.sleep(.01);return F['source']()
        with self.assertRaises(CatalogError):self.acquire(slow,seconds=.001)
        report=json.loads(next((self.root/'source-runs').glob('*/manifest.json')).read_text())
        self.assertEqual(report['status'],'cancelled')
        with self.assertRaises(CatalogError):self.acquire(lambda *a,**kw:b'not HTML')

    def test_request_and_redirect_guard_run_before_target_transport(self):
        approved=F['MAIN_URL'];target='https://example.com/unapproved';calls=[]
        def guard(url):
            calls.append(url)
            if url!=approved:raise AcquisitionError('outside exact allowlist')
        config=self.config|{'sec_user_agent':'Synthetic Tests test@example.com'}
        fetch=Mock(return_value=F['source']())
        session=prepare_sources(config,self.root,fetch=fetch,_session_only=True,request_guard=guard)
        with self.assertRaises(AcquisitionError):session['request'](target,{'example.com'})
        self.assertEqual(fetch.call_count,0)
        session['finish']()
        # Exercise prepare_sources' real redirect callback wiring, while the
        # opener supplies a synthetic redirect and never opens a socket.
        def opener(*handlers):
            redirect=next(h for h in handlers if isinstance(h,_Redirect))
            result=Mock()
            result.open.side_effect=lambda request,**kw:redirect.redirect_request(request,None,302,'Found',{},target)
            return result
        redirected=prepare_sources(config,self.root,_session_only=True,request_guard=guard)
        with patch('uteki.infrastructure.document_sources.company_acquisition.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), patch('uteki.infrastructure.document_sources.company_acquisition.urllib.request.build_opener',side_effect=opener):
            with self.assertRaises(AcquisitionError):redirected['request'](approved,{'example.com'})
        self.assertEqual(calls,[target,approved,target])
        self.assertEqual(redirected['report']['requests'],1)
        redirected['finish']()

    def test_size_limit_retains_failure_and_hidden_resources_are_not_requested(self):
        self.config['limits']['max_bytes_per_document']=20
        fetch=Mock(return_value=F['source']())
        with self.assertRaises(CatalogError):self.acquire(fetch)
        self.assertEqual(fetch.call_count,1)
        self.config['limits']['max_bytes_per_document']=50000
        calls=[]
        def normal(url,**kw):calls.append(url);return F['source']('<div hidden><img src="private.png"></div>') if url==F['MAIN_URL'] else b'figure'
        acquired=self.acquire(normal)
        self.assertEqual(len(calls),2);self.assertTrue(acquired['excluded']);self.assertFalse(acquired['missing'])

    def test_srcset_gap_is_in_frozen_input_without_fetching_variants(self):
        raw=F['source']().replace(b'src="chart.png"',b'src="chart.png" srcset="larger.png 2x"')
        calls=[]
        def fetch(url,**kw):calls.append(url);return raw if url==F['MAIN_URL'] else b'figure'
        acquired=self.acquire(fetch)
        self.assertEqual(calls,[F['MAIN_URL'],F['IMAGE_URL']])
        self.assertEqual(len(acquired['unsupported']),1)
        store=ContentStore(self.root);ref=store_acquisition(store,acquired,main_url=F['MAIN_URL']);inputs=store.read_manifest(ref)
        self.assertEqual(sum(isinstance(r,MissingResource) for r in inputs.resources),1)
        from uteki.data_platform.build.html import parse_html
        parsed=parse_html(raw,inputs,encoding='utf-8',form_type='synthetic')
        self.assertTrue(any(i.startswith('unsupported_srcset:') for i in parsed.quality.issues))


if __name__=='__main__':unittest.main()
