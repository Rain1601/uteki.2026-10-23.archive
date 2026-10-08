"""Real indexed HTML + scripted system navigation; no model-quality claims."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_company_materialization import filing
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.business_map.runtime_materials import build_runtime_packet
from uteki.agents.business_map.product_run import verify_packet
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


class RuntimeMaterialsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.open_case()

    def open_case(self, cik='987', period='2025-12-31', prefix='case'):
        work = self.root/prefix; work.mkdir()
        identity = (f'<p><ix:nonNumeric name="dei:EntityCentralIndexKey">{cik}</ix:nonNumeric></p>'
                    '<p><ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric></p>'
                    f'<p><ix:nonNumeric name="dei:DocumentPeriodEndDate">{period}</ix:nonNumeric></p>')
        raw = filing(cik=cik, start=period[:4]+'-01-01', end=period).replace(b'<h1>', identity.encode()+b'<h1>', 1)
        (work/'original.html').write_bytes(raw)
        company = f'sec-{int(cik):010d}'
        run = dict(company=dict(company_id=company,cik=cik),as_of='2026-03-01', documents=[dict(
            source_id='annual',source_url='https://www.sec.gov/Archives/edgar/data/'+cik+'/annual.htm',
            form='10-K',filed_at='2026-02-01',period_end=period,content_sha256=digest(raw),
            path='original.html',mime_type='text/html',status='frozen')])
        materialize_sources(run, work, work/'dataset')
        owner = QueryDataPort(work/'dataset'); self.addCleanup(owner.close)
        scope = dict(snapshot_id=owner.snapshot_id,company_ids=[company],source_snapshot_ids=['annual'],
            source_policy_id='local-frozen-v1',knowledge_cutoff='2026-03-01',include_candidates=True)
        scoped = owner.scoped(scope)
        nodes = [n for n in scoped.outline_source({'source_snapshot_id':'annual'})['nodes'] if n['kind']=='item']
        requirements = [dict(requirement_id='r'+str(i),kind='read_node',description='Read selected chapter',
            source_id='annual',node_id=n['node_id']) for i,n in enumerate(nodes)]
        actions = [dict(action='plan',reason='System selects actual outline chapters',requirements=requirements)]
        actions += [dict(action='read_source',requirement_ids=[r['requirement_id']],read=dict(
            source_snapshot_id='annual',node_id=r['node_id'],count=12)) for r in requirements]
        actions += [dict(action='finish')]
        result = asyncio.run(AutonomousDataAgent(owner, ScriptedPlanner(actions), purpose='business_materials', limits={'max_steps':len(actions)}).run(
            {'question':'Read business and risk chapters completely', 'scope':scope}, output=work/'query'))
        self.assertEqual(result['status'],'evidence_ready',result.get('gaps'))
        self.work, self.port, self.result = work, scoped, result

    def build(self, **changes):
        options = dict(query_output=self.work/'query',output=self.work/'materials',root=self.root,max_bytes=1000000)
        options.update(changes)
        return build_runtime_packet(self.port,self.result,**options)

    def reseal_query(self):
        folder=self.work/'query'
        (folder/'result.json').write_text(json.dumps(self.result))
        path=folder/'manifest.json'; m=json.loads(path.read_text())
        for name in m['files']:m['files'][name]=digest((folder/name).read_bytes())
        path.write_text(json.dumps(m))

    def test_two_real_nodes_freeze_and_validate_without_caller_block_selection(self):
        result=self.build();packet=json.loads(Path(result['packet_path']).read_text())
        self.assertEqual(len(packet['extraction_scope']['selected_nodes']),2)
        self.assertEqual(result['selection_report']['plan_origin'],'scripted_fixture')
        self.assertEqual(result['selection_report']['semantic_completeness'],'not_evaluated')
        verify_packet(packet,self.root,company_id=packet['company_id'],document_id=packet['document_id'],
                      period_end=packet['period_end'],contract_version='business-draft-v2')
        self.assertTrue(any('Independent source' in b['text'] for b in packet['blocks']))

    def test_another_issuer_and_period_uses_same_runtime(self):
        self.open_case(cik='456',period='2024-12-31',prefix='other')
        packet=json.loads(Path(self.build()['packet_path']).read_text())
        self.assertEqual((packet['company_id'],packet['period_end']),('sec-0000000456','2024-12-31'))

    def test_navigation_plan_discovers_real_nodes_before_read_plan(self):
        owner=QueryDataPort(self.work/'dataset');self.addCleanup(owner.close)
        scope=self.port.scope.model_dump(mode='json')
        info=dict(requirement_id='navigation',kind='information',description='Find relevant source chapters')
        chosen=[]
        def append_plan(packet):
            nodes=[n for n in packet['observation']['result']['nodes'] if n['kind']=='item']
            chosen.extend(dict(requirement_id='body'+str(i),kind='read_node',description='Read discovered chapter',
                source_id='annual',node_id=n['node_id']) for i,n in enumerate(nodes))
            return dict(action='plan',reason='Actual outline supplied the nodes',requirements=[info,*chosen])
        def read_at(i):
            return lambda packet:dict(action='read_source',requirement_ids=['navigation',chosen[i]['requirement_id']],
                read=dict(source_snapshot_id='annual',node_id=chosen[i]['node_id'],count=12))
        actions=[dict(action='plan',reason='Discover source first',requirements=[info]),
            dict(action='outline_source',requirement_ids=['navigation'],outline=dict(source_snapshot_id='annual')),
            append_plan,read_at(0),read_at(1),dict(action='finish')]
        result=asyncio.run(AutonomousDataAgent(owner,ScriptedPlanner(actions),purpose='business_materials',limits={'max_steps':len(actions)}).run(
            {'question':'Find and read business materials','scope':scope},output=self.work/'navigation-query'))
        self.assertEqual(result['status'],'evidence_ready',result['gaps'])
        result=build_runtime_packet(self.port,result,query_output=self.work/'navigation-query',
            output=self.work/'navigation-materials',root=self.root,max_bytes=1000000)
        self.assertEqual(len(result['selection_report']['extraction_scope']['selected_nodes']),2)

    def test_deleted_required_block_cannot_be_hidden_by_claimed_complete(self):
        row=self.result['coverage'][0]
        row['required_block_ids']=row['required_block_ids'][1:]
        row['returned_block_ids']=row['required_block_ids'][:]
        self.reseal_query()
        with self.assertRaisesRegex(ValueError,'coverage_differs_from_index'):self.build()

    def test_multiple_sources_or_answer_only_plan_do_not_become_materials(self):
        original=deepcopy(self.result)
        self.result['coverage'][1]['source_id']='another-source';self.reseal_query()
        with self.assertRaisesRegex(ValueError,'multiple_sources_not_supported'):self.build()
        self.result=deepcopy(original);self.result['coverage'][0]['kind']='source_answer';self.reseal_query()
        with self.assertRaisesRegex(ValueError,'read_node_plan_required'):self.build()

    def test_frozen_packet_changed_node_and_original_are_rejected(self):
        built=self.build();packet=json.loads(Path(built['packet_path']).read_text())
        altered=deepcopy(packet);altered['extraction_scope']['selected_nodes'][0]['end_block_id']=altered['blocks'][0]['id']
        kwargs=dict(company_id=packet['company_id'],document_id=packet['document_id'],period_end=packet['period_end'],contract_version='business-draft-v2')
        with self.assertRaisesRegex(ValueError,'scope_changed'):verify_packet(altered,self.root,**kwargs)
        path=self.root/packet['source_local_path'];path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'source_changed'):verify_packet(packet,self.root,**kwargs)

    def test_complete_claim_without_actual_delivery_fails(self):
        path=self.work/'query/evidence-bundle.json';bundle=json.loads(path.read_text())
        bundle['delivered_body']={};path.write_text(json.dumps(bundle));self.reseal_query()
        with self.assertRaisesRegex(ValueError,'not_actually_delivered'):self.build()

    def test_incomplete_pending_gap_and_unsealed_result_fail(self):
        original=deepcopy(self.result)
        for changes in [dict(status='partial'),dict(purpose='question_answer'),dict(pending_body_reads=[{'missing':'body'}]),dict(gaps=[{'reason':'unread'}])]:
            self.result={**original,**changes};self.reseal_query()
            with self.assertRaisesRegex(ValueError,'complete_body_required'):self.build()
        self.result=original
        with self.assertRaisesRegex(ValueError,'not_frozen'):self.build()

    def test_cross_scope_source_and_period_rejected(self):
        original=deepcopy(self.result)
        for changes in [dict(company_ids=['sec-0000000123']),dict(source_snapshot_ids=['other-source'])]:
            self.result=deepcopy(original);self.result['active_scope'].update(changes);self.reseal_query()
            with self.assertRaisesRegex(ValueError,'active_scope_mismatch'):self.build()
        self.result=original;self.reseal_query()
        source=self.port.sources[0];prior=source['period_end'];source['period_end']='2024-12-31'
        try:
            with self.assertRaisesRegex(ValueError,'source_metadata_changed'):self.build()
        finally:source['period_end']=prior

    def test_size_limit_never_truncates_or_writes_partial_materials(self):
        with self.assertRaisesRegex(ValueError,'exceeds_max_bytes'):self.build(max_bytes=100)
        self.assertFalse((self.work/'materials').exists())
        with self.assertRaisesRegex(ValueError,'explicit_max_bytes'):self.build(max_bytes=None)

    def test_packet_deletion_and_renumbering_fail_against_frozen_index(self):
        packet=json.loads(Path(self.build()['packet_path']).read_text())
        removed=packet['blocks'].pop(1);packet['extraction_scope']['section_block_ids'].remove(removed['id'])
        for i,b in enumerate(packet['blocks'],1):b['ordinal']=i
        with self.assertRaisesRegex(ValueError,'runtime_selection_scope_changed'):
            verify_packet(packet,self.root,company_id=packet['company_id'],document_id=packet['document_id'],
                period_end=packet['period_end'],contract_version='business-draft-v2')

    def test_unsupported_source_is_not_silently_reinterpreted(self):
        self.port.sources[0]['form']='20-F'
        dataset=self.port.dataset;path=dataset/'sources.json'
        sources=json.loads(path.read_text());sources[0]['form']='20-F';path.write_text(json.dumps(sources))
        mp=dataset/'manifest.json';manifest=json.loads(mp.read_text())
        manifest['files']['sources.json']=digest(path.read_bytes());mp.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'sec_html_10k_only'):self.build()


if __name__=='__main__':unittest.main()
