"""Missing original-record selections remain reviewable gaps, never implicit delivery."""
from copy import deepcopy
import json
import unittest

from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from tests.unit import test_analysis_record_selection as fixtures
from tests.unit.test_task_completion import pin_dataset


class MissingRecordDeliveryTests(unittest.TestCase):
    setUp = fixtures.AnalysisRecordSelectionTests.setUp
    run_actions = fixtures.AnalysisRecordSelectionTests.run_actions
    select = fixtures.AnalysisRecordSelectionTests.select

    def prepare(self):
        return prepare_review_packet(self.root/'run', self.dataset, expected_scope=self.scope,
            max_packet_bytes=128000, source_delivery='query_evidence_v1')

    def rewrite(self, result):
        (self.root/'run/result.json').write_text(json.dumps(result))
        pin_dataset(self.root/'run')

    def assert_reviewable_gap(self, packet):
        self.assertEqual(packet['facts'], [])
        self.assertEqual(packet['source_documents'], [])
        self.assertIn('record_delivery_selection_missing:revenue', packet['program_gaps'])
        response = {'packet_id': packet['packet_id'], 'facts': [], 'body_checks': [],
            'requirements': [{'requirement_id': 'revenue', 'verdict': 'insufficient_evidence',
                'rationale': 'No original revenue record was selected for delivery.', 'citations': []}],
            'source_checks': [{'source_snapshot_id': 'acme-annual',
                'verdict': 'requires_more_source_content',
                'rationale': 'No original body was delivered.', 'citations': []}],
            'question_coverage': 'incomplete', 'coverage_reason': 'Requested record is unavailable.',
            'missing_information': ['Original revenue record for the requested period.'],
            'limitations': ['Offline synthetic check.']}
        self.assertFalse(validate_assessment(packet, response)[1])

    def test_nonexistent_period_query_gap_finish_can_be_reviewed(self):
        self.request['question'] = 'Retrieve original revenue for 2029.'
        records = [fixtures.criterion(2029)]
        result, _ = self.run_actions([fixtures.plan(records), fixtures.query(records),
            {'action': 'gap', 'requirement_ids': ['revenue'],
             'reason': 'The selected frozen source has no revenue for 2029.'}, {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial', result['trace'])
        self.assertTrue(result['gaps'])
        self.assertEqual(result['coverage'][0]['selected_record_ids'], [])
        packet = self.prepare()
        self.assertEqual(packet['query_gaps'], result['gaps'])
        self.assert_reviewable_gap(packet)

    def test_queried_but_unselected_records_do_not_leak_from_limited_run(self):
        records = [fixtures.criterion()]
        result, _ = self.run_actions([fixtures.plan(records), fixtures.query(records)])
        self.assertEqual(result['status'], 'limited')
        self.assertTrue(result['coverage'][0]['evidence_ids'])
        self.assert_reviewable_gap(self.prepare())

    def test_missing_field_and_false_ready_status_still_deliver_no_records(self):
        records = [fixtures.criterion()]
        result, _ = self.run_actions([fixtures.plan(records), fixtures.query(records)])
        del result['coverage'][0]['selected_record_ids']
        result['coverage'][0]['program_check'] = 'satisfied'
        result['status'] = 'evidence_ready'
        self.rewrite(result)
        self.assert_reviewable_gap(self.prepare())

    def test_malformed_duplicate_and_unqueried_selections_are_rejected(self):
        records = [fixtures.criterion()]
        result, _ = self.run_actions([fixtures.plan(records), fixtures.query(records),
                                     self.select(), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready')
        selected = result['coverage'][0]['selected_record_ids'][0]
        for invalid in (None, selected, {}, [{}], [selected, selected], ['ev-foreign']):
            with self.subTest(selection=invalid):
                changed = deepcopy(result)
                changed['coverage'][0]['selected_record_ids'] = invalid
                self.rewrite(changed)
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_legacy_v1_still_delivers_queried_records_without_selection(self):
        records = [fixtures.criterion()]
        result, _ = self.run_actions([fixtures.plan(records), fixtures.query(records)])
        result['delivery_schema_version'] = 'selected-originals-v1'
        # Legacy numeric runs predate analysis_evidence's strict original DOM locator.
        result.pop('purpose', None)
        del result['coverage'][0]['selected_record_ids']
        self.rewrite(result)
        packet = self.prepare()
        self.assertEqual(len(packet['facts']), 2)  # Two preserved original disclosures.
        self.assertTrue(packet['source_documents'])
        self.assertNotIn('record_delivery_selection_missing:revenue', packet['program_gaps'])


if __name__ == '__main__':
    unittest.main()
