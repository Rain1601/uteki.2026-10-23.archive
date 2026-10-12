"""Offline request-identity generation boundaries; no model-quality claims."""
from copy import deepcopy
import unittest

from agents import AgentOutputSchema
from pydantic import ValidationError

from uteki.agents.data_query.question_review_generation import (
    QuestionCoverageGeneration, project_question_generation,
)
from uteki.agents.data_query.question_coverage_review import (
    QuestionCoverageAssessment, QuestionReviewProtocolError,
    project_question_review, validate_question_review, question_review_repair_input,
)
from uteki.infrastructure.research_data.financial_records import digest


class QuestionReviewGenerationTests(unittest.TestCase):
    def setUp(self):
        self.question = 'For Beacon and Cinder, provide revenue in FY2031 and FY2030.'
        text = 'Beacon FY2031 revenue was 42. Cinder FY2031 revenue was 18.'
        self.packet = {'schema_version': 'data-answer-review-input-v1', 'packet_id': 'synthetic',
            'purpose': 'analysis_evidence', 'source_delivery': 'query_evidence_v1',
            'question': self.question,
            'scope': {'execution_schema_version': 'research-execution-v1', 'snapshot_id': 'dataset',
                'company_ids': ['example'], 'source_snapshot_ids': ['annual'],
                'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2032-05-01',
                'include_candidates': True},
            'source_documents': [{'source_snapshot_id': 'annual', 'index_id': 'idx',
                'source_sha256': 'a'*64, 'company_id': 'example',
                'source_url': 'https://example.org/annual', 'source_period_end': '2031-12-31',
                'available_at': '2032-02-01', 'blocks': [{'block_id': 'table', 'type': 'paragraph',
                    'text': text, 'text_hash': digest(text.encode()), 'table': None}]}]}
        self.projected = project_question_review(self.packet)
        self.generated = {'packet_id': self.projected['packet_id'],
            'projection_id': self.projected['projection_id'], 'checks': [{
                'request': {'question_quote': 'provide revenue in FY2031 and FY2030',
                    'requested_subject': 'revenue', 'requested_dimension': 'metric',
                    'scope': {'kind': 'qualified', 'quotes': ['Beacon', 'FY2031']}},
                'judgment': {'source_subject': 'Beacon FY2031 revenue', 'relation': 'same',
                    'coverage': 'complete', 'support_basis': 'direct', 'citations': [{
                        'kind': 'block_quote', 'source_snapshot_id': 'annual', 'block_id': 'table',
                        'quote': 'Beacon FY2031 revenue was 42.'}], 'gap': None,
                    'rationale': 'Original disclosure supports this requested amount.'}}],
            'output_constraints': [], 'uncovered_requests': ['Other requested periods remain missing.'],
            'question_coverage': 'incomplete', 'coverage_reason': 'Only one requested amount is supported.'}

    def test_sdk_schema_exposes_request_before_judgment_and_requires_scope(self):
        schema = AgentOutputSchema(QuestionCoverageGeneration, strict_json_schema=False).json_schema()
        definitions = schema['$defs']
        check = definitions[schema['properties']['checks']['items']['$ref'].split('/')[-1]]
        self.assertEqual(list(check['properties']), ['request', 'judgment'])
        request = definitions[check['properties']['request']['$ref'].split('/')[-1]]
        self.assertIn('scope', request['required'])
        self.assertNotIn('source_subject', request['properties'])
        self.assertNotIn('citations', request['properties'])

    def test_scope_requires_an_explicit_nonempty_qualified_or_self_contained_choice(self):
        for scope in (None, {}, {'kind': 'qualified', 'quotes': []},
                      {'kind': 'self_contained'}, {'kind': 'self_contained', 'reason': ' '}):
            value = deepcopy(self.generated)
            if scope is None:
                del value['checks'][0]['request']['scope']
            else:
                value['checks'][0]['request']['scope'] = scope
            with self.subTest(scope=scope), self.assertRaises(ValidationError):
                project_question_generation(value)

    def test_projection_preserves_model_fields_and_never_fills_company_from_source(self):
        value = deepcopy(self.generated)
        value['checks'][0]['request']['scope']['quotes'] = ['FY2031']
        before = deepcopy(value)
        canonical = project_question_generation(value)
        normalized = QuestionCoverageGeneration.model_validate(value).model_dump(mode='json')
        request, judgment = normalized['checks'][0]['request'], normalized['checks'][0]['judgment']
        expected = {key: val for key, val in normalized.items() if key != 'checks'}
        expected['checks'] = [{key: val for key, val in request.items() if key != 'scope'} |
                              {'requested_scope_quotes': ['FY2031']} | judgment]
        self.assertEqual(canonical, QuestionCoverageAssessment.model_validate(expected).model_dump(mode='json'))
        self.assertEqual(value, before)
        self.assertEqual(canonical['checks'][0]['requested_scope_quotes'], ['FY2031'])
        canonical['checks'][0]['citations'][0]['quote'] = 'mutated result'
        self.assertEqual(value, before)

    def test_source_fields_cannot_leak_into_request_identity(self):
        value = deepcopy(self.generated)
        value['checks'][0]['request']['source_subject'] = 'A source-derived company'
        with self.assertRaises(ValidationError):
            project_question_generation(value)

    def test_omitted_company_duplicate_still_fails_original_validator_after_projection(self):
        # Reproduce the R3 mechanism using independent names: source identity
        # differs, but the requested identity loses its company qualifier.
        value = deepcopy(self.generated)
        first = value['checks'][0]
        first['request']['scope']['quotes'] = ['FY2031']
        second = deepcopy(first)
        second['judgment']['source_subject'] = 'Cinder FY2031 revenue'
        second['judgment']['citations'][0]['quote'] = 'Cinder FY2031 revenue was 18.'
        value['checks'].append(second)
        canonical = project_question_generation(value)
        with self.assertRaises(QuestionReviewProtocolError) as caught:
            validate_question_review(self.projected, canonical)
        self.assertEqual(caught.exception.diagnostic['code'], 'duplicate_check_requires_distinct_scope')
        repair = question_review_repair_input(self.projected, canonical)
        self.assertEqual(repair['previous_assessment'], canonical)
        self.assertIn('duplicate_check_requires_distinct_scope',
                      {item['code'] for item in repair['host_protocol_diagnostics']})

    def test_local_quote_and_full_question_scope_checks_remain_strict(self):
        changes = [('requested_subject', 'Beacon', 'requested_subject_requires_verbatim'),
                   ('question_quote', 'Show the revenue', 'question_quote_requires_verbatim')]
        for field, replacement, code in changes:
            value = deepcopy(self.generated)
            value['checks'][0]['request'][field] = replacement
            with self.subTest(field=field), self.assertRaises(QuestionReviewProtocolError) as caught:
                validate_question_review(self.projected, project_question_generation(value))
            self.assertEqual(caught.exception.diagnostic['code'], code)
        value = deepcopy(self.generated)
        value['checks'][0]['request']['scope']['quotes'] = ['Invented company']
        with self.assertRaises(QuestionReviewProtocolError) as caught:
            validate_question_review(self.projected, project_question_generation(value))
        self.assertEqual(caught.exception.diagnostic['code'], 'scope_quotes_require_verbatim')

    def test_self_contained_definition_remains_compatible_without_qualifiers(self):
        packet = deepcopy(self.packet)
        packet['question'] = 'Define Beacon.'
        definition = 'Beacon is a compute platform.'
        packet['source_documents'][0]['blocks'][0].update(text=definition, text_hash=digest(definition.encode()))
        projected = project_question_review(packet)
        value = deepcopy(self.generated)
        value.update(projection_id=projected['projection_id'], question_coverage='complete',
                     uncovered_requests=[], coverage_reason='The requested definition is supported.')
        value['checks'][0]['request'] = {'question_quote': 'Define Beacon',
            'requested_subject': 'Beacon', 'requested_dimension': 'definition',
            'scope': {'kind': 'self_contained', 'reason': 'Beacon is the sole requested subject.'}}
        value['checks'][0]['judgment']['source_subject'] = 'Beacon'
        value['checks'][0]['judgment']['citations'][0]['quote'] = definition
        canonical = project_question_generation(value)
        self.assertEqual(canonical['checks'][0]['requested_scope_quotes'], [])
        self.assertTrue(validate_question_review(projected, canonical)[1])
