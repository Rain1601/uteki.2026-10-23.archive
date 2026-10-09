"""Body-review schema completeness does not replace original/identity checks."""
from copy import deepcopy
import unittest

from uteki.agents.data_query.answer_handoff import AnswerAssessment, source_assessment_schema, validate_assessment
from tests.unit import test_delivery_body_review as fixtures


class SourceBodySchemaTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.DeliveryBodyReviewTests(); fixture.setUp()
        self.packet, self.response = fixture.packet, fixture.response

    def test_exact_delivery_schema_requires_every_body_but_does_not_choose_relevance(self):
        schema = source_assessment_schema(self.packet)
        exported = schema.model_json_schema()
        self.assertIn('body_checks', exported['required'])
        self.assertEqual(exported['properties']['body_checks']['minItems'], 2)
        self.assertEqual(exported['properties']['body_checks']['maxItems'], 2)
        for bad in (None, [], self.response['body_checks'][:1], self.response['body_checks'] * 2):
            response = deepcopy(self.response)
            if bad is None: response.pop('body_checks')
            else: response['body_checks'] = bad
            with self.assertRaises(ValueError): schema.model_validate(response)
        parsed = schema.model_validate(self.response).model_dump(mode='json')
        self.assertEqual(parsed['body_checks'], self.response['body_checks'])
        self.assertFalse(validate_assessment(self.packet, parsed)[1])  # Irrelevant body still blocks.

    def test_multi_source_counts_bodies_and_still_rejects_wrong_identities(self):
        self.packet['source_documents'][0]['blocks'].pop()
        self.packet['source_documents'].append({'source_snapshot_id': 'second-source',
            'blocks': [{'block_id': 'b3', 'text': 'Second original source'}]})
        schema = source_assessment_schema(self.packet)
        parsed = schema.model_validate(self.response).model_dump(mode='json')
        with self.assertRaisesRegex(ValueError, 'body_checks_identity_mismatch'):
            validate_assessment(self.packet, parsed)  # Count matches, identity does not.

    def test_legacy_optional_body_contract_and_empty_exact_delivery(self):
        self.packet['delivery_schema_version'] = 'selected-originals-v1'
        self.assertIs(source_assessment_schema(self.packet), AnswerAssessment)
        response = deepcopy(self.response); response.pop('body_checks')
        AnswerAssessment.model_validate(response)
        self.packet['delivery_schema_version'] = 'selected-originals-v3'
        self.packet['source_documents'] = []
        schema = source_assessment_schema(self.packet)
        self.assertEqual(schema.model_json_schema()['properties']['body_checks']['maxItems'], 0)
        response['body_checks'] = []; schema.model_validate(response)
