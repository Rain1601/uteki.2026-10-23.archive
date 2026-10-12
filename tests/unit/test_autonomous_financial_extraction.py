"""Scripted Agent-loop boundary checks; no real model or financial-quality claims."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from uteki.agents.data_query.autonomous import (AutonomousDataAgent, AutonomousDecision, Requirement,
    runtime_prompt, runtime_prompt_version)
from uteki.agents.data_query.autonomous_model import _decision_validation_hints
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import pin_dataset


def financial_requirement(batch=0, *, task='selected-annual', rid='extract-table'):
    return {'kind': 'financial_extract', 'requirement_id': rid,
            'description': 'Generate candidates for the explicitly selected table.',
            'financial_task_id': task, 'batch_index': batch}


def plan(*requirements):
    return {'action': 'plan', 'reason': 'Select the table matching the request.', 'requirements': list(requirements)}


def extract(batch=0, *, task='selected-annual', rid='extract-table', method=None):
    return {'action': 'financial_extract', 'requirement_ids': [rid],
            'financial_extraction': {'task_id': task, 'batch_index': batch, 'method_id': method}}


class AutonomousFinancialExtractionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        for sid in ('acme-annual', 'other-annual'):
            path = self.dataset / 'indexes' / sid / 'blocks.jsonl'
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            blocks[9].update(type='table', text='Cash flows for 2031: Operating cash flow 20',
                             table={'rows': [[{'text': 'Operating cash flow'}, {'text': '20'}]]})
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest_path = path.parent / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.dataset)
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Extract candidates from the annual cash-flow table.',
                        'scope': self.scope.model_dump(mode='json')}
        self.task = self.make_task()
        self.calls = []

    def make_task(self, company='acme', source='acme-annual'):
        return {'task_id': 'selected-annual', 'task_type': 'annual-financial-extraction',
                'company_id': company, 'source_snapshot_id': source, 'source_sha256': digest(source),
                'dataset_manifest_sha256': digest((self.dataset / 'manifest.json').read_bytes()),
                'catalog_id': 'source-tables-fixture', 'task': 'Extract the registered financial tables.',
                'default_method_id': 'fixture-v1', 'allowed_method_ids': ['fixture-v1', 'fixture-v2'],
                'max_new_batches': 1,
                'batches': [{'batch_index': i, 'table_block_id': bid, 'source_excerpt': excerpt,
                             'block_ids': [bid], 'status': 'pending'}
                            for i, bid, excerpt in ((0, 'b8', 'Sales 100'),
                                                   (1, 'b9', 'Cash flows for 2031: Operating cash flow 20'))],
                'limits': ['Fixture catalog only; no model-quality claim.']}

    async def callback(self, arguments, *, scope, output):
        self.calls.append({'arguments': deepcopy(arguments), 'scope': scope.model_dump(mode='json'),
                           'output': str(output)})
        return {'status': 'candidate', 'task_id': arguments['task_id'], 'batch_index': arguments['batch_index'],
                'catalog_id': self.task['catalog_id'], 'method_id': arguments['method_id'] or self.task['default_method_id'],
                'method_sha256': digest('fixture-method'),
                'run': {'path': str(output), 'manifest_sha256': digest('fixture-run-manifest')},
                'dataset': {'path': str(output / 'candidate-dataset'), 'snapshot_id': 'separate-candidate',
                            'manifest_sha256': digest('fixture-candidate-manifest')},
                'raw_record_count': 2, 'normalized_record_count': 1, 'unresolved_count': 1,
                'gaps': [{'reason': 'One draft has unresolved mapping.'}], 'adoption': 'unchanged_candidate',
                'semantic_acceptance': 'not_evaluated', 'candidate_only': True}

    def run_actions(self, actions, *, name='run', tasks=None, callback=None, worker=None, request=None):
        planner = ScriptedPlanner(actions)
        agent = AutonomousDataAgent(self.port, planner, financial_tasks=tasks if tasks is not None else [self.task],
            financial_extract=callback or self.callback, worker_planner=worker,
            limits={'max_steps': len(actions) + (6 if worker else 0), 'turn_timeout': 300})
        output = self.root / name
        result = asyncio.run(agent.run(request or self.request, output=output))
        return result, planner, output

    def test_contract_rejects_unrelated_payload_and_implicit_batch(self):
        required = financial_requirement()
        for invalid in ({k: v for k, v in required.items() if k != 'financial_task_id'},
                        {k: v for k, v in required.items() if k != 'batch_index'},
                        dict(required, kind='information'), dict(required, batch_index=True),
                        dict(required, source_id='acme-annual'), dict(required, batch_index=-1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                Requirement.model_validate(invalid)
        for invalid in (dict(extract(), arguments={}), dict(extract(), plan={'queries': []}),
                        dict(extract(), action='finish'), dict(extract(), financial_extraction={
                            'task_id': 'selected-annual', 'batch_index': 0, 'job': {'company_id': 'other'}})):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                AutonomousDecision.model_validate(invalid)
        hint = _decision_validation_hints(json.dumps(plan({k: v for k, v in required.items() if k != 'batch_index'})))
        self.assertTrue(any(item.get('rule') == 'financial_requirement_task_batch' for item in hint))

    def test_planner_selects_batch_and_candidate_stays_outside_baseline(self):
        original = (self.dataset / 'manifest.json').read_bytes()
        def select(packet):
            task = packet['financial_tasks'][0]
            chosen = next(batch for batch in task['batches'] if 'Cash flows' in batch['source_excerpt'])
            return plan(financial_requirement(chosen['batch_index'], task=task['task_id']))
        def invoke(packet):
            requirement = packet['requirements'][0]
            return extract(requirement['batch_index'], task=requirement['financial_task_id'])
        result, planner, output = self.run_actions([select, invoke, {'action': 'finish'}])
        self.assertEqual(result['status'], 'candidate_ready')
        self.assertEqual(result['coverage'][0]['program_check'], 'candidate_batch_generated')
        self.assertEqual(self.calls[0]['arguments']['batch_index'], 1)
        self.assertEqual(self.calls[0]['scope'], self.scope.model_dump(mode='json'))
        self.assertEqual(result['active_scope'], self.scope.model_dump(mode='json'))
        self.assertEqual((self.dataset / 'manifest.json').read_bytes(), original)
        self.assertTrue(planner.packets[0]['available_financial_extract'])
        self.assertEqual(planner.packets[-1]['financial_tasks'][0]['batches'][1]['status'], 'candidate')
        bundle = load_evidence_bundle(output)
        self.assertEqual(bundle['delivered_body'], {})
        self.assertEqual(bundle['scope_history'], [])
        self.assertEqual(len(bundle['items']), 1)
        item = bundle['items'][0]
        self.assertEqual(item['kind'], 'candidate_financial_extraction')
        self.assertEqual(item['value']['source_snapshot_id'], 'acme-annual')
        self.assertEqual(item['value']['dataset']['snapshot_id'], 'separate-candidate')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        self.assertTrue(result['financial_extractions'][0]['candidate_only'])
        config = json.loads((output / 'config.json').read_text())
        self.assertEqual(config['prompt_version'], runtime_prompt_version())
        self.assertIn('host-registered extraction tasks', runtime_prompt('planner', 'question_answer'))

    def test_missing_scope_rejected_before_planner(self):
        with self.assertRaises(ValueError):
            self.run_actions([], request={'question': 'Extract the annual table.'})
        self.assertFalse(self.calls)
        self.assertFalse((self.root / 'run').exists())

    def test_cross_company_source_snapshot_and_future_period_rejected_before_planning(self):
        cases = [dict(self.task, company_id='other'), dict(self.task, source_snapshot_id='other-annual'),
                 dict(self.task, source_sha256=digest('wrong-source')),
                 dict(self.task, dataset_manifest_sha256=digest('other-snapshot'))]
        for index, task in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.run_actions([], tasks=[task], name=f'invalid-{index}')
        future_scope = self.scope.model_copy(update={'source_snapshot_ids': ('acme-future',)})
        with self.assertRaises(ValueError):
            self.run_actions([], tasks=[self.make_task(source='acme-future')], name='future',
                request={'question': 'Extract future filing.', 'scope': future_scope.model_dump(mode='json')})
        self.assertFalse(self.calls)

    def test_other_company_can_use_same_flow_with_explicit_scope(self):
        self.task = self.make_task(company='other', source='other-annual')
        other_scope = self.scope.model_copy(update={'company_ids': ('other',), 'source_snapshot_ids': ('other-annual',)})
        result, _, output = self.run_actions([plan(financial_requirement(1)), extract(1), {'action': 'finish'}],
            request={'question': 'Extract the other company cash-flow table.', 'scope': other_scope.model_dump(mode='json')})
        self.assertEqual(result['status'], 'candidate_ready')
        self.assertEqual(load_evidence_bundle(output)['items'][0]['value']['company_id'], 'other')
        self.assertEqual(self.calls[0]['scope']['company_ids'], ['other'])

    def test_unknown_task_or_batch_cannot_enter_plan(self):
        for index, requirement in enumerate((financial_requirement(task='unknown'), financial_requirement(99))):
            result, _, _ = self.run_actions([plan(requirement)], name=f'unknown-{index}')
            self.assertEqual(result['trace'][0]['status'], 'rejected')
            self.assertEqual(result['coverage'], [])
        self.assertFalse(self.calls)

    def test_action_must_match_declared_task_batch_and_allowed_method(self):
        for index, action in enumerate((extract(1), extract(task='unknown'), extract(method='outside-policy'))):
            result, _, output = self.run_actions([plan(financial_requirement()), action, {'action': 'finish'}],
                                                 name=f'mismatch-{index}')
            self.assertEqual(result['trace'][1]['status'], 'rejected')
            self.assertEqual(result['status'], 'limited')
            self.assertFalse(load_evidence_bundle(output)['items'])
        self.assertFalse(self.calls)

    def test_callback_gap_or_failure_does_not_complete_batch(self):
        async def unavailable(*args, **kwargs):
            return {'status': 'gap', 'gaps': [{'reason': 'Model unavailable.'}]}
        result, _, output = self.run_actions([plan(financial_requirement()), extract(), {'action': 'finish'}],
                                             callback=unavailable)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage'][0]['program_check'], 'candidate_financial_batch_missing')
        self.assertFalse(load_evidence_bundle(output)['items'])
        async def failed(*args, **kwargs):
            raise RuntimeError('synthetic provider failure')
        result, _, _ = self.run_actions([plan(financial_requirement()), extract()], callback=failed, name='failed')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['financial_extractions'])
        self.assertTrue(result['gaps'])

    def test_wrong_receipt_identity_and_adoption_are_rejected(self):
        changes = [{'task_id': 'wrong'}, {'batch_index': 1}, {'catalog_id': 'wrong'},
                   {'company_id': 'other'}, {'source_snapshot_id': 'other-annual'},
                   {'method_id': 'fixture-v2'}, {'adoption': 'adopted'}, {'candidate_only': False},
                   {'semantic_acceptance': 'approved'}, {'method_sha256': 'unfrozen'}]
        for index, changed in enumerate(changes):
            async def wrong(arguments, *, scope, output, changed=changed):
                return {**await self.callback(arguments, scope=scope, output=output), **changed}
            result, _, output = self.run_actions([plan(financial_requirement()), extract(), {'action': 'finish'}],
                                                 callback=wrong, name=f'wrong-{index}')
            self.assertEqual(result['trace'][1]['status'], 'rejected')
            self.assertFalse(load_evidence_bundle(output)['items'])
            self.assertEqual(result['coverage'][0]['program_check'], 'candidate_financial_batch_missing')

    def test_candidate_cannot_satisfy_numeric_or_source_read_requirement(self):
        self.request['question'] = 'Extract and read the table, then retrieve operating margin for 2031.'
        numeric = {'kind': 'query', 'requirement_id': 'numeric', 'description': 'Retrieve reported revenue.',
                   'query': {'calculations': [{'formula_id': 'operating_margin', 'entity_id': 'acme-services',
                                              'periods': [year(2031)]}]}}
        source = {'kind': 'source_evidence', 'requirement_id': 'read', 'description': 'Read original table.',
                  'source_id': 'acme-annual'}
        def attach_to_others(packet):
            return {'action': 'reread', 'requirement_ids': ['numeric', 'read'],
                    'evidence_ids': packet['observation']['evidence_ids']}
        result, _, _ = self.run_actions([plan(financial_requirement(), numeric, source), extract(), attach_to_others,
                                         {'action': 'finish'}])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        rows = {row['requirement_id']: row for row in result['coverage']}
        self.assertEqual(rows['extract-table']['program_check'], 'candidate_batch_generated')
        self.assertNotEqual(rows['numeric']['program_check'], 'satisfied')
        self.assertEqual(rows['read']['program_check'], 'source_body_not_delivered')

    def test_unrelated_source_receipt_cannot_complete_financial_requirement(self):
        result, _, _ = self.run_actions([plan(financial_requirement()),
            {'action': 'read_source', 'requirement_ids': ['extract-table'],
             'read': {'source_snapshot_id': 'acme-annual', 'node_id': 'notes', 'count': 3}}, {'action': 'finish'}])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(result['coverage'][0]['program_check'], 'candidate_financial_batch_missing')
        self.assertFalse(self.calls)

    def test_financial_requirement_cannot_be_delegated_to_evidence_worker(self):
        worker = ScriptedPlanner([])
        result, _, _ = self.run_actions([plan(financial_requirement()),
            {'action': 'delegate', 'requirement_ids': ['extract-table'],
             'delegation': {'instruction': 'Extract this table.'}}, {'action': 'finish'}], worker=worker)
        self.assertEqual(result['trace'][1]['status'], 'rejected')
        self.assertFalse(worker.packets)
        self.assertFalse(self.calls)


if __name__ == '__main__':
    unittest.main()
