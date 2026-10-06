"""Public coordinator/CLI wiring; scripted decisions are not model quality evidence."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.agent_cli import register_agent_commands, run_agent_command
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_extraction_batches as batch_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


class CompanyFinancialTaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        fixture = batch_fixtures.ExtractionBatchTests()
        fixture.method(self.root)
        self.dataset, self.job = fixture.source(self.root/'source')
        manifest = json.loads((self.dataset/'manifest.json').read_text())
        self.scope = ExecutionScope(snapshot_id=manifest['snapshot_id'],
            company_ids=(self.job['company_id'],), source_snapshot_ids=(self.job['source_snapshot_id'],),
            source_policy_id=manifest['source_policy_id'], knowledge_cutoff=self.job['as_of'], include_candidates=True)
        self.task = {'task_id': 'explicit-annual-task', 'job': self.job, 'task_profile': 'task.json',
            'task_profile_sha256': digest((self.root/'task.json').read_bytes()), 'max_new_batches': 1}
        self.request = {'question': 'Produce candidate observations from the registered assets table.',
            'dataset': str(self.dataset), 'scope': self.scope.model_dump(mode='json'),
            'financial_tasks': [self.task], 'limits': {'max_steps': 3}}
        self.config = {'provider': 'deepseek', 'model': 'explicit-fixture-model',
            'budget_ledger': str(self.root/'ledger.sqlite'), 'budget_usd': None,
            'budget_policy': 'record_only', 'max_requests_total': None}
        self.coordinator = CompanyDataCoordinator(self.root/'workspace')

    async def fixture_extract(self, packet):
        tables = [block for block in packet['blocks'] if block['type'] == 'table']
        self.assertEqual(len(tables), 1)
        self.assertIn('Assets', tables[0]['text'])
        return {'records': [], 'relations': [], 'gaps': ['Offline routing fixture; no financial quality claim.']}

    def test_registered_task_is_called_by_agent_without_changing_baseline(self):
        selected = {}
        def plan(packet):
            tasks = packet['financial_tasks']
            task, = tasks
            selected['index'] = next(b['batch_index'] for b in task['batches'] if 'Assets' in b['source_excerpt'])
            return {'action': 'plan', 'reason': 'Select the source table matching this fixture task.',
                'requirements': [{'kind': 'financial_extract', 'requirement_id': 'produce-candidates',
                    'description': 'Run the registered assets batch.',
                    'financial_task_id': task['task_id'], 'batch_index': selected['index']}]}
        def extract(packet):
            return {'action': 'financial_extract', 'requirement_ids': ['produce-candidates'],
                'financial_extraction': {'task_id': self.task['task_id'], 'batch_index': selected['index']}}
        planner = ScriptedPlanner([plan, extract, {'action': 'finish'}])
        output = self.root/'query-run'
        before = digest((self.dataset/'manifest.json').read_bytes())
        result = asyncio.run(self.coordinator.query(self.request, planner=planner,
            financial_extractor=self.fixture_extract, extractor_model_config=self.config,
            method_root=self.root, credential_root=self.root, output=output))
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['dataset']['path'], str(self.dataset))
        self.assertEqual(result['active_scope'], self.scope.model_dump(mode='json'))
        self.assertEqual(digest((self.dataset/'manifest.json').read_bytes()), before)
        self.assertEqual(inspect_run(output)['status'], 'verified')
        child_result = json.loads((output/'query/result.json').read_text())
        self.assertEqual(child_result['semantic_completeness'], 'not_evaluated')
        row, = child_result['coverage']
        self.assertEqual(row['program_check'], 'candidate_batch_generated')
        decision = json.loads((output/'query/turn-002/decision.json').read_text())
        self.assertEqual(decision['financial_extraction']['batch_index'], selected['index'])

    def test_missing_execution_configuration_and_budget_split_fail_before_run(self):
        for kwargs in ({}, {'method_root': self.root},
                       {'method_root': self.root, 'extractor_model_config': self.config}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                asyncio.run(self.coordinator.query(self.request, planner=ScriptedPlanner([]),
                    output=self.root/'rejected', **kwargs))
            self.assertFalse((self.root/'rejected').exists())
        wrong = {**self.config, 'budget_ledger': str(self.root/'other-ledger.sqlite')}
        with self.assertRaisesRegex(ValueError, 'share the same budget'):
            asyncio.run(self.coordinator.query(self.request, model_config=self.config,
                extractor_model_config=wrong, method_root=self.root, credential_root=self.root,
                output=self.root/'split'))
        self.assertFalse((self.root/'split').exists())

    def test_unknown_extra_task_fields_duplicate_id_and_implicit_quota_rejected(self):
        for changes in ({'max_new_batches': None}, {'max_new_batches': True},
                        {'model': 'unselected-model'}, {'task_id': '../escape'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CompanyQueryInput.model_validate({**self.request, 'financial_tasks': [{**self.task, **changes}]})
        with self.assertRaisesRegex(ValueError, 'unique'):
            CompanyQueryInput.model_validate({**self.request, 'financial_tasks': [self.task, self.task]})

    def test_cli_passes_explicit_extractor_config_and_method_root(self):
        parser = argparse.ArgumentParser()
        register_agent_commands(parser.add_subparsers(dest='tool', required=True))
        for name, value in [('request.json', self.request), ('planner.json', self.config), ('extractor.json', self.config)]:
            (self.root/name).write_text(json.dumps(value))
        args = parser.parse_args(['agent', 'query', '--request', str(self.root/'request.json'),
            '--workspace', str(self.root/'workspace'), '--output', str(self.root/'new'),
            '--model-config', str(self.root/'planner.json'), '--extractor-model-config', str(self.root/'extractor.json'),
            '--method-root', str(self.root), '--credentials-root', str(self.root)])
        runner = AsyncMock(return_value={'status': 'fixture'})
        with patch.object(CompanyDataCoordinator, 'query', runner):
            self.assertEqual(run_agent_command(args), {'status': 'fixture'})
        self.assertEqual(runner.call_args.kwargs['extractor_model_config'], self.config)
        self.assertEqual(runner.call_args.kwargs['method_root'], self.root)


if __name__ == '__main__':
    unittest.main()
