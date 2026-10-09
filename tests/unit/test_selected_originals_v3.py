"""Only frozen layout labels may be removed from automatic table attachments."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort
from uteki.infrastructure.document_sources.sec_index import NAVIGATION_PARSERS
from tests.unit import test_selected_originals_v2 as fixtures
from tests.unit.test_bounded_answer_handoff import narrow_assessment
from tests.unit.test_task_completion import pin_dataset
from tests.unit import test_compact_answer_handoff as compact_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_analysis_evidence_runtime import choose


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
        with self.assertRaisesRegex(ValueError,'body_checks_identity_mismatch'):
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


class NavigationFilteredTableHandoffTests(unittest.TestCase):
    save_blocks = SelectedOriginalsV3Tests.save_blocks
    prepare = fixtures.SelectedOriginalsV2Tests.prepare
    reseal_context = compact_fixtures.CompactAnswerHandoffTests.reseal_context

    def setUp(self):
        SelectedOriginalsV3Tests.setUp(self)
        self.blocks[9].update(text='Table of Contents', layout_role='repeated_navigation')
        self.save_blocks()
        path=self.folder/'index.json';index=json.loads(path.read_text())
        index['parser_version']=sorted(NAVIGATION_PARSERS)[0]
        path.write_text(json.dumps(index))
        manifest_path=self.folder/'manifest.json';manifest=json.loads(manifest_path.read_text())
        manifest['artifacts']['index.json']['sha256']=digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest));pin_dataset(self.dataset)

    def run_table(self, representation, name):
        action=context_read(block='b12');action['context']['representation']=representation
        actions=[source_plan(),action,choose('b12'),{'action':'finish'}]
        output=self.root/name
        with QueryDataPort(self.dataset) as owner:
            result=asyncio.run(AutonomousDataAgent(owner,ScriptedPlanner(actions),purpose='analysis_evidence',
                limits={'max_steps':4,'max_packet_bytes':100000,'observation_bytes':40000}).run(
                    self.request,output=output))
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        return output

    def test_full_and_compact_filtered_navigation_roundtrip_preserves_table_and_context(self):
        packets=[]
        for representation in ('full','compact'):
            output=self.run_table(representation,representation)
            packet=self.prepare(output);packets.append(packet)
            document=packet['source_documents'][0]
            self.assertEqual([b['block_id'] for b in document['blocks']],['b8','b11','b12','b13'])
            table=next(b['table'] for b in document['blocks'] if b['block_id']=='b12')
            decoded=[dict(zip(table['cell_fields'],cell)) for cell in table['cells']]
            self.assertEqual(decoded,self.blocks[12]['table']['cells'])
            group,=document['reading_groups']
            self.assertIn('b9',group['block_ids'])
            self.assertIn({'block_id':'b9','layout_role':'repeated_navigation',
                           'reason':'frozen_repeated_navigation'},group['excluded_layout_blocks'])
            self.assertTrue(group['all_required_blocks_delivered'])
        self.assertEqual(packets[0]['source_documents'],packets[1]['source_documents'])

    def test_filter_projection_does_not_allow_dropping_source_group_members_or_changing_metadata(self):
        output=self.run_table('full','group-tamper')
        original=ScopedQueryDataPort.read_context
        changes=[lambda group:group['block_ids'].remove('b11'),
                 lambda group:group.update(rule='invented-rule'),
                 lambda group:group.update(table_id='b11'),
                 lambda group:group.update(kind='list_context'),
                 lambda group:group.update(group_id='unknown-group')]
        for change in changes:
            def tampered(port, **kwargs):
                page=deepcopy(original(port,**kwargs))
                group=next(g for g in page['reading_groups'] if g['kind']=='table_context')
                change(group)
                return page
            with self.subTest(change=change),patch.object(ScopedQueryDataPort,'read_context',tampered), \
                 self.assertRaises(ValueError):
                self.prepare(output)
        def without_group(port, **kwargs):
            page=deepcopy(original(port,**kwargs))
            page['reading_groups']=[g for g in page['reading_groups'] if g['kind']!='table_context']
            return page
        with patch.object(ScopedQueryDataPort,'read_context',without_group), \
             self.assertRaisesRegex(ValueError,'table context differs from frozen index'):
            self.prepare(output)

    def test_navigation_projection_does_not_relax_body_cell_position_or_span_validation(self):
        for representation in ('full','compact'):
            for field in ('body_text','text','row','column','rowspan','colspan'):
                output=self.run_table(representation,representation+'-'+field)
                def tamper(context):
                    block=next(b for b in context['blocks'] if b['block_id']=='b12')
                    if field=='body_text':
                        block.update(text='forged original body',text_hash=digest(b'forged original body'))
                        return
                    table=block['table']
                    cell=table['cells'][0]
                    altered='forged-cell' if field=='text' else 7
                    if isinstance(cell,dict):cell[field]=altered
                    else:cell[table['cell_fields'].index(field)]=altered
                self.reseal_context(output,tamper)
                with self.subTest(representation=representation,field=field), \
                     self.assertRaisesRegex(ValueError,'differs from original source block'):
                    self.prepare(output)


if __name__ == '__main__':unittest.main()
