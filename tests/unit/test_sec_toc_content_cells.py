"""TOC semantic cells must not depend on publisher layout spacer positions."""
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline
from uteki.infrastructure.document_sources.parsed_package import build_parsed_package, verify_parsed_package
from tests.unit.test_parsed_package import identity

NEW='sec-source-blocks-v0.1.13'
OLD='sec-source-blocks-v0.1.12'

def fixture(padded=True, conflict=False):
    space='<td>\u00a0</td><td></td>' if padded else ''
    bad='<a href="#wrong">Different</a>' if conflict else ''
    return f'''<html><body><table><tr>{space}<td>PART I</td>{space}</tr>
    <tr>{space}<td>Item 1.</td>{space}<td><a href="#products">PRODUCTS<br>AND SERVICES</a>{bad}</td>{space}<td><a href="#products">3</a></td>{space}</tr>
    <tr>{space}<td>Item 1A.</td>{space}<td><a href="#risk">RISK FACTORS</a></td>{space}<td>4</td>{space}</tr></table>
    <h1>PART I</h1><h2 id="products">ITEM 1. PRODUCTS<br>AND SERVICES</h2><p>Orion builds navigation hardware.</p><p style="text-align:center">3</p>
    <h2 id="risk">ITEM 1A. RISK FACTORS</h2><p>Supplier risk.</p><p style="text-align:center">4</p></body></html>'''.encode()


def parse(raw,version=NEW):
    return parse_sec_source('orion-2031','https://example.invalid/orion/annual',raw,source_snapshot_id='orion-frozen',parser_version=version)

class TocContentCellTests(unittest.TestCase):
    def test_spacers_do_not_remove_items_or_confuse_title_and_page(self):
        raw=fixture();old,new=parse(raw,OLD),parse(raw)
        self.assertEqual([e.kind for e in old.toc_entries],['part'])
        entries=[e for e in new.toc_entries if e.kind=='item']
        self.assertEqual([(e.number,e.title,e.source_anchor,e.reported_page) for e in entries],
                         [('1','PRODUCTS AND SERVICES','products',3),('1A','RISK FACTORS','risk',4)])
        self.assertEqual(old.blocks,new.blocks)
        self.assertEqual(old.anchors,new.anchors)
        nodes=[n for n in build_legal_outline(new).nodes if n.kind=='item']
        self.assertEqual([n.item_number for n in nodes],['1','1A'])
        self.assertEqual([e for e in parse(fixture(False)).toc_entries if e.kind=='item'],entries)

    def test_conflicting_links_remain_errors_after_spacer_normalization(self):
        parsed=parse(fixture(conflict=True));entries=[e for e in parsed.toc_entries if e.kind=='item']
        self.assertIsNone(entries[0].source_anchor)
        self.assertIn('toc_row_anchor_conflict',{d.code for d in parsed.parser_diagnostics})

    def test_hidden_leading_cell_cannot_supply_item_number(self):
        raw=fixture(False).replace(b'<td>Item 1.</td>',b'<td hidden>ITEM 77.</td><td>Item 1.</td>')
        parsed=parse(raw)
        self.assertEqual([e.number for e in parsed.toc_entries if e.kind=='item'],['1','1A'])

    def test_combined_item_title_cell_is_not_replaced_by_page(self):
        raw=fixture(False).replace(b'<td>Item 1.</td><td><a href="#products">PRODUCTS<br>AND SERVICES</a></td>',
            b'<td><a href="#products">Item 1. PRODUCTS<br>AND SERVICES</a></td>')
        old,new=parse(raw,OLD),parse(raw)
        self.assertEqual(next(e.title for e in old.toc_entries if e.kind=='item'),'3')
        entry=next(e for e in new.toc_entries if e.kind=='item')
        self.assertEqual((entry.title,entry.reported_page,entry.source_anchor),('PRODUCTS AND SERVICES',3,'products'))

    def test_hidden_links_cannot_create_anchor_conflicts(self):
        raw=fixture().replace(b'<a href="#products">3</a>',
            b'<a hidden href="#hidden-target">Invisible</a><a href="#products">3</a>')
        parsed=parse(raw)
        entry=next(e for e in parsed.toc_entries if e.kind=='item')
        self.assertEqual(entry.source_anchor,'products')
        self.assertNotIn('toc_row_anchor_conflict',{d.code for d in parsed.parser_diagnostics})

    def test_same_input_replays_and_package_preserves_complete_toc(self):
        raw=fixture();scope=identity(raw,parser_version=NEW,company_id='synthetic-orion',report_period_end='2031-09-30')
        with tempfile.TemporaryDirectory() as td:
            roots=[Path(td)/'one',Path(td)/'two']
            for root in roots:
                build_parsed_package(raw,scope,root)
                verify_parsed_package(root,expected_source=scope)
            self.assertEqual({p.relative_to(roots[0]):p.read_bytes() for p in roots[0].rglob('*') if p.is_file()},
                             {p.relative_to(roots[1]):p.read_bytes() for p in roots[1].rglob('*') if p.is_file()})
