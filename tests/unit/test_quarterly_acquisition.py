"""Explicit quarterly acquisition; independent synthetic issuers, no model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from tests.unit.data_platform.test_filing_integrity import filing


class QuarterlyAcquisitionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.called = []

    def fixture(self, symbol='QONE', cik='0000000123', period='2025-03-31', *, archived=False):
        config = {'symbol':symbol, 'cik':cik, 'market':'US', 'as_of':'2025-06-30',
            'sec_user_agent':'QuarterFixture contact@example.test',
            'filing_selection':{'mode':'filing_period', 'form_type':'10-Q', 'report_period_end':period},
            'source_policy':{'official':[], 'third_party':[]},
            'document_validation':'sec_inline_identity_v1', 'download_policy':'reuse_verified',
            'limits':{'retries':0, 'backoff_seconds':0}}
        rows = [
            ('10-Q','2025-05-01',period,cik+'-25-000001','quarter.htm'),
            ('10-Q/A','2025-06-01',period,cik+'-25-000002','amended.htm'),
            ('10-Q/A','2025-07-01',period,cik+'-25-000003','future.htm'),
            ('10-Q','2025-02-01','2024-12-31',cik+'-25-000004','other-quarter.htm'),
            ('10-K','2025-05-01',period,cik+'-25-000005','annual.htm'),
            ('8-K','2025-05-01',period,cik+'-25-000006','event.htm')]
        keys = ('form','filingDate','reportDate','accessionNumber','primaryDocument')
        encode = lambda values: {k:[r[i] for r in values] for i,k in enumerate(keys)}
        history = {'name':'quarter-history.json','filingFrom':'2025-01-01','filingTo':'2025-06-01'}
        metadata = {'cik':cik,'name':symbol,'tickers':[symbol],'exchanges':[],
            'filings':{'recent':encode(rows[3:] if archived else rows),'files':[history] if archived else []}}
        submission = f'https://data.sec.gov/submissions/CIK{cik}.json'
        responses = {submission:json.dumps(metadata).encode()}
        if archived:
            responses['https://data.sec.gov/submissions/quarter-history.json']=json.dumps(encode(rows[:3])).encode()
        for form,_,end,acc,name in rows:
            url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-","")}/{name}'
            responses[url]=filing(cik,form,end)
        def fetch(url,**kwargs):
            self.called.append(url); value=responses[url]
            if isinstance(value,Exception):raise value
            return value
        return config,responses,submission,fetch

    def test_two_issuers_and_periods_select_only_original_and_available_amendment(self):
        for symbol,cik,period in [('QONE','0000000123','2025-03-31'),('QTWO','0000000987','2025-02-28')]:
            with self.subTest(symbol=symbol):
                config,_,_,fetch=self.fixture(symbol,cik,period,archived=True)
                store=self.root/symbol
                report=prepare_sources(config,store,fetch=fetch)
                self.assertEqual(report['status'],'completed',report['gaps'])
                self.assertEqual(report['scope']['form_type'],'10-Q')
                self.assertNotIn('annual_form',report['scope'])
                self.assertEqual(report['company']['company_id'],'sec-'+cik)
                self.assertEqual([d['form'] for d in report['documents']],['10-Q','10-Q/A'])
                self.assertEqual({d['period_end'] for d in report['documents']},{period})
                self.assertTrue(report['filing_catalog']['selection_discovery_complete'])
                self.assertTrue(all(d['validation']['status']=='identity_validated' for d in report['documents']))
                self.assertEqual(report['model_calls'],0)
                for doc in report['documents']:
                    self.assertEqual(hashlib.sha256((store/doc['path']).read_bytes()).hexdigest(),doc['content_sha256'])
                before=(store/report['manifest_path']).read_bytes()
                again=prepare_sources(config,store,fetch=fetch)
                self.assertEqual({d['acquisition'] for d in again['documents']},{'reused_verified'})
                self.assertEqual((store/report['manifest_path']).read_bytes(),before)
        self.assertFalse(any(url.endswith(('future.htm','other-quarter.htm','annual.htm','event.htm')) for url in self.called))

    def test_invalid_scope_fails_before_network_or_workspace(self):
        config,_,_,fetch=self.fixture()
        invalid=[{}, {'mode':'filing_period'},
            {'mode':'filing_period','form_type':'10-Q','report_period_end':None},
            {'mode':'filing_period','form_type':'10-Q','report_period_end':'2025-02-30'},
            {'mode':'filing_period','form_type':'10-Q','report_period_end':'2025-07-01'},
            {'mode':'filing_period','form_type':'10-Q/A','report_period_end':'2025-03-31'},
            {'mode':'filing_period','form_type':'8-K','report_period_end':'2025-03-31'},
            {'mode':'filing_period','form_type':'','report_period_end':'2025-03-31'},
            {**config['filing_selection'],'annual_form':'10-K'}]
        for selected in invalid:
            with self.subTest(selected=selected),self.assertRaises(ValueError):
                prepare_sources({**config,'filing_selection':selected},self.root/'forbidden',fetch=fetch)
        self.assertEqual(self.called,[]);self.assertFalse((self.root/'forbidden').exists())

    def test_missing_original_or_period_does_not_download_another_quarter(self):
        for condition in ('amendment_only','original_after_cutoff','missing_period'):
            with self.subTest(condition=condition):
                config,responses,submission,fetch=self.fixture()
                data=json.loads(responses[submission]);recent=data['filings']['recent']
                if condition=='amendment_only':
                    for key in recent:recent[key]=recent[key][1:]
                elif condition=='original_after_cutoff':recent['filingDate'][0]='2025-07-01'
                else:config['filing_selection']['report_period_end']='2025-01-31'
                responses[submission]=json.dumps(data).encode()
                report=prepare_sources(config,self.root/condition,fetch=fetch)
                self.assertEqual(report['documents'],[])
                reasons={g['reason'] for g in report['gaps']}
                self.assertIn('filing_report_period_not_found',reasons)
                if condition!='missing_period':self.assertIn('filing_original_not_found_for_amendment',reasons)
        self.assertTrue(all('submissions/' in u for u in self.called))

    def test_wrong_download_identity_is_rejected(self):
        for field,value in [('cik','0000000456'),('form','10-K'),('period','2025-02-28')]:
            config,responses,_,fetch=self.fixture()
            url=next(u for u in responses if u.endswith('/quarter.htm'))
            args={'cik':'0000000123','form':'10-Q','period':'2025-03-31'};args[field]=value
            responses[url]=filing(**args)
            report=prepare_sources(config,self.root/field,fetch=fetch)
            self.assertTrue(any('identity_mismatch' in g.get('detail','') for g in report['gaps']))
            self.assertFalse(any(d['form']=='10-Q' for d in report['documents']))

    def test_incomplete_archive_discovery_keeps_selection_gap(self):
        config,responses,_,fetch=self.fixture(archived=True)
        responses['https://data.sec.gov/submissions/quarter-history.json']=OSError('fixture unavailable')
        report=prepare_sources(config,self.root/'archive-blocked',fetch=fetch)
        self.assertFalse(report['filing_catalog']['selection_discovery_complete'])
        self.assertIn('filing_catalog_incomplete_for_selection',{g['reason'] for g in report['gaps']})
        self.assertEqual(report['documents'],[])

    def test_quarterly_manifest_replay_preserves_form_period_and_rejects_changed_scope(self):
        config,_,_,fetch=self.fixture()
        store=self.root/'replay-store';report=prepare_sources(config,store,fetch=fetch)
        origin=store/report['manifest_path'];sid=report['documents'][0]['source_id']
        coordinator=CompanyDataCoordinator(store)
        with patch('uteki.agents.data_query.coordinator.prepare_sources',side_effect=AssertionError('no acquisition')):
            replay=coordinator.prepare_acquisition(origin,acquisition_sha256=hashlib.sha256(origin.read_bytes()).hexdigest(),
                source_ids=[sid],output=self.root/'replay')
        self.assertEqual(replay['model_calls'],0)
        self.assertEqual(inspect_run(self.root/'replay')['status'],'verified')
        for key,value in [('form_type','10-K'),('report_period_end','2025-02-28')]:
            altered=deepcopy(report);altered['scope']['filing_selection'][key]=value
            path=self.root/(key+'.json');path.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                coordinator.prepare_acquisition(path,acquisition_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    source_ids=[sid],output=self.root/('reject-'+key))
        for key,value in [('form_type','10-K'),('report_period_end','2025-02-28'),('annual_form','10-K')]:
            altered=deepcopy(report);altered['scope'][key]=value
            path=self.root/('top-'+key+'.json');path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'scope declarations'):
                coordinator.prepare_acquisition(path,acquisition_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    source_ids=[sid],output=self.root/('reject-top-'+key))


if __name__=='__main__':unittest.main()
