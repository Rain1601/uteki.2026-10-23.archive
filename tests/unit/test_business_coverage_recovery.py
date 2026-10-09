"""Offline safeguards; fixture audits do not establish model semantic quality."""
import asyncio
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from uteki.agents.business_map import coverage_recovery as recovery
from uteki.agents.business_map.evidence_projection import project_relationship_evidence
from uteki.agents.runtime.run_budget import RunBudget

spec = importlib.util.spec_from_file_location('coverage_tests', Path(__file__).with_name('test_business_coverage_run.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
Helpers = fixtures.CoverageRunTests


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    client = Helpers.client
    respond = Helpers.respond
    answer = Helpers.answer
    candidate = Helpers.candidate
    inventory = Helpers.inventory
    audit = Helpers.audit
    audit_response = Helpers.audit_response
    run_coverage = Helpers.run_coverage

    def setUp(self):
        fixtures.CoverageRunTests.setUp(self)
        native = recovery.ClaudeMessagesModel
        mock = patch.object(recovery, 'ClaudeMessagesModel',
            side_effect=lambda *args, **kwargs: native(*args, **dict(kwargs, client_factory=self.client)))
        mock.start()
        self.addCleanup(mock.stop)

    async def failed_revision(self):
        await self.candidate()
        bad = copy.deepcopy(self.draft)
        issuer = next(b for b in self.packet['blocks'] if b['id']=='issuer')
        bad['relationships'][0]['excerpts'].append(dict(block_id='issuer',quote=issuer['text']))
        self.responses = [self.answer(self.inventory()),
            lambda payload:self.answer(self.audit(payload, needs_revision=True)), self.answer(bad)]
        result = await self.run_coverage()
        self.assertEqual(result['attempts'][-1]['validation_error'], 'relationship_excerpt_evidence_mismatch')
        self.requests.clear()
        return result, bad

    async def recover(self, output='recovered'):
        return await recovery.execute(root=self.root, prior_failed_run='coverage', output=self.root/output,
            observation_root=self.root/'observations', audit_max_tokens=3000)

    async def test_only_redundant_index_changes_and_only_final_audit_is_called(self):
        prior, bad = await self.failed_revision()
        hashes = {p:p.read_bytes() for p in (self.root/'coverage').rglob('*') if p.is_file() and p.name!='budget.sqlite'}
        self.responses = [self.audit_response]
        result = await self.recover()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['budget']['requests'], prior['budget']['requests']+1)
        self.assertEqual(result['budget_path'], 'coverage/budget.sqlite')
        self.assertFalse((self.root/'recovered/budget.sqlite').exists())
        projected = json.loads((self.root/'recovered/revision/projected-raw.json').read_text())
        expected = copy.deepcopy(bad)
        expected['relationships'][0]['evidence_block_ids'].append('issuer')
        self.assertEqual(projected, expected)
        self.assertEqual((self.root/'recovered/revision/response.txt').read_bytes(),
                         (self.root/'coverage/revision/response.txt').read_bytes())
        for p, before in hashes.items():self.assertEqual(p.read_bytes(),before)
        with self.assertRaisesRegex(ValueError, 'snapshot|successor'):
            await self.recover(output='fork')
        self.assertEqual(len(self.requests),1)

    async def test_tampered_original_response_is_rejected_before_dispatch_or_claim(self):
        await self.failed_revision()
        path = self.root/'coverage/revision/response.txt'
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'originally_published'):
            await self.recover()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root/'coverage/recovery-claim.json').exists())

    async def test_legacy_copied_ledger_is_rejected_before_projection_or_dispatch(self):
        await self.failed_revision()
        ledger = self.root/'coverage/budget.sqlite'
        frozen = ledger.read_bytes()
        (self.root/'coverage/recovery.json').write_text(json.dumps({'prior_failed_run':'older'}))
        with self.assertRaisesRegex(ValueError, 'legacy_copied_budget_requires_reconciliation'):
            await self.recover()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root/'coverage/recovery-claim.json').exists())
        self.assertFalse((self.root/'recovered').exists())
        self.assertEqual(ledger.read_bytes(), frozen)

    async def test_failed_final_audit_keeps_valid_projected_candidate(self):
        await self.failed_revision()
        self.responses = [self.answer({'wrong':'schema'})]
        result = await self.recover()
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['self_check_status'], 'not_completed')
        self.assertIsNone(result['final_audit_candidate_sha256'])
        self.assertTrue((self.root/result['candidate_path']/'business_map.json').exists())
        self.assertEqual(len(self.requests),1)

    async def test_unknown_cost_is_inherited_and_budget_failure_preserves_candidate(self):
        prior, _ = await self.failed_revision()
        ledger = RunBudget(self.root/'coverage/budget.sqlite', '1', allow_unknown_reservations=True)
        held = Decimal('1')-Decimal(prior['budget']['estimated_spent_usd'])-Decimal('.000001')
        token = ledger.reserve(held)
        ledger.settle(token, None)
        prior['budget'] = ledger.summary()
        (self.root/'coverage/summary.json').write_text(json.dumps(prior))
        result = await self.recover()
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['stop_reason'], 'audit_final_failed_BudgetExceeded')
        self.assertEqual(result['budget']['held_usd'], str(held))
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertEqual(self.requests, [])
        self.assertTrue((self.root/result['candidate_path']/'business_map.json').exists())

    async def test_projection_cannot_hide_invalid_quote_or_remove_existing_index(self):
        _, bad = await self.failed_revision()
        for mutate in (lambda v:v['relationships'][0]['excerpts'][0].update(quote='Invented statement'),
                       lambda v:v['relationships'][0]['evidence_block_ids'].append('period')):
            value=copy.deepcopy(bad)
            mutate(value)
            before=copy.deepcopy(value)
            with self.assertRaises(ValueError):
                project_relationship_evidence(value,self.packet,expected_version=value['schema_version'])
            self.assertEqual(value,before)

    async def test_predispatch_failure_can_resume_only_final_audit_on_same_ledger(self):
        await self.failed_revision()
        from uteki.agents.runtime.run_budget import RequestEnvelopeTooLarge
        with patch.object(recovery, 'metered_response', side_effect=RequestEnvelopeTooLarge('bounded fixture')):
            failed = await self.recover()
        self.assertEqual(failed['stop_reason'],'audit_final_failed_RequestEnvelopeTooLarge')
        self.responses = [self.audit_response]
        result = await recovery.execute(root=self.root,prior_failed_run='recovered',output=self.root/'next',
            observation_root=self.root/'observations',audit_max_tokens=3000)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(result['self_check_status'],'pass')
        self.assertEqual(result['budget_path'],'coverage/budget.sqlite')
        final=self.root/'next/audit_final'
        for name in ('manifest.json','source_packet.json','skill.md','request.json','result.json'):
            self.assertTrue((final/name).is_file())
        recovery.run.verify_published_artifacts(root=self.root,observation_root=self.root/'observations',
            stage=final,trace_id=result['attempts'][-1]['trace_id'],relative_paths=['result.json','manifest.json'])


del Helpers  # Avoid re-discovering the imported base suite in this module.

if __name__ == '__main__':
    unittest.main()
