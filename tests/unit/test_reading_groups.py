import unittest
from itertools import permutations
from pathlib import Path
from uteki.agents.document_reader import DocumentReader
from uteki.agents.reading_groups import build_reading_groups

ROOT = Path(__file__).resolve().parents[2]


class ReadingGroupsTests(unittest.TestCase):
    @staticmethod
    def synthetic_reader(blocks, *, node_start=0, node_end=None):
        reader = DocumentReader.__new__(DocumentReader)
        reader.blocks = blocks
        reader.positions = {block['block_id']: i for i, block in enumerate(blocks)}
        reader.index = {'index_id': 'synthetic-reading-overlap'}
        reader.nodes = {'section': {'start_block_id': blocks[node_start]['block_id'],
                                    'end_block_id': blocks[node_end if node_end is not None else -1]['block_id']}}
        reader.groups = build_reading_groups(blocks, [])
        return reader

    def test_competition_list_is_complete(self):
        r = DocumentReader(ROOT / 'data/source_documents/alphabet_2025_10k/indexes/v0.1')
        b = r.blocks[116]
        node = next(n for n in r.index['nodes'] if n['kind'] == 'item' and n['item_number'] == '1')
        result = r.read(node['node_id'], b['block_id'], count=1)
        self.assertEqual([x['ordinal'] for x in result['blocks']], list(range(110,123)))
        self.assertEqual(len(result['reading_groups'][0]['item_ids']), 11)
        self.assertEqual(r.blocks[116]['type'], 'paragraph')

    def test_boundary_and_cross_page(self):
        blocks = [{'block_id':str(i),'type':t,'text':text} for i,(t,text) in enumerate([
            ('paragraph','Examples:'),('list_item','•one'),('page_marker','6'),
            ('list_item','•two'),('heading_candidate','Next'),('list_item','•three')])]
        groups = build_reading_groups(blocks, [])
        self.assertEqual(groups[0]['block_ids'], ['0','1','2','3'])
        groups = build_reading_groups(blocks, [{'kind':'item','start_block_id':'3'}])
        self.assertEqual(groups[0]['block_ids'], ['0','1'])
        self.assertNotIn('0',groups[1]['block_ids'])

    def test_no_merge_unrelated_prose(self):
        blocks=[{'block_id':'a','type':'paragraph','text':'Unrelated.'},
                {'block_id':'b','type':'paragraph','text':'•example'}]
        self.assertEqual(build_reading_groups(blocks,[])[0]['block_ids'], ['b'])

    def test_table_note_expands_into_complete_list(self):
        blocks = [{'block_id': str(i), 'type': kind, 'text': text}
                  for i, (kind, text) in enumerate([
                      ('paragraph', 'Previous context.'),
                      ('heading_candidate', 'Financial information'),
                      ('table', 'Reported values'),
                      ('paragraph', 'Note: the following conditions apply:'),
                      ('list_item', '• First condition'),
                      ('list_item', '• Second condition'),
                      ('heading_candidate', 'Next section')])]
        reader = self.synthetic_reader(blocks)
        self.assertEqual([group['kind'] for group in reader.groups], ['list_context', 'table_context'])
        result = reader.read('section', '2', count=1)
        self.assertEqual([block['block_id'] for block in result['blocks']], ['1', '2', '3', '4', '5'])
        self.assertEqual(result['reading_groups'], reader.groups)
        self.assertEqual((result['previous_block_id'], result['next_block_id']), ('0', '6'))

    def test_overlapping_group_closure_is_independent_of_group_order(self):
        blocks = [{'block_id': str(i), 'type': 'paragraph', 'text': str(i)} for i in range(7)]
        reader = self.synthetic_reader(blocks)
        groups = [{'group_id': name, 'block_ids': ids} for name, ids in (
            ('left', ['1', '2']), ('middle', ['2', '3']),
            ('right', ['3', '4']), ('nested', ['2']))]
        for order in permutations(groups):
            with self.subTest(order=[group['group_id'] for group in order]):
                reader.groups = list(order)
                result = reader.read('section', '4', count=1)
                self.assertEqual([block['block_id'] for block in result['blocks']], ['1', '2', '3', '4'])
                self.assertEqual(result['reading_groups'], list(order))
                self.assertEqual((result['previous_block_id'], result['next_block_id']), ('0', '5'))

    def test_expansion_respects_node_and_does_not_join_adjacent_groups(self):
        blocks = [{'block_id': str(i), 'type': 'paragraph', 'text': str(i)} for i in range(7)]
        reader = self.synthetic_reader(blocks, node_start=1, node_end=5)
        reader.groups = [
            {'group_id': 'outside-left', 'block_ids': ['0', '1', '2']},
            {'group_id': 'inside', 'block_ids': ['2', '3']},
            {'group_id': 'adjacent', 'block_ids': ['4', '5']},
            {'group_id': 'outside-right', 'block_ids': ['3', '4', '5', '6']},
        ]
        result = reader.read('section', '2', count=1)
        self.assertEqual([block['block_id'] for block in result['blocks']], ['2', '3'])
        self.assertEqual([group['group_id'] for group in result['reading_groups']], ['inside'])
        self.assertEqual((result['previous_block_id'], result['next_block_id']), ('1', '4'))

    @staticmethod
    def table(block_id, rows):
        cells = [{'row': r, 'column': c, 'text': text, 'rowspan': 1, 'colspan': 1}
                 for r, row in enumerate(rows) for c, text in enumerate(row)]
        return {'block_id': block_id, 'type': 'table', 'text': ''.join(c['text'] for c in cells),
                'table': {'cells': cells}}

    def test_table_shaped_note_preserves_unit_context_and_original_cells(self):
        from copy import deepcopy
        blocks = [{'block_id': 'unit', 'type': 'paragraph', 'text': 'Amounts in thousands'},
                  self.table('values', [['Client', 'Share'], ['Company Z', '*']]),
                  self.table('note', [['', '', ''], ['*', '', 'Less than 5%']]),
                  self.table('next', [['Region', 'Revenue'], ['West', '120']])]
        original = deepcopy(blocks)
        reader = self.synthetic_reader(blocks)
        for start in ('values', 'note'):
            result = reader.read('section', start, count=1)
            self.assertEqual([b['block_id'] for b in result['blocks']], ['unit', 'values', 'note'])
            link = result['reading_groups'][0]['note_links'][0]
            self.assertEqual(link['source_marker_cells'][0]['row'], 1)
            self.assertEqual(link['definition_cell']['column'], 2)
            self.assertEqual(link['semantic_applicability'], 'not_inferred')
        self.assertEqual(blocks, original)
        self.assertEqual(len(reader.groups), 2)

    def test_explicit_note_table_requires_two_nonempty_cells_and_prose(self):
        source = self.table('v', [['Value', '100']])
        note = self.table('n', [['Note:', 'Changes include credits.']])
        groups = build_reading_groups([source, note], [])
        self.assertEqual(groups[0]['block_ids'], ['v', 'n'])
        self.assertEqual(groups[0]['note_links'][0]['association_basis'], 'adjacent_explicit_note')
        self.assertEqual(groups[0]['note_links'][0]['source_marker_cells'], [])
        for rows in ([['Note:', '123']], [['Note:', 'Information', 'Another column']],
                     [['Note: extra words', 'Information']]):
            with self.subTest(rows=rows):
                self.assertEqual(build_reading_groups([source, self.table('n', rows)], [])[0]['block_ids'], ['v'])

    def test_exhibits_unmatched_markers_and_unrelated_tables_are_not_notes(self):
        source = self.table('v', [['Description', 'Value'], ['Service', '*']])
        for rows in ([['*10.28', 'Employee purchase plan']], [['(1)', 'Exhibit description']],
                     [['**', 'Different marker']], [['*', 'Term', 'Amount']],
                     [['*', '123']], [['Ordinary heading', 'Next business table']]):
            with self.subTest(rows=rows):
                self.assertEqual(build_reading_groups([source, self.table('n', rows)], [])[0]['block_ids'], ['v'])

    def test_note_context_respects_legal_and_reader_boundaries(self):
        blocks = [self.table('v', [['Amount', '*']]), self.table('n', [['*', 'Not material']])]
        self.assertEqual(build_reading_groups(blocks, [{'kind':'item', 'start_block_id':'n'}])[0]['block_ids'], ['v'])
        reader = self.synthetic_reader(blocks, node_end=0)
        self.assertEqual([b['block_id'] for b in reader.read('section', 'v', count=1)['blocks']], ['v'])
