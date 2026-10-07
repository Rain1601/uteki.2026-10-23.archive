"""Visible line breaks delimit words; inline spans and old versions stay intact."""
import tempfile
from pathlib import Path
import unittest

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.agents.reading.document_reader import DocumentReader
from tests.unit.test_parsed_package import identity

NEW = 'sec-source-blocks-v0.1.12'
OLD = 'sec-source-blocks-v0.1.11'


class SecLineBreakTests(unittest.TestCase):
    def parse(self, raw, version=NEW):
        return parse_sec_source('lyra-2030', 'https://example.invalid/lyra/report', raw,
                                source_snapshot_id='lyra-2030-frozen', form_type='20-F', parser_version=version)

    def test_table_headers_units_and_note_lines_preserve_word_boundaries(self):
        raw = b'''<html><body><table><tr><th>Notional<br>Amount</th><th>Fiscal<br><span>2030</span></th></tr>
        <tr><td>USD<br>millions</td><td><span>1</span><span>,200</span></td></tr></table>
        <p id="note">(1) Includes<br>foreign operations.</p></body></html>'''
        old, new = self.parse(raw, OLD), self.parse(raw)
        self.assertEqual([c.text for c in new.blocks[0].table.cells],
                         ['Notional Amount', 'Fiscal 2030', 'USD millions', '1,200'])
        self.assertEqual(new.blocks[1].text, '(1) Includes foreign operations.')
        self.assertEqual(old.blocks[0].table.cells[0].text, 'NotionalAmount')
        self.assertEqual(old.blocks[1].text, '(1) Includesforeign operations.')
        self.assertEqual([b.dom_path for b in new.blocks], [b.dom_path for b in old.blocks])
        self.assertEqual([(c.row,c.column,c.rowspan,c.colspan) for c in new.blocks[0].table.cells],
                         [(c.row,c.column,c.rowspan,c.colspan) for c in old.blocks[0].table.cells])
        self.assertEqual(new.anchors[0].target_block_id,new.blocks[1].block_id)
        self.assertNotEqual(new.blocks[0].block_id,old.blocks[0].block_id)
        self.assertNotEqual(build_legal_outline(new).index_id,build_legal_outline(old).index_id)

    def test_hidden_breaks_do_not_split_and_inline_tags_do_not_invent_spaces(self):
        raw=b'''<html><body><p>A<br hidden>B<br style="display:none">C<span hidden><br>secret</span>D</p>
        <p>co<span>operate</span> <span>1</span><span>,234</span></p>
        <p>First<br><br>second</p><p style="text-align:center">4<br>3</p></body></html>'''
        blocks=self.parse(raw).blocks
        self.assertEqual([b.text for b in blocks],['ABCD','cooperate 1,234','First second','4 3'])
        self.assertNotEqual(blocks[-1].type,'page_marker')
        self.assertIsNone(blocks[-1].reported_page)

    def test_toc_and_body_titles_share_break_normalization(self):
        raw=b'''<html><body><table><tr><td>PART I</td></tr><tr><td>ITEM 1.</td>
        <td><a href="#business">BUSINESS<br>OVERVIEW</a></td><td>1</td></tr></table>
        <h1>PART I</h1><h2 id="business">ITEM 1. BUSINESS<br>OVERVIEW</h2><p>Details.</p></body></html>'''
        parsed=self.parse(raw)
        self.assertEqual(next(t for t in parsed.toc_entries if t.kind=='item').title,'BUSINESS OVERVIEW')
        target=next(a.target_block_id for a in parsed.anchors if a.anchor=='business')
        self.assertEqual(next(b.text for b in parsed.blocks if b.block_id==target),'ITEM 1. BUSINESS OVERVIEW')
        self.assertTrue(any(n.item_number=='1' for n in build_legal_outline(parsed).nodes))

    def test_unchanged_input_is_byte_equivalent_except_parser_identity(self):
        raw=b'<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>Independent facts.</p></body></html>'
        old,new=self.parse(raw,OLD),self.parse(raw)
        self.assertEqual(old.blocks,new.blocks)
        self.assertEqual(old.anchors,new.anchors)
        self.assertEqual(old.toc_entries,new.toc_entries)

    def test_versioned_package_reads_new_text_rejects_missing_scope_and_replays(self):
        raw=b'<html><body><p>USD<br>millions</p><p>Independent note.</p></body></html>'
        scope=identity(raw,parser_version=NEW,company_id='synthetic-lyra',report_period_end='2030-09-30')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for key in ('company_id','document_id','source_snapshot_id','report_period_end'):
                missing={k:v for k,v in scope.items() if k!=key}
                with self.subTest(key=key),self.assertRaises(ValueError):
                    package.build_parsed_package(raw,missing,root/('missing-'+key))
                self.assertFalse((root/('missing-'+key)).exists())
            for name in ('one','two'):
                package.build_parsed_package(raw,scope,root/name)
                self.assertEqual(package.verify_parsed_package(root/name,expected_source=scope)['files_verified'],15)
            self.assertEqual({p.relative_to(root/'one'):p.read_bytes() for p in (root/'one').rglob('*') if p.is_file()},
                             {p.relative_to(root/'two'):p.read_bytes() for p in (root/'two').rglob('*') if p.is_file()})
            reader=DocumentReader(root/'one')
            node=next(n for n in reader.index['nodes'] if n['kind']=='document')
            self.assertEqual(len(reader.search(node['node_id'],'USD millions')['hits']),1)


if __name__ == '__main__':
    unittest.main()
