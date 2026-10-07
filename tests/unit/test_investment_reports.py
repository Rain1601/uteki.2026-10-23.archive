import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hashlib import sha256

from uteki.infrastructure.investment_reports.fxbaogao import FxBaogaoService, ReportError, Scope, load_key

PDF = b'%PDF-1.4\nsynthetic fixture, envelope only\n%%EOF\n'
SCOPE = dict(provider='fxbaogao', start_date='2024-01-01', end_date='2024-01-31', org_names=['Broker A'], report_ids=[17])

class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'FXBAOGAO_API_KEY':'secret-test-key'})
        self.env.start()
        self.calls = []
        self.rows = [dict(reportId=17, title='<em>Research A</em>', orgName='Broker A', pubTimeStr='2024/01/15/')]
        self.url = 'https://dr.fxbaogao.com/report.pdf?auth_key=signed-secret'
        self.data = PDF
        self.code = 0

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def transport(self, url, body, headers, limit):
        self.calls.append((url, body, headers, limit))
        if url.startswith('https://dr.'):
            self.assertNotIn('Authorization', headers)
            return self.data
        self.assertEqual(headers['Authorization'], 'Bearer secret-test-key')
        if '/search' in url:
            data = self.rows
        elif '/paragraph' in url:
            data = dict(title='Research A', summary='\n  ', paragraphs=[dict(content='<em>Evidence</em>',pageNum=2)])
        else:
            data = self.url
        return json.dumps(dict(code=self.code,data=data)).encode()

    def service(self, cap=0, scope=None):
        return FxBaogaoService(scope=scope or SCOPE, workspace=self.root/'work', max_downloads=cap, transport=self.transport)

    def test_missing_scope_and_credential_fail_before_network(self):
        for key in ('org_names','start_date','end_date','provider','report_ids'):
            scope={k:v for k,v in SCOPE.items() if k!=key}
            with self.assertRaises(ValueError): self.service(scope=scope)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ReportError): load_key()
            p=self.root/'key';p.write_text('FXBAOGAO_API_KEY=private-key\n');p.chmod(0o644)
            with self.assertRaises(ReportError): load_key(p)
            p.chmod(0o600)
            self.assertEqual(load_key(p),'private-key')
        self.assertEqual(self.calls,[])

    def test_scope_filters_other_broker_period_id_and_records_gap(self):
        self.rows += [dict(reportId=18,title='Other',orgName='Broker B',pubTimeStr='2024/01/15/'),
                      dict(reportId=17,title='Late',orgName='Broker A',pubTimeStr='2024/02/01/')]
        s=self.service()
        result=s.search_reports('topic')
        self.assertEqual([r['report_id'] for r in result['reports']],[17])
        self.assertEqual(result['excluded_out_of_scope'],2)
        self.assertEqual(result['reports'][0]['title'],'Research A')
        with self.assertRaises(ReportError): s.get_paragraphs(18,'topic')
        self.assertEqual(len(self.calls),1)

    def test_other_explicit_scope_works_without_sample_fallback(self):
        scope={**SCOPE,'start_date':'2023-02-01','end_date':'2023-02-28','org_names':['Broker B'],'report_ids':[29]}
        self.rows=[dict(reportId=29,title='Research B',orgName='Broker B',pubTimeStr='2023/02/10/')]
        s=self.service(scope=scope)
        result=s.search_reports('different company')
        self.assertEqual(result['reports'][0]['report_id'],29)
        params=json.loads(self.calls[0][1]);self.assertEqual(params['orgNames'],['Broker B'])
        self.assertNotIn('5429854',str(result))

    def test_validation_errors_do_not_call_provider(self):
        s=self.service()
        for keywords,page in [('',1),('x',0),('x',11),('x',True)]:
            self.assertEqual(s.invoke('search_reports',dict(keywords=keywords,page=page))['status'],'error')
        self.assertEqual(s.invoke('get_paragraphs',dict(report_id=17,keyword='x'))['status'],'error')
        self.assertFalse(self.calls)

    def test_blank_summary_and_no_key_or_signed_url_in_tool_output(self):
        s=self.service(cap=1);s.invoke('search_reports',{'keywords':'x'})
        result=s.invoke('get_paragraphs',dict(report_id=17,keyword='x'))
        self.assertIsNone(result['summary'])
        result=s.invoke('download_pdf',dict(report_id=17))
        self.assertEqual(result['status'],'downloaded')
        for file in (self.root/'work').glob('*-tool.json'):
            self.assertNotIn('secret-test-key',file.read_text())
            self.assertNotIn('signed-secret',file.read_text())
        before=len(self.calls)
        s2=self.service(cap=1);s2.search_reports('x')
        self.assertEqual(s2.download_pdf(17)['status'],'reused')
        self.assertEqual(len(self.calls),before+1)

    def test_default_download_block_and_cached_import(self):
        s=self.service();s.search_reports('x')
        self.assertEqual(s.invoke('download_pdf',{'report_id':17})['error'],'download_attempt_cap_reached')
        p=self.root/'original.pdf';p.write_bytes(PDF)
        s.import_pdf(17,p,sha256(PDF).hexdigest())
        self.assertEqual(s.download_pdf(17)['status'],'reused')
        self.assertEqual(len(self.calls),1)
        (self.root/'work'/(sha256(PDF).hexdigest()+'.pdf')).write_bytes(b'corrupt')
        self.assertEqual(s.invoke('download_pdf',{'report_id':17})['error'],'cached_pdf_missing_or_changed')
        self.assertEqual(len(self.calls),1)

    def test_failed_download_does_not_restore_budget_or_retry_after_restart(self):
        s=self.service(cap=1);s.search_reports('x');self.data=b'<html>login</html>'
        self.assertEqual(s.invoke('download_pdf',{'report_id':17})['error'],'invalid_pdf_envelope')
        s2=self.service(cap=1);s2.search_reports('x');before=len(self.calls)
        self.assertEqual(s2.invoke('download_pdf',{'report_id':17})['error'],'prior_download_attempt_requires_reconciliation')
        self.assertEqual(len(self.calls),before)
        with self.assertRaises(ReportError): self.service(cap=2)

    def test_business_error_and_unapproved_download_domain(self):
        s=self.service(cap=1);self.code=5
        self.assertEqual(s.invoke('search_reports',{'keywords':'x'})['error'],'provider_business_error')
        self.code=0;s.search_reports('x');self.url='https://evil.example/file?auth_key=signed-secret'
        self.assertEqual(s.invoke('download_pdf',{'report_id':17})['error'],'unapproved_pdf_address')
        self.assertTrue(all(not c[0].startswith('https://evil') for c in self.calls))

    def test_real_sdk_wrapper_and_agent_registration(self):
        from agents.tool_context import ToolContext
        from uteki.agents.investment_reports.agent import create_agent
        s=self.service()
        root=Path(__file__).resolve().parents[2]
        agent=create_agent(s,model='unused-test-model',skill_path=root/'skills/uteki-investment-reports/SKILL.md')
        self.assertEqual([t.name for t in agent.tools],['search_reports','get_paragraphs','download_pdf'])
        self.assertIn('Host scope:',agent.instructions)
        self.assertNotIn('secret-test-key',agent.instructions)
        output=asyncio.run(agent.tools[0].on_invoke_tool(ToolContext(context=None, tool_name="search_reports", tool_call_id="test-call", tool_arguments="{}"),json.dumps({'keywords':'topic','page':1})))
        self.assertEqual(json.loads(output)['reports'][0]['report_id'],17)

    def test_audit_includes_arguments_and_start_before_request(self):
        s=self.service()
        original=self.transport
        def observed(*args):
            starts=list((self.root/'work').glob('*-started.json'))
            self.assertEqual(len(starts),1)
            self.assertEqual(json.loads(starts[0].read_text())['arguments'],{'keywords':'topic','page':2})
            return original(*args)
        s._transport=observed
        self.assertEqual(s.invoke('search_reports',{'keywords':'topic','page':2})['status'],'searched')

    def test_cancellation_stops_pdf_request_after_download_url(self):
        s=self.service(cap=1);s.search_reports('x')
        original=self.transport
        def cancelled(url,*args):
            result=original(url,*args)
            if '/download?' in url:s.cancel()
            return result
        s._transport=cancelled
        self.assertEqual(s.invoke('download_pdf',{'report_id':17})['error'],'report_task_cancelled')
        self.assertFalse(any(c[0].startswith('https://dr.') for c in self.calls))

    def test_concurrent_services_do_not_duplicate_download(self):
        from concurrent.futures import ThreadPoolExecutor
        s1=self.service(cap=1);s2=self.service(cap=1)
        s1.search_reports('x');s2.search_reports('x')
        with ThreadPoolExecutor(2) as pool:
            result=list(pool.map(lambda s:s.invoke('download_pdf',{'report_id':17}),[s1,s2]))
        self.assertEqual(sum('/download?' in c[0] for c in self.calls),1)
        self.assertTrue(any(r['status']=='downloaded' for r in result))

if __name__=='__main__': unittest.main()
