"""Synthetic annotation boundaries; no API calls or semantic oracle claims."""
from copy import deepcopy
import unittest

from uteki.evaluation.evidence_benchmark import evaluate


class EvidenceBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.corpus = {'filing': {'company_id': 'issuer-a', 'sha256': 'a' * 64,
                                  'blocks': {'b1': 'Revenue 10. Other', 'equivalent': 'Revenue 10.'}}}
        self.gold = {'schema_version': 'evidence-gold-v1', 'case_id': 'synthetic',
                     'question': 'What revenue?', 'company_ids': ['issuer-a'],
                     'sources': [{'source_id': 'filing', 'company_id': 'issuer-a', 'sha256': 'a' * 64}],
                     'required': [{'id': 'amount', 'description': 'Revenue amount with its label'}],
                     'optional': [{'id': 'other', 'description': 'Ancillary detail'}]}
        citation = {'source_id': 'filing', 'block_id': 'b1', 'start': 0, 'end': 11, 'quote': 'Revenue 10.'}
        self.review = {'schema_version': 'evidence-review-v1', 'case_id': 'synthetic',
                       'question': 'What revenue?', 'reviewer': 'synthetic-reviewer',
                       'requirements': [{'id': 'amount', 'status': 'supported',
                                         'reason': 'Synthetic label and amount.', 'citations': [citation]}],
                       'checks': {k: {'status': 'pass', 'reason': 'Synthetic reviewed fixture.'}
                                  for k in ('scope', 'truth', 'provenance', 'focus')},
                       'deliveries': [{'id': 'd1', **citation, 'segments': [
                           {'start': 0, 'end': 11, 'category': 'required', 'requirement_ids': ['amount']}]}],
                       'cost': {'known_usd': '0.10', 'unknown_reserved_usd': '0.20'}}

    def test_equivalent_location_and_costs_without_double_counting(self):
        self.review['deliveries'].append({**deepcopy(self.review['deliveries'][0]), 'id': 'd2'})
        score = evaluate(self.gold, self.review, self.corpus)
        self.assertEqual(score['status'], 'pass')
        self.assertEqual(score['characters']['unique_source_characters'], 11)
        self.assertEqual(score['characters']['delivered_character_occurrences'], 22)
        self.assertEqual(score['cost']['committed_estimated_usd'], '0.30')
        for item in [*self.review['deliveries'], *self.review['requirements'][0]['citations']]:
            item['block_id'] = 'equivalent'
        self.assertEqual(evaluate(self.gold, self.review, self.corpus)['status'], 'pass')

    def test_missing_partial_and_hard_checks_never_offset(self):
        self.review['requirements'][0]['status'] = 'partial'
        score = evaluate(self.gold, self.review, self.corpus)
        self.assertEqual(score['required_coverage']['numerator'], 0)
        self.assertEqual(score['status'], 'fail')
        self.review['requirements'][0]['status'] = 'supported'
        self.review['checks']['truth']['status'] = 'fail'
        self.assertEqual(evaluate(self.gold, self.review, self.corpus)['status'], 'fail')
        self.review['checks']['truth']['status'] = 'unassessed'
        self.assertEqual(evaluate(self.gold, self.review, self.corpus)['status'], 'unassessed')

    def test_intervals_must_cover_without_overlap_and_stay_in_bounds(self):
        for segments in ([{'start': 1, 'end': 11}], [{'start': 0, 'end': 12}],
                         [{'start': 0, 'end': 6}, {'start': 5, 'end': 11}], [{'start': 0, 'end': 10}]):
            with self.subTest(segments=segments):
                review = deepcopy(self.review)
                review['deliveries'][0]['segments'] = [dict(s, category='required', requirement_ids=['amount']) for s in segments]
                with self.assertRaises(ValueError):
                    evaluate(self.gold, review, self.corpus)

    def test_unassessed_and_table_structure_reported_separately(self):
        delivery = self.review['deliveries'][0]
        delivery.update(end=17, quote='Revenue 10. Other')
        delivery['end'] = len(delivery['quote'])
        delivery['segments'] += [dict(start=11, end=12, category='table_structure', requirement_ids=[]),
                                 dict(start=12, end=17, category='unassessed', requirement_ids=[])]
        score = evaluate(self.gold, self.review, self.corpus)
        self.assertEqual(score['status'], 'unassessed')
        self.assertEqual(score['characters']['categories']['table_structure']['numerator'], 1)
        self.assertEqual(score['characters']['categories']['unassessed']['numerator'], 5)

    def test_metadata_requirement_uses_verified_delivered_metadata_not_fabricated_quote(self):
        self.corpus['filing']['metadata'] = {'fiscal_period.start': '2023-07-01'}
        self.gold['required'].append({'id': 'period', 'kind': 'metadata', 'description': 'Fiscal start'})
        citation = dict(kind='metadata', source_id='filing', field='fiscal_period.start', value='2023-07-01')
        self.review['metadata_deliveries'] = [dict(citation, id='m1')]
        self.review['requirements'].append(dict(id='period', status='supported', reason='Verified XBRL context.', citations=[citation]))
        score = evaluate(self.gold, self.review, self.corpus)
        self.assertEqual(score['status'], 'pass')
        self.assertEqual(score['required_coverage']['numerator'], 2)
        self.assertEqual(score['characters']['unique_source_characters'], 11)
        self.review['metadata_deliveries'] = []
        with self.assertRaises(ValueError): evaluate(self.gold, self.review, self.corpus)

    def test_focus_failure_cannot_be_offset_by_complete_required_coverage(self):
        self.review['checks']['focus'] = dict(status='fail', reason='Independent reviewer found excessive unrelated material.')
        score = evaluate(self.gold, self.review, self.corpus)
        self.assertEqual(score['required_coverage']['ratio'], 1)
        self.assertEqual(score['status'], 'fail')
        self.review['checks']['focus']['status'] = 'unassessed'
        self.assertEqual(evaluate(self.gold, self.review, self.corpus)['status'], 'unassessed')

    def test_optional_category_cannot_bypass_empty_optional_contract(self):
        self.gold['optional'] = []
        segment = self.review['deliveries'][0]['segments'][0]
        segment.update(category='optional', requirement_ids=[])
        with self.assertRaises(ValueError): evaluate(self.gold, self.review, self.corpus)

    def test_wrong_identity_quote_or_undelivered_support_rejected(self):
        for field, value in [('question', 'Another question'), ('case_id', 'other')]:
            review = deepcopy(self.review); review[field] = value
            with self.assertRaises(ValueError): evaluate(self.gold, review, self.corpus)
        for field, value in [('quote', 'Wrong text!'), ('block_id', 'equivalent')]:
            review = deepcopy(self.review); review['requirements'][0]['citations'][0][field] = value
            with self.assertRaises(ValueError): evaluate(self.gold, review, self.corpus)
        corpus = deepcopy(self.corpus); corpus['filing']['company_id'] = 'issuer-b'
        with self.assertRaises(ValueError): evaluate(self.gold, self.review, corpus)
        self.review['cost']['unknown_reserved_usd'] = 'NaN'
        with self.assertRaises(ValueError): evaluate(self.gold, self.review, self.corpus)


if __name__ == '__main__':
    unittest.main()
