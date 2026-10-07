"""Independent company/period fixtures; no source-specific heading lists."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_parsed_package import identity
from tests.unit.test_scoped_query_service import make_scoped_dataset
from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import save
from uteki.infrastructure.research_data.query_service import QueryDataPort


def filing(*, nav='<h5><a href="#toc">Table of Contents</a></h5>'):
    return (f'<html><body id="whole">{nav}<p id="toc">TABLE OF CONTENTS</p><p>Orion Research Limited</p>'
        '<table><tr><td>PART I</td></tr>' + ''.join(
            f'<tr><td>ITEM {n}.</td><td></td><td><a href="#i{n}">{title}</a></td><td></td><td>{n+2}</td><td></td></tr>'
            for n, title in ((1, 'PRODUCTS'), (2, 'RISKS'), (3, 'LOCATIONS'))) + '</table>'
        '<p>The Table of Contents helps readers find topics.</p><h2>PART I</h2>' + ''.join(
            f'<table><tr><td id="i{n}">ITEM {n}.</td><td><div><b>{title}</b></div></td></tr></table><p>Body {n}.</p>'
            for n, title in ((1, 'PRODUCTS'), (2, 'RISKS'), (3, 'LOCATIONS'))) + nav + '</body></html>')


def parse(raw, version='sec-source-blocks-v0.1.10'):
    parsed = parse_sec_source('orion-2031', 'https://example.invalid/orion/annual', raw.encode(),
        source_snapshot_id='orion-frozen-2031', form_type='20-F', parser_version=version)
    return parsed, build_legal_outline(parsed)


class NavigationStageTests(unittest.TestCase):
    def test_only_repeated_verified_links_are_marked_and_source_content_is_unchanged(self):
        raw = filing()
        old, _ = parse(raw, 'sec-source-blocks-v0.1.8')
        new, _ = parse(raw, 'sec-source-blocks-v0.1.9')
        marked = [b for b in new.blocks if b.layout_role == 'repeated_navigation']
        self.assertEqual(len(marked), 2)
        self.assertEqual(old.anchors, new.anchors)
        self.assertEqual([{k:v for k,v in asdict(b).items() if k != 'layout_role'} for b in old.blocks],
                         [{k:v for k,v in asdict(b).items() if k != 'layout_role'} for b in new.blocks])
        self.assertTrue(all(b.layout_role is None for b in new.blocks
                            if b.text in ('TABLE OF CONTENTS', 'The Table of Contents helps readers find topics.')))

    def test_unknown_hidden_duplicate_whole_document_and_single_targets_are_not_marked(self):
        cases = [filing().replace('href="#toc"', 'href="#missing"'),
                 filing().replace('href="#toc"', 'href="#whole"'),
                 filing().replace('<p id="toc">', '<p hidden id="toc">'),
                 filing().replace('</body>', '<p id="toc">Duplicate</p></body>'),
                 filing().replace('<h5><a href="#toc">Table of Contents</a></h5>', '', 1),
                 filing(nav='<h5><a href="#toc">Table of Contents 7</a></h5>')]
        for tag in ('script', 'style', 'noscript'):
            cases.append(filing().replace('<p id="toc">TABLE OF CONTENTS</p><p>Orion Research Limited</p>',
                f'<{tag} id="toc"></{tag}><p>TABLE OF CONTENTS</p>'))
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                self.assertFalse(any(b.layout_role == 'repeated_navigation' for b in parse(raw)[0].blocks))

    def test_reader_filters_actual_payload_and_exposes_omissions_without_skipping_to_body(self):
        raw = filing().encode()
        with tempfile.TemporaryDirectory() as temp:
            readers = []
            for version in ('sec-source-blocks-v0.1.8', 'sec-source-blocks-v0.1.9'):
                folder = Path(temp)/version
                package.build_parsed_package(raw, identity(raw, parser_version=version, form_type='20-F'), folder)
                readers.append(DocumentReader(folder))
            old, new = readers
            old_root, new_root = old.index['nodes'][0]['node_id'], new.index['nodes'][0]['node_id']
            self.assertEqual(old.search(old_root, 'Table of Contents')['total'], 4)
            result = new.search(new_root, 'Table of Contents')
            self.assertEqual((result['total'], result['omitted_block_count']), (2, 2))
            for block in new.blocks:
                if block.get('layout_role') != 'repeated_navigation':
                    continue
                page = new.read(new_root, block['block_id'], 1)
                self.assertEqual(page['blocks'], [])
                self.assertEqual(page['reading_groups'], [])
                self.assertEqual(page['omitted_block_ids'], [block['block_id']])
            self.assertIsNone(page['next_block_id'])
            self.assertEqual(len(new.blocks), len(old.blocks))


class TableItemStageTests(unittest.TestCase):
    def test_spacer_toc_and_table_headers_create_nodes_without_changing_any_block_or_anchor(self):
        raw = filing()
        a, ia = parse(raw, 'sec-source-blocks-v0.1.9')
        b, ib = parse(raw)
        self.assertEqual(a.blocks, b.blocks)
        self.assertEqual(a.anchors, b.anchors)
        self.assertEqual(sum(n.kind == 'item' for n in ia.nodes), 0)
        nodes = [n for n in ib.nodes if n.kind == 'item']
        self.assertEqual([(n.item_number, n.title) for n in nodes], [('1', 'PRODUCTS'), ('2', 'RISKS'), ('3', 'LOCATIONS')])
        self.assertEqual([e.reported_page for e in b.toc_entries if e.kind == 'item'], [3, 4, 5])
        self.assertEqual([(n.source_anchor, n.reported_page) for n in nodes], [('i1', 3), ('i2', 4), ('i3', 5)])
        by_id = {block.block_id:block for block in b.blocks}
        self.assertTrue(all(by_id[n.start_block_id].type == 'table' for n in nodes))
        self.assertIn('outline_ranges_are_navigation', {d.code for d in ib.diagnostics})

    def test_short_and_long_item_references_in_prose_do_not_truncate_a_table_heading_range(self):
        for tail in ('', 'Narrative sentence. ' * 20):
            prose = 'Item 2 as well as other requirements are discussed here. ' + tail
            parsed, index = parse(filing().replace('<p>Body 2.</p>', f'<p>{prose}</p><p>Body 2.</p>'))
            two = next(n for n in index.nodes if n.item_number == '2')
            self.assertEqual(next(b.text for b in parsed.blocks if b.block_id == two.end_block_id), 'Body 2.')

    def test_wrong_or_missing_anchor_does_not_absorb_rejected_item_into_previous_range(self):
        for link in ('href="#wrong"', ''):
            raw = filing().replace('href="#i2"', link)
            parsed, index = parse(raw)
            nodes = {n.item_number:n for n in index.nodes if n.kind == 'item'}
            self.assertEqual(set(nodes), {'1', '3'})
            self.assertEqual(next(b.text for b in parsed.blocks if b.block_id == nodes['1'].end_block_id), 'Body 1.')
            self.assertIn('table_item_heading_rejected', {d.code for d in index.diagnostics})

    def test_conflicting_body_or_duplicate_toc_identity_is_not_published(self):
        duplicate = '<table><tr><td>ITEM 2.</td><td>DIFFERENT TITLE</td></tr></table>'
        conflict = filing().replace('<p>Body 2.</p>', '<p>Body 2.</p>'+duplicate)
        duplicate_toc = filing().replace('<tr><td>PART I</td></tr>',
            '<tr><td>PART I</td></tr><tr><td>ITEM 2.</td><td><a href="#i2">RISKS</a></td><td>4</td></tr>')
        for raw in (conflict, duplicate_toc):
            parsed, index = parse(raw)
            self.assertNotIn('2', {n.item_number for n in index.nodes})
            one = next(n for n in index.nodes if n.item_number == '1')
            self.assertEqual(next(b.text for b in parsed.blocks if b.block_id == one.end_block_id), 'Body 1.')

    def test_nested_non_latin_unknown_part_and_financial_shapes_are_rejected(self):
        table = '<table><tr><td id="i2">ITEM 2.</td><td><div><b>RISKS</b></div></td></tr></table>'
        replacements = [f'<table><tr><td>{table}</td></tr></table>',
            table.replace('RISKS', '风险'), table.replace('</table>', '<tr><td>Amount</td><td>17</td></tr></table>'),
            table.replace('ITEM 2.', 'ITEM 98.')]
        for replacement in replacements:
            parsed, index = parse(filing().replace(table, replacement))
            self.assertNotIn('2', {n.item_number for n in index.nodes})
            self.assertIn('table_item_heading_rejected', {d.code for d in index.diagnostics})
        _, index = parse(filing().replace('<h2>PART I</h2>', '<h2>PART II</h2>'))
        self.assertFalse(any(n.kind == 'item' for n in index.nodes))


class NavigationQueryBoundaryTests(unittest.TestCase):
    def test_layout_only_read_context_node_end_cursor_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_scoped_dataset(root)
            folder = root/'indexes/acme-annual'
            index = json.loads((folder/'index.json').read_bytes())
            index['parser_version'] = 'sec-source-blocks-v0.1.9'
            save(folder/'index.json', index)
            blocks = [json.loads(line) for line in (folder/'blocks.jsonl').read_text().splitlines()]
            for position in (1, 2, 9):
                blocks[position].update(text='Table of Contents', layout_role='repeated_navigation')
            (folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in blocks))
            save(folder/'manifest.json', {'status':'candidate', 'artifacts':{name:{'sha256':digest((folder/name).read_bytes())}
                 for name in ('index.json','blocks.jsonl')}})
            manifest = json.loads((root/'manifest.json').read_bytes())
            manifest['files'] = {name:digest((root/name).read_bytes()) for name in manifest['files']}
            save(root/'manifest.json', manifest)
            with QueryDataPort(root) as owner:
                port = owner.scoped({'snapshot_id':owner.snapshot_id, 'company_ids':['acme'],
                    'source_snapshot_ids':['acme-annual'], 'source_policy_id':'local-frozen-v1',
                    'knowledge_cutoff':'2032-06-01', 'include_candidates':True})
                page = port.read_context(source_snapshot_id='acme-annual', block_id='b1')
                self.assertEqual((page['status'], page['blocks'], page['not_disclosed']), ('layout_only', [], False))
                first = port.read_source({'source_snapshot_id':'acme-annual', 'node_id':'business', 'start_block_id':'b1', 'count':1})
                second = port.read_source({'source_snapshot_id':'acme-annual', 'node_id':'business', 'cursor':first['next_cursor'], 'count':1})
                self.assertEqual(second['omitted_block_ids'], ['b2'])
                self.assertEqual(second['status'], 'layout_only')
                self.assertTrue(second['node_complete'])
                self.assertIsNone(second['next_cursor'])
                tail = port.read_context(source_snapshot_id='acme-annual', block_id='b9')
                self.assertEqual(tail['blocks'], [])
                self.assertIsNone(tail['next_cursor'])
                with self.assertRaises(ValueError):
                    port.read_source({'source_snapshot_id':'acme-annual', 'node_id':'business', 'start_block_id':'b3'})
                with self.assertRaises(ValueError):
                    port.read_context(source_snapshot_id='other-annual', block_id='b1')


if __name__ == '__main__':
    unittest.main()
