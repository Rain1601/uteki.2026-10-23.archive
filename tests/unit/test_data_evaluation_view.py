"""Synthetic read-only evaluation views: explicit scope, exact values and lineage."""
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from apps.review_workbench.pages import data_evaluation as view


DECIMAL = '9007199254740993.123456789012'
UNTRUSTED = '<script>untrusted_source()</script>'


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.queries = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href', '')
            self.queries.append(parse_qs(urlparse(href).query))


def dataset(company):
    sid = f'{company}-source'
    eid = f'{company}-evidence'
    source = {'source_snapshot_id': sid, 'company_id': company,
              'document_id': sid, 'source_url': f'https://example.test/{company}',
              'source_sha256': 'a' * 64, 'raw_file_sha256': 'a' * 64,
              'raw_file': f'raw/{sid}.html', 'index_id': f'{company}-index',
              'index_folder': f'indexes/{sid}', 'form': '10-K',
              'period_end': '2032-12-31', 'available_at': '2033-02-01',
              'status': 'candidate', 'declared_mime_type': 'text/html',
              'parsed_mime_type': 'text/html', 'image_block_count': 0,
              'capabilities': ['read_context', 'literal_search', 'source_bytes']}
    block = {'block_id': 'table-1', 'type': 'table', 'text': f'{company} evidence {UNTRUSTED} {DECIMAL}',
             'table': {'row_count': 2, 'column_count': 3, 'cells': [
                 {'row': 0, 'column': 0, 'rowspan': 2, 'colspan': 2,
                  'text': f'{company} evidence {UNTRUSTED}', 'is_header': True},
                 {'row': 0, 'column': 2, 'rowspan': 1, 'colspan': 1,
                  'text': DECIMAL, 'is_header': False}]}}
    record = {'record_id': 'shared-local-record', 'record_type': 'metric',
              'entity_id': company, 'metric_id': 'synthetic_capacity',
              'period': {'kind': 'year', 'start': '2032-01-01', 'end': '2032-12-31'},
              'period_resolution': 'resolved', 'value_kind': 'actual',
              'value_decimal': DECIMAL, 'upper_decimal': None,
              'value_relation': 'eq', 'unit': 'units', 'denominator': None,
              'modality': None, 'accounting_basis': 'reported_consolidated',
              'dimensions': {}, 'available_at': '2033-02-01',
              'source_snapshot_id': sid, 'evidence_ids': [eid],
              'qualifier_evidence_ids': [], 'question_evidence_ids': [],
              'summary': f'{company} candidate only', 'speaker': None,
              'status': 'candidate', 'origin': {'artifact': source['raw_file'],
                  'adapter': 'synthetic-v1', 'record_index': 0},
              'normalization_notes': ['Synthetic source; not adopted.']}
    evidence = {'evidence_id': eid, 'source_snapshot_id': sid, 'block_id': 'table-1',
                'quote': f'{company} evidence {UNTRUSTED}', 'source_sha256': 'a' * 64,
                'source_url': source['source_url'], 'index_id': source['index_id'],
                'number_metadata': {'value_decimal': DECIMAL, 'scale': 0, 'unit': 'units'}}
    return {'id': company, 'company': {'company_id': company, 'name': company.title(),
                                     'symbol': company.upper(), 'cik': None, 'market': 'synthetic'},
            'snapshot_id': f'{company}-snapshot', 'manifest_sha256': 'b' * 64,
            'source_policy_id': 'synthetic-frozen-v1', 'status': 'candidate',
            'sources': [source], 'records': [record], 'evidence': {eid: evidence},
            'metrics': {'synthetic_capacity': {'label': 'Synthetic capacity'}},
            'columns': [{'table_name': 'observations', 'column_name': 'value_decimal',
                         'data_type': 'DECIMAL(38,12)', 'is_nullable': 'YES'}],
            'blocks': {sid: [block]}, 'indexes': {sid: {'index_id': source['index_id'],
                'source_snapshot_id': sid, 'block_count': 1}},
            'assets': {sid: {'assets': []}}, 'raw_sizes': {sid: 100},
            'gaps': [{'source_snapshot_id': sid, 'layer': 'normalization',
                      'reason': 'unmapped_concept', 'concept': f'{company}:UnmappedOne'},
                     {'source_snapshot_id': sid, 'layer': 'normalization',
                      'reason': 'unmapped_concept', 'concept': f'{company}:UnmappedTwo'},
                     {'source_snapshot_id': sid, 'layer': 'reading',
                      'reason': 'image_reference_only', 'asset_id': f'{company}-asset',
                      'description': UNTRUSTED}],
            'limits': [f'{company} synthetic data has no independent adoption.']}


class DataEvaluationViewTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/synthetic/evaluation')
        self.datasets = {company: dataset(company) for company in ('orchard', 'harbor')}
        self.catalog = {'datasets': [
            {'id': name, 'company_id': name, 'company_name': name.title(),
             'symbol': name.upper(), 'snapshot_id': data['snapshot_id'],
             'status': 'candidate', 'source_count': 1, 'record_count': 1,
             'manifest_sha256': data['manifest_sha256']}
            for name, data in self.datasets.items()],
            'runs': [{'id': 'orchard-run', 'label': 'Orchard saved run', 'dataset_id': 'orchard'}]}
        record = deepcopy(self.datasets['orchard']['records'][0])
        evidence = deepcopy(next(iter(self.datasets['orchard']['evidence'].values())))
        evidence['original_block'] = deepcopy(self.datasets['orchard']['blocks']['orchard-source'][0])
        self.run = {'id': 'orchard-run', 'label': 'Orchard saved run', 'dataset_id': 'orchard',
                    'question': 'What capacity did Orchard report?',
                    'scope': {'snapshot_id': 'orchard-snapshot', 'company_ids': ['orchard'],
                              'source_snapshot_ids': ['orchard-source']},
                    'result': {'status': 'complete', 'gaps': [], 'coverage': []},
                    'facts': [{'fact_id': 'orchard-fact', 'kind': 'record',
                               'requirement_ids': ['capacity'], 'value': record,
                               'citations': [evidence]}],
                    'assessment': None, 'review_result': {}, 'steps': [], 'limitations': []}
        self.catalog_mock = self.patch('load_catalog', return_value=self.catalog)
        self.dataset_mock = self.patch('load_dataset', side_effect=self.load_dataset)
        self.run_mock = self.patch('load_run', side_effect=self.load_run)

    def patch(self, name, **kwargs):
        patcher = patch.object(view, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def load_dataset(self, root, dataset_id):
        if dataset_id not in self.datasets:
            raise ValueError('Unknown dataset')
        return deepcopy(self.datasets[dataset_id])

    def load_run(self, root, run_id):
        if run_id != self.run['id']:
            raise ValueError('Unknown run')
        return deepcopy(self.run)

    def render(self, **query):
        return view.render_evaluation(self.root, {key: [value] for key, value in query.items()})

    def test_landing_lists_choices_without_loading_an_arbitrary_dataset(self):
        html = self.render()
        self.dataset_mock.assert_not_called()
        self.run_mock.assert_not_called()
        self.assertIn('Orchard', html)
        self.assertIn('Harbor', html)
        self.assertNotIn('orchard candidate only', html)
        self.assertEqual(self.render(dataset='orchard'),
                         self.render(dataset='orchard', tab='materials'))

    def test_unknown_blank_and_ambiguous_dataset_selection_fails_closed(self):
        for query in ({'dataset': ['unknown']}, {'dataset': ['']},
                      {'dataset': ['orchard', 'harbor']}, {'run': ['orchard-run']}):
            with self.subTest(query=query), self.assertRaises((KeyError, ValueError)):
                view.render_evaluation(self.root, query)

    def test_each_selected_dataset_keeps_records_and_sources_isolated(self):
        for company, other in (('orchard', 'harbor'), ('harbor', 'orchard')):
            with self.subTest(company=company):
                html = self.render(dataset=company, tab='records', record='shared-local-record')
                self.assertIn(f'{company} candidate only', html)
                self.assertIn(f'{company}-source', html)
                self.assertNotIn(f'{other} candidate only', html)
                self.assertNotIn(f'{other} evidence', html)
                for query in Links(html).queries:
                    if 'record' in query:
                        self.assertEqual(query.get('dataset'), [company])

    def test_unknown_record_source_block_and_run_do_not_fall_back(self):
        for extra in ({'tab': 'records', 'record': 'unknown'},
                      {'tab': 'materials', 'source': 'harbor-source'},
                      {'tab': 'blocks', 'source': 'orchard-source', 'block': 'unknown'},
                      {'tab': 'runs', 'run': 'unknown'}):
            with self.subTest(extra=extra), self.assertRaises((KeyError, ValueError)):
                self.render(dataset='orchard', **extra)

    def test_exact_decimal_and_source_table_survive_record_drilldown(self):
        html = self.render(dataset='orchard', tab='records', record='shared-local-record')
        for value in ('observations', 'value_decimal', 'DECIMAL(38,12)', 'YES'):
            self.assertIn(f'<td>{value}</td>', html)
        self.assertIn(DECIMAL, html)
        self.assertIn('colspan="2"', html)
        self.assertIn('rowspan="2"', html)
        self.assertIn('&lt;script&gt;untrusted_source()&lt;/script&gt;', html)
        self.assertNotIn(UNTRUSTED, html)

    def test_materials_group_coverage_gaps_and_preserve_full_scoped_details(self):
        for company, other in (('orchard', 'harbor'), ('harbor', 'orchard')):
            with self.subTest(company=company):
                data = self.datasets[company]
                annex = f'{company}-annex'
                data['sources'].append({**data['sources'][0], 'source_snapshot_id': annex})
                data['blocks'][annex] = []
                data['indexes'][annex] = {}
                data['gaps'].append({'source_snapshot_id': annex, 'layer': 'normalization',
                                     'reason': 'unmapped_concept', 'concept': f'{company}:AnnexConcept'})
                html = self.render(dataset=company, tab='materials')
                summaries = [unescape(re.sub(r'<[^>]+>', '', item)) for item in
                             re.findall(r'<summary>(.*?)</summary>', html, flags=re.DOTALL)]
                for reason in ('unmapped_concept', 'image_reference_only'):
                    group = [text for text in summaries if f'{company}-source' in text and reason in text]
                    self.assertEqual(len(group), 1, f'Expected one {company}/{reason} gap disclosure.')
                self.assertEqual(len([text for text in summaries if annex in text and 'unmapped_concept' in text]), 1)
                original_entries = [json.loads(unescape(item)) for item in
                                    re.findall(r'<pre>(\s*\[.*?)</pre>', html, flags=re.DOTALL)]
                for entries in original_entries:
                    self.assertEqual(len({entry['source_snapshot_id'] for entry in entries}), 1)
                    self.assertEqual(len({entry['reason'] for entry in entries}), 1)
                for gap in data['gaps']:
                    self.assertTrue(any(isinstance(value, list) and gap in value for value in original_entries),
                                    f'Original gap metadata is missing: {gap}')
                self.assertIn(f'{company}:UnmappedOne', html)
                self.assertIn(f'{company}:UnmappedTwo', html)
                self.assertIn(f'{company} synthetic data has no independent adoption.', html)
                self.assertNotIn(f'{other}:Unmapped', html)
                self.assertNotIn(f'{other}-asset', html)
                self.assertNotIn(f'{other} synthetic data', html)
                self.assertIn('&lt;script&gt;untrusted_source()&lt;/script&gt;', html)
                self.assertNotIn(UNTRUSTED, html)

    def test_run_requires_its_bound_dataset_even_when_local_record_ids_match(self):
        with self.assertRaises((KeyError, ValueError)):
            self.render(dataset='harbor', tab='runs', run='orchard-run')
        self.run['dataset_id'] = 'harbor'
        with self.assertRaises((KeyError, ValueError)):
            self.render(dataset='orchard', tab='runs', run='orchard-run')

    def test_unreviewed_run_does_not_display_a_supported_verdict(self):
        html = self.render(dataset='orchard', tab='runs', run='orchard-run')
        self.assertTrue(re.search(r'未复核|未审核|未评审|未审阅|尚无复核|No (?:saved .*|review)|Not reviewed|Unreviewed|review unavailable|Missing review', html),
                        'A saved run with no assessment must show an explicit missing-review message.')
        self.assertFalse(re.search(r'>(?:supported|approved)<', html, flags=re.IGNORECASE))

    def test_fact_record_link_checks_source_as_well_as_local_record_id(self):
        self.run['assessment'] = {'facts': [{'fact_id': 'orchard-fact', 'verdict': 'supported',
                                           'rationale': 'Matches the selected source.', 'citations': []}]}
        detail = self.render(dataset='orchard', tab='records', record='shared-local-record')
        self.assertIn('Matches the selected source.', detail)
        other = self.render(dataset='harbor', tab='records', record='shared-local-record')
        self.assertNotIn('Matches the selected source.', other)
        matched = self.render(dataset='orchard', tab='runs', run='orchard-run')
        record_links = [query for query in Links(matched).queries if 'record' in query]
        self.assertTrue(record_links)
        for query in record_links:
            self.assertEqual(query.get('dataset'), ['orchard'])
            self.assertEqual(query['record'], ['shared-local-record'])
        self.run['facts'][0]['value']['source_snapshot_id'] = 'harbor-source'
        self.run['facts'][0]['value']['entity_id'] = 'harbor'
        detail = self.render(dataset='orchard', tab='records', record='shared-local-record')
        self.assertNotIn('Matches the selected source.', detail)
        with self.assertRaises((KeyError, ValueError)):
            self.render(dataset='orchard', tab='runs', run='orchard-run')
