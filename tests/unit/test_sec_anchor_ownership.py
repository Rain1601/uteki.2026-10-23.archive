"""Source anchor ownership changes only in explicitly selected parser v0.1.8."""
from dataclasses import asdict
import unittest

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline


class SecAnchorOwnershipTests(unittest.TestCase):
    def parse(self, body, version='sec-source-blocks-v0.1.8'):
        raw = ('<html><body>' + body + '</body></html>').encode()
        return parse_sec_source('synthetic-other-issuer', 'https://example.invalid/2032/quarter', raw,
            source_snapshot_id='synthetic-other-issuer-2032', form_type='10-Q', parser_version=version)

    def target(self, parsed, anchor):
        ref = next(a for a in parsed.anchors if a.anchor == anchor)
        return next((b for b in parsed.blocks if b.block_id == ref.target_block_id), None)

    def test_inline_anchors_resolve_to_owning_paragraph_table_and_final_block(self):
        for body, expected in [
            ('<p>A <span id="a">inside</span> B</p><p>Following</p>', 'A inside B'),
            ('<table><tr><td><span id="a">17</span></td></tr></table><p>Following</p>', '17'),
            ('<p>Final <span id="a">17</span></p>', 'Final 17'),
        ]:
            with self.subTest(body=body):
                old, new = self.parse(body, 'sec-source-blocks-v0.1.7'), self.parse(body)
                self.assertEqual(self.target(new, 'a').text, expected)
                self.assertNotEqual(self.target(old, 'a'), self.target(new, 'a'))
                self.assertEqual([asdict(b) for b in old.blocks], [asdict(b) for b in new.blocks])

    def test_nearest_nested_table_owns_its_inner_anchor_with_spans_unchanged(self):
        body = '<table id="outer"><tr><td>Outer<table id="inner"><tr><th colspan="2">Amounts</th></tr>' \
            '<tr><td><i id="a">17</i></td><td>19</td></tr></table>tail</td></tr></table><p>Following</p>'
        new, old = self.parse(body), self.parse(body, 'sec-source-blocks-v0.1.7')
        self.assertEqual(self.target(new, 'a'), self.target(new, 'inner'))
        self.assertNotEqual(self.target(new, 'a'), self.target(new, 'outer'))
        self.assertEqual([asdict(b) for b in new.blocks], [asdict(b) for b in old.blocks])
        self.assertEqual(self.target(new, 'a').table.cells[0].colspan, 2)

    def test_exact_blocks_empty_markers_and_wrappers_keep_expected_targets(self):
        parsed = self.parse('<p id="own">Own</p><a name="marker"></a><section id="wrapper">'
            '<p>Child one</p><p>Child two</p></section><a id="eof"></a>')
        self.assertEqual(self.target(parsed, 'own').text, 'Own')
        for anchor in ('marker', 'wrapper'):
            self.assertEqual(self.target(parsed, anchor).text, 'Child one')
        self.assertIsNone(self.target(parsed, 'eof'))

    def test_hidden_or_script_anchors_never_claim_a_visible_target(self):
        body = '<p>Visible <span hidden id="attribute">secret</span> tail</p>' \
            '<div style="display:none"><span id="style">secret</span></div>' \
            '<ix:hidden><i id="ix">secret</i></ix:hidden><script id="script">secret</script>' \
            '<style id="css">secret</style><noscript><i id="noscript">secret</i></noscript><p>Following</p>'
        parsed = self.parse(body)
        for anchor in ('attribute', 'style', 'ix', 'script', 'css', 'noscript'):
            self.assertIsNone(self.target(parsed, anchor))
        self.assertEqual([asdict(b) for b in parsed.blocks], [asdict(b) for b in self.parse(body, 'sec-source-blocks-v0.1.7').blocks])

    def test_duplicate_id_first_occurrence_wins_with_explicit_diagnostic(self):
        body = '<p id="duplicate">First</p><p id="duplicate">Second</p>'
        new, old = self.parse(body), self.parse(body, 'sec-source-blocks-v0.1.7')
        self.assertEqual(self.target(new, 'duplicate').text, 'First')
        self.assertEqual(len(new.anchors), 1)
        self.assertEqual(len(old.anchors), 2)
        self.assertEqual([d.code for d in new.parser_diagnostics].count('duplicate_source_anchor'), 1)
        self.assertNotIn('duplicate_source_anchor', [d.code for d in old.parser_diagnostics])
        hidden_first = self.parse('<p hidden id="duplicate">Hidden</p><p id="duplicate">Visible</p>')
        self.assertIsNone(self.target(hidden_first, 'duplicate'))

    def test_page_marker_exclusion_and_body_outline_stay_versioned(self):
        body = '<h1>PART I</h1><h2>ITEM 1. PRODUCTS</h2><p>Content</p>' \
            '<p id="page" style="text-align:center">1</p><h2>ITEM 2. LOCATIONS</h2><p>Content two</p>'
        old, new = self.parse(body, 'sec-source-blocks-v0.1.7'), self.parse(body)
        self.assertEqual(self.target(old, 'page').text, 'ITEM 2. LOCATIONS')
        self.assertEqual(self.target(new, 'page').text, 'ITEM 2. LOCATIONS')
        old_nodes, new_nodes = build_legal_outline(old).nodes, build_legal_outline(new).nodes
        self.assertEqual([(n.kind, n.item_number, n.start_block_id, n.end_block_id) for n in old_nodes],
                         [(n.kind, n.item_number, n.start_block_id, n.end_block_id) for n in new_nodes])


if __name__ == '__main__':
    unittest.main()
