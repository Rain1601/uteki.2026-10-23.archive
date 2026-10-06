"""Independent synthetic companies, exact decimals, scope and failure-state UI."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from apps.review_workbench.data import direct_extraction_views as artifacts
from apps.review_workbench.pages import data_evaluation
from apps.review_workbench.pages.direct_extractions import render_direct_extractions
from tests.unit import test_direct_extraction_views as fixtures
from tests.unit.test_data_evaluation_view import dataset, Links


class ExtractionFactMatrixTests(unittest.TestCase):
    save = fixtures.DirectExtractionViewTests.save
    register = fixtures.DirectExtractionViewTests.register

    def setUp(self):
        fixtures.DirectExtractionViewTests.setUp(self)
        self.data = dataset('cedar')
        self.data['records'] = []
        self.data['evidence'] = {}
        block = self.data['blocks']['cedar-source'][0]
        block['text_hash'] = hashlib.sha256(block['text'].encode()).hexdigest()
        self.packet = {'company_id': 'cedar', 'source': self.data['sources'][0],
            'task': {'company_id': 'cedar'}, 'blocks': [block],
            'entity_catalog': [{'entity_id': 'cedar'}, {'entity_id': 'cedar-segment'}],
            'period_catalog': [{'period_id': 'fy2032', 'period': {'kind': 'year', 'basis': 'source', 'start': '2032-01-04', 'end': '2033-01-01'}},
                               {'period_id': 'fy2031', 'period': {'kind': 'year', 'basis': 'source', 'start': '2030-12-29', 'end': '2032-01-03'}}]}
        base = {'draft_id': 'd1', 'kind': 'financial', 'entity': 'Cedar', 'entity_id': 'cedar',
            'metric': 'Revenue <script>x</script>', 'metric_id': 'revenue', 'period': 'FY2032', 'period_id': 'fy2032',
            'value': '12.34567890123456789', 'unit': 'USD_millions', 'value_relation': 'eq',
            'accounting_basis': 'reported_consolidated', 'evidence': [{'block_id': 'table-1', 'quote': 'cedar evidence'}],
            'qualifiers': [], 'unresolved_fields': []}
        self.drafts = [base, {**base, 'draft_id': 'd2', 'period': 'FY2031', 'period_id': 'fy2031', 'value': '10'},
                       {**base, 'draft_id': 'd3', 'entity': 'Cedar segment', 'entity_id': 'cedar-segment'},
                       {**base, 'draft_id': 'd4', 'unit': 'TWD_millions'},
                       {**base, 'draft_id': 'd5', 'accounting_basis': 'non_gaap'},
                       {**base, 'draft_id': 'd6', 'value': '99'}]
        self.normal = {'record_id': 'n1', 'entity_id': 'cedar', 'metric_id': 'revenue',
            'source_snapshot_id': 'cedar-source', 'period': self.packet['period_catalog'][0]['period'],
            'value_decimal': '12345678.90123456789', 'unit': 'USD', 'accounting_basis': 'reported_consolidated',
            'dimensions': {}, 'status': 'candidate', 'origin': {'draft_id': 'd1', 'raw': base},
            'evidence_ids': [], 'qualifier_evidence_ids': [], 'question_evidence_ids': []}
        self.payloads = {'packet.json': self.packet, 'extraction.json': {'records': self.drafts, 'gaps': ['Synthetic incomplete source coverage']},
            'normalized.json': {'records': [self.normal], 'evidence': {},
                'unresolved': [{'draft_id': 'd3', 'reason': 'unresolved_entity'}, {'draft_id': 'd4', 'reason': 'unsupported_unit'}]},
            'result.json': {'status': 'completed_with_gaps'}}
        self.pin()

    def pin(self):
        self.register(self.payloads)
        self.config['runs'][0]['dataset'] = {'id': 'cedar', 'manifest_sha256': self.data['manifest_sha256']}
        self.save(artifacts.REGISTRATION, self.config)

    def evaluation(self, **extra):
        query = {'dataset': self.data['id'], 'tab': 'records', 'source': 'cedar-source', **extra}
        catalog = {'datasets': [{'id': self.data['id'], 'company_name': self.data['company']['name'],
                                'symbol': self.data['company']['symbol'], 'snapshot_id': self.data['snapshot_id']}], 'runs': []}
        with patch.object(data_evaluation, 'load_catalog', return_value=catalog), patch.object(data_evaluation, 'load_dataset', return_value=self.data):
            return data_evaluation.render_evaluation(self.root, {k: [v] for k, v in query.items() if v is not None})

    def test_short_run_link_resolves_its_bound_source_for_filters_and_navigation(self):
        # A different material first in the same dataset must not become the source.
        other_source = deepcopy(self.data['sources'][0])
        other_source['source_snapshot_id'] = 'cedar-other-source'
        self.data['sources'].insert(0, other_source)
        html = self.evaluation(source=None, run='synthetic', kind='reported', fact='d1')
        self.assertIn('id="fact-detail"', html)
        self.assertIn('value="cedar-source" selected', html)
        queries = Links(html).queries
        for query in queries:
            if query.get('run') == ['synthetic'] or query.get('return_run') == ['synthetic']:
                if query.get('dataset') == ['cedar']:
                    self.assertEqual(query['source'], ['cedar-source'])
        for tab in ('materials', 'blocks', 'records'):
            self.assertTrue(any(q.get('tab') == [tab] and q.get('source') == ['cedar-source'] for q in queries))

    def test_run_source_resolution_rejects_blank_conflicting_unknown_or_ambiguous_scope(self):
        for args in ({'source': ''}, {'source': ' '}, {'source': 'harbor-source'},
                     {'source': None, 'run': 'unregistered'}):
            with self.subTest(args=args), self.assertRaises((KeyError, ValueError)):
                self.evaluation(**{'run': 'synthetic', **args})
        other_source = deepcopy(self.data['sources'][0])
        other_source['source_snapshot_id'] = 'cedar-other-source'
        self.data['sources'].append(other_source)
        with self.assertRaisesRegex(ValueError, 'outside selected dataset/source'):
            self.evaluation(run='synthetic', source='cedar-other-source')
        self.config['runs'].append(deepcopy(self.config['runs'][0]))
        self.save(artifacts.REGISTRATION, self.config)
        with self.assertRaises(ValueError):
            self.evaluation(run='synthetic', source=None)

    def test_short_run_link_still_checks_dataset_source_and_packet_bindings(self):
        original = self.data
        for target, key, value in [('dataset', 'manifest_sha256', 'c'*64),
                                  ('source', 'source_sha256', 'd'*64),
                                  ('company', 'company_id', 'harbor')]:
            self.data = deepcopy(original)
            destination = self.data if target == 'dataset' else self.data['sources'][0] if target == 'source' else self.data['company']
            destination[key] = value
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.evaluation(run='synthetic', source=None)
        self.data = dataset('harbor')
        with self.assertRaises(ValueError):
            self.evaluation(run='synthetic', source=None)
        self.data = deepcopy(original)
        self.data['blocks']['cedar-source'][0]['text_hash'] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'packet block differs'):
            self.evaluation(run='synthetic', source=None)

    def test_missing_run_and_source_only_lists_available_runs(self):
        html = self.evaluation(source=None)
        self.assertIn('synthetic', html)
        self.assertNotIn('data-fact-id=', html)
        self.assertIn('value="" selected', html)

    def test_matrix_keeps_entity_currency_basis_and_duplicate_cells_separate(self):
        html = self.evaluation(run='synthetic')
        # Four reported groups plus one normalized group. Duplicate d1/d6 both remain.
        self.assertEqual(html.count('<tr data-scope='), 5)
        for fact in ('d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'n1'):
            self.assertIn(f'data-fact-id="{fact}"', html)
        self.assertIn('12.34567890123456789', html)
        self.assertIn('12345678.90123456789', html)
        self.assertIn('USD_millions', html)
        self.assertIn('TWD_millions', html)
        self.assertIn('2032-01-04 — 2033-01-01', html)
        self.assertIn('2030-12-29 — 2032-01-03', html)
        self.assertNotIn('<script>x</script>', html)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;', html)
        self.assertIn('No per-fact review', html)

    def test_no_implicit_latest_run_or_cross_company_fallback(self):
        html = self.evaluation()
        self.assertIn('synthetic', html)
        self.assertNotIn('data-fact-id=', html)
        with self.assertRaises(ValueError):
            self.evaluation(run='unregistered')
        other = dataset('harbor')
        self.assertEqual(artifacts.dataset_runs(self.root, other)['runs'], [])
        with self.assertRaises(ValueError):
            artifacts.load_dataset_run(self.root, other, 'synthetic', 'harbor-source')

    def test_dataset_manifest_source_hash_and_company_all_bind(self):
        self.assertEqual(len(artifacts.dataset_runs(self.root, self.data)['runs']), 1)
        for target, key, value in [('dataset', 'manifest_sha256', 'c'*64),
                                    ('source', 'source_sha256', 'd'*64), ('company', 'company_id', 'harbor')]:
            data = deepcopy(self.data)
            destination = data if target == 'dataset' else data['sources'][0] if target == 'source' else data['company']
            destination[key] = value
            result = artifacts.dataset_runs(self.root, data)
            self.assertEqual(result['runs'], [])
            self.assertTrue(result['gaps'])
        del self.config['runs'][0]['dataset']
        self.save(artifacts.REGISTRATION, self.config)
        self.assertEqual(artifacts.dataset_runs(self.root, self.data)['runs'], [])

    def test_source_block_hash_must_also_match_dataset(self):
        self.data['blocks']['cedar-source'][0]['text_hash'] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'packet block differs'):
            artifacts.load_dataset_run(self.root, self.data, 'synthetic', 'cedar-source')

    def test_zero_normalized_still_shows_all_reported_candidates_and_own_diagnostics(self):
        self.payloads['normalized.json']['records'] = []
        self.pin()
        html = self.evaluation(run='synthetic', kind='reported', fact='d3')
        self.assertIn('Reported model drafts (6)', html)
        self.assertIn('Normalized candidates (0)', html)
        detail = html.split('id="fact-detail"', 1)[1].split('</section>', 1)[0]
        self.assertIn('unresolved_entity', detail)
        self.assertNotIn('unsupported_unit', detail)
        self.assertIn('No independent verdict', detail)
        self.assertIn('ds-original-table', detail)
        self.assertIn('No database artifact', html)

    def test_cell_source_and_return_links_preserve_selected_dataset_source_run(self):
        html = self.evaluation(run='synthetic', kind='reported', fact='d1')
        block_query = next(q for q in Links(html).queries if q.get('return_fact') == ['d1'])
        self.assertEqual(block_query['dataset'], ['cedar'])
        self.assertEqual(block_query['source'], ['cedar-source'])
        self.assertEqual(block_query['return_run'], ['synthetic'])
        source_page = self.evaluation(**{k: v[0] for k, v in block_query.items()})
        back = next(q for q in Links(source_page).queries if q.get('fact') == ['d1'])
        self.assertEqual(back['tab'], ['records'])
        self.assertEqual(back['dataset'], ['cedar'])
        self.assertEqual(back['source'], ['cedar-source'])
        self.assertEqual(back['run'], ['synthetic'])

    def test_unknown_fact_layer_and_return_identity_reject_without_substitution(self):
        for args in ({'run': 'synthetic', 'kind': 'reported', 'fact': 'missing'},
                     {'run': 'synthetic', 'kind': 'normalized', 'fact': 'd1'},
                     {'kind': 'reported', 'fact': 'd1'},
                     {'tab': 'blocks', 'return_run': 'synthetic', 'return_kind': 'reported', 'return_fact': 'other'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.evaluation(**args)

    def test_review_verdict_does_not_spread_from_one_draft_to_others(self):
        review = {'run_id': 'synthetic', 'company_id': 'cedar', 'source_snapshot_id': 'cedar-source',
                  'source_sha256': 'a'*64, 'verdict': 'supported',
                  'facts': [{'draft_id': 'd1', 'verdict': 'supported', 'rationale': 'Explicitly scoped synthetic review.'}]}
        sha = self.save('experiments/review.json', review)
        self.config['runs'][0]['review'] = {'path': 'experiments/review.json', 'sha256': sha}
        self.save(artifacts.REGISTRATION, self.config)
        html = self.evaluation(run='synthetic', kind='reported', fact='d2')
        detail = html.split('id="fact-detail"', 1)[1].split('</section>', 1)[0]
        self.assertIn('No independent verdict', detail)
        self.assertNotIn('Explicitly scoped synthetic review.', detail)

    def test_review_status_is_readable_and_requires_explicit_scope(self):
        review = {'run_id': 'synthetic', 'company_id': 'cedar', 'source_snapshot_id': 'cedar-source',
                  'source_sha256': 'a'*64,
                  'facts': [{'draft_id': 'd1', 'verdict': 'value_scope_matched'}, {'draft_id': 'd2', 'verdict': 'needs_evidence'},
                            {'draft_id': 'd3', 'verdict': 'not_reviewed'}]}
        def pin_review():
            sha = self.save('experiments/review.json', review)
            self.config['runs'][0]['review'] = {'path': 'experiments/review.json', 'sha256': sha}
            self.save(artifacts.REGISTRATION, self.config)
        pin_review()
        html = self.evaluation(run='synthetic')
        for label in ('金额/期间核对匹配', '需补证据', '未核验'):
            self.assertIn(label, html)
        del review['company_id']
        pin_review()
        html = self.evaluation(run='synthetic')
        self.assertNotIn('Value / period matched', html)

    def test_missing_normalization_artifact_and_unmatched_quote_are_visible(self):
        del self.payloads['normalized.json']
        self.drafts[0]['evidence'][0]['quote'] = 'absent source words'
        self.pin()
        html = render_direct_extractions(self.root, {'run': ['synthetic'], 'kind': ['reported'], 'fact': ['d1']})
        self.assertIn('Reported model drafts (6)', html)
        self.assertIn('Quote does not match', html)
        self.assertIn('Not saved', html)

    def test_material_page_separates_four_artifacts_and_does_not_invent_brief(self):
        html = self.evaluation(tab='materials')
        for text in ('Original material', 'Source retrieval', 'Financial facts', 'Filing brief', 'Not generated'):
            self.assertIn(text, html)
        self.assertNotIn('data-fact-id=', html)

    def test_coverage_and_negative_relations_are_visible_outside_json(self):
        review = {'run_id': 'synthetic', 'company_id': 'cedar', 'source_snapshot_id': 'cedar-source',
            'source_sha256': 'a'*64, 'facts': [],
            'coverage_findings': [{'id': 'comparative-missing', 'verdict': 'insufficient', 'rationale': 'A comparative column was omitted.', 'source_block_ids': ['table-1']}],
            'relations': [{'relation_id': 'bad-relation', 'verdict': 'incorrect', 'rationale': 'Wrong target record.'},
                          {'relation_id': 'good-relation', 'verdict': 'supported', 'rationale': 'Supported relation.'}]}
        sha = self.save('experiments/review.json', review)
        self.config['runs'][0]['review'] = {'path': 'experiments/review.json', 'sha256': sha}
        self.save(artifacts.REGISTRATION, self.config)
        html = self.evaluation(run='synthetic')
        self.assertIn('data-review-finding="comparative-missing"', html)
        self.assertIn('<p>A comparative column was omitted.</p>', html)
        self.assertIn('data-review-finding="bad-relation"', html)
        self.assertIn('<p>Wrong target record.</p>', html)
        self.assertNotIn('data-review-finding="good-relation"', html)


if __name__ == '__main__':
    unittest.main()
