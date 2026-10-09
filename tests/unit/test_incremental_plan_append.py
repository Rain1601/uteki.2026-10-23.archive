"""Incremental immutable requirements; independent issuer/period fixtures, no API."""
import asyncio
from copy import deepcopy
import json
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from tests.unit import test_autonomous_data_agent as fixtures
from tests.unit.test_scoped_query_service import year


def revision(*requirements):
    return {'action': 'plan', 'reason': 'Append independent synthetic requirements.',
            'requirements': list(requirements)}


def information(rid):
    return {'requirement_id': rid, 'description': 'Synthetic bounded requirement ' + rid}


def numeric(rid='number', *, entity='acme-services', period=2031, source='acme-annual'):
    return {'kind': 'query', 'requirement_id': rid, 'description': 'Retrieve scoped synthetic revenue.',
            'source_id': source, 'query': {'records': [{'entity_id': entity, 'metric_id': 'revenue',
                                                     'period': year(period), 'value_kind': 'actual'}]}}


class IncrementalPlanAppendTests(unittest.TestCase):
    setUp = fixtures.AutonomousDataAgentTests.setUp

    def run_actions(self, actions, *, purpose='question_answer'):
        output = self.root / f'run-{len(list(self.root.glob("run-*"))) + 1}'
        planner = fixtures.ScriptedPlanner(actions)
        result = asyncio.run(AutonomousDataAgent(self.port, planner, purpose=purpose,
            limits={'max_steps': len(actions)}).run(self.request, output=output))
        return result, planner, output

    def test_new_only_append_preserves_old_and_full_union_is_compatible(self):
        seed, new, third = information('seed'), information('new'), information('third')
        result, _, _ = self.run_actions([revision(seed), revision(new), revision(seed, new, third)])
        self.assertEqual(len(result['plans']), 3)
        self.assertEqual([x['requirement_id'] for x in result['plans'][-1]['requirements']], ['seed', 'new', 'third'])
        self.assertEqual([x['requirement_id'] for x in result['coverage']], ['seed', 'new', 'third'])

    def test_same_id_rewrite_and_duplicate_payload_are_rejected_without_mutation(self):
        seed = information('seed')
        for proposal in ([{**seed, 'description': 'Changed content.'}], [seed, seed]):
            with self.subTest(proposal=proposal):
                result, _, output = self.run_actions([revision(seed), revision(*proposal)])
                self.assertEqual(len(result['plans']), 1)
                self.assertEqual(result['plans'][0]['requirements'][0]['description'], seed['description'])
                feedback = json.loads((output / 'turn-002/feedback.json').read_text())
                self.assertEqual(feedback['status'], 'rejected')

    def test_new_requirements_still_validate_source_entity_period_role_and_schema_atomically(self):
        seed = information('seed')
        invalid = [
            {'kind': 'source_evidence', 'source_id': 'other-annual', 'requirement_id': 'outside-source',
             'description': 'Must not read another issuer.'},
            numeric(entity='other-services'),
            numeric(period=2030),
            numeric(source='other-annual'),
            {'kind': 'source_answer', 'source_id': 'acme-annual', 'requirement_id': 'wrong-purpose',
             'description': 'Answer authoring forbidden for analysis_evidence.'},
            {**information('invalid-schema'), 'unknown_payload': 'not accepted'},
        ]
        for bad in invalid:
            with self.subTest(bad=bad):
                result, _, output = self.run_actions([revision(seed), revision(information('valid-first'), bad)],
                                                     purpose='analysis_evidence')
                self.assertEqual(len(result['plans']), 1)
                self.assertEqual([x['requirement_id'] for x in result['coverage']], ['seed'])
                feedback = json.loads((output / 'turn-002/feedback.json').read_text())
                self.assertEqual(feedback['status'], 'rejected')

    def test_preserves_existing_numeric_and_body_selections_evidence_and_gaps(self):
        number = numeric()
        body = {'kind': 'source_evidence', 'source_id': 'acme-annual', 'requirement_id': 'body',
                'description': 'Deliver original synthetic table.'}
        prior_gap = information('prior-gap')
        state = {}
        def select_number(packet):
            state['record_eid'] = packet['observation']['evidence_ids'][0]
            return {'action': 'select_records', 'requirement_ids': ['number'],
                    'record_selection': {'record_ids': [state['record_eid']]}, 'reason': 'Choose original returned record.'}
        def select_body(packet):
            state['body_eid'] = packet['observation']['evidence_ids'][0]
            return {'action': 'select_evidence', 'requirement_ids': ['body'], 'reason': 'Choose read original table.',
                    'delivery': {'blocks': [{'context_id': state['body_eid'], 'block_id': 'b8'}]}}
        def append(packet):
            state['coverage'] = {x['requirement_id']: deepcopy(x) for x in packet['coverage']}
            return revision(information('new-only'))
        result, planner, _ = self.run_actions([
            revision(number, body, prior_gap),
            {'action': 'query', 'requirement_ids': ['number'], 'plan': number['query']},
            select_number,
            {'action': 'read_context', 'requirement_ids': ['body'],
             'context': {'source_snapshot_id': 'acme-annual', 'block_id': 'b8'}},
            select_body,
            {'action': 'gap', 'requirement_ids': ['prior-gap'], 'reason': 'Known synthetic data gap.'},
            append,
            {'action': 'gap', 'requirement_ids': ['new-only'], 'reason': 'Explicit synthetic remaining gap.'},
            {'action': 'finish'}], purpose='analysis_evidence')
        self.assertEqual(len(result['plans']), 2)
        self.assertEqual(result['status'], 'partial')
        current = {x['requirement_id']: x for x in result['coverage']}
        for rid in ('number', 'body', 'prior-gap'):
            self.assertEqual(current[rid]['evidence_ids'], state['coverage'][rid]['evidence_ids'])
            self.assertEqual(current[rid]['gap_ids'], state['coverage'][rid]['gap_ids'])
        self.assertEqual(current['number']['selected_record_ids'], [state['record_eid']])
        self.assertEqual(current['body']['selected_blocks'], [{'context_id': state['body_eid'], 'block_id': 'b8'}])
        # Appended plan does not change the original source/query pinned scope.
        self.assertEqual(current['number']['query_scope'], state['coverage']['number']['query_scope'])
        self.assertEqual(current['body']['source_scope'], state['coverage']['body']['source_scope'])

    def test_accumulated_limit_cannot_be_bypassed_by_small_appends(self):
        original = [information(f'seed-{i}') for i in range(32)]
        result, _, output = self.run_actions([revision(*original), revision(information('overflow'))])
        self.assertEqual(len(result['plans']), 1)
        self.assertEqual(len(result['coverage']), 32)
        self.assertEqual(json.loads((output / 'turn-002/feedback.json').read_text())['status'], 'rejected')

    def test_omitted_existing_requirement_is_not_deleted_or_completed(self):
        result, _, _ = self.run_actions([revision(information('old'), information('unresolved')),
                                        revision(information('old')), {'action': 'finish'}])
        self.assertEqual(len(result['plans']), 2)
        self.assertEqual([x['requirement_id'] for x in result['coverage']], ['old', 'unresolved'])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(len(result['plans'][-1]['requirements']), 2)

    def test_repeat_only_revision_and_repeated_catalog_page_do_not_create_progress(self):
        seed = information('seed')
        result, _, _ = self.run_actions([revision(seed), revision(seed), revision(seed), revision(seed)])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        catalog = {'action': 'discover_catalog', 'catalog': {'kind': 'entities', 'limit': 1}}
        result, _, _ = self.run_actions([revision(seed), catalog, catalog, catalog, catalog])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(result['trace'][-1]['consecutive_no_progress'], 3)
