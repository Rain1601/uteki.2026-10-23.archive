"""Bounded mixed-role handoffs over scripted synthetic fixtures; no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import at_pointer, load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, plan, read
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes


def delegate(*requirement_ids, instruction='Read the assigned source and report gaps.'):
    return {'action': 'delegate', 'requirement_ids': list(requirement_ids or ('business',)),
            'delegation': {'instruction': instruction}}


def numeric_requirement():
    return {'action': 'plan', 'reason': 'Verify operating margin for the requested year.',
            'requirements': [{'kind': 'query', 'requirement_id': 'business',
                'description': 'Operating margin for 2031',
                'query': {'calculations': [{'formula_id': 'operating_margin',
                    'entity_id': 'acme-services', 'periods': [year(2031)]}]}}]}


def numeric_query(period=2031):
    return {'action': 'query', 'requirement_ids': ['business'],
            'plan': {'calculations': [{'formula_id': 'operating_margin',
                'entity_id': 'acme-services', 'periods': [year(period)]}]}}


class WaitingWorker:
    plan_origin = 'scripted_fixture'

    def __init__(self):
        self.packets = []
        self.started = asyncio.Event()

    async def decide(self, packet):
        self.packets.append(deepcopy(packet))
        self.started.set()
        await asyncio.Event().wait()


class AutonomousWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / 'dataset'
        dataset.mkdir()
        make_scoped_dataset(dataset)
        attach_synthetic_quotes(dataset)
        self.port = QueryDataPort(dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id,
            company_ids=('acme',), source_snapshot_ids=('acme-annual',),
            source_policy_id='local-frozen-v1', knowledge_cutoff='2032-05-01',
            include_candidates=True)
        self.request = {'question': 'Read business and show operating margin for 2031',
                        'scope': self.scope.model_dump(mode='json')}

    def make_agent(self, parent_actions, worker, *, limits=None):
        parent = ScriptedPlanner(parent_actions)
        agent = AutonomousDataAgent(self.port, parent, worker_planner=worker,
            limits={'max_steps': 16, **(limits or {})})
        return agent, parent

    def run_actions(self, parent_actions, child_actions, *, name='run', limits=None):
        worker = ScriptedPlanner(child_actions)
        agent, parent = self.make_agent(parent_actions, worker, limits=limits)
        output = self.root / name
        parent.output = output
        result = asyncio.run(agent.run(self.request, output=output))
        return result, parent, worker, output

    def worker_result(self, parent):
        observations = [packet.get('observation') or {} for packet in parent.packets]
        returned = [observation['result'] for observation in observations
                    if observation.get('status') == 'worker_returned']
        self.assertEqual(len(returned), 1)
        reference = returned[0]['full_handoff_ref']
        self.assertEqual(reference['kind'], 'worker_handoff_full')
        content = (parent.output / reference['path']).read_bytes()
        self.assertEqual(digest(content), reference['sha256'])
        return json.loads(content)

    def assert_sealed(self, folder):
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertIn('result.json', manifest['files'])
        for relative, expected in manifest['files'].items():
            self.assertEqual(digest((folder / relative).read_bytes()), expected, relative)
        return json.loads((folder / 'result.json').read_text())

    def assert_worker_sealed(self, output):
        child_results = [path for path in output.rglob('result.json')
                         if path.parent != output]
        self.assertEqual(len(child_results), 1, child_results)
        return self.assert_sealed(child_results[0].parent)

    def test_parent_verifies_worker_evidence_before_finishing(self):
        instruction = 'Look specifically for the products described in the business section.'
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate(instruction=instruction), read(), {'action': 'finish'}],
            [read(), {'action': 'finish'}], limits={'max_steps': 6})

        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        self.assertTrue(all(packet['role'] == 'planner' for packet in parent.packets))
        self.assertTrue(all(packet['available_worker'] for packet in parent.packets))
        self.assertTrue(all(packet['role'] == 'worker' for packet in worker.packets))
        first = worker.packets[0]
        self.assertEqual(first['request']['question'], self.request['question'])
        self.assertEqual(first['request']['scope'], self.request['scope'])
        self.assertEqual(first['active_scope'], self.request['scope'])
        self.assertEqual(first['delegation_instruction'], instruction)
        self.assertEqual([item['requirement_id'] for item in first['requirements']], ['business'])
        self.assertFalse(first['available_worker'])
        self.assertEqual(first['available_callbacks'], [])
        self.assertEqual(len(parent.packets) + len(worker.packets), 6)
        self.assertEqual(parent.packets[0]['steps_remaining'], 6)
        self.assertEqual(parent.packets[-1]['steps_remaining'], 1)

        handoff = self.worker_result(parent)
        self.assertEqual(handoff['status'], 'evidence_ready')
        self.assertEqual(handoff['requirement_ids'], ['business'])
        self.assertEqual(handoff['scope'], self.request['scope'])
        self.assertEqual(handoff['semantic_completeness'], 'not_evaluated')
        self.assertEqual(handoff['results']['status'], 'evidence_ready')
        self.assertTrue(handoff['worker_run'])
        self.assertTrue(handoff['evidence_bundle']['items'])
        self.assertEqual(parent.packets[2]['coverage'][0]['evidence_ids'], [])
        self.assertEqual(parent.packets[2]['evidence_index'], [])
        self.assertEqual(len(load_evidence_bundle(output)['items']), 1)
        self.assert_worker_sealed(output)
        self.assert_sealed(output)

    def test_worker_success_does_not_satisfy_parent_finish(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate(), {'action': 'finish'}, read(), {'action': 'finish'}],
            [read(), {'action': 'finish'}])
        finishes = [entry for entry in result['trace'] if entry['action'] == 'finish']
        self.assertEqual(finishes[0]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(len(worker.packets), 2)
        self.assertEqual(len(load_evidence_bundle(output)['items']), 1)

    def test_unknown_requirement_cannot_start_worker(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate('invented'), read(), {'action': 'finish'}], [])
        self.assertEqual(result['trace'][1]['status'], 'rejected')
        self.assertEqual(worker.packets, [])
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(list(output.rglob('result.json')), [output / 'result.json'])

    def test_worker_cannot_replan_acquire_materialize_or_delegate(self):
        prohibited = [plan('replacement'),
            {'action': 'acquire', 'requirement_ids': ['business'], 'arguments': {}},
            {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}},
            delegate()]
        for index, action in enumerate(prohibited):
            with self.subTest(action=action['action']):
                result, parent, worker, output = self.run_actions(
                    [plan('business'), delegate(), read(), {'action': 'finish'}],
                    [action, read(), {'action': 'finish'}], name=f'forbidden-{index}')
                handoff = self.worker_result(parent)
                self.assertEqual(handoff['results']['trace'][0]['status'], 'rejected')
                self.assertEqual(handoff['results']['active_scope'], self.request['scope'])
                self.assertEqual([row['requirement_id'] for row in handoff['results']['coverage']], ['business'])
                self.assertEqual(result['status'], 'evidence_ready')
                self.assert_worker_sealed(output)

    def test_worker_rejects_other_company_source_without_expanding_scope(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate(), read(), {'action': 'finish'}],
            [read(source='other-annual'), read(), {'action': 'finish'}])
        handoff = self.worker_result(parent)
        self.assertEqual(handoff['results']['trace'][0]['status'], 'rejected')
        self.assertEqual(handoff['scope'], self.request['scope'])
        self.assertTrue(all(item['scope'] == self.request['scope']
                            for item in handoff['evidence_bundle']['items']))
        self.assertEqual(result['status'], 'evidence_ready')

    def test_worker_cannot_reinterpret_required_numeric_period(self):
        result, parent, worker, output = self.run_actions(
            [numeric_requirement(), delegate(), numeric_query(), {'action': 'finish'}],
            [numeric_query(2030), numeric_query(), {'action': 'finish'}])
        handoff = self.worker_result(parent)
        self.assertEqual(handoff['results']['trace'][0]['status'], 'rejected')
        self.assertEqual(handoff['results']['coverage'][0]['program_check'], 'satisfied')
        self.assertEqual(result['status'], 'evidence_ready')
        computed = [item for item in load_evidence_bundle(output)['items'] if item['kind'] == 'computed']
        self.assertEqual(computed[0]['value']['display_decimal'], '15.00')

    def test_numeric_handoff_exposes_values_and_precise_reads_without_parent_credit(self):
        state = {}

        def inspect_summary(packet):
            self.assertEqual(packet['observation']['status'], 'worker_returned')
            summary = packet['observation']['result']
            self.assertEqual(summary['status'], 'evidence_ready')
            self.assertEqual(summary['scope'], self.request['scope'])
            self.assertEqual(summary['requirement_ids'], ['business'])
            full_ref = summary['full_handoff_ref']
            self.assertEqual(full_ref['kind'], 'worker_handoff_full')
            full = json.loads((self.root / 'run' / full_ref['path']).read_text())
            records = {row['metric_id']: row for row in summary['records']}
            self.assertEqual(set(records), {'revenue', 'operating_income'})
            for metric, value in [('revenue', '100'), ('operating_income', '15')]:
                row = records[metric]
                self.assertEqual(row['value_decimal'], value)
                self.assertEqual(row['unit'], 'USD')
                self.assertEqual(row['period'], year(2031))
                self.assertEqual(row['entity_id'], 'acme-services')
                self.assertEqual(row['accounting_basis'], 'reported_segment')
                self.assertEqual(row['source_snapshot_id'], 'acme-annual')
                request = row['full_read']
                self.assertEqual(request['artifact_id'], full_ref['artifact_id'])
                self.assertNotEqual(request['pointer'], '')
                original = at_pointer(full, request['pointer'])
                self.assertEqual(original['value_decimal'], value)
                self.assertEqual(original['record_id'], row['record_id'])
            self.assertTrue(summary['citations'])
            for citation in summary['citations']:
                self.assertEqual(citation['source_snapshot_id'], 'acme-annual')
                self.assertEqual(citation['block_id'], 'b9')
                self.assertTrue(citation['quote'])
                request = citation['full_read']
                self.assertEqual(request['artifact_id'], full_ref['artifact_id'])
                self.assertEqual(at_pointer(full, request['pointer'])['quote'], citation['quote'])
            self.assertIn('delivered_body', summary['body_read_status'])
            self.assertIs(summary['body_read_status']['candidate_only'], True)
            self.assertEqual(packet['coverage'][0]['evidence_ids'], [])
            self.assertEqual(packet['evidence_index'], [])
            self.assertIs(packet['completion']['reference_checks_passed'], False)
            self.assertEqual(packet['completion']['semantic_completeness'], 'not_evaluated')
            delegation, = packet['delegations']
            preview_records = delegation['findings_preview']['value']['records']
            self.assertEqual({row['metric_id']: row['value_decimal'] for row in preview_records},
                             {'revenue': '100', 'operating_income': '15'})
            state['summary'] = deepcopy(summary)
            state['delegation'] = deepcopy(delegation)
            return numeric_query()

        def finish(packet):
            self.assertEqual(packet['delegations'], [state['delegation']])
            self.assertIs(packet['completion']['reference_checks_passed'], True)
            return {'action': 'finish'}

        result, parent, _, output = self.run_actions(
            [numeric_requirement(), delegate(), inspect_summary, finish],
            [numeric_query(), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        handoff = self.worker_result(parent)
        self.assertEqual(handoff['status'], 'evidence_ready')
        artifacts = json.loads((output / 'artifact-index.json').read_text())
        summary_ref = next(item for item in artifacts
                           if item['artifact_id'] == state['delegation']['handoff_artifact_id'])
        self.assertEqual(summary_ref['kind'], 'worker_handoff')
        self.assertEqual(json.loads((output / summary_ref['path']).read_text()), state['summary'])
        own_records = [item for item in load_evidence_bundle(output)['items'] if item['kind'] == 'record']
        self.assertEqual({item['value']['record_id'] for item in own_records},
                         {'acme-annual-revenue-2031', 'acme-annual-operating_income-2031'})

    def test_parent_and_worker_cannot_exceed_total_decision_limit(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate(), {'action': 'finish'}, read(), {'action': 'finish'}],
            [read(), {'action': 'finish'}], limits={'max_steps': 4})
        self.assertEqual(len(parent.packets) + len(worker.packets), 4)
        self.assertEqual(len(parent.packets), 3)
        self.assertEqual(len(worker.packets), 1)
        self.assertEqual(parent.packets[-1]['steps_remaining'], 1)
        self.assertEqual(result['decision_budget'], {'limit': 4, 'used': 4})
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(load_evidence_bundle(output)['items'], [])
        self.assert_worker_sealed(output)
        self.assert_sealed(output)

    def test_worker_step_limit_returns_partial_work_for_parent_verification(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), delegate(), read(), {'action': 'finish'}],
            [read(), {'action': 'finish'}], limits={'max_worker_steps': 1})
        self.assertEqual(len(worker.packets), 1)
        handoff = self.worker_result(parent)
        self.assertNotEqual(handoff['status'], 'evidence_ready')
        self.assertTrue(handoff['evidence_bundle']['items'])
        self.assertEqual(result['status'], 'evidence_ready')

    def test_repeated_delegation_cannot_invent_progress(self):
        result, parent, worker, output = self.run_actions(
            [plan('business'), *[delegate(instruction=f'Recheck the same section, attempt {i}.') for i in range(8)],
             read(), {'action': 'finish'}],
            [action for _ in range(8) for action in (read(), {'action': 'finish'})],
            limits={'max_steps': 40})
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertLess(len(parent.packets), 10)
        self.assertFalse(any(entry['action'] == 'read_source' for entry in result['trace']))
        self.assertEqual(load_evidence_bundle(output)['items'], [])

    def test_worker_timeout_is_sealed_and_parent_can_continue(self):
        worker = WaitingWorker()
        agent, parent = self.make_agent(
            [plan('business'), delegate(), read(), {'action': 'finish'}], worker,
            limits={'worker_timeout': 0.02, 'turn_timeout': 5})
        output = self.root / 'timeout'
        result = asyncio.run(agent.run(self.request, output=output))
        self.assertEqual(parent.packets[2]['observation']['status'], 'worker_timeout')
        self.assertEqual(result['status'], 'evidence_ready')
        child_result = self.assert_worker_sealed(output)
        self.assertIn(child_result['status'], {'cancelled', 'failed'})
        self.assert_sealed(output)

    def test_worker_error_is_sealed_and_parent_can_continue(self):
        class BrokenWorker(ScriptedPlanner):
            async def decide(self, packet):
                self.packets.append(deepcopy(packet))
                raise RuntimeError('Synthetic worker failure')

        worker = BrokenWorker([])
        agent, parent = self.make_agent(
            [plan('business'), delegate(), read(), {'action': 'finish'}], worker)
        output = self.root / 'failure'
        result = asyncio.run(agent.run(self.request, output=output))
        self.assertEqual(parent.packets[2]['observation']['status'], 'worker_failed')
        self.assertEqual(result['status'], 'evidence_ready')
        self.assertEqual(self.assert_worker_sealed(output)['status'], 'failed')
        self.assert_sealed(output)

    def test_parent_cancellation_seals_both_runs_and_propagates(self):
        worker = WaitingWorker()
        agent, parent = self.make_agent([plan('business'), delegate()], worker,
                                        limits={'worker_timeout': 10, 'turn_timeout': 10})
        output = self.root / 'cancelled'

        async def run():
            task = asyncio.create_task(agent.run(self.request, output=output))
            try:
                await asyncio.wait_for(worker.started.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())
        self.assertEqual(self.assert_worker_sealed(output)['status'], 'cancelled')
        self.assertEqual(self.assert_sealed(output)['status'], 'cancelled')
        self.assertEqual(len(parent.packets), 2)
        self.assertEqual(len(worker.packets), 1)


if __name__ == '__main__':
    unittest.main()
