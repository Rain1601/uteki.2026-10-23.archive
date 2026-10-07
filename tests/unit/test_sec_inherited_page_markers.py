"""Independent HTML examples for inherited footer alignment and reader effects."""
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_parsed_package import identity
from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec_index import parse_sec_source


def parse(body, version="sec-source-blocks-v0.1.11"):
    return parse_sec_source("lyra-2030-report", "https://example.invalid/lyra/report",
        ("<html><body>" + body + "</body></html>").encode(),
        source_snapshot_id="lyra-frozen-2030", form_type="20-F", parser_version=version)


class InheritedPageMarkerTests(unittest.TestCase):
    def test_wrapped_footer_backfills_its_page_and_keeps_all_source_fields(self):
        body = ('<h2>ITEM 1. OPERATIONS</h2><p>Factory capacity is unchanged.</p>'
                '<div style="text-align:center"><div><div>26</div></div></div>'
                '<p>Second page text.</p><p style="text-align:center">27</p>')
        old, new = parse(body, "sec-source-blocks-v0.1.10"), parse(body)
        self.assertEqual([b.reported_page for b in old.blocks], [27] * 5)
        self.assertEqual([b.reported_page for b in new.blocks], [26, 26, 26, 27, 27])
        self.assertEqual(new.blocks[2].type, "page_marker")
        self.assertEqual(new.blocks[2].layout_role, "reported_page_number")
        keep = lambda b: {k:v for k,v in asdict(b).items() if k not in {"type", "layout_role", "reported_page"}}
        self.assertEqual([keep(b) for b in old.blocks], [keep(b) for b in new.blocks])
        self.assertEqual(old.anchors, new.anchors)

    def test_nearer_alignment_and_mixed_wrappers_do_not_create_markers(self):
        examples = [
            '<div style="text-align:center"><div style="text-align:left"><div>26</div></div></div>',
            '<div style="text-align:center"><p>Revenue</p><div>26</div></div>',
            '<div style="text-align:center">Total <div>26</div></div>',
            '<div style="text-align:center"><div>26</div><p>units</p></div>',
            '<div style="text-align:center"><table><tr><td>26</td></tr></table></div>',
            '<div style="text-align:center"><div>F-26</div></div>',
            '<div style="text-align:center"><div hidden>26</div></div>',
        ]
        for body in examples:
            with self.subTest(body=body):
                parsed = parse(body)
                self.assertFalse(any(b.type == "page_marker" for b in parsed.blocks))
                self.assertTrue(all(b.reported_page is None for b in parsed.blocks))

    def test_body_alignment_is_not_a_footer_rule(self):
        raw = b'<html><body style="text-align:center"><div>26</div></body></html>'
        result = parse_sec_source('lyra', 'https://example.invalid/lyra', raw,
            parser_version='sec-source-blocks-v0.1.11')
        self.assertEqual(result.blocks[0].type, 'paragraph')
        self.assertIsNone(result.blocks[0].reported_page)

    def test_reader_search_and_context_keep_actual_units_notes_and_page(self):
        body = ('<h2>ITEM 1. OPERATIONS</h2><p>Amounts in thousands of euros.</p>'
                '<table><tr><th>Metric</th><th>2030</th></tr><tr><td>License income</td><td>83</td></tr></table>'
                '<p>Note (a): Includes deferred amounts.</p>'
                '<div style="text-align:center"><div><div>26</div></div></div>'
                '<h2>ITEM 2. PROPERTY</h2><p>Factory capacity is unchanged.</p>')
        raw = ('<html><body>' + body + '</body></html>').encode()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'new'
            package.build_parsed_package(raw, identity(raw, company_id='synthetic-lyra',
                document_id='lyra-2030', source_snapshot_id='lyra-frozen-2030',
                report_period_end='2030-09-30', form_type='20-F'), path)
            reader = DocumentReader(path)
            root = next(n['node_id'] for n in reader.index['nodes'] if n['kind'] == 'document')
            hit = reader.search(root, 'License income')['hits'][0]
            self.assertEqual(hit['reported_page'], 26)
            # Select table plus following note explicitly. Automatic footnote
            # association remains outside this page-label repair.
            context = reader.read(root, hit['block_id'], count=2)
            texts = [b['text'] for b in context['blocks']]
            self.assertIn('Amounts in thousands of euros.', texts)
            self.assertIn('Note (a): Includes deferred amounts.', texts)
            last = reader.search(root, 'Factory capacity')['hits'][0]
            self.assertIsNone(last['reported_page'])  # No invented next page.
            self.assertTrue(reader.filter_navigation)


if __name__ == '__main__':
    unittest.main()
