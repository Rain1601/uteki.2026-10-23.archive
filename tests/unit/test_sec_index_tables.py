"""Table ownership changes only in the explicitly selected parser version."""
import unittest

from lxml import html

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline


class NestedTableTests(unittest.TestCase):
    def parse(self, raw, version='sec-source-blocks-v0.1.7'):
        return parse_sec_source('independent-issuer-annual', 'https://example.invalid/annual', raw,
                                form_type='20-F', parser_version=version)

    def test_nested_table_owns_its_rows_without_changing_source_blocks(self):
        raw = b'''<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2>
        <table id="outer"><tr><td>Layout introduction
          <table id="financial"><tr><th>Period</th><th>Amount</th></tr>
            <tr><td>2031</td><td>71</td></tr></table>
          Layout ending</td></tr></table></body></html>'''
        old = self.parse(raw, 'sec-source-blocks-v0.1.6')
        new = self.parse(raw)
        outer, inner = [b for b in new.blocks if b.type == 'table']
        self.assertEqual((outer.table.row_count, outer.table.column_count, len(outer.table.cells)), (1, 1, 1))
        self.assertEqual((inner.table.row_count, inner.table.column_count, len(inner.table.cells)), (2, 2, 4))
        self.assertEqual([c.text for c in inner.table.cells], ['Period', 'Amount', '2031', '71'])
        self.assertIn('2031', outer.table.cells[0].text)
        self.assertEqual([b.table.row_count for b in old.blocks if b.type == 'table'], [1, 0])
        self.assertEqual([(b.block_id, b.text, b.text_hash, b.dom_path) for b in new.blocks],
                         [(b.block_id, b.text, b.text_hash, b.dom_path) for b in old.blocks])
        self.assertNotEqual(build_legal_outline(new).index_id, build_legal_outline(old).index_id)
        tree = html.document_fromstring(raw).getroottree()
        for block in new.blocks:
            self.assertEqual(len(tree.xpath(block.dom_path)), 1)

    def test_nested_spans_hidden_rows_and_parent_rows_remain_separate(self):
        raw = b'''<html><body><table><tbody><tr><td>Outer row one</td></tr>
        <tr><td><table><tbody><tr><th rowspan="2">Group</th><th colspan="2">Amounts</th></tr>
        <tr style="display:none"><td>Hidden</td></tr>
        <tr><td>11</td><td>12</td></tr></tbody></table></td></tr>
        <tr><td>Outer row three</td></tr></tbody></table></body></html>'''
        outer, inner = [b for b in self.parse(raw).blocks if b.type == 'table']
        self.assertEqual((outer.table.row_count, len(outer.table.cells)), (3, 3))
        self.assertEqual((inner.table.row_count, inner.table.column_count, len(inner.table.cells)), (2, 3, 4))
        self.assertEqual([(c.row, c.column) for c in inner.table.cells], [(0, 0), (0, 1), (1, 1), (1, 2)])
        self.assertNotIn('Hidden', inner.text)
        self.assertTrue(all('Hidden' not in c.text for c in inner.table.cells))

    def test_mixed_prose_container_preserves_independent_assets_and_legal_ranges(self):
        raw = b'''<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2>
        <div id="mixed">Direct introductory text.
          <table id="outer"><tr><td><table id="inner"><tr><td>Metric</td><td>19</td></tr></table></td></tr></table>
          <img src="chart.png" alt="Visible chart"><span hidden><table><tr><td>Hidden asset</td></tr></table></span>
          Direct closing text.</div>
        <h2>ITEM 2. PROPERTIES</h2><p>Second section.</p></body></html>'''
        old, new = self.parse(raw, 'sec-source-blocks-v0.1.6'), self.parse(raw)
        self.assertEqual([b.type for b in old.blocks].count('table'), 0)
        tables = [b for b in new.blocks if b.type == 'table']
        self.assertEqual([len(b.table.cells) for b in tables], [1, 2])
        self.assertEqual(len(new.assets), 1)
        self.assertEqual(len({b.dom_path for b in new.blocks}), len(new.blocks))
        parent = next(b for b in new.blocks if b.dom_path.endswith('/div'))
        old_parent = next(b for b in old.blocks if b.dom_path == parent.dom_path)
        self.assertEqual((parent.text, parent.text_hash), (old_parent.text, old_parent.text_hash))
        self.assertIn('Direct closing text.', parent.text)
        self.assertNotIn('Hidden asset', ' '.join(b.text for b in new.blocks))
        index = build_legal_outline(new)
        blocks = {b.block_id: b for b in new.blocks}
        first = next(n for n in index.nodes if n.item_number == '1')
        second = next(n for n in index.nodes if n.item_number == '2')
        self.assertEqual(blocks[first.start_block_id].text, 'ITEM 1. BUSINESS')
        self.assertLess(blocks[first.end_block_id].ordinal, blocks[second.start_block_id].ordinal)
        self.assertTrue(all(blocks[first.start_block_id].ordinal < b.ordinal <= blocks[first.end_block_id].ordinal for b in tables))


if __name__ == '__main__':
    unittest.main()
