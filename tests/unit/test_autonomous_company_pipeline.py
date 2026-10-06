"""Synthetic acquisition-to-query integration; no network or model evaluation."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.document_sources.company_acquisition import TICKERS, prepare_sources
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_company_materialization import filing


class AutonomousCompanyPipelineTests(unittest.TestCase):
    def test_source_fiscal_query_and_business_evidence_across_modules(self):
        # Independent issuer/date inputs exercise both non-calendar and calendar years.
        cases = (
            ('ACME', '123', '2024-07-01', '2025-06-30', '2025-08-01', '2025-09-01'),
            ('OTHER', '987', '2025-01-01', '2025-12-31', '2026-02-01', '2026-03-01'),
        )
        for symbol, cik, start, end, filed, cutoff in cases:
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                workspace = root / 'workspace'
                accession = f'{int(cik):010d}-25-000001'
                source_url = ('https://www.sec.gov/Archives/edgar/data/' + cik + '/'
                              + accession.replace('-', '') + '/annual.htm')
                original = filing(cik=cik, start=start, end=end)
                responses = {
                    TICKERS: {'0': {'ticker': symbol, 'cik_str': int(cik), 'title': symbol}},
                    f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json': {
                        'cik': cik, 'name': symbol, 'tickers': [symbol], 'exchanges': ['Nasdaq'],
                        'filings': {'recent': {'form': ['10-K'], 'filingDate': [filed],
                            'reportDate': [end], 'accessionNumber': [accession],
                            'primaryDocument': ['annual.htm']}, 'files': []}},
                    source_url: original,
                }
                called = []

                def fetch(url, *, headers, timeout):
                    called.append(url)
                    value = responses[url]
                    return value if isinstance(value, bytes) else json.dumps(value).encode()

                source_run = prepare_sources({
                    'symbol': symbol, 'market': 'NASDAQ', 'as_of': cutoff,
                    'sec_user_agent': 'Offline fixture fixture@example.test',
                    'filing_selection': {'mode': 'latest_10k_and_subsequent_filings'},
                    'source_policy': {'official': [], 'third_party': [],
                                      'updates_window': {'trailing_calendar_days': 90}},
                    'limits': {'retries': 0, 'backoff_seconds': 0},
                }, workspace, fetch=fetch)
                self.assertEqual(len(source_run['documents']), 1)
                self.assertEqual(len(called), 3)
                document = source_run['documents'][0]
                self.assertEqual((workspace / document['path']).read_bytes(), original)
                frozen_source = (workspace / source_run['manifest_path']).read_bytes()
                dataset = root / 'dataset'
                materialized = materialize_sources(source_run, workspace, dataset)
                self.assertEqual(materialized['record_count'], 2)

                with QueryDataPort(dataset) as owner:
                    scope = {
                        'snapshot_id': owner.snapshot_id,
                        'company_ids': [source_run['company']['company_id']],
                        'source_snapshot_ids': [document['source_id']],
                        'source_policy_id': 'local-frozen-v1',
                        'knowledge_cutoff': cutoff, 'include_candidates': True,
                    }

                    def plan(packet):
                        schema = packet['catalog']['schema']
                        fiscal, = schema['fiscal_periods']
                        query = {'records': [{
                            'entity_id': fiscal['company_id'], 'metric_id': 'revenue',
                            'period': fiscal['period']}], 'calculations': [{
                            'formula_id': 'operating_margin', 'entity_id': fiscal['company_id'],
                            'periods': [fiscal['period']]}]}
                        return {'action': 'plan', 'reason': 'Two explicit evidence needs',
                            'requirements': [
                                {'requirement_id': 'business', 'description': 'Quoted Business description'},
                                {'requirement_id': 'financial', 'description': 'FY2025 revenue and margin',
                                 'kind': 'query', 'query': query}]}

                    def outline(packet):
                        source, = packet['catalog']['discovery']['sources']
                        return {'action': 'outline_source', 'requirement_ids': ['business'],
                                'outline': {'source_snapshot_id': source['source_snapshot_id']}}

                    def read_business(packet):
                        result = packet['observation']['result']
                        node, = [n for n in result['nodes'] if n['kind'] == 'item' and n['item_number'] == '1']
                        return {'action': 'read_source', 'requirement_ids': ['business', 'financial'],
                            'read': {'source_snapshot_id': result['source_snapshot_id'],
                                     'node_id': node['node_id'], 'count': 12}}

                    def query(packet):
                        requirement, = [r for r in packet['requirements'] if r['kind'] == 'query']
                        return {'action': 'query', 'requirement_ids': ['financial'], 'plan': requirement['query']}

                    planner = ScriptedPlanner([plan, outline, read_business, {'action': 'finish'},
                                               query, {'action': 'finish'}])
                    agent = AutonomousDataAgent(owner, planner, limits={'max_steps': 6})
                    output = root / 'run'
                    result = asyncio.run(agent.run({
                        'question': 'Provide FY2025 revenue and operating margin plus a quoted Business description.',
                        'scope': scope,
                    }, output=output))

                self.assertEqual(result['trace'][3]['status'], 'rejected')
                feedback = [{k: v for k, v in json.loads((output / step['feedback']).read_text()).items()
                             if k in ('status', 'error_type', 'reason')} for step in result['trace']]
                self.assertEqual(result['status'], 'evidence_ready', feedback)
                self.assertEqual(result['plan_origin'], 'scripted_fixture')
                self.assertEqual(result['semantic_completeness'], 'not_evaluated')
                coverage = {r['requirement_id']: r for r in result['coverage']}
                self.assertEqual(coverage['financial']['program_check'], 'satisfied')
                self.assertFalse(result['gaps'])
                receipt = json.loads((output / 'turn-005/query-receipt.json').read_text())
                fact, = receipt['result']['computed_facts']
                self.assertEqual(fact['display_decimal'], '25.00')
                self.assertEqual(fact['periods'][0]['start'], start)
                self.assertEqual(fact['periods'][0]['end'], end)
                self.assertEqual({r['value_decimal'] for r in receipt['result']['records']},
                                 {'120000000', '30000000'})
                quotes = [a for a in receipt['package']['artifacts'] if a['kind'] == 'source_quote']
                self.assertEqual(len(quotes), 2)
                for quote in quotes:
                    self.assertEqual(quote['provenance']['verification'], 'source_verified')
                    self.assertTrue(all(loc['source_url'] == source_url for loc in quote['locators']))
                manifest = json.loads((output / 'manifest.json').read_text())
                for name, sha in manifest['files'].items():
                    self.assertEqual(digest((output / name).read_bytes()), sha)
                self.assertEqual((workspace / source_run['manifest_path']).read_bytes(), frozen_source)
                self.assertEqual((workspace / document['path']).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
