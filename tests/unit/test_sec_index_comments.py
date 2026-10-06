"""Non-content HTML nodes must not break source indexing or become evidence."""
import unittest

from lxml import html

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline


class SourceCommentTests(unittest.TestCase):
    def test_comments_preserve_visible_blocks_anchors_and_dom_paths(self):
        raw = b'''<html><body><!-- invisible opening -->
        <h1 id="business">Item 1. Business</h1>
        <!-- invisible between blocks -->
        <p>Visible <!-- invisible inline -->business text.</p>
        <table><tr><!-- invisible row --><td>Revenue</td><td>42</td></tr></table>
        <!-- invisible closing --></body></html>'''
        for version in ('sec-source-blocks-v0.1.1', 'sec-source-blocks-v0.1.5'):
            with self.subTest(parser_version=version):
                parsed = parse_sec_source('fixture', 'https://example.test/report', raw,
                                          form_type='OFFICIAL_UPDATE', parser_version=version)
                self.assertEqual([b.text for b in parsed.blocks],
                                 ['Item 1. Business', 'Visible business text.', 'Revenue42'])
                self.assertEqual([c.text for c in parsed.blocks[-1].table.cells], ['Revenue', '42'])
                anchor = next(a for a in parsed.anchors if a.anchor == 'business')
                self.assertEqual(anchor.target_block_id, parsed.blocks[0].block_id)
                tree = html.document_fromstring(raw).getroottree()
                for block in parsed.blocks:
                    element, = tree.xpath(block.dom_path)
                    self.assertEqual(' '.join(element.text_content().split()), block.text)
                self.assertTrue(build_legal_outline(parsed).nodes)
