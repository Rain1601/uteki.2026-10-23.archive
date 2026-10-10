"""Offline scope/integrity checks for the bounded E5 preparation adapter."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

PATH = Path(__file__).with_name('build_preparation.py')
spec = importlib.util.spec_from_file_location('e5_build_preparation', PATH)
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


def filing(cik, start, end):
    return f'''<html xmlns:us-gaap="http://fasb.org/us-gaap/2031"
    xmlns:dei="http://xbrl.sec.gov/dei/2031" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
    <div style="display:none"><xbrli:context id="c"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></div>
    <p><ix:nonNumeric name="dei:EntityCentralIndexKey">{cik}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentPeriodEndDate">{end}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentFiscalYearFocus">2031</ix:nonNumeric></p>
    <h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>All business text remains available.</p>
    <table><tr><td>Revenue</td><td><ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    contextRef="c" unitRef="usd" scale="6" id="rev">120</ix:nonFraction></td></tr></table>
    <h2>ITEM 1A. RISK FACTORS</h2><p>Unrelated risk text is retained in the corpus.</p></body></html>'''.encode()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        (builder.ROOT / 'output').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='e5-preparation-test-', dir=builder.ROOT / 'output')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {'schema_version': 'e5-explicit-full-datasets-v1', 'knowledge_cutoff': '2032-03-01',
                       'source_policy_id': 'local-frozen-v1', 'include_candidates': True, 'sources': []}
        for cik, start, end in [('123', '2031-01-01', '2031-12-31'), ('456', '2030-07-01', '2031-06-30')]:
            sid = 'issuer-' + cik
            raw = filing(cik, start, end)
            (self.root / (sid + '.html')).write_bytes(raw)
            company = 'sec-' + cik.zfill(10)
            dataset = self.root / sid
            materialize_sources({'company': {'company_id': company, 'cik': cik.zfill(10)},
                'as_of': '2032-03-01', 'documents': [{'source_id': sid, 'form': '10-K',
                'source_url': 'https://example.invalid/' + sid, 'filed_at': '2032-02-01',
                'period_end': end, 'content_sha256': digest(raw), 'path': sid + '.html',
                'mime_type': 'text/html', 'status': 'frozen'}]}, self.root, dataset)
            self.config['sources'].append({'dataset': str(dataset.relative_to(builder.ROOT)),
                'manifest_sha256': digest((dataset / 'manifest.json').read_bytes()), 'company_id': company,
                'source_snapshot_id': sid, 'content_sha256': digest(raw), 'form': '10-K',
                'period_end': end, 'available_at': '2032-02-01'})

    def prepare(self, config=None):
        path = self.root / 'input.json'
        path.write_text(json.dumps(self.config if config is None else config))
        return builder.prepare(path, builder.ROOT, self.root / 'prepared')

    def test_full_originals_and_company_fiscal_mappings_survive(self):
        result = self.prepare()
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['semantic_selection'])
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(result['normalization_gap_count'], 0)
        self.assertEqual(len(result['sources']), 2)
        with QueryDataPort(builder.ROOT / result['dataset']) as port:
            scoped = port.scoped(result['scope'])
            mapping = scoped.get_schema()['fiscal_periods']
            periods = {row['company_id']: row['period']['start'] for row in mapping}
            self.assertEqual(periods, {'sec-0000000123': '2031-01-01', 'sec-0000000456': '2030-07-01'})
            for source in scoped.sources:
                reader = builder.DocumentReader(port.dataset / source['index_folder'])
                self.assertTrue(any('Unrelated risk text' in b['text'] for b in reader.blocks))
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_missing_scope_wrong_source_company_period_and_semantic_fields_rejected(self):
        for change in ('missing_cutoff', 'wrong_source', 'wrong_company', 'wrong_period', 'semantic_blocks', 'future'):
            config = copy.deepcopy(self.config)
            if change == 'missing_cutoff': del config['knowledge_cutoff']
            elif change == 'wrong_source': config['sources'][0]['source_snapshot_id'] = 'unknown'
            elif change == 'wrong_company': config['sources'][0]['company_id'] = 'sec-0000000999'
            elif change == 'wrong_period': config['sources'][0]['period_end'] = '2030-12-31'
            elif change == 'semantic_blocks': config['sources'][0]['block_ids'] = ['desired-answer']
            else: config['knowledge_cutoff'] = '2031-01-01'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare(config)
            self.assertFalse((self.root / 'prepared').exists())

    def test_normalization_gaps_remain_visible(self):
        source = self.config['sources'][0]
        raw = (self.root / 'issuer-123.html').read_bytes().replace(b'</table>', b'''<tr><td>
            <ix:nonFraction name="us-gaap:UnmappedSyntheticMetric" contextRef="c" unitRef="usd"
            id="unmapped">10</ix:nonFraction></td></tr></table>''')
        (self.root / 'unmapped.html').write_bytes(raw)
        dataset = self.root / 'dataset-with-gap'
        materialize_sources({'company': {'company_id': source['company_id'], 'cik': '0000000123'},
            'as_of': '2032-03-01', 'documents': [{'source_id': source['source_snapshot_id'], 'form': '10-K',
            'source_url': 'https://example.invalid/issuer-123', 'filed_at': source['available_at'],
            'period_end': source['period_end'], 'content_sha256': digest(raw), 'path': 'unmapped.html',
            'mime_type': 'text/html', 'status': 'frozen'}]}, self.root, dataset)
        source.update(dataset=str(dataset.relative_to(builder.ROOT)), content_sha256=digest(raw),
                      manifest_sha256=digest((dataset / 'manifest.json').read_bytes()))
        result = self.prepare()
        self.assertEqual(result['status'], 'prepared_with_gaps')
        self.assertEqual(result['normalization_gap_count'], 1)
        self.assertEqual(result['normalization_gap_reasons'], {'unmapped_concept': 1})

    def test_hash_tamper_rejected(self):
        source = self.config['sources'][0]
        raw = builder.ROOT / source['dataset'] / 'raw' / (source['source_snapshot_id'] + '.html')
        raw.write_bytes(raw.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.prepare()
        self.assertFalse((self.root / 'prepared').exists())


if __name__ == '__main__':
    unittest.main()
