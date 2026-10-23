"""Structure/reading boundaries. Real PDF quality is reviewed separately."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from uteki.data_platform.contracts.documents import BlockQuery, BlockRef, DocumentPackage
from uteki.data_platform.documents import DocumentStore
from uteki.data_platform.documents.directory import build_sections, _contents_table
from uteki.data_platform.documents.pdf import _checked_table
from uteki.data_platform.documents.passages import build_passages, attach_text_lines
from uteki.data_platform.documents.query import DocumentStoreError

EXAMPLE = runpy.run_path(str(Path(__file__).parents[3]/'examples/data_platform/documents.py'))


class SectionTests(unittest.TestCase):
    def test_contents_filter_needs_source_context_and_multiple_outline_rows(self):
        titles=['Balance Sheets','Income Statements','Cash Flow Statements']
        native=[dict(title=t) for t in titles]
        loc=dict(kind='pdf_region',page_number=1,bbox=[10,50,400,100])
        table=dict(type='table',locations=[loc],table=dict(cells=[
            cell for row,title in enumerate(titles) for cell in
            (dict(row=row,column=0,text=title),dict(row=row,column=1,text=str(10+row)))]))
        heading=dict(type='text',role='heading',text='Table of Contents',locations=[loc])
        self.assertTrue(_contents_table(table,native,heading))
        heading['text']='Financial Performance'
        self.assertFalse(_contents_table(table,native,heading))
        self.assertTrue(_contents_table(table,native,None,'Index to Financial Statements'))
        table['table']['cells'][1]['text']='12,000'
        self.assertFalse(_contents_table(table,native,None,'Index to Financial Statements'))

    def test_conflicting_table_spans_fail_without_choosing_or_mutating_cells(self):
        cells=[dict(row=0,column=0,row_span=1,column_span=2,text='A'),
               dict(row=0,column=1,row_span=1,column_span=1,text='B')]
        original=deepcopy(cells)
        result=_checked_table(cells,1,2)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['cells'],[])
        self.assertIn('overlapping cells',result['issues'][0])
        self.assertEqual(cells,original)
        cells[0]['column_span']=1
        self.assertEqual(_checked_table(cells,1,2)['status'],'complete')

    def test_bookmark_protects_header_and_unmatched_destination_keeps_scope(self):
        blocks=[]
        for i,(text,role,y) in enumerate([('Chapter One','header',10),('Body one','body',30),('Body two','body',90)]):
            blocks.append(dict(block_id=str(i),order=i,type='text',role=role,text=text,
                locations=[dict(kind='pdf_region',page_number=1,bbox=[10,y,300,y+10])]))
        native=dict(has_source_directory=True,status='complete',issues=[],nodes=[
            dict(node_id='one',parent_id=None,title='Chapter One',order=0,basis='source_directory',locations=[dict(kind='pdf_destination',page_number=1,y=10)]),
            dict(node_id='two',parent_id=None,title='A bookmark alias',order=1,basis='source_directory',locations=[dict(kind='pdf_destination',page_number=1,y=80)])])
        directory,result=build_sections(blocks,[],native)
        self.assertEqual(result[0]['body_selection']['decision'],'keep')
        self.assertEqual(result[1]['directory_node_ids'],['one'])
        self.assertEqual(result[2]['directory_node_ids'],['two'])
        self.assertEqual(directory['nodes'][1]['hierarchy_basis'],'bookmark_destination_only')
        self.assertIn('outline_heading_unmatched:two',directory['issues'])

    def test_merged_subtitle_and_repeated_context_preserve_source(self):
        blocks, cells, nodes = [], [], []
        for page, title, rendered in ((1,'Statement A','Statement A'),
                                      (2,'Statement B','Statement B (in units)'),
                                      (3,'Statement C','Statement C extra words')):
            for i, (text, role) in enumerate((('Report issuer','heading'),(rendered,'heading'),
                                             ('See the accompanying notes.','body'))):
                bid=f'p{page}-{i}'
                loc=dict(kind='pdf_region',page_number=page,bbox=[20,20+i*30,400,30+i*30])
                blocks.append(dict(block_id=bid,order=len(blocks),type='text',role=role,text=text,locations=[loc]))
                cells.append(dict(text=text,font_name='bold' if role=='heading' else 'regular',
                    font_weight=700 if role=='heading' else 400,font_italic=False,location=loc))
            nodes.append(dict(node_id=f'outline-{page}',parent_id=None,title=title,order=page,
                basis='source_directory',locations=[dict(kind='pdf_destination',page_number=page,y=50)]))
        # Unobserved ancestors must precede descendants even when inserted last.
        nodes[0]['parent_id']='ancestor'
        nodes.append(dict(node_id='ancestor',parent_id=None,title='Root',order=0,
            basis='source_directory',locations=[dict(kind='pdf_destination',page_number=4,y=10)]))
        directory, result=build_sections(blocks,cells,
            dict(has_source_directory=True,status='complete',issues=[],nodes=nodes))
        order=[n['node_id'] for n in directory['nodes']]
        self.assertLess(order.index('ancestor'),order.index('outline-1'))
        self.assertEqual(result[0]['directory_node_ids'],['outline-1'])
        self.assertEqual(result[3]['directory_node_ids'],['outline-2'])
        self.assertEqual(result[3]['body_selection']['decision'],'keep')
        self.assertEqual(result[4]['text'],'Statement B (in units)')
        self.assertEqual(result[5]['directory_node_ids'],['outline-2'])
        self.assertIn('outline_heading_unmatched:outline-3',directory['issues'])
        self.assertEqual([b['text'] for b in blocks],[b['text'] for b in result])

    def test_native_outline_and_passages_keep_theme_with_all_paragraphs(self):
        texts = [('root','Operating exposure','heading','bold',700,False),
                 ('a','A long original heading can occupy multiple lines.','body','bold-italic',700,True),
                 ('a1','First paragraph.','body','regular',400,False),
                 ('a2','Second paragraph.','body','regular',400,False),
                 ('footer','Page 1','footer','regular',400,False),
                 ('b','Another heading using the same typography.','body','bold-italic',700,True),
                 ('b1','Different content.','body','regular',400,False)]
        blocks, cells = [], []
        for i,(bid,text,role,font,weight,italic) in enumerate(texts):
            loc=dict(kind='pdf_region',page_number=1 if i<3 else 2,bbox=[20,i*30,400,i*30+10])
            blocks.append(dict(block_id=bid,order=i,type='text',role=role,text=text,locations=[loc]))
            cells.append(dict(text=text,font_name=font,font_weight=weight,font_italic=italic,location=loc))
        native=dict(has_source_directory=True,status='complete',issues=[],nodes=[dict(node_id='outline',
            parent_id=None,title='Operating exposure',order=0,basis='source_directory',
            locations=[dict(kind='pdf_destination',page_number=1,y=0)])])
        original = deepcopy(blocks)
        directory, result = build_sections(blocks,cells,native)
        self.assertEqual([n['node_id'] for n in directory['nodes']],['outline'])
        self.assertEqual(result[2]['directory_node_ids'],result[3]['directory_node_ids'])
        self.assertEqual(result[2]['directory_node_ids'],result[6]['directory_node_ids'])
        groups=build_passages(result,cells,directory)
        self.assertEqual([g['block_ids'] for g in groups],[['a','a1','a2'],['b','b1']])
        self.assertEqual(result[4]['body_selection']['decision'],'exclude')
        self.assertEqual([b['text'] for b in result],[b['text'] for b in original])
        self.assertEqual(blocks,original)

    def test_passage_publication_reading_reopen_and_reference_validation(self):
        with tempfile.TemporaryDirectory() as root:
            with DocumentStore.initialize(Path(root)) as store:
                legacy=EXAMPLE['fixture'](store);raw=legacy.canonical_bytes();store.publish(legacy)
                value=json.loads(raw)
                value['parse'].update(parse_id='passages-v1',schema_version='document-v3',passages=[
                    dict(passage_id='first',directory_node_id='revenue',index=0,
                         block_ids=['caption','table','footnote'],grouping_basis='section_content'),
                    dict(passage_id='second',directory_node_id='revenue',index=1,
                         block_ids=['chart','link'],grouping_basis='section_content')])
                for node in value['parse']['directory_schema']['nodes']:
                    node['code']=node['node_id'].title()
                for block in value['blocks']:
                    block['body_selection']=dict(decision='keep',reason='source_content',policy_version='test')
                package=DocumentPackage.model_validate_json(json.dumps(value));store.publish(package,make_default=False)
                result=store.read_passage('passages-v1',path='Operations.Revenue.passages[0]')
                self.assertEqual([b['ref']['block_id'] for b in result['blocks']],['caption','table','footnote'])
                self.assertIn('Consolidated',result['text'])
                self.assertEqual(len(store.list_passages('passages-v1',code_path='Operations.Revenue')),2)
                self.assertEqual(store.list_passages('passages-v1',code_path='Operations'),[])
                self.assertEqual(store.get_schema('passages-v1')['content_summary']['passages'],2)
                with self.assertRaisesRegex(DocumentStoreError,'PASSAGES_NOT_AVAILABLE'):
                    store.read_passage('demo-parse-v1',passage_id='first')
                with self.assertRaisesRegex(DocumentStoreError,'INVALID_ARGUMENT'):
                    store.read_passage('passages-v1',path='Operations.Revenue.passages[-1]')
                with self.assertRaisesRegex(DocumentStoreError,'NOT_FOUND'):
                    store.read_passage('passages-v1',path='Operations.Revenue.passages[2]')
                with self.assertRaisesRegex(DocumentStoreError,'no partial passage'):
                    store.read_passage('passages-v1',passage_id='first',max_bytes=256)
                bad=deepcopy(value);bad['parse']['passages'][1]['block_ids'].append('footnote')
                with self.assertRaisesRegex(ValueError,'membership'):
                    DocumentPackage.model_validate_json(json.dumps(bad))
                bad=deepcopy(value);bad['parse']['schema_version']='document-v2'
                with self.assertRaisesRegex(ValueError,'require document-v3'):
                    DocumentPackage.model_validate_json(json.dumps(bad))
                bad=deepcopy(value);bad['parse']['passages'][1]['block_ids'].remove('link')
                with self.assertRaisesRegex(ValueError,'exactly once'):
                    DocumentPackage.model_validate_json(json.dumps(bad))
                bad=deepcopy(value)
                bad['parse']['passages'][0]['block_ids']=['chart','link']
                bad['parse']['passages'][1]['block_ids']=['caption','table','footnote']
                with self.assertRaisesRegex(ValueError,'reading order'):
                    DocumentPackage.model_validate_json(json.dumps(bad))
                store.reindex('passages-v1')
            with DocumentStore.open(Path(root)) as store:
                self.assertEqual(store.read_passage('passages-v1',passage_id='first'),result)
                self.assertEqual(store.export_package('demo-parse-v1').canonical_bytes(),raw)
                self.assertEqual(store.default_parse('demo-material'),'demo-parse-v1')

    def test_line_alignment_retains_coordinates_and_explicit_unmatched_line(self):
        loc=dict(kind='pdf_region',page_number=2,bbox=[10,10,400,60])
        block=dict(block_id='b',type='text',text='First line.\nSecond line.',locations=[loc])
        observations=[dict(text=text,location=dict(kind='pdf_region',page_number=2,bbox=[10,y,300,y+8]))
                      for y,text in [(10,'First line.'),(20,'Second line.'),(30,'Not in the block')]]
        attach_text_lines([block],observations)
        self.assertEqual(block['text_lines'][0]['char_range'],[0,11])
        self.assertEqual(block['text_lines'][1]['char_range'],[12,24])
        self.assertIsNone(block['text_lines'][2]['char_range'])
        self.assertEqual(block['text_lines'][1]['location'],observations[1]['location'])

    def test_versioned_read_path_filter_and_legacy_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            with DocumentStore.initialize(Path(root)) as store:
                legacy=EXAMPLE['fixture'](store)
                raw=legacy.canonical_bytes()
                self.assertNotIn(b'body_selection',raw)
                self.assertNotIn(b'heading_block_id',raw)
                self.assertNotIn('body_selection',legacy.blocks[0].model_dump(exclude_none=True))
                self.assertNotIn('code',legacy.parse.directory_schema.nodes[0].model_dump(exclude_none=True))
                store.publish(legacy)
                self.assertEqual(store.export_package('demo-parse-v1').canonical_bytes(),raw)
                with self.assertRaisesRegex(DocumentStoreError,'no recorded'):
                    store.query_blocks(BlockQuery(parse_id='demo-parse-v1',content_view='body'))
                value=json.loads(raw)
                value['parse'].update(parse_id='sections-v2',schema_version='document-v2')
                for node in value['parse']['directory_schema']['nodes']:
                    node['code']=node['node_id'].title()
                for block in value['blocks']:
                    block['body_selection']=dict(decision='keep',reason='source_content',policy_version='test')
                value['blocks'][-1]['body_selection'].update(decision='exclude',reason='page_footer')
                # More than one query page: section reading must not silently stop at 100.
                template=value['blocks'][0]
                for i in range(105):
                    b=deepcopy(template);b.update(block_id=f'paragraph-{i}',order=i+10,text=f'Paragraph {i}')
                    value['blocks'].append(b)
                store.publish(DocumentPackage.model_validate_json(json.dumps(value)))
                result=store.read_section('sections-v2',code_path='Operations.Revenue')
                ids=[b['ref']['block_id'] for b in result['blocks']]
                self.assertIn('paragraph-104',ids)
                self.assertNotIn('link',ids)
                self.assertIn('footnote',ids)
                self.assertIn('table',ids)
                all_result=store.read_section('sections-v2',node_id='revenue',content_view='all')
                self.assertIn('link',[b['ref']['block_id'] for b in all_result['blocks']])
                self.assertEqual(store.resolve_code_path('sections-v2','Revenue',scope_node_id='operations'),'revenue')
                self.assertEqual(store.read_block(BlockRef(material_id='demo-material',parse_id='sections-v2',block_id='link'))['block']['text'],'Report link')
                with self.assertRaisesRegex(DocumentStoreError,'no partial'):
                    store.read_section('sections-v2',node_id='revenue',max_bytes=256)
                first=store.query_blocks(BlockQuery(parse_id='sections-v2',content_view='all',limit=1))
                with self.assertRaisesRegex(DocumentStoreError,'same query'):
                    store.query_blocks(BlockQuery(parse_id='sections-v2',content_view='body',limit=1),cursor=first['next_cursor'])
            with DocumentStore.open(Path(root)) as store:
                self.assertEqual(store.export_package('demo-parse-v1').canonical_bytes(),raw)

    def test_invalid_new_contract_does_not_hide_missing_policy_or_reference(self):
        with tempfile.TemporaryDirectory() as root, DocumentStore.initialize(Path(root)) as store:
            value=EXAMPLE['fixture'](store).model_dump(mode='json')
            value['parse']['schema_version']='document-v2'
            with self.assertRaisesRegex(ValueError,'explicit body selection'):
                DocumentPackage.model_validate_json(json.dumps(value))
            value['parse']['schema_version']='document-v1'
            value['parse']['directory_schema']['nodes'][0]['heading_block_id']='missing'
            with self.assertRaisesRegex(ValueError,'missing block'):
                DocumentPackage.model_validate_json(json.dumps(value))


if __name__=='__main__':
    unittest.main()
