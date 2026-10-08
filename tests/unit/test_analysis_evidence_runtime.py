"""Analysis-evidence role and delivery-state checks; synthetic planners, no models."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from uteki.agents.data_query.autonomous import AutonomousDataAgent, runtime_prompt, runtime_prompt_version
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit import test_answer_handoff as fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_answer import answer_plan
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_task_completion import pin_dataset


def choose(*block_ids):
    def decision(packet):
        refs = []
        for bid in block_ids:
            item = next(i for i in packet['retained_body']['items'] if i['block_id'] == bid)
            refs.append({'context_id': item['context_evidence_id'], 'block_id': bid})
        return {'action': 'select_evidence', 'requirement_ids': ['business'],
                'delivery': {'blocks': refs}, 'reason': 'Deliver only the original blocks needed for this question.'}
    return decision


class ManagedFixturePlanner(ScriptedPlanner):
    async def aclose(self):
        self.closed = True

    def snapshot_usage(self):
        return {'plan_origin': 'scripted_fixture', 'model_requests': 0}


class AnalysisEvidenceRuntimeTests(unittest.TestCase):
    setUp = fixtures.AnswerHandoffTests.setUp

    def run_actions(self, actions, *, worker=None, limits=None, name='run'):
        planner = ScriptedPlanner(actions)
        output = self.root / name
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, planner, worker_planner=worker,
                purpose='analysis_evidence', limits={'max_steps': len(actions) + (6 if worker else 0),
                'max_packet_bytes': 64000, **(limits or {})}).run(self.request, output=output))
        return result, planner, output

    def test_prompt_replaces_narrative_policy_for_planner_and_worker(self):
        for role in ('planner', 'worker'):
            with self.subTest(role=role):
                text = runtime_prompt(role, 'analysis_evidence')
                self.assertNotIn('Questions requiring a narrative answer MUST use kind=source_answer', text)
                self.assertNotIn('For source_answer, use action=answer', text)
                self.assertIn('Even when the original question is narrative, use kind=source_evidence', text)
                self.assertIn('Do not create source_answer requirements', text)
                self.assertNotEqual(runtime_prompt_version('analysis_evidence'), runtime_prompt_version())
                self.assertIn('Questions requiring a narrative answer MUST use kind=source_answer', runtime_prompt(role))

    def test_host_rejects_source_answer_then_accepts_original_evidence(self):
        result, planner, output = self.run_actions([
            answer_plan(), source_plan(), context_read(), choose('b1'), {'action':'finish'}])
        self.assertEqual(result['trace'][0]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual([r['kind'] for r in result['coverage']], ['source_evidence'])
        self.assertFalse(any(i['kind']=='candidate_source_answer' for i in load_evidence_bundle(output)['items']))
        self.assertTrue(all(p['purpose']=='analysis_evidence' for p in planner.packets))
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')

    def test_catalog_without_original_body_cannot_complete_source_requirement(self):
        result, planner, output = self.run_actions([source_plan(),
            {'action':'discover_catalog', 'requirement_ids':['business'], 'catalog':{'kind':'sources'}},
            {'action':'finish'}])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(planner.packets[-1]['retained_body']['items'], [])
        self.assertFalse(load_evidence_bundle(output)['delivered_body'])

    def test_reread_refreshes_retained_body_order_without_recreating_evidence(self):
        state = {}
        def second(packet):
            state['first_id'] = packet['observation']['evidence_ids'][0]
            return context_read(block='b2')
        def reread(packet):
            state['second_id'] = packet['observation']['evidence_ids'][0]
            self.assertEqual(packet['retained_body']['items'][0]['block_id'], 'b2')
            return {'action':'reread', 'requirement_ids':['business'], 'evidence_ids':[state['first_id']]}
        def finish(packet):
            self.assertEqual([b['block_id'] for b in packet['retained_body']['items']][:2], ['b1','b2'])
            self.assertEqual(packet['retained_body']['items'][0]['context_evidence_id'], state['first_id'])
            self.assertFalse(packet['observation']['preview_truncated'])
            self.assertFalse(packet['observation']['receipt']['preview_truncated'])
            return choose('b1')(packet)
        result, _, output = self.run_actions([source_plan(), context_read(), second, reread, finish, {'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        contexts = [i['evidence_id'] for i in load_evidence_bundle(output)['items'] if i['kind']=='context']
        self.assertEqual(contexts,[state['first_id'],state['second_id']])

    def test_read_catalog_remembers_only_delivered_bodies_and_remains_navigation(self):
        def inspect(packet):
            catalog = packet['read_body_catalog']
            self.assertTrue(catalog['navigation_only'])
            self.assertLessEqual(len(json.dumps(catalog['items'], ensure_ascii=False).encode()), catalog['byte_limit'])
            self.assertEqual({row['block_id'] for row in catalog['items']}, {'b1'})
            row = catalog['items'][0]
            self.assertTrue(row['fully_delivered'])
            self.assertLessEqual(len(row['text_preview']), 160)
            self.assertEqual(row['context_id'], packet['retained_body']['items'][0]['context_evidence_id'])
            self.assertTrue(row['read_request']['pointer'].endswith('/text'))
            return choose('b1')(packet)
        result, _, _ = self.run_actions([source_plan(), context_read(),
            {'action':'discover_catalog', 'requirement_ids':['business'], 'catalog':{'kind':'sources'}},
            inspect, {'action':'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])

    def test_truncated_reread_flags_observation_and_receipt_without_crediting_body(self):
        folder = self.dataset / 'indexes/acme-annual'
        path = folder / 'blocks.jsonl'
        blocks = [json.loads(line) for line in path.read_text().splitlines()]
        blocks[1].update(type='table',text='Visible start ' + 'x'*4000 + ' UNREAD_END',
                         table={'rows': [[{'text':'cell ' + 'x'*100}] for _ in range(160)]})
        path.write_text(''.join(json.dumps(b)+'\n' for b in blocks))
        manifest_path=folder/'manifest.json';manifest=json.loads(manifest_path.read_text())
        manifest['artifacts']['blocks.jsonl']['sha256']=digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest));pin_dataset(self.dataset)
        def reread(packet):
            context = next(i for i in packet['evidence_index'] if i['kind']=='context')
            return {'action':'reread','requirement_ids':['business'],'evidence_ids':[context['evidence_id']]}
        def unfinished(packet):
            self.assertTrue(packet['observation']['preview_truncated'])
            self.assertTrue(packet['observation']['receipt']['preview_truncated'])
            self.assertFalse(packet['completion']['reference_checks_passed'])
            self.assertNotIn('b1', {r['block_id'] for r in packet['read_body_catalog']['items']})
            return {'action':'finish'}
        result, _, output = self.run_actions([source_plan(),context_read(),reread,unfinished],
            limits={'observation_bytes':1800})
        self.assertNotEqual(result['status'],'evidence_ready')
        receipt=json.loads((output/'turn-003/receipt.json').read_text())
        feedback=json.loads((output/'turn-003/feedback.json').read_text())
        self.assertTrue(receipt['preview_truncated'])
        self.assertTrue(feedback['preview_truncated'])

    def test_delegated_runtime_keeps_analysis_evidence_purpose(self):
        worker = ScriptedPlanner([context_read(),choose('b1'),{'action':'finish'}])
        result, _, output = self.run_actions([source_plan(),
            {'action':'delegate','requirement_ids':['business'],
             'delegation':{'instruction':'Read original evidence for Analysis; do not write conclusions.'}},
            context_read(),choose('b1'),{'action':'finish'}],worker=worker)
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertTrue(worker.packets)
        self.assertTrue(all(p['purpose']=='analysis_evidence' for p in worker.packets),
                        'The child runtime must not silently use question_answer.')
        config=json.loads((output/'turn-002/worker/config.json').read_text())
        self.assertEqual(config['prompt_version'],runtime_prompt_version('analysis_evidence'))

    def test_no_selection_cannot_complete_even_after_body_was_read(self):
        result, planner, output = self.run_actions([source_plan(),context_read(),{'action':'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertIn('delivery_selection_required', [u['reason'] for u in planner.packets[-1]['completion']['unmet']])
        self.assertEqual(result['coverage'][0]['selected_blocks'], [])
        packet = prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100_000,source_delivery='query_evidence_v1')
        self.assertIn('delivery_selection_missing:business',packet['program_gaps'])

    def test_metadata_only_plan_cannot_finish_analysis_evidence(self):
        actions=[{'action':'plan','reason':'Metadata fixture','requirements':[
            {'kind':'information','requirement_id':'business','description':'Inspect source catalog'}]},
            {'action':'discover_catalog','requirement_ids':['business'],'catalog':{'kind':'sources'}},
            {'action':'finish'}]
        result, planner, _ = self.run_actions(actions)
        self.assertNotEqual(result['status'],'evidence_ready')
        self.assertIn('analysis_evidence_requires_data_requirements',
                      [u['reason'] for u in planner.packets[-1]['completion']['unmet']])

    def test_select_rejects_unread_blocks_and_duplicate_selection_then_recovers(self):
        def unread(packet):
            choice=choose('b1')(packet)
            choice['delivery']['blocks'][0]['block_id']='b2'
            return choice
        def duplicate(packet):
            choice=choose('b1')(packet)
            choice['delivery']['blocks']*=2
            return choice
        result, _, _ = self.run_actions([source_plan(),context_read(),unread,duplicate,
                                         choose('b1'),{'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertEqual([result['trace'][i]['status'] for i in (2,3)],['rejected','rejected'])
        self.assertEqual([b['block_id'] for b in result['coverage'][0]['selected_blocks']],['b1'])

    def test_final_selection_replaces_exploration_but_handoff_preserves_atomic_context(self):
        result, _, output=self.run_actions([source_plan(),context_read(),choose('b1'),
            context_read(block='b8'),choose('b8'),{'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        packet=prepare_review_packet(output,self.dataset,expected_scope=self.scope,
            max_packet_bytes=100_000,source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'],[])
        self.assertEqual([f['value']['block_id'] for f in packet['facts']],['b8'])
        self.assertEqual({b['block_id'] for b in packet['source_documents'][0]['blocks']},{'b7','b8','b9'})
        self.assertNotIn('In 2031, acme invested',json.dumps(packet['source_documents']))
        bundle=load_evidence_bundle(output)
        self.assertTrue(any('b1' in bids for bids in bundle['delivered_body'].values()))
        first=json.loads((output/'turn-003/feedback.json').read_text())
        self.assertEqual(first['delivery_selection'][0]['block_id'],'b1')
        self.assertEqual(result['coverage'][0]['selected_blocks'][0]['block_id'],'b8')
        self.assertIn('Numbers in millions',json.dumps(packet['source_documents']))
        self.assertIn('exclude discontinued',json.dumps(packet['source_documents']))

    def test_resealed_selected_unread_block_cannot_enter_handoff(self):
        result, _, output=self.run_actions([source_plan(),context_read(),choose('b1'),{'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready')
        result['coverage'][0]['selected_blocks'][0]['block_id']='b2'
        (output/'result.json').write_text(json.dumps(result))
        pin_dataset(output)
        with self.assertRaisesRegex(ValueError,'selected delivery differs from fully read'):
            prepare_review_packet(output,self.dataset,expected_scope=self.scope,
                max_packet_bytes=100_000,source_delivery='query_evidence_v1')

    def test_coordinator_passes_purpose_to_both_managed_model_roles(self):
        managed = {}
        def factory(config, output, credential_root, *, role='planner', purpose='question_answer'):
            self.assertEqual(purpose,'analysis_evidence')
            actions=[source_plan(),context_read(),choose('b1'),{'action':'finish'}] if role=='planner' else []
            managed[role]=ManagedFixturePlanner(actions)
            return managed[role]
        config={'provider':'deepseek','model':'deepseek-flash','budget_ledger':str(self.root/'budget.sqlite'),
                'budget_usd':'1','budget_policy':'enforced','max_requests_total':10}
        coordinator=CompanyDataCoordinator(self.root/'workspace')
        with patch.object(CompanyDataCoordinator,'_planner',side_effect=factory) as constructor:
            result=asyncio.run(coordinator.query({**self.request,'dataset':str(self.dataset),
                'purpose':'analysis_evidence','limits':{'max_steps':4,'max_packet_bytes':64000}},
                output=self.root/'coordinator-run',model_config=config,worker_model_config=deepcopy(config),
                credential_root=self.root))
        self.assertEqual(result['status'],'evidence_ready',result)
        self.assertEqual(constructor.call_count,2)
        self.assertEqual(set(managed),{'planner','worker'})
        self.assertTrue(all(role.closed for role in managed.values()))
        self.assertFalse((self.root/'budget.sqlite').exists())


if __name__=='__main__':
    unittest.main()
