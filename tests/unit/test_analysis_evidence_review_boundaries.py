"""Independent regression cases for allowed Data plans entering content review."""
import asyncio

from tests.unit.test_exact_record_handoff import pin_originals_for_synthetic_records
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit import test_answer_handoff_records as record_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_scoped_query_service import year


class AnalysisEvidenceReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        record_fixtures.AnswerHandoffRecordTests.setUp(self)
        pin_originals_for_synthetic_records(self.dataset)

    def run_actions(self, actions, question):
        output = self.root/'query'
        planner = ScriptedPlanner(actions)
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                limits={'max_steps':len(actions), 'max_packet_bytes':64000}).run(
                    {'question':question, 'scope':self.scope.model_dump(mode='json')}, output=output))
        return result, output

    def test_mixed_selected_source_and_complete_node_have_reviewable_originals(self):
        plan = source_plan()
        plan['requirements'].append({'kind':'read_node', 'requirement_id':'notes',
            'description':'Read original notes', 'source_id':'acme-annual', 'node_id':'notes'})
        result, output = self.run_actions([plan, context_read(), choose('b1'),
            context_read(block='b8',requirement='notes'), {'action':'finish'}],
            'Retrieve product description and notes in 2031.')
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        packet = prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'],[])
        blocks = {b['block_id'] for d in packet['source_documents'] for b in d['blocks']}
        self.assertTrue({'b1','b7','b8','b9'} <= blocks)
        self.assertEqual({r for fact in packet['facts'] for r in fact['requirement_ids']}, {'business','notes'})

    def test_explored_record_attached_to_source_requirement_remains_audit_only(self):
        query = {'records':[{'entity_id':'acme-services','metric_id':'revenue','period':year(2031)}]}
        result, output = self.run_actions([source_plan(),
            {'action':'query','requirement_ids':['business'],'plan':query},
            context_read(),choose('b1'),{'action':'finish'}], 'Retrieve the original product description in 2031.')
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertTrue(any(i['kind']=='record' for i in load_evidence_bundle(output)['items']))
        packet = prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')
        self.assertEqual({f['kind'] for f in packet['facts']},{'source_block'})
        self.assertEqual({b['block_id'] for d in packet['source_documents'] for b in d['blocks']},{'b1'})

    def test_read_node_exploration_outside_required_blocks_is_not_delivered(self):
        plan = {'action':'plan','reason':'Read notes only.','requirements':[{'kind':'read_node',
            'requirement_id':'notes','description':'Read original notes','source_id':'acme-annual','node_id':'notes'}]}
        plan['requirements'] += source_plan()['requirements']
        result, output = self.run_actions([plan,context_read(),choose('b1'),context_read(block='b8',requirement='notes'),
            context_read(block='b2',requirement='notes'),{'action':'finish'}], 'Retrieve original financial notes.')
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        bundle = load_evidence_bundle(output)
        self.assertTrue(any('b2' in ids for ids in bundle['delivered_body'].values()))
        self.assertEqual(set(result['coverage'][0]['required_block_ids']),{'b7','b8','b9'})
        packet = prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'],[])
        self.assertEqual({b['block_id'] for d in packet['source_documents'] for b in d['blocks']},{'b1','b7','b8','b9'})
        self.assertEqual({f['value']['block_id'] for f in packet['facts']},{'b1','b7','b8','b9'})

    def test_calculation_is_rejected_before_execution_and_agent_can_replan_to_operands(self):
        calculation = {'calculations':[{'formula_id':'operating_margin','entity_id':'acme-services',
                                       'periods':[year(2031)]}]}
        records = {'records':[{'entity_id':'acme-services','metric_id':metric,'period':year(2031)}
                              for metric in ('revenue','operating_income')]}
        def plan(payload):
            return {'action':'plan','reason':'Retrieve supported source operands for Analysis.',
                'requirements':[{'kind':'query','requirement_id':'operands',
                    'description':'Reported operating margin operands for 2031','query':payload}]}
        actions = [plan(calculation), plan(records),
            {'action':'query','requirement_ids':['operands'],'plan':calculation},
            {'action':'query','requirement_ids':['operands'],'plan':records},
            lambda packet: {'action':'select_records','requirement_ids':['operands'],
                'record_selection':{'record_ids':packet['observation']['evidence_ids']},
                'reason':'Retain both original operands for Analysis.'}, {'action':'finish'}]
        result, output = self.run_actions(actions,'Retrieve operating margin evidence for Acme services in 2031.')
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertEqual([result['trace'][n]['status'] for n in (0,2)], ['rejected','rejected'])
        self.assertFalse((output/'turn-003/query-receipt.json').exists())
        packet = prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'],[])
        self.assertEqual({f['value']['metric_id'] for f in packet['facts']}, {'revenue','operating_income'})
        self.assertTrue(all(f['kind']=='record' for f in packet['facts']))


if __name__ == '__main__':
    unittest.main()
