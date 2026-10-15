"""Behavioral HTML/source evidence checks against ordinarily installed code."""
import errno
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import io

from pydantic import ValidationError
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.content import ContentStore,ContentStoreError
from uteki.data_platform.content.publication import Publication
from uteki.data_platform.contracts.assets import Acquisition,ArtifactFile,BuildManifest,BuildRecipe,SnapshotRelation
from uteki.data_platform.contracts.common import CatalogError,SourceTime,canonical,digest
from uteki.data_platform.contracts.content import ObjectRef
from uteki.data_platform.contracts.evidence import HtmlEvidenceRef,HtmlLocator
from uteki.data_platform.build.dom import SourceDOM
from uteki.data_platform.build.html import parse_html
from uteki.data_platform.build.pipeline import build_bundle,build_html,html_recipe
from uteki.data_platform.connectors.official import acquire_html,store_acquisition
from uteki.data_platform.retrieval.content import HtmlReader

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/data_platform'
F=runpy.run_path(str(FIXTURES/'html_fixture.py'))
C=runpy.run_path(str(FIXTURES/'catalog_worker.py'))


class HtmlParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='uteki-html-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.store=ContentStore(self.root)

    def parsed(self,raw=None,missing=False):
        raw=raw or F['source']();inputs=F['inputs'](self.store,raw,missing=missing)
        return parse_html(raw,inputs,encoding='utf-8',form_type='synthetic'),inputs

    def test_source_text_hidden_content_and_complete_accounting(self):
        p,_=self.parsed();text=' '.join(b.text for b in p.blocks)
        self.assertIn('Exact source paragraph. Second line.',text)
        for hidden in ('Aria secret','Style secret','Hidden secret','Script secret','Noscript secret','Navigation must'):
            self.assertNotIn(hidden,text)
        counts=p.quality.counts
        self.assertEqual(counts['source_text_atoms'],counts['visible_text_atoms']+counts['excluded_text_atoms'])
        self.assertEqual(counts['visible_text_atoms'],counts['covered_text_atoms'])
        self.assertEqual(counts['unexplained_omissions'],0)
        self.assertTrue(any(e['reason']=='hidden_attribute' for e in p.quality.exclusions))

    def test_period_units_scale_sign_duplicates_nil_and_unknown(self):
        p,_=self.parsed();r={v.fact_id:v for v in p.records}
        self.assertEqual(r['r1'].value_decimal,'-12500');self.assertEqual(r['r2'].value_decimal,'10000')
        self.assertEqual(r['r1'].period,{'start':'2023-07-02','end':'2024-06-29'})
        self.assertNotEqual(r['r1'].period,r['r2'].period)
        self.assertEqual(r['r1'].unit,{'measures':('{http://www.xbrl.org/2003/iso4217}EUR',)})
        self.assertEqual(r['r1'].duplicate_group,r['r3'].duplicate_group)
        self.assertIsNotNone(r['r1'].duplicate_group);self.assertIsNone(r['r2'].duplicate_group)
        self.assertEqual(r['r4'].dimensions[0]['value'],'{https://example.com/taxonomy}North')
        self.assertEqual(r['r4'].unit['denominator'],('{http://www.xbrl.org/2003/instance}shares',))
        self.assertEqual(r['r5'].status,'nil');self.assertIsNone(r['r5'].value_decimal)
        self.assertEqual(r['r6'].value_decimal,'0');self.assertEqual(r['r7'].status,'unsupported')
        self.assertEqual(len(r),7)

    def test_table_span_headers_units_and_footnote_are_retained(self):
        p,_=self.parsed();table=p.tables[0];self.assertEqual((table.row_count,table.column_count),(3,3))
        metric=next(c for c in table.cells if c.text=='Metric');self.assertEqual(metric.row_span,2)
        years=next(c for c in table.cells if c.text=='Years');self.assertEqual(years.col_span,2)
        value=next(c for c in table.cells if c.text=='12.5*')
        lookup={c.id:c.text for c in table.cells}
        self.assertEqual({lookup[i] for i in value.explicit_headers},{'Cash movement','2024'})
        self.assertEqual(len(value.footnote_paths),1)
        contexts={b.id:b.text for b in p.blocks}
        self.assertTrue(any('EUR thousands' in contexts[i] for i in table.context_block_ids))

    def test_unknown_bad_and_incomplete_facts_are_not_zero_or_first(self):
        raw=F['source']('''<p><ix:nonFraction id="invalid" name="ex:Bad" contextRef="absent" unitRef="eur">9</ix:nonFraction>
<ix:nonFraction id="continued" name="ex:Complex" contextRef="current" unitRef="eur" continuedAt="more">12</ix:nonFraction>
<ix:nonFraction id="malformed" name="ex:BadDecimal" contextRef="current" unitRef="eur">NaN</ix:nonFraction></p>''')
        p,_=self.parsed(raw);r={v.fact_id:v for v in p.records}
        for identity,status in [('invalid','invalid'),('continued','unsupported'),('malformed','invalid')]:
            self.assertEqual(r[identity].status,status);self.assertIsNone(r[identity].value_decimal);self.assertTrue(r[identity].issues)

    def test_registry_versions_have_distinct_numeric_rules(self):
        raw=F['source']('''<p><ix:nonFraction id="modern" name="ex:Modern" contextRef="current" unitRef="eur" format="ixt:num-dot-decimal">12,34. 5</ix:nonFraction>
<ix:nonFraction id="oldbad" name="ex:Old" contextRef="current" unitRef="eur" format="ixtold:numdotdecimal">12,34</ix:nonFraction>
<ix:nonFraction id="oldgood" name="ex:Old" contextRef="current" unitRef="eur" format="ixtold:numdotdecimal">1 234.5</ix:nonFraction></p>''')
        p,_=self.parsed(raw);r={v.fact_id:v for v in p.records}
        self.assertEqual(r['modern'].value_decimal,'1234.5');self.assertEqual(r['oldbad'].status,'invalid')
        self.assertEqual(r['oldgood'].value_decimal,'1234.5')

    def test_missing_image_and_nested_table_are_explicit(self):
        p,_=self.parsed(F['source']('<table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td></tr></table>'),missing=True)
        self.assertEqual(p.images[0].status,'missing');self.assertEqual(p.images[0].reason,'not_obtained')
        self.assertEqual(len(p.tables),3);self.assertEqual(len(p.tables[1].cells),1)
        self.assertEqual(p.tables[1].nested_table_ids,(p.tables[2].id,))

    def test_malformed_spans_and_wrong_bytes_fail(self):
        for old,new in [(b'rowspan="2"',b'rowspan="999"'),(b'colspan="2"',b'colspan="oops"')]:
            with self.assertRaises(CatalogError) as raised:self.parsed(F['source']().replace(old,new))
            self.assertEqual(raised.exception.code,'PARSE_FAILED')
        inputs=F['inputs'](self.store,F['source']())
        with self.assertRaises(CatalogError):parse_html(F['source']()+b'changed',inputs,encoding='utf-8',form_type='synthetic')
        with self.assertRaises(CatalogError):self.parsed(b'<p>fragment only</p>')

    def test_unwrapped_text_and_locator_bounds(self):
        p,_=self.parsed(F['source']('unwrapped <em>tail</em> here.'))
        self.assertEqual(p.quality.counts['unexplained_omissions'],0)
        dom=SourceDOM(F['source'](),encoding='utf-8');loc=dom.locator(dom.root.xpath('//p')[0])
        self.assertEqual(dom.resolve(loc)[1],'Exact source paragraph. Second line.')
        for update in [{'dom_path':'//p'},{'char_end':100000},{'text_sha256':'0'*64}]:
            with self.assertRaises(CatalogError):dom.resolve(loc.model_copy(update=update))

    def test_named_missing_and_ambiguous_footnotes_are_not_silently_dropped(self):
        raw=F['source']('''<table><tr><td><a href="#named">a</a><a href="#absent">b</a><a href="#duplicate">c</a></td></tr></table>
<a name="named">Named note.</a><p id="duplicate">One</p><p id="duplicate">Two</p>''')
        p,_=self.parsed(raw);cell=p.tables[-1].cells[0]
        self.assertEqual([link['status'] for link in cell.footnote_links],['resolved','missing_target','ambiguous_target'])
        self.assertEqual(len(cell.footnote_paths),1)
        self.assertEqual(sum('unresolved_table_link' in i for i in p.quality.issues),2)

    def test_typed_dimension_and_qname_alias_keep_correct_fact_status(self):
        raw=F['source']().replace(b'xmlns:ex="https://example.com/taxonomy"',b'xmlns:ex="https://example.com/taxonomy" xmlns:alias="https://example.com/taxonomy"').replace(b'id="r3" name="ex:Cash"',b'id="r3" name="alias:Cash"')
        p,_=self.parsed(raw);records={r.fact_id:r for r in p.records}
        self.assertEqual(records['r1'].duplicate_group,records['r3'].duplicate_group)
        raw=raw.replace(b'<xbrldi:explicitMember dimension="ex:RegionAxis">ex:North</xbrldi:explicitMember>',b'<xbrldi:typedMember dimension="ex:RegionAxis"><ex:region>North</ex:region></xbrldi:typedMember>')
        p,_=self.parsed(raw);record=next(r for r in p.records if r.fact_id=='r4')
        self.assertEqual(record.status,'unsupported');self.assertIsNone(record.value_decimal)
        self.assertEqual(record.dimensions[0]['status'],'raw_only');self.assertIn('North',record.dimensions[0]['value'])

    def test_unregistered_image_and_base_url_fail_explicitly(self):
        with self.assertRaises(CatalogError) as raised:self.parsed(F['source']('<img src="unregistered.png">'))
        self.assertEqual(raised.exception.code,'INPUT_INCOMPLETE')
        with self.assertRaises(CatalogError):self.parsed(F['source']().replace(b'<head>',b'<head><base href="https://example.net/">'))

    def test_oversized_span_fails_before_legacy_grid_expansion(self):
        with patch('uteki.data_platform.build.html.parse_sec_source') as legacy:
            with self.assertRaises(CatalogError):self.parsed(F['source']().replace(b'colspan="2"',b'colspan="999999999"'))
            legacy.assert_not_called()


class HtmlPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='uteki-html-publish-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.catalog=Catalog.initialize(self.root);self.addCleanup(self.catalog.close)
        self.context=C['setup'](self.catalog,main=F['source']().replace(b'<img src="chart.png" alt="Synthetic chart">',b''))
        self.recipe=html_recipe(self.catalog,encoding='utf-8',form_type='synthetic',profile_ref='synthetic-v1',taxonomy_ref='none')

    def begin(self,recipe=None):
        return self.catalog.begin_build(snapshot_id=self.context['snapshot_id'],representation_id=self.context['representation_id'],recipe=recipe or self.recipe,run_id=self.context['run_id'])

    def publish(self,recipe=None):
        return build_html(self.catalog,snapshot_id=self.context['snapshot_id'],representation_id=self.context['representation_id'],recipe=recipe or self.recipe,run_id=self.context['run_id'])

    def test_publish_reopen_and_read_actual_source_and_context(self):
        ref=self.publish();self.catalog.close()
        with Catalog.open(self.root) as reopened:
            reader=HtmlReader(reopened,ref);inventory=reader.inventory()
            record=next(r for r in inventory['records'] if r['fact_id']=='r1')
            result=reader.read(HtmlEvidenceRef(asset_ref=ref,kind='record_field',item_id=record['id'],field='value_decimal'))
            self.assertEqual(result['value'],'-12500');self.assertEqual(result['source']['raw_node_text'],'12.5')
            self.assertIn('2023-07-02',result['context']['xbrl_context']['html'])
            self.assertEqual(result['context']['table']['column_count'],3)
            cell=next(c for t in inventory['tables'] for c in t['cells'] if c['text']=='12.5*')
            result=reader.read(HtmlEvidenceRef(asset_ref=ref,kind='table_cell',item_id=cell['id'],field='text'))
            self.assertIn('cash outflows',result['context']['footnotes'][0]['text'])
            record=next(r for r in inventory['records'] if r['fact_id']=='r7')
            with self.assertRaises(CatalogError) as raised:reader.read(HtmlEvidenceRef(asset_ref=ref,kind='record_field',item_id=record['id'],field='value_decimal'))
            self.assertEqual(raised.exception.code,'CONTENT_NOT_READY')
            self.assertEqual(reader.read(HtmlEvidenceRef(asset_ref=ref,kind='record_field',item_id=record['id'],field='raw_value'))['value'],'seven')

    def test_unknown_format_bad_locator_and_false_ready_cannot_publish(self):
        for case in ('version','locator','ready','number'):
            with self.subTest(case=case):
                recipe=self.recipe.model_copy(update={'profile_ref':'case-'+case});build=self.begin(recipe);files,manifest=build_bundle(self.catalog,build)
                if case=='version':
                    with self.assertRaises(ValidationError):BuildManifest.model_validate(manifest.model_dump()|{'schema_version':'invented'})
                    continue
                if case=='locator':
                    blocks=[json.loads(x) for x in files['blocks.jsonl'].splitlines()];blocks[0]['locator']['dom_path']='//body'
                    files['blocks.jsonl']=b''.join(canonical(b)+b'\n' for b in blocks)
                elif case=='ready':
                    schema=json.loads(files['asset-schema.json']);schema['content_readiness']['inline_facts']='ready';schema['published_readiness']['inline_facts']='ready';files['asset-schema.json']=canonical(schema)
                else:
                    records=[json.loads(x) for x in files['records.jsonl'].splitlines()];records[0]['value_decimal']='999';files['records.jsonl']=b''.join(canonical(r)+b'\n' for r in records)
                manifest=manifest.model_copy(update={'files':tuple(ArtifactFile(path=name,object_ref=ObjectRef(sha256=digest(raw),byte_length=len(raw))) for name,raw in files.items())})
                with self.assertRaises(CatalogError):Publication(self.catalog).stage(build['build_id'],files=files,manifest=manifest)
                self.assertEqual(self.catalog.get_build(build['build_id'])['status'],'failed')

    def test_old_format_and_new_recipe_keep_explicit_references(self):
        old=C['publish'](self.catalog,C['begin'](self.catalog,self.context));first=self.publish()
        second=self.publish(self.recipe.model_copy(update={'profile_ref':'synthetic-v2'}))
        self.assertNotEqual(first.build_id,second.build_id)
        self.assertEqual(self.catalog.read_published(old).schema_version,'uteki-build-v1')
        self.assertTrue(self.catalog.read_artifact(old,'blocks.jsonl'))
        first_reader=HtmlReader(self.catalog,first);second_reader=HtmlReader(self.catalog,second)
        a=first_reader.inventory();b=second_reader.inventory()
        self.assertEqual(a['blocks'],b['blocks']);self.assertEqual(a['records'],b['records'])
        with self.assertRaises(CatalogError):first_reader.read(HtmlEvidenceRef(asset_ref=second,kind='block',item_id=a['blocks'][0]['id'],field='text'))
        with self.assertRaises(CatalogError):first_reader.read(HtmlEvidenceRef(asset_ref=first,kind='block',item_id='nonexistent',field='text'))

    def test_partial_move_is_not_visible_and_recovery_verifies_real_html(self):
        old=self.publish();recipe=self.recipe.model_copy(update={'profile_ref':'interrupt-v2'});build=self.begin(recipe)
        files,manifest=build_bundle(self.catalog,build);publisher=Publication(self.catalog);publisher.stage(build['build_id'],files=files,manifest=manifest)
        with patch.object(publisher,'commit_build',side_effect=OSError(errno.EIO,'synthetic commit failure')):
            with self.assertRaises(CatalogError):publisher.publish(build['build_id'])
        with self.assertRaises(CatalogError):HtmlReader(self.catalog,self.catalog.asset_ref(build))
        HtmlReader(self.catalog,old)
        self.catalog.recover();HtmlReader(self.catalog,self.catalog.asset_ref(build))

    def test_parse_failure_has_failed_build_and_does_not_publish(self):
        new=C['snapshot'](self.catalog,self.context,'bad',main=b'<p>not complete HTML</p>',previous=self.context['snapshot_id'])
        with self.assertRaises(CatalogError):build_html(self.catalog,snapshot_id=new['snapshot_id'],representation_id=new['representation_id'],recipe=self.recipe,run_id=self.context['run_id'])
        self.assertEqual(self.catalog._db.execute('SELECT status FROM asset_builds').fetchone()[0],'failed')

    def material_version(self,label,*,main=None,figure=b'figure-v1',missing=False,previous=None):
        inputs=F['inputs'](self.catalog.content,main or F['source'](),figure=figure,missing=missing)
        input_ref=self.catalog.content.put_manifest(inputs)
        unknown=SourceTime(value=None,basis=None,unknown_reason='not_processed')
        acquisition=Acquisition(source_id=self.context['source_id'],request_url=F['MAIN_URL'],final_url=F['MAIN_URL'],
            acquired_at='2024-07-01T00:00:00+00:00',published_at=unknown,available_at=unknown,source_revised_at=unknown)
        snapshot=self.catalog.begin_snapshot(label,asset_id=self.context['asset_id'],acquisition=acquisition,
            completeness='partial' if missing else 'complete',version_consistency='consistent',
            revision_of_snapshot_id=previous,revision_basis='synthetic explicit revision' if previous else None,run_id=self.context['run_id'])
        representation=self.catalog.add_representation(label+':html',snapshot_id=snapshot,format='html',input_manifest=input_ref)
        self.catalog.relate_snapshot(snapshot,SnapshotRelation(company_id=self.context['company_id'],role='issuer',basis='source_metadata',status='confirmed',evidence=C['evidence']()))
        self.catalog.freeze_snapshot(snapshot)
        reference=build_html(self.catalog,snapshot_id=snapshot,representation_id=representation,recipe=self.recipe,run_id=self.context['run_id'])
        return reference,inputs,input_ref

    def test_attachment_change_main_change_and_explicit_absence_keep_old_versions(self):
        old,a,ar=self.material_version('resource-first')
        changed,b,br=self.material_version('resource-changed',figure=b'figure-v2',previous=old.snapshot_id)
        absent,c,cr=self.material_version('resource-missing',missing=True,previous=changed.snapshot_id)
        revised,d,dr=self.material_version('main-changed',main=F['source']().replace(b'Exact ',b'Revised '),previous=absent.snapshot_id)
        self.assertEqual(a.main,b.main);self.assertNotEqual(ar,br);self.assertNotEqual(br,cr);self.assertNotEqual(c.main,d.main)
        self.catalog.close()
        with Catalog.open(self.root) as catalog:
            self.assertEqual(catalog.content.read_object(a.resources[0].object_ref),b'figure-v1')
            self.assertEqual(catalog.content.read_object(b.resources[0].object_ref),b'figure-v2')
            for ref in (old,changed,absent,revised):HtmlReader(catalog,ref)
            schema=HtmlReader(catalog,absent).inventory()['schema']
            self.assertEqual(schema['content_readiness']['original'],'partial')
            self.assertEqual(HtmlReader(catalog,absent).inventory()['images'][0]['status'],'missing')

    def test_missing_and_corrupt_registered_image_are_errors_not_absence(self):
        reference,inputs,_=self.material_version('corruption')
        resource=inputs.resources[0].object_ref;path=self.catalog.content._path(resource)
        original=path.read_bytes();path.chmod(0o644);path.write_bytes(b'corrupt')
        with self.assertRaises(ContentStoreError) as raised:HtmlReader(self.catalog,reference)
        self.assertEqual(raised.exception.code,'OBJECT_CORRUPT')
        path.write_bytes(original);HtmlReader(self.catalog,reference)
        path.unlink()
        with self.assertRaises(ContentStoreError) as raised:HtmlReader(self.catalog,reference)
        self.assertEqual(raised.exception.code,'OBJECT_MISSING')

    def test_v1_and_v2_processors_keep_existing_artifacts_readable(self):
        old=self.publish(self.recipe.model_copy(update={'processor_version':'uteki-html-parser-v1'}))
        new=self.publish()
        self.assertNotEqual(old.build_id,new.build_id)
        old_raw=self.catalog.read_artifact(old,'tables.jsonl');new_raw=self.catalog.read_artifact(new,'tables.jsonl')
        self.assertNotIn(b'footnote_links',old_raw);self.assertIn(b'footnote_links',new_raw)
        self.catalog.close()
        with Catalog.open(self.root) as catalog:
            HtmlReader(catalog,old);HtmlReader(catalog,new)
            self.assertEqual(catalog.read_artifact(old,'tables.jsonl'),old_raw)

    def test_controlled_write_failure_requires_explicit_new_attempt(self):
        old=self.publish();recipe=self.recipe.model_copy(update={'profile_ref':'write-failure-v2'})
        candidate=self.begin(recipe)
        from uteki.data_platform.content import publication
        write=publication.write_control
        def fail(path,raw,**kwargs):
            if path.name=='records.jsonl':raise OSError(errno.EIO,'synthetic write failure')
            return write(path,raw,**kwargs)
        with patch.object(publication,'write_control',side_effect=fail):
            with self.assertRaises(CatalogError):self.publish(recipe)
        self.assertEqual(self.catalog.get_build(candidate['build_id'])['status'],'failed')
        with self.assertRaises(CatalogError):self.publish(recipe)
        HtmlReader(self.catalog,old)
        new=build_html(self.catalog,snapshot_id=self.context['snapshot_id'],representation_id=self.context['representation_id'],
            recipe=recipe,run_id=self.context['run_id'],retry_of_build_id=candidate['build_id'])
        self.assertNotEqual(new.build_id,candidate['build_id']);HtmlReader(self.catalog,new)
        self.assertTrue((self.root/'staging'/candidate['job_id']).exists())

    def test_unsupported_processor_is_not_silently_replaced(self):
        with self.assertRaises(CatalogError) as raised:self.publish(self.recipe.model_copy(update={'processor_version':'unknown-v99'}))
        self.assertEqual(raised.exception.code,'UNSUPPORTED_PROCESSOR')
        self.assertEqual(self.catalog._db.execute('SELECT count(*) FROM asset_builds').fetchone()[0],0)


if __name__=='__main__':unittest.main()
