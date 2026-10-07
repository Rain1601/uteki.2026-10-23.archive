"""Offline independent critic boundaries; no semantic quality claims or live calls."""
import asyncio
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx2 as httpx
from tests.unit.test_business_coverage_contract_v2 import attribute_sample
from uteki.agents.business_map import semantic_critic as run, product_run as base
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded


class SemanticCriticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.packet,self.draft,_,_=attribute_sample(self.root)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'skill.md').write_text('Use frozen source and cited attributes.')
        env=patch.dict(os.environ,{'AIHUBMIX_API_KEY':'mock-key'});env.start();self.addCleanup(env.stop)
        self.requests,self.responses,self.clients=[],[],[]
        self.budget=RunBudget(self.root/'shared.sqlite','8',allow_unknown_reservations=True)
        token=self.budget.reserve('.38341');self.budget.settle(token,None)
        token=self.budget.reserve('.3');self.budget.settle(token,'.2')
        self.prior=self.rows()
        p=self.prepared()
        origin=self.root/'producer';origin.mkdir()
        base.write_json(origin/'draft.json',self.draft)
        base.write_json(origin/'manifest.json',dict(p['manifest'],model='claude-sonnet-5-5',trace_id='run-original'))
        base.write_json(origin/'response_metadata.json',dict(actual_upstream_model='claude-sonnet-5-5'))
        self.review=dict(schema_version='business-semantic-critic-v1',candidate_sha256=run.canonical_hash(self.draft),
            reviewed_check_keys=[t['check_key'] for t in run.check_targets(self.draft)],status='pass',issues=[])

    def rows(self):
        with closing(sqlite3.connect(self.root/'shared.sqlite')) as db:
            return {r[0]:r[1:] for r in db.execute('select id,reserved,actual,state from reservations')}

    def prepared(self,model='claude-opus-5-5',max_tokens=8000):
        p=base.prepare(root=self.root,packet_path='packet.json',skill_path='skill.md',
            company_id=self.packet['company_id'],document_id=self.packet['document_id'],period_end=self.packet['period_end'],
            model=model,effort='high',max_tokens=max_tokens,timeout_seconds=30,stream=max_tokens>16000,contract_version='business-draft-v2')
        p['native']._client_factory=self.client
        return p

    def client(self,**kwargs):
        c=httpx.AsyncClient(**dict(kwargs,transport=httpx.MockTransport(self.respond)));self.clients.append(c);return c

    def respond(self,request):
        self.requests.append(request);value=self.responses.pop(0)
        if callable(value):value=value()
        if isinstance(value,BaseException):raise value
        return httpx.Response(200,json=dict(id='mock-critic',model='claude-opus-5-5',stop_reason='end_turn',
            usage=dict(input_tokens=180,output_tokens=120),
            content=[dict(type='text',text=value if isinstance(value,str) else json.dumps(value))]))

    async def stage(self,name='critic',prepared=None,**overrides):
        args=dict(root=self.root,output=self.root/name,observation_root=self.root/'observations',budget_path='shared.sqlite',
            budget_limit_usd='8',candidate_path='producer/draft.json',
            dependencies={'packet.json':base.digest((self.root/'packet.json').read_bytes())})
        args.update(overrides)
        return await run.execute_stage(prepared or self.prepared(),**args)

    def issue(self):
        return dict(category='claim_support',target_keys=[self.review['reviewed_check_keys'][0]],
            node_ids=[self.draft['businesses'][0]['id']],excerpts=[dict(block_id=self.packet['blocks'][0]['id'],
            quote=self.packet['blocks'][0]['text'])],explanation='Synthetic uncertainty; exact quotation does not prove semantics.')

    def test_pointer_targets_and_whole_fence_preserve_review_content(self):
        p=self.prepared()
        full,_=run.request_for(p,self.draft)
        compact,_=run.request_for(p,self.draft,target_format='pointers-v1')
        a,b=json.loads(full['input']),json.loads(compact['input'])
        self.assertEqual(a['candidate'],b['candidate'])
        self.assertEqual(a['frozen_source_packet'],b['frozen_source_packet'])
        self.assertEqual([x['check_key'] for x in a['check_targets']],[x['check_key'] for x in b['check_targets']])
        for item in b['check_targets']:
            value=b['candidate']
            for key in item['candidate_pointer'].strip('/').split('/'):
                value=value[int(key)] if isinstance(value,list) else value[key]
            self.assertIn('excerpts',value)
        raw='```json\n'+json.dumps(self.review)+'\n```'
        value,receipt=run.parse_review_response(raw)
        self.assertEqual(value,self.review); self.assertFalse(receipt['semantic_changes'])
        for bad in ('before'+raw,raw+'after',raw[:-3],'```json\n{"a":1,"a":2}\n```'):
            with self.assertRaises(ValueError):run.parse_review_response(bad)

    def test_contract_binding_coverage_issues_and_exact_evidence(self):
        cases=[lambda r:r.update(candidate_sha256='0'*64),lambda r:r['reviewed_check_keys'].pop(),
            lambda r:r['reviewed_check_keys'].append(r['reviewed_check_keys'][0]),lambda r:r.update(status='uncertain'),
            lambda r:r.update(issues=[self.issue()])]
        for mutate in cases:
            r=deepcopy(self.review);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):run.validate_review(r,self.packet,self.draft)
        good=deepcopy(self.review);good.update(status='uncertain',issues=[self.issue()])
        self.assertEqual(run.validate_review(good,self.packet,self.draft),good)
        for mutate in [lambda i:i.update(target_keys=[]),lambda i:i.update(target_keys=['foreign']),
            lambda i:i.update(node_ids=['foreign']),lambda i:i['excerpts'][0].update(block_id='foreign'),
            lambda i:i['excerpts'][0].update(quote='fabricated quote'),lambda i:i.update(node_ids=['issuer','issuer'])]:
            r=deepcopy(good);mutate(r['issues'][0])
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):run.validate_review(r,self.packet,self.draft)
        omission=deepcopy(good);omission['issues'][0].update(category='omission',target_keys=[])
        self.assertEqual(run.validate_review(omission,self.packet,self.draft),omission)
        foreign=deepcopy(self.draft);foreign['company_id']='foreign'
        with self.assertRaises(ValueError):run.validate_review(self.review,self.packet,foreign)

    async def test_source_only_payload_shared_ledger_and_published_receipt(self):
        self.responses=[self.review];p=self.prepared()
        kwargs,_=run.request_for(p,self.draft)
        preview=run.preflight(p,kwargs,self.budget)
        self.assertEqual(self.rows(),self.prior)
        result=await self.stage(prepared=p)
        self.assertEqual(result['status'],'completed');self.assertFalse(result['independent_acceptance'])
        self.assertEqual(result['semantic_acceptance'],'not_evaluated')
        body=json.loads(self.requests[0].content);payload=json.loads(body['messages'][0]['content'])
        self.assertEqual(set(payload),{'frozen_source_packet','candidate','check_targets'})
        self.assertEqual(payload['candidate'],self.draft)
        self.assertNotIn('run-original',body['system'])
        manifest=json.loads((self.root/'critic/manifest.json').read_text())
        self.assertEqual(manifest['model'],'claude-opus-5-5')
        self.assertEqual(manifest['candidate_origin']['actual_upstream_model'],'claude-sonnet-5-5')
        self.assertEqual(manifest['request_sha256'],base.digest(self.requests[0].content))
        start=json.loads(next((self.root/'critic/model-calls').glob('*-start.json')).read_text())
        self.assertEqual(Decimal(start['reserved_usd']),Decimal(preview['reserved_estimated_usd']))
        self.assertEqual({k:self.rows()[k] for k in self.prior},self.prior)
        self.assertEqual(self.budget.summary()['held_usd'],'0.38341')
        self.assertTrue(p['native']._closed);self.assertTrue(all(c.is_closed for c in self.clients))
        published=[json.loads(p.read_text()) for p in (self.root/'observations').glob('*/events/*.json')]
        names={e['data']['ref']['path'] for e in published if e.get('type')=='artifact.published'}
        self.assertTrue({'result.json','review.json','response.txt','response_metadata.json','candidate.json'} <= names)

    async def test_failed_protocol_preserves_raw_cost_and_original_without_retry(self):
        before={p.name:base.digest(p.read_bytes()) for p in (self.root/'producer').iterdir()}
        self.responses=['{bad'];p=self.prepared()
        with self.assertRaises(ValueError):await self.stage(prepared=p)
        self.assertEqual(len(self.requests),1);self.assertEqual((self.root/'critic/response.txt').read_text(),'{bad')
        self.assertEqual(json.loads((self.root/'critic/result.json').read_text())['status'],'failed')
        self.assertFalse((self.root/'critic/review.json').exists());self.assertTrue(p['native']._closed)
        self.assertEqual(before,{p.name:base.digest(p.read_bytes()) for p in (self.root/'producer').iterdir()})
        self.assertEqual(len(self.rows()),3)

    async def test_dependencies_checked_after_request_and_between_retries(self):
        def alter():
            (self.root/'producer/response_metadata.json').write_text('{}')
            return httpx.ConnectError('offline')
        self.responses=[alter,self.review]
        with patch('uteki.agents.runtime.bounded_retry.asyncio.sleep',new=AsyncMock()),self.assertRaisesRegex(ValueError,'frozen_dependency_changed'):
            await self.stage()
        self.assertEqual(len(self.requests),1)
        # A changed dependency after a successful HTTP response also blocks materialization.
        base.write_json(self.root/'producer/response_metadata.json',dict(actual_upstream_model='claude-sonnet-5-5'))
        def after():
            (self.root/'packet.json').write_text('{}');return self.review
        self.responses=[after]
        with self.assertRaisesRegex(ValueError,'frozen_dependency_changed'):await self.stage('post')
        self.assertFalse((self.root/'post/review.json').exists())

    async def test_one_network_retry_and_cancellation_are_bounded(self):
        self.responses=[httpx.ConnectError('offline'),self.review]
        with patch('uteki.agents.runtime.bounded_retry.asyncio.sleep',new=AsyncMock()):await self.stage()
        self.assertEqual(len(self.requests),2);self.assertEqual(self.requests[0].content,self.requests[1].content)
        self.responses=[asyncio.CancelledError()];p=self.prepared()
        with self.assertRaises(asyncio.CancelledError):await self.stage('cancel',prepared=p)
        self.assertTrue(p['native']._closed);self.assertEqual(len(self.requests),3)
        self.assertEqual(json.loads((self.root/'cancel/result.json').read_text())['stop_reason'],'CancelledError')

    async def test_missing_empty_wrong_limit_or_escaping_ledger_never_resets(self):
        (self.root/'empty.sqlite').touch()
        for path,limit in [('missing.sqlite','8'),('empty.sqlite','8'),('shared.sqlite','9'),('../escape.sqlite','8')]:
            p=self.prepared()
            with self.subTest(path=path,limit=limit),self.assertRaises((ValueError,sqlite3.DatabaseError)):
                await self.stage(prepared=p,budget_path=path,budget_limit_usd=limit)
            self.assertTrue(p['native']._closed)
        self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)
        self.assertFalse((self.root/'missing.sqlite').exists())
        self.assertEqual((self.root/'empty.sqlite').stat().st_size,0)

    async def test_frozen_origin_and_skill_tamper_rejected_before_dispatch(self):
        original=(self.root/'producer/manifest.json').read_bytes()
        origin=json.loads(original);origin['source_packet_sha256']='0'*64
        base.write_json(self.root/'producer/manifest.json',origin)
        p=self.prepared()
        with self.assertRaisesRegex(ValueError,'producer_scope'):
            await self.stage(prepared=p)
        self.assertTrue(p['native']._closed)
        (self.root/'producer/manifest.json').write_bytes(original)
        p=self.prepared();(self.root/'skill.md').write_text('changed rules')
        with self.assertRaisesRegex(ValueError,'frozen_skill_changed'):
            await self.stage(prepared=p)
        self.assertFalse(self.requests);self.assertEqual(self.rows(),self.prior)

    async def test_low_budget_no_dispatch_and_invalid_model_or_capacity_rejected(self):
        token=self.budget.reserve('7.416');self.budget.settle(token,'7.416')
        with self.assertRaises(BudgetExceeded):await self.stage()
        self.assertFalse(self.requests)
        for model,tokens in [('claude-sonnet-5-5',8000),('claude-opus-5-5',16001)]:
            p=self.prepared(model,tokens)
            with self.assertRaises(ValueError):await self.stage('invalid',prepared=p)
            self.assertTrue(p['native']._closed)


if __name__=='__main__':unittest.main()
