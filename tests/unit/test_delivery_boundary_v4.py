"""Final delivery differs from exploratory reading; synthetic offline runtime."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit import test_analysis_record_selection as records
from tests.unit import test_record_origins as origins
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import context_read, source_plan
from tests.unit.test_exact_record_handoff import pin_originals_for_synthetic_records


class DeliveryBoundaryV4Tests(unittest.TestCase):
    setUp = origins.RecordOriginsTests.setUp
    change_duplicate_origin = origins.RecordOriginsTests.change_duplicate_origin

    def run_delivery(self, actions, *, version='selected-originals-v4', name='run'):
        pin_originals_for_synthetic_records(self.dataset)
        output = self.root/name
        planner = ScriptedPlanner(actions)
        with QueryDataPort(self.dataset) as port, patch(
                'uteki.agents.data_query.autonomous.ANALYSIS_EVIDENCE_DELIVERY_VERSION', version):
            result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                limits={'max_steps': len(actions), 'max_packet_bytes': 128000,
                        'observation_bytes': 32000}).run(self.request, output=output))
        return result, planner, output

    def prepare(self, output):
        return prepare_review_packet(output, self.dataset, expected_scope=self.scope,
            max_packet_bytes=500000, source_delivery='query_evidence_v1')

    def select_occurrence(self, block='b8'):
        def select(packet):
            candidates = packet['record_origins']['items']
            selected = next(row for row in candidates
                if any(citation['block_id'] == block for citation in row['citations']))
            return {'action': 'select_records', 'requirement_ids': ['revenue'],
                'record_selection': {'record_ids': [selected['evidence_id']]},
                'reason': 'Use the queried original occurrence for this explicit criterion.'}
        return select

    @staticmethod
    def actual_blocks(packet):
        return {(document['source_snapshot_id'], block['block_id'])
            for document in packet['source_documents'] for block in document['blocks']}

    def assert_preview_matches(self, planner, packet):
        preview = planner.packets[-1]['record_selection_effect']
        self.assertTrue(preview['complete'])
        self.assertTrue(preview['navigation_only'])
        self.assertFalse(preview['source_body_reading_established'])
        projected = {(row['source_snapshot_id'], block_id)
            for row in preview['value']['delivery_block_ids'] for block_id in row['block_ids']}
        self.assertEqual(projected, self.actual_blocks(packet))

    def numeric_exploration(self):
        criteria = [records.criterion()]
        return [records.plan(criteria), records.query(criteria),
            context_read(block='b1', requirement='revenue'), self.select_occurrence(),
            {'action': 'finish'}]

    def test_numeric_exploration_stays_in_audit_but_does_not_enter_delivery(self):
        self.change_duplicate_origin()
        result, planner, output = self.run_delivery(self.numeric_exploration())
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        packet = self.prepare(output)
        self.assertEqual(packet['delivery_schema_version'], 'selected-originals-v4')
        self.assertEqual(self.actual_blocks(packet),
            {('acme-annual', bid) for bid in ('b7', 'b8', 'b9')})
        self.assertEqual(len(packet['facts']), 1)
        self.assertEqual(packet['facts'][0]['citations'][0]['block_id'], 'b8')
        bundle = load_evidence_bundle(output)
        self.assertTrue(any('b1' in body for body in bundle['delivered_body'].values()))
        self.assertTrue(any(item['block_id'] == 'b1' for item in planner.packets[-1]['retained_body']['items']))
        self.assertEqual(packet['program_gaps'], [])
        self.assert_preview_matches(planner, packet)

    def test_explicit_source_requirement_keeps_the_selected_additional_body(self):
        self.change_duplicate_origin()
        criteria = [records.criterion()]
        plan = records.plan(criteria)
        plan['requirements'] += source_plan()['requirements']
        result, planner, output = self.run_delivery([plan, records.query(criteria),
            context_read(block='b1'), choose('b1'), self.select_occurrence(), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        packet = self.prepare(output)
        self.assertEqual(self.actual_blocks(packet),
            {('acme-annual', bid) for bid in ('b1', 'b7', 'b8', 'b9')})
        body_facts = [fact for fact in packet['facts'] if fact['kind'] == 'source_block']
        self.assertEqual([fact['value']['block_id'] for fact in body_facts], ['b1'])
        self.assertEqual(packet['program_gaps'], [])
        self.assert_preview_matches(planner, packet)

    def test_historical_v3_keeps_its_original_exploration_expansion(self):
        self.change_duplicate_origin()
        result, _, output = self.run_delivery(self.numeric_exploration(), version='selected-originals-v3')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        original = self.prepare(output)
        self.assertEqual(self.actual_blocks(original),
            {('acme-annual', bid) for bid in ('b1', 'b7', 'b8', 'b9')})
        self.assertEqual(original, self.prepare(output))
        self.assertEqual(original['delivery_schema_version'], 'selected-originals-v3')

    def test_declared_read_node_delivery_and_preview_match_its_required_bodies(self):
        self.change_duplicate_origin()
        self.scope['company_ids'].append('other')
        self.scope['source_snapshot_ids'].append('other-annual')
        self.request['scope'] = deepcopy(self.scope)
        criteria = [records.criterion()]
        plan = records.plan(criteria)
        plan['requirements'].append({'kind': 'read_node', 'requirement_id': 'exploration',
            'description': 'Deliver the selected Business chapter in addition to the numeric disclosure.',
            'source_id': 'acme-annual', 'node_id': 'business'})
        result, planner, output = self.run_delivery([plan, records.query(criteria),
            {'action': 'read_source', 'requirement_ids': ['exploration'],
             'read': {'source_snapshot_id': 'other-annual', 'node_id': 'business', 'count': 3}},
            {'action': 'read_source', 'requirement_ids': ['exploration'],
             'read': {'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'count': 3}},
            self.select_occurrence(),
            {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        packet = self.prepare(output)
        declaration = next(row for row in result['coverage'] if row['kind'] == 'read_node')
        declared = set(declaration['required_block_ids'])
        self.assertEqual(self.actual_blocks(packet),
            {('acme-annual', bid) for bid in declared | {'b7', 'b8', 'b9'}})
        self.assertTrue({'b1', 'b2'} <= declared)
        self.assert_preview_matches(planner, packet)

    def test_cross_company_body_cannot_be_selected_for_the_pinned_source(self):
        self.change_duplicate_origin()
        self.scope['company_ids'].append('other')
        self.scope['source_snapshot_ids'].append('other-annual')
        self.request['scope'] = deepcopy(self.scope)
        criteria = [records.criterion()]
        plan = records.plan(criteria)
        plan['requirements'] += source_plan()['requirements']
        def wrong(packet):
            item = next(item for item in packet['retained_body']['items']
                if item['source_snapshot_id'] == 'other-annual' and item['block_id'] == 'b1')
            return {'action': 'select_evidence', 'requirement_ids': ['business'],
                'delivery': {'blocks': [{'context_id': item['context_evidence_id'], 'block_id': 'b1'}]},
                'reason': 'Attempt another source with a colliding local block ID.'}
        result, _, output = self.run_delivery([plan, records.query(criteria),
            context_read(source='other-annual', block='b1'), wrong,
            context_read(block='b1'), choose('b1'), self.select_occurrence(), {'action': 'finish'}])
        self.assertEqual(result['trace'][3]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual({source for source, _ in self.actual_blocks(self.prepare(output))}, {'acme-annual'})

    def test_another_company_and_period_have_no_exploration_or_sample_fallback(self):
        cases = [('other', 'other-annual', 'other-services', 2031),
                 ('acme', 'acme-annual', 'acme-services', 2030)]
        for company, source, entity, year in cases:
            with self.subTest(company=company, year=year):
                self.scope = {**self.scope, 'company_ids': [company], 'source_snapshot_ids': [source]}
                self.request['scope'] = deepcopy(self.scope)
                criteria = [records.criterion(year, entity)]
                result, _, output = self.run_delivery([records.plan(criteria), records.query(criteria),
                    context_read(source=source, block='b1', requirement='revenue'),
                    self.select_occurrence('b9'), {'action': 'finish'}], name=f'{company}-{year}')
                self.assertEqual(result['status'], 'evidence_ready', result['trace'])
                packet = self.prepare(output)
                self.assertEqual(self.actual_blocks(packet), {(source, 'b9')})
                self.assertEqual(packet['facts'][0]['value']['entity_id'], entity)
                self.assertEqual(packet['facts'][0]['value']['period']['end'], f'{year}-12-31')


if __name__ == '__main__':
    unittest.main()
