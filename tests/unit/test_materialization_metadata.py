"""Fiscal descriptions must be tied to visible headers and issuer contexts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.domain.research_data.period_scope import explicit_periods
from uteki.infrastructure.research_data.company_materialization import implementation_fingerprint, materialize_sources, metric_catalog
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


def comparative_filing(*, prior_label='2024', current_label='2025', cik='456', dei='2025', caption='Year Ended June 30,'):
    contexts = ''.join(f'<xbrli:context id="c{year}"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier>'
        f'</xbrli:entity><xbrli:period><xbrli:startDate>{year-1}-07-01</xbrli:startDate>'
        f'<xbrli:endDate>{year}-06-30</xbrli:endDate></xbrli:period></xbrli:context>' for year in (2024, 2025))
    facts = ''.join(f'<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c{year}" '
        f'unitRef="u" scale="6">{year-2000}</ix:nonFraction></td>' for year in (2025, 2024))
    return f'''<html xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:dei="http://xbrl.sec.gov/dei/2025"
        xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body><div style="display:none">{contexts}
        <xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></div>
        <p><ix:nonNumeric name="dei:DocumentFiscalYearFocus">{dei}</ix:nonNumeric></p>
        <table><tr><td>{caption}</td><td>{current_label}</td><td>{prior_label}</td></tr>
        <tr><td>Revenue</td>{facts}</tr></table></body></html>'''.encode()


class MaterializationMetadataTests(unittest.TestCase):
    def test_fingerprint_tracks_reading_groups_and_metadata_implementation(self):
        original = Path.read_bytes
        baseline = implementation_fingerprint()
        for module in ('reading_groups.py', 'materialization_metadata.py'):
            with self.subTest(module=module):
                def changed(path):
                    value = original(path)
                    return value + b'\n# changed implementation' if path.name == module else value
                with patch.object(Path, 'read_bytes', changed):
                    self.assertNotEqual(implementation_fingerprint(), baseline)

    def build(self, raw, folder, *, company='sec-0000000456'):
        (folder/'original.html').write_bytes(raw)
        run = {'company': {'company_id':company, 'cik':company[4:]}, 'as_of':'2025-09-01', 'documents':[
            {'source_id':'independent-annual', 'path':'original.html', 'content_sha256':digest(raw),
             'source_url':'https://example.invalid/report', 'mime_type':'text/html', 'form':'10-K',
             'period_end':'2025-06-30', 'filed_at':'2025-08-01', 'status':'frozen'}]}
        destination = folder/'dataset'
        manifest = materialize_sources(run, folder, destination)
        return destination, manifest, json.loads((destination/'sources.json').read_text())[0]

    def test_explicit_comparative_header_unlocks_prior_fiscal_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, manifest, source = self.build(comparative_filing(), Path(tmp))
            prior, = explicit_periods('FY2024 revenue', fiscal_periods=source['fiscal_periods'], require_fiscal_mapping=True)
            self.assertEqual((str(prior.start), str(prior.end)), ('2023-07-01', '2024-06-30'))
            mapping = next(p for p in source['fiscal_periods'] if p['fiscal_year']==2024)
            refs = json.loads((folder/'evidence.json').read_text())
            proof = mapping['basis_evidence']
            self.assertEqual(proof['header']['text'], '2024')
            self.assertEqual(refs[proof['evidence_id']]['source_snapshot_id'], source['source_snapshot_id'])
            self.assertEqual(refs[proof['evidence_id']]['block_id'], proof['block_id'])
            with QueryDataPort(folder) as owner:
                port = owner.scoped({'snapshot_id':manifest['snapshot_id'], 'company_ids':['sec-0000000456'],
                    'source_snapshot_ids':[source['source_snapshot_id']], 'source_policy_id':'local-frozen-v1',
                    'knowledge_cutoff':'2025-09-01', 'include_candidates':True})
                fiscal = port.get_schema()['fiscal_periods']
                self.assertTrue(all(p['company_id']=='sec-0000000456' and p['source_snapshot_id']==source['source_snapshot_id'] for p in fiscal))
                result = port.query_data({'query_id':'prior', 'snapshot_id':manifest['snapshot_id'],
                    'source_policy_id':'local-frozen-v1','knowledge_cutoff':'2025-09-01','include_candidates':True,
                    'records':[{'entity_id':'sec-0000000456', 'metric_id':'revenue', 'period':prior.model_dump(mode='json')}]})
                self.assertEqual([r['value_decimal'] for r in result['records']], ['24000000'])
            self.assertEqual(explicit_periods('FY2023 revenue', fiscal_periods=source['fiscal_periods'], require_fiscal_mapping=True), ())

    def test_unverified_calendar_labels_and_issuer_never_supply_comparative_years(self):
        cases = [dict(prior_label='prior year'), dict(current_label='current year'), dict(prior_label='2023'),
                 dict(caption='Three Months Ended June 30,'), dict(dei=''), dict(cik='999')]
        for changes in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                _, _, source = self.build(comparative_filing(**changes), Path(tmp))
                self.assertFalse(any(p['fiscal_year']==2024 for p in source.get('fiscal_periods', [])))

    def test_conflicting_explicit_fiscal_mappings_remain_unqueryable(self):
        mappings = [{'fiscal_year':2024, 'period':{'kind':'year','start':'2023-07-01','end':'2024-06-30','basis':'source'}},
                    {'fiscal_year':2024, 'period':{'kind':'year','start':'2024-01-01','end':'2024-12-31'}}]
        self.assertEqual(explicit_periods('FY2024 revenue', fiscal_periods=mappings, require_fiscal_mapping=True), ())

    def test_metric_descriptions_are_small_and_distinguish_accounting_meanings(self):
        catalog = metric_catalog()
        for metric, description in catalog.items():
            self.assertNotEqual(description['definition'], metric)
            self.assertLess(len(json.dumps(description).encode()), 1400)
            self.assertEqual(description['aggregation'], 'no_implicit_sum')
            self.assertIn(' / ', description['label'])
        self.assertIn('营业收入', catalog['revenue']['aliases'])
        self.assertIn('Revenues', catalog['revenue']['aliases'])
        self.assertIn('Not operating profit', catalog['operating_cash_flow']['definition'])
        self.assertIn('never sum', catalog['revenue_including_assessed_tax']['definition'])

    def test_frozen_msft_and_google_rebuild_comparatives_without_changing_old_datasets(self):
        repository = Path(__file__).resolve().parents[2]
        for name, start, end, count in [('msft','2023-07-01','2024-06-30',102), ('googl','2024-01-01','2024-12-31',253)]:
            workspace = repository/'data/company_workspace/extraction_ab_v1/corpus'/name
            if not (workspace/'acquisition.json').exists():
                self.skipTest('optional frozen local acquisition unavailable')
            historical = workspace/'dataset/sources.json'
            before = historical.read_bytes() if historical.exists() else None
            with self.subTest(company=name), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp)/'dataset'
                run = json.loads((workspace/'acquisition.json').read_text())
                manifest = materialize_sources(run, workspace, destination)
                self.assertEqual(manifest['record_count'], count)
                source = next(s for s in json.loads((destination/'sources.json').read_text()) if s['form']=='10-K')
                periods = explicit_periods('FY2024 revenue', fiscal_periods=source['fiscal_periods'], require_fiscal_mapping=True)
                self.assertEqual([(str(p.start),str(p.end)) for p in periods], [(start,end)])
                self.assertEqual({p['fiscal_year'] for p in source['fiscal_periods']}, {2023,2024,2025})
                self.assertLess(len(json.dumps(source).encode()), 4096)
                self.assertEqual(historical.read_bytes() if historical.exists() else None, before)


if __name__ == '__main__':
    unittest.main()
