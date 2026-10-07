import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit import test_extraction_batches as fixtures
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet
from uteki.infrastructure.research_data.fact_completion import (complete_required_facts,
    merge_delivered_extractions, verify_completion_publication, claim_completion_successor,
    prepare_completion_batch)
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.extraction_batches import table_batch_catalog


class FactCompletionTests(unittest.TestCase):
    def setup(self, root, company='sec-0000090011'):
        helper = fixtures.ExtractionBatchTests()
        dataset, job = helper.source(root/'source', company=company)
        helper.method(root)
        job['entity_catalog'] = [{'company_id': company, 'entity_id': company, 'label': 'Issuer'}]
        job['normalization_config'] = {'version': 'synthetic-v1', 'metric_catalog': {
            'revenue': {'label': 'Revenue', 'unit': 'USD'}, 'assets': {'label': 'Assets', 'unit': 'USD'}}}
        job['required_facts'] = [{'requirement_id': metric, 'entity_id': company,
            'metric_id': metric, 'period_id': 'selected-year', 'unit': 'USD',
            'accounting_basis': 'reported_consolidated', 'value_kind': 'actual'} for metric in ('revenue', 'assets')]
        return dataset, job

    def row(self, packet):
        table = next(b for b in packet['blocks'] if b['type'] == 'table')
        metric, amount = ('revenue', '13') if 'Revenue' in table['text'] else ('assets', '29')
        return {'draft_id': 'same-draft-id-across-batches', 'kind': 'financial', 'entity': 'Issuer',
            'entity_id': packet['company_id'], 'metric': metric.title(), 'metric_id': metric,
            'period': '2033', 'period_id': 'selected-year', 'value': amount,
            'value_relation': 'eq', 'unit': 'USD', 'accounting_basis': 'reported_consolidated',
            'summary': 'Synthetic amount', 'evidence': [{'block_id': table['block_id'], 'quote': table['text']}]}

    def test_two_batches_complete_without_overwriting_or_losing_provenance(self):
        for company in ('sec-0000090011', 'sec-0000090044'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); dataset, job = self.setup(root, company)
                calls = []
                async def fixture(mode, value, schema):
                    calls.append(mode)
                    if mode == 'select_batch':
                        return {'batch_index': value['batches'][0]['batch_index'], 'requirement_ids': [value['required_facts'][0]['requirement_id']], 'reason': 'Synthetic choice'}
                    return {'records': [self.row(value)], 'gaps': []}
                result = asyncio.run(complete_required_facts(dataset=dataset, job=job, output=root/'run',
                    task_profile=root/'task.json', method_root=root, credentials_root=root,
                    model='claude-sonnet-5-5', budget_usd=3, max_batches=2,
                    observation_root=root/'observations', model_call=fixture))
                self.assertEqual(result['present_fact_count'], 2)
                self.assertEqual(result['fact_coverage'], 'candidate_coverage_complete')
                self.assertEqual(result['plan_origin'], 'scripted_fixture')
                self.assertEqual(calls, ['select_batch', 'extract_batch', 'extract_batch'])
                initial = json.loads((root/'run/initial-coverage.json').read_text())
                self.assertTrue(all(i['status'] == 'not_extracted' for i in initial['requirements']))
                normalized = json.loads((root/'run/normalized.json').read_text())
                self.assertEqual(len({r['record_id'] for r in normalized['records']}), 2)
                self.assertTrue(all(r['entity_id'] == company for r in normalized['records']))
                verify_completion_publication(root/'run',root/'observations',['result.json','normalized.json'])
                (root/'run/normalized.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'original_publication'):
                    verify_completion_publication(root/'run',root/'observations',['normalized.json'])

    def test_only_one_concurrent_successor_can_claim_failed_task(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            def claim(number):
                try:
                    claim_completion_successor(root/'failed',root/f'next-{number}',{'source':'sha'})
                    return True
                except ValueError: return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(claim,[1,2]))
            self.assertEqual(sum(results),1)

    def test_merge_rejects_cross_source_changed_catalog_and_undelivered_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); dataset, job = self.setup(root)
            packet = build_extraction_packet(dataset, job)
            delivered = deepcopy(packet)
            delivered['blocks'] = [next(b for b in packet['blocks'] if b['type'] == 'table')]
            row = self.row(delivered)
            for mutate in ('source', 'catalog', 'block', 'citation'):
                one, draft = deepcopy(delivered), deepcopy(row)
                if mutate == 'source': one['source']['source_sha256'] = 'a'*64
                elif mutate == 'catalog': one['metric_catalog']['revenue']['unit'] = 'TWD'
                elif mutate == 'block': one['blocks'][0]['text'] += 'mutated'
                else: draft['evidence'][0]['block_id'] = next(b['block_id'] for b in packet['blocks'] if b not in delivered['blocks'])
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    merge_delivered_extractions(packet, [(one, {'records': [draft]})])

    def test_scope_failure_occurs_before_model_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); dataset,job=self.setup(root)
            job['required_facts'][0]['entity_id']='wrong'
            async def forbidden(*args): raise AssertionError('must not dispatch')
            with self.assertRaises(ValueError):
                asyncio.run(complete_required_facts(dataset=dataset, job=job, output=root/'run',
                    task_profile=root/'task.json', method_root=root, credentials_root=root,
                    model='claude-sonnet-5-5', budget_usd=3, max_batches=2,
                    observation_root=root/'observations', model_call=forbidden))

    def test_protocol_repair_is_bounded_and_rechecks_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); dataset,job=self.setup(root)
            job['required_facts'] = job['required_facts'][:1]
            calls=[]
            async def fixture(mode, value, schema):
                calls.append(mode)
                if mode == 'select_batch':
                    return {'batch_index': value['batches'][0]['batch_index'], 'requirement_ids': [value['required_facts'][0]['requirement_id']], 'reason': 'Synthetic choice'}
                if mode == 'extract_batch':
                    row=self.row(value);row['question_refs']=['revenue']
                    return {'records':[row]}
                self.assertEqual(mode, 'repair_batch')
                self.assertEqual(value['previous_extraction']['records'][0]['question_refs'], ['revenue'])
                self.assertTrue(value['host_validation_feedback'])
                return {'records':[self.row(value['source_packet'])]}
            result=asyncio.run(complete_required_facts(dataset=dataset,job=job,output=root/'run',
                task_profile=root/'task.json',method_root=root,credentials_root=root,
                model='claude-sonnet-5-5',budget_usd=3,max_batches=1,
                    observation_root=root/'observations',model_call=fixture))
            self.assertEqual(calls,['select_batch','extract_batch','repair_batch'])
            self.assertEqual(result['present_fact_count'],1)
            self.assertEqual(result['budget']['requests'],0)

    def test_context_binding_only_narrows_frozen_metric_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();dataset,job=self.setup(root)
            packet=build_extraction_packet(dataset,job)
            assets=next(b for b in packet['blocks'] if b['type']=='table' and 'Assets' in b['text'])
            packet['source_bound_normalization']={'adapter_id':'explicit-synthetic-context-v1',
                **{k:packet['source'][k] for k in ('company_id','source_snapshot_id','source_sha256')},
                'dataset_manifest_sha256':packet['dataset_manifest_sha256'],
                'block_hashes':{b['block_id']:b['text_hash'] for b in packet['blocks']},
                'metric_contexts':{'assets':[{'block_id':assets['block_id'],'quote':'Assets'}]}}
            catalog=table_batch_catalog(packet,neighbor_radius=2)
            first=prepare_completion_batch(packet,catalog['batches'][0],[packet['required_facts'][0]])
            self.assertEqual(set(first['metric_catalog']),{'revenue'})
            self.assertNotIn('source_bound_normalization',first)
            self.assertEqual(first['parent_source_mapping_sha256'],digest(packet['source_bound_normalization']))
            wrong=self.row(first);wrong['metric_id']='assets'
            with self.assertRaisesRegex(ValueError,'metric_outside_delivered'):
                merge_delivered_extractions(packet,[(first,{'records':[wrong]})])
            second=prepare_completion_batch(packet,catalog['batches'][1],[packet['required_facts'][1]])
            self.assertEqual(second['source_bound_normalization']['metric_contexts'],packet['source_bound_normalization']['metric_contexts'])
            self.assertEqual(second['source_bound_normalization']['block_hashes'],{b['block_id']:b['text_hash'] for b in second['blocks']})

    def test_selection_only_partial_resumes_once_with_original_budget_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();dataset,job=self.setup(root)
            common=dict(dataset=dataset,job=job,task_profile=root/'task.json',method_root=root,
                credentials_root=root,model='claude-sonnet-5-5',budget_usd=3,max_batches=2,
                observation_root=root/'observations')
            async def first(mode,value,schema):
                self.assertEqual(mode,'select_batch')
                return {'batch_index':None,'requirement_ids':[],'reason':'Synthetic incomplete interpretation'}
            result=asyncio.run(complete_required_facts(**common,output=root/'first',model_call=first))
            self.assertEqual(result['present_fact_count'],0)
            calls=[]
            async def recovered(mode,value,schema):
                calls.append(mode)
                if mode=='select_batch':
                    self.assertIn('previous_selection',value)
                    return {'batch_index':value['batches'][0]['batch_index'],
                        'requirement_ids':[value['required_facts'][0]['requirement_id']],'reason':'One subset now'}
                return {'records':[self.row(value)]}
            result=asyncio.run(complete_required_facts(**common,output=root/'second',
                model_call=recovered,resume_failed_run=root/'first'))
            self.assertEqual(result['present_fact_count'],2)
            self.assertEqual(calls,['select_batch','extract_batch','extract_batch'])
            self.assertFalse((root/'second/budget.sqlite').exists())
            self.assertEqual(json.loads((root/'second/resume.json').read_text())['budget_ledger'],str(root/'first/budget.sqlite'))
            with self.assertRaisesRegex(ValueError,'already_has_successor'):
                asyncio.run(complete_required_facts(**common,output=root/'third',
                    model_call=recovered,resume_failed_run=root/'first'))


if __name__ == '__main__': unittest.main()
