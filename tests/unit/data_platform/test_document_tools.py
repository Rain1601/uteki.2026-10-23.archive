"""Shared-service document behavior using an installed package and synthetic boundaries."""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.assets import SourceInput
from uteki.data_platform.contracts.common import CatalogError, canonical
from uteki.data_platform.contracts.documents import DocumentPackage
from uteki.data_platform.contracts.query import ContextRequest, ReadEvidence, parse
from uteki.data_platform.documents import DocumentStore
from uteki.data_platform.service import DataService

ROOT = Path(__file__).resolve().parents[3]
C = runpy.run_path(str(ROOT/'tests/fixtures/data_platform/catalog_worker.py'))
E = runpy.run_path(str(ROOT/'examples/data_platform/documents.py'))


class DocumentToolsTests(unittest.TestCase):
    def test_progress_delta_preserves_state_and_plan_without_repetition(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        schema=binding.tool_schema('find_assets')
        self.assertNotIn('PlanUpdate',schema['$defs'])
        self.assertNotIn('TaskState',schema['$defs'])
        call=lambda name,request,state: json.loads(asyncio.run(binding.invoke(name,dict(request=request,state=state))))
        initial=call('find_assets',dict(filters={}),dict(add_needs=[dict(need_id='x',description='Read source',required=True),
            dict(need_id='y',description='Assess scope',required=True)],reason='Find material'))
        self.assertEqual(initial['status'],'ok',initial)
        snapshot=self.service.inspect_context(self.context)
        self.assertEqual(snapshot['plan']['version'],1)
        self.assertEqual({g['need_id'] for g in snapshot['state']['gaps']},{'x','y'})
        text=canonical(initial).decode();binding.observe(text,boundary='test-model-input')
        ref=dict(handle=initial['items'][0]['result_handle'])
        reply=call('get_asset_schema',dict(asset_ref=self.reference),dict(
            satisfied=[dict(need_id='x',result_refs=[ref])],reason='Inspect schema'))
        self.assertNotEqual(reply['status'],'error')
        snapshot=self.service.inspect_context(self.context)
        self.assertEqual(snapshot['plan']['version'],1)
        self.assertEqual([g['need_id'] for g in snapshot['state']['gaps']],['y'])
        reply=call('get_asset_schema',dict(asset_ref=self.reference),dict(reason='Inspect again'))
        self.assertNotEqual(reply['status'],'error')
        self.assertEqual(self.service.inspect_context(self.context)['state']['satisfied'][0]['need_id'],'x')
        rejected=call('find_assets',{},dict(add_needs=[dict(need_id='x',description='rewrite',required=True)],reason='Bad rewrite'))
        self.assertEqual(rejected['error']['code'],'INVALID_REQUEST')
        rejected=call('find_assets',{},dict(gaps=[dict(need_id='unknown',missing='unknown')],reason='Bad update'))
        self.assertEqual(rejected['error']['code'],'INVALID_REQUEST')

    def test_progress_does_not_infer_satisfaction_or_hide_invalid_references(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        invoke=lambda state: json.loads(asyncio.run(binding.invoke('find_assets',dict(request=dict(filters={}),state=state))))
        self.assertEqual(invoke(dict(reason='Missing initial needs'))['error']['code'],'INVALID_REQUEST')
        result=invoke(dict(add_needs=[dict(need_id='x',description='Find evidence',required=True)],reason='Find'))
        self.assertEqual(result['status'],'ok',result)
        bad=invoke(dict(satisfied=[dict(need_id='x',result_refs=[dict(handle='rr_0000000000000000')])],reason='Invalid evidence'))
        self.assertEqual(bad['error']['code'],'RESULT_REF_INVALID')
        snapshot=self.service.inspect_context(self.context)
        self.assertEqual(snapshot['state']['satisfied'],[])
        self.assertEqual(snapshot['state']['gaps'][0]['need_id'],'x')
        ambiguous=invoke(dict(satisfied=[dict(need_id='x',result_refs=[result['items'][0]['result_ref']])],
            gaps=[dict(need_id='x',missing='Not ready')],reason='Contradictory update'))
        self.assertEqual(ambiguous['status'],'error')

    def test_document_record_output_default_uses_hard_cap_but_respects_explicit_budget(self):
        from uteki.data_platform.agent.document_contracts import DocumentRecords
        self.assertEqual(DocumentRecords.model_validate_json(canonical(dict(asset_ref=self.reference))).max_bytes,200000)
        self.assertEqual(DocumentRecords.model_validate_json(canonical(dict(asset_ref=self.reference,max_bytes=24000))).max_bytes,24000)
        with self.assertRaises(ValueError):
            DocumentRecords.model_validate_json(canonical(dict(asset_ref=self.reference,max_bytes=200001)))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='uteki-document-tools-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'catalog').mkdir(); (self.root/'documents').mkdir()
        self.catalog = Catalog.initialize(self.root/'catalog')
        self.addCleanup(self.catalog.close)
        self.setup = C['setup'](self.catalog)
        self.store = DocumentStore.initialize(self.root/'documents')
        self.addCleanup(self.store.close)
        value = E['fixture'](self.store).model_dump(mode='json')
        value['blocks'][0]['text'] = 'Synthetic alpha; Revenue (USD millions; shares in thousands)'
        value['blocks'][1]['table'].update(row_count=3,column_count=3,cells=[
            dict(row=r,column=c,row_span=1,column_span=1,text=t,is_header=r==0 or c==0,locations=[])
            for r,row in enumerate([['Revenue','FY2025','FY2024'],['Net sales','120','80'],['Other expense','50','40']]) for c,t in enumerate(row)])
        original = b'<html><p>Synthetic alpha; Revenue (USD millions; shares in thousands)</p><table><tr><th>Revenue</th><th>FY2025</th><th>FY2024</th></tr><tr><td>Net sales</td><td>120</td><td>80</td></tr><tr><td>Other expense</td><td>50</td><td>40</td></tr></table><p>Consolidated scope; excludes intersegment sales.</p></html>'
        value['source']['object_ref'] = self.store.content.put_object(original).model_dump(mode='json')
        value['parse']['schema_version'] = 'document-v3'
        for node in value['parse']['directory_schema']['nodes']:
            node['code'] = node['node_id'].title()
        for block in value['blocks']:
            block['body_selection'] = dict(decision='keep',reason='synthetic body',policy_version='fixture')
        value['parse']['passages'] = [dict(passage_id='first',directory_node_id='revenue',index=0,
            block_ids=[b['block_id'] for b in value['blocks']],lead_block_id=None,grouping_basis='section_content')]
        self.package = DocumentPackage.model_validate_json(json.dumps(value))
        publication = self.store.publish(self.package)
        self.reference = dict(kind='document_parse',material_id=self.package.material.material_id,
            source_version_id=self.package.source.source_version_id,parse_id=self.package.parse.parse_id,
            package_ref=publication['package_ref'])
        self.catalog.register_policy('document-read',definition=canonical(dict(schema_version='uteki-read-policy-v1',
            source_kinds=['user_file'],source_ids=[])).decode(),run_id=self.setup['run_id'])
        source = self.catalog.register_source('document-source',SourceInput(source_kind='user_file',
            publisher_name='Synthetic publisher',publisher_company_id=None,platform_name=None,
            canonical_url=self.package.source.source_url,policy_ref='document-read'),run_id=self.setup['run_id'])
        self.request = dict(question='Read the explicitly selected synthetic document',caller=dict(kind='user'),
            entities=dict(company_ids=[self.setup['company_id']]),source_policy_ref='document-read',
            expansion=dict(mode='disabled',allow=[],deny=['acquire','process']),
            run_policy=dict(max_usd='0',max_turns=100,max_wall_seconds=120,max_no_progress_turns=20),
            documents=dict(data_root=str(self.store.root),bindings=[dict(asset_ref=self.reference,
                company_id=self.setup['company_id'],source_id=source,selection_basis='Explicit synthetic input')]))
        self.service = DataService(self.catalog)
        self.context = self.service.create_context(self.request,request_key='context')['context_ref']
        self.sequence = 0

    def state(self, tool, refs=(), complete=False):
        value = dict(next_action=tool,reason='Inspect selected source',
            satisfied=[dict(need_id='n',result_refs=list(refs))] if complete else [],
            gaps=[] if complete else [dict(need_id='n',missing='Evidence needed',result_refs=list(refs))])
        if not self.service.inspect_context(self.context)['plan']['version']:
            value['plan_update'] = dict(base_version=0,needs=[dict(need_id='n',description='Read source',required=True)])
        return value

    def call(self, tool, request):
        self.sequence += 1
        return self.service.call(self.context,tool,request,state=self.state(tool),request_key=f'call-{self.sequence}')

    def test_sdk_handles_require_observation_and_deliver_without_duplicate_state(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        malformed=json.loads(asyncio.run(binding.invoke('find_assets',[])))
        self.assertEqual(malformed['error']['code'],'INVALID_REQUEST')
        schema=binding.tool_schema('deliver')
        self.assertNotIn('state',schema['properties'])
        self.assertEqual(schema['$defs']['ResultRef']['required'],['handle'])
        args=dict(request=dict(asset_ref=self.reference,targets=[dict(passage_path='Operations.Revenue.passages[0]')]),
                  state=self.state('read_evidence'))
        text=asyncio.run(binding.invoke('read_evidence',args));response=json.loads(text)
        group=response['items'][0]['group_evidence']
        request=dict(needs=[dict(need_id='n',status='supported',result_refs=[dict(handle=group['result_handle'])],gaps=[])])
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=request))))
        self.assertEqual(rejected['error']['code'],'RESULT_REF_INVALID')
        altered=deepcopy(response);altered['items'][0]['items'].pop()
        binding.observe(canonical(altered).decode(),boundary='test-mutated')
        self.assertFalse(binding.visible)
        binding.observe(text,boundary='test-actual-model-input')
        unknown=deepcopy(request);unknown['needs'][0]['result_refs']=[dict(handle='rr_0000000000000000')]
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=unknown))))
        self.assertEqual(rejected['error']['code'],'RESULT_REF_INVALID')
        self.assertIn('$.request.needs[0].result_refs[0]',rejected['error']['message'])
        # Recovery uses the same already-observed immutable references, not a new registry.
        reopened=ToolBinding(self.service,self.context);reopened.visible=set(binding.visible)
        good=json.loads(asyncio.run(reopened.invoke('deliver',dict(request=request))))
        self.assertEqual(good['delivery']['business_status'],'completed',good)
        self.assertEqual(len(good['delivery']['evidence']),6)
        self.assertEqual(good['delivery']['needs'][0]['result_refs'],[group['result_ref']])

    def test_sdk_handles_cannot_cross_contexts_or_repair_full_references(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        text=asyncio.run(binding.invoke('read_evidence',dict(request=dict(asset_ref=self.reference,targets=[dict(block_id='caption')]),state=self.state('read_evidence'))))
        response=json.loads(text);binding.observe(text,boundary='test-model-input')
        item=response['items'][0]['items'][0]
        wrong=deepcopy(item['result_ref']);wrong['operation_id']=wrong['run_id'].replace('run_','op_')
        request=dict(needs=[dict(need_id='n',status='supported',result_refs=[wrong],gaps=[])])
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=request))))
        self.assertEqual(rejected['error']['code'],'RESULT_REF_INVALID')
        another=self.service.create_context(self.request,request_key='different-context')['context_ref']
        other=ToolBinding(self.service,another)
        request['needs'][0]['result_refs']=[dict(handle=item['result_handle'])]
        rejected=json.loads(asyncio.run(other.invoke('deliver',dict(request=request))))
        self.assertEqual(rejected['error']['code'],'RESULT_REF_INVALID')

    def test_sdk_delivery_keeps_explicit_gaps_and_rejects_missing_needs(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        found=json.loads(asyncio.run(binding.invoke('find_assets',dict(request=dict(filters={}),state=self.state('find_assets')))))
        self.assertEqual(found['status'],'ok',found)
        missing=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[])))))
        self.assertEqual(missing['status'],'error')
        gap=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[dict(
            need_id='n',status='unresolved',result_refs=[],gaps=['Source not yet read','Period unknown'])])))))
        self.assertIn('delivery',gap,gap)
        self.assertEqual(gap['delivery']['business_status'],'partial',gap)
        self.assertEqual(gap['delivery']['needs'][0]['gaps'],['Source not yet read','Period unknown'])

    def test_discovery_native_schema_complete_passage_and_delivery(self):
        found = self.call('find_assets',dict(filters={}))
        self.assertEqual(found['items'][0]['asset_ref'],self.reference)
        schema = self.call('get_asset_schema',dict(asset_ref=self.reference,outline=dict(depth=3)))
        self.assertEqual(schema['items'][0]['facets'][1]['value']['code_path'],'Operations.Revenue')
        nav = self.call('search_asset',dict(asset_ref=self.reference,mode='passages',outline=dict(section_id='Operations.Revenue')))
        self.assertEqual(nav['items'][0]['path'],'Operations.Revenue.passages[0]')
        read = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(passage_path=nav['items'][0]['path'])]))
        self.assertEqual(read['status'],'ok',read)
        self.assertEqual(len(read['items'][0]['items']),5)
        refs = [item['result_ref'] for item in read['items'][0]['items']]
        delivered = self.service.deliver(self.context,dict(needs=[dict(need_id='n',status='supported',result_refs=refs,gaps=[])]),
            state=self.state('deliver',refs,True),request_key='deliver')
        self.assertEqual(len(delivered['delivery']['evidence']),5)
        self.assertEqual(delivered['delivery']['assets_used'],[self.reference])
        self.assertFalse(delivered['delivery']['business_sufficiency_evaluated'])

    def test_metadata_citations_keep_page_boundary_and_source_qualifications(self):
        from uteki.data_platform.agent.binding import ToolBinding
        from uteki.data_platform.application.exports import export_delivery
        binding=ToolBinding(self.service,self.context)
        found_text=asyncio.run(binding.invoke('find_assets',dict(request=dict(filters={}),state=self.state('find_assets'))))
        found=json.loads(found_text)['items'][0]
        self.assertEqual(found['result_ref']['kind'],'metadata')
        args=dict(request=dict(asset_ref=self.reference,outline=dict(depth=3),limit=1),
                  state=self.state('get_asset_schema',[dict(handle=found['result_handle'])],True))
        self.assertEqual(json.loads(asyncio.run(binding.invoke('get_asset_schema',args)))['error']['code'],'RESULT_REF_INVALID')
        binding.observe(found_text,boundary='test-model-input')
        text=asyncio.run(binding.invoke('get_asset_schema',args));response=json.loads(text)
        self.assertIsNotNone(response['next_cursor'])
        schema=response['items'][0]
        self.assertFalse(schema['directory']['complete'])
        self.assertEqual(len(schema['facets']),1)
        binding.observe(text,boundary='test-model-input')
        submitted=dict(needs=[dict(need_id='n',status='supported',result_refs=[dict(handle=found['result_handle']),
            dict(handle=schema['result_handle'])],gaps=[],limitations=['Only the returned metadata page was requested; source quality remains unverified'])])
        delivery=json.loads(asyncio.run(binding.invoke('deliver',dict(request=submitted))))['delivery']
        self.assertEqual(delivery['business_status'],'completed')
        self.assertEqual(delivery['metadata'],[found,schema])
        self.assertEqual(delivery['evidence'],[])
        self.assertEqual(delivery['records'],[])
        self.assertEqual(delivery['metadata'][0]['metadata']['material']['reporting_period'],found['metadata']['material']['reporting_period'])
        self.assertEqual(delivery['limitations'][0]['reason'],submitted['needs'][0]['limitations'][0])
        export_delivery(delivery,self.root/'metadata-export')
        exported=json.loads((self.root/'metadata-export/delivery.json').read_text())
        self.assertEqual(exported,delivery)
        markdown=(self.root/'metadata-export/delivery.md').read_text()
        self.assertIn('Registered metadata',markdown)
        self.assertIn('Limitation:',markdown)
        self.assertIn('not original document text',markdown)
        # Reopen the stored result without needing another source read or model call.
        self.assertEqual(self.service.inspect_context(self.context)['status'],'completed')

    def test_metadata_cannot_substitute_for_numeric_source_evidence(self):
        request=self.extracted_request()
        metadata=self.call('find_assets',dict(filters={}))['items'][0]
        request['document_records'][0]['value_evidence']=metadata['result_ref']
        rejected=self.call('query_records',request)
        self.assertEqual(rejected['error']['code'],'VALUE_SOURCE_MISMATCH')

    def test_task_gaps_remain_partial_even_with_disclosed_limitations(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        text=asyncio.run(binding.invoke('find_assets',dict(request=dict(filters={}),state=self.state('find_assets'))))
        item=json.loads(text)['items'][0];binding.observe(text,boundary='test-model-input')
        request=dict(needs=[dict(need_id='n',status='supported',result_refs=[dict(handle=item['result_handle'])],
            gaps=['Requested body was not read'],limitations=['Parser has known issues'])])
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=request))))
        self.assertEqual(rejected['status'],'error')
        request['needs'][0]['status']='partial'
        result=json.loads(asyncio.run(binding.invoke('deliver',dict(request=request))))['delivery']
        self.assertEqual(result['business_status'],'partial')
        self.assertEqual(result['needs'][0]['gaps'],['Requested body was not read'])
        self.assertEqual(result['needs'][0]['limitations'],['Parser has known issues'])

    def test_document_delivery_rejects_unquoted_note_and_metadata_source_claim(self):
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        need_schema=binding.tool_schema('deliver')['$defs']['DeliveryNeedInput']
        self.assertNotIn('note',need_schema['properties'])
        text=asyncio.run(binding.invoke('find_assets',dict(request=dict(filters={}),state=self.state('find_assets'))))
        item=json.loads(text)['items'][0];binding.observe(text,boundary='test-model-input')
        need=dict(need_id='n',status='supported',result_refs=[dict(handle=item['result_handle'])],gaps=[],
                  note='报告期间与合并口径已从原文读取')
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[need])))))
        self.assertEqual(rejected['status'],'error')
        # The canonical service also rejects it; this is not only a prompt/schema hint.
        with self.assertRaises(CatalogError) as error:
            self.service.deliver(self.context,dict(needs=[need|dict(result_refs=[item['result_ref']])]),
                state=self.state('deliver',[item['result_ref']],True),request_key='unsupported-note')
        self.assertEqual(error.exception.code,'DELIVERY_NOTE_UNSUPPORTED')
        need.pop('note')
        need['source_claims']=[dict(statement='The period and scope were verified',
            support=[dict(result_ref=dict(handle=item['result_handle']),quote=item['title'])])]
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[need])))))
        self.assertEqual(rejected['error']['code'],'SOURCE_CLAIM_INVALID')

    def test_source_claim_requires_observed_exact_quote_in_need_closure(self):
        from uteki.data_platform.agent.binding import ToolBinding
        from uteki.data_platform.application.exports import export_delivery
        binding=ToolBinding(self.service,self.context)
        text=asyncio.run(binding.invoke('read_evidence',dict(request=dict(asset_ref=self.reference,
            targets=[dict(passage_path='Operations.Revenue.passages[0]')]),state=self.state('read_evidence'))))
        group=json.loads(text)['items'][0]
        item=next(i for i in group['items'] if i['content'].get('text','').startswith('Synthetic alpha'))
        need=dict(need_id='n',status='supported',result_refs=[dict(handle=group['group_evidence']['result_handle'])],gaps=[],
            source_claims=[dict(statement='The source labels revenue in USD millions',
                support=[dict(result_ref=dict(handle=item['result_handle']),quote='Revenue (USD millions; shares in thousands)')])])
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[need])))))
        self.assertEqual(rejected['error']['code'],'RESULT_REF_INVALID')
        binding.observe(text,boundary='test-model-input')
        wrong=deepcopy(need);wrong['source_claims'][0]['support'][0]['quote']='This quote is not in the source'
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[wrong])))))
        self.assertEqual(rejected['error']['code'],'QUOTE_NOT_FOUND')
        # A source observed elsewhere is insufficient unless included in this need.
        other=next(i for i in group['items'] if i['result_ref']!=item['result_ref'])
        wrong=deepcopy(need);wrong['result_refs']=[dict(handle=other['result_handle'])]
        rejected=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[wrong])))))
        self.assertEqual(rejected['error']['code'],'SOURCE_CLAIM_INVALID')
        delivered=json.loads(asyncio.run(binding.invoke('deliver',dict(request=dict(needs=[need])))))['delivery']
        claim=delivered['needs'][0]['source_claims'][0]
        self.assertTrue(claim['quote_presence_checked'])
        self.assertEqual(claim['semantic_verification'],'not_performed')
        self.assertEqual(claim['support'][0]['locator'],item['locator'])
        self.assertEqual(claim['support'][0]['source_object'],item['source_object'])
        export_delivery(delivered,self.root/'quoted-export')
        rendered=(self.root/'quoted-export/delivery.md').read_text()
        self.assertIn('semantic correctness not independently verified',rendered)
        self.assertIn('Revenue (USD millions; shares in thousands)',rendered)
        self.assertIn(item['source_url'],rendered)

    def test_table_cells_keep_headers_footnote_and_source_reference(self):
        read = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(table_id='table',rows=[1],cols=[1])]))
        self.assertEqual(read['status'],'ok',read)
        group = read['items'][0]
        self.assertEqual(group['items'][0]['content']['text'],'120')
        self.assertEqual(group['items'][0]['locator']['row'],1)
        texts = [i['content']['text'] for i in group['context']]
        self.assertTrue(any('Consolidated' in t for t in texts))
        self.assertIn('Revenue',texts)
        self.assertIn('Net sales',texts)
        self.assertNotIn('Other expense',texts)

    def test_complete_directory_and_explicit_parent_content_scope(self):
        schema = self.call('get_asset_schema',dict(asset_ref=self.reference))['items'][0]
        self.assertTrue(schema['directory']['complete'])
        nodes = schema['directory']['nodes']
        self.assertEqual([n['code_path'] for n in nodes],['Operations','Operations.Revenue'])
        parent = nodes[0]
        self.assertEqual(parent['direct_passages'],0)
        self.assertEqual(parent['subtree_passages'],1)
        direct = self.call('search_asset',dict(asset_ref=self.reference,mode='passages',outline=dict(section_id='Operations')))
        self.assertEqual(direct['items'],[])
        subtree = self.call('search_asset',dict(asset_ref=self.reference,mode='passages',
            outline=dict(section_id='Operations'),passage_scope='subtree'))
        self.assertEqual(subtree['items'][0]['path'],'Operations.Revenue.passages[0]')
        self.assertIn('Synthetic alpha',subtree['items'][0]['lead_text'])
        invalid = self.call('search_asset',dict(asset_ref=self.reference,mode='passages',outline=dict(section_id='Operations',depth=3)))
        self.assertEqual(invalid['error']['code'],'INVALID_REQUEST')
        self.assertIn('passage_scope',invalid['error']['message'])

    def test_symbol_discovery_requires_confirmed_mapping_and_preserves_asset_binding(self):
        from uteki.data_platform.contracts.assets import SecurityInput
        security=dict(company_id=self.setup['company_id'],ticker='TEST',exchange_mic='XNAS',
            security_type='common',valid_from=None,valid_to=None,status='confirmed',evidence=C['evidence']())
        self.catalog.register_security('test-symbol',SecurityInput(**security),run_id=self.setup['run_id'])
        found=self.call('find_assets',dict(filters=dict(securities=[dict(ticker='TEST',exchange_mic='XNAS')])))
        self.assertEqual(found['items'][0]['asset_ref'],self.reference)
        self.assertEqual(found['items'][0]['metadata']['symbol_matches'][0]['temporal_validity'],'not_asserted')
        read=self.call('read_evidence',dict(asset_ref=found['items'][0]['asset_ref'],
            targets=[dict(section_path='Operations',include_descendants=True)],max_bytes=80000))
        self.assertEqual(len(read['items'][0]['items']),5)
        unknown=self.call('find_assets',dict(filters=dict(securities=[dict(ticker='MISSING',exchange_mic='XNAS')])))
        self.assertEqual(unknown['error']['code'],'NOT_FOUND')
        historical=self.call('find_assets',dict(filters=dict(securities=[dict(ticker='TEST',exchange_mic='XNAS')]),
            as_of='2026-01-01T00:00:00Z'))
        self.assertEqual(historical['error']['code'],'UNRESOLVED_TIME')

    def test_reused_symbol_is_ambiguous_without_an_evidenced_date(self):
        from datetime import date
        from uteki.data_platform.contracts.assets import SecurityInput
        other=self.catalog.register_company('other-symbol-owner',C['company']('other'),run_id=self.setup['run_id'])
        for year,company in [(2020,self.setup['company_id']),(2021,other)]:
            self.catalog.register_security(f'symbol-{year}',SecurityInput(company_id=company,ticker='REUSED',
                exchange_mic='XNAS',security_type='common',valid_from=date(year,1,1),valid_to=date(year,12,31),
                status='confirmed',evidence=C['evidence']()),run_id=self.setup['run_id'])
        response=self.call('find_assets',dict(filters=dict(securities=[dict(ticker='REUSED',exchange_mic='XNAS')])))
        self.assertEqual(response['error']['code'],'AMBIGUOUS_ENTITY')

    def test_required_security_lookup_cannot_be_replaced_or_bypassed(self):
        from uteki.data_platform.contracts.assets import SecurityInput
        security=dict(ticker='TEST',exchange_mic='XNAS')
        self.catalog.register_security('required-symbol',SecurityInput(company_id=self.setup['company_id'],
            **security,security_type='common',valid_from=None,valid_to=None,status='confirmed',evidence=C['evidence']()),
            run_id=self.setup['run_id'])
        request=deepcopy(self.request);request['required_securities']=[security]
        self.context=self.service.create_context(request,request_key='required-symbol-context')['context_ref']
        blocked=self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(block_id='caption')]))
        self.assertEqual(blocked['error']['code'],'ASSET_DISCOVERY_REQUIRED')
        blocked=self.call('find_assets',dict(filters=dict(company_ids=[self.setup['company_id']])))
        self.assertEqual(blocked['error']['code'],'SECURITY_FILTER_REQUIRED')
        wrong=self.call('find_assets',dict(filters=dict(securities=[dict(ticker='OTHER',exchange_mic='XNAS')])))
        self.assertEqual(wrong['error']['code'],'SECURITY_FILTER_REQUIRED')
        found=self.call('find_assets',dict(filters=dict(securities=[security])))
        self.assertEqual(found['status'],'ok',found)
        self.assertEqual(found['items'][0]['metadata']['symbol_matches'][0]['ticker'],'TEST')
        read=self.call('read_evidence',dict(asset_ref=found['items'][0]['asset_ref'],targets=[dict(block_id='caption')]))
        self.assertEqual(read['status'],'ok',read)

    def test_required_security_contract_preserves_legacy_and_clarification_constraints(self):
        from types import SimpleNamespace
        from uteki.data_platform.application.clarification import validate_narrowing
        from uteki.data_platform.contracts.query import ContextRequest,ReadPolicy,parse
        self.assertNotIn('required_securities',parse(ContextRequest,self.request).context_payload())
        request=deepcopy(self.request);request['required_securities']=[dict(ticker='ANOTHER',exchange_mic='XNYS')]
        context=self.service.create_context(request,request_key='another-required-security')['context_ref']
        parent=SimpleNamespace(data=dict(context=self.service.inspect_context(context)['context']))
        with self.assertRaises(CatalogError) as error:
            validate_narrowing(parent,parse(ContextRequest,self.request),parent.data['context']['company_ids'],
                               parse(ReadPolicy,parent.data['context']['read_policy']))
        self.assertEqual(error.exception.code,'SCOPE_VIOLATION')
        duplicate=deepcopy(request);duplicate['required_securities']*=2
        with self.assertRaises(ValueError):parse(ContextRequest,duplicate)

    def test_currency_unit_labels_are_source_based_across_codes_and_names(self):
        from uteki.data_platform.structured.document_records import require_source_unit
        examples=[('USD',['Revenue in USD millions']),('CAD',['CAD millions']),
            ('Canadian dollars',['Revenue in Canadian dollars (millions)']),
            ('U.S. dollars',['Net sales are expressed in U.S. dollars.']),
            ('EUR',['EUR 123']),('€',['€ 123']),('kilograms',['Weight in kilograms'])]
        for unit,quotes in examples:
            with self.subTest(unit=unit):self.assertEqual(require_source_unit(unit,quotes),'explicit_source_label')
        missing=[('USD',['$ 123','In millions']),('USD',['USDC amounts']),
            ('USD',['CAD millions']),('$',['$ 123']),('dollars',['Canadian dollars']),('millions',['In millions'])]
        for unit,quotes in missing:
            with self.subTest(unit=unit,quotes=quotes),self.assertRaises(CatalogError) as error:
                require_source_unit(unit,quotes)
            self.assertEqual(error.exception.code,'UNIT_EVIDENCE_REQUIRED')

    def test_currency_evidence_error_allows_source_supported_repair(self):
        request=self.extracted_request();bad=deepcopy(request)
        for record in bad['document_records']:
            record['support']['unit'][0]['quote']='millions; shares in thousands'
        rejected=self.call('query_records',bad)
        self.assertEqual(rejected['error']['code'],'UNIT_EVIDENCE_REQUIRED')
        repaired=self.call('query_records',request)
        self.assertEqual(repaired['status'],'ok',repaired)
        records=[item for item in repaired['items'] if item['result_ref']['kind']=='record']
        self.assertEqual(len(records),2)
        self.assertTrue(all(item['unit_basis']=='explicit_source_label' for item in records))

    def test_group_reference_delivers_all_members_without_copying_block_references(self):
        from uteki.data_platform.application.session import Session
        read = self.call('read_evidence',dict(asset_ref=self.reference,
            targets=[dict(passage_path='Operations.Revenue.passages[0]')],max_bytes=80000))
        self.assertEqual(read['status'],'ok',read)
        group = read['items'][0]['group_evidence']
        reference = group['result_ref']
        self.assertEqual(len(group['dependency_refs']),5)
        self.assertEqual(Session(self.catalog,self.context).lookup(reference),group)
        delivery = self.service.deliver(self.context,dict(needs=[dict(need_id='n',status='supported',
            result_refs=[reference],gaps=[])]),state=self.state('deliver',[reference],True),request_key='whole-group')['delivery']
        members = [e for e in delivery['evidence'] if e['kind']!='passage']
        self.assertEqual({e['locator']['block_id'] for e in members},{b.block_id for b in self.package.blocks})
        self.assertFalse(delivery['business_sufficiency_evaluated'])

    def test_oversized_group_never_registers_hidden_members_or_group(self):
        from uteki.data_platform.application.session import Session
        before = dict(Session(self.catalog,self.context).data['results'])
        read = self.call('read_evidence',dict(asset_ref=self.reference,
            targets=[dict(passage_path='Operations.Revenue.passages[0]')],max_bytes=2000))
        self.assertEqual(read['items'],[])
        self.assertTrue(read['truncated'])
        self.assertEqual(Session(self.catalog,self.context).data['results'],before)
        resumed = self.call('read_evidence',dict(asset_ref=self.reference,
            targets=[dict(passage_path='Operations.Revenue.passages[0]')],max_bytes=80000,cursor=read['next_cursor']))
        self.assertEqual(resumed['status'],'ok',resumed)
        self.assertEqual(resumed['items'][0]['group_evidence']['coverage']['member_count'],5)

    def test_parent_section_cursor_reads_every_block_and_delivers_all_pages(self):
        from uteki.data_platform.application.session import Session
        request=dict(asset_ref=self.reference,targets=[dict(section_path='Operations',include_descendants=True)],
                     max_bytes=6500,context=['section_title'])
        cursor=None; block_ids=[]; page_refs=[]; previous_end=0
        for _ in range(10):
            response=self.call('read_evidence',request|dict(cursor=cursor))
            self.assertFalse(response['issues'],response)
            self.assertLessEqual(len(canonical(response)),request['max_bytes'])
            item=response['items'][0]
            self.assertEqual(item['target'],request['targets'][0])
            self.assertEqual(item['coverage']['block_start'],previous_end)
            previous_end=item['coverage']['block_end_exclusive']
            block_ids.extend(e['locator']['block_id'] for e in item['items'])
            page_refs.append(item['page_evidence']['result_ref'])
            cursor=response['next_cursor']
            if cursor is None:break
        else:self.fail('section cursor did not finish')
        self.assertGreater(len(page_refs),1)
        self.assertEqual(block_ids,[b.block_id for b in self.package.blocks])
        self.assertEqual(previous_end,item['coverage']['total_blocks'])
        self.assertEqual(item['page_evidence']['coverage']['status'],'section_page')
        delivered=self.service.deliver(self.context,dict(needs=[dict(need_id='n',status='supported',
            result_refs=page_refs,gaps=[])]),state=self.state('deliver',page_refs,True),request_key='section-pages')['delivery']
        members=[e for e in delivered['evidence'] if e['kind']!='section_page']
        self.assertEqual({e['locator']['block_id'] for e in members},set(block_ids))
        coverage=delivered['read_coverage'][0]
        self.assertEqual(coverage['ranges'],[[0,len(block_ids)]])
        self.assertEqual(coverage['missing_ranges'],[])
        self.assertTrue(coverage['stored_section_complete'])
        from uteki.data_platform.application.exports import render_markdown
        self.assertIn('zero-based ranges [start, end), end excluded: [0, 5)',render_markdown(delivered))

    def test_coverage_omissions_overlap_and_scope_are_not_falsely_complete(self):
        from uteki.data_platform.application.delivery_checks import section_coverage
        request=dict(asset_ref=self.reference,targets=[dict(section_path='Operations',include_descendants=True)],
                     max_bytes=6500,context=['section_title'])
        first=self.call('read_evidence',request)['items'][0]['page_evidence']
        summary=section_coverage([first,deepcopy(first)])[0]
        end=first['coverage']['block_end_exclusive']
        self.assertEqual(summary['delivered_blocks'],end)
        self.assertEqual(summary['missing_ranges'],[[end,5]])
        self.assertFalse(summary['stored_section_complete'])
        changed=deepcopy(first);changed['asset_ref']['parse_id']='independent-parse'
        self.assertEqual(len(section_coverage([first,changed])),2)
        changed=deepcopy(first);changed['locator']['include_descendants']=False
        self.assertEqual(len(section_coverage([first,changed])),2)
        changed=deepcopy(first);changed['content']['member_block_ids'][0]='contradictory-member'
        with self.assertRaises(CatalogError) as error:section_coverage([first,changed])
        self.assertEqual(error.exception.code,'COVERAGE_INCONSISTENT')

    def test_section_pagination_never_skips_oversized_blocks_or_changes_scope(self):
        from uteki.data_platform.application.session import Session
        from uteki.data_platform.retrieval.cursors import fingerprint
        from uteki.data_platform.contracts.common import digest
        request=dict(asset_ref=self.reference,targets=[dict(section_path='Operations',include_descendants=True)],max_bytes=2000)
        parsed=parse(ReadEvidence,request)
        session=Session(self.catalog,self.context)
        session.data['cursors']['old-section-layout']=dict(
            fingerprint=fingerprint(self.context,'read_evidence',parsed),
            version=digest(parsed.asset_ref.canonical_bytes()),offset=0)
        session.save()
        old=self.call('read_evidence',request|dict(cursor='old-section-layout'))
        self.assertEqual(old['error']['code'],'CURSOR_EXPIRED')
        before=dict(Session(self.catalog,self.context).data['results'])
        first=self.call('read_evidence',request)
        self.assertEqual(first['items'],[])
        self.assertEqual(first['issues'][0]['code'],'ITEM_TOO_LARGE')
        self.assertEqual(first['coverage']['block_end_exclusive'],0)
        self.assertEqual(Session(self.catalog,self.context).data['results'],before)
        bad=self.call('read_evidence',request|dict(cursor=first['next_cursor'],
            targets=[dict(section_path='Operations',include_descendants=False)]))
        self.assertEqual(bad['error']['code'],'CURSOR_MISMATCH')
        resumed=self.call('read_evidence',request|dict(max_bytes=80000,cursor=first['next_cursor']))
        self.assertEqual(resumed['coverage']['block_start'],0)
        self.assertEqual(len(resumed['items'][0]['items']),5)
        self.assertIsNone(resumed['next_cursor'])

    def test_document_binding_exposes_and_executes_only_supported_parameters(self):
        import asyncio
        from uteki.data_platform.agent.binding import ToolBinding
        binding=ToolBinding(self.service,self.context)
        self.assertNotIn('request_asset_update',binding.envelopes)
        search_schema=json.dumps(binding.envelopes['search_asset'].model_json_schema())
        self.assertNotIn('any_terms',search_schema)
        self.assertNotIn('text_layer',search_schema)
        self.assertNotIn('list_item',search_schema)
        self.assertNotIn('roles',json.dumps(binding.envelopes['find_assets'].model_json_schema()))
        bad=json.loads(asyncio.run(binding.invoke('find_assets',dict(request=dict(filters=dict(roles=['issuer'])),
            state=self.state('find_assets')))))
        self.assertEqual(bad['error']['code'],'INVALID_REQUEST')
        self.assertIn('state',bad['error']['current_task_state'])
        reply=json.loads(asyncio.run(binding.invoke('get_asset_schema',dict(request=dict(asset_ref=self.reference),
            state=self.state('get_asset_schema')))))
        self.assertEqual(reply['status'],'ok',reply)
        self.assertTrue(reply['items'][0]['directory']['complete'])

    def test_whole_table_exposes_complete_grid_and_reports_actual_bounds(self):
        read = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(table_id='table')],max_bytes=24000))
        self.assertEqual(read['status'],'ok',read)
        table = read['items'][0]['items'][0]['content']['table']
        self.assertEqual((table['row_count'],table['column_count']),(3,3))
        self.assertEqual(len(table['cells']),9)
        invalid = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(table_id='table',rows=[0],cols=[3])]))
        self.assertEqual(invalid['error']['code'],'INVALID_REQUEST')
        self.assertIn('column_count=3',invalid['error']['message'])

    def test_unsupported_read_options_do_not_silently_succeed(self):
        request = dict(asset_ref=self.reference,targets=[dict(block_id='caption')])
        for options in (dict(include_image=True),dict(table_representation='compact')):
            with self.subTest(options=options):
                result = self.call('read_evidence',request|options)
                self.assertEqual(result['status'],'error',result)
                self.assertEqual(result['error']['code'],'CAPABILITY_UNSUPPORTED')
                self.assertEqual(result['items'],[])

    def extracted_request(self):
        read = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(table_id='table',rows=[1],cols=[1,2])]))
        group = read['items'][0]
        pool = group['items']+group['context']
        def proof(text):
            item = next(i for i in pool if text in i['content']['text'])
            return dict(result_ref=item['result_ref'],quote=text)
        rows = []
        for value, year in zip(group['items'],(2025,2024)):
            rows.append(dict(record_id=f'revenue-{year}',value_evidence=value['result_ref'],raw_value=value['content']['text'],
                metric='Net sales',period_label=f'FY{year}',fiscal_year=year,period_kind='annual',unit='USD',scale=6,
                entity='Synthetic alpha',entity_scope='consolidated',interpretation='Synthetic source column interpretation',
                support=dict(metric=[proof('Net sales')],period=[proof(f'FY{year}')],unit=[proof('USD millions; shares in thousands')],
                    entity=[proof('Synthetic alpha')],scope=[proof('Consolidated scope')])) )
        spec = dict(calc_id='growth',op='growth',operands=[dict(asset_ref=self.reference,record_selector=dict(record_id=r['record_id'])) for r in rows],
                    output_unit='ratio',period_policy='distinct_nonoverlapping',comparison_basis='Explicit annual columns of the same synthetic statement')
        return dict(asset_ref=self.reference,select={},document_records=rows,calculations=[spec],max_bytes=80000)

    def test_source_bound_records_code_calculation_and_dependency_delivery(self):
        request = self.extracted_request()
        response = self.call('query_records',request)
        self.assertEqual(response['status'],'ok',response)
        records = [i for i in response['items'] if i['result_ref']['kind']=='record']
        result = next(i for i in response['items'] if i['result_ref']['kind']=='calculation')
        self.assertEqual([r['value'] for r in records],['120000000','80000000'])
        self.assertEqual(result['value'],'0.500000000000000000')
        self.assertEqual(records[0]['semantic_verification'],'not_performed')
        ref = result['result_ref']
        delivery = self.service.deliver(self.context,dict(needs=[dict(need_id='n',status='supported',result_refs=[ref],gaps=[])]),
            state=self.state('deliver',[ref],True),request_key='numeric-delivery')['delivery']
        self.assertEqual(len(delivery['records']),2)
        self.assertGreater(len(delivery['evidence']),2)
        from uteki.data_platform.application.exports import export_delivery
        import csv
        manifest = export_delivery(delivery,self.root/'exported')
        self.assertEqual(set(manifest['files']),{'delivery.json','delivery.md','records.csv','calculations.csv'})
        saved = json.loads((self.root/'exported/delivery.json').read_text())
        self.assertEqual(saved,delivery)
        with (self.root/'exported/records.csv').open(newline='') as stream:
            self.assertEqual([r['value'] for r in csv.DictReader(stream)],['120000000','80000000'])
        with (self.root/'exported/calculations.csv').open(newline='') as stream:
            calculations = list(csv.DictReader(stream))
        self.assertEqual(len(calculations), 1)
        self.assertEqual(calculations[0]['value'], '0.500000000000000000')
        self.assertEqual(calculations[0]['formula'], '(operand[0] - operand[1]) / operand[1]')
        self.assertEqual(json.loads(calculations[0]['operand_refs']), delivery['calculations'][0]['operand_refs'])
        self.assertEqual(json.loads(calculations[0]['result_ref']), delivery['calculations'][0]['result_ref'])
        self.assertEqual(calculations[0]['semantic_verification'], 'source_interpretations_not_independently_verified')
        with self.assertRaises(FileExistsError): export_delivery(delivery,self.root/'exported')

    def test_full_record_dependencies_obey_explicit_budget_and_fit_default(self):
        from uteki.data_platform.agent.document_contracts import DocumentRecords
        request=self.extracted_request()
        rejected=self.call('query_records',request|dict(max_bytes=2000))
        self.assertEqual(rejected['error']['code'],'OUTPUT_LIMIT')
        self.assertIn('requires ',rejected['error']['message'])
        self.assertIn('max_bytes=2000',rejected['error']['message'])
        request.pop('max_bytes')
        projected=DocumentRecords.model_validate_json(canonical(request)).model_dump(mode='json')
        response=self.call('query_records',projected)
        self.assertEqual(response['status'],'ok',response)
        self.assertGreater(len(canonical(response)),2000)
        self.assertEqual(sum(i['result_ref']['kind']=='record' for i in response['items']),2)
        self.assertTrue(any(i['result_ref']['kind']=='evidence' for i in response['items']))
        self.assertTrue(any(i['result_ref']['kind']=='calculation' for i in response['items']))

    def test_fabricated_quote_wrong_raw_value_and_scale_are_rejected(self):
        request = self.extracted_request()
        changed = deepcopy(request);changed['document_records'][0]['support']['scope'][0]['quote']='not in the source'
        self.assertEqual(self.call('query_records',changed)['error']['code'],'QUOTE_NOT_FOUND')
        changed = deepcopy(request);changed['document_records'][0]['raw_value']='999'
        self.assertEqual(self.call('query_records',changed)['error']['code'],'VALUE_SOURCE_MISMATCH')
        changed = deepcopy(request);changed['document_records'][0]['scale']=9
        self.assertEqual(self.call('query_records',changed)['error']['code'],'SCALE_SOURCE_MISMATCH')

    def test_calculation_uses_prior_records_and_wrong_period_order_remains_partial(self):
        request = self.extracted_request()
        response = self.call('query_records',request|dict(calculations=[]))
        self.assertEqual(response['status'],'ok',response)
        request['document_records']=[]
        request['calculations'][0]['operands'].reverse()
        response = self.call('query_records',request)
        self.assertEqual(response['status'],'partial',response)
        result = next(i for i in response['items'] if i['result_ref']['kind']=='calculation')
        self.assertIsNone(result['value'])
        self.assertIn('GROWTH_OPERAND_ORDER',result['limitations'])

    def test_search_cursor_is_query_bound_and_repeated_metadata_is_not_progress(self):
        request = dict(asset_ref=self.reference,mode='text',text=dict(match='phrase',value='Revenue'),limit=1)
        first = self.call('search_asset',request)
        self.assertIsNotNone(first['next_cursor'],first)
        second = self.call('search_asset',request|dict(cursor=first['next_cursor']))
        self.assertNotEqual(first['items'],second['items'])
        wrong = self.call('search_asset',request|dict(cursor=first['next_cursor'],text=dict(match='phrase',value='other')))
        self.assertEqual(wrong['error']['code'],'CURSOR_MISMATCH')
        self.call('search_asset',request)
        self.assertGreater(self.service.inspect_context(self.context)['no_progress_turns'],0)

    def test_search_native_section_table_filters_and_titles(self):
        request=dict(asset_ref=self.reference,mode='text',text=dict(match='phrase',value='Revenue'),
            scope=dict(section_ids=['Operations'],block_kinds=['table'],text_origins=['table']),
            include=['snippet','section_title'])
        found=self.call('search_asset',request)
        self.assertEqual(found['status'],'ok',found)
        self.assertEqual([i['ref']['block_id'] for i in found['items']],['table'])
        self.assertEqual(found['items'][0]['sections'][0]['code_path'],'Operations.Revenue')
        invalid=self.call('search_asset',request|dict(scope=dict(block_kinds=['list_item'])))
        self.assertEqual(invalid['error']['code'],'CAPABILITY_UNSUPPORTED')

    def test_context_does_not_expand_unrequested_or_wrong_side_neighbors(self):
        request=dict(asset_ref=self.reference,targets=[dict(block_id='footnote')],
            context=['section_title','units'],neighbors=dict(before=3,after=2))
        read=self.call('read_evidence',request)
        self.assertEqual(read['status'],'ok',read)
        self.assertEqual(read['items'][0]['context'],[])
        self.assertEqual(read['items'][0]['items'][0]['sections'][0]['code_path'],'Operations.Revenue')
        read=self.call('read_evidence',request|dict(context=['neighbors'],neighbors=dict(before=0,after=1)))
        self.assertEqual([i['reader_ref']['block_id'] for i in read['items'][0]['context']],['chart'])
        read=self.call('read_evidence',request|dict(context=['neighbors'],neighbors=dict(before=2,after=0)))
        self.assertEqual({i['reader_ref']['block_id'] for i in read['items'][0]['context']},{'caption','table'})

    def test_oversized_read_cursor_allows_larger_budget_but_not_changed_targets(self):
        request=dict(asset_ref=self.reference,targets=[dict(table_id='table')],max_bytes=2000)
        first=self.call('read_evidence',request)
        self.assertEqual(first['items'],[])
        self.assertEqual(first['issues'][0]['code'],'ITEM_TOO_LARGE')
        second=self.call('read_evidence',request|dict(max_bytes=24000,cursor=first['next_cursor']))
        self.assertEqual(second['status'],'ok',second)
        self.assertEqual(len(second['items'][0]['items'][0]['content']['table']['cells']),9)
        wrong=self.call('read_evidence',request|dict(targets=[dict(block_id='caption')],cursor=first['next_cursor']))
        self.assertEqual(wrong['error']['code'],'CURSOR_MISMATCH')

    def test_legacy_read_cursor_remains_valid_for_its_original_parameters(self):
        from uteki.data_platform.application.session import Session
        from uteki.data_platform.retrieval.cursors import fingerprint
        request=dict(asset_ref=self.reference,targets=[dict(table_id='table')],max_bytes=24000)
        parsed=parse(ReadEvidence,request)
        session=Session(self.catalog,self.context)
        from uteki.data_platform.contracts.common import digest
        session.data['cursors']['legacy-read']=dict(fingerprint=fingerprint(self.context,'read_evidence',parsed,legacy_read=True),
            version=digest(parsed.asset_ref.canonical_bytes()),offset=0)
        session.save()
        result=self.call('read_evidence',request|dict(cursor='legacy-read'))
        self.assertEqual(result['status'],'ok',result)

    def test_invalid_version_and_missing_source_fail_without_success(self):
        wrong = deepcopy(self.reference);wrong['source_version_id']='other'
        read = self.call('get_asset_schema',dict(asset_ref=wrong))
        self.assertEqual(read['error']['code'],'SCOPE_DENIED')
        # Resolve the actual CAS path via its public path convention used by ContentStore.
        paths = list((self.store.root/'objects').rglob(self.package.source.object_ref.sha256))
        self.assertEqual(len(paths),1)
        paths[0].unlink()
        read = self.call('read_evidence',dict(asset_ref=self.reference,targets=[dict(block_id='caption')]))
        self.assertEqual(read['status'],'error',read)
        self.assertEqual(read['items'],[])

    def test_legacy_context_bytes_and_unadmitted_document_reference(self):
        old = deepcopy(self.request);old.pop('documents')
        payload = parse(ContextRequest,old).context_payload()
        self.assertNotIn('documents',payload)
        self.context = self.service.create_context(old,request_key='legacy')['context_ref']
        read = self.call('get_asset_schema',dict(asset_ref=self.reference))
        self.assertEqual(read['error']['code'],'SCOPE_DENIED')


if __name__ == '__main__':
    unittest.main()
