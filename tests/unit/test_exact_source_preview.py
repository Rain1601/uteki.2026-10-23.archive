"""Explicit indexed coordinates select the intended occurrence without fuzzy search."""
from dataclasses import asdict
import hashlib
import unittest
from lxml import html

from apps.review_workbench.pages import source_preview as preview
from apps.review_workbench.pages.data_workspace import locate_button
from uteki.infrastructure.document_sources.sec_index import _table_structure
from tests.unit import test_workspace_source_preview as fixtures
ROOT = fixtures.ROOT


class ExactSourcePreviewTests(unittest.TestCase):
    fixture = fixtures.WorkspaceSourcePreviewTests.fixture
    load = fixtures.WorkspaceSourcePreviewTests.load
    def test_second_repeated_sentence_across_markup_uses_unicode_character_range(self):
        text = '😀 Sales 42. Sales 42.'
        selection = self.fixture('<html><body><p>😀 Sales 42. <b>Sales</b> 42.</p></body></html>',
            blocks=[{'block_id': 'repeated', 'type': 'paragraph', 'text': text, 'dom_path': '/html/body/p',
                     'text_hash': hashlib.sha256(text.encode()).hexdigest()}])
        before = self.raw
        start = text.rindex('Sales')
        result = self.load(selection | {'block': ['repeated'], 'char_start': [str(start)],
            'char_end': [str(len(text))], 'quote': ['Sales 42.']})
        document = html.fromstring(result['content'])
        marks = document.xpath('//mark')
        self.assertEqual(''.join(m.text_content() for m in marks), 'Sales 42.')
        self.assertEqual(document.xpath('//p')[0].text_content(), text)
        self.assertEqual(document.xpath('//p')[0].text, '😀 Sales 42. ')
        self.assertEqual(result['locator_precision'], 'character')
        self.assertEqual(result['char_start'], start)
        self.assertEqual(before, self.raw)

    def test_whitespace_normalization_maps_back_to_actual_nodes(self):
        selection = self.fixture('<html><body><p>  Alpha\n <i> Beta </i>  Gamma  </p></body></html>',
            blocks=[{'block_id': 'p', 'type': 'paragraph', 'text': 'Alpha Beta Gamma', 'dom_path': '/html/body/p'}])
        result = self.load(selection | {'block': ['p'], 'char_start': ['6'], 'char_end': ['10'], 'quote': ['Beta']})
        document = html.fromstring(result['content'])
        self.assertEqual(document.get_element_by_id('workspace-evidence').text, 'Beta')
        self.assertEqual(document.xpath('//p')[0].text_content(), '  Alpha\n  Beta   Gamma  ')

    def test_invalid_or_stale_precise_locators_fail_instead_of_block_fallback(self):
        selection = self.fixture('<p>Cash 42 Cash 42</p>', blocks=[{'block_id': 'p', 'type': 'paragraph',
            'text': 'Cash 42 Cash 42', 'dom_path': '/html/body/p', 'text_hash': 'a'*64}]) | {'block': ['p']}
        for change in ({'char_start': ['8']}, {'char_start': ['0'], 'char_end': ['50']},
                       {'char_start': ['0'], 'char_end': ['7'], 'quote': ['Wrong']},
                       {'char_start': ['-1'], 'char_end': ['7']}, {'cell_row': ['0']},
                       {'source_sha256': ['0'*64]}, {'text_hash': ['b'*64]}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.load(selection | change)

    def test_cell_grid_uses_rowspan_and_colspan_coordinates_not_equal_text(self):
        raw = '<html><body><table><tr><td rowspan="2">Label</td><td colspan="2">42</td></tr><tr><td>42</td><td>84</td></tr></table></body></html>'
        table = html.fromstring(raw).xpath('//table')[0]
        grid = asdict(_table_structure(table, visible_only=True, nearest_table=True))
        grid['cells'] = list(grid['cells'])
        block = {'block_id': 'table', 'type': 'table', 'text': 'Label424284',
                 'table': grid, 'dom_path': '/html/body/table'}
        selection = self.fixture(raw, blocks=[block]) | {'block': ['table'], 'cell_row': ['1'], 'cell_column': ['1'], 'quote': ['42']}
        result = self.load(selection)
        document = html.fromstring(result['content'])
        self.assertEqual(result['locator_precision'], 'cell')
        self.assertEqual(document.get_element_by_id('workspace-evidence').getparent(), document.xpath('//tr')[1])
        self.assertIsNone(document.xpath('//tr')[0][1].get('id'))
        invalid = self.load(selection | {'cell_column': ['0']})
        self.assertEqual(invalid['locator_status'], 'unavailable')
        self.assertEqual(invalid['locator_precision'], 'none')
        self.assertNotIn('id="workspace-evidence"', invalid['content'].decode())

    def test_character_and_cell_must_point_to_same_content(self):
        raw = '<table><tr><td>42</td><td>42</td></tr></table>'
        table = html.fromstring(raw)
        grid = asdict(_table_structure(table, visible_only=True, nearest_table=True)); grid['cells'] = list(grid['cells'])
        selection = self.fixture(raw, blocks=[{'block_id': 't', 'type': 'table', 'text': '4242',
            'table': grid, 'dom_path': '/html/body/table'}]) | {'block': ['t'], 'char_start': ['0'],
            'char_end': ['2'], 'cell_row': ['0'], 'cell_column': ['1']}
        with self.assertRaisesRegex(ValueError, 'conflicts'): self.load(selection)

    def test_pdf_cannot_mislabel_requested_character_precision_as_page_success(self):
        selection = self.fixture(b'%PDF-fixture', mime='application/pdf', blocks=[{
            'block_id': 'b', 'text': 'Cash 42', 'pdf_page': 1}])
        result = self.load(selection | {'block': ['b'], 'char_start': ['0'], 'char_end': ['4']})
        self.assertEqual(result['locator_status'], 'unavailable')
        self.assertEqual(result['requested_precision'], 'character')
        self.assertEqual(result['locator_precision'], 'none')

    def test_financial_button_preserves_normalized_offset_and_cell_aliases(self):
        button = html.fromstring(locate_button('b', ('定位', 'Locate'), quote='42', evidence={
            'source_start': 8, 'source_end': 10, 'text_hash': 'a'*64, 'cell': {'row': 2, 'column': 3}}))
        self.assertEqual(button.get('data-char-start'), '8')
        self.assertEqual(button.get('data-char-end'), '10')
        self.assertEqual(button.get('data-cell-row'), '2')
        self.assertEqual(button.get('data-cell-column'), '3')
        with self.assertRaisesRegex(ValueError, 'conflict'):
            locate_button('b', ('定位', 'Locate'), evidence={'source_start': 8, 'source_end': 10, 'start': 0, 'end': 2})

class RealSourcePrecisionTests(unittest.TestCase):
    def test_registered_original_amd_tsmc_cells_and_character_spans_without_mutation(self):
        cases = (('amd-annual-v2', 'source-291485b98a75d8cfabe47571', 'block-000686-a6e8806b'),
                 ('tsmc-annual-v2', 'source-6719837a8d24b2b7df359f29', 'block-001166-04f27bf6'))
        if not (ROOT/'data/evaluation_views/data-agent-v1.json').is_file():
            self.skipTest('Registered real sources unavailable')
        for dataset_id, sid, bid in cases:
            with self.subTest(dataset=dataset_id):
                dataset = preview.load_dataset(ROOT, dataset_id)
                block = next(b for b in dataset['blocks'][sid] if b['block_id'] == bid)
                source = next(s for s in dataset['sources'] if s['source_snapshot_id'] == sid)
                path = ROOT/dataset['storage']['dataset_path']/source['raw_file']
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                cell = next(c for c in block['table']['cells'] if c['text'] and c['row'] > 0 and c['column'] > 0)
                selection = {'dataset': [dataset_id], 'source': [sid], 'block': [bid], 'source_sha256': [before]}
                result = preview.load_source_preview(ROOT, selection | {'cell_row': [str(cell['row'])],
                    'cell_column': [str(cell['column'])], 'quote': [cell['text']]})
                self.assertEqual(result['locator_precision'], 'cell', result['notice'])
                target = html.fromstring(result['content']).get_element_by_id('workspace-evidence')
                self.assertIn(target.tag, ('td', 'th'))
                self.assertEqual(preview.normalize_text(target.text_content()), cell['text'])
                length = min(32, len(block['text']))
                result = preview.load_source_preview(ROOT, selection | {'char_start': ['0'],
                    'char_end': [str(length)], 'quote': [block['text'][:length]]})
                self.assertEqual(result['locator_precision'], 'character', result['notice'])
                marks = html.fromstring(result['content']).xpath('//mark')
                self.assertEqual(preview.normalize_text(''.join(mark.text_content() for mark in marks)), block['text'][:length].strip())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
