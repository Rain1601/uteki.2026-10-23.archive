"""Source-selection ownership boundaries over invented data; no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.data_query.selection_contract import (
    SelectionContractError, validate_source_selection,
)
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset


class SelectionOwnershipContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = {'snapshot_id': 'snapshot-one', 'company_ids': ['invented-issuer'],
                      'source_snapshot_ids': ['annual-original', 'annual-amended']}
        self.coverage = {
            rid: {'source_id': source, 'source_scope': deepcopy(self.scope)}
            for rid, source in (('original', 'annual-original'),
                                ('shared', 'annual-original'), ('amended', 'annual-amended'))}
        self.evidence = {
            cid: {'kind': 'context', 'scope': deepcopy(self.scope),
                  'value': {'source_snapshot_id': source}}
            for cid, source in (('context-original', 'annual-original'),
                                ('context-amended', 'annual-amended'))}
        # Block IDs are local to a source, so these deliberately collide.
        self.delivered = {'context-original': {'same-block'}, 'context-amended': {'same-block'}}
        self.original = {'context_id': 'context-original', 'block_id': 'same-block'}
        self.amended = {'context_id': 'context-amended', 'block_id': 'same-block'}

    def validate(self, refs, selected):
        return validate_source_selection(refs, selected, self.coverage, self.evidence, self.delivered)

    def reject(self, refs, selected, code):
        before = deepcopy((self.coverage, self.evidence, self.delivered))
        with self.assertRaises(SelectionContractError) as caught:
            self.validate(refs, selected)
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic['code'], code)
        self.assertIs(diagnostic['action_accepted'], False)
        self.assertEqual(diagnostic['action'], 'select_evidence')
        self.assertEqual((self.coverage, self.evidence, self.delivered), before)
        return diagnostic

    def test_one_source_can_broadcast_identical_blocks_to_multiple_requirements(self):
        self.assertIsNone(self.validate(['original', 'shared'], [self.original]))
        self.assertIsNone(self.validate(['shared', 'original'], [self.original]))

    def test_same_company_different_report_versions_are_distinct_ownership_groups(self):
        diagnostic = self.reject(['original', 'amended'], [self.original, self.amended],
                                 'selection_requirement_scope_mismatch')
        self.assertEqual({g['source_id'] for g in diagnostic['requirement_groups']},
                         {'annual-original', 'annual-amended'})
        self.assertEqual({tuple(g['requirement_ids']) for g in diagnostic['requirement_groups']},
                         {('original',), ('amended',)})
        self.assertIn('No selection changed', diagnostic['guidance'])

    def test_same_source_in_different_frozen_scopes_cannot_broadcast(self):
        self.coverage['shared']['source_scope']['snapshot_id'] = 'snapshot-two'
        diagnostic = self.reject(['original', 'shared'], [self.original],
                                 'selection_requirement_scope_mismatch')
        self.assertEqual(len({g['scope_id'] for g in diagnostic['requirement_groups']}), 2)
        self.assertEqual({g['source_id'] for g in diagnostic['requirement_groups']}, {'annual-original'})

    def test_same_block_id_from_other_source_is_not_interchangeable(self):
        diagnostic = self.reject(['original'], [self.amended], 'selection_block_source_mismatch')
        self.assertEqual(diagnostic['expected_source_id'], 'annual-original')
        self.assertEqual(diagnostic['actual_source_id'], 'annual-amended')
        self.assertEqual(diagnostic['context_id'], 'context-amended')
        self.assertIsNone(self.validate(['amended'], [self.amended]))

    def test_context_from_another_snapshot_has_its_own_error(self):
        self.evidence['context-original']['scope']['snapshot_id'] = 'older-snapshot'
        diagnostic = self.reject(['original'], [self.original], 'selection_context_scope_mismatch')
        self.assertNotEqual(diagnostic['actual_scope_id'], diagnostic['expected_scope_id'])

    def test_unknown_and_non_context_ids_do_not_count_as_read_evidence(self):
        for kind in ('missing', 'record'):
            with self.subTest(kind=kind):
                if kind == 'missing':
                    self.evidence.pop('context-original')
                else:
                    self.evidence['context-original'] = {'kind': 'record'}
                self.reject(['original'], [self.original], 'selection_context_not_available')

    def test_unread_block_in_known_context_requires_reading_not_regrouping(self):
        self.delivered['context-original'] = set()
        diagnostic = self.reject(['original'], [self.original], 'selection_block_not_fully_read')
        self.assertIn('pending body read', diagnostic['guidance'])
        self.assertNotIn('requirement_groups', diagnostic)

    def test_duplicate_context_block_pair_is_rejected(self):
        self.reject(['original'], [self.original, deepcopy(self.original)], 'selection_duplicate_block')


class SelectionOwnershipRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)

    @staticmethod
    def requirement(rid, source):
        return {'kind': 'source_evidence', 'requirement_id': rid, 'source_id': source,
                'description': 'Supply the original product disclosure from this report.'}

    @staticmethod
    def read(rid, source, block='b1'):
        return {'action': 'read_context', 'requirement_ids': [rid],
                'context': {'source_snapshot_id': source, 'block_id': block}}

    @staticmethod
    def select(packet, refs, source_blocks):
        blocks = []
        for source, bid in source_blocks:
            item = next(row for row in packet['retained_body']['items']
                        if row['source_snapshot_id'] == source and row['block_id'] == bid)
            blocks.append({'context_id': item['context_evidence_id'], 'block_id': bid})
        return {'action': 'select_evidence', 'requirement_ids': refs,
                'delivery': {'blocks': blocks}, 'reason': 'Retain the necessary original disclosure.'}

    def run_actions(self, actions, sources, name):
        companies = ('acme', 'other') if 'other-annual' in sources else ('acme',)
        scope = ExecutionScope(snapshot_id='synthetic-scoped-v1', company_ids=companies,
            source_snapshot_ids=sources, source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        planner = ScriptedPlanner(actions)
        output = self.root / name
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                limits={'max_steps': len(actions), 'max_packet_bytes': 100000,
                        'observation_bytes': 24000, 'page_items': 30}).run(
                {'question': 'Supply the original product disclosures for each selected report.',
                 'scope': scope.model_dump(mode='json')}, output=output))
        return result, planner, output

    def test_rejection_preserves_old_selection_and_diagnostic_guides_separate_actions(self):
        # Both cross-company reports and same-company amended reports must work.
        for second in ('other-annual', 'acme-amended'):
            with self.subTest(second=second):
                prior = {}

                def initial(packet):
                    return self.select(packet, ['first'], [('acme-annual', 'b1')])

                def mixed(packet):
                    prior.update(deepcopy(packet['delivery_selection']))
                    return self.select(packet, ['first', 'second'],
                                       [('acme-annual', 'b2'), (second, 'b1')])

                def recover_first(packet):
                    self.assertEqual(packet['delivery_selection'], prior)
                    self.assertNotIn('second', packet['delivery_selection'])
                    diagnostic = packet['observation']['selection_diagnostic']
                    self.assertEqual(packet['observation']['status'], 'rejected')
                    self.assertEqual(diagnostic['code'], 'selection_requirement_scope_mismatch')
                    self.assertEqual({g['source_id'] for g in diagnostic['requirement_groups']},
                                     {'acme-annual', second})
                    return self.select(packet, ['first'], [('acme-annual', 'b2')])

                def recover_second(packet):
                    self.assertEqual(packet['delivery_selection']['first'][0]['block_id'], 'b2')
                    return self.select(packet, ['second'], [(second, 'b1')])

                actions = [
                    {'action': 'plan', 'reason': 'Read each selected report independently.',
                     'requirements': [self.requirement('first', 'acme-annual'),
                                      self.requirement('second', second)]},
                    self.read('first', 'acme-annual'), initial,
                    self.read('first', 'acme-annual', 'b2'), self.read('second', second),
                    mixed, recover_first, recover_second, {'action': 'finish'}]
                result, _, output = self.run_actions(actions, ('acme-annual', second), second)
                self.assertEqual(result['status'], 'evidence_ready', result['trace'])
                self.assertEqual([row['step'] for row in result['trace'] if row['status'] == 'rejected'], [6])
                rejected = json.loads((output / 'turn-006/feedback.json').read_text())
                self.assertEqual(rejected['selection_diagnostic']['code'],
                                 'selection_requirement_scope_mismatch')
                self.assertIs(rejected['receipt']['progress_delta'], False)
                self.assertEqual(json.loads((output / 'turn-003/feedback.json').read_text())[
                    'delivery_selection'][0]['block_id'], 'b1')
                coverage = {row['requirement_id']: row for row in result['coverage']}
                self.assertEqual(coverage['first']['selected_blocks'][0]['block_id'], 'b2')
                self.assertEqual(coverage['second']['selected_blocks'][0]['block_id'], 'b1')

    def test_same_source_broadcast_remains_legal_in_agent_runtime(self):
        def broadcast(packet):
            return self.select(packet, ['first', 'shared'], [('acme-annual', 'b1')])

        actions = [
            {'action': 'plan', 'reason': 'Two related requirements share one source passage.',
             'requirements': [self.requirement('first', 'acme-annual'),
                              self.requirement('shared', 'acme-annual')]},
            self.read('first', 'acme-annual'), broadcast, {'action': 'finish'}]
        result, _, _ = self.run_actions(actions, ('acme-annual',), 'broadcast')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertFalse(any(row['status'] == 'rejected' for row in result['trace']))
        coverage = {row['requirement_id']: row for row in result['coverage']}
        self.assertEqual(coverage['first']['selected_blocks'], coverage['shared']['selected_blocks'])

    def test_valid_first_block_then_foreign_block_cannot_partially_replace_selection(self):
        old = {}

        def initial(packet):
            return self.select(packet, ['first'], [('acme-annual', 'b1')])

        def invalid(packet):
            old.update(deepcopy(packet['delivery_selection']))
            return self.select(packet, ['first'], [('acme-annual', 'b2'), ('other-annual', 'b1')])

        def recover(packet):
            self.assertEqual(packet['delivery_selection'], old)
            diagnostic = packet['observation']['selection_diagnostic']
            self.assertEqual(diagnostic['code'], 'selection_block_source_mismatch')
            self.assertEqual(diagnostic['expected_source_id'], 'acme-annual')
            self.assertEqual(diagnostic['actual_source_id'], 'other-annual')
            return self.select(packet, ['second'], [('other-annual', 'b1')])

        actions = [
            {'action': 'plan', 'reason': 'Keep the two reports separate.',
             'requirements': [self.requirement('first', 'acme-annual'),
                              self.requirement('second', 'other-annual')]},
            self.read('first', 'acme-annual'), initial,
            self.read('first', 'acme-annual', 'b2'), self.read('second', 'other-annual'),
            invalid, recover, {'action': 'finish'}]
        result, _, _ = self.run_actions(actions, ('acme-annual', 'other-annual'), 'block-mismatch')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        coverage = {row['requirement_id']: row for row in result['coverage']}
        self.assertEqual(coverage['first']['selected_blocks'][0]['block_id'], 'b1')
        self.assertEqual([row['step'] for row in result['trace'] if row['status'] == 'rejected'], [6])


if __name__ == '__main__':
    unittest.main()
