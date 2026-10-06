import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from run_annual_report_spike import Report, Paragraph, Section, Citation, SECTIONS, compile_sources, validate_report
from uteki.agents.analysis_comparison import ToolSession
from uteki.agents.call_costs import MeteredModel, pricing_snapshot
from uteki.agents.local_credentials import load_aihubmix_key
from uteki.agents.narrative_runner import run_narrative
from uteki.agents.run_budget import RunBudget, BudgetExceeded, reserve_request
from uteki.agents.narrative_contract import AnnualNarrative
from uteki.agents.narrative_reader import compact_read


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_named_sections_are_required_and_convert_without_rewriting(self):
        p = dict(text='Unknown',kind='unknown',citations=[])
        payload = dict(title='Test',thesis=p,limitations=[],stop_reason='No data',
                       **{key:dict(title=key,paragraphs=[p]) for key in SECTIONS})
        report = AnnualNarrative.model_validate(payload)
        self.assertEqual([s['key'] for s in report.reading_payload()['sections']], list(SECTIONS))
        del payload['watch']
        with self.assertRaises(ValueError):
            AnnualNarrative.model_validate(payload)

    def test_compact_transport_keeps_source_text_and_nonempty_cells(self):
        block = dict(block_id='b',text='Entire text',style_signature={'font-size':'10px'},
                     table={'cells':[dict(row=0,column=0,text='',colspan=2,rowspan=1),
                                     dict(row=0,column=2,text='2025',colspan=1,rowspan=1)]})
        result = compact_read({'blocks':[block]})
        self.assertEqual(len(block['table']['cells']),2)
        compact = result['blocks'][0]
        self.assertEqual(compact['text'],block['text'])
        self.assertEqual(compact['table']['cells'],[block['table']['cells'][1]])
        self.assertEqual(compact['table']['columns'],3)
        self.assertNotIn('style_signature',compact)

    def test_shared_budget_and_unknown_fail_closed(self):
        budget = RunBudget(self.root/'budget.sqlite', '1')
        token = budget.reserve('.6')
        with self.assertRaises(BudgetExceeded):
            RunBudget(self.root/'budget.sqlite', '1').reserve('.5')
        budget.settle(token, '.2')
        pending = budget.reserve('.7')
        budget.settle(pending, None)
        with self.assertRaises(BudgetExceeded):
            budget.reserve('.01')
        self.assertEqual(budget.summary()['unknown_requests'], 1)
        with self.assertRaises(ValueError):
            RunBudget(self.root/'budget.sqlite', '10')

    def test_parallel_reservations_do_not_exceed_limit(self):
        budget = RunBudget(self.root/'budget.sqlite', '1')
        def attempt(_):
            try:
                budget.reserve('.6')
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(4))), 1)

    def test_budget_blocks_before_model_call(self):
        class Never:
            async def get_response(self, **kwargs):
                raise AssertionError('Must not invoke provider')
        budget = RunBudget(self.root/'budget.sqlite', '.00001')
        model = MeteredModel(Never(), self.root/'calls', 'test', 'aihubmix', 'gpt-5.4-mini',
                             pricing_snapshot('aihubmix','gpt-5.4-mini'), budget=budget)
        with self.assertRaises(BudgetExceeded):
            asyncio.run(model.get_response(input='test', model_settings=SimpleNamespace(max_tokens=100)))
        self.assertEqual(budget.summary()['requests'], 0)
        self.assertEqual(list((self.root/'calls').glob('*')), [])

    def test_credentials_are_private_and_never_executed(self):
        path = self.root/'.env'
        path.write_text('AIHUBMIX_API_KEY="test-key"\n')
        path.chmod(0o600)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_aihubmix_key(self.root), 'local_env_file')
            self.assertEqual(os.environ['AIHUBMIX_API_KEY'], 'test-key')
        path.chmod(0o644)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            load_aihubmix_key(self.root)
        path.chmod(0o600)
        path.write_text('AIHUBMIX_API_KEY=$(echo secret)\n')
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            load_aihubmix_key(self.root)

    def test_aihubmix_alias_is_loaded_and_conflicts_rejected(self):
        path = self.root / '.env'
        path.write_text('AI_HUB_MIX_API_KEY="test-alias"\n')
        path.chmod(0o600)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_aihubmix_key(self.root), 'local_env_file')
            self.assertEqual(os.environ['AIHUBMIX_API_KEY'], 'test-alias')
        with patch.dict(os.environ, {'AI_HUB_MIX_API_KEY': 'env-alias'}, clear=True):
            self.assertEqual(load_aihubmix_key(self.root), 'environment')
            self.assertEqual(os.environ['AIHUBMIX_API_KEY'], 'env-alias')
        path.write_text('AI_HUB_MIX_API_KEY=first\nAIHUBMIX_API_KEY=second\n')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'Conflicting'):
            load_aihubmix_key(self.root)

    def test_record_only_preserves_unknown_and_enforced_mode_still_blocks(self):
        path = self.root / 'budget.sqlite'
        budget = RunBudget(path, '1')
        token = budget.reserve('.5')
        budget.settle(token, None)
        observed = RunBudget(path, '1', enforce=False)
        token = observed.reserve('2')
        observed.settle(token, '.1')
        self.assertEqual(observed.summary()['requests'], 2)
        self.assertEqual(observed.summary()['unknown_requests'], 1)
        self.assertEqual(observed.summary()['enforcement'], 'record_only')
        with self.assertRaises(BudgetExceeded):
            budget.reserve('.01')

    def test_unlimited_record_only_preserves_large_and_unknown_costs_across_reopens(self):
        path = self.root/'unlimited.sqlite'
        first = RunBudget(path, None, enforce=False)
        unknown = first.reserve('1e30')
        first.settle(unknown, None)
        second = RunBudget(path, None, enforce=False)
        settled = second.reserve('1e40')
        second.settle(settled, '1234567890')
        summary = first.summary()
        self.assertIsNone(summary['limit_usd'])
        self.assertEqual(summary['enforcement'], 'record_only')
        self.assertEqual(summary['requests'], 2)
        self.assertEqual(summary['unknown_requests'], 1)
        self.assertEqual(Decimal(summary['held_usd']), Decimal('1e30'))
        self.assertEqual(Decimal(summary['estimated_spent_usd']), Decimal('1234567890'))
        self.assertIsNone(summary['actual_billed_usd'])
        self.assertEqual(RunBudget(path, None, enforce=False).summary(), summary)
        with closing(sqlite3.connect(path)) as connection:
            self.assertIsNone(connection.execute('SELECT usd FROM config WHERE id=1').fetchone()[0])

    def test_existing_ledger_cannot_change_between_finite_and_unlimited(self):
        for existing, proposed in (('1', None), (None, '1'), ('1', '2')):
            with self.subTest(existing=existing, proposed=proposed):
                path = self.root/f'budget-{existing}-{proposed}.sqlite'
                budget = RunBudget(path, existing, enforce=False)
                token = budget.reserve('.25')
                budget.settle(token, '.1')
                before = budget.summary()
                with self.assertRaisesRegex(ValueError, 'cannot be silently changed'):
                    RunBudget(path, proposed, enforce=False)
                self.assertEqual(budget.summary(), before)

    def test_unlimited_enforced_budget_rejected_before_filesystem_or_database_io(self):
        path = self.root/'not-created/budget.sqlite'
        with patch('uteki.agents.runtime.run_budget.Path.mkdir') as mkdir, \
                patch('uteki.agents.runtime.run_budget.sqlite3.connect') as connect:
            with self.assertRaisesRegex(ValueError, 'record-only'):
                RunBudget(path, None, enforce=True)
            mkdir.assert_not_called()
            connect.assert_not_called()
        self.assertFalse(path.parent.exists())

    def _run_fake(self, repair_valid=True):
        cited = Paragraph(text='A conditional claim', kind='inference', citations=[
            Citation(document_id='doc',index_id='idx',block_id='bad',quote='')])
        report = Report(title='Test',thesis=cited,sections=[Section(key=k,title=k,paragraphs=[
            cited.model_copy(deep=True)]) for k in SECTIONS],limitations=[],stop_reason='Done')
        session = ToolSession(self.root, {}, self.root)
        session.calls = 1
        session.evidence = {('doc','idx','good'):'actual source'}
        @dataclass
        class Usage:
            requests: int = 1
            input_tokens: int = 20
            output_tokens: int = 10
        class FakeRunner:
            calls = 0
            @classmethod
            async def run(cls, agent, value, **kwargs):
                cls.calls += 1
                answer = report.model_copy(deep=True)
                if cls.calls > 1 and repair_valid:
                    for p in [answer.thesis]+[p for s in answer.sections for p in s.paragraphs]:
                        p.citations[0].block_id = 'good'
                return SimpleNamespace(final_output=answer,context_wrapper=SimpleNamespace(usage=Usage()),
                                       to_input_list=lambda: [{'role':'user','content':'observed context'}])
        manifest = dict(max_tool_calls=20,max_tool_chars=10000,model='gpt-5.4-mini',provider='aihubmix',
            pricing_snapshot=pricing_snapshot('aihubmix','gpt-5.4-mini'),max_output_tokens=1000,max_turns=4,timeout_seconds=10)
        folder = self.root/'run'
        with patch('uteki.agents.narrative_runner.ToolSession', return_value=session):
            asyncio.run(run_narrative(self.root,manifest,folder,report_type=Report,prompt='test',question='q',
                compile_sources=compile_sources,validate_report=validate_report,
                budget=RunBudget(self.root/'b.sqlite','1'),runner=FakeRunner,model=object()))
        return folder, FakeRunner.calls

    def test_single_repair_retains_raw_and_diff(self):
        folder, calls = self._run_fake()
        result = json.loads((folder/'result.json').read_text())
        self.assertEqual(calls, 2)
        self.assertEqual(result['validation_errors'], [])
        self.assertEqual(result['repair_attempts'], 1)
        self.assertEqual(json.loads((folder/'raw-report.json').read_text())['thesis']['citations'][0]['block_id'], 'bad')
        self.assertEqual(result['report']['thesis']['citations'][0]['block_id'], 'good')
        self.assertEqual(result['semantic_review'], 'pending')
        self.assertFalse(result['automatic_adoption'])

    def test_failed_repair_does_not_loop(self):
        folder, calls = self._run_fake(False)
        self.assertEqual(calls, 2)
        result = json.loads((folder/'result.json').read_text())
        self.assertEqual(result['status'], 'invalid_citations_or_structure')
        self.assertTrue(result['validation_errors'])


if __name__ == '__main__':
    unittest.main()
