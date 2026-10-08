"""Bounded original-evidence handoff checks; all model roles are offline fixtures."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from uteki.agents.data_query.answer_handoff import (
    load_reviewed_data, prepare_review_packet, review_data_answer,
)
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort
from tests.unit import test_answer_handoff as fixtures
from tests.unit import test_answer_handoff_records as record_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_task_completion import pin_dataset


def narrow_assessment(packet, *, insufficient=False):
    quote = {key: packet['facts'][0]['citations'][0][key]
             for key in ('source_snapshot_id', 'block_id', 'quote')} if packet['facts'] else None
    return {'packet_id': packet['packet_id'],
        'facts': [{'fact_id': f['fact_id'], 'verdict': 'supported',
                   'rationale': 'An original source block, not an invented assertion.',
                   'citations': [{key: f['citations'][0][key] for key in ('source_snapshot_id', 'block_id', 'quote')}]}
                  for f in packet['facts']],
        'requirements': [{'requirement_id': r['requirement_id'],
            'verdict': 'insufficient_evidence' if insufficient else 'complete',
            'rationale': 'Check the original question against the selected evidence.',
            'citations': [quote] if quote else []} for r in packet['requirements']],
        'source_checks': [{'source_snapshot_id': d['source_snapshot_id'],
            'verdict': 'requires_more_source_content' if insufficient else 'text_sufficient',
            'rationale': 'Only evidence for this narrow question was reviewed.',
            'citations': [quote] if quote else []} for d in packet['source_documents']],
        'question_coverage': 'incomplete' if insufficient else 'complete',
        'coverage_reason': 'Narrow question evidence assessment.',
        'missing_information': ['Additional source context is needed.'] if insufficient else [],
        'limitations': ['Scripted fixture; no model quality or source-wide completeness claim.']}


class BoundedAnswerHandoffTests(unittest.TestCase):
    setUp = fixtures.AnswerHandoffTests.setUp

    def prepare(self, output, **options):
        return prepare_review_packet(output, self.dataset, expected_scope=options.pop('expected_scope', self.scope),
            max_packet_bytes=options.pop('max_packet_bytes', 100_000),
            source_delivery=options.pop('source_delivery', 'query_evidence_v1'), **options)

    def raw_query(self, *, read=True, duplicate=False, block='b1'):
        actions = [source_plan()]
        if read:
            actions += [context_read(block=block)] * (2 if duplicate else 1)
        actions.append({'action': 'finish'})
        output = self.root / 'raw-query'
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, ScriptedPlanner(actions),
                limits={'max_steps': len(actions), 'max_packet_bytes': 64000}).run(
                    {'question': 'Return the original actual investment disclosure in 2031.',
                     'scope': self.scope.model_dump(mode='json')}, output=output))
        return result, output

    def review(self, packet, *, insufficient=False):
        output = self.root / 'bounded-review'
        role = fixtures.ScriptedRole(lambda p: narrow_assessment(p, insufficient=insufficient))
        result = asyncio.run(review_data_answer(packet, output, reviewer_factory=lambda path: role))
        return result, output

    def load(self, output, result):
        return load_reviewed_data(output, expected_scope=self.scope, allow_fixture=True,
            expected_review_manifest_sha256=result['review_ref']['manifest_sha256'])

    def enlarge_unread_block(self):
        folder = self.dataset / 'indexes/acme-annual'
        path = folder / 'blocks.jsonl'
        blocks = [json.loads(line) for line in path.read_text().splitlines()]
        blocks[4]['text'] = 'Unrelated unread disclosure. ' * 20_000
        path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        pin_dataset(self.dataset)

    def test_raw_selected_evidence_reaches_analysis_without_unread_large_source(self):
        self.enlarge_unread_block()
        result, output = self.raw_query(duplicate=True)
        self.assertEqual(result['status'], 'evidence_ready')
        # Whole-document navigation must never be needed in bounded mode.
        with patch.object(ScopedQueryDataPort, 'outline_source', side_effect=AssertionError('whole source traversal')):
            packet = self.prepare(output)
            reviewed, review = self.review(packet)
            handoff = self.load(review, reviewed)
        self.assertEqual(reviewed['status'], 'reviewed', reviewed)
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual([b['block_id'] for b in packet['source_documents'][0]['blocks']], ['b1'])
        self.assertEqual([f['kind'] for f in packet['facts']], ['source_block'])
        self.assertEqual(handoff['source_documents'], packet['source_documents'])
        self.assertEqual(handoff['source_delivery'], 'query_evidence_v1')
        self.assertIn('unselected source text', handoff['limitations'][1])
        self.assertNotIn('Unrelated unread', json.dumps(handoff))
        self.assertEqual(handoff['facts'][0]['citations'][0]['source_sha256'], digest('acme-annual'))

    def test_source_answer_claims_use_bounded_originals_and_legacy_stays_unchanged(self):
        _, output = fixtures.AnswerHandoffTests.query(self)
        bounded = self.prepare(output)
        legacy = self.prepare(output, source_delivery='full_indexed_text_v1', max_packet_bytes=1_000_000)
        default = prepare_review_packet(output, self.dataset, expected_scope=self.scope, max_packet_bytes=1_000_000)
        self.assertEqual(default, legacy)
        self.assertNotIn('source_delivery', legacy)
        self.assertEqual(len(legacy['source_documents'][0]['blocks']), 10)
        self.assertEqual(len(bounded['source_documents'][0]['blocks']), 3)
        self.assertEqual(bounded['program_gaps'], [])
        self.assertEqual([f['kind'] for f in bounded['facts']], ['source_claim', 'source_claim'])

    def test_structured_records_reopen_only_cited_originals_across_company_and_period(self):
        numeric = record_fixtures.AnswerHandoffRecordTests()
        numeric.setUp()
        self.addCleanup(numeric.doCleanups)
        for company, period in (('acme', 2030), ('other', 2031)):
            with self.subTest(company=company, period=period):
                output, scope = numeric.query(name=f'{company}-{period}', company=company, period_year=period)
                packet = prepare_review_packet(output, numeric.dataset, expected_scope=scope,
                    max_packet_bytes=100_000, source_delivery='query_evidence_v1')
                self.assertEqual(packet['program_gaps'], [])
                self.assertEqual(packet['facts'][0]['value']['entity_id'], company + '-services')
                self.assertEqual({d['company_id'] for d in packet['source_documents']}, {company})
                self.assertLess(len(packet['source_documents'][0]['blocks']), 10)
                self.assertIn(f'{period}-12-31', packet['facts'][0]['citations'][0]['quote'])

    def test_complete_coverage_with_trimming_request_is_valid_needs_revision(self):
        _, output = self.raw_query()
        packet = self.prepare(output)
        def respond(value):
            response = narrow_assessment(value)
            response['revision_requests'] = ['Remove duplicated context while retaining the necessary source.']
            return response
        result = asyncio.run(review_data_answer(packet, self.root/'trim-review',
            reviewer_factory=lambda path: fixtures.ScriptedRole(respond)))
        self.assertEqual(result['status'], 'needs_revision', result)
        self.assertEqual(result['failures'], [])
        self.assertFalse(result['analysis_eligible'])
        self.assertEqual(result['assessment']['question_coverage'], 'complete')
        self.assertEqual(result['assessment']['missing_information'], [])
        self.assertEqual(len(result['assessment']['revision_requests']), 1)

    def test_cap_and_unknown_delivery_fail_explicitly(self):
        _, output = self.raw_query()
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.prepare(output, max_packet_bytes=1024)
        with self.assertRaisesRegex(ValueError, 'unsupported source delivery'):
            self.prepare(output, source_delivery='truncate_anything')

    def test_scope_changes_reject(self):
        _, output = self.raw_query()
        for change in ({'company_ids': ['other'], 'source_snapshot_ids': ['other-annual']},
                       {'knowledge_cutoff': '2032-04-30'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'scope'):
                self.prepare(output, expected_scope={**self.scope.model_dump(mode='json'), **change})

    def test_resealed_tampered_context_rejected_against_original(self):
        _, output = self.raw_query()
        bundle_path = output / 'evidence-bundle.json'
        bundle = json.loads(bundle_path.read_text())
        item = next(i for i in bundle['items'] if i['kind'] == 'context')
        path = output / item['artifact']['path']
        context = json.loads(path.read_text())
        context['blocks'][0]['text'] = 'Forged original material.'
        path.write_text(json.dumps(context))
        item['artifact'].update(sha256=digest(path.read_bytes()), size_bytes=path.stat().st_size)
        item['sha256'] = digest({'kind': item['kind'], 'value': context, 'scope': item['scope']})
        index_path = output / 'artifact-index.json'
        index = json.loads(index_path.read_text())
        for ref in index:
            if ref['artifact_id'] == item['artifact']['artifact_id']:
                ref.update(item['artifact'])
        index_path.write_text(json.dumps(index))
        bundle['bundle_id'] = 'bundle-' + digest({k: v for k, v in bundle.items() if k != 'bundle_id'})[:24]
        bundle_path.write_text(json.dumps(bundle))
        result_path = output / 'result.json'
        result = json.loads(result_path.read_text())
        result['evidence_bundle']['bundle_id'] = bundle['bundle_id']
        result_path.write_text(json.dumps(result))
        pin_dataset(output)
        with self.assertRaisesRegex(ValueError, 'differs from original'):
            self.prepare(output)

    def test_no_body_or_insufficient_selection_cannot_enter_analysis(self):
        _, output = self.raw_query(read=False)
        packet = self.prepare(output)
        self.assertIn('no_reviewable_facts', packet['program_gaps'])
        result, review = self.review(packet)
        self.assertFalse(result['analysis_eligible'])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.load(review, result)

    def test_model_detected_missing_evidence_blocks_analysis_even_with_valid_raw_fact(self):
        _, output = self.raw_query()
        packet = self.prepare(output)
        result, review = self.review(packet, insufficient=True)
        self.assertEqual(result['status'], 'needs_revision', result)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.load(review, result)

    def test_atomic_table_context_preserves_units_and_notes(self):
        _, output = self.raw_query(block='b8')
        packet = self.prepare(output)
        ids = {b['block_id'] for b in packet['source_documents'][0]['blocks']}
        self.assertEqual(ids, {'b7', 'b8', 'b9'})
        self.assertIn('Numbers in millions', json.dumps(packet))
        self.assertIn('exclude discontinued', json.dumps(packet))


if __name__ == '__main__':
    unittest.main()
