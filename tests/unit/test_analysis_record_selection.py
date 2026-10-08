"""Explicit original-record delivery, independent synthetic data and no models."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AutonomousDataAgent, AutonomousDecision
from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.runtime.claude_messages import decode_decision_envelope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes


def criterion(year_value=2031, entity='acme-services'):
    return {'entity_id': entity, 'metric_id': 'revenue', 'period': year(year_value)}


def plan(records, rid='revenue'):
    return {'action': 'plan', 'reason': 'Retrieve explicit record criteria.', 'requirements': [
        {'kind': 'query', 'requirement_id': rid, 'description': 'Original reported revenue.', 'query': {'records': records}}]}


def query(records, rid='revenue'):
    return {'action': 'query', 'requirement_ids': [rid], 'plan': {'records': records}}


class AnalysisRecordSelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.dataset = self.root/'dataset'; self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        # Same value disclosed twice; neither is silently deleted during query.
        db = duckdb.connect(str(self.dataset/'research.duckdb'))
        original = list(db.execute("SELECT * FROM observations WHERE record_id = 'acme-annual-revenue-2031'").fetchone())
        duplicate = json.loads(original[-1]); duplicate['record_id'] += '-second-disclosure'
        duplicate['evidence_ids'] = [duplicate['record_id']]
        original[0], original[-1] = duplicate['record_id'], json.dumps(duplicate)
        db.execute('INSERT INTO observations VALUES (' + ','.join('?' for _ in original) + ')', original)
        db.execute('INSERT INTO evidence VALUES (?, ?, ?)', [duplicate['record_id'], 'acme-annual',
            json.dumps({'evidence_id': duplicate['record_id'], 'source_snapshot_id': 'acme-annual', 'quote': '100'})])
        db.close(); attach_synthetic_quotes(self.dataset)
        self.scope = {'snapshot_id': 'synthetic-scoped-v1', 'company_ids': ['acme'],
            'source_snapshot_ids': ['acme-annual'], 'source_policy_id': 'local-frozen-v1',
            'knowledge_cutoff': '2032-05-01', 'include_candidates': True}
        self.request = {'question': 'Retrieve revenue for 2030 and for 2031.', 'scope': self.scope}
        self.records = {}

    def select(self, predicate=lambda r: True, *, rid='revenue', raw_ids=None):
        def action(packet):
            for r in packet.get('observation', {}).get('result', {}).get('records', []):
                eid = 'ev-' + digest({'kind': 'record', 'value': r, 'scope': packet['active_scope']})[:24]
                self.records[eid] = r
            ids = raw_ids if raw_ids is not None else [eid for eid, r in self.records.items() if predicate(r)]
            return {'action': 'select_records', 'requirement_ids': [rid],
                'record_selection': {'record_ids': ids}, 'reason': 'Deliver required records without repeated disclosures.'}
        return action

    def run_actions(self, actions, **kwargs):
        planner = ScriptedPlanner(actions)
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                limits={'max_steps': len(actions), 'max_packet_bytes': 128000, 'observation_bytes': 32000},
                **kwargs).run(self.request, output=self.root/'run'))
        return result, planner

    def test_trim_duplicate_and_replace_preserves_original_query_and_selection_audit(self):
        records = [criterion(2030), criterion(2031)]
        result, _ = self.run_actions([plan(records), query(records), self.select(),
            self.select(lambda r: not r['record_id'].endswith('second-disclosure')), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(len(result['coverage'][0]['selected_record_ids']), 2)
        bundle = load_evidence_bundle(self.root/'run')
        self.assertEqual(sum(i['kind'] == 'record' for i in bundle['items']), 3)
        first = json.loads((self.root/'run/turn-003/feedback.json').read_text())
        second = json.loads((self.root/'run/turn-004/feedback.json').read_text())
        self.assertEqual(len(first['selected_record_ids']), 3)
        self.assertEqual(len(second['selected_record_ids']), 2)

    def test_finish_requires_selection_after_successful_numeric_query(self):
        records = [criterion()]
        result, planner = self.run_actions([plan(records), query(records), {'action': 'finish'}])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertIn('record_selection_required', [x['reason'] for x in planner.packets[-1]['completion']['unmet']])
        self.assertEqual(result['coverage'][0]['selected_record_ids'], [])

    def test_cannot_drop_declared_year_then_can_recover(self):
        records = [criterion(2030), criterion(2031)]
        result, _ = self.run_actions([plan(records), query(records),
            self.select(lambda r: r['period']['end'] == '2031-12-31'), self.select(), {'action': 'finish'}])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready')

    def test_unknown_and_original_record_ids_rejected(self):
        records = [criterion()]
        result, _ = self.run_actions([plan(records), query(records),
            self.select(raw_ids=['ev-unqueried']), self.select(raw_ids=['acme-annual-revenue-2031']),
            self.select(), {'action': 'finish'}])
        self.assertEqual([t['status'] for t in result['trace'][2:4]], ['rejected', 'rejected'])
        self.assertEqual(result['status'], 'evidence_ready')

    def test_other_requirement_record_is_not_eligible_even_when_same_scope(self):
        first, other = [criterion(2030)], [criterion(2031)]
        combined = plan(first); combined['requirements'] += plan(other, 'other')['requirements']
        def wrong(packet):
            selected = self.select()(packet)
            selected['record_selection']['record_ids'] = [eid for eid,r in self.records.items() if r['period']['end']=='2031-12-31']
            return selected
        result, _ = self.run_actions([combined, query(first), self.select(), query(other, 'other'), wrong,
            self.select(lambda r: r['period']['end']=='2031-12-31', rid='other'), {'action':'finish'}])
        self.assertEqual(result['trace'][4]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])

    def test_cross_company_and_changed_period_queries_still_rejected(self):
        records = [criterion(2031)]
        result, _ = self.run_actions([plan(records), query([criterion(2031, 'other-services')]),
            query([criterion(2030)]), query(records), self.select(), {'action':'finish'}])
        self.assertEqual([t['status'] for t in result['trace'][1:3]], ['rejected','rejected'])
        self.assertEqual(result['status'], 'evidence_ready')

    def test_multi_period_requirement_rejects_partial_query_then_accepts_full_selection(self):
        records = [criterion(2030), criterion(2031)]
        result, _ = self.run_actions([plan(records), query([criterion(2030)]),
            query(records), self.select(), {'action':'finish'}])
        self.assertEqual(result['trace'][1]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready')
        receipt = json.loads((self.root/'run/turn-002/feedback.json').read_text())
        self.assertIn('query differs from requirement plan', receipt['reason'])

    def test_scope_transition_cannot_select_record_from_other_snapshot_scope(self):
        # A changed-scope evidence ID cannot be fabricated merely by reusing
        # the same original record. The host only resolves stored query evidence.
        def altered_scope(packet):
            r = packet['observation']['result']['records'][0]
            changed = deepcopy(packet['active_scope']); changed['source_snapshot_ids'].append('acme-amended')
            eid = 'ev-' + digest({'kind':'record','value':r,'scope':changed})[:24]
            return self.select(raw_ids=[eid])(packet)
        records=[criterion()]
        result,_=self.run_actions([plan(records),query(records),altered_scope,self.select(),{'action':'finish'}])
        self.assertEqual(result['trace'][2]['status'],'rejected')
        self.assertEqual(result['status'],'evidence_ready')

    def test_native_envelope_supports_action_and_rejects_duplicate_selection(self):
        payload={'record_ids':['ev-a']}
        decoded=decode_decision_envelope(json.dumps({'action':'select_records', 'requirement_ids':['r'],
            'reason':'Required record.', 'payload_json':json.dumps(payload)}))
        value=AutonomousDecision.model_validate_json(decoded)
        self.assertEqual(value.record_selection.record_ids, ('ev-a',))
        for ids in ([], ['ev-a','ev-a']):
            with self.assertRaises(ValidationError):
                AutonomousDecision.model_validate({**json.loads(decoded),'record_selection':{'record_ids':ids}})


class FrozenCompanyRecordSelectionTests(unittest.TestCase):
    def test_two_frozen_company_queries_trim_without_modifying_dataset(self):
        """Deterministic engineering replay, not a model selection quality claim."""
        root = Path(__file__).resolve().parents[2]/'experiments/agent_design/2026-10-09-data-agent-completion-v1'
        for company in ('msft', 'googl'):
            config_file = root/f'configs/{company}-revenue.json'
            if not config_file.exists():
                self.skipTest('Explicit frozen company fixture unavailable')
            config = json.loads(config_file.read_text())
            dataset = root/'datasets'/company
            before = digest((dataset/'manifest.json').read_bytes())
            scope = config['request']['scope']
            sources = json.loads((dataset/'sources.json').read_text())
            fiscal = {f['fiscal_year']: f['period'] for s in sources
                      if s['source_snapshot_id'] in scope['source_snapshot_ids'] for f in s['fiscal_periods']}
            criteria = [{'entity_id':scope['company_ids'][0], 'metric_id':'revenue', 'period':fiscal[y]}
                        for y in (2024, 2025)]
            counts = {}
            def select(packet):
                records = packet['observation']['result']['records']
                counts['queried'] = len(records)
                chosen = []
                for criterion_value in criteria:
                    record = next(r for r in records if all(r[k] == v for k,v in criterion_value.items()))
                    chosen.append('ev-' + digest({'kind':'record','value':record,'scope':packet['active_scope']})[:24])
                return {'action':'select_records','record_selection':{'record_ids':chosen},
                        'requirement_ids':['revenue'],'reason':'One original disclosure per declared criterion.'}
            with self.subTest(company=company), tempfile.TemporaryDirectory() as temporary, QueryDataPort(dataset) as port:
                output = Path(temporary)/'run'
                result = asyncio.run(AutonomousDataAgent(port,
                    ScriptedPlanner([plan(criteria),query(criteria),select,{'action':'finish'}]),
                    purpose='analysis_evidence', limits={'max_steps':4,'max_packet_bytes':500000,
                    'observation_bytes':100000,'page_items':100}).run(
                        {'question':config['request']['question'],'scope':scope},output=output))
                self.assertEqual(result['status'],'evidence_ready',result['trace'])
                packet = prepare_review_packet(output,dataset,expected_scope=scope,
                    max_packet_bytes=500000,source_delivery='query_evidence_v1')
                self.assertEqual(len(packet['facts']),2)
                self.assertGreater(counts['queried'],len(packet['facts']))
                self.assertEqual(packet['program_gaps'],[])
                self.assertEqual({f['value']['period']['end'] for f in packet['facts']},
                                 {p['period']['end'] for p in criteria})
                self.assertEqual(before,digest((dataset/'manifest.json').read_bytes()))


if __name__ == '__main__':
    unittest.main()
