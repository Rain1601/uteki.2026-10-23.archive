"""Source-structural split reading units; no company rules, source edits or models."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from uteki.agents.reading.document_reader import DocumentReader
from uteki.agents.reading.reading_groups import build_reading_groups, VERSION
from tests.unit import test_reading_groups as fixtures

ROOT = Path(__file__).resolve().parents[2]


def block(identity, kind, text, path):
    return {'block_id': identity, 'type': kind, 'text': text, 'dom_path': path}


class SplitReadingGroupsTests(unittest.TestCase):
    @staticmethod
    def listed():
        return [block('heading', 'heading_candidate', 'Segment Z', '/html/body/div[5]/p[1]'),
            block('intro', 'paragraph', 'This segment includes:', '/html/body/div[5]/p[2]'),
            block('marker1', 'list_item', '•', '/html/body/div[5]/div[1]/span'),
            block('body1', 'paragraph', 'Independent synthetic product.', '/html/body/div[5]/div[1]/div/p[1]'),
            block('body1b', 'paragraph', 'Its explicit qualifier.', '/html/body/div[5]/div[1]/div/p[2]'),
            block('marker2', 'list_item', '•', '/html/body/div[5]/div[2]/span'),
            block('body2', 'other', 'Independent synthetic service.', '/html/body/div[5]/div[2]/div'),
            block('next', 'paragraph', 'Unrelated next disclosure.', '/html/body/div[5]/p[3]')]

    def test_split_bullets_join_header_full_bodies_and_peer_items_bidirectionally(self):
        blocks = self.listed()
        original = deepcopy(blocks)
        reader = fixtures.ReadingGroupsTests.synthetic_reader(blocks)
        for start in ('heading', 'intro', 'marker1', 'body1', 'body1b', 'marker2', 'body2'):
            with self.subTest(start=start):
                result = reader.read('section', start, count=1)
                self.assertEqual([b['block_id'] for b in result['blocks']], [b['block_id'] for b in blocks[:-1]])
                self.assertEqual(result['next_block_id'], 'next')
        items = reader.groups[0]['items']
        self.assertEqual(items[0]['content_block_ids'], ['body1', 'body1b'])
        self.assertEqual(items[1]['content_block_ids'], ['body2'])
        self.assertEqual(blocks, original)

    def test_bold_item_body_keeps_its_heading_candidate_type(self):
        blocks = self.listed()
        blocks[3]['type'] = 'heading_candidate'
        reader = fixtures.ReadingGroupsTests.synthetic_reader(blocks)
        result = reader.read('section','body1',1)
        self.assertEqual([b['block_id'] for b in result['blocks']], [b['block_id'] for b in blocks[:-1]])
        self.assertEqual(next(b for b in result['blocks'] if b['block_id']=='body1')['type'], 'heading_candidate')

    def test_different_container_missing_dom_and_document_root_do_not_join(self):
        for paths in [('/html/body/div[1]/span','/html/body/div[2]/p'), ('',''),
                      ('/html/body/span', '/html/body/p')]:
            with self.subTest(paths=paths):
                blocks = [block('marker','list_item','•',paths[0]),block('prose','paragraph','Unrelated prose.',paths[1])]
                self.assertEqual(build_reading_groups(blocks,[])[0]['block_ids'], ['marker'])

    def test_split_list_respects_item_and_explicit_read_node_boundaries(self):
        blocks = self.listed()
        groups = build_reading_groups(blocks,[{'kind':'item','start_block_id':'body1'}])
        self.assertNotIn('body1',groups[0]['block_ids'])
        reader = fixtures.ReadingGroupsTests.synthetic_reader(blocks,node_start=3,node_end=4)
        self.assertEqual([b['block_id'] for b in reader.read('section','body1',1)['blocks']],['body1'])

    @staticmethod
    def noted(marker='(a)', *, wrapped=True):
        table = fixtures.ReadingGroupsTests.table('values', [['Units in thousands', '2034'], ['Region ' + marker, '120']])
        table['dom_path'] = '/html/body/div[7]/table'
        parent = '/html/body/div[7]/div' if wrapped else '/html/body/div[7]'
        return [block('unit','paragraph','Amounts in thousands','/html/body/div[7]/p'), table,
            block('marker','other',marker,parent+'/span[1]'),
            block('definition','other','Includes separately identified distribution billings.',parent+'/span[2]'),
            block('next','paragraph','Different subsequent topic.','/html/body/div[8]/p')]

    def test_split_numeric_alpha_and_symbol_footnotes_keep_units_cells_and_source_markers(self):
        for marker, wrapped in [('(a)',True),('(1)',False),('[2]',False),('*',True)]:
            with self.subTest(marker=marker,wrapped=wrapped):
                blocks = self.noted(marker,wrapped=wrapped)
                original = deepcopy(blocks)
                reader = fixtures.ReadingGroupsTests.synthetic_reader(blocks)
                for start in ('values','marker','definition'):
                    result=reader.read('section',start,count=1)
                    self.assertEqual([b['block_id'] for b in result['blocks']],['unit','values','marker','definition'])
                link=reader.groups[0]['note_links'][0]
                self.assertEqual(link['marker_block_id'],'marker')
                self.assertEqual(link['definition_block_id'],'definition')
                self.assertEqual(link['source_marker_cells'][0]['row'],1)
                self.assertEqual(link['semantic_applicability'],'not_inferred')
                self.assertEqual(blocks,original)

    def test_unmatched_marker_wrong_container_nonprose_and_missing_dom_are_not_joined(self):
        for change in ('unmatched','container','nonprose','missing_dom','heading'):
            with self.subTest(change=change):
                blocks=self.noted()
                if change=='unmatched':blocks[2]['text']='(b)'
                if change=='container':blocks[3]['dom_path']='/html/body/div[8]/div/span[2]'
                if change=='nonprose':blocks[3]['text']='123'
                if change=='missing_dom':blocks[1].pop('dom_path')
                if change=='heading':blocks[2]['type']='heading_candidate'
                self.assertEqual(build_reading_groups(blocks,[])[0]['block_ids'],['unit','values'])

    def test_split_notes_respect_legal_and_reader_boundaries(self):
        blocks=self.noted()
        for bid in ('marker','definition'):
            groups=build_reading_groups(blocks,[{'kind':'item','start_block_id':bid}])
            self.assertEqual(groups[0]['block_ids'],['unit','values'])
        reader=fixtures.ReadingGroupsTests.synthetic_reader(blocks,node_end=1)
        self.assertEqual([b['block_id'] for b in reader.read('section','values',1)['blocks']],['values'])

    def test_multiple_split_notes_keep_only_matched_note_pairs(self):
        blocks=self.noted()
        blocks[1]['table']['cells'][2]['text']='Region (a) (b)'
        blocks[4:4]=[block('marker-b','other','(b)','/html/body/div[7]/div[2]/span'),
            block('definition-b','paragraph','Second explanatory condition.','/html/body/div[7]/div[2]/div')]
        reader=fixtures.ReadingGroupsTests.synthetic_reader(blocks)
        self.assertEqual([b['block_id'] for b in reader.read('section','definition-b',1)['blocks']],
            ['unit','values','marker','definition','marker-b','definition-b'])
        self.assertEqual(len(reader.groups[0]['note_links']),2)

    def test_real_frozen_microsoft_and_alphabet_contexts(self):
        base=ROOT/'experiments/agent_design/2026-10-08-acquisition-reuse-v1'
        for company,starts,expected in [
            ('msft',[117,119,120,121,122],list(range(117,123))),
            ('msft',[1166,1167,1168],list(range(1165,1169))),
            ('msft',[1219,1220,1221],list(range(1218,1222))),
            ('googl',[1155,1156,1157],list(range(1154,1158))),
            ('googl',[1176,1177,1178],list(range(1174,1179))),
        ]:
            folder=base/company/'dataset/indexes'/f'{company}-2025-10k'
            hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    (folder/'blocks.jsonl',folder/'index.json',folder/'manifest.json')}
            reader=DocumentReader(folder)
            self.assertEqual(reader.index['parser_version'],'sec-source-blocks-v0.1.11')
            node=next(n['node_id'] for n in reader.index['nodes'] if n['kind']=='document')
            for start in starts:
                with self.subTest(company=company,start=start):
                    result=reader.read(node,reader.blocks[start-1]['block_id'],count=1)
                    self.assertEqual([reader.positions[b['block_id']]+1 for b in result['blocks']],expected)
                    self.assertEqual(result['reading_group_version'],VERSION)
            self.assertEqual(hashes,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes})


if __name__=='__main__':
    unittest.main()
