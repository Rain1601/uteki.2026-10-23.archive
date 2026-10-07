"""Coverage is explicit scope accounting, not an extraction quality score."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit import test_direct_normalization as normalization_fixtures
from tests.unit import test_extraction_batches as batch_fixtures
from uteki.infrastructure.research_data.direct_extraction import run_direct_extraction
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.financial_records import digest


class FactCoverageTests(unittest.TestCase):
    def fixture(self, company='issuer-alpha', year=2030):
        packet, extraction = normalization_fixtures.DirectNormalizationTests().fixture(company, year)
        packet['required_facts'] = [{'requirement_id': 'revenue-outlook', 'entity_id': company,
            'metric_id': 'revenue', 'period_id': f'p-{year}', 'unit': 'USD',
            'accounting_basis': 'management_guidance', 'value_kind': 'management_guidance'}]
        return packet, extraction

    def test_exact_scoped_candidate_and_second_company(self):
        for company, year in [('issuer-alpha', 2030), ('issuer-beta', 2028)]:
            packet, extraction = self.fixture(company, year)
            original = deepcopy((packet, extraction))
            result = normalize_direct_candidates(extraction, packet)
            coverage = result['fact_coverage']
            self.assertEqual(coverage['status'], 'candidate_coverage_complete')
            self.assertEqual(coverage['company_id'], company)
            self.assertEqual(coverage['requirements'][0]['period']['end'], f'{year}-12-31')
            self.assertEqual(coverage['semantic_acceptance'], 'not_evaluated')
            self.assertEqual((packet, extraction), original)

    def test_missing_and_unsupported_never_become_not_disclosed(self):
        packet, extraction = self.fixture()
        missing = normalize_direct_candidates({}, packet)
        self.assertEqual(missing['validation']['status'], 'partial')
        self.assertEqual(missing['fact_coverage']['requirements'][0]['status'], 'not_extracted')
        extraction['records'][0]['unit'] = 'unsupported_currency'
        unsupported = normalize_direct_candidates(extraction, packet)
        item = unsupported['fact_coverage']['requirements'][0]
        self.assertEqual(item['status'], 'unresolved')
        self.assertIn('unsupported_unit', [i['reason'] for i in item['unresolved']])
        self.assertEqual(item['disclosure_status'], 'not_evaluated')
        self.assertEqual(unsupported['raw_candidates'], extraction['records'])

    def test_conflicting_amounts_require_review_and_duplicates_do_not_choose_winner(self):
        packet, extraction = self.fixture()
        other = deepcopy(extraction['records'][0]); other['draft_id'] = 'second'
        extraction['records'].append(other)
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result['fact_coverage']['requirements'][0]['status'], 'candidate_present')
        self.assertEqual(len(result['fact_coverage']['requirements'][0]['record_ids']), 2)
        other['value'] = '1.5'
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result['fact_coverage']['requirements'][0]['status'], 'conflict')
        self.assertEqual(result['fact_coverage']['status'], 'partial')
        self.assertEqual(len(result['records']), 2)

    def test_basis_and_period_cannot_be_satisfied_by_another_value(self):
        packet, extraction = self.fixture()
        packet['required_facts'][0].update(accounting_basis='reported_consolidated', value_kind='actual')
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result['fact_coverage']['requirements'][0]['status'], 'not_extracted')
        packet, extraction = self.fixture()
        packet['period_catalog'].append({'period_id': 'next', 'label': '2031',
            'period': {'kind': 'year', 'start': '2031-01-01', 'end': '2031-12-31'}})
        packet['required_facts'][0]['period_id'] = 'next'
        self.assertEqual(normalize_direct_candidates(extraction, packet)['fact_coverage']['requirements'][0]['status'], 'not_extracted')

    def test_no_implicit_coverage_and_invalid_scope_rejected(self):
        packet, extraction = self.fixture()
        del packet['required_facts']
        self.assertEqual(normalize_direct_candidates(extraction, packet)['fact_coverage']['status'], 'not_requested')
        for mutation in [{'entity_id': 'other'}, {'period_id': 'unknown'}, {'unit': 'TWD'},
                         {'accounting_basis': 'unknown'}, {'unexpected': 'field'}]:
            packet, extraction = self.fixture(); packet['required_facts'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize_direct_candidates(extraction, packet)
        packet, extraction = self.fixture(); packet['required_facts'] = []
        with self.assertRaises(ValueError): normalize_direct_candidates(extraction, packet)
        for same_id in (True, False):
            packet, extraction = self.fixture()
            duplicate = deepcopy(packet['required_facts'][0])
            if not same_id: duplicate['requirement_id'] = 'another-id'
            packet['required_facts'].append(duplicate)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                normalize_direct_candidates(extraction, packet)

    def test_model_gap_does_not_disappear_when_requested_amount_is_present(self):
        packet, extraction = self.fixture()
        extraction['gaps'] = ['Source unit footnote needs review.']
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result['fact_coverage']['requirements'][0]['status'], 'candidate_present')
        self.assertEqual(result['fact_coverage']['status'], 'partial')
        self.assertEqual(result['fact_coverage']['model_gaps'], extraction['gaps'])

    def test_exact_fiscal_dates_and_currency_remain_explicit(self):
        packet, extraction = self.fixture('issuer-gamma', 2028)
        packet['record_schema_version'] = 'research-query-v0.5'
        packet['period_catalog'][0]['period'] = {'kind': 'year', 'start': '2027-12-26', 'end': '2028-12-30', 'basis': 'source'}
        packet['metric_catalog']['revenue']['unit'] = 'TWD'
        packet['required_facts'][0]['unit'] = 'TWD'
        extraction['records'][0]['unit'] = 'TWD_millions'
        block = packet['blocks'][0]
        block['text'] = block['text'].replace('USD', 'TWD')
        block['text_hash'] = digest(block['text'].encode())
        extraction['records'][0]['evidence'][0]['quote'] = block['text']
        result = normalize_direct_candidates(extraction, packet)
        self.assertEqual(result['fact_coverage']['status'], 'candidate_coverage_complete')
        self.assertEqual(result['records'][0]['period']['start'], '2027-12-26')
        self.assertEqual(result['records'][0]['unit'], 'TWD')
        packet['record_schema_version'] = 'research-query-v0.4'
        with self.assertRaises(ValueError): normalize_direct_candidates(extraction, packet)

    def test_projection_keeps_model_gaps_and_missing_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset, job = batch_fixtures.ExtractionBatchTests().source(root / 'source')
            job['entity_catalog'] = [{'company_id': job['company_id'], 'entity_id': job['company_id'], 'label': 'Issuer'}]
            job['required_facts'] = [{'requirement_id': 'revenue', 'entity_id': job['company_id'],
                'metric_id': 'revenue', 'period_id': 'selected-year', 'unit': 'USD',
                'accounting_basis': 'reported_consolidated', 'value_kind': 'actual'}]
            calls = []
            async def fixture(packet):
                calls.append(packet)
                return {'records': [], 'gaps': ['Footnote was not delivered.']}
            result = asyncio.run(run_direct_extraction(dataset, job, root / 'run', strategy='direct', model_call=fixture))
            manifest = json.loads((root / 'run/dataset/manifest.json').read_text())
            self.assertEqual(calls[0]['required_facts'], job['required_facts'])
            self.assertEqual(result['validation']['status'], 'partial')
            self.assertEqual(manifest['fact_coverage']['status'], 'partial')
            self.assertEqual({g['reason'] for g in manifest['gaps']}, {'model_reported_gap', 'required_fact_not_extracted'})
            self.assertIn('fact-coverage.json', manifest['files'])
            self.assertEqual(json.loads((root / 'run/dataset/model-gaps.json').read_text()), ['Footnote was not delivered.'])
            job['required_facts'][0]['entity_id'] = 'another-company'
            with self.assertRaises(ValueError):
                asyncio.run(run_direct_extraction(dataset, job, root / 'bad', strategy='direct', model_call=fixture))
            self.assertEqual(len(calls), 1)

    def test_source_year_header_adapter_preserves_exact_noncalendar_dates(self):
        packet, extraction = self.fixture('issuer-delta', 2028)
        packet['record_schema_version'] = 'research-query-v0.5'
        packet['period_catalog'][0]['period'] = {'kind': 'year', 'start': '2027-12-26', 'end': '2028-12-30', 'basis': 'source'}
        text = 'Year Ended December 30,2028 Revenue 1.2 to 1.5 million USD subject to supply'
        packet['blocks'][0].update(text=text, text_hash=digest(text.encode()), table={'cells':[
            {'text':'Year Ended','row':0,'column':1,'colspan':3},
            {'text':'December 30,2028','row':1,'column':1,'colspan':1}]})
        extraction['records'][0].update(period='December 30,2028', evidence=[{'block_id':'b1','quote':text}])
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'], [])
        packet['period_alias_adapter']='table-year-header-v1'
        result=normalize_direct_candidates(extraction,packet)
        self.assertEqual(result['records'][0]['period']['start'],'2027-12-26')
        self.assertEqual(result['records'][0]['origin']['raw']['period'],'December 30,2028')
        self.assertIn('Year Ended', [result['evidence'][eid]['quote'] for eid in result['records'][0]['qualifier_evidence_ids']])
        for target in ('wrong_end', 'wrong_column', 'quarter_caption', 'missing_header_quote'):
            changed, draft=deepcopy(packet),deepcopy(extraction)
            if target=='wrong_end': changed['period_catalog'][0]['period']['end']='2028-12-31'
            elif target=='wrong_column': changed['blocks'][0]['table']['cells'][0]['column']=4
            elif target=='quarter_caption': changed['blocks'][0]['table']['cells'][0]['text']='Quarter Ended'
            else: draft['records'][0]['evidence'][0]['quote']='Revenue 1.2 to 1.5'
            with self.subTest(target=target): self.assertEqual(normalize_direct_candidates(draft,changed)['records'], [])


if __name__ == '__main__':
    unittest.main()
