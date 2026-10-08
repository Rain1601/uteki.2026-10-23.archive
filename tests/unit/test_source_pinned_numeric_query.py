"""Source-version selection is a model action; fixtures are not model-quality claims."""
import asyncio
from copy import deepcopy
import json
import unittest

import duckdb

from uteki.agents.data_query.autonomous import AutonomousDataAgent, Requirement
from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.infrastructure.research_data.query_completion import QueryCompletionEvaluator
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit import test_answer_handoff_records as fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import year
from tests.unit.test_task_completion import pin_dataset, attach_synthetic_quotes
from tests.unit.test_exact_record_handoff import pin_originals_for_synthetic_records


class SourcePinnedNumericQueryTests(unittest.TestCase):
    setUp = fixtures.AnswerHandoffRecordTests.setUp

    def plan(self, entity='acme-services'):
        return {'records': [{'entity_id': entity, 'metric_id': 'revenue',
                             'period': year(2031), 'value_kind': 'actual'}]}

    def requirement(self, rid, source=None, entity='acme-services'):
        return {'kind': 'query', 'requirement_id': rid, 'description': 'Original reported 2031 revenue',
                'source_id': source, 'query': self.plan(entity)}

    def run_actions(self, actions, *, name='run', sources=('acme-annual', 'acme-amended'),
                    companies=('acme',), purpose='question_answer'):
        scope = self.scope.model_copy(update={'source_snapshot_ids': sources, 'company_ids': companies})
        output = self.root / name
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, ScriptedPlanner(actions), purpose=purpose,
                limits={'max_steps': len(actions), 'max_packet_bytes': 64000}).run(
                    {'question': 'Retrieve reported revenue for calendar year 2031 from each selected report.',
                     'scope': scope.model_dump(mode='json')}, output=output))
        return result, output, scope

    def actions(self, requirements):
        return [{'action': 'plan', 'reason': 'Retain every requested report version.', 'requirements': requirements},
                *[{'action': 'query', 'requirement_ids': [r['requirement_id']], 'plan': r['query']} for r in requirements],
                {'action': 'finish'}]

    def test_distinct_report_requirements_keep_both_values_and_canonical_sources(self):
        reqs = [self.requirement('old', 'acme-annual'), self.requirement('new', 'acme-amended')]
        result, output, scope = self.run_actions(self.actions(reqs))
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        packet = prepare_review_packet(output, self.dataset, expected_scope=scope, max_packet_bytes=1_000_000)
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual({(f['value']['source_snapshot_id'], f['value']['value_decimal']) for f in packet['facts']},
                         {('acme-annual', '100'), ('acme-amended', '900')})
        for number, sid in ((2, 'acme-annual'), (3, 'acme-amended')):
            receipt = json.loads((output / f'turn-{number:03d}/query-receipt.json').read_text())
            self.assertEqual(receipt['request']['source_id'], sid)
            self.assertEqual(receipt['result']['scope']['source_snapshot_ids'], [sid])
            self.assertEqual(receipt['package']['scope'], receipt['result']['scope'])
            self.assertEqual(receipt['result']['selections'][0]['status'], 'matched')

    def test_omitted_selector_keeps_ambiguity_and_legacy_receipt_shape(self):
        req = self.requirement('both')
        result, output, _ = self.run_actions(self.actions([req]))
        self.assertNotEqual(result['status'], 'evidence_ready')
        receipt = json.loads((output / 'turn-002/query-receipt.json').read_text())
        self.assertNotIn('source_id', receipt['request'])
        self.assertEqual(receipt['result']['selections'][0]['status'], 'ambiguous')
        self.assertEqual(len(receipt['result']['records']), 2)

    def test_analysis_delivery_selects_both_versions_without_changing_record_scope(self):
        pin_originals_for_synthetic_records(self.dataset)
        reqs = [self.requirement('old', 'acme-annual'), self.requirement('new', 'acme-amended')]
        actions = [self.actions(reqs)[0]]
        for req in reqs:
            rid = req['requirement_id']
            actions.append({'action': 'query', 'requirement_ids': [rid], 'plan': req['query']})
            actions.append(lambda packet, rid=rid: {'action': 'select_records', 'requirement_ids': [rid],
                'record_selection': {'record_ids': packet['observation']['evidence_ids']},
                'reason': 'Retain this explicitly requested report version.'})
        actions.append({'action': 'finish'})
        result, output, scope = self.run_actions(actions, purpose='analysis_evidence')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        packet = prepare_review_packet(output, self.dataset, expected_scope=scope, max_packet_bytes=1_000_000,
                                       source_delivery='query_evidence_v1')
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual({f['value']['source_snapshot_id'] for f in packet['facts']}, {'acme-annual', 'acme-amended'})
        self.assertTrue(all(row['selected_record_ids'] for row in result['coverage']))

    def test_conflicting_values_inside_one_selected_report_still_block(self):
        with duckdb.connect(str(self.dataset / 'research.duckdb')) as db:
            original = db.execute("SELECT * FROM observations WHERE record_id = 'acme-annual-revenue-2031'").fetchone()
            row = list(original)
            payload = json.loads(row[-1])
            payload.update(record_id='conflicting-occurrence', value_decimal='101', evidence_ids=['conflicting-occurrence'])
            row[0], row[7], row[-1] = payload['record_id'], '101', json.dumps(payload)
            db.execute('INSERT INTO observations VALUES (' + ','.join('?' for _ in row) + ')', row)
            db.execute('INSERT INTO evidence VALUES (?, ?, ?)', ['conflicting-occurrence', 'acme-annual',
                json.dumps({'evidence_id': 'conflicting-occurrence', 'source_snapshot_id': 'acme-annual', 'quote': '101'})])
        attach_synthetic_quotes(self.dataset)
        result, output, _ = self.run_actions(self.actions([self.requirement('one', 'acme-annual')]))
        self.assertNotEqual(result['status'], 'evidence_ready')
        receipt = json.loads((output / 'turn-002/query-receipt.json').read_text())
        self.assertEqual(receipt['result']['selections'][0]['status'], 'ambiguous')
        self.assertEqual({r['value_decimal'] for r in receipt['result']['records']}, {'100', '101'})

    def test_mixed_selectors_in_one_action_are_rejected(self):
        reqs = [self.requirement('old', 'acme-annual'), self.requirement('new', 'acme-amended')]
        actions = [self.actions(reqs)[0], {'action': 'query', 'requirement_ids': ['old', 'new'], 'plan': self.plan()},
                   {'action': 'finish'}]
        result, output, _ = self.run_actions(actions)
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertFalse((output / 'turn-002/query-receipt.json').exists())
        self.assertEqual(result['trace'][1]['status'], 'rejected')

    def test_unknown_outside_scope_cross_company_and_future_cannot_be_pinned(self):
        cases = [('unknown', 'unknown-source', 'acme-services'),
                 ('outside', 'acme-quarter', 'acme-services'),
                 ('company', 'acme-annual', 'other-services'),
                 ('future', 'acme-future', 'acme-services')]
        for name, sid, entity in cases:
            with self.subTest(name=name):
                req = self.requirement('one', sid, entity)
                result, output, _ = self.run_actions(self.actions([req]), name=name,
                    sources=('acme-annual', 'acme-amended', 'acme-future', 'other-annual'),
                    companies=('acme', 'other'))
                self.assertNotEqual(result['status'], 'evidence_ready')
                self.assertFalse((output / 'turn-002/query-receipt.json').exists())

    def test_resealed_source_selector_cannot_relabel_another_report_record(self):
        result, output, scope = self.run_actions(self.actions([self.requirement('one', 'acme-annual')]))
        path = output / 'result.json'
        result['coverage'][0]['source_id'] = 'acme-amended'
        path.write_text(json.dumps(result))
        pin_dataset(output)
        with self.assertRaisesRegex(ValueError, 'record differs from scoped dataset'):
            prepare_review_packet(output, self.dataset, expected_scope=scope, max_packet_bytes=1_000_000)

    def test_completion_rejects_mismatched_receipt_and_package_source(self):
        req = self.requirement('one', 'acme-annual')
        _, output, _ = self.run_actions(self.actions([req]))
        receipt = json.loads((output / 'turn-002/query-receipt.json').read_text())
        evaluator = QueryCompletionEvaluator()
        for target in ('request', 'scope', 'record', 'package'):
            with self.subTest(target=target):
                changed = deepcopy(receipt)
                if target == 'request': changed['request']['source_id'] = 'acme-amended'
                if target == 'scope': changed['result']['scope']['source_snapshot_ids'] = ['acme-amended']
                if target == 'record': changed['result']['records'][0]['source_snapshot_id'] = 'acme-amended'
                if target == 'package': changed['package']['scope']['source_snapshot_ids'] = ['acme-amended']
                with self.assertRaisesRegex(ValueError, 'source selector'):
                    evaluator.evaluate_query(Requirement.model_validate(req), [changed])

    def test_blank_selector_rejected_and_old_requirement_default_unchanged(self):
        for sid in ('', '  '):
            with self.assertRaises(ValueError): Requirement.model_validate(self.requirement('one', sid))
        value = Requirement.model_validate(self.requirement('one')).model_dump(mode='json')
        self.assertIsNone(value['source_id'])
        self.assertEqual(set(value['query']), {'records', 'documents', 'calculations'})

    def test_source_narrowing_retains_authority_and_candidate_denial(self):
        scope = self.scope.model_dump(mode='json')
        scope.update(company_ids=['acme', 'other'],
                     source_snapshot_ids=['acme-annual', 'acme-amended', 'other-annual'])
        with QueryDataPort(self.dataset) as base:
            outer = base.scoped(scope)
            self.assertIs(outer.for_query_source(), outer)
            child = outer.for_query_source('other-annual')
            self.assertEqual(child.scope.company_ids, ('other',))
            self.assertEqual(child.scope.source_snapshot_ids, ('other-annual',))
            self.assertEqual(outer.scope.model_dump(mode='json'), scope)
            for key in ('snapshot_id', 'source_policy_id', 'knowledge_cutoff', 'include_candidates'):
                self.assertEqual(getattr(child.scope, key), getattr(outer.scope, key))
            denied = base.scoped({**scope, 'include_candidates': False}).for_query_source('acme-annual')
            value = denied.query_data({'query_id': 'denied', 'snapshot_id': denied.snapshot_id,
                'source_policy_id': denied.scope.source_policy_id,
                'knowledge_cutoff': denied.scope.knowledge_cutoff, 'include_candidates': False,
                'records': [{'entity_id': 'acme', 'metric_id': 'revenue', 'period': year(2031)}]})
            self.assertEqual(value['records'], [])
            self.assertEqual(value['selections'][0]['status'], 'quality_filtered')


if __name__ == '__main__':
    unittest.main()
