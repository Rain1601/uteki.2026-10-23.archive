"""Exact selected prose and bounded structural context; synthetic runtime, no API."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit import test_answer_handoff as fixtures
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit.test_bounded_answer_handoff import narrow_assessment
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_task_completion import pin_dataset


class SelectedOriginalsV2Tests(unittest.TestCase):
    def setUp(self):
        fixtures.AnswerHandoffTests.setUp(self)
        self.folder = self.dataset / 'indexes/acme-annual'
        texts = [
            ('heading_candidate', 'Business'),
            ('heading_candidate', 'Primary segment'),
            ('paragraph', 'This segment primarily includes:'),
            ('list_item', '• Product alpha.'), ('list_item', '• Product beta.'),
            ('page_marker', '12'), ('heading_candidate', 'Annual report'),
            ('heading_candidate', 'Detailed demand drivers'),
            ('paragraph', 'Demand is affected by:'),
            ('list_item', '• Unrelated seasonal driver.'),
            ('list_item', '• Unrelated regional driver.'),
            ('heading_candidate', 'Amounts in millions'),
            ('table', 'Revenue 25'), ('paragraph', '(1) Includes unsettled items.'),
        ]
        blocks = [{'block_id': f'b{i}', 'ordinal': i + 1, 'type': kind, 'text': text,
            'text_hash': digest(text.encode()), 'reported_page': 1,
            'dom_path': f'/html/body/div[{i+1}]', 'table': None}
            for i, (kind, text) in enumerate(texts)]
        blocks[5]['layout_role'] = 'reported_page_number'
        blocks[6]['layout_role'] = 'running_header'
        blocks[12]['table'] = {'cells': [
            {'row': 0, 'column': 0, 'text': 'Revenue', 'rowspan': 1, 'colspan': 1},
            {'row': 0, 'column': 1, 'text': '25', 'rowspan': 1, 'colspan': 1}]}
        (self.folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in blocks))
        path = self.folder/'index.json';index = json.loads(path.read_text())
        index['nodes'] = [{'node_id': 'root', 'kind': 'document', 'title': 'Document',
            'start_block_id': 'b0', 'end_block_id': 'b13'},
            {'node_id': 'business', 'kind': 'item', 'title': 'Business',
             'start_block_id': 'b0', 'end_block_id': 'b13'}]
        path.write_text(json.dumps(index))
        path = self.folder/'manifest.json';manifest = json.loads(path.read_text())
        for name in ('index.json', 'blocks.jsonl'):
            manifest['artifacts'][name]['sha256'] = digest((self.folder/name).read_bytes())
        path.write_text(json.dumps(manifest));pin_dataset(self.dataset)

    def run_selection(self, reads, selected, *, version='selected-originals-v2', name='query'):
        actions = [source_plan(), *[context_read(block=bid) for bid in reads],
                   choose(*selected), {'action': 'finish'}]
        output = self.root/name
        with QueryDataPort(self.dataset) as owner, patch(
                'uteki.agents.data_query.autonomous.ANALYSIS_EVIDENCE_DELIVERY_VERSION', version):
            result = asyncio.run(AutonomousDataAgent(owner, ScriptedPlanner(actions),
                purpose='analysis_evidence', limits={'max_steps':len(actions),
                'max_packet_bytes':100000,'observation_bytes':40000}).run(self.request, output=output))
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['delivery_schema_version'], version)
        return output

    def prepare(self, output):
        return prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')

    def test_next_heading_does_not_deliver_following_list_and_closure_skips_layout(self):
        output=self.run_selection(['b3','b7'],['b1','b2','b3','b4','b7'])
        packet=self.prepare(output);doc=packet['source_documents'][0]
        self.assertEqual([b['block_id'] for b in doc['blocks']],['b1','b2','b3','b4','b7'])
        group,=doc['reading_groups']
        self.assertTrue(group['all_item_bodies_delivered'])
        self.assertEqual(group['missing_item_body_ids'],[])
        self.assertEqual(group['closure']['skipped_layout_block_ids'],['b5','b6'])
        self.assertEqual(group['closure']['following_block']['block_id'],'b7')
        self.assertEqual(group['closure']['semantic_completeness'],'not_evaluated')
        self.assertEqual(group['validation'],'recomputed_from_frozen_index')
        self.assertNotIn('original_block',packet['facts'][0]['citations'][0])

    def test_partial_list_selection_does_not_claim_every_item_delivered(self):
        output=self.run_selection(['b3'],['b2','b3'])
        doc=self.prepare(output)['source_documents'][0]
        self.assertEqual([b['block_id'] for b in doc['blocks']],['b2','b3'])
        group,=doc['reading_groups']
        self.assertFalse(group['all_item_bodies_delivered'])
        self.assertEqual(group['missing_item_body_ids'],['b4'])

    def test_selected_table_keeps_unit_and_note_attachments(self):
        output=self.run_selection(['b12'],['b12'])
        packet=self.prepare(output)
        self.assertEqual([b['block_id'] for b in packet['source_documents'][0]['blocks']],['b11','b12','b13'])
        self.assertEqual([f['value']['block_id'] for f in packet['facts']],['b12'])

    def test_legacy_v1_marker_retains_historical_atomic_expansion(self):
        output=self.run_selection(['b7'],['b7'])
        path=output/'result.json';result=json.loads(path.read_text())
        result['delivery_schema_version']='selected-originals-v1'
        path.write_text(json.dumps(result));pin_dataset(output)
        packet=self.prepare(output);doc=packet['source_documents'][0]
        self.assertEqual([b['block_id'] for b in doc['blocks']],['b7','b8','b9','b10'])
        self.assertNotIn('reading_groups',doc)
        self.assertEqual(packet['delivery_schema_version'],'selected-originals-v1')

    def test_review_must_cover_unselected_table_attachments_and_reject_redundancy(self):
        output=self.run_selection(['b12'],['b12'])
        packet=self.prepare(output)
        response=narrow_assessment(packet)
        for fact in response['facts']:
            fact['relevance']='necessary'
        response['body_checks']=[{'source_snapshot_id':'acme-annual','block_id':bid,
            'relevance':'necessary' if bid=='b12' else 'supporting_context',
            'rationale':'Original table or required unit/footnote context.'}
            for bid in ['b11','b12','b13']]
        self.assertTrue(validate_assessment(packet,response)[1])
        missing=deepcopy(response);missing['body_checks'].pop()
        with self.assertRaisesRegex(ValueError,'every delivered source body'):
            validate_assessment(packet,missing)
        duplicate=deepcopy(response);duplicate['body_checks'].append(duplicate['body_checks'][0])
        with self.assertRaisesRegex(ValueError,'every delivered source body'):
            validate_assessment(packet,duplicate)
        irrelevant=deepcopy(response);irrelevant['body_checks'][0]['relevance']='irrelevant'
        self.assertFalse(validate_assessment(packet,irrelevant)[1])
        redundant=deepcopy(response);redundant['body_checks'][0]['relevance']='redundant'
        self.assertFalse(validate_assessment(packet,redundant)[1])


if __name__=='__main__':unittest.main()
