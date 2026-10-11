"""Information availability is not the fiscal observation period; no live calls."""
import asyncio
from datetime import date
from pathlib import Path
import tempfile
import unittest
from uteki.domain.research_data.period_scope import explicit_periods
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes


class CutoffRolesTests(unittest.TestCase):
    def periods(self, text, cutoff='2032-05-01', mapping=None):
        return explicit_periods(text, knowledge_cutoff=cutoff, require_fiscal_mapping=True,
            fiscal_periods=mapping if mapping is not None else [{'fiscal_year':2031,'period':{
                'kind':'year','start':'2030-07-01','end':'2031-06-30','basis':'source'}}])

    def test_cutoff_clause_and_fiscal_period_have_separate_roles(self):
        for prefix in ('以2032-05-01为资料可得截止日，', '资料截止日期：2032-05-01，',
                       'Information available as of 2032-05-01, ', 'information cutoff: 2032-05-01, '):
            with self.subTest(prefix=prefix):
                p, = self.periods(prefix+'FY2031 revenue')
                self.assertEqual((str(p.start),str(p.end)),('2030-07-01','2031-06-30'))
        self.assertEqual(self.periods('Information available as of 2032-05-01, FY2031 revenue',date(2032,5,1)),
                         self.periods('FY2031 revenue'))

    def test_missing_mismatched_invalid_cutoff_and_unsupported_ranges_still_reject(self):
        for text, cutoff in [
            ('Information available as of 2032-05-01, FY2031 revenue',None),
            ('Information available as of 2032-05-02, FY2031 revenue','2032-05-01'),
            ('Information available as of 2032-02-30, FY2031 revenue','2032-05-01'),
            ('Information available as of 2032-05-01 and information available as of 2032-05-02, FY2031 revenue','2032-05-01'),
            ('Information available as of 2032-05-01, FY2031 YTD revenue','2032-05-01'),
            ('Information available as of 2032-05-01, revenue from 2031-01-01 to 2031-06-30','2032-05-01'),
            ('以2032-05-01为起点的FY2031收入','2032-05-01'),
            ('FY2031 debt balance as of 2032-05-01','2032-05-01'),
            ('以2032-05-01为截止日期的应收账款，FY2031对照','2032-05-01'),
            ('information cutoff: 2032-05-01T12:00:00 FY2031 revenue','2032-05-01'),
            ('Information available as of 2032-05-01, revenue','2032-05-01'),
        ]:
            with self.subTest(text=text):self.assertEqual(self.periods(text,cutoff),())
        self.assertEqual(self.periods('Information available as of 2032-05-01, FY2031 revenue',mapping=[]),())
        conflict=[{'fiscal_year':2031,'period':year(2031)}]
        self.assertEqual(self.periods('Information available as of 2032-05-01, FY2030 revenue',mapping=conflict),())

    def test_availability_role_without_material_noun_keeps_each_fiscal_calendar(self):
        alternate = [{'fiscal_year':2031,'period':year(2031)}]
        for prefix in ('以2032-05-01为可得截止日，', '以2032-05-01为可用截止日期，',
                       '可得截止日为2032-05-01，', '可用截止日期：2032-05-01，'):
            with self.subTest(prefix=prefix):
                source, = self.periods(prefix+'FY2031 revenue')
                calendar, = self.periods(prefix+'FY2031 revenue',mapping=alternate)
                self.assertEqual((str(source.start),str(source.end)),('2030-07-01','2031-06-30'))
                self.assertEqual((str(calendar.start),str(calendar.end)),('2031-01-01','2031-12-31'))
                self.assertEqual(self.periods(prefix+'FY2031 revenue',mapping=[]),())

    def test_short_availability_clause_cannot_override_or_supply_period(self):
        for text, cutoff in (
            ('以2032-05-01为可得截止日，FY2031 revenue',None),
            ('以2032-05-02为可得截止日，FY2031 revenue','2032-05-01'),
            ('可用截止日期：2032-02-30，FY2031 revenue','2032-05-01'),
            ('以2032-05-01为可得截止日，资料截止日为2032-05-02，FY2031 revenue','2032-05-01'),
            ('以2032-05-01为可得截止日，revenue','2032-05-01'),
            ('以2032-05-01为可得截止日，FY2031 YTD revenue','2032-05-01'),
            ('以2032-05-01为可得截止日，FY2031 debt as of 2031-06-30','2032-05-01'),
            ('以2032-05-01为截止日，FY2031 revenue','2032-05-01'),
            ('不可得截止日期：2032-05-01，FY2031 revenue','2032-05-01'),
            ('未可用截止日为2032-05-01，FY2031 revenue','2032-05-01'),
            ('非可得截止日期：2032-05-01，FY2031 revenue','2032-05-01'),
            ('无资料可得截止日期：2032-05-01，FY2031 revenue','2032-05-01'),
            ('非材料 可用截止日期：2032-05-01，FY2031 revenue','2032-05-01'),
            ('不以2032-05-01为可得截止日，FY2031 revenue','2032-05-01'),
            ('identifier_可得截止日期：2032-05-01，FY2031 revenue','2032-05-01'),
        ):
            with self.subTest(text=text):self.assertEqual(self.periods(text,cutoff),())

    def test_autonomous_plan_uses_immutable_cutoff_and_keeps_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dataset=root/'dataset';dataset.mkdir();make_scoped_dataset(dataset);attach_synthetic_quotes(dataset)
            with QueryDataPort(dataset) as port:
                scope=ExecutionScope(snapshot_id=port.snapshot_id,company_ids=('acme',),source_snapshot_ids=('acme-annual',),
                    source_policy_id='local-frozen-v1',knowledge_cutoff='2032-05-01',include_candidates=True)
                actions=[{'action':'load_skill','skill':'query'},{'action':'plan','reason':'Explicit independent synthetic scope',
                    'requirements':[{'kind':'query','requirement_id':'revenue','description':'Year revenue',
                        'query':{'records':[{'entity_id':'acme-services','metric_id':'revenue','period':year(2031)}]}}]}]
                for n,(prefix,cutoff) in enumerate((('资料可得','2032-05-01'),('可得','2032-05-01'),
                                                     ('可用','2032-05-01'),('可得','2032-05-02'))):
                    agent=AutonomousDataAgent(port,ScriptedPlanner(actions),limits={'max_steps':2},purpose='analysis_evidence')
                    result=asyncio.run(agent.run({'question':f'以{cutoff}为{prefix}截止日，查询2031年收入',
                        'scope':scope.model_dump(mode='json')},output=root/f'run{n}'))
                    self.assertEqual(bool(result['plans']),cutoff=='2032-05-01')
                    if cutoff!='2032-05-01':self.assertEqual(result['trace'][-1]['status'],'rejected')
