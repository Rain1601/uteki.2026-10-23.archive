"""Only frozen layout labels may be removed from automatic table attachments."""
import json
from pathlib import Path
import unittest

from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_selected_originals_v2 as fixtures
from tests.unit.test_bounded_answer_handoff import narrow_assessment
from tests.unit.test_task_completion import pin_dataset


class SelectedOriginalsV3Tests(unittest.TestCase):
    run_selection = fixtures.SelectedOriginalsV2Tests.run_selection
    prepare = fixtures.SelectedOriginalsV2Tests.prepare

    def setUp(self):
        fixtures.SelectedOriginalsV2Tests.setUp(self)
        self.blocks = list(map(json.loads, (self.folder/'blocks.jsonl').read_text().splitlines()))
        self.blocks[8].update(type='heading_candidate', text='CONSOLIDATED RESULTS')
        self.blocks[9].update(type='heading_candidate', text='Annual report', layout_role='running_header')
        self.blocks[10].update(type='page_marker', text='13', layout_role='reported_page_number')
        self.save_blocks()

    def save_blocks(self):
        for block in self.blocks:
            block['text_hash'] = digest(block['text'].encode())
        path = self.folder/'blocks.jsonl';path.write_text(''.join(json.dumps(b)+'\n' for b in self.blocks))
        manifest_path = self.folder/'manifest.json';manifest = json.loads(manifest_path.read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest));pin_dataset(self.dataset)

    def test_v3_filters_only_automatic_layout_and_retains_title_unit_table_footnote(self):
        output = self.run_selection(['b12'], ['b12'], version='selected-originals-v3')
        packet = self.prepare(output);document = packet['source_documents'][0]
        self.assertEqual([b['block_id'] for b in document['blocks']], ['b8','b11','b12','b13'])
        group, = document['reading_groups']
        self.assertEqual(group['excluded_layout_blocks'], [
            {'block_id':'b9','layout_role':'running_header','reason':'frozen_running_header'},
            {'block_id':'b10','layout_role':'reported_page_number','reason':'frozen_reported_page_number'}])
        self.assertEqual(group['required_block_ids'], ['b8','b11','b12','b13'])
        self.assertTrue(group['all_required_blocks_delivered'])
        self.assertEqual(group['missing_context_block_ids'], [])
        self.assertFalse(group['all_group_blocks_delivered'])
        self.assertEqual([f['value']['block_id'] for f in packet['facts']], ['b12'])
        self.assertNotIn('original_block', packet['facts'][0]['citations'][0])
        response = narrow_assessment(packet)
        for fact in response['facts']:fact['relevance']='necessary'
        response['body_checks']=[{'source_snapshot_id':d['source_snapshot_id'],'block_id':b['block_id'],
            'relevance':'supporting_context','rationale':'Original supporting material.'}
            for d in packet['source_documents'] for b in d['blocks']]
        self.assertTrue(validate_assessment(packet,response)[1])
        response['body_checks'].pop()
        with self.assertRaisesRegex(ValueError,'every delivered source body'):
            validate_assessment(packet,response)

    def test_v2_rebuild_keeps_historical_automatic_layout_expansion(self):
        output = self.run_selection(['b12'], ['b12'])
        first = self.prepare(output)
        self.assertEqual([b['block_id'] for b in first['source_documents'][0]['blocks']],
                         ['b8','b9','b10','b11','b12','b13'])
        self.assertEqual(first['source_documents'][0]['reading_groups'], [])
        self.assertEqual(digest(first), digest(self.prepare(output)))
        self.assertNotIn('excluded_layout_blocks', json.dumps(first))

    def test_explicitly_selected_running_header_is_preserved(self):
        output = self.run_selection(['b12'], ['b12','b9'], version='selected-originals-v3')
        document = self.prepare(output)['source_documents'][0]
        self.assertIn('b9', [b['block_id'] for b in document['blocks']])
        self.assertEqual([e['block_id'] for e in document['reading_groups'][0]['excluded_layout_blocks']], ['b10'])

    def test_unmarked_short_header_and_unknown_role_are_not_guessed_away(self):
        self.blocks[9].pop('layout_role');self.blocks[9]['text']='X'
        self.blocks[10].update(type='heading_candidate',layout_role='unknown_future_role',text='Required title')
        self.save_blocks()
        output = self.run_selection(['b12'], ['b12'], version='selected-originals-v3')
        document = self.prepare(output)['source_documents'][0]
        self.assertTrue({'b9','b10','b13'} <= {b['block_id'] for b in document['blocks']})
        self.assertEqual(document['reading_groups'][0]['excluded_layout_blocks'], [])


class FrozenV2CompatibilityTests(unittest.TestCase):
    def test_existing_sealed_v2_model_review_inputs_rebuild_identically(self):
        root = Path(__file__).resolve().parents[2]/'experiments/agent_design/2026-10-09-data-agent-completion-v1'
        paths = sorted(root.glob('runs/*/attempt-*/review-*/input.json'))
        checked = 0
        for path in paths:
            original = json.loads(path.read_text())
            if original.get('delivery_schema_version') != 'selected-originals-v2':continue
            if not Path(original['query_ref']['path']).exists():continue
            before = path.read_bytes()
            rebuilt = prepare_review_packet(original['query_ref']['path'], original['dataset_ref']['path'],
                expected_scope=original['scope'], max_packet_bytes=original['max_packet_bytes'],
                source_delivery=original['source_delivery'])
            self.assertEqual(rebuilt, original, str(path))
            self.assertEqual(digest(rebuilt), digest(original))
            self.assertEqual(path.read_bytes(),before)
            checked += 1
        if not checked:self.skipTest('Original absolute-path frozen v2 fixtures unavailable')


if __name__ == '__main__':unittest.main()
