"""Independent Birch fixtures: per-record row coverage and delivered-context claims."""
from copy import deepcopy
import unittest

from uteki.domain.research_data.semantic_review import SemanticAssessmentV2
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import build_context_inventory, validate_semantic_assessment


class SemanticReviewV2Tests(unittest.TestCase):
    @staticmethod
    def seal(packet):
        packet['packet_id'] = 'semantic-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]
        return packet

    def packet(self, source='birch-annual-a', years=(2025, 2024)):
        company = 'sec-0000000678'
        # Identical numeric values and a repeated row defeat value-only/first-occurrence matching.
        text = ('桦木 Birch Devices. Illustrative prior layout: Revenue 20 20.\n'
                f'Actual annual results in USD millions. FY{years[0]} FY{years[1]}.\n'
                'Revenue 20 20\nOperating income 20 20')
        detail = ('Note 1. Segment presentation changed. Prior-period segment information was recast. '
                  'Consolidated results were unchanged. See Note 4 for allocation methodology.')
        blocks = [{'source_snapshot_id': source, 'block_id': bid, 'text': value,
                   'text_hash': digest(value.encode('utf-8'))}
                  for bid, value in [('financial-table', text), ('note-1-detail', detail)]]
        records, anchors = [], {}
        for metric, row in [('revenue', 'Revenue 20 20'), ('operating_income', 'Operating income 20 20')]:
            for year in years:
                rid = f'{source}-{metric}-{year}'
                record = {'record_id': rid, 'source_snapshot_id': source, 'entity_id': company,
                    'metric_id': metric, 'value_decimal': '20000000', 'unit': 'USD',
                    'period': {'kind': 'year', 'start': f'{year}-01-01', 'end': f'{year}-12-31'},
                    'dimensions': {}}
                records.append({'record': record, 'record_sha256': digest(record)})
                start = text.rindex(row)
                anchors[rid] = {'status': 'located', 'source_snapshot_id': source, 'block_id': 'financial-table',
                    'start': start, 'end': start+len(row), 'text': row, 'kind': 'table_row'}
        packet = {'schema_version': 'semantic-review-input-v2', 'source_origin': 'synthetic_fixture',
            'scope': {'execution_schema_version': 'research-execution-v1', 'snapshot_id': source+'-snapshot',
                'company_ids': [company], 'source_snapshot_ids': [source], 'source_policy_id': 'local-frozen-v1',
                'knowledge_cutoff': f'{max(years)+1}-03-01', 'include_candidates': True},
            'source': {'source_snapshot_id': source, 'company_id': company,
                'source_sha256': digest((text+'\n'+detail).encode()), 'source_url': 'https://example.invalid/'+source},
            'records': records, 'record_anchors': anchors, 'source_blocks': blocks,
            'metric_definitions': {'revenue': {'definition': 'Revenue in USD.'},
                                   'operating_income': {'definition': 'Operating income in USD.'}},
            'axes': ['dimensions', 'value'],
            'assertions': [{'assertion_id': 'all-values', 'record_ids': list(anchors),
                            'text': 'All four selected consolidated values are USD 20 million in their displayed periods.'}],
            'selection_warnings': [], 'output_schema': SemanticAssessmentV2.model_json_schema()}
        packet['context_inventory'] = build_context_inventory(packet)
        return self.seal(packet)

    def citation(self, packet, quote, *, first=False, block_id='financial-table'):
        block = next(b for b in packet['source_blocks'] if b['block_id'] == block_id)
        return {'source_snapshot_id': block['source_snapshot_id'], 'block_id': block_id, 'quote': quote,
                'source_start': block['text'].find(quote) if first else block['text'].rfind(quote)}

    def response(self, packet):
        rows = [self.citation(packet, row) for row in ('Revenue 20 20', 'Operating income 20 20')]
        constraint = {'record_ids': list(packet['record_anchors']), 'statement': 'Selected rows show consolidated annual values.',
                      'citations': rows}
        return {'packet_id': packet['packet_id'],
            'checks': [{'axis': axis, 'status': 'constraints_found', 'reason': 'The row coverage is explicit.',
                        'constraints': [deepcopy(constraint)], 'unresolved_questions': []} for axis in packet['axes']],
            'assertions': [{'assertion_id': 'all-values', 'verdict': 'supported',
                'reason': 'All selected displayed rows are cited.', 'citations': deepcopy(rows)}],
            'context_claims': [{'object_id': o['object_id'], 'status': o['status']}
                               for o in packet['context_inventory']['objects']], 'context_requests': []}

    def test_complete_rows_cover_both_metrics_and_multiple_periods(self):
        for source, years in [('birch-annual-a', (2025, 2024)), ('birch-annual-b', (2023, 2022))]:
            with self.subTest(source=source):
                packet = self.packet(source, years)
                result = validate_semantic_assessment(packet, self.response(packet))
                self.assertEqual(len(result['checks']), 2)
                self.assertEqual(result['assertions'][0]['verdict'], 'supported')

    def test_missing_profit_row_is_rejected_even_with_all_four_record_ids(self):
        packet = self.packet()
        for axis in ('dimensions', 'value'):
            response = self.response(packet)
            next(c for c in response['checks'] if c['axis'] == axis)['constraints'][0]['citations'].pop()
            with self.subTest(axis=axis), self.assertRaises(ValueError):
                validate_semantic_assessment(packet, response)

    def test_supported_assertion_requires_profit_row_and_complete_rows_pass(self):
        packet = self.packet(); response = self.response(packet)
        response['assertions'][0]['citations'].pop()
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)
        complete = self.response(packet)
        result = validate_semantic_assessment(packet, complete)
        self.assertEqual(result['assertions'][0]['verdict'], 'supported')

    def test_contradicted_assertion_can_cite_one_disproving_record(self):
        packet = self.packet()
        packet['assertions'][0]['text'] = 'All four selected annual values are USD 99 million.'
        self.seal(packet)
        response = self.response(packet)
        response['assertions'][0].update(verdict='contradicted',
            reason='The cited revenue row alone disproves the universal USD 99 million assertion.')
        response['assertions'][0]['citations'].pop()
        result = validate_semantic_assessment(packet, response)
        self.assertEqual(result['assertions'][0]['verdict'], 'contradicted')

    def test_duplicate_revenue_quote_does_not_cover_profit_with_same_numeric_values(self):
        packet = self.packet(); response = self.response(packet)
        constraint = response['checks'][0]['constraints'][0]
        constraint['citations'] = [constraint['citations'][0], deepcopy(constraint['citations'][0])]
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_exact_same_text_at_wrong_occurrence_is_not_record_evidence(self):
        packet = self.packet(); response = self.response(packet)
        wrong = self.citation(packet, 'Revenue 20 20', first=True)
        self.assertNotEqual(wrong['source_start'], response['checks'][0]['constraints'][0]['citations'][0]['source_start'])
        response['checks'][0]['constraints'][0]['citations'][0] = wrong
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_unique_quote_without_offset_is_located_without_mutating_raw_response(self):
        packet = self.packet(); response = self.response(packet)
        for check in response['checks']:
            check['constraints'][0]['citations'][1].pop('source_start')
        response['assertions'][0]['citations'][1].pop('source_start')
        original = deepcopy(response)
        result = validate_semantic_assessment(packet, response)
        expected_start = packet['source_blocks'][0]['text'].index('Operating income 20 20')
        for check in result['checks']:
            self.assertEqual(check['constraints'][0]['citations'][1]['source_start'], expected_start)
        self.assertEqual(result['assertions'][0]['citations'][1]['source_start'], expected_start)
        self.assertEqual(response, original)

    def test_repeated_quote_without_offset_is_ambiguous_and_rejected(self):
        packet = self.packet(); response = self.response(packet)
        response['checks'][0]['constraints'][0]['citations'][0].pop('source_start')
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_bare_repeated_number_and_noncharacter_offset_are_rejected(self):
        packet = self.packet()
        for mode in ('number', 'byte-offset', 'boolean-offset'):
            response = self.response(packet); citations = response['checks'][0]['constraints'][0]['citations']
            if mode == 'number': citations[0] = self.citation(packet, '20')
            elif mode == 'byte-offset':
                text = packet['source_blocks'][0]['text']; start = citations[0]['source_start']
                citations[0]['source_start'] = len(text[:start].encode('utf-8'))
            else: citations[0]['source_start'] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_same_text_from_other_source_cannot_support_selected_source(self):
        packet = self.packet(); other = self.packet('birch-annual-b', (2023, 2022))
        response = self.response(packet)
        response['checks'][0]['constraints'][0]['citations'][0] = self.citation(other, 'Revenue 20 20')
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_supplied_detail_cannot_be_claimed_missing_even_when_response_cites_it(self):
        packet = self.packet(); response = self.response(packet)
        detail = next(o for o in packet['context_inventory']['objects']
                      if o['kind'] == 'source_block' and o['block_id'] == 'note-1-detail')
        response['checks'][0]['constraints'][0]['citations'].append(self.citation(packet,
            'Prior-period segment information was recast.', block_id='note-1-detail'))
        response['context_claims'] = [{'object_id': detail['object_id'], 'status': 'not_supplied'}]
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_unresolved_reference_does_not_prove_note_missing(self):
        packet = self.packet()
        reference = next(o for o in packet['context_inventory']['objects'] if o['kind'] == 'source_reference')
        for status in ('not_supplied', 'supplied'):
            response = self.response(packet)
            response['context_claims'] = [{'object_id': reference['object_id'], 'status': status}]
            with self.subTest(status=status), self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_full_note_question_remains_a_request_not_missing_material_fact(self):
        packet = self.packet(); response = self.response(packet)
        references = [o['object_id'] for o in packet['context_inventory']['objects'] if o['kind'] == 'source_reference']
        response['context_requests'] = [{'question': 'Would the full referenced Note 4 add allocation detail beyond this supplied excerpt?',
            'reviewed_block_ids': ['note-1-detail'], 'reference_ids': references}]
        result = validate_semantic_assessment(packet, response)
        self.assertEqual(len(result['context_requests']), 1)
        self.assertFalse(any(c['status'] == 'not_supplied' for c in result['context_claims']))

    def test_context_request_and_claim_ids_cannot_cross_source_or_invent_objects(self):
        packet = self.packet(); other = self.packet('birch-annual-b', (2023, 2022))
        foreign = other['context_inventory']['objects'][0]['object_id']
        for mode in ('foreign-claim', 'invented-claim', 'unknown-reviewed-block', 'unknown-reference'):
            response = self.response(packet)
            if mode.endswith('claim'):
                response['context_claims'] = [{'object_id': foreign if mode == 'foreign-claim' else 'absent-note', 'status': 'supplied'}]
            else:
                response['context_requests'] = [{'question': 'Please clarify this source.',
                    'reviewed_block_ids': ['unknown'] if mode == 'unknown-reviewed-block' else ['note-1-detail'],
                    'reference_ids': ['unknown'] if mode == 'unknown-reference' else []}]
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_assessment(packet, response)

    def test_inventory_cannot_be_resealed_with_a_false_delivery_status(self):
        packet = self.packet()
        packet['context_inventory']['objects'][0]['status'] = 'not_supplied'
        self.seal(packet)
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, self.response(packet))

    def test_old_free_missing_statement_and_old_input_gap_fields_are_rejected(self):
        packet = self.packet(); response = self.response(packet)
        response['limitations'] = ['Note 1 detailed explanation was not supplied.']
        with self.assertRaises(ValueError): validate_semantic_assessment(packet, response)
        for field, value in [('context_gaps', []), ('unresolved_note_references', []), ('context_completeness', 'missing')]:
            changed = deepcopy(packet); changed[field] = value; self.seal(changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_semantic_assessment(changed, self.response(changed))


if __name__ == '__main__': unittest.main()
