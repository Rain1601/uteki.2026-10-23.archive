"""Candidate narrative answers over synthetic sources; no model evaluation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AutonomousDataAgent, Requirement, SourceAnswer
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, read
from tests.unit.test_autonomous_source_evidence import context_read
from tests.unit.test_autonomous_worker import delegate
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import pin_dataset


ACTUAL = 'In 2031, acme invested in production equipment and warehouse facilities.'
FUTURE = 'For 2032, acme expects to expand production equipment.'


def answer_plan(source='acme-annual', requirement='business'):
    return {'action': 'plan', 'reason': 'Answer the disclosed investment uses and separate future plans.',
            'requirements': [{'kind': 'source_answer', 'requirement_id': requirement,
                              'description': 'Describe actual investment uses and future plans with citations.',
                              'source_id': source}]}


def answer_action(context_id, *, requirement='business', partial=False, include_future=False):
    claims = [{'statement': 'Actual investments included production equipment and warehouse facilities.',
               'temporal_basis': 'reported_actual', 'period_context': '2031, as stated in the source.',
               'citations': [{'context_id': context_id, 'block_id': 'b1', 'quote': ACTUAL,
                              'label': 'Actual investment uses'}]}]
    if include_future:
        claims.append({'statement': 'Expansion of production equipment is a future expectation.',
                       'temporal_basis': 'forward_looking', 'period_context': '2032, as stated in the source.',
                       'citations': [{'context_id': context_id, 'block_id': 'b2', 'quote': FUTURE,
                                      'label': 'Future investment plan'}]})
    return {'action': 'answer', 'requirement_ids': [requirement], 'answer': {
        'claims': claims, 'model_claimed_coverage': 'partial' if partial else 'claimed_complete',
        'coverage_note': 'Future plans still need review.' if partial else 'The cited passages cover the stated answer.',
        'unresolved_questions': ['What future plans are disclosed?'] if partial else []}}


class AutonomousSourceAnswerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        for source in ('acme-annual', 'acme-amended'):
            index = self.dataset / 'indexes' / source
            path = index / 'blocks.jsonl'
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            blocks[1]['text'], blocks[2]['text'] = ACTUAL, FUTURE
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest_path = index / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.dataset)

    def open_dataset(self, *, sources=('acme-annual',), long_body=False, eviction_body=False):
        if long_body or eviction_body:
            index = self.dataset / 'indexes/acme-annual'
            path = index / 'blocks.jsonl'
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            if long_body:
                blocks[1]['text'] += ' Additional source detail.' * 180
            if eviction_body:
                # Several individually deliverable blocks can displace older retained text.
                for block in blocks[3:7]:
                    block['text'] = block['text'] + ' Unrelated disclosure.' * 39
            path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
            manifest_path = index / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
            manifest_path.write_text(json.dumps(manifest))
            pin_dataset(self.dataset)
        self.port = QueryDataPort(self.dataset)
        self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=sources, source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Describe investment uses in 2031 and distinguish expectations for 2032.',
                        'scope': self.scope.model_dump(mode='json')}

    def run_actions(self, actions, *, name='run', limits=None, worker=None, materialize=None):
        planner = ScriptedPlanner(actions)
        output = self.root / name
        agent = AutonomousDataAgent(self.port, planner, worker_planner=worker, materialize=materialize,
            limits={'max_steps': len(actions) + (6 if worker else 0),
                    'max_packet_bytes': 64000, **(limits or {})})
        result = asyncio.run(agent.run(self.request, output=output))
        return result, planner, output

    @staticmethod
    def answer_from_observation(packet):
        return answer_action(packet['observation']['evidence_ids'][0], include_future=True)

    def candidates(self, output):
        return [item for item in load_evidence_bundle(output)['items']
                if item['kind'] == 'candidate_source_answer']

    def test_source_answer_contract_requires_explicit_source_and_consistent_answer(self):
        requirement = answer_plan()['requirements'][0]
        invalid_requirements = [{key: value for key, value in requirement.items() if key != 'source_id'},
                                {**requirement, 'source_id': ' '}, {**requirement, 'node_id': 'business'}]
        for invalid in invalid_requirements:
            with self.subTest(requirement=invalid), self.assertRaises(ValidationError):
                Requirement.model_validate(invalid)
        valid = answer_action('context-test')['answer']
        invalid_answers = [dict(valid, model_claimed_coverage='partial'),
                           dict(valid, unresolved_questions=['Unresolved category']),
                           dict(valid, claims=[])]
        for field, value in (('period_context', ' '), ('citations', []), ('temporal_basis', 'inferred_actual')):
            invalid = deepcopy(valid)
            invalid['claims'][0][field] = value
            invalid_answers.append(invalid)
        for invalid in invalid_answers:
            with self.subTest(answer=invalid), self.assertRaises(ValidationError):
                SourceAnswer.model_validate(invalid)
        self.open_dataset()
        for index, source in enumerate(('unknown-source', 'other-annual')):
            with self.subTest(source=source):
                result, _, _ = self.run_actions([answer_plan(source)], name=f'bad-source-{index}')
                self.assertEqual(result['trace'][0]['status'], 'rejected')

    def test_read_body_without_answer_cannot_finish(self):
        self.open_dataset()

        def finish(packet):
            self.assertTrue(packet['retained_body']['items'])
            self.assertIn({'requirement_id': 'business', 'reason': 'source_answer_missing'},
                          packet['completion']['unmet'])
            self.assertIs(packet['completion']['reference_checks_passed'], False)
            return {'action': 'finish'}

        result, _, output = self.run_actions([answer_plan(), context_read(), finish])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertEqual(self.candidates(output), [])

    def test_invalid_quotes_and_not_fully_delivered_blocks_leave_no_candidate(self):
        self.open_dataset(long_body=True)

        def incomplete_body(packet):
            self.assertTrue(any(item['block_id'] == 'b1' for item in packet['pending_body_reads']))
            return answer_action(packet['observation']['evidence_ids'][0])

        result, _, output = self.run_actions([answer_plan(), context_read(), incomplete_body],
                                             limits={'observation_bytes': 1800})
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(self.candidates(output), [])

        def invented_second_quote(packet):
            value = answer_action(packet['observation']['evidence_ids'][0], include_future=True)
            value['answer']['claims'][1]['citations'][0]['quote'] = 'Invented guaranteed returns.'
            return value

        # Read the short future block: the first claim is valid, the later quote is not.
        def invalid_second_claim(packet):
            value = invented_second_quote(packet)
            value['answer']['claims'][0]['citations'][0].update(block_id='b2', quote=FUTURE)
            return value

        result, _, output = self.run_actions([answer_plan(), context_read(block='b2'), invalid_second_claim],
                                             name='invalid-second-quote')
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(self.candidates(output), [])

    def test_identical_quote_in_other_allowed_source_cannot_answer_requirement(self):
        self.open_dataset(sources=('acme-annual', 'acme-amended'))
        result, _, output = self.run_actions([
            answer_plan(), read(source='acme-amended'), self.answer_from_observation, {'action': 'finish'}])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['trace'][3]['status'], 'rejected')
        self.assertEqual(self.candidates(output), [])

    def test_worker_only_context_cannot_be_cited_as_parent_reading(self):
        self.open_dataset()
        state = {}

        def worker_answer(packet):
            state['context_id'] = packet['observation']['evidence_ids'][0]
            return answer_action(state['context_id'], include_future=True)

        worker = ScriptedPlanner([read(), worker_answer, {'action': 'finish'}])

        def stolen_context(packet):
            self.assertEqual(packet['retained_body']['items'], [])
            self.assertEqual(packet['coverage'][0]['evidence_ids'], [])
            self.assertTrue(worker.packets[-1]['retained_body']['items'])
            self.assertEqual(packet['delegations'][0]['result_status'], 'evidence_ready')
            summary = packet['observation']['result']
            self.assertTrue(summary['candidate_source_answers'])
            return answer_action(state['context_id'], include_future=True)

        result, _, output = self.run_actions([
            answer_plan(), delegate(), stolen_context, read(),
            self.answer_from_observation, {'action': 'finish'}], worker=worker)
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(len(self.candidates(output)), 1)
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')

    def test_cross_block_answer_persists_after_unrelated_context_without_semantic_acceptance(self):
        self.open_dataset(eviction_body=True)
        state = {}

        def next_context(packet):
            item, = packet['research_answers']['items']
            self.assertEqual(item['requirement_id'], 'business')
            self.assertEqual(len(item['value']['claims']), 2)
            self.assertIn('artifact', item)
            self.assertIn('reads', item)
            self.assertEqual([claim['temporal_basis'] for claim in item['value']['claims']],
                             ['reported_actual', 'forward_looking'])
            state['answer'] = deepcopy(item)
            state['answer_id'] = packet['coverage'][0]['active_answer_id']
            return {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
                'source_snapshot_id': 'acme-annual', 'node_id': 'risks', 'count': 4}}

        def finish(packet):
            self.assertIn(state['answer'], packet['research_answers']['items'])
            self.assertEqual(packet['coverage'][0]['active_answer_id'], state['answer_id'])
            self.assertGreater(packet['retained_body']['omitted_count'], 0)
            self.assertNotIn('b1', {item['block_id'] for item in packet['retained_body']['items']})
            self.assertNotIn('b2', {item['block_id'] for item in packet['retained_body']['items']})
            self.assertIs(packet['completion']['reference_checks_passed'], True)
            self.assertEqual(packet['completion']['semantic_completeness'], 'not_evaluated')
            return {'action': 'finish'}

        result, _, output = self.run_actions([
            answer_plan(), read(), self.answer_from_observation, next_context, finish],
            limits={'max_packet_bytes': 30000})
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        candidate, = self.candidates(output)
        self.assertEqual(candidate['scope'], self.request['scope'])
        self.assertEqual(candidate['evidence_id'], state['answer_id'])
        self.assertEqual({citation['block_id'] for claim in candidate['value']['claims']
                          for citation in claim['citations']}, {'b1', 'b2'})
        bundle = load_evidence_bundle(output)
        for claim in candidate['value']['claims']:
            for citation in claim['citations']:
                self.assertIn(citation['block_id'], bundle['delivered_body'][citation['context_id']])
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')

    def test_partial_answer_seals_partial_but_complete_revision_leaves_no_answer_gap(self):
        self.open_dataset()
        state = {}

        def partial(packet):
            state['context_id'] = packet['observation']['evidence_ids'][0]
            return answer_action(state['context_id'], partial=True, include_future=True)

        result, _, output = self.run_actions([answer_plan(), read(), partial, {'action': 'finish'}])
        self.assertEqual(result['status'], 'partial', result['trace'])
        self.assertTrue(any(gap['reason'] == 'source_answer_partial' for gap in result['gaps']))
        self.assertEqual(len(self.candidates(output)), 1)

        def revised(packet):
            self.assertEqual(packet['research_answers']['items'][0]['value']['model_claimed_coverage'], 'partial')
            self.assertEqual(packet['consecutive_no_progress'], 2)
            return answer_action(state['context_id'], include_future=True)

        def repeat_partial(packet):
            return answer_action(state['context_id'], partial=True, include_future=True)

        result, planner, output = self.run_actions([
            answer_plan(), read(), partial, repeat_partial, repeat_partial,
            revised, {'action': 'finish'}], name='revised')
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['gaps'], [])
        self.assertEqual(result['coverage'][0]['gap_ids'], [])
        self.assertEqual(len(self.candidates(output)), 2)
        final_answer, = planner.packets[-1]['research_answers']['items']
        self.assertEqual(final_answer['value']['model_claimed_coverage'], 'claimed_complete')
        self.assertEqual(planner.packets[-1]['consecutive_no_progress'], 0)
        revision_receipt = json.loads((output / result['trace'][-2]['receipt']).read_text())
        self.assertIs(revision_receipt['progress_delta'], True)

    def test_old_scope_context_cannot_answer_new_scope_requirement(self):
        self.open_dataset()
        new_dataset = self.root / 'new-dataset'
        new_dataset.mkdir()
        make_scoped_dataset(new_dataset)
        manifest_path = new_dataset / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['snapshot_id'] = 'second-explicit-snapshot'
        manifest_path.write_text(json.dumps(manifest))
        new_port = QueryDataPort(new_dataset)
        self.addCleanup(new_port.close)
        next_scope = self.scope.model_copy(update={'snapshot_id': new_port.snapshot_id})
        state = {}

        def materialize(arguments, *, scope, output):
            return {'port': new_port, 'scope': next_scope}

        def save_context(packet):
            state['context_id'] = packet['observation']['evidence_ids'][0]
            return {'action': 'materialize', 'requirement_ids': ['business'], 'arguments': {}}

        def replan(packet):
            self.assertEqual(packet['active_scope'], next_scope.model_dump(mode='json'))
            plan = answer_plan()
            plan['requirements'].extend(answer_plan(requirement='refreshed')['requirements'])
            return plan

        def stale_answer(packet):
            rows = {row['requirement_id']: row for row in packet['coverage']}
            self.assertEqual(rows['business']['source_scope'], self.request['scope'])
            self.assertEqual(rows['refreshed']['source_scope'], next_scope.model_dump(mode='json'))
            return answer_action(state['context_id'], requirement='refreshed', include_future=True)

        result, _, output = self.run_actions([
            answer_plan(), read(), save_context, replan, stale_answer], materialize=materialize)
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertEqual(self.candidates(output), [])

    def test_rewording_statements_with_identical_citations_is_not_progress(self):
        self.open_dataset()
        state = {'version': 0}

        def answer(packet):
            if 'context_id' not in state:
                state['context_id'] = packet['observation']['evidence_ids'][0]
            value = answer_action(state['context_id'], include_future=True)
            state['version'] += 1
            value['answer']['claims'][0]['statement'] += f" Rewording {state['version']}."
            return value

        result, _, output = self.run_actions([
            answer_plan(), read(), answer, answer, answer, answer, {'action': 'finish'}])
        self.assertEqual(result['stop_reason'], 'no_progress_limit', result['trace'])
        self.assertEqual([step['consecutive_no_progress'] for step in result['trace'][-3:]], [1, 2, 3])
        for step in result['trace'][-3:]:
            receipt = json.loads((output / step['receipt']).read_text())
            self.assertIs(receipt['progress_delta'], False)
        self.assertTrue(self.candidates(output))


if __name__ == '__main__':
    unittest.main()
