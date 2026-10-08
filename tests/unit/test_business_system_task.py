"""Offline runtime boundaries, not model selection or business-quality evaluation."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from uteki.agents.business_map.workflow import BusinessTaskInput, run_business_task
from uteki.agents.data_query.autonomous import runtime_prompt, AUTONOMOUS_PROMPT
from uteki.agents.data_query.autonomous_model import _RequestLimitedBudget
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_autonomous_data_agent as fixtures


class BusinessMaterialPurposeTests(unittest.TestCase):
    setUp = fixtures.AutonomousDataAgentTests.setUp
    run_actions = fixtures.AutonomousDataAgentTests.run_actions

    def test_information_references_cannot_finish_material_selection(self):
        result, planner = self.run_actions([
            fixtures.plan('business'), fixtures.read(), {'action': 'finish'}], purpose='business_materials')
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertIn('business_materials_require_node_reading',
                      {x['reason'] for x in planner.packets[-1]['completion']['unmet']})

    def test_full_node_delivery_keeps_semantic_boundary_and_origin(self):
        plan = fixtures.plan('business')
        plan['requirements'][0].update(kind='read_node', source_id='acme-annual', node_id='business')
        result, planner = self.run_actions([plan, fixtures.read(), {'action': 'finish'}], purpose='business_materials')
        self.assertEqual(result['status'], 'evidence_ready', result)
        self.assertEqual(result['purpose'], 'business_materials')
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        self.assertTrue(all(p['purpose'] == 'business_materials' for p in planner.packets))
        self.assertEqual(runtime_prompt('planner'), AUTONOMOUS_PROMPT)
        self.assertIn('select the relevant complete nodes yourself', runtime_prompt('planner', 'business_materials'))

    def test_node_tail_is_not_complete_material_delivery(self):
        plan = fixtures.plan('business')
        plan['requirements'][0].update(kind='read_node', source_id='acme-annual', node_id='business')
        read = fixtures.read()
        read['read']['start_block_id'] = 'b3'
        result, _ = self.run_actions([plan, read, {'action': 'finish'}], purpose='business_materials')
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertTrue(result['gaps'])


class BusinessSystemTaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.skill = self.root/'skill.md'
        self.skill.write_text('Extract only source-grounded business candidates.')
        self.config = {'provider': 'aihubmix', 'model': 'claude-sonnet-5-5',
            'reasoning_effort': 'high', 'max_tokens': 4096, 'request_timeout': 30,
            'budget_ledger': str(self.root/'task.sqlite'), 'budget_usd': '3',
            'budget_policy': 'enforced', 'max_requests_total': 20}
        self.query = {'question': 'Describe this issuer business and relevant relationships.',
            'purpose': 'business_materials', 'dataset': str(self.root/'dataset'),
            'scope': {'snapshot_id': 'synthetic-dataset', 'company_ids': ['synthetic-issuer'],
                      'source_snapshot_ids': ['synthetic-report'], 'source_policy_id': 'local-frozen-v1',
                      'knowledge_cutoff': '2031-12-31', 'include_candidates': True}}
        self.request = {'query': self.query, 'skill_path': 'skill.md',
            'skill_sha256': digest(self.skill.read_bytes()), 'max_material_bytes': 200000}

    def run_task(self, **changes):
        return asyncio.run(run_business_task(self.request, root=self.root,
            workspace=self.root/'workspace', output=self.root/'run', planner_model_config=self.config,
            extractor_model_config=changes.pop('extractor_model_config', dict(self.config)),
            credentials_root=self.root, observation_root=self.root/'observations', **changes))

    def test_contract_has_no_caller_section_or_excerpt_parameters(self):
        BusinessTaskInput.model_validate(self.request)
        for field, value in [('node_ids', ['expected-answer']), ('packet_path', 'curated.json'),
                             ('blocks', [{'text': 'curated content'}])]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                BusinessTaskInput.model_validate({**self.request, field: value})
        with self.assertRaises(ValueError):
            CompanyQueryInput.model_validate({**self.query, 'node_ids': ['chosen-by-caller']})
        with self.assertRaises(ValueError):
            BusinessTaskInput.model_validate({**self.request, 'query': {**self.query, 'purpose': 'question_answer'}})

    def test_partial_selection_cannot_trigger_extraction(self):
        with patch('uteki.agents.business_map.workflow.CompanyDataCoordinator.query', new_callable=AsyncMock,
                   return_value={'status': 'partial', 'gaps': [{'reason': 'source_missing'}],
                                 'stop_reason': 'completed_with_gaps'}) as query, \
             patch('uteki.agents.business_map.workflow.product_run.prepare') as prepare:
            result = self.run_task()
        self.assertEqual(result['status'], 'material_gap')
        self.assertEqual(result['selection_sufficiency'], 'not_evaluated')
        self.assertEqual(query.call_args.args[0].purpose, 'business_materials')
        prepare.assert_not_called()
        self.assertEqual(result['budget']['requests'], 0)
        sealed = json.loads((self.root/'run/manifest.json').read_text())
        self.assertEqual(sealed['files']['result.json'], digest((self.root/'run/result.json').read_bytes()))

    def test_budget_mismatch_fails_before_selection(self):
        with patch('uteki.agents.business_map.workflow.CompanyDataCoordinator.query', new_callable=AsyncMock) as query:
            with self.assertRaises(ValueError):
                self.run_task(extractor_model_config={**self.config, 'budget_ledger': str(self.root/'fresh.sqlite')})
        query.assert_not_called()
        self.assertFalse((self.root/'run').exists())

    def test_invalid_native_settings_fail_before_paid_selection(self):
        for changes in ({'max_tokens': 64000}, {'model': 'claude-opus-5-5', 'max_tokens': 32000},
                        {'request_timeout': True}, {'reasoning_effort': None}):
            with self.subTest(changes=changes), \
                 patch('uteki.agents.business_map.workflow.CompanyDataCoordinator.query', new_callable=AsyncMock) as query:
                with self.assertRaises(ValueError):
                    self.run_task(extractor_model_config={**self.config, **changes})
                query.assert_not_called()
        self.assertFalse((self.root/'run').exists())

    def test_skill_is_frozen_before_planning(self):
        original = self.skill.read_bytes()
        async def edit_skill(*args, **kwargs):
            self.skill.write_text('Edited during long running task.')
            return {'status': 'partial', 'gaps': [{'reason': 'no_evidence'}]}
        with patch('uteki.agents.business_map.workflow.CompanyDataCoordinator.query', side_effect=edit_skill):
            self.run_task()
        self.assertEqual((self.root/'run/skill.md').read_bytes(), original)

    def test_shared_request_limit_and_unknown_cost_survive_stage_change(self):
        first = _RequestLimitedBudget(RunBudget(self.root/'shared.sqlite', '3'), 2)
        token = first.reserve('.1')
        first.settle(token, '.01')
        second = _RequestLimitedBudget(RunBudget(self.root/'shared.sqlite', '3'), 2)
        unknown = second.reserve('.2')
        second.settle(unknown, None)
        self.assertEqual(second.summary()['requests'], 2)
        self.assertEqual(second.summary()['unknown_requests'], 1)
        with self.assertRaises(BudgetExceeded):
            second.reserve('.1')
        self.assertEqual(first.summary(), second.summary())

    def test_public_workflow_connects_navigation_to_extraction_with_offline_http(self):
        # Mock HTTP responses exercise the real SDK/protocol/host pipeline. These
        # temporary artifacts are transport fixtures, not model-quality evidence.
        import httpx2 as httpx
        from tests.unit.test_business_runtime_materials import RuntimeMaterialsTests
        from tests.unit.test_claude_messages import MockWireBody
        fixture = RuntimeMaterialsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.query.update(dataset=str(fixture.port.dataset), scope=fixture.port.scope.model_dump(mode='json'))
        requests, selected = [], []
        info = dict(requirement_id='navigation', kind='information', description='Find relevant chapters')
        step = 0

        def respond(request):
            nonlocal step
            body = json.loads(request.content)
            requests.append(body)
            packet = json.loads(body['messages'][0]['content'])
            if 'blocks' in packet:
                block = next(b for b in packet['blocks'] if 'Independent source business description.' in b['text'])
                quote = 'Independent source business description.'
                draft = dict(schema_version='business-draft-v2', company_id=packet['company_id'],
                    document_id=packet['document_id'], period_end=packet['period_end'],
                    source_sha256=packet['source_sha256'], summary='Synthetic candidate only.',
                    relationship_absence='unknown', businesses=[dict(id='company', name='Independent', kind='company',
                        description=quote, products_services=[], customers=[], monetization=[],
                        evidence_block_ids=[block['id']], claim_evidence=[dict(field=f, item_index=None,
                            excerpts=[dict(block_id=block['id'], quote=quote)]) for f in ('name', 'description')])],
                    relationships=[], unknowns=[], block_disposition=[dict(block_id=b['id'],
                        disposition='used' if b['id']==block['id'] else 'context', reason='Synthetic pipeline test')
                        for b in packet['blocks']])
                events = [dict(type='message_start', message=dict(id='fixture-extraction', model=body['model'],
                    content=[], usage=dict(input_tokens=100, output_tokens=1))),
                    dict(type='content_block_start', index=0, content_block=dict(type='text', text='')),
                    dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=json.dumps(draft))),
                    dict(type='content_block_stop', index=0),
                    dict(type='message_delta', delta=dict(stop_reason='end_turn'), usage=dict(output_tokens=50)),
                    dict(type='message_stop')]
                return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=MockWireBody(events))
            step += 1
            if step == 1:
                decision = dict(action='load_skill', skill='query')
            elif step == 2:
                decision = dict(action='plan', reason='Navigate first', requirements=[info])
            elif step == 3:
                sid = packet['catalog']['discovery']['sources'][0]['source_snapshot_id']
                decision = dict(action='outline_source', requirement_ids=['navigation'], outline=dict(source_snapshot_id=sid))
            elif step == 4:
                outline = packet['observation']['result']
                selected.extend(dict(requirement_id='read'+str(i), kind='read_node',
                    description='Read actual discovered chapter', source_id=outline['source_snapshot_id'], node_id=n['node_id'])
                    for i,n in enumerate(n for n in outline['nodes'] if n['kind']=='item'))
                decision = dict(action='plan', reason='Use returned outline', requirements=[info, *selected])
            elif step <= 4 + len(selected):
                selected_row = selected[step-5]
                decision = dict(action='read_source', requirement_ids=['navigation', selected_row['requirement_id']],
                    read=dict(source_snapshot_id=selected_row['source_id'], node_id=selected_row['node_id'], count=12))
            else:
                decision = dict(action='finish')
            return httpx.Response(200, json=dict(id='fixture-planner', model=body['model'], stop_reason='end_turn',
                content=[dict(type='text', text=json.dumps(decision))], usage=dict(input_tokens=100, output_tokens=50)))

        real_client = httpx.AsyncClient
        def client(**kwargs):
            kwargs['transport'] = httpx.MockTransport(respond)
            return real_client(**kwargs)
        with patch('uteki.agents.runtime.claude_messages.httpx.AsyncClient', side_effect=client), \
             patch.dict('os.environ', {'AIHUBMIX_API_KEY': 'offline-fixture-key'}), \
             patch('uteki.agents.data_query.autonomous_model.load_provider_key', return_value='offline_fixture'), \
             patch('uteki.agents.business_map.workflow.load_provider_key', return_value='offline_fixture'):
            result = self.run_task()
        self.assertEqual(result['status'], 'candidate', result)
        self.assertEqual(len(requests), 8)
        self.assertEqual(result['budget']['requests'], 8)
        self.assertEqual(result['selection_sufficiency'], 'not_evaluated')
        self.assertFalse((self.root/'run/extraction/budget.sqlite').exists())
        self.assertTrue((self.root/'run/extraction/business_map.json').is_file())
        materials = json.loads((self.root/'run/materials/source_packet.json').read_text())
        self.assertEqual(len(materials['extraction_scope']['selected_nodes']), 2)
        self.assertEqual(json.loads(requests[-1]['messages'][0]['content']), materials)


if __name__ == '__main__':
    unittest.main()
