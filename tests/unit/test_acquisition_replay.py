"""Frozen acquisition replay uses real parsing; the query planner below is a fixture."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_cli import main
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


def filing(cik, year, value, form):
    return f'''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:dei="http://xbrl.sec.gov/dei/2024" xmlns:us-gaap="http://fasb.org/us-gaap/2024"><body>
    <div style="display:none"><xbrli:context id="c"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier>
    </xbrli:entity><xbrli:period><xbrli:startDate>{year}-01-01</xbrli:startDate>
    <xbrli:endDate>{year}-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></div>
    <p><ix:nonNumeric name="dei:EntityCentralIndexKey">{cik}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentType">{form}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentPeriodEndDate">{year}-12-31</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentFiscalYearFocus">{year}</ix:nonNumeric></p>
    <h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>Issuer {cik}, annual report {year}.</p>
    <table><tr><td>Revenue</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c"
    unitRef="usd" scale="6" id="revenue">{value}</ix:nonFraction></td></tr></table>
    <h2>ITEM 1A. RISK FACTORS</h2><p>Independent demand risk.</p></body></html>'''.encode()


class AcquisitionReplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root/'workspace'
        self.coordinator = CompanyDataCoordinator(self.workspace)
        self.origin, self.acquired = self.acquisition('0000000123', 'ACME', '10-K', [(2023, 111), (2024, 120)])
        self.pin = digest(self.origin.read_bytes())

    def acquisition(self, cik, symbol, form, years):
        docs = []
        for year, value in years:
            raw = filing(cik, year, value, form)
            relative = 'sources/objects/'+digest(raw)+'.html'
            path = self.workspace/relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            docs.append({'source_id': symbol.lower()+'-'+str(year), 'company_id': 'sec-'+cik,
                'source_url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{year}/annual.htm',
                'form': form, 'period_end': f'{year}-12-31', 'filed_at': f'{year+1}-02-01',
                'path': relative, 'content_sha256': digest(raw), 'mime_type': 'text/html',
                'status': 'frozen', 'as_of_eligible': True, 'role': 'filing',
                'validation': validate_sec_filing(raw, cik, form, f'{year}-12-31')})
        source = {'schema_version': 'company-source-run-v1', 'run_id': 'acquired-'+symbol,
            'status': 'completed', 'company': {'company_id': 'sec-'+cik, 'cik': cik, 'symbol': symbol, 'market': 'NASDAQ'},
            'scope': {'as_of': '2025-06-30', 'symbol': symbol, 'market': 'NASDAQ', 'requested_cik': cik,
                'source_policy': {'official': [], 'third_party': []}, 'document_validation': 'sec_inline_identity_v1',
                'filing_selection': {'mode': 'annual_filings_range', 'annual_form': form,
                    'report_period_end_from': '2023-01-01', 'report_period_end_to': '2024-12-31'}},
            'documents': docs, 'gaps': [], 'requests': 2, 'model_calls': 0}
        origin = self.workspace/'source-runs'/symbol/'manifest.json'
        origin.parent.mkdir(parents=True, exist_ok=True)
        origin.write_text(json.dumps(source))
        return origin, source

    def no_external_work(self):
        stack = ExitStack()
        for name in ('uteki.agents.data_query.coordinator.prepare_sources',
                     'uteki.infrastructure.document_sources.sec_settings.resolve_sec_contact',
                     'urllib.request.urlopen', 'uteki.agents.data_query.coordinator.CompanyDataCoordinator._planner'):
            stack.enter_context(patch(name, side_effect=AssertionError('replay must not acquire, resolve contact or call a model')))
        return stack

    def replay(self, *, output=None, origin=None, pin=None, ids=None):
        return self.coordinator.prepare_acquisition(origin or self.origin, acquisition_sha256=pin or self.pin,
            source_ids=['acme-2024'] if ids is None else ids, output=output or self.root/'replayed')

    def mutate(self, change):
        source = deepcopy(self.acquired); change(source)
        path = self.root/'changed-origin/manifest.json'; path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(source))
        return path, digest(path.read_bytes())

    def test_cli_replays_two_issuers_and_explicit_periods_without_contact_or_network(self):
        other, _ = self.acquisition('0000000987', 'OTHER', '20-F', [(2023, 234)])
        for origin, sid, company, period, value in (
                (self.origin, 'acme-2024', 'sec-0000000123', '2024-12-31', '120000000'),
                (other, 'other-2023', 'sec-0000000987', '2023-12-31', '234000000')):
            with self.subTest(sid=sid):
                before = origin.read_bytes(); output = self.root/sid
                stdout = io.StringIO()
                with self.no_external_work(), redirect_stdout(stdout):
                    code = main(['agent', 'prepare', '--workspace', str(self.workspace), '--output', str(output),
                        '--from-acquisition', str(origin), '--acquisition-sha256', digest(before), '--source-id', sid,
                        '--settings-root', str(self.root/'does-not-exist')])
                self.assertEqual(code, 0, stdout.getvalue())
                result = json.loads(stdout.getvalue())
                self.assertEqual(result['acquisition']['requests'], 0)
                self.assertEqual(result['model_calls'], 0)
                self.assertEqual(inspect_run(output)['status'], 'verified')
                self.assertEqual(origin.read_bytes(), before)
                self.assertFalse((output/'source-config.json').exists())
                sources = json.loads((output/'dataset/sources.json').read_text())
                self.assertEqual([(s['source_snapshot_id'], s['company_id'], s['period_end']) for s in sources], [(sid, company, period)])
                self.assertTrue(sources[0]['parsed_package']['manifest_sha256'])
                rows = json.loads((output/'dataset/records.json').read_text())['rows']
                self.assertEqual([(r['entity_id'], r['period']['end'], r['value_decimal']) for r in rows], [(company, period, value)])
                selected = json.loads((output/'source-run.json').read_text())
                self.assertNotEqual(selected['run_id'], selected['parent_run_ids'][0])
                self.assertEqual(selected['replay']['origin_manifest_sha256'], digest(before))
                self.assertEqual(selected['replay']['source_ids'], [sid])

    def test_selection_is_exact_and_gaps_keep_global_and_selected_only(self):
        origin, pin = self.mutate(lambda source: source['gaps'].extend([
            {'reason': 'global_scope_warning'}, {'reason': 'selected_warning', 'source_id': 'acme-2024'},
            {'reason': 'excluded_warning', 'source_url': source['documents'][0]['source_url']},
            {'reason': 'excluded_warning_id', 'source_snapshot_id': 'acme-2023'}]))
        with self.no_external_work():
            result = self.replay(origin=origin, pin=pin)
        selected = json.loads((self.root/'replayed/source-run.json').read_text())
        self.assertEqual({g['reason'] for g in selected['gaps']}, {'global_scope_warning', 'selected_warning'})
        self.assertEqual(result['status'], 'prepared_with_gaps')
        self.assertEqual({d['source_id'] for d in selected['documents']}, {'acme-2024'})

    def test_cli_repeated_source_ids_selects_both_explicit_periods(self):
        output = self.root/'both-periods'
        with self.no_external_work(), redirect_stdout(io.StringIO()):
            code = main(['agent', 'prepare', '--workspace', str(self.workspace), '--output', str(output),
                '--from-acquisition', str(self.origin), '--acquisition-sha256', self.pin,
                '--source-id', 'acme-2024', '--source-id', 'acme-2023'])
        self.assertEqual(code, 0)
        sources = json.loads((output/'dataset/sources.json').read_text())
        self.assertEqual([s['source_snapshot_id'] for s in sources], ['acme-2024', 'acme-2023'])
        self.assertEqual({s['period_end'] for s in sources}, {'2024-12-31', '2023-12-31'})

    def test_missing_blank_duplicate_unknown_selection_and_invalid_hash_do_not_create_output(self):
        for index, (ids, pin) in enumerate((([], self.pin), ([''], self.pin), ([' acme-2024'], self.pin),
                (['acme-2024', 'acme-2024'], self.pin), (['unknown'], self.pin),
                (['acme-2024'], ''), (['acme-2024'], '0'*64))):
            output = self.root/f'invalid-{index}'
            with self.subTest(ids=ids, pin=pin), self.no_external_work(), self.assertRaises(ValueError):
                self.coordinator.prepare_acquisition(self.origin, acquisition_sha256=pin, source_ids=ids, output=output)
            self.assertFalse(output.exists())

    def test_cli_rejects_replay_options_on_other_selectors_before_loading_configuration(self):
        examples = [
            ['--from-acquisition', str(self.origin)],
            ['--from-acquisition', str(self.origin), '--acquisition-sha256', self.pin],
            ['--from-acquisition', str(self.origin), '--source-id', 'acme-2024'],
            ['--config', str(self.root/'missing.json'), '--source-id', 'acme-2024'],
            ['--from-run', str(self.root/'missing-run'), '--acquisition-sha256', self.pin],
            ['--from-acquisition', str(self.origin), '--acquisition-sha256', self.pin, '--source-id', 'acme-2024',
             '--company-catalog', str(self.root/'missing-catalog')],
            ['--from-acquisition', str(self.origin), '--acquisition-sha256', self.pin, '--source-id', 'acme-2024',
             '--sec-user-agent', 'unneeded-contact'],
        ]
        for index, flags in enumerate(examples):
            output = self.root/f'cli-invalid-{index}'
            with self.subTest(flags=flags), self.no_external_work(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['agent', 'prepare', '--workspace', str(self.workspace), '--output', str(output), *flags]), 2)
            self.assertFalse(output.exists())

    def test_cross_company_wrong_period_and_conflicting_scope_are_rejected(self):
        changes = [lambda s: s['company'].update(cik='0000000987', company_id='sec-0000000987'),
            lambda s: s['documents'][1].update(company_id='sec-0000000987'),
            lambda s: s['documents'][1].update(period_end='2023-12-31'),
            lambda s: s['documents'][1].update(form='20-F'),
            lambda s: s['documents'][1].update(form=['10-K']),
            lambda s: s['company'].update(cik=1234567890, company_id='sec-1234567890'),
            lambda s: s['scope'].update(requested_cik='0000000987'),
            lambda s: s['documents'].append(deepcopy(s['documents'][1]))]
        for index, change in enumerate(changes):
            origin, pin = self.mutate(change); output = self.root/f'conflict-{index}'
            with self.subTest(index=index), self.no_external_work(), self.assertRaises(ValueError):
                self.replay(origin=origin, pin=pin, output=output)
            self.assertFalse(output.exists())

    def test_other_issuer_bytes_cannot_be_relabelled_by_a_new_manifest_pin(self):
        _, other = self.acquisition('0000000987', 'OTHER', '20-F', [(2023, 234)])
        def relabel(source):
            for key in ('path', 'content_sha256', 'validation'):
                source['documents'][1][key] = other['documents'][0][key]
        origin, pin = self.mutate(relabel)
        with self.no_external_work(), self.assertRaisesRegex(ValueError, 'filing_identity_mismatch'):
            self.replay(origin=origin, pin=pin)
        self.assertFalse((self.root/'replayed').exists())

    def test_strict_filing_policy_does_not_require_dei_receipts_for_attachments(self):
        raw = b'<html><body><p>Explicitly acquired report attachment.</p></body></html>'
        relative = 'sources/objects/'+digest(raw)+'.html'
        (self.workspace/relative).write_bytes(raw)
        def attachment(source):
            doc = source['documents'][1]
            doc.update(role='filing_attachment', form='EXHIBIT', path=relative, content_sha256=digest(raw))
            doc.pop('validation')
        origin, pin = self.mutate(attachment)
        with self.no_external_work():
            result = self.replay(origin=origin, pin=pin)
        self.assertEqual(result['dataset']['source_count'], 1)
        selected = json.loads((self.root/'replayed/source-run.json').read_text())
        self.assertNotIn('validation', selected['documents'][0])

    def test_filing_identity_checks_cannot_be_bypassed_with_missing_or_spoofed_role(self):
        for index, role in enumerate((None, '', 'unknown', 'blog', 'filing_attachment', ['filing'])):
            def change(source):
                doc = source['documents'][1]
                doc.pop('validation')
                if role is None: doc.pop('role')
                else: doc['role'] = role
            origin, pin = self.mutate(change); output = self.root/f'role-{index}'
            with self.subTest(role=role), self.no_external_work(), self.assertRaisesRegex(ValueError, 'role and form'):
                self.replay(origin=origin, pin=pin, output=output)
            self.assertFalse(output.exists())

    def test_tampered_bytes_and_wrong_workspace_are_rejected_before_output(self):
        raw = self.workspace/self.acquired['documents'][1]['path']; before = raw.read_bytes()
        raw.write_bytes(before+b'changed')
        with self.no_external_work(), self.assertRaisesRegex(ValueError, 'source bytes SHA256'):
            self.replay()
        self.assertFalse((self.root/'replayed').exists())
        raw.write_bytes(before)
        with self.no_external_work(), self.assertRaises(FileNotFoundError):
            CompanyDataCoordinator(self.root/'missing-workspace').prepare_acquisition(self.origin,
                acquisition_sha256=self.pin, source_ids=['acme-2024'], output=self.root/'wrong-workspace')
        self.assertFalse((self.root/'wrong-workspace').exists())

    def test_frozen_directories_and_existing_output_are_preserved(self):
        with self.no_external_work():
            result = self.replay()
        before = (self.root/'replayed/manifest.json').read_bytes()
        targets = [self.origin.parent/'nested', self.workspace/'sources/new-output', self.root/'replayed',
                   self.root/'replayed/nested', Path(result['dataset']['path'])/'nested']
        for output in targets:
            with self.subTest(output=output), self.no_external_work(), self.assertRaises((ValueError, FileExistsError)):
                self.replay(output=output)
            if output != self.root/'replayed': self.assertFalse(output.exists())
        self.assertEqual((self.root/'replayed/manifest.json').read_bytes(), before)

    def test_replayed_preparation_supports_readonly_query_and_reprocessing(self):
        with self.no_external_work():
            self.replay()
            again = self.coordinator.reprocess(self.root/'replayed', output=self.root/'reprocessed')
        self.assertEqual(inspect_run(self.root/'reprocessed')['status'], 'verified')
        self.assertEqual(again['dataset']['source_count'], 1)
        self.assertFalse((self.root/'reprocessed/source-config.json').exists())
        def plan(packet):
            fiscal, = packet['catalog']['schema']['fiscal_periods']
            return {'action': 'plan', 'reason': 'Verify selected frozen numerical scope', 'requirements': [{
                'requirement_id': 'revenue', 'kind': 'query', 'description': 'Revenue in the selected report',
                'query': {'records': [{'entity_id': fiscal['company_id'], 'metric_id': 'revenue', 'period': fiscal['period']}]}}]}
        planner = ScriptedPlanner([plan, lambda p: {'action': 'query', 'requirement_ids': ['revenue'],
            'plan': p['requirements'][0]['query']}, {'action': 'finish'}])
        with self.no_external_work():
            result = asyncio.run(self.coordinator.query({'question': 'Provide FY2024 revenue.',
                'prepared_run': str(self.root/'reprocessed'), 'include_candidates': True, 'limits': {'max_steps': 3}},
                planner=planner, output=self.root/'query'))
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['active_scope']['source_snapshot_ids'], ['acme-2024'])
        self.assertTrue(result['active_scope']['include_candidates'])
        self.assertEqual(result['active_scope']['knowledge_cutoff'], '2025-06-30')
        self.assertTrue(all(p['available_callbacks'] == [] for p in planner.packets))
        with self.assertRaisesRegex(ValueError, 'explicit acquisition configuration'):
            self.coordinator.refresh({}, previous=self.root/'replayed', output=self.root/'forbidden-refresh')
        self.assertFalse((self.root/'forbidden-refresh').exists())


if __name__ == '__main__':
    unittest.main()
