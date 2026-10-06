"""Offline behavior through the public coordinator, not a model evaluation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.document_sources.company_acquisition import TICKERS
from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.query_cli import main
from tests.unit.test_company_materialization import filing
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


class CompanyCoordinatorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root/'workspace'
        self.config = {'symbol': 'ACME', 'market': 'NASDAQ', 'as_of': '2026-03-01',
            'sec_user_agent': 'Offline fixture fixture@example.test',
            'filing_selection': {'mode': 'latest_10k_and_subsequent_filings'},
            'source_policy': {'official': [], 'third_party': [], 'updates_window': {'trailing_calendar_days': 90}},
            'limits': {'retries': 0, 'backoff_seconds': 0}}
        self.requests, self.ports = [], []
        rows = [('10-K', '2026-02-01', '2025-12-31', '0000000123-26-000001', 'new.htm'),
                ('10-K', '2025-02-01', '2024-12-31', '0000000123-25-000001', 'old.htm')]
        self.urls = ['https://www.sec.gov/Archives/edgar/data/123/'+r[3].replace('-', '')+'/'+r[4] for r in rows]
        self.responses = {TICKERS: {'0': {'ticker': 'ACME', 'cik_str': 123, 'title': 'Acme'}},
            'https://data.sec.gov/submissions/CIK0000000123.json': {'cik': '123', 'name': 'Acme', 'tickers': ['ACME'],
                'exchanges': ['Nasdaq'], 'filings': {'recent': {key: [row[i] for row in rows]
                for i, key in enumerate(('form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument'))}, 'files': []}},
            self.urls[0]: filing(cik='123', start='2025-01-01', end='2025-12-31'),
            self.urls[1]: filing(cik='123', start='2024-01-01', end='2024-12-31').replace(
                b'DocumentFiscalYearFocus">2025', b'DocumentFiscalYearFocus">2024')}
        self.coordinator = CompanyDataCoordinator(self.workspace, fetch=self.fetch, port_factory=self.port)

    def fetch(self, url, **kwargs):
        self.requests.append(url)
        value = self.responses[url]
        if isinstance(value, Exception): raise value
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def port(self, path):
        port = QueryDataPort(path); self.ports.append(port)
        return port

    def assert_closed(self):
        for port in self.ports:
            with self.assertRaises(Exception): port._db.execute('SELECT 1')

    def numeric_actions(self):
        def plan(packet):
            fiscal, = packet['catalog']['schema']['fiscal_periods']
            return {'action': 'plan', 'reason': 'Declared number and arithmetic', 'requirements': [{
                'kind': 'query', 'requirement_id': 'numbers', 'description': 'Revenue and operating margin',
                'query': {'records': [{'entity_id': fiscal['company_id'], 'metric_id': 'revenue', 'period': fiscal['period']}],
                          'calculations': [{'formula_id': 'operating_margin', 'entity_id': fiscal['company_id'], 'periods': [fiscal['period']]}]}}]}
        def query(packet):
            return {'action': 'query', 'requirement_ids': ['numbers'], 'plan': packet['requirements'][0]['query']}
        return [plan, query, {'action': 'finish'}]

    def test_query_prepares_company_returns_cited_numbers_and_closes_ports(self):
        planner = ScriptedPlanner(self.numeric_actions())
        request = {'question': 'Provide FY2025 revenue and operating margin.', 'company_config': self.config,
                   'include_candidates': True, 'limits': {'max_steps': 3}}
        result = asyncio.run(self.coordinator.query(request, planner=planner, output=self.root/'query-run'))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['active_scope']['company_ids'], ['sec-0000000123'])
        self.assertEqual(len(self.requests), 3)
        self.assert_closed()
        checked = inspect_run(self.root/'query-run')
        self.assertEqual(checked['status'], 'verified')
        query_dir = self.root/'query-run/query'
        index = json.loads((query_dir/'artifact-index.json').read_text())
        record = next(r for r in index if r['kind'] == 'record')
        page = inspect_run(self.root/'query-run', artifact_read={'artifact_id': record['artifact_id']})['artifact_page']
        self.assertTrue(page['returned_count'])
        self.assertNotIn(self.urls[1], self.requests)

    def test_missing_and_conflicting_inputs_fail_before_network(self):
        for request in ({'question': 'Revenue'}, {'question': 'Revenue', 'company_config': self.config},
                        {'question': 'Revenue', 'dataset': 'x'}, {'question': 'Revenue', 'prepared_run': 'a', 'dataset': 'b'}):
            with self.subTest(request=request), self.assertRaises(ValueError): CompanyQueryInput.model_validate(request)
        self.assertFalse(self.requests)

    def test_missing_filing_policy_rejected_before_prepare_output(self):
        config = {key: value for key, value in self.config.items() if key != 'filing_selection'}
        output = self.root/'invalid-policy'
        with self.assertRaisesRegex(ValueError, 'filing_selection'):
            self.coordinator.prepare(config, output=output)
        self.assertFalse(self.requests)
        self.assertFalse(output.exists())
        self.assertFalse(self.workspace.exists())

    def test_output_inside_frozen_dataset_or_prepared_run_is_rejected_before_write(self):
        prepared = self.coordinator.prepare(self.config, output=self.root/'prepared')
        for destination in (self.root/'prepared/nested', Path(prepared['dataset']['path'])/'nested'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                asyncio.run(self.coordinator.query({'question': 'FY2025 revenue', 'prepared_run': str(self.root/'prepared'),
                    'include_candidates': True}, planner=ScriptedPlanner([]), output=destination))
            self.assertFalse(destination.exists())
        self.assertEqual(inspect_run(self.root/'prepared')['status'], 'verified')

    def test_identity_403_is_preserved_without_empty_dataset_success(self):
        self.responses[TICKERS] = HTTPError(TICKERS, 403, 'Forbidden', {}, None)
        result = self.coordinator.prepare(self.config, output=self.root/'denied')
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['dataset'])
        acquisition = json.loads((self.root/'denied/acquisition.json').read_text())
        self.assertEqual(acquisition['requests'], 1)
        self.assertEqual(acquisition['discovery'][0]['http_status'], 403)
        self.assertFalse((self.root/'denied/dataset').exists())
        self.assertEqual(inspect_run(self.root/'denied')['status'], 'verified')

    def test_no_literal_match_is_an_explicit_partial_gap_not_undisclosed(self):
        plan = {'action': 'plan', 'reason': 'Find literal source evidence', 'requirements': [
            {'requirement_id': 'missing', 'description': 'Find a requested phrase'}]}
        query = {'action': 'query', 'requirement_ids': ['missing'], 'plan': {'documents': [{
            'company_id': 'sec-0000000123', 'form': '10-K', 'period_end': '2025-12-31',
            'phrase': 'phrase absent from the synthetic annual report'}]}}
        def gap(packet):
            document = packet['observation']['result']['documents'][0]
            self.assertEqual(document['status'], 'no_literal_match')
            self.assertFalse(document['not_disclosed'])
            self.assertEqual(document['contexts'], [])
            return {'action': 'gap', 'requirement_ids': ['missing'], 'reason': 'no_literal_match'}
        result = asyncio.run(self.coordinator.query({'question': 'Find the requested literal phrase in the FY2025 annual report.',
            'company_config': self.config, 'include_candidates': True, 'limits': {'max_steps': 4}},
            planner=ScriptedPlanner([plan, query, gap, {'action': 'finish'}]), output=self.root/'missing'))
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['stop_reason'], 'host_reference_checks_passed')
        self.assertTrue(any(g['reason'] == 'no_literal_match' for g in result['gaps']))
        self.assert_closed()

    def test_refresh_reuses_unchanged_dataset_and_rejects_old_run_tampering(self):
        calls = []
        def materializer(*args, **kwargs):
            calls.append(1)
            return materialize_sources(*args, **kwargs)
        coordinator = CompanyDataCoordinator(self.workspace, fetch=self.fetch, materializer=materializer)
        first = coordinator.prepare(self.config, output=self.root/'first')
        before = (self.root/'first/manifest.json').read_bytes()
        second = coordinator.refresh({**self.config, 'as_of': '2026-03-02'}, previous=self.root/'first', output=self.root/'second')
        self.assertEqual(second['materialization'], 'reused', second)
        self.assertEqual(second['dataset'], first['dataset'])
        self.assertEqual(second['stage_coverage'], first['stage_coverage'])
        self.assertEqual(second['gaps'], first['gaps'])
        self.assertEqual(second['status'], first['status'])
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.root/'first/manifest.json').read_bytes(), before)
        for destination in (self.root/'first/nested', Path(first['dataset']['path'])/'nested'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                coordinator.refresh(self.config, previous=self.root/'first', output=destination)
            self.assertFalse(destination.exists())
        (self.root/'first/dataset/sources.json').write_text('[]')
        request_count = len(self.requests)
        with self.assertRaises(ValueError):
            coordinator.refresh(self.config, previous=self.root/'first', output=self.root/'third')
        self.assertEqual(len(self.requests), request_count)

    def callback_actions(self):
        def outline(packet):
            sid = packet['catalog']['discovery']['sources'][0]['source_snapshot_id']
            return {'action': 'outline_source', 'requirement_ids': ['business'], 'outline': {'source_snapshot_id': sid}}
        def read(packet):
            outline = packet['observation']['result']
            node = next(n for n in outline['nodes'] if n['kind'] == 'item' and n.get('item_number') == '1')
            return {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
                'source_snapshot_id': outline['source_snapshot_id'], 'node_id': node['node_id'], 'count': 12}}
        def materialize(packet):
            return {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {
                'source_run_id': packet['observation']['result']['source_run_id']}}
        return [{'action': 'plan', 'reason': 'Need source text', 'requirements': [
                    {'requirement_id': 'business', 'description': 'Business source'}]}, outline, read,
                {'action': 'acquire', 'requirement_ids': ['business'], 'arguments': {
                    'filing_selection': {'mode': 'annual_report_period', 'report_period_end': '2024-12-31'}}},
                materialize, {'action': 'finish'}]

    def test_changed_parser_fingerprint_prevents_reuse_of_old_dataset(self):
        first = self.coordinator.prepare(self.config, output=self.root/'first')
        original = (self.root/'first/manifest.json').read_bytes()
        with patch('uteki.infrastructure.research_data.company_materialization.implementation_fingerprint',
                   return_value='a'*64):
            second = self.coordinator.refresh(self.config, previous=self.root/'first', output=self.root/'second')
        self.assertEqual(second['materialization'], 'created')
        self.assertNotEqual(second['dataset']['snapshot_id'], first['dataset']['snapshot_id'])
        self.assertEqual((self.root/'first/manifest.json').read_bytes(), original)

    def test_reprocess_uses_frozen_bytes_without_network_and_keeps_original(self):
        first = self.coordinator.prepare(self.config, output=self.root/'first')
        original = (self.root/'first/manifest.json').read_bytes()
        self.requests.clear()
        result = self.coordinator.reprocess(self.root/'first', output=self.root/'reprocessed')
        self.assertEqual(result['acquisition']['requests'], 0)
        self.assertFalse(self.requests)
        self.assertEqual(result['dataset']['source_count'], first['dataset']['source_count'])
        self.assertEqual(inspect_run(self.root/'reprocessed')['status'], 'verified')
        self.assertEqual((self.root/'first/manifest.json').read_bytes(), original)
        with self.assertRaises(ValueError):
            self.coordinator.reprocess(self.root/'first', output=Path(first['dataset']['path'])/'nested')
        self.assertFalse((Path(first['dataset']['path'])/'nested').exists())
        with self.assertRaises(ValueError):
            CompanyDataCoordinator(self.root/'wrong-store').reprocess(self.root/'first', output=self.root/'wrong')
        self.assertFalse((self.root/'wrong').exists())

    def test_old_period_acquisition_then_materialization_switches_only_verified_scope(self):
        planner = ScriptedPlanner(self.callback_actions())
        result = asyncio.run(self.coordinator.query({'question': 'Read Business for 2025 and get the 2024 original.',
            'company_config': self.config, 'include_candidates': True, 'limits': {'max_steps': 6}},
            planner=planner, output=self.root/'query'))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(len(result['active_scope']['source_snapshot_ids']), 2)
        self.assertEqual(planner.packets[4]['active_scope'], planner.packets[0]['active_scope'])
        self.assertNotEqual(planner.packets[5]['active_scope'], planner.packets[4]['active_scope'])
        self.assert_closed()
        self.assertEqual(inspect_run(self.root/'query')['status'], 'verified')

    def test_partial_materialization_keeps_previous_scope_and_saved_gap(self):
        calls = []
        def materializer(report, workspace, destination, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                report = deepcopy(report)
                report['documents'] = [d for d in report['documents'] if d['period_end'] == '2025-12-31']
            return materialize_sources(report, workspace, destination, **kwargs)
        coordinator = CompanyDataCoordinator(self.workspace, fetch=self.fetch, materializer=materializer, port_factory=self.port)
        planner = ScriptedPlanner(self.callback_actions())
        result = asyncio.run(coordinator.query({'question': 'Read Business and obtain 2024 original.',
            'company_config': self.config, 'include_candidates': True, 'limits': {'max_steps': 6}},
            planner=planner, output=self.root/'partial'))
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['active_scope'], planner.packets[0]['active_scope'])
        self.assertTrue(any(g['reason'] == 'materialization_incomplete' for g in result['gaps']))
        self.assert_closed()
        self.assertTrue((self.root/'partial/query/turn-005/materialize/dataset/manifest.json').exists())
        self.assertEqual(inspect_run(self.root/'partial')['status'], 'verified')

    def test_old_unindexed_original_does_not_block_valid_new_annual_source(self):
        def prepare_with_attachment(config, workspace, **kwargs):
            report = prepare_sources(config, workspace, **kwargs)
            if config['filing_selection']['mode'] == 'latest_10k_and_subsequent_filings':
                raw = b'<?xml version="1.0"?><metadata>unsupported original</metadata>'
                (Path(workspace)/'metadata.xml').write_bytes(raw)
                report['documents'].append({**report['documents'][0], 'source_id': 'metadata-only',
                    'path': 'metadata.xml', 'content_sha256': digest(raw), 'form': 'EXHIBIT',
                    'mime_type': 'application/xml'})
            return report
        planner = ScriptedPlanner(self.callback_actions())
        with patch('uteki.agents.data_query.coordinator.prepare_sources', side_effect=prepare_with_attachment):
            result = asyncio.run(self.coordinator.query({'question': 'Read Business and obtain 2024 original.',
                'company_config': self.config, 'include_candidates': True, 'limits': {'max_steps': 6}},
                planner=planner, output=self.root/'with-unsupported'))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(len(result['active_scope']['source_snapshot_ids']), 2)
        manifest = json.loads((Path(result['dataset']['path'])/'manifest.json').read_text())
        self.assertTrue(any(g['reason'] == 'unsupported_source_mime_type' for g in manifest['gaps']))
        self.assert_closed()

    def test_cancelled_preparation_drains_worker_and_seals_cancelled_run(self):
        started, release = threading.Event(), threading.Event()
        def fetch(url, **kwargs):
            started.set()
            if not release.wait(3): raise TimeoutError('fixture release')
            return self.fetch(url, **kwargs)
        coordinator = CompanyDataCoordinator(self.workspace, fetch=fetch)
        async def run():
            task = asyncio.create_task(coordinator.query({'question': 'FY2025 revenue', 'company_config': self.config,
                'include_candidates': True}, planner=ScriptedPlanner([]), output=self.root/'cancelled'))
            self.assertTrue(await asyncio.to_thread(started.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(run())
        checked = inspect_run(self.root/'cancelled')
        self.assertEqual(checked['result']['status'], 'cancelled')
        self.assertFalse((self.root/'cancelled/prepare/dataset').exists())
        acquisition = json.loads((self.root/'cancelled/prepare/acquisition.json').read_text())
        self.assertEqual(acquisition['status'], 'cancelled')
        self.assertEqual(acquisition['documents'], [])

    def test_cancelled_acquire_callback_keeps_its_request_receipt_in_the_run(self):
        started, release = threading.Event(), threading.Event()
        def fetch(url, **kwargs):
            if url == self.urls[1]:
                started.set()
                if not release.wait(3): raise TimeoutError('fixture release')
            return self.fetch(url, **kwargs)
        coordinator = CompanyDataCoordinator(self.workspace, fetch=fetch, port_factory=self.port)
        async def run():
            task = asyncio.create_task(coordinator.query({'question': 'Read Business and get 2024 original.',
                'company_config': self.config, 'include_candidates': True, 'limits': {'max_steps': 6}},
                planner=ScriptedPlanner(self.callback_actions()), output=self.root/'cancel-acquire'))
            self.assertTrue(await asyncio.to_thread(started.wait, 3))
            task.cancel(); await asyncio.sleep(0)
            task.cancel(); await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(run())
        checked = inspect_run(self.root/'cancel-acquire')
        self.assertEqual(checked['result']['status'], 'cancelled')
        receipt = self.root/'cancel-acquire/query/turn-004/acquire/source-run.json'
        self.assertTrue(receipt.exists())
        acquisition = json.loads(receipt.read_text())
        self.assertEqual(acquisition['status'], 'cancelled')
        self.assertEqual(acquisition['requests'], 3)
        self.assertEqual(acquisition['documents'], [])
        self.assert_closed()

    def test_cli_prepare_and_inspect_share_coordinator_and_old_commands_stay_available(self):
        config = self.root/'config.json'; config.write_text(json.dumps(self.config))
        with patch('uteki.agents.data_query.coordinator.prepare_sources', wraps=__import__(
                'uteki.infrastructure.document_sources.company_acquisition', fromlist=['prepare_sources']).prepare_sources) as prepare:
            original = prepare._mock_wraps
            prepare.side_effect = lambda cfg, workspace, **kwargs: original(cfg, workspace, fetch=self.fetch,
                                                                         should_stop=kwargs.get('should_stop'))
            with patch('builtins.print'):
                code = main(['agent', 'prepare', '--config', str(config), '--workspace', str(self.workspace), '--output', str(self.root/'cli')])
                self.assertEqual(code, 0)
                self.assertEqual(main(['agent', 'inspect', '--run', str(self.root/'cli')]), 0)
        self.assertEqual(inspect_run(self.root/'cli')['result']['operation'], 'prepare')
