"""Bounded continuation and explicit budget authorization; no live model calls."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

from uteki.agents.business_map import coverage_continuation as continuation
from uteki.agents.runtime.run_budget import RunBudget

spec=importlib.util.spec_from_file_location('recovery_fixtures',Path(__file__).with_name('test_business_coverage_recovery.py'))
fixtures=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    client=fixtures.RecoveryTests.client
    respond=fixtures.RecoveryTests.respond
    answer=fixtures.RecoveryTests.answer
    candidate=fixtures.RecoveryTests.candidate
    inventory=fixtures.RecoveryTests.inventory
    audit=fixtures.RecoveryTests.audit
    audit_response=fixtures.RecoveryTests.audit_response
    run_coverage=fixtures.RecoveryTests.run_coverage
    failed_revision=fixtures.RecoveryTests.failed_revision
    recover=fixtures.RecoveryTests.recover

    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        native=continuation.ClaudeMessagesModel
        mock=patch.object(continuation,'ClaudeMessagesModel',side_effect=lambda *args,**kwargs:
            native(*args,**dict(kwargs,client_factory=self.client)))
        mock.start();self.addCleanup(mock.stop)

    async def prepared_prior(self):
        await self.failed_revision()
        self.responses=[lambda p:self.answer(self.audit(p,needs_revision=True))]
        prior=await self.recover()
        self.requests.clear()
        authorization=dict(authorization_id='explicit-user-approval',authorized_by='user',confirmation='Continue with limit 2.',
            scope='One revision and fresh audit only.',old_limit_usd='1',new_limit_usd='2',prior_run='recovered',
            budget_path='coverage/budget.sqlite',
            prior_summary_sha256=continuation.base.digest((self.root/'recovered/summary.json').read_bytes()))
        (self.root/'authorization.json').write_text(json.dumps(authorization))
        return prior

    async def execute(self):
        return await continuation.execute(root=self.root,prior_run='recovered',output=self.root/'continued',
            observation_root=self.root/'observations',authorization_path='authorization.json',
            revision_max_tokens=3000,audit_max_tokens=3000)

    async def test_exactly_one_revision_fresh_audit_same_ledger_and_no_human_answer(self):
        prior=await self.prepared_prior()
        saved=(self.root/'recovered/summary.json').read_bytes()
        self.responses=[self.answer(self.draft),self.audit_response]
        result=await self.execute()
        self.assertEqual(len(self.requests),2)
        self.assertEqual(result['self_check_status'],'pass')
        self.assertEqual(result['budget']['requests'],prior['budget']['requests']+2)
        self.assertEqual(result['budget']['limit_usd'],'2')
        self.assertEqual(result['budget_path'],'coverage/budget.sqlite')
        self.assertFalse((self.root/'continued/budget.sqlite').exists())
        self.assertEqual((self.root/'recovered/summary.json').read_bytes(),saved)
        first=json.loads(self.requests[0]['messages'][0]['content'])
        self.assertTrue(self.requests[0]['system'].startswith(continuation.REVISION_INSTRUCTION))
        self.assertIn('including items previously marked supported',self.requests[0]['system'])
        self.assertEqual(set(first),{'frozen_source_packet','source_inventory','own_candidate','own_audit'})
        self.assertEqual(first['own_candidate'],json.loads((self.root/'recovered/revision/draft.json').read_text()))
        self.assertEqual(first['own_audit'],json.loads((self.root/'recovered/audit_final/audit.json').read_text()))
        self.assertEqual(result['input_candidate_sha256'],prior['candidate_sha256'])
        self.assertTrue((self.root/'continued/budget-authorization.json').exists())
        with self.assertRaisesRegex(ValueError,'limit|successor|snapshot'):
            await continuation.execute(root=self.root,prior_run='recovered',output=self.root/'fork',
                observation_root=self.root/'observations',authorization_path='authorization.json')
        self.assertEqual(len(self.requests),2)

    async def test_tampered_final_audit_fails_before_limit_change_or_claim(self):
        await self.prepared_prior()
        p=self.root/'recovered/audit_final/audit.json'
        p.write_text(p.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'originally_published'):
            await self.execute()
        self.assertEqual(RunBudget(self.root/'coverage/budget.sqlite','1').summary()['limit_usd'],'1')
        self.assertFalse((self.root/'recovered/recovery-claim.json').exists())
        self.assertEqual(self.requests,[])

    async def test_invalid_revision_retains_previous_candidate_and_skips_audit(self):
        prior=await self.prepared_prior()
        self.responses=[self.answer({'wrong':'contract'})]
        result=await self.execute()
        self.assertEqual(len(self.requests),1)
        self.assertEqual(result['candidate_path'],prior['candidate_path'])
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['self_check_status'],'not_completed')
        self.assertIsNone(result['final_audit_candidate_sha256'])

    async def test_invalid_authorization_does_not_claim_or_change_budget(self):
        await self.prepared_prior()
        path=self.root/'authorization.json';auth=json.loads(path.read_text());auth['confirmation']=' '
        path.write_text(json.dumps(auth))
        with self.assertRaisesRegex(ValueError,'authorization_scope'):
            await self.execute()
        self.assertFalse((self.root/'recovered/recovery-claim.json').exists())
        self.assertEqual(RunBudget(self.root/'coverage/budget.sqlite','1').summary()['limit_usd'],'1')

    async def test_missing_original_ledger_is_rejected_without_creating_a_new_one(self):
        await self.prepared_prior()
        ledger=self.root/'coverage/budget.sqlite';ledger.unlink()
        with self.assertRaisesRegex(ValueError,'source_path_missing'):
            await self.execute()
        self.assertFalse(ledger.exists())
        self.assertFalse((self.root/'recovered/recovery-claim.json').exists())


class AuthorizationTests(unittest.TestCase):
    def test_limit_authorization_preserves_unknown_and_is_append_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'budget.sqlite'
            budget=RunBudget(path,'3',allow_unknown_reservations=True)
            token=budget.reserve('.38341');budget.settle(token,None)
            before=budget.summary()
            auth=dict(authorization_id='approved-five',authorized_by='user',confirmation='OK continue',scope='One round',
                      old_limit_usd='3',new_limit_usd='5')
            record=budget.increase_limit('5',expected_current='3',authorization=auth)
            after=budget.summary()
            self.assertEqual(after,{**before,'limit_usd':'5'})
            self.assertEqual(record['authorization'],auth)
            with closing(sqlite3.connect(path)) as db:
                with self.assertRaisesRegex(sqlite3.DatabaseError,'immutable'):
                    db.execute("UPDATE limit_authorizations SET record='changed'")
                with self.assertRaisesRegex(sqlite3.DatabaseError,'immutable'):
                    db.execute('DELETE FROM limit_authorizations')

    def test_inflight_or_unapproved_increase_rejected_without_changing_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            budget=RunBudget(Path(temp)/'budget.sqlite','3')
            budget.reserve('.1')
            auth=dict(authorization_id='approval',authorized_by='user',confirmation='OK',scope='One round',
                      old_limit_usd='3',new_limit_usd='5')
            with self.assertRaisesRegex(ValueError,'in flight'):
                budget.increase_limit('5',expected_current='3',authorization=auth)
            with self.assertRaisesRegex(ValueError,'authorization'):
                budget.increase_limit('5',expected_current='3',authorization={**auth,'authorized_by':'model'})
            self.assertEqual(budget.summary()['limit_usd'],'3')


if __name__=='__main__':unittest.main()
