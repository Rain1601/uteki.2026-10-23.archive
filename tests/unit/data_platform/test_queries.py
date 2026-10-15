"""Query behavior over synthetic frozen HTML, using the installed package."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from pydantic import ValidationError
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.build.pipeline import build_html, html_recipe
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.contracts.query import Calculation, RecordFilters, TextSearch, parse
from uteki.data_platform.retrieval.content import HtmlReader
from uteki.data_platform.retrieval.index import DerivedIndex
from uteki.data_platform.structured.calculations import calculate
from uteki.data_platform.service import DataService

FIXTURES = Path(__file__).resolve().parents[2]/'fixtures/data_platform'
C = runpy.run_path(str(FIXTURES/'catalog_worker.py'))
F = runpy.run_path(str(FIXTURES/'html_fixture.py'))


class DerivedQueryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='uteki-query-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.catalog = Catalog.initialize(self.root)
        self.addCleanup(self.catalog.close)
        source = F['source']('<p>投资研究 waterfall running 现金流。 Straße.</p>').replace(b'<img src="chart.png" alt="Synthetic chart">', b'')
        self.setup = C['setup'](self.catalog, main=source)
        recipe = html_recipe(self.catalog, encoding='utf-8', form_type='synthetic', profile_ref='fixture', taxonomy_ref='source')
        self.reference = build_html(self.catalog, snapshot_id=self.setup['snapshot_id'], representation_id=self.setup['representation_id'], recipe=recipe, run_id=self.setup['run_id'])
        self.reader = HtmlReader(self.catalog, self.reference)
        self.index = DerivedIndex(self.catalog, self.reader)

    def test_read_does_not_build_and_explicit_index_supports_source_search(self):
        self.assertEqual(self.index.availability()['status'], 'not_ready')
        self.assertFalse((self.root/'derived').exists())
        self.index.build()
        for mode, value in [('phrase','投资'), ('phrase','水'), ('all_terms','running'), ('regex',r'投资.*现金流')]:
            ids, _ = self.index.text_candidates(TextSearch(match=mode, value=value))
            self.assertEqual(bool(ids), value != '水')
        ids, _ = self.index.text_candidates(TextSearch(match='phrase',value='Aria secret'))
        self.assertEqual(ids, [])

    def test_regex_is_re2_and_rejects_backreferences(self):
        self.index.build()
        with self.assertRaises(CatalogError):
            self.index.text_candidates(TextSearch(match='regex',value=r'(a)\1'))
        with self.assertRaises(ValidationError):
            TextSearch(match='regex',value='a'*201)

    def test_match_offsets_follow_regex_stemming_and_unicode_source_characters(self):
        self.index.build()
        blocks={b['id']:b['text'] for b in self.reader.inventory()['blocks']}
        for mode,query,expected in [('regex',r'waterf[a-z]+','waterfall'),('all_terms','runs','running'),('phrase','STRASSE','Straße')]:
            ids,_,ranges=self.index.text_candidates(TextSearch(match=mode,value=query),with_ranges=True)
            self.assertEqual(len(ids),1)
            start,end=ranges[ids[0]]
            self.assertEqual(blocks[ids[0]][start:end],expected)

    def test_filters_keep_duplicate_nil_and_dimensioned_values(self):
        self.index.build()
        rows, _ = self.index.record_rows(concepts=('{https://example.com/taxonomy}Cash',))
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['period']['end'] for r in rows}, {'2024-06-29','2023-07-01'})
        rows, _ = self.index.record_rows(filters=RecordFilters(dimensions={'{https://example.com/taxonomy}RegionAxis':'{https://example.com/taxonomy}North'}))
        self.assertEqual([r['fact_id'] for r in rows], ['r4'])
        rows, _ = self.index.record_rows(filters=RecordFilters(statuses=('nil','unsupported')))
        self.assertEqual({r['fact_id'] for r in rows}, {'r5','r7'})
        rows, _ = self.index.record_rows(concepts=("' OR 1=1 --",))
        self.assertEqual(rows, [])

    def test_corrupt_index_requires_explicit_rebuild_and_keeps_source(self):
        self.index.build()
        directory, old, _ = self.index.current()
        (directory/'records.duckdb').write_bytes(b'broken')
        self.assertEqual(self.index.availability()['status'], 'not_ready')
        with self.assertRaises(CatalogError):
            self.index.record_rows()
        new = self.index.build()
        self.assertNotEqual(old['generation'], new['generation'])
        self.assertEqual((directory/'records.duckdb').read_bytes(), b'broken')
        self.assertTrue(HtmlReader(self.catalog,self.reference).inventory()['blocks'])

    def test_interrupted_build_does_not_replace_old_generation(self):
        old = self.index.build()
        def stop(phase):
            if phase == 'index_before_head':
                raise OSError('controlled write failure')
        with self.assertRaises(OSError):
            self.index.build(checkpoint=stop)
        self.assertEqual(self.index.current()[1]['generation'],old['generation'])
        self.assertEqual(len(list(self.index.base.glob('idx_*'))),2)

    def spec(self, op, records, **updates):
        value = dict(calc_id='calc-1',op=op,
            operands=[dict(asset_ref=self.reference.model_dump(mode='json'),record_selector={'record_id':r['id']}) for r in records],
            output_unit='ratio' if op in {'growth','ratio'} else records[0]['unit'],
            period_policy='distinct_nonoverlapping' if op=='growth' else 'same',comparison_basis='Explicit synthetic compatible units and reporting basis')
        return parse(Calculation, value | updates)

    def test_decimal_growth_preserves_sign_and_fiscal_periods(self):
        by_id = {r['fact_id']:r for r in self.reader.inventory()['records']}
        records = [by_id['r1'],by_id['r2']]
        result = calculate(self.spec('growth',records),records)
        self.assertEqual(result['value'],'-2.250000000000000000')
        self.assertEqual(result['limitations'],[])
        self.assertEqual(records[0]['period']['start'],'2023-07-02')

    def test_zero_unknown_units_and_duplicate_sum_fail_explicitly(self):
        by_id = {r['fact_id']:r for r in self.reader.inventory()['records']}
        for op,ids,code in [('ratio',['r1','r6'],'ZERO_DENOMINATOR'),
                            ('ratio',['r1','r5'],'OPERAND_NOT_PARSED'),
                            ('sum',['r1','r3'],'DUPLICATE_FACT_IN_SUM')]:
            records = [by_id[i] for i in ids]
            result = calculate(self.spec(op,records),records)
            self.assertIsNone(result['value']); self.assertIn(code,result['limitations'])
        changed = deepcopy(by_id['r1']); changed['unit']={'measures':['different']}
        records=[by_id['r1'],changed]
        result=calculate(self.spec('difference',records),records)
        self.assertIn('UNIT_MISMATCH',result['limitations'])

    def test_overlapping_periods_are_not_growth(self):
        by_id={r['fact_id']:r for r in self.reader.inventory()['records']}
        records=[by_id['r1'],by_id['r3']]
        self.assertIn('PERIOD_OVERLAP',calculate(self.spec('growth',records),records)['limitations'])

    def test_period_comparison_uses_timezone_instants_not_string_order(self):
        by_id={r['fact_id']:r for r in self.reader.inventory()['records']}
        current,prior=deepcopy(by_id['r1']),deepcopy(by_id['r2'])
        current['period']={'instant':'2024-01-01T00:00:00-10:00'}
        prior['period']={'instant':'2024-01-01T01:00:00+10:00'}
        result=calculate(self.spec('growth',[current,prior]),[current,prior])
        self.assertEqual(result['value'],'-2.250000000000000000')
        prior['entity_identifier']=None
        self.assertIn('ENTITY_UNKNOWN',calculate(self.spec('growth',[current,prior]),[current,prior])['limitations'])


class DataToolTests(unittest.TestCase):
    def setUp(self):
        DerivedQueryTests.setUp(self)
        self.catalog.register_policy('fixture-read',definition=canonical(dict(schema_version='uteki-read-policy-v1',source_kinds=['user_file'],source_ids=[])).decode(),run_id=self.setup['run_id'])
        self.service = DataService(self.catalog)
        self.request = dict(question='Inspect the synthetic fiscal cash comparison',caller=dict(kind='user',prior_delivery_refs=[]),
            entities=dict(company_ids=[self.setup['company_id']]),periods=[],source_policy_ref='fixture-read',
            expansion=dict(mode='controlled',allow=['process'],deny=['acquire']),
            run_policy=dict(max_usd='0',max_turns=100,max_wall_seconds=120,max_no_progress_turns=100))
        self.context = self.service.create_context(self.request,request_key='context-one')['context_ref']
        self.sequence = 0

    def state(self,tool,refs=(),*,supported=False,context=None):
        context = context or self.context
        version = self.service.inspect_context(context)['plan']['version']
        result = dict(satisfied=[dict(need_id='need-1',result_refs=list(refs))] if supported else [],
            gaps=[] if supported else [dict(need_id='need-1',missing='More source evidence needed',result_refs=list(refs))],next_action=tool,reason='Deterministic fixture step')
        if not version:
            result['plan_update'] = dict(base_version=0,needs=[dict(need_id='need-1',description='Compare cash values and sources',required=True)])
        return result

    def call(self,tool,args,*,refs=(),context=None,**options):
        self.sequence += 1
        return self.service.call(context or self.context,tool,args,state=self.state(tool,refs,context=context),request_key='step-'+str(self.sequence),**options)

    def process(self):
        result = self.call('request_asset_update',dict(need_id='need-1',action='process',process=dict(asset_ref=self.reference.model_dump(mode='json'),capabilities=['text_search','records']),reason='Build explicitly requested derived views'))
        self.assertEqual(result['status'],'ok',result)
        return result

    def test_all_six_tools_and_immutable_delivery_reopen(self):
        found = self.call('find_assets',dict(filters={'company_ids':[self.setup['company_id']]}))
        self.assertEqual(found['status'],'ok',found)
        self.assertEqual(found['items'][0]['readiness']['records'],'not_ready')
        self.process()
        schema = self.call('get_asset_schema',dict(asset_ref=self.reference.model_dump(mode='json'),facets=['fields','concepts']))
        self.assertIn('query_records',schema['items'][0]['capabilities'])
        hit = self.call('search_asset',dict(asset_ref=self.reference.model_dump(mode='json'),mode='text',text={'match':'phrase','value':'Exact source'}))
        self.assertEqual(hit['status'],'ok',hit)
        source = hit['items'][0]['evidence']
        read = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':hit['items'][0]['block_id']}]))
        self.assertIn('Exact source paragraph.',read['items'][0]['content']['text'])
        records = self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={'concepts':['{https://example.com/taxonomy}Cash']}))
        self.assertEqual(len(records['items']),3)
        by_fact = {r['fact_id']:r for r in self.reader.inventory()['records']}
        spec = DerivedQueryTests.spec(self,'growth',[by_fact['r1'],by_fact['r2']])
        computed = self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={'concepts':['{https://example.com/taxonomy}Cash']},calculations=[spec.model_dump(mode='json')]))
        self.assertEqual(computed['calculations'][0]['value'],'-2.250000000000000000',computed)
        refs = [source['result_ref'],computed['calculations'][0]['result_ref']]
        delivery = self.service.deliver(self.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=refs,gaps=[])]),
            state=self.state('deliver',refs,supported=True),request_key='delivery-one')
        self.assertEqual(len(delivery['delivery']['records']),2)
        self.assertEqual(len(delivery['delivery']['evidence']),1)
        frozen = deepcopy(delivery)
        delivery['delivery']['records'][0]['value']='invented'
        self.assertEqual(self.service.read_delivery(self.context),frozen['delivery'])
        self.catalog.close()
        with Catalog.open(self.root) as catalog:
            self.assertEqual(DataService(catalog).read_delivery(self.context),frozen['delivery'])

    def test_ambiguous_selector_has_no_valid_calculation(self):
        self.process()
        by_fact = {r['fact_id']:r for r in self.reader.inventory()['records']}
        spec = DerivedQueryTests.spec(self,'growth',[by_fact['r1'],by_fact['r2']]).model_dump(mode='json')
        spec['operands'][0]['record_selector']={'concept_id':'{https://example.com/taxonomy}Cash','period':by_fact['r1']['period']}
        result = self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={},calculations=[spec]))
        self.assertEqual(result['status'],'partial',result)
        self.assertIsNone(result['calculations'][0]['value'])
        self.assertIn('OPERAND_AMBIGUOUS',result['calculations'][0]['limitations'])

    def test_record_pagination_binding_and_generation_expiry(self):
        self.process()
        args = dict(asset_ref=self.reference.model_dump(mode='json'),select={},limit=2)
        first = self.call('query_records',args)
        second = self.call('query_records',args|{'cursor':first['next_cursor']})
        self.assertFalse({r['record_id'] for r in first['items']} & {r['record_id'] for r in second['items']})
        changed = self.call('query_records',args|{'limit':3,'cursor':first['next_cursor']})
        self.assertEqual(changed['error']['code'],'CURSOR_MISMATCH')
        self.process()
        stale = self.call('query_records',args|{'cursor':first['next_cursor']})
        self.assertEqual(stale['error']['code'],'CURSOR_EXPIRED')

    def test_unknown_cutoff_excludes_candidate_and_direct_read(self):
        request = self.request | {'as_of':'2026-01-01T00:00:00Z'}
        context = self.service.create_context(request,request_key='historical')['context_ref']
        result = self.call('find_assets',dict(filters={'company_ids':[self.setup['company_id']]}),context=context)
        self.assertEqual(result['items'],[])
        self.assertEqual(result['issues'][0]['code'],'SCOPE_TIME_UNKNOWN')
        denied = self.call('get_asset_schema',dict(asset_ref=self.reference.model_dump(mode='json')),context=context)
        self.assertEqual(denied['error']['code'],'SCOPE_TIME_UNKNOWN')
        self.assertEqual(denied['resource_usage']['external_calls'],0)

    def test_cross_run_and_invented_results_rejected_before_state_change(self):
        block = next(b for b in self.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        response = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':block['id']}]))
        ref = response['items'][0]['result_ref']
        other = self.service.create_context(self.request,request_key='other')['context_ref']
        result = self.call('get_asset_schema',dict(asset_ref=self.reference.model_dump(mode='json')),context=other,refs=[ref])
        self.assertEqual(result['error']['code'],'RESULT_REF_INVALID')
        self.assertEqual(self.service.inspect_context(other)['plan']['version'],0)

    def test_duplicate_request_replays_without_rebuilding_index(self):
        args = dict(need_id='need-1',action='process',process=dict(asset_ref=self.reference.model_dump(mode='json'),capabilities=['records']),reason='Explicit fixture processing')
        state = self.state('request_asset_update')
        first = self.service.request_asset_update(self.context,args,state=state,request_key='same')
        second = self.service.request_asset_update(self.context,args,state=state,request_key='same')
        self.assertEqual(first,second)
        self.assertEqual(len(list(self.index.base.glob('idx_*'))),1)
        conflict = self.service.request_asset_update(self.context,args|{'reason':'changed'},state=state,request_key='same')
        self.assertEqual(conflict['error']['code'],'IDEMPOTENCY_CONFLICT')

    def test_table_cell_delivery_retains_requested_headers_units_and_footnote(self):
        table = self.reader.inventory()['tables'][0]
        response = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),
            targets=[dict(table_id=table['id'],rows=[2],cols=[1])],
            context=['table_headers','units','footnotes','section_title'],max_bytes=24000))
        self.assertEqual(response['status'],'ok',response)
        self.assertEqual(len(response['items']),1)
        target = response['items'][0]
        self.assertEqual(target['content']['text'],'12.5*')
        self.assertTrue(target['dependency_refs'])
        texts = [v['content']['text'] for v in response['context_evidence']]
        for required in ['Cash movement','2024','Annual results',
                'Amounts in EUR thousands; fiscal years end in June.',
                '* Payments are cash outflows; periods are not calendar years.']:
            self.assertIn(required,texts)
        refs = [target['result_ref']]
        delivery = self.service.deliver(self.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=refs,gaps=[])]),
            state=self.state('deliver',refs,supported=True),request_key='table-delivery')
        self.assertEqual({canonical(v) for v in delivery['delivery']['evidence']},
            {canonical(v) for v in response['items']+response['context_evidence']})

    def test_context_bundle_over_budget_is_never_registered_partially(self):
        table = self.reader.inventory()['tables'][0]
        result = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),
            targets=[dict(table_id=table['id'],rows=[2],cols=[1])],context=['table_headers','units','footnotes'],max_bytes=2000))
        self.assertLessEqual(len(canonical(result)),2000)
        self.assertEqual(result['items'],[])
        self.assertEqual(result.get('context_evidence',[]),[])
        from uteki.data_platform.application.session import Session
        self.assertEqual(Session(self.catalog,self.context).data['results'],{})

    def test_cell_record_and_partial_block_locators_roundtrip(self):
        table = self.reader.inventory()['tables'][0]
        record = next(r for r in self.reader.inventory()['records'] if r['fact_id']=='r1')
        block = next(b for b in self.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        for target in [dict(table_id=table['id'],rows=[2],cols=[1]),dict(record_id=record['id']),dict(block_id=block['id'],char_range=[2,18])]:
            original = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[target]))
            self.assertEqual(original['status'],'ok',original)
            item = original['items'][0]
            reread = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[dict(locator=item['locator'])]))
            self.assertEqual(reread['status'],'ok',reread)
            self.assertEqual(reread['items'][0]['content']['text'],item['content']['text'])
            self.assertEqual(reread['items'][0]['locator'],item['locator'])

    def test_merged_header_span_and_unsupported_representation(self):
        table = self.reader.inventory()['tables'][0]
        result = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),
            targets=[dict(table_id=table['id'],rows=[1],cols=[0])]))
        self.assertEqual([v['content']['text'] for v in result['items']],['Metric'])
        denied = self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),
            targets=[dict(table_id=table['id'])],table_representation='compact'))
        self.assertEqual(denied['error']['code'],'CAPABILITY_UNSUPPORTED')

    def test_invalid_selector_period_rejected_before_plan_acceptance(self):
        records={r['fact_id']:r for r in self.reader.inventory()['records']}
        spec=DerivedQueryTests.spec(self,'growth',[records['r1'],records['r2']]).model_dump(mode='json')
        spec['operands'][0]['record_selector']['period']={'start':'2024-06-29','end':'2023-07-02'}
        result=self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={},calculations=[spec]))
        self.assertEqual(result['error']['code'],'INVALID_REQUEST')
        self.assertEqual(self.service.inspect_context(self.context)['plan']['version'],0)

    def another_asset(self,label,source):
        from uteki.data_platform.contracts.assets import AssetInput
        source=source.replace(b'<img src="chart.png" alt="Synthetic chart">',b'')
        asset=self.catalog.register_asset('additional:'+label,AssetInput(asset_kind='document',material_type='synthetic-document',
            title='Additional synthetic source '+label,language=None,natural_key='additional:'+label,reporting_period=None,
            declared_scope=None,evidence=C['evidence']()),run_id=self.setup['run_id'])
        metadata=self.setup | {'asset_id':asset}
        snapshot=C['snapshot'](self.catalog,metadata,label,main=source)
        recipe=html_recipe(self.catalog,encoding='utf-8',form_type='synthetic',profile_ref='fixture',taxonomy_ref='source')
        reference=build_html(self.catalog,snapshot_id=snapshot['snapshot_id'],representation_id=snapshot['representation_id'],
            recipe=recipe,run_id=self.setup['run_id'])
        reader=HtmlReader(self.catalog,reference)
        DerivedIndex(self.catalog,reader).build()
        return reference,reader

    def test_cross_asset_calculation_has_both_source_versions_and_rejects_unit_conflict(self):
        self.process()
        first=next(r for r in self.reader.inventory()['records'] if r['fact_id']=='r1')
        compatible=None
        for label,currency in [('same','EUR'),('different','USD')]:
            source=F['source']().replace(b'>12.5<',b'>25<').replace(b'iso4217:EUR',('iso4217:'+currency).encode())
            reference,reader=self.another_asset(label,source)
            second=next(r for r in reader.inventory()['records'] if r['fact_id']=='r1')
            spec=DerivedQueryTests.spec(self,'difference',[first,second]).model_dump(mode='json')
            spec['operands'][1]['asset_ref']=reference.model_dump(mode='json')
            result=self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={},calculations=[spec],max_bytes=100000))
            if currency=='EUR':
                self.assertEqual(result['calculations'][0]['value'],'12500',result)
                compatible=result['calculations'][0]
                values=result['items']+result['supporting_records']
                self.assertEqual({canonical(v['asset_ref']) for v in values if v['result_ref'] in compatible['operand_refs']},
                    {canonical(self.reference.model_dump(mode='json')),canonical(reference.model_dump(mode='json'))})
            else:
                self.assertIsNone(result['calculations'][0]['value'])
                self.assertIn('UNIT_MISMATCH',result['calculations'][0]['limitations'])
        refs=[compatible['result_ref']]
        result=self.service.deliver(self.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=refs,gaps=[])]),
            state=self.state('deliver',refs,supported=True),request_key='cross-asset-delivery')
        self.assertEqual(len(result['delivery']['assets_used']),2)
        self.assertEqual({r['value'] for r in result['delivery']['records']},{'-12500','-25000'})

    def test_record_budget_cannot_hide_calculation_operands(self):
        self.process()
        records={r['fact_id']:r for r in self.reader.inventory()['records']}
        spec=DerivedQueryTests.spec(self,'growth',[records['r1'],records['r2']]).model_dump(mode='json')
        result=self.call('query_records',dict(asset_ref=self.reference.model_dump(mode='json'),select={},calculations=[spec],limit=1))
        self.assertEqual(result['calculations'],[])
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['supporting_records'],[])
        self.assertIn('CALC_DEPENDENCIES_TOO_LARGE',[i['code'] for i in result['issues']])
        from uteki.data_platform.application.session import Session
        saved=Session(self.catalog,self.context).data['results']
        self.assertEqual(list(saved.values()),result['items'])

    def test_no_progress_limit_counts_same_evidence_despite_new_references(self):
        request=deepcopy(self.request)
        request['run_policy']['max_no_progress_turns']=2
        context=self.service.create_context(request,request_key='no-progress')['context_ref']
        block=next(b for b in self.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        args=dict(asset_ref=self.reference.model_dump(mode='json'),targets=[dict(block_id=block['id'])])
        for _ in range(3):
            result=self.call('read_evidence',args,context=context)
            self.assertEqual(result['status'],'ok',result)
        denied=self.call('read_evidence',args,context=context)
        self.assertEqual(denied['error']['code'],'BUDGET_EXCEEDED')

    def test_search_contexts_are_source_evidence_and_delivered_with_snippet(self):
        self.process()
        result=self.call('search_asset',dict(asset_ref=self.reference.model_dump(mode='json'),mode='text',
            text={'match':'phrase','value':'Cash movement'},include=['snippet','table_header','units']))
        self.assertEqual(result['status'],'ok',result)
        hit=result['items'][0]
        self.assertTrue(hit['evidence']['dependency_refs'])
        self.assertIn('2024',[v['content']['text'] for v in hit['context_evidence']])

    def test_repeated_rebuild_without_new_material_is_not_new_progress(self):
        request=deepcopy(self.request)
        request['run_policy']['max_no_progress_turns']=1
        context=self.service.create_context(request,request_key='no-progress-update')['context_ref']
        args=dict(need_id='need-1',action='process',process=dict(asset_ref=self.reference.model_dump(mode='json'),capabilities=['text_search']),reason='Explicit rebuild')
        for _ in range(2):
            result=self.call('request_asset_update',args,context=context)
            self.assertEqual(result['status'],'ok',result)
        denied=self.call('request_asset_update',args,context=context)
        self.assertEqual(denied['error']['code'],'BUDGET_EXCEEDED')

    def test_plan_rewrite_and_forged_delivery_do_not_mutate_accepted_plan(self):
        block=next(b for b in self.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        result=self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':block['id']}]))
        original=self.service.inspect_context(self.context)['plan']
        state=self.state('get_asset_schema')
        state['plan_update']=dict(base_version=original['version'],needs=[dict(need_id='need-1',description='Changed to an easier requirement',required=False)])
        rejected=self.service.get_asset_schema(self.context,dict(asset_ref=self.reference.model_dump(mode='json')),state=state,request_key='rewrite')
        self.assertEqual(rejected['error']['code'],'INVALID_REQUEST')
        self.assertEqual(self.service.inspect_context(self.context)['plan'],original)
        forged=deepcopy(result['items'][0]['result_ref']);forged['item_id']='never-returned'
        with self.assertRaises(CatalogError) as error:
            self.service.deliver(self.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=[forged],gaps=[])]),
                state=self.state('deliver',[forged],supported=True),request_key='forged')
        self.assertEqual(error.exception.code,'RESULT_REF_INVALID')
        self.assertIsNone(self.service.inspect_context(self.context)['delivery'])

    def test_conflict_cannot_be_declared_supported_and_partial_keeps_both_sources(self):
        blocks=self.reader.inventory()['blocks']
        response=self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':b['id']} for b in blocks[:2]]))
        refs=[v['result_ref'] for v in response['items']]
        self.assertEqual(len(refs),2)
        conflict=dict(need_id='need-1',result_refs=refs,description='Caller reports unresolved interpretation conflict')
        request=dict(needs=[dict(need_id='need-1',status='supported',result_refs=refs,gaps=[])],conflicts=[conflict])
        with self.assertRaises(CatalogError):
            self.service.deliver(self.context,request,state=self.state('deliver',refs,supported=True),request_key='invalid-supported')
        request['needs'][0].update(status='partial',gaps=['More source evidence needed'])
        result=self.service.deliver(self.context,request,state=self.state('deliver',refs),request_key='partial-conflict')
        self.assertEqual(len(result['delivery']['evidence']),2)
        self.assertEqual(result['delivery']['needs'][0]['status'],'partial')
        self.assertEqual(result['delivery']['conflicts'],[conflict])

    def test_pagination_collects_every_record_once_and_catalog_change_expires_asset_cursor(self):
        self.process()
        args=dict(asset_ref=self.reference.model_dump(mode='json'),select={},limit=2)
        collected=[]
        while True:
            result=self.call('query_records',args)
            self.assertEqual(result['status'],'ok',result)
            collected.extend(v['record_id'] for v in result['items'])
            if result['next_cursor'] is None:
                break
            args['cursor']=result['next_cursor']
        expected={r['id'] for r in self.reader.inventory()['records']}
        self.assertEqual(set(collected),expected)
        self.assertEqual(len(collected),len(expected))
        self.another_asset('second-for-paging',F['source']())
        first=self.call('find_assets',dict(filters={'company_ids':[self.setup['company_id']]},limit=1))
        self.assertIsNotNone(first['next_cursor'])
        # A metadata view change is observable even though read-run writes are not.
        self.catalog.register_company('new-metadata',C['company']('new-metadata'),run_id=self.setup['run_id'])
        stale=self.call('find_assets',dict(filters={'company_ids':[self.setup['company_id']]},limit=1,cursor=first['next_cursor']))
        self.assertEqual(stale['error']['code'],'CURSOR_EXPIRED')

    def test_delivery_rejects_cycles_or_dangling_dependencies_in_persisted_results(self):
        from uteki.data_platform.application.session import Session,ref_key
        block=next(b for b in self.reader.inventory()['blocks'] if 'Exact source' in b['text'])
        response=self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':block['id']}]))
        ref=response['items'][0]['result_ref']
        for label,dependency in [('cycle',ref),('dangling',ref|{'item_id':'not-returned'})]:
            with self.subTest(label=label):
                # Fault injection models a producer/persistence defect; caller
                # delivery arguments cannot supply their own result payloads.
                session=Session(self.catalog,self.context)
                session.data['results'][ref_key(ref)]['dependency_refs']=[dependency]
                session.save()
                before=len(session.data['operations'])
                with self.assertRaises(CatalogError) as error:
                    self.service.deliver(self.context,dict(needs=[dict(need_id='need-1',status='supported',result_refs=[ref],gaps=[])]),
                        state=self.state('deliver',[ref],supported=True),request_key=label)
                self.assertEqual(error.exception.code,'RESULT_REF_INVALID')
                self.assertEqual(len(self.service.inspect_context(self.context)['operations']),before)

    def test_standalone_record_context_and_unsupported_search_options_are_explicit(self):
        record=next(r for r in self.reader.inventory()['records'] if r['fact_id']=='r3')
        response=self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[dict(record_id=record['id'])],context=['section_title']))
        self.assertEqual(response['status'],'ok',response)
        self.assertIn('Annual results',[v['content']['text'] for v in response['context_evidence']])
        self.assertTrue(response['items'][0]['content']['unit_source']['html'])
        rejected=self.call('search_asset',dict(asset_ref=self.reference.model_dump(mode='json'),mode='concept',
            concept={'concept_id':'{https://example.com/taxonomy}Cash'},include=['units']))
        self.assertEqual(rejected['error']['code'],'CAPABILITY_UNSUPPORTED')

    def test_typed_dimension_does_not_match_explicit_empty_dimensions(self):
        source=F['source']().replace(b'<xbrldi:explicitMember dimension="ex:RegionAxis">ex:North</xbrldi:explicitMember>',
            b'<xbrldi:typedMember dimension="ex:RegionAxis"><ex:Region>North</ex:Region></xbrldi:typedMember>')
        reference,reader=self.another_asset('typed-dimension',source)
        typed=next(r for r in reader.inventory()['records'] if r['fact_id']=='r4')
        self.assertEqual(typed['status'],'unsupported')
        all_records=self.call('query_records',dict(asset_ref=reference.model_dump(mode='json'),select={},max_bytes=100000))
        self.assertIn(typed['id'],[r['record_id'] for r in all_records['items']])
        empty_dimensions=self.call('query_records',dict(asset_ref=reference.model_dump(mode='json'),select={},filters={'dimensions':{}},max_bytes=100000))
        self.assertNotIn(typed['id'],[r['record_id'] for r in empty_dimensions['items']])

    def test_hard_entity_and_source_boundaries_apply_to_direct_reads(self):
        other=C['setup'](self.catalog,'other-entity',main=F['source']().replace(b'<img src="chart.png" alt="Synthetic chart">',b''))
        recipe=html_recipe(self.catalog,encoding='utf-8',form_type='synthetic',profile_ref='fixture',taxonomy_ref='source')
        reference=build_html(self.catalog,snapshot_id=other['snapshot_id'],representation_id=other['representation_id'],recipe=recipe,run_id=other['run_id'])
        denied=self.call('get_asset_schema',dict(asset_ref=reference.model_dump(mode='json')))
        self.assertEqual(denied['error']['code'],'SCOPE_DENIED')
        widened=self.call('find_assets',dict(filters={'company_ids':[other['company_id']]}))
        self.assertEqual(widened['error']['code'],'SCOPE_DENIED')
        self.assertEqual(self.service.inspect_context(self.context)['plan']['version'],0)
        self.catalog.register_policy('official-only',definition=canonical(dict(schema_version='uteki-read-policy-v1',source_kinds=['official_site'])).decode(),run_id=self.setup['run_id'])
        context=self.service.create_context(self.request|{'source_policy_ref':'official-only'},request_key='narrow-source')['context_ref']
        blocked=self.call('read_evidence',dict(asset_ref=self.reference.model_dump(mode='json'),targets=[{'block_id':self.reader.inventory()['blocks'][0]['id']}]),context=context)
        self.assertEqual(blocked['error']['code'],'SCOPE_DENIED')
        self.assertEqual(self.service.inspect_context(context)['plan']['version'],0)

    def test_unknown_period_matching_is_partial_and_cutoff_cannot_be_widened(self):
        found=self.call('find_assets',dict(filters={'reporting_periods':['FY2024']}))
        self.assertEqual(found['status'],'partial',found)
        self.assertEqual(found['items'][0]['match']['status'],'unresolved')
        self.assertIn('reporting_period',found['items'][0]['match']['unresolved_fields'])
        context=self.service.create_context(self.request|{'as_of':'2026-01-01T00:00:00Z'},request_key='historical-bound')['context_ref']
        denied=self.call('find_assets',dict(filters={},as_of='2026-02-01T00:00:00Z'),context=context)
        self.assertEqual(denied['error']['code'],'SCOPE_DENIED')


if __name__ == '__main__':
    unittest.main()
