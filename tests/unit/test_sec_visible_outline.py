"""Versioned visible legal headings: no issuer-specific text or source repairs."""
import unittest

from lxml import html

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline


class SecVisibleOutlineTests(unittest.TestCase):
    def parse(self, body, version='sec-source-blocks-v0.1.6'):
        raw = ('<html><body>' + body + '</body></html>').encode()
        parsed = parse_sec_source('synthetic', 'https://example.invalid/filing', raw,
                                  source_snapshot_id='synthetic-source', parser_version=version)
        return raw, parsed, build_legal_outline(parsed)

    def test_hidden_containers_and_inline_text_are_excluded_without_moving_dom(self):
        body = '<div style=" DISPLAY : none !important; "><p>HIDDEN_CONTEXT</p></div>' \
               '<ix:hidden><p>HIDDEN_FACT</p></ix:hidden><div hidden>HIDDEN_ATTRIBUTE</div>' \
               '<div><h1>PART I</h1><h2>ITEM 1. PRODUCTS</h2><p>Visible <span style="display:none">SECRET</span> tail.</p>' \
               '<table><tr><td>100<span hidden>999</span></td></tr></table></div>'
        raw, parsed, index = self.parse(body)
        text = ' '.join(block.text for block in parsed.blocks)
        for hidden in ('HIDDEN_CONTEXT', 'HIDDEN_FACT', 'HIDDEN_ATTRIBUTE', 'SECRET', '999'):
            self.assertNotIn(hidden, text)
        block = next(b for b in parsed.blocks if b.text == 'Visible tail.')
        root = html.document_fromstring(raw)
        self.assertEqual(root.xpath(block.dom_path)[0].text_content(), 'Visible SECRET tail.')
        table = next(b.table for b in parsed.blocks if b.table)
        self.assertEqual(table.cells[0].text, '100')
        _, legacy, _ = self.parse(body, 'sec-source-blocks-v0.1.5')
        self.assertIn('HIDDEN_CONTEXT', ' '.join(b.text for b in legacy.blocks))
        self.assertEqual(parsed.content_hash, legacy.content_hash)

    def test_wrapper_anchor_and_repeated_page_labels_do_not_target_cover(self):
        body = '<div><a id="wrapper"></a><h1>COVER PAGE</h1><h2>PART I</h2><h2>Item 1</h2>' \
               '<h2>ITEM 1. PRODUCTS</h2><p>First visible paragraph.</p><h2>PART I</h2><h2>Item 1</h2>' \
               '<p>Last visible paragraph.</p><h2>PART I</h2><h2>Item 1A</h2>' \
               '<h2>ITEM 1A. UNCERTAINTY</h2><p>Different section.</p></div>'
        _, parsed, index = self.parse(body)
        self.assertEqual(len(index.nodes), len({n.node_id for n in index.nodes}))
        item = next(n for n in index.nodes if n.item_number == '1')
        blocks = {b.block_id: b for b in parsed.blocks}
        self.assertEqual(blocks[item.start_block_id].text, 'ITEM 1. PRODUCTS')
        self.assertEqual(blocks[item.end_block_id].text, 'Last visible paragraph.')
        roles = [b.layout_role for b in parsed.blocks if b.text in ('Item 1', 'Item 1A')]
        self.assertTrue(roles and all(role == 'running_header' for role in roles))
        codes = {d.code for d in index.diagnostics}
        self.assertIn('item_anchor_body_override', codes)
        self.assertIn('repeated_legal_headers_excluded', codes)
        self.assertNotIn('item_anchor_title_mismatch', codes)

    def test_ambiguous_next_item_is_not_absorbed_into_previous_item(self):
        _, parsed, index = self.parse('<h1>PART I</h1><h2>ITEM 1. PRODUCTS</h2><p>End of first.</p>'
            '<h2>ITEM 2. LOCATION</h2><p>Unresolved content.</p><h2>ITEM 2. DIFFERENT TITLE</h2>'
            '<p>More unresolved content.</p><h2>ITEM 3. PROCEEDINGS</h2><p>Third.</p>')
        self.assertNotIn('2', {n.item_number for n in index.nodes})
        first = next(n for n in index.nodes if n.item_number == '1')
        self.assertEqual(next(b.text for b in parsed.blocks if b.block_id == first.end_block_id), 'End of first.')
        self.assertTrue(any(d.code == 'item_heading_ambiguous' and d.severity == 'error' for d in index.diagnostics))

    def test_toc_anchor_to_cover_is_not_published_as_item_body(self):
        _, parsed, index = self.parse('<a id="bad"></a><h1>COVER</h1>'
            '<table><tr><td>PART I</td></tr><tr><td>Item 1</td><td><a href="#bad">PRODUCTS</a></td><td>3</td></tr></table>'
            '<h2>PART I</h2><h2>ITEM 1. PRODUCTS</h2><p>Actual section.</p>')
        item = next(n for n in index.nodes if n.item_number == '1')
        self.assertEqual(next(b.text for b in parsed.blocks if b.block_id == item.start_block_id), 'ITEM 1. PRODUCTS')

    def test_no_visible_headings_preserves_unresolved_diagnostic(self):
        _, parsed, index = self.parse('<div style="display:none"><h2>PART I</h2><h2>ITEM 1. FALSE</h2></div><p>Visible prose.</p>')
        self.assertEqual(len(index.nodes), 1)
        self.assertIn('item_unresolved', {d.code for d in index.diagnostics})
