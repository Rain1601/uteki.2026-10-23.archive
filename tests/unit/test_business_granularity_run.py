"""Offline stage integration: real adapters/observation/budget with mock HTTP only."""
import asyncio
from copy import deepcopy
from contextlib import closing
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

import httpx2 as httpx
from tests.unit.test_business_coverage_contract_v2 import attribute_sample
from uteki.agents.business_map import granularity_run as run, product_run as base
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


class GranularityRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.packet, self.draft, self.inventory, self.audit = attribute_sample(self.root)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'skill.md').write_text('Use frozen source and cited attributes. No reference answers.')
        env = patch.dict(os.environ, {'AIHUBMIX_API_KEY':'mock-key'}); env.start(); self.addCleanup(env.stop)
        self.requests, self.responses, self.clients = [], [], []
        self.budget = RunBudget(self.root/'shared.sqlite', '2', allow_unknown_reservations=True)
        token = self.budget.reserve('.38341'); self.budget.settle(token, None)
        token = self.budget.reserve('.3'); self.budget.settle(token, '.2')
        self.prior = self.rows()

    def rows(self):
        with closing(sqlite3.connect(self.root/'shared.sqlite')) as c:
            return {r[0]:r[1:] for r in c.execute('select id,reserved,actual,state from reservations')}

    def client(self, **kwargs):
        c = httpx.AsyncClient(**dict(kwargs, transport=httpx.MockTransport(self.respond)))
        self.clients.append(c); return c

    def respond(self, request):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, BaseException): raise value
        if isinstance(value, httpx.Response): return value
        return httpx.Response(200, json=dict(id='mock-granularity',model='claude-sonnet-5-5',stop_reason='end_turn',
            usage=dict(input_tokens=180,output_tokens=120),content=[dict(type='text',text=value if isinstance(value,str) else json.dumps(value))]))

    def prepared(self):
        p = base.prepare(root=self.root,packet_path='packet.json',skill_path='skill.md',
            company_id=self.packet['company_id'],document_id=self.packet['document_id'],period_end=self.packet['period_end'],
            model='claude-sonnet-5-5',effort='high',max_tokens=3000,timeout_seconds=30,contract_version='business-draft-v2')
        p['native']._client_factory = self.client
        return p

    async def stage(self, name, mode, prepared=None, **inputs):
        return await run.execute_stage(prepared or self.prepared(),root=self.root,output=self.root/name,
            observation_root=self.root/'observations',budget_path='shared.sqlite',budget_limit_usd='2',mode=mode,
            dependencies={'packet.json':base.digest((self.root/'packet.json').read_bytes())},**inputs)

    def assert_prior_kept(self):
        self.assertEqual({k:self.rows()[k] for k in self.prior}, self.prior)
        self.assertEqual(self.budget.summary()['unknown_requests'],1)
        self.assertEqual(self.budget.summary()['held_usd'],'0.38341')
        self.assertFalse(any(self.root.glob('*/budget.sqlite')))

    def events(self):
        return [json.loads(p.read_text()) for p in (self.root/'observations').glob('*/events/*.json')]

    async def test_generation_inventory_audit_share_ledger_and_exact_request_bytes(self):
        self.responses = [self.draft,self.inventory,self.audit]
        p=self.prepared()
        preview=run.preflight(p,p['kwargs'],self.budget)
        self.assertEqual(preview['remaining_usd'],'1.41659')
        self.assertEqual(self.rows(),self.prior)
        gen=await self.stage('gen','generation',prepared=p)
        inv=await self.stage('inventory','inventory')
        audited=await self.stage('audit','audit',inventory=self.inventory,candidate=self.draft)
        self.assertEqual((gen['status'],inv['status'],audited['self_check_status']),('candidate','completed','pass'))
        self.assertEqual(json.loads((self.root/'gen/projection.json').read_text())['changes'],[])
        self.assert_prior_kept(); self.assertEqual(len(self.rows()),5)
        for name, request in zip(('gen','inventory','audit'),self.requests):
            stage=self.root/name
            manifest=json.loads((stage/'manifest.json').read_text())
            body=json.loads(request.content)
            self.assertEqual(manifest['request_sha256'],base.digest(request.content))
            self.assertEqual(manifest['source_wire_sha256'],base.digest(body['messages'][0]['content'].encode()))
            self.assertEqual(manifest['trace_id'],json.loads((stage/'result.json').read_text())['trace_id'])
            start=json.loads(next((stage/'model-calls').glob('*-start.json')).read_text())
            estimate=(Decimal(len(request.content)+16000)*2+Decimal(3000)*10)/Decimal(1000000)
            self.assertEqual(Decimal(start['reserved_usd']),estimate)
        self.assertTrue(all(c.is_closed for c in self.clients))
        self.assertTrue(p['native']._closed)
        events=self.events()
        self.assertTrue(any(e.get('type')=='artifact.published' and e['data']['ref']['path']=='result.json' for e in events))
        self.assertEqual(json.loads(self.requests[0].content)['messages'][0]['content'],p['kwargs']['input'])
        inventory_payload=json.loads(json.loads(self.requests[1].content)['messages'][0]['content'])
        self.assertEqual(set(inventory_payload),{'frozen_source_packet','source_packet_sha256'})

    async def test_invalid_json_preserves_raw_and_cost_without_retry_or_revision(self):
        self.responses=['{incomplete']
        p=self.prepared()
        with self.assertRaises(ValueError):await self.stage('invalid','generation',prepared=p)
        self.assertEqual(len(self.requests),1)
        self.assertEqual((self.root/'invalid/response.txt').read_text(),'{incomplete')
        receipt=json.loads((self.root/'invalid/result.json').read_text())
        self.assertEqual(receipt['status'],'failed')
        self.assertEqual(len(list((self.root/'invalid/transport-attempts').iterdir())),1)
        self.assertTrue(p['native']._closed); self.assert_prior_kept()

    async def test_budget_failure_never_dispatches_or_retries(self):
        token=self.budget.reserve('1.40');self.budget.settle(token,'1.40')
        p=self.prepared()
        with self.assertRaises(BudgetExceeded):await self.stage('no-funds','generation',prepared=p)
        self.assertFalse(self.requests)
        self.assertTrue(p['native']._closed)
        self.assertEqual(len(self.rows()),3)
        self.assertEqual(json.loads((self.root/'no-funds/result.json').read_text())['stop_reason'],'BudgetExceeded')

    async def test_preflight_invalid_inputs_close_native_and_do_not_create_new_ledger(self):
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'source_only'):
            await self.stage('bad-input','generation',prepared=p,candidate=self.draft)
        self.assertTrue(p['native']._closed);self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)
        p=self.prepared()
        with self.assertRaises((ValueError,FileNotFoundError)):
            await run.execute_stage(p,root=self.root,output=self.root/'missing-ledger',observation_root=self.root/'observations',
                budget_path='absent.sqlite',budget_limit_usd='2',mode='generation',dependencies={})
        self.assertFalse((self.root/'absent.sqlite').exists());self.assertTrue(p['native']._closed)

    async def test_revision_accepts_own_published_audit_and_final_audit_is_fresh(self):
        failed=deepcopy(self.audit);failed['checks'][0]['verdict']='partial'
        published=run.audit_contract.validate_audit(failed,self.packet,self.inventory,self.draft)
        self.responses=[self.draft,self.audit]
        await self.stage('revision','revision',inventory=self.inventory,candidate=self.draft,audit=published)
        await self.stage('final','audit_final',inventory=self.inventory,candidate=self.draft)
        payloads=[json.loads(json.loads(r.content)['messages'][0]['content']) for r in self.requests]
        self.assertEqual(payloads[0]['own_audit'],published)
        self.assertNotIn('own_audit',payloads[1])
        self.assertEqual(payloads[1]['candidate_sha256'],run.inventory_contract.canonical_hash(self.draft))
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'old_verdicts'):
            await self.stage('polluted-final','audit_final',prepared=p,inventory=self.inventory,candidate=self.draft,audit=published)
        self.assertEqual(len(self.requests),2);self.assertTrue(p['native']._closed)

    async def test_one_transient_retry_keeps_separate_attempts_and_same_request(self):
        self.responses=[httpx.ConnectError('offline'),self.draft]
        with patch('uteki.agents.runtime.bounded_retry.asyncio.sleep',new=AsyncMock()):
            await self.stage('retry','generation')
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[0].content,self.requests[1].content)
        self.assertEqual(len(list((self.root/'retry/transport-attempts').iterdir())),2)
        self.assert_prior_kept();self.assertEqual(len(self.rows()),4)

    async def test_cancellation_preserves_receipt_closes_and_does_not_retry(self):
        self.responses=[asyncio.CancelledError()]
        p=self.prepared()
        with self.assertRaises(asyncio.CancelledError):await self.stage('cancel','generation',prepared=p)
        self.assertEqual(len(self.requests),1);self.assertTrue(p['native']._closed)
        self.assertEqual(json.loads((self.root/'cancel/result.json').read_text())['stop_reason'],'CancelledError')

    async def test_audit_failure_preserves_candidate_and_publishes_failed_receipt(self):
        self.responses=[self.draft,'{"invalid":true}']
        await self.stage('candidate','generation')
        frozen={p.name:base.digest(p.read_bytes()) for p in (self.root/'candidate').iterdir() if p.is_file()}
        p=self.prepared()
        with self.assertRaises(ValueError):
            await self.stage('bad-audit','audit',prepared=p,inventory=self.inventory,candidate=self.draft)
        self.assertEqual(frozen,{f.name:base.digest(f.read_bytes()) for f in (self.root/'candidate').iterdir() if f.is_file()})
        self.assertEqual(len(self.requests),2)
        self.assertTrue((self.root/'bad-audit/response.txt').is_file())
        self.assertFalse((self.root/'bad-audit/audit.json').exists())
        receipt=json.loads((self.root/'bad-audit/result.json').read_text())
        self.assertEqual(receipt['status'],'failed');self.assertTrue(p['native']._closed)
        self.assertTrue(any(e.get('type')=='artifact.published' and e['data']['ref']['path']=='result.json'
                            and e['data']['ref']['sha256']==base.digest((self.root/'bad-audit/result.json').read_bytes())
                            for e in self.events()))

    async def test_dependency_tamper_blocks_dispatch_and_preserves_ledger(self):
        p=self.prepared()
        (self.root/'dependency.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'dependency_changed'):
            await run.execute_stage(p,root=self.root,output=self.root/'tampered',observation_root=self.root/'observations',
                budget_path='shared.sqlite',budget_limit_usd='2',mode='generation',
                dependencies={'dependency.json':base.digest(b'original')})
        self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)
        self.assertTrue(p['native']._closed)

    async def test_generation_and_revision_project_indexes_without_mutating_raw(self):
        raw=deepcopy(self.draft);raw['businesses'][1]['evidence_block_ids']=['section']
        failed=deepcopy(self.audit);failed['checks'][0]['verdict']='partial'
        published=run.audit_contract.validate_audit(failed,self.packet,self.inventory,self.draft)
        self.responses=[raw,raw]
        for name,mode,inputs in [('projected-generation','generation',{}),
                ('projected-revision','revision',dict(inventory=self.inventory,candidate=self.draft,audit=published))]:
            with self.subTest(mode=mode):
                await self.stage(name,mode,**inputs)
                folder=self.root/name
                self.assertEqual(json.loads((folder/'response.txt').read_text()),raw)
                result=json.loads((folder/'draft.json').read_text())
                self.assertEqual(result,self.draft)
                projection=json.loads((folder/'projection.json').read_text())
                self.assertEqual(projection['changes'][0]['path'],'/businesses/1/evidence_block_ids')
                self.assertEqual(projection['original_sha256'],run.inventory_contract.canonical_hash(raw))
        self.assertEqual(len(self.requests),2)

    def protocol_fixture(self):
        failed=deepcopy(self.draft)
        node=failed['businesses'][1]
        quote=next(b['text'] for b in self.packet['blocks'] if b['id']=='product')
        node['monetization']=[dict(description=quote,basis='explicit',evidence_block_ids=['section','product'])]
        node['claim_evidence'].append(dict(field='monetization',item_index=0,
            excerpts=[dict(block_id='product',quote=quote)]))
        corrected=deepcopy(failed);corrected['businesses'][1]['monetization'][0]['evidence_block_ids']=['product']
        return failed,corrected

    async def test_protocol_repair_sends_only_own_failure_machine_error_and_source(self):
        failed,corrected=self.protocol_fixture()
        original=deepcopy(failed)
        self.responses=[corrected]
        p=self.prepared()
        result=await self.stage('protocol-repair','protocol_repair',prepared=p,own_failed_response=failed,
                                protocol_error='monetization_claim_evidence_mismatch')
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['execution_mode'],'business_products_protocol_repair')
        self.assertEqual(result['source_wire_mode'],'source_and_own_failed_response')
        self.assertEqual(len(self.requests),1);self.assertEqual(failed,original)
        payload=json.loads(json.loads(self.requests[0].content)['messages'][0]['content'])
        self.assertEqual(set(payload),{'frozen_source_packet','own_failed_response','protocol_error','failed_response_sha256'})
        self.assertEqual(payload['own_failed_response'],failed)
        self.assertEqual(payload['frozen_source_packet'],self.packet)
        self.assertEqual(payload['failed_response_sha256'],run.inventory_contract.canonical_hash(failed))
        folder=self.root/'protocol-repair'
        self.assertEqual(json.loads((folder/'draft.json').read_text()),corrected)
        self.assertEqual(json.loads((folder/'own_failed_response.json').read_text()),failed)
        self.assertEqual(json.loads((folder/'projection.json').read_text())['changes'],[])
        self.assertTrue(p['native']._closed);self.assert_prior_kept()

    async def test_protocol_repair_rejects_valid_wrong_error_scope_or_other_inputs(self):
        failed,_=self.protocol_fixture()
        bad_scope=deepcopy(failed);bad_scope['company_id']='different-company'
        invalid_shape=deepcopy(failed);invalid_shape['injected_feedback']='Use expected answer'
        examples=[dict(own_failed_response=self.draft,protocol_error='monetization_claim_evidence_mismatch'),
                  dict(own_failed_response=failed,protocol_error='Please delete eight indexes'),
                  dict(own_failed_response=bad_scope,protocol_error='monetization_claim_evidence_mismatch'),
                  dict(own_failed_response=invalid_shape,protocol_error='monetization_claim_evidence_mismatch'),
                  dict(own_failed_response=failed,protocol_error='monetization_claim_evidence_mismatch',candidate=self.draft),
                  dict(own_failed_response=failed,protocol_error='monetization_claim_evidence_mismatch',inventory=self.inventory),
                  dict(own_failed_response=failed,protocol_error='monetization_claim_evidence_mismatch',audit=self.audit)]
        for i,inputs in enumerate(examples):
            p=self.prepared()
            with self.subTest(i=i),self.assertRaises(ValueError):
                await self.stage('rejected-'+str(i),'protocol_repair',prepared=p,**inputs)
            self.assertTrue(p['native']._closed)
        self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'only_allowed'):
            await self.stage('contaminated-generation','generation',prepared=p,own_failed_response=failed,
                             protocol_error='monetization_claim_evidence_mismatch')
        self.assertFalse(self.requests)

    async def test_failed_protocol_repair_stops_after_one_complete_model_answer(self):
        failed,_=self.protocol_fixture();self.responses=[failed]
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'monetization_claim_evidence_mismatch'):
            await self.stage('repair-failed','protocol_repair',prepared=p,own_failed_response=failed,
                             protocol_error='monetization_claim_evidence_mismatch')
        self.assertEqual(len(self.requests),1)
        folder=self.root/'repair-failed'
        self.assertEqual(json.loads((folder/'response.txt').read_text()),failed)
        self.assertEqual(json.loads((folder/'own_failed_response.json').read_text()),failed)
        self.assertEqual(json.loads((folder/'result.json').read_text())['status'],'failed')
        self.assertFalse((folder/'draft.json').exists());self.assertTrue(p['native']._closed)
        self.assert_prior_kept()

    def failed_alignment(self):
        failed=deepcopy(self.audit)
        mapping=next(m for m in failed['mappings'] if m['mention_id']=='m3')
        mapping['attribute_refs'][0]['excerpts']=[e for e in mapping['attribute_refs'][0]['excerpts'] if e['block_id']=='competition']
        return failed

    async def test_revision_from_failed_audit_retains_raw_and_requires_fresh_audit(self):
        failed=self.failed_alignment();original=deepcopy(failed)
        self.responses=[self.draft]
        p=self.prepared()
        result=await self.stage('failed-audit-revision','revision_from_failed_audit',prepared=p,
            inventory=self.inventory,candidate=self.draft,own_failed_audit=failed,
            audit_protocol_error='attribute_excerpt_does_not_locate_mention')
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['self_check_status'],'pending_final_audit')
        self.assertTrue(result['requires_fresh_audit'])
        self.assertEqual(result['failed_audit_validation'],'failed_not_accepted')
        self.assertEqual(result['semantic_revision_invocations_max'],1)
        payload=json.loads(json.loads(self.requests[0].content)['messages'][0]['content'])
        self.assertEqual(set(payload),{'frozen_source_packet','source_inventory','own_candidate','candidate_sha256',
            'inventory_sha256','own_failed_audit','audit_protocol_error'})
        self.assertEqual(payload['own_failed_audit'],original)
        self.assertEqual(failed,original)
        folder=self.root/'failed-audit-revision'
        self.assertEqual(json.loads((folder/'own_failed_audit.json').read_text()),original)
        self.assertEqual(json.loads((folder/'draft.json').read_text()),self.draft)
        self.assertEqual(json.loads((folder/'response.txt').read_text()),self.draft)
        self.assertFalse((folder/'audit.json').exists())
        self.assertTrue(p['native']._closed);self.assert_prior_kept()

    async def test_failed_audit_revision_rejects_binding_coverage_and_feedback_changes(self):
        failed=self.failed_alignment()
        mutations=[lambda a:a.update(candidate_sha256='0'*64),lambda a:a.update(inventory_sha256='0'*64),
                   lambda a:a['mappings'].pop(),lambda a:a['mappings'].append(deepcopy(a['mappings'][0])),
                   lambda a:a['checks'].pop(),lambda a:a['checks'].append(deepcopy(a['checks'][0])),
                   lambda a:a.update(human_feedback='Use this answer')]
        examples=[]
        for mutate in mutations:
            changed=deepcopy(failed);mutate(changed);examples.append((changed,'attribute_excerpt_does_not_locate_mention'))
        examples.extend([(failed,'Please use my interpretation'),(self.audit,'attribute_excerpt_does_not_locate_mention')])
        for i,(value,error) in enumerate(examples):
            p=self.prepared()
            with self.subTest(i=i),self.assertRaises(ValueError):
                await self.stage('invalid-failed-audit-'+str(i),'revision_from_failed_audit',prepared=p,
                    inventory=self.inventory,candidate=self.draft,own_failed_audit=value,audit_protocol_error=error)
            self.assertTrue(p['native']._closed)
        self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)

    async def test_failed_audit_cannot_leak_into_generation_or_fresh_audit(self):
        for i,mode in enumerate(('generation','inventory','audit_final','protocol_repair','revision')):
            p=self.prepared()
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'failed_audit_inputs_only_allowed'):
                await self.stage('not-allowed-'+str(i),mode,prepared=p,own_failed_audit=self.failed_alignment(),
                                 audit_protocol_error='attribute_excerpt_does_not_locate_mention')
            self.assertTrue(p['native']._closed)
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'does_not_receive_accepted_audit'):
            await self.stage('duplicate-audit-input','revision_from_failed_audit',prepared=p,
                inventory=self.inventory,candidate=self.draft,audit=self.audit,own_failed_audit=self.failed_alignment(),
                audit_protocol_error='attribute_excerpt_does_not_locate_mention')
        self.assertFalse(self.requests)
