import asyncio
import tempfile
import unittest
import urllib.error
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uteki.infrastructure.document_sources.official_discovery import OfficialDiscovery, _PublicHTTPSConnection
from uteki.infrastructure.document_sources.company_acquisition import AcquisitionCancelled, AcquisitionError, LimitReached, _Redirect
from uteki.agents.data_query.official_acquisition import run_official_acquisition

ROOT = 'https://ir.example.com/'
DOC = ROOT + 'report'
HTML = b'<html><body>Acme Holdings Annual Report 2025 for year ended December 31, 2025</body></html>'

def inputs():
    company = dict(company_id='sec-0000000001', symbol='ACME', cik='0000000001', market='US', name='Acme Holdings', aliases=['Acme Holdings'])
    config = dict(symbol='ACME', cik='0000000001', market='US', as_of='2026-10-12', sec_user_agent='test contact@example.com',
        filing_selection=dict(mode='annual_filing_period', annual_form='10-K', report_period_end='2025-12-31'),
        source_policy=dict(official=[dict(kind='ir', url=ROOT, allowed_hosts=['ir.example.com'])], third_party=[], updates_window={'trailing_calendar_days':365}),
        limits=dict(timeout_seconds=10,max_requests=5,max_documents=2,max_total_bytes=100000,max_bytes_per_document=50000,retries=1,backoff_seconds=0))
    task = dict(company=company, fiscal_year=2025, period_end='2025-12-31', material_type='annual_report', task='Find the FY2025 annual report',
        roots=[ROOT], allowed_hosts=['ir.example.com'], max_steps=8,page_chars=1000,links_per_page=10)
    return config, task

def browse(url):return dict(operation='browse', url=url, offset=0, link_offset=0)
def download(url=DOC):return dict(operation='download', url=url,reason='Requested annual report',company_quote='Acme Holdings',period_quote='2025',material_quote='Annual Report')

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
        self.config,self.task=inputs()
        self.pages={ROOT:b'<html><a href="/report">2025 report</a><a href="/copy">copy</a></html>',DOC:HTML,ROOT+'copy':HTML}
    def session(self, **kwargs):return OfficialDiscovery(self.config,self.task,self.path,fetch=lambda url,**_:self.pages[url],**kwargs)
    def acquire(self,s,url=DOC):
        s.execute(browse(ROOT));s.execute(browse(url));return s.execute(download(url))
    def test_observed_download_unknown_date_and_duplicate(self):
        s=self.session();a=self.acquire(s)['document'];s.execute(browse(ROOT+'copy'));b=s.execute(download(ROOT+'copy'))['document']
        self.assertEqual(a['path'],b['path']);self.assertNotEqual(a['source_id'],b['source_id'])
        self.assertEqual(b['same_content_sources'],[DOC]);self.assertFalse(a['as_of_eligible']);self.assertIsNone(a['available_at'])
        self.assertEqual(a['discovered_from'][0]['page_url'],ROOT);s.finish('finished')
    def test_revision_keeps_previous_bytes(self):
        s=self.session();a=self.acquire(s)['document'];s.finish('finished')
        self.pages[DOC]=HTML.replace(b'</body>',b' Revised</body>')
        s=self.session();b=self.acquire(s)['document'];s.finish('finished')
        self.assertEqual(b['change'],'revised');self.assertEqual(b['previous_content_sha256'],a['content_sha256'])
        self.assertEqual((self.path/a['path']).read_bytes(),HTML)
    def test_unobserved_and_private_url(self):
        s=self.session()
        for url in (ROOT+'invented','https://localhost/', 'https://127.0.0.1/'):
            with self.assertRaises(ValueError):s.execute(browse(url))
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(AcquisitionError):_PublicHTTPSConnection('ir.example.com').connect()
        with self.assertRaises(AcquisitionError):
            _Redirect({'ir.example.com'}).redirect_request(None,None,302,'',{},'https://127.0.0.1/')
    def test_wrong_identity_period_and_unread_quote(self):
        for field,value in [('company_quote','Another Company'),('period_quote','2024'),('material_quote','not in page')]:
            s=self.session();s.execute(browse(ROOT));s.execute(browse(DOC));a=download();a[field]=value
            self.assertEqual(s.execute(a)['status'],'gap');self.assertEqual(s.report['documents'],[])
    def test_config_scope(self):
        for field,value in [('period_end','2024-12-31'),('roots',[DOC]),('allowed_hosts',['unapproved.example'])]:
            t=deepcopy(self.task);t[field]=value
            with self.assertRaises(ValueError):OfficialDiscovery(self.config,t,self.path)
    def test_permanent_failure_and_recovery_new_run(self):
        calls=[]
        def fetch(url,**_):
            calls.append(url);raise urllib.error.HTTPError(url,403,'blocked',{},None)
        s=OfficialDiscovery(self.config,self.task,self.path,fetch=fetch)
        self.assertEqual(s.execute(browse(ROOT))['reason'],'access_denied_or_challenge')
        s.execute(browse(ROOT));self.assertEqual(len(calls),1);s.finish('material_unavailable')
        self.assertEqual(self.acquire(self.session())['status'],'archived_pending_review')
    def test_stop_and_limits(self):
        s=self.session(should_stop=lambda:True)
        with self.assertRaises(AcquisitionCancelled):s.execute(browse(ROOT))
        self.assertEqual(s.finish('acquisition_cancelled')['status'],'cancelled')
        self.config['limits']['max_requests']=1;s=self.session();s.execute(browse(ROOT))
        with self.assertRaises(LimitReached):s.execute(browse(DOC))
    def test_agent_dispatch(self):
        class Planner:
            actions=iter([browse(ROOT),browse(DOC),download()])
            async def decide(self,packet):
                try:return dict(action='acquire',requirement_ids=['official-material'],arguments={'official':next(self.actions)})
                except StopIteration:return {'action':'finish'}
        result=asyncio.run(run_official_acquisition(self.config,self.task,self.path,self.path/'run',Planner(),fetch=lambda url,**_:self.pages[url]))
        self.assertEqual(len(result['documents']),1);self.assertEqual(result['stop_reason'],'finished')

    def test_transient_retry_and_bytes(self):
        calls=[]
        def fetch(url,**_):
            calls.append(url)
            if len(calls)==1:raise urllib.error.URLError('temporary')
            return self.pages[url]
        s=OfficialDiscovery(self.config,self.task,self.path,fetch=fetch)
        self.assertEqual(s.execute(browse(ROOT))['status'],'observed')
        self.assertEqual(len(calls),2)
        self.config['limits']['max_total_bytes']=10;s=self.session()
        with self.assertRaises(LimitReached):s.execute(browse(ROOT))
        self.assertEqual(s.report['documents'],[])

    def test_wrong_original_company_and_year(self):
        for raw in (HTML.replace(b'Acme Holdings',b'Other Holdings'),HTML.replace(b'2025',b'2024')):
            self.pages[DOC]=raw;s=self.session();s.execute(browse(ROOT));s.execute(browse(DOC))
            self.assertEqual(s.execute(download())['status'],'gap');self.assertEqual(s.report['documents'],[])

    def test_cancellation_drains_download_before_sealing(self):
        import threading
        from uteki.agents.data_query.coordinator import CompanyDataCoordinator
        entered=threading.Event();release=threading.Event()
        def fetch(url,**_):
            entered.set();release.wait(2);return self.pages[url]
        s=OfficialDiscovery(self.config,self.task,self.path,fetch=fetch)
        async def cancel():
            worker=asyncio.create_task(CompanyDataCoordinator._worker(s.execute,browse(ROOT)))
            await asyncio.to_thread(entered.wait,2)
            worker.cancel();await asyncio.sleep(0);release.set()
            with self.assertRaises(asyncio.CancelledError):await worker
        asyncio.run(cancel());r=s.finish('acquisition_cancelled')
        self.assertEqual(r['status'],'cancelled');self.assertEqual(r['documents'],[])
        self.assertFalse(list(self.path.glob('sources/objects/*.bin')))

    def test_previous_version_uses_observation_time_not_random_run_suffix(self):
        import json
        from uteki.infrastructure.document_sources.company_acquisition import _sha
        # Lexical order intentionally disagrees with observation time.
        for name,when,raw in [('z-older','2026-01-01T00:00:00+00:00',b'older'),
                              ('a-newer','2026-01-02T00:00:00+00:00',b'newer')]:
            directory=self.path/'source-runs'/name;directory.mkdir(parents=True)
            (directory/'manifest.json').write_text(json.dumps({'scope':{'symbol':'ACME'},
                'company':{'cik':'0000000001'},'documents':[{'source_url':DOC,
                'content_sha256':_sha(raw),'verified_at':when}]}))
        result=self.acquire(self.session())['document']
        self.assertEqual(result['previous_content_sha256'],_sha(b'newer'))
