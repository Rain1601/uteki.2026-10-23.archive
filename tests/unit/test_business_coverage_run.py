"""Offline execution boundaries for source inventory and candidate-bound audits.

Model semantic answers are fixtures, never evidence of actual extraction quality.
"""
import copy
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx2 as httpx
from uteki.agents.business_map import coverage_contract as contract, coverage_run, product_run as base
from uteki.agents.business_map.product_contract import BUSINESS_DRAFT_VERSION

spec = importlib.util.spec_from_file_location('coverage_fixture', Path(__file__).with_name('test_business_only_run.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class CoverageRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.requests, self.responses = [], []
        env = patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-test-key'})
        env.start()
        self.addCleanup(env.stop)
        native = coverage_run.ClaudeMessagesModel
        def factory(*args, **kwargs):
            return native(*args, **dict(kwargs, client_factory=self.client))
        mock = patch.object(coverage_run, 'ClaudeMessagesModel', side_effect=factory)
        mock.start()
        self.addCleanup(mock.stop)

    def client(self, **kwargs):
        return httpx.AsyncClient(**dict(kwargs, transport=httpx.MockTransport(self.respond)))

    def respond(self, request):
        request = json.loads(request.content)
        self.requests.append(request)
        response = self.responses.pop(0)
        if callable(response):
            response = response(json.loads(request['messages'][0]['content']))
        return httpx.Response(200, json=response)

    def answer(self, value, *, usage=True, stop='end_turn'):
        data = dict(id='msg_coverage', model='claude-sonnet-5-5', stop_reason=stop,
                    content=[dict(type='text', text=json.dumps(value))])
        if usage:
            data['usage'] = dict(input_tokens=180, output_tokens=120)
        return data

    async def candidate(self, company='quartz', period='2020-09-30'):
        self.packet, self.draft = fixture.fixture(self.root, company, period)
        (self.root/'packet.json').write_text(json.dumps(self.packet))
        (self.root/'skill.md').write_text('Preserve supported source objects and exact evidence. No expected graph.')
        prepared = base.prepare(root=self.root, packet_path='packet.json', skill_path='skill.md',
            company_id=company, document_id=self.packet['document_id'], period_end=period,
            model='claude-sonnet-5-5', effort='high', max_tokens=3000, timeout_seconds=30,
            contract_version=BUSINESS_DRAFT_VERSION)
        prepared['native']._client_factory = self.client
        self.responses = [self.answer(self.draft)]
        await base.execute(prepared, root=self.root, output=self.root/'original',
                           observation_root=self.root/'observations', budget_limit_usd='1')
        self.requests.clear()

    async def run_coverage(self, budget='1'):
        return await coverage_run.execute(root=self.root, input_run='original', output=self.root/'coverage',
            observation_root=self.root/'observations', budget_limit_usd=budget,
            inventory_max_tokens=3000, audit_max_tokens=3000)

    def inventory(self):
        blocks = {b['id']: b for b in self.packet['blocks']}
        mentions = []
        for node, block, category, surface in [
                ('issuer', 'issuer', 'issuer_entity', self.packet['company_id']+' Systems'),
                ('services', 'section', 'issuer_grouping', 'Services'),
                ('beacon', 'product', 'issuer_offering', 'Beacon support software'),
                ('beacon-again', 'competition', 'issuer_offering', 'Beacon support software')]:
            mentions.append(dict(id=node, block_id=block, surface=surface, category=category,
                trigger='self_offering' if category=='issuer_offering' else 'definition',
                excerpts=[dict(block_id=block, quote=blocks[block]['text'])], scope_note='Selected subsection.'))
        mentioned = {m['block_id'] for m in mentions}
        return dict(schema_version='business-coverage-inventory-v1',
            source_packet_sha256=contract.canonical_hash(self.packet), mentions=mentions,
            blocks=[dict(block_id=b['id'], disposition='mentions' if b['id'] in mentioned else
                'layout' if b['id']=='layout' else 'context', reason='Source classification.')
                for b in self.packet['blocks']])

    def audit(self, payload, *, needs_revision=False):
        inventory, draft = payload['source_inventory'], payload['own_candidate']
        value = dict(schema_version='business-coverage-audit-v1',
            candidate_sha256=payload['candidate_sha256'], inventory_sha256=payload['inventory_sha256'],
            mappings=[dict(mention_id=m['id'], disposition='node',
                node_ids=['beacon' if m['id']=='beacon-again' else m['id']], rationale='Same source object.')
                for m in inventory['mentions']],
            checks=[dict(check_key=t['check_key'], verdict='supported', rationale='Exact fixture evidence.')
                for t in payload['check_targets']])
        self.assertEqual(payload['check_targets'], contract.check_targets(draft))
        if needs_revision:
            value['checks'][0]['verdict'] = 'partial'
        return value

    def audit_response(self, payload):
        return self.answer(self.audit(payload))

    async def test_pass_uses_source_only_inventory_and_exhaustive_bound_audit(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()), self.audit_response]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['candidate_path'], 'original')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
        self.assertFalse(result['independent_evaluation'])
        first = json.loads(self.requests[0]['messages'][0]['content'])
        self.assertEqual(set(first), {'frozen_source_packet', 'source_packet_sha256'})
        self.assertEqual(first['frozen_source_packet'], self.packet)
        self.assertNotIn('own_candidate', first)
        self.assertNotIn('reference_answer', first)
        manifest = json.loads((self.root/'coverage/inventory/manifest.json').read_text())
        self.assertIsNone(manifest['input_candidate_sha256'])
        self.assertEqual(result['budget']['requests'], 2)
        self.assertFalse((self.root/'coverage/revision').exists())

    async def test_transport_retry_keeps_unknown_cost_and_finishes_with_new_full_reply(self):
        await self.candidate()
        def broken(_):
            raise httpx.RemoteProtocolError('offline stream interruption')
        self.responses = [broken, self.answer(self.inventory()), self.audit_response]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.requests[0], self.requests[1])
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertGreater(float(result['budget']['held_usd']), 0)
        self.assertTrue((self.root/'coverage/inventory/transport-attempts/001/response_metadata.json').exists())
        self.assert_result_references(result)

    async def test_transport_retry_stops_at_task_cap_and_does_not_log_exception_secret(self):
        await self.candidate()
        def broken(_):
            raise httpx.RemoteProtocolError('transport echoed credential offline-test-key')
        self.responses = [broken]
        result = await self.run_coverage('0.12')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['stop_reason'], 'inventory_failed_BudgetExceeded')
        self.assertEqual(result['budget']['requests'], 1)
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertLessEqual(float(result['budget']['held_usd']), .12)
        self.assertFalse((self.root/'coverage/audit_initial').exists())
        for path in (self.root/'coverage').rglob('*'):
            if path.suffix in ('.json', '.txt'):
                self.assertNotIn('offline-test-key', path.read_text(), str(path))

    async def test_cancelled_dispatch_keeps_unknown_reservation_and_does_not_retry(self):
        await self.candidate()
        def cancelled(_):
            raise asyncio.CancelledError()
        self.responses = [cancelled]
        with self.assertRaises(asyncio.CancelledError):
            await self.run_coverage()
        self.assertEqual(len(self.requests), 1)
        result = json.loads((self.root/'coverage/summary.json').read_text())
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertEqual(result['budget']['in_flight_requests'], 0)
        self.assertGreater(float(result['budget']['held_usd']), 0)
        self.assertFalse((self.root/'coverage/audit_initial').exists())
        attempts = self.root/'coverage/inventory/transport-attempts'
        self.assertTrue((attempts/'001/response_metadata.json').exists())
        self.assertFalse((attempts/'002').exists())

    async def test_resume_failed_inventory_inherits_budget_without_mutating_old_snapshot(self):
        await self.candidate()
        def broken(_): raise httpx.RemoteProtocolError('offline')
        self.responses = [broken, broken]
        failed = await self.run_coverage()
        old = (self.root/'coverage/summary.json').read_bytes()
        self.responses = [self.answer(self.inventory()), self.audit_response]
        result = await coverage_run.execute(root=self.root, input_run='original', output=self.root/'recovered',
            observation_root=self.root/'observations', budget_limit_usd='1',
            inventory_max_tokens=3000,audit_max_tokens=3000,prior_failed_run='coverage')
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['budget']['requests'],4)
        self.assertEqual(result['budget']['unknown_requests'],2)
        self.assertEqual(result['budget']['held_usd'],failed['budget']['held_usd'])
        self.assertEqual((self.root/'coverage/summary.json').read_bytes(),old)

    async def test_recovery_cannot_fork_the_same_failed_budget_twice(self):
        await self.candidate()
        def broken(_): raise httpx.RemoteProtocolError('offline')
        self.responses = [broken, broken]
        failed = await self.run_coverage()
        frozen = {p.relative_to(self.root/'coverage'): p.read_bytes()
                  for p in (self.root/'coverage').rglob('*') if p.is_file()}
        self.responses = [self.answer(self.inventory()), self.audit_response]
        recovered = await coverage_run.execute(root=self.root, input_run='original', output=self.root/'recovered',
            observation_root=self.root/'observations', budget_limit_usd='1',
            inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(recovered['budget']['held_usd'], failed['budget']['held_usd'])
        count = len(self.requests)
        with self.assertRaises((ValueError, FileExistsError)):
            await coverage_run.execute(root=self.root, input_run='original', output=self.root/'fork',
                observation_root=self.root/'observations', budget_limit_usd='1',
                inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(len(self.requests), count)
        for name, data in frozen.items():
            self.assertEqual((self.root/'coverage'/name).read_bytes(), data, str(name))

    async def test_concurrent_recoveries_have_only_one_dispatching_successor(self):
        await self.candidate()
        def broken(_): raise httpx.RemoteProtocolError('offline')
        self.responses = [broken, broken]
        await self.run_coverage()
        self.requests.clear()
        self.responses = [self.answer(self.inventory()), self.audit_response]
        async def recover(name):
            return await coverage_run.execute(root=self.root, input_run='original', output=self.root/name,
                observation_root=self.root/'observations', budget_limit_usd='1',
                inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        outcomes = await asyncio.gather(recover('recovered-a'), recover('recovered-b'), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        self.assertEqual(sum(isinstance(item, (ValueError, FileExistsError)) for item in outcomes), 1)
        self.assertEqual(len(self.requests), 2)

    async def test_output_cap_recovery_is_explicit_and_inherits_spend(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory(), stop='max_tokens')]
        failed = await self.run_coverage()
        self.assertEqual(len(self.requests), 1, 'max_tokens must not trigger an automatic retry')
        old = (self.root/'coverage/summary.json').read_bytes()
        # An unchanged limit cannot turn a deterministic truncation into a retry.
        with self.assertRaises(ValueError):
            await coverage_run.execute(root=self.root, input_run='original', output=self.root/'same-cap',
                observation_root=self.root/'observations', budget_limit_usd='1',
                inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(len(self.requests), 1)
        self.responses = [self.answer(self.inventory()), self.audit_response]
        recovered = await coverage_run.execute(root=self.root, input_run='original', output=self.root/'larger-cap',
            observation_root=self.root/'observations', budget_limit_usd='1',
            inventory_max_tokens=4000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(recovered['status'], 'candidate')
        self.assertEqual(recovered['budget']['requests'], 3)
        self.assertGreater(float(recovered['budget']['estimated_spent_usd']), float(failed['budget']['estimated_spent_usd']))
        self.assertEqual(self.requests[1]['max_tokens'], 4000)
        self.assertEqual((self.root/'coverage/summary.json').read_bytes(), old)

    async def test_output_cap_recovery_does_not_bypass_unknown_usage_or_budget_limit(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory(), usage=False, stop='max_tokens')]
        await self.run_coverage()
        for budget in ('1', '2'):
            with self.assertRaises(ValueError):
                await coverage_run.execute(root=self.root, input_run='original', output=self.root/('blocked-'+budget),
                    observation_root=self.root/'observations', budget_limit_usd=budget,
                    inventory_max_tokens=4000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(len(self.requests), 1)

    async def test_resume_published_inventory_and_old_unresolved_audit_only_calls_revision_and_final(self):
        await self.candidate()
        bad = self.inventory()
        bad['mentions'][2]['surface'] = 'Unsupported paraphrase'
        def unresolved(payload):
            value = self.audit(payload)
            value['mappings'][1].update(disposition='unresolved', node_ids=['services'])
            return self.answer(value)
        self.responses = [self.answer(bad), self.repaired_inventory_response, unresolved]
        # Simulate the old host validator rejecting a complete, paid model answer.
        with patch.object(contract, 'validate_audit', side_effect=ValueError('non_node_mapping_requires_empty_node_ids')):
            failed = await self.run_coverage()
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual([a['status'] for a in failed['attempts']], ['completed', 'failed'])
        self.assertEqual(failed['budget']['requests'], 3)
        frozen = {p.relative_to(self.root/'coverage'): p.read_bytes()
                  for p in (self.root/'coverage').rglob('*') if p.is_file()}
        revised = copy.deepcopy(self.draft)
        revised['summary'] = 'Revised from the source and own unresolved audit.'
        self.responses = [self.answer(revised), self.audit_response]
        self.requests.clear()
        result = await coverage_run.execute(root=self.root, input_run='original', output=self.root/'recovered',
            observation_root=self.root/'observations', budget_limit_usd='1',
            inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['budget']['requests'], 5)
        self.assertGreater(float(result['budget']['estimated_spent_usd']), float(failed['budget']['estimated_spent_usd']))
        payload = json.loads(self.requests[0]['messages'][0]['content'])
        self.assertEqual(payload['source_inventory'], self.inventory())
        self.assertEqual(payload['own_audit']['computed_status'], 'needs_revision')
        self.assertEqual(payload['own_audit']['mappings'][1]['node_ids'], ['services'])
        self.assertEqual(payload['own_candidate'], json.loads((self.root/'original/draft.json').read_text()))
        for mode in ('inventory', 'audit_initial'):
            stage = self.root/'recovered'/mode
            self.assertEqual(list((stage/'model-calls').glob('*-start.json')), [])
            self.assertEqual((stage/'response.txt').read_bytes(), (self.root/'coverage'/mode/'response.txt').read_bytes())
            self.assertIn('reused_stage_response', result['attempts'][0 if mode=='inventory' else 1])
        self.assertFalse((self.root/'recovered/inventory/contract-repair').exists())
        for name, raw in frozen.items():
            self.assertEqual((self.root/'coverage'/name).read_bytes(), raw, str(name))
        self.assert_result_references(result)

    async def test_audit_recovery_rejects_changed_published_inventory_before_dispatch(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()), self.audit_response]
        with patch.object(contract, 'validate_audit', side_effect=ValueError('old contract failure')):
            await self.run_coverage()
        inventory_path = self.root/'coverage/inventory/inventory.json'
        value = json.loads(inventory_path.read_text())
        value['mentions'][0]['scope_note'] = 'Manual change after publication'
        inventory_path.write_text(json.dumps(value))
        self.requests.clear()
        with self.assertRaisesRegex(ValueError, 'not_originally_published: inventory.json'):
            await coverage_run.execute(root=self.root, input_run='original', output=self.root/'recovered',
                observation_root=self.root/'observations', budget_limit_usd='1',
                inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root/'coverage/recovery-claim.json').exists())

    async def test_revision_rebuilds_keys_and_final_binds_new_draft_for_another_scope(self):
        await self.candidate('cobalt', '2023-03-31')
        changed = copy.deepcopy(self.draft)
        changed['relationships'].append(dict(source_id='services', target_id='issuer', kind='part_of',
            description='Services belongs to the issuer.', basis='derived',
            rationale='Section scope identifies the reporting company.', evidence_block_ids=['issuer','section'],
            excerpts=[dict(block_id=b['id'],quote=b['text']) for b in self.packet['blocks'] if b['id'] in ('issuer','section')]))
        self.responses = [self.answer(self.inventory()),
            lambda p:self.answer(self.audit(p, needs_revision=True)), self.answer(changed), self.audit_response]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['candidate_path'], 'coverage/revision')
        initial = json.loads(self.requests[1]['messages'][0]['content'])
        revision = json.loads(self.requests[2]['messages'][0]['content'])
        final = json.loads(self.requests[3]['messages'][0]['content'])
        self.assertEqual(set(revision), {'frozen_source_packet','source_inventory','own_candidate','own_audit'})
        self.assertEqual(final['frozen_source_packet']['company_id'], 'cobalt')
        self.assertEqual(final['frozen_source_packet']['period_end'], '2023-03-31')
        self.assertNotEqual(initial['candidate_sha256'], final['candidate_sha256'])
        self.assertEqual(len(final['check_targets']), len(initial['check_targets'])+1)
        self.assertEqual(result['final_audit_candidate_sha256'], final['candidate_sha256'])
        self.assertEqual(result['candidate_sha256'], final['candidate_sha256'])
        self.assertEqual(result['budget']['requests'], 4)
        self.assertEqual(json.loads((self.root/'original/draft.json').read_text()), initial['own_candidate'])

    async def test_final_audit_failure_is_not_repaired_again_or_accepted(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()),
            lambda p:self.answer(self.audit(p, needs_revision=True)), self.answer(self.draft),
            lambda p:self.answer(self.audit(p, needs_revision=True))]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result['candidate_path'], 'coverage/revision')
        self.assertEqual(result['self_check_status'], 'needs_revision')
        self.assertEqual(result['stop_reason'], 'final_self_audit_needs_revision')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')

    async def test_final_audit_cannot_reuse_old_candidate_hash(self):
        await self.candidate()
        changed = copy.deepcopy(self.draft)
        changed['summary'] = 'Same frozen subsection, revised candidate summary.'
        old_hash = {}
        def first(payload):
            old_hash['value'] = payload['candidate_sha256']
            return self.answer(self.audit(payload, needs_revision=True))
        def stale(payload):
            value = self.audit(payload)
            self.assertNotEqual(payload['candidate_sha256'], old_hash['value'])
            value['candidate_sha256'] = old_hash['value']
            return self.answer(value)
        self.responses = [self.answer(self.inventory()), first, self.answer(changed), stale]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['candidate_path'], 'coverage/revision')
        self.assertEqual(result['self_check_status'], 'pending_final_audit')
        self.assertIn('audit_candidate_binding_mismatch', result['attempts'][-1]['validation_error'])

    def assert_result_references(self, result):
        for attempt in result['attempts']:
            events = [json.loads(p.read_text()) for p in
                (self.root/'observations'/attempt['trace_id']/'events').glob('*.json')]
            finished = [event for event in events if event['type']=='run.finished']
            self.assertEqual(len(finished), 1)
            ref = finished[0]['data']['result_ref']
            self.assertIsNotNone(ref)
            path = self.root/attempt['path']/'result.json'
            self.assertEqual(ref['sha256'], base.digest(path.read_bytes()))
            self.assertEqual(finished[0]['data']['business_status'], attempt['status'])

    async def test_request_construction_failure_is_recorded_and_native_closed(self):
        await self.candidate()
        factory = coverage_run.ClaudeMessagesModel.side_effect
        created = []
        def failing_factory(*args, **kwargs):
            native = factory(*args, **kwargs)
            native.request_body = Mock(side_effect=ValueError('unsupported_test_request'))
            native.aclose = AsyncMock(wraps=native.aclose)
            created.append(native)
            return native
        coverage_run.ClaudeMessagesModel.side_effect = failing_factory
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['stop_reason'], 'inventory_failed_ValueError')
        self.assertIn('unsupported_test_request', result['attempts'][0]['validation_error'])
        self.assertEqual(result['budget']['requests'], 0)
        self.assertEqual(len(created), 1)
        created[0].aclose.assert_awaited_once()
        self.assert_result_references(result)

    async def test_finished_events_reference_final_stage_result_bytes(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()),
            lambda p:self.answer(self.audit(p, needs_revision=True)),
            self.answer(self.draft), self.audit_response]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result['self_check_status'], 'pass')
        self.assert_result_references(result)

    async def test_initial_pass_response_cannot_accept_changed_original(self):
        await self.candidate()
        def tamper(payload):
            path = self.root/'original/result.json'
            value = json.loads(path.read_text())
            value['changed_during_model_call'] = True
            path.write_text(json.dumps(value))
            return self.answer(self.audit(payload))
        self.responses = [self.answer(self.inventory()), tamper]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['self_check_status'], 'not_run')
        self.assertIsNone(result['final_audit_candidate_sha256'])
        self.assertIn('input_changed_after_preflight', result['attempts'][-1]['validation_error'])
        self.assertFalse((self.root/'coverage/audit_initial/audit.json').exists())
        self.assert_result_references(result)

    async def test_final_pass_response_cannot_accept_changed_inventory(self):
        await self.candidate()
        def tamper(payload):
            path = self.root/'coverage/inventory/inventory.json'
            value = json.loads(path.read_text())
            value['mentions'][0]['scope_note'] = 'Mutated during final audit'
            path.write_text(json.dumps(value))
            return self.answer(self.audit(payload))
        self.responses = [self.answer(self.inventory()),
            lambda p:self.answer(self.audit(p, needs_revision=True)), self.answer(self.draft), tamper]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['self_check_status'], 'pending_final_audit')
        self.assertIsNone(result['final_audit_candidate_sha256'])
        self.assertIn('dependency_changed_after_validation', result['attempts'][-1]['validation_error'])
        self.assertFalse((self.root/'coverage/audit_final/audit.json').exists())
        self.assert_result_references(result)

    async def test_missing_audit_check_rejected_without_revision(self):
        await self.candidate()
        def incomplete(payload):
            value = self.audit(payload)
            value['checks'].pop()
            return self.answer(value)
        self.responses = [self.answer(self.inventory()), incomplete]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['candidate_path'], 'original')
        self.assertIn('audit_check_coverage_mismatch', result['attempts'][-1]['validation_error'])

    async def test_invalid_inventory_stops_before_audit(self):
        await self.candidate()
        value = self.inventory()
        value['blocks'].pop()
        self.responses = [self.answer(value)]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('inventory_block_coverage_mismatch', result['attempts'][-1]['validation_error'])

    def repaired_inventory_response(self, payload):
        self.assertEqual(set(payload), {'frozen_source_packet', 'inventory_sha256',
            'source_packet_sha256', 'error_mentions', 'validation_errors'})
        self.assertEqual(payload['frozen_source_packet'], self.packet)
        self.assertEqual([m['id'] for m in payload['error_mentions']], ['beacon'])
        self.assertEqual(payload['validation_errors']['error_mention_ids'], ['beacon'])
        self.assertNotIn('own_candidate', payload)
        return self.answer(dict(schema_version='business-coverage-inventory-repair-v1',
            inventory_sha256=payload['inventory_sha256'], source_packet_sha256=payload['source_packet_sha256'],
            replacements=[self.inventory()['mentions'][2]]))

    async def test_local_inventory_repair_preserves_original_and_supplies_no_answer_graph(self):
        await self.candidate()
        bad = self.inventory()
        bad['mentions'][2]['surface'] = 'Unsupported paraphrase'
        self.responses = [self.answer(bad), self.repaired_inventory_response, self.audit_response]
        result = await self.run_coverage()
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(len(self.requests), 3)
        stage = self.root/'coverage/inventory'
        self.assertEqual(json.loads((stage/'response.txt').read_text()), bad)
        self.assertEqual(json.loads((stage/'inventory.json').read_text()), self.inventory())
        sent = json.loads(self.requests[1]['messages'][0]['content'])
        self.assertEqual(sent['error_mentions'][0], bad['mentions'][2])
        self.assertEqual(sent['inventory_sha256'], contract.canonical_hash(bad))
        repaired = json.loads((stage/'inventory.json').read_text())
        self.assertEqual(repaired['blocks'], bad['blocks'])
        self.assertEqual(repaired['mentions'][:2]+repaired['mentions'][3:], bad['mentions'][:2]+bad['mentions'][3:])
        audit = json.loads(self.requests[2]['messages'][0]['content'])
        self.assertEqual(audit['source_inventory'], repaired)
        self.assert_result_references(result)

    async def test_invalid_local_repair_stops_without_audit_or_second_repair(self):
        await self.candidate()
        bad = self.inventory()
        bad['mentions'][2]['surface'] = 'Unsupported paraphrase'
        def invalid(payload):
            answer = self.repaired_inventory_response(payload)
            patch = json.loads(answer['content'][0]['text'])
            patch['replacements'][0]['category'] = 'cross_reference'
            return self.answer(patch)
        self.responses = [self.answer(bad), invalid]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('changed_non_evidence_fields', result['attempts'][0]['validation_error'])
        self.assertFalse((self.root/'coverage/audit_initial').exists())
        self.assertFalse((self.root/'coverage/inventory/inventory.json').exists())
        self.assertEqual(json.loads((self.root/'coverage/inventory/response.txt').read_text()), bad)

    async def test_cancelled_local_repair_preserves_both_attempts_and_stops(self):
        await self.candidate()
        bad = self.inventory()
        bad['mentions'][2]['surface'] = 'Unsupported paraphrase'
        def cancelled(_): raise asyncio.CancelledError()
        self.responses = [self.answer(bad), cancelled]
        with self.assertRaises(asyncio.CancelledError):
            await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        result = json.loads((self.root/'coverage/summary.json').read_text())
        self.assertEqual(result['budget']['requests'], 2)
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertFalse((self.root/'coverage/audit_initial').exists())
        self.assertEqual(json.loads((self.root/'coverage/inventory/response.txt').read_text()), bad)

    async def test_published_provenance_rejects_changed_bytes_missing_events_and_wrong_trace(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()), self.audit_response]
        result = await self.run_coverage()
        stage = self.root/'coverage/inventory'
        trace = result['attempts'][0]['trace_id']
        args = dict(root=self.root, observation_root=self.root/'observations', stage=stage,
                    trace_id=trace, relative_paths=['request.json', 'response.txt', 'response_metadata.json', 'configuration.json'])
        self.assertEqual(len(coverage_run.verify_published_artifacts(**args)), 4)
        raw = (stage/'response.txt').read_bytes()
        (stage/'response.txt').write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError, 'not_originally_published'):
            coverage_run.verify_published_artifacts(**args)
        (stage/'response.txt').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'output_mismatch'):
            coverage_run.verify_published_artifacts(**dict(args, trace_id=result['attempts'][1]['trace_id']))
        for path in (self.root/'observations'/trace/'events').glob('*.json'):
            event=json.loads(path.read_text())
            if event['type']=='artifact.published' and event['data']['ref']['path']=='response.txt':
                path.unlink()
        with self.assertRaisesRegex(ValueError, 'not_originally_published'):
            coverage_run.verify_published_artifacts(**args)

    async def test_recovery_reconciles_only_published_legacy_preconnect_charge(self):
        await self.candidate()
        # Reproduce the older adapter's sent-before-connect accounting. Production
        # now records ConnectError as not_sent, so this explicit shim is test-only.
        factory = coverage_run.ClaudeMessagesModel.side_effect
        def legacy_factory(*args, **kwargs):
            native = factory(*args, **kwargs)
            original = native.get_response
            async def legacy_get_response(*a, **kw):
                try:
                    return await original(*a, **kw)
                except RuntimeError:
                    if (native.response_metadata or {}).get('transport_error_type') == 'ConnectError':
                        native.response_metadata['dispatch_status'] = 'sent'
                    raise
            native.get_response = legacy_get_response
            return native
        coverage_run.ClaudeMessagesModel.side_effect = legacy_factory
        def read_failure(_): raise httpx.RemoteProtocolError('read interrupted')
        def connect_failure(_): raise httpx.ConnectError('connection failed')
        self.responses = [read_failure, connect_failure]
        failed = await self.run_coverage()
        self.assertEqual(failed['budget']['unknown_requests'], 2)
        old_logs = {p: p.read_bytes() for p in (self.root/'coverage/inventory/model-calls').glob('*-end.json')}
        self.responses = [self.answer(self.inventory()), self.audit_response]
        result = await coverage_run.execute(root=self.root, input_run='original', output=self.root/'recovered',
            observation_root=self.root/'observations', budget_limit_usd='1',
            inventory_max_tokens=3000, audit_max_tokens=3000, prior_failed_run='coverage')
        self.assertEqual(result['self_check_status'], 'pass')
        self.assertEqual(result['budget']['unknown_requests'], 1)
        self.assertGreater(float(result['budget']['held_usd']), 0)
        self.assertLess(float(result['budget']['held_usd']), float(failed['budget']['held_usd']))
        corrections = json.loads((self.root/'recovered/preconnect-reconciliation.json').read_text())['corrections']
        self.assertEqual(len(corrections), 1)
        corrected_path = self.root/corrections[0]['record']
        self.assertEqual(json.loads(corrected_path.read_text())['transport_error_type'], 'ConnectError')
        self.assertEqual(corrections[0]['sha256'], base.digest(old_logs[corrected_path]))
        for path, raw in old_logs.items():
            self.assertEqual(path.read_bytes(), raw)

    async def test_unknown_inventory_usage_stops_before_audit(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory(), usage=False)]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['unknown_requests'], 1)
        self.assertEqual(result['candidate_path'], 'original')

    async def test_truncated_audit_stops_before_revision(self):
        await self.candidate()
        self.responses = [self.answer(self.inventory()),
            lambda p:self.answer(self.audit(p,needs_revision=True), stop='max_tokens')]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse((self.root/'coverage/revision').exists())

    async def test_budget_prevents_first_model_call(self):
        await self.candidate()
        result = await self.run_coverage('0.00001')
        self.assertEqual(len(self.requests), 0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['budget']['requests'], 0)

    async def test_manually_edited_original_rejected_before_dispatch(self):
        await self.candidate()
        path = self.root/'original/draft.json'
        value = json.loads(path.read_text())
        value['summary'] = 'Manual replacement'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'draft_raw_response'):
            await self.run_coverage()
        self.assertEqual(len(self.requests), 0)

    async def test_original_modified_between_stages_blocks_next_call(self):
        await self.candidate()
        def tamper(_):
            path = self.root/'original/result.json'
            value = json.loads(path.read_text())
            value['custom_untrusted_change'] = True
            path.write_text(json.dumps(value))
            return self.answer(self.inventory())
        self.responses = [tamper]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('input_changed_after_preflight', result['attempts'][-1]['validation_error'])

    async def test_dependency_modified_between_stages_blocks_revision(self):
        await self.candidate()
        def tamper(payload):
            path = self.root/'coverage/inventory/inventory.json'
            value = json.loads(path.read_text())
            value['mentions'][0]['scope_note'] = 'Manual mutation'
            path.write_text(json.dumps(value))
            return self.answer(self.audit(payload, needs_revision=True))
        self.responses = [self.answer(self.inventory()), tamper]
        result = await self.run_coverage()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('dependency_changed_after_validation', result['attempts'][-1]['validation_error'])
        self.assertEqual(result['candidate_path'], 'original')


if __name__ == '__main__':
    unittest.main()
