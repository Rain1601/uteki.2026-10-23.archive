"""A correct selected fact must not hide unrelated supplementary body delivery."""
from copy import deepcopy
import unittest

from uteki.agents.data_query.answer_handoff import validate_assessment


class DeliveryBodyReviewTests(unittest.TestCase):
    def setUp(self):
        citation = {'source_snapshot_id':'annual-a', 'block_id':'b1', 'quote':'Products A and B.'}
        self.packet = {'packet_id':'review-fixture', 'purpose':'analysis_evidence',
            'delivery_schema_version':'selected-originals-v2',
            'scope':{'source_snapshot_ids':['annual-a']}, 'query_status':'evidence_ready',
            'query_gaps':[], 'program_gaps':[], 'requirements':[{'requirement_id':'business'}],
            'facts':[{'fact_id':'f1'}], 'source_documents':[{'source_snapshot_id':'annual-a', 'index_id':'index-a', 'source_sha256':'a'*64,
                'blocks':[{'block_id':'b1','text':'Products A and B.'},
                          {'block_id':'b2','text':'Unrelated litigation paragraph.'}]}]}
        self.response = {'packet_id':'review-fixture', 'question_coverage':'complete',
            'coverage_reason':'Both products are provided.', 'missing_information':[], 'limitations':[],
            'facts':[{'fact_id':'f1','verdict':'supported','relevance':'necessary',
                      'rationale':'Lists the products.','citations':[citation]}],
            'requirements':[{'requirement_id':'business','verdict':'complete',
                             'rationale':'Product list available.','citations':[citation]}],
            'source_checks':[{'source_snapshot_id':'annual-a','verdict':'text_sufficient',
                              'rationale':'Original list sufficient.','citations':[citation]}],
            'body_checks':[{'source_snapshot_id':'annual-a','block_id':'b1','relevance':'necessary',
                            'rationale':'Product list.'},
                           {'source_snapshot_id':'annual-a','block_id':'b2','relevance':'irrelevant',
                            'rationale':'Not needed for the product question.'}]}

    def test_unrelated_extra_body_blocks_eligibility_even_when_all_facts_are_supported(self):
        assessment, eligible = validate_assessment(self.packet, self.response)
        self.assertEqual(assessment['question_coverage'], 'complete')
        self.assertFalse(eligible)

    def test_all_delivered_body_identities_must_be_reviewed_exactly_once(self):
        for bad in ([], self.response['body_checks'][:1], self.response['body_checks']*2,
                    [*self.response['body_checks'], {'source_snapshot_id':'other-source',
                     'block_id':'b3','relevance':'necessary','rationale':'Foreign block.'}]):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'every delivered source body'):
                validate_assessment(self.packet, {**self.response, 'body_checks':bad})

    def test_only_sufficient_relevant_body_delivery_is_eligible(self):
        packet, response = deepcopy(self.packet), deepcopy(self.response)
        packet['source_documents'][0]['blocks'].pop()
        response['body_checks'].pop()
        self.assertTrue(validate_assessment(packet, response)[1])

    def test_legacy_response_without_body_checks_retains_its_representation(self):
        packet, response = deepcopy(self.packet), deepcopy(self.response)
        packet['delivery_schema_version']='selected-originals-v1'
        del response['body_checks']
        assessment, eligible = validate_assessment(packet, response)
        self.assertNotIn('body_checks', assessment)
        self.assertTrue(eligible)


if __name__ == '__main__':
    unittest.main()
