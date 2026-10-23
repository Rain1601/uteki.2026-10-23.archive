"""Observable document retrieval behavior against the installed package."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from uteki.data_platform.contracts.documents import BlockQuery, BlockRef, DocumentPackage
from uteki.data_platform.content.store import ContentStoreError
from uteki.data_platform.documents import DocumentStore, DocumentStoreError


REPO=Path(__file__).resolve().parents[3]
EXAMPLE=runpy.run_path(str(REPO/'examples/data_platform/documents.py'))


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='uteki-document-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.store=DocumentStore.initialize(self.root)
        self.addCleanup(lambda:self.store.close())
        self.package=EXAMPLE['fixture'](self.store)
        self.store.publish(self.package)

    def changed(self, change):
        value=self.package.model_dump(mode='json');change(value)
        return DocumentPackage.model_validate_json(json.dumps(value))

    def query(self, **kwargs):
        return self.store.query_blocks(BlockQuery(parse_id='demo-parse-v1',**kwargs))

    def reference(self, block='table', parse='demo-parse-v1', material='demo-material'):
        return BlockRef(material_id=material,parse_id=parse,block_id=block)

    def test_directory_tags_table_context_and_original_bytes(self):
        found=self.store.find_materials(entity_id='demo-company',reporting_period='FY2025',published_from='2026-01-10',published_to='2026-01-10')
        self.assertEqual([m['material_id'] for m in found['items']],['demo-material'])
        self.assertEqual(self.store.find_materials(entity_id='other')['items'],[])
        self.assertEqual(self.store.find_materials(published_from='2026-01-11')['items'],[])
        schema=self.store.get_schema('demo-parse-v1')
        child=schema['directory']['nodes'][0]['children'][0]
        self.assertEqual(child['path'],['经营情况','收入构成'])
        self.assertEqual(child['block_count'],5)
        self.assertEqual(schema['processing']['ocr']['complete'],1)
        self.assertEqual(schema['processing']['ocr']['not_applicable'],4)
        self.assertEqual(schema['tags']['completed_without_match'],4)
        self.assertEqual(schema['completed_at'],self.package.parse.model_dump(mode='json')['completed_at'])
        self.assertEqual(self.query(directory_path=('经营情况',))['items'],[])
        query=self.query(directory_path=('经营情况',),include_descendants=True,tags=('finance.revenue','business.region'),tag_match='all',types=('table',))
        self.assertEqual([i['ref']['block_id'] for i in query['items']],['table'])
        result=self.store.read_block(BlockRef.model_validate(query['items'][0]['ref']))
        self.assertEqual([c['text'] for c in result['block']['table']['cells']],['Region','Revenue','East','120','West','80'])
        self.assertEqual([c['relation'] for c in result['context']],['caption','footnote'])
        self.assertIn('合并口径',result['context'][1]['block']['text'])
        self.assertEqual(self.store.read_source('demo-parse-v1'),EXAMPLE['SOURCE'])
        self.assertEqual(self.store.read_resource(self.reference('chart'),'chart-original'),EXAMPLE['IMAGE'])

    def test_fulltext_chinese_short_words_and_derived_description_are_distinct(self):
        revenue=self.query(text='收入',text_match='substring')
        self.assertEqual([r['ref']['block_id'] for r in revenue['items']],['caption','chart'])
        self.assertEqual(revenue['items'][1]['matches'][0]['origin'],'ocr')
        self.assertEqual([r['ref']['block_id'] for r in self.query(text='收入构成',text_match='substring')['items']],['caption'])
        self.assertEqual(self.query(text='trend',text_match='phrase')['items'],[])
        description=self.query(text='trend',text_origins=('description',))
        self.assertEqual(description['items'][0]['matches'][0]['origin'],'description')
        self.assertEqual(self.query(text='Revenue',types=('table',))['items'][0]['ref']['block_id'],'table')
        self.assertEqual(self.query(text='" OR anything') ['items'],[])

    def test_old_references_survive_source_change_default_switch_and_reopen(self):
        original=self.store.read_block(self.reference())
        new_ref=self.store.content.put_object(EXAMPLE['SOURCE'].replace(b'120',b'121')).model_dump(mode='json')
        def update(d):
            d['source'].update(source_version_id='demo-source-v2',object_ref=new_ref,revision_of='demo-source-v1')
            d['parse'].update(parse_id='demo-parse-v2',source_version_id='demo-source-v2')
            d['blocks'][1]['table']['cells'][3]['text']='121'
        newer=self.changed(update);self.store.publish(newer)
        self.assertEqual(self.store.default_parse('demo-material'),'demo-parse-v2')
        self.assertTrue(self.store.publish(self.package)['reused'])
        self.assertEqual(self.store.default_parse('demo-material'),'demo-parse-v2')
        with DocumentStore.open(self.root) as reopened:
            self.assertEqual(reopened.read_block(self.reference()),original)
            self.assertEqual(reopened.read_block(self.reference(parse='demo-parse-v2'))['block']['table']['cells'][3]['text'],'121')
            self.assertEqual(reopened.read_source('demo-parse-v1'),EXAMPLE['SOURCE'])
            self.assertEqual(reopened.find_materials()['returned'],1)

    def test_ocr_table_is_not_indexed_as_native_source(self):
        def update(d):
            d['parse']['parse_id']='ocr-table'
            table=d['blocks'][1]
            table['text_origin']='ocr'
            table['ocr']={'status':'complete','text':'Region Revenue East 120 West 80','processor_ref':'synthetic-parser'}
        self.store.publish(self.changed(update))
        native=self.store.query_blocks(BlockQuery(parse_id='ocr-table',types=('table',),text='Revenue',text_origins=('source',)))
        self.assertEqual(native['items'],[])
        ocr=self.store.query_blocks(BlockQuery(parse_id='ocr-table',types=('table',),text='Revenue',text_origins=('ocr',)))
        self.assertEqual([r['ref']['block_id'] for r in ocr['items']],['table'])
        self.assertEqual(ocr['items'][0]['matches'][0]['origin'],'ocr')

    def test_inspection_views_show_source_date_and_accept_string_number_filters(self):
        # Browser query strings are strings. JSON-derived numeric columns need affinity.
        date=self.store._db.execute('SELECT published_at FROM inspect_materials').fetchone()[0]
        self.assertEqual(date,'2026-01-10')
        cells=self.store._db.execute('SELECT text FROM inspect_table_cells WHERE block_id=? AND row_index=? ORDER BY column_index',
                                    ('table','1')).fetchall()
        self.assertEqual([r[0] for r in cells],['East','120'])
        shown=self.store._db.execute('SELECT material_name,directory_paths,content_preview FROM inspect_blocks WHERE block_id=?',('table',)).fetchone()
        self.assertEqual(shown['material_name'],'合成年度材料')
        self.assertEqual(json.loads(shown['directory_paths']),[['经营情况','收入构成']])
        self.assertIn('East | 120',shown['content_preview'])

    def test_path_ambiguity_is_explicit_and_multiple_memberships_do_not_duplicate(self):
        def update(d):
            d['parse']['parse_id']='duplicate-path'
            node=dict(d['parse']['directory_schema']['nodes'][1]);node['node_id']='revenue-second';node['order']=2
            d['parse']['directory_schema']['nodes'].append(node)
            d['blocks'][1]['directory_node_ids'].append('revenue-second')
        p=self.changed(update);self.store.publish(p)
        with self.assertRaises(DocumentStoreError) as ctx:
            self.store.resolve_directory('duplicate-path',('经营情况','收入构成'))
        self.assertEqual(ctx.exception.code,'AMBIGUOUS_PATH')
        self.assertEqual(len(ctx.exception.details['candidates']),2)
        result=self.store.query_blocks(BlockQuery(parse_id='duplicate-path',directory_node_id='operations',include_descendants=True,types=('table',)))
        self.assertEqual(result['returned'],1)

    def test_tags_any_all_and_directory_type_constraints(self):
        def update(d):
            d['parse']['parse_id']='tag-test'
            d['blocks'][0]['tagging']['tag_ids']=['finance.revenue']
        self.store.publish(self.changed(update))
        common=dict(parse_id='tag-test',tags=('finance.revenue','business.region'))
        self.assertEqual(self.store.query_blocks(BlockQuery(**common,tag_match='any'))['returned'],2)
        self.assertEqual(self.store.query_blocks(BlockQuery(**common,tag_match='all'))['returned'],1)
        self.assertEqual(self.store.query_blocks(BlockQuery(**common,types=('text',)))['returned'],1)
        with self.assertRaises(DocumentStoreError) as ctx:self.query(tags=('made-up',))
        self.assertEqual(ctx.exception.code,'UNKNOWN_TAG')

    def test_cursor_continuation_rejects_changed_query_and_version(self):
        request=BlockQuery(parse_id='demo-parse-v1',limit=2)
        first=self.store.query_blocks(request);second=self.store.query_blocks(request,cursor=first['next_cursor'])
        third=self.store.query_blocks(request,cursor=second['next_cursor'])
        self.assertEqual([x['ref']['block_id'] for page in (first,second,third) for x in page['items']],['caption','table','footnote','chart','link'])
        self.assertIsNone(third['next_cursor'])
        with self.assertRaises(DocumentStoreError) as ctx:
            self.store.query_blocks(BlockQuery(parse_id='demo-parse-v1',limit=3),cursor=first['next_cursor'])
        self.assertEqual(ctx.exception.code,'CURSOR_MISMATCH')
        with self.assertRaises(DocumentStoreError):self.store.query_blocks(request,cursor='broken')
        with self.assertRaises(DocumentStoreError) as ctx:self.store.read_block(self.reference(),max_bytes=256)
        self.assertEqual(ctx.exception.code,'RESULT_TOO_LARGE')

    def test_incorrect_parse_material_and_unknown_block_fail(self):
        for reference in (self.reference(material='wrong-material'),self.reference(parse='missing-parse'),self.reference(block='missing-block')):
            with self.subTest(reference=reference),self.assertRaises(DocumentStoreError):self.store.read_block(reference)
        with self.assertRaises(DocumentStoreError):self.store.read_resource(self.reference('chart'),'missing-resource')

    def test_schema_distinguishes_unprocessed_failed_and_completed_without_tags(self):
        def update(d):
            d['parse'].update(parse_id='partial-tags',status='partial',issues=['Tagging incomplete'])
            d['blocks'][0]['tagging']={'status':'not_processed'}
            d['blocks'][3]['tagging']={'status':'failed','processor_ref':'synthetic-tags','issues':['Synthetic tagging failure']}
        self.store.publish(self.changed(update))
        schema=self.store.get_schema('partial-tags')
        self.assertEqual(schema['processing']['tagging'],dict(complete=3,partial=0,not_processed=1,failed=1,not_applicable=0))
        self.assertEqual(schema['tags']['completed_without_match'],2)
        self.assertEqual(len(schema['tags']['available']),2)
        self.assertEqual(schema['status'],'partial')

    def test_independent_pdf_package_retains_multiple_regions_and_text_without_directory(self):
        # Storage receives already-extracted locations; these synthetic bytes
        # are deliberately not a PDF parser or OCR acceptance test.
        source=self.store.content.put_object(b'%PDF synthetic storage-only fixture').model_dump(mode='json')
        def update(d):
            d['material']['material_id']='independent-material'
            d['source'].update(source_version_id='independent-source',material_id='independent-material',format='pdf',object_ref=source)
            d['parse'].update(parse_id='independent-parse',material_id='independent-material',source_version_id='independent-source',
                directory_schema={'has_source_directory':False,'status':'not_applicable'})
            block=d['blocks'][1]
            block.update(directory_assignment='no_source_directory',directory_node_ids=[],related_blocks=[],locations=[
                {'kind':'pdf_region','page_number':2,'page_label':'i','bbox':[10,20,200,300]},
                {'kind':'pdf_region','page_number':3,'page_label':'ii','bbox':[10,10,200,100]}])
            d['blocks']=[block]
        self.store.publish(self.changed(update))
        query=BlockQuery(parse_id='independent-parse',types=('table',),text='Revenue')
        reference=BlockRef.model_validate(self.store.query_blocks(query)['items'][0]['ref'])
        result=self.store.read_block(reference)
        self.assertEqual([loc['page_number'] for loc in result['block']['locations']],[2,3])
        self.assertEqual(self.store.get_schema('independent-parse')['directory']['nodes'],[])
        self.assertEqual(self.store.read_source('independent-parse'),b'%PDF synthetic storage-only fixture')

    def test_contract_rejects_cycles_missing_directory_unknown_labels_and_false_complete(self):
        changes=[
            lambda d:d['parse']['directory_schema']['nodes'][0].update(parent_id='revenue'),
            lambda d:d['parse']['directory_schema'].update(nodes=[]),
            lambda d:d['blocks'][0].update(directory_node_ids=['missing']),
            lambda d:d['blocks'][1]['tagging'].update(tag_ids=['unknown']),
            lambda d:d['blocks'][0].update(processor_ref='not-registered'),
            lambda d:d['blocks'][3].update(ocr={'status':'not_processed'}),
            lambda d:d['blocks'][1]['table']['cells'][1].update(column=0),
            lambda d:d['blocks'][0].update(related_blocks=[{'block_id':'missing','relation':'context'}]),
            lambda d:d['blocks'][0].update(locations=[{'kind':'pdf_region','page_number':1,'bbox':[0,0,100,100]}]),
        ]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValidationError):self.changed(change)
        def partial(d):
            d['parse'].update(parse_id='unprocessed',status='partial',issues=['OCR not processed'])
            d['blocks'][3].update(ocr={'status':'not_processed'})
        self.store.publish(self.changed(partial))
        self.assertEqual(self.store.read_block(self.reference('chart','unprocessed'))['block']['ocr']['status'],'not_processed')

    def test_queries_do_not_read_original_or_frozen_package_and_reindex_does(self):
        with patch.object(self.store.content,'read_object',side_effect=AssertionError('query attempted file reprocessing')):
            self.store.find_materials();self.store.get_schema('demo-parse-v1')
            self.store.browse_directory('demo-parse-v1',parent_id='operations')
            self.query(text='Revenue');self.store.read_block(self.reference())
        before=self.store.read_block(self.reference())
        # An explicit interrupted repair rolls back to the previous usable projection.
        def fail(phase):
            if phase=='block_written':raise RuntimeError('controlled repair failure')
        with self.assertRaises(RuntimeError):self.store.reindex('demo-parse-v1',checkpoint=fail)
        self.assertEqual(self.store.read_block(self.reference()),before)
        self.store._db.execute("UPDATE blocks SET payload=? WHERE parse_id=? AND block_id=?",
                               ('{}','demo-parse-v1','table'))
        with self.assertRaises(DocumentStoreError) as ctx:self.store.read_block(self.reference())
        self.assertEqual(ctx.exception.code,'STORE_CORRUPT')
        with patch.object(self.store.content,'read_object',wraps=self.store.content.read_object) as read:
            self.assertEqual(self.store.reindex('demo-parse-v1')['blocks'],5)
            self.assertEqual(read.call_count,1)  # Frozen package only, never the original.
        self.assertEqual(self.store.read_block(self.reference()),before)
        self.assertEqual(self.query(text='Revenue',types=('table',))['returned'],1)

    def test_controlled_publication_failure_and_identity_conflicts(self):
        p=self.changed(lambda d:d['parse'].update(parse_id='interrupted'))
        def fail(phase):
            if phase=='projection_written':raise RuntimeError('controlled publish failure')
        with self.assertRaises(RuntimeError):self.store.publish(p,checkpoint=fail)
        with self.assertRaises(DocumentStoreError):self.store.get_schema('interrupted')
        self.assertEqual(self.store.default_parse('demo-material'),'demo-parse-v1')
        self.assertEqual(self.store.publish(p)['parse_id'],'interrupted')
        changed=self.changed(lambda d:d['blocks'][0].update(text='different content same parse ID'))
        with self.assertRaises(DocumentStoreError) as ctx:self.store.publish(changed)
        self.assertEqual(ctx.exception.code,'IDENTITY_CONFLICT')
        self.assertEqual(self.store.read_block(self.reference('caption'))['block']['text'],self.package.blocks[0].text)

    def test_process_exit_before_and_after_commit_and_same_id_replay(self):
        script='''
import os,sys
from pathlib import Path
from uteki.data_platform.contracts.documents import DocumentPackage
from uteki.data_platform.documents import DocumentStore
with DocumentStore.open(Path(sys.argv[1])) as store:
    p=DocumentPackage.model_validate_json(Path(sys.argv[2]).read_bytes())
    def stop(phase):
        if phase==sys.argv[3]:os._exit(71)
    store.publish(p,checkpoint=stop)
'''
        for phase in ('block_written','after_commit'):
            identity='process-'+phase
            p=self.changed(lambda d:d['parse'].update(parse_id=identity))
            path=self.root/(identity+'.json');path.write_bytes(p.canonical_bytes())
            result=subprocess.run([sys.executable,'-I','-c',script,str(self.root),str(path),phase],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,71,result.stderr)
            with DocumentStore.open(self.root) as reopened:
                if phase=='block_written':
                    with self.assertRaises(DocumentStoreError):reopened.get_schema(identity)
                else:self.assertEqual(reopened.get_schema(identity)['parse_id'],identity)
                publication=reopened.publish(p)
                self.assertEqual(publication['reused'],phase=='after_commit')
                self.assertEqual(reopened.read_block(self.reference(parse=identity))['block']['block_id'],'table')
                self.assertEqual(reopened.read_source('demo-parse-v1'),EXAMPLE['SOURCE'])

    def test_missing_and_corrupt_bytes_are_not_repaired_and_root_is_explicit(self):
        for ref,read in [(self.package.source.object_ref,lambda:self.store.read_source('demo-parse-v1')),
                         (self.package.blocks[3].resources[0].object_ref,lambda:self.store.read_resource(self.reference('chart'),'chart-original'))]:
            path=self.root/'objects'/'sha256'/ref.sha256[:2]/ref.sha256
            # CAS is deliberately read-only. Only the synthetic corruption test
            # makes this one temporary file writable; production permissions stay.
            original=path.read_bytes();path.chmod(0o600);path.write_bytes(b'corrupt')
            with self.assertRaises(ContentStoreError):read()
            self.assertEqual(path.read_bytes(),b'corrupt')
            path.unlink()
            with self.assertRaises(ContentStoreError):read()
            self.store.content.put_object(original)
        with self.assertRaises(ContentStoreError):DocumentStore.open('.')
        missing=self.root/'uninitialized';missing.mkdir()
        with self.assertRaises(DocumentStoreError):DocumentStore.open(missing)
        self.assertFalse((missing/'documents.sqlite').exists())


if __name__=='__main__':unittest.main()
