"""Offline semantic-review boundary checks; no model or expected-answer injection."""
from copy import deepcopy
import json
import unittest

from uteki.domain.research_data.semantic_review import SemanticTask
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import (
    prepare_semantic_inputs, validate_semantic_packet, validate_semantic_assessment, validate_dataset_binding,
)
from tests.unit import test_record_review as record_review_fixture


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = record_review_fixture.RecordReviewTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.dataset = self.fixture.root, self.fixture.dataset
        source, = json.loads((self.dataset/'sources.json').read_text())
        blocks = [json.loads(line) for line in (self.dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines()]
        included = {b['block_id'] for b in self.fixture.packet['source_blocks']}
        self.extra = next(b for b in blocks if b['block_id'] not in included and b.get('dom_path'))
        self.task = {'task_id': 'synthetic-semantics', 'record_ids': self.fixture.ids,
            'axes': ['comparability', 'allocation'], 'additional_block_ids': [self.extra['block_id']],
            'assertions': [{'assertion_id': 'claim-a', 'record_ids': self.fixture.ids,
                            'text': 'The displayed revenue is 120 million USD.'}]}
        self.output = self.root/'semantics'
        self.spec = prepare_semantic_inputs(self.fixture.output, [self.task], self.output)
        self.packet = json.loads((self.output/self.spec['packets'][0]['path']).read_text())

    @staticmethod
    def reseal(packet):
        packet['packet_id'] = 'semantic-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]
        return packet

    def citation(self):
        block = next(b for b in self.packet['source_blocks'] if 'Prior periods were recast' in b['text'])
        return {'source_snapshot_id': block['source_snapshot_id'], 'block_id': block['block_id'],
                'quote': block['text'], 'source_start': 0}

    def assessment(self):
        return {'packet_id': self.packet['packet_id'], 'checks': [
            {'axis': 'comparability', 'status': 'constraints_found', 'reason': 'Source states a recast.',
             'constraints': [{'record_ids': self.fixture.ids, 'statement': 'Use the disclosed recast basis.',
                              'citations': [self.citation()]}]},
            {'axis': 'allocation', 'status': 'insufficient_evidence', 'reason': 'Missing referenced detail.',
             'unresolved_questions': ['What does the referenced Note 2 specify?']}],
            'assertions': [{'assertion_id': 'claim-a', 'verdict': 'insufficient_evidence',
                            'reason': 'This fixture assessment does not establish every clause.'}]}

    def test_added_context_has_frozen_fragment_and_matching_source_hash(self):
        validate_semantic_packet(self.packet)
        self.assertIn(self.extra['block_id'], {b['block_id'] for b in self.packet['source_blocks']})
        fragment = next(f for f in self.packet['source_fragments'] if f['block_id'] == self.extra['block_id'])
        self.assertEqual(digest((self.output/fragment['original_fragment_path']).read_bytes()), fragment['original_fragment_sha256'])
        source, = json.loads((self.dataset/'sources.json').read_text())
        self.assertEqual(digest((self.dataset/source['raw_file']).read_bytes()), self.packet['source']['source_sha256'])
        self.assertEqual(self.packet['metric_definitions']['revenue']['unit'], 'USD')
        self.assertEqual(validate_semantic_assessment(self.packet, self.assessment())['checks'][0]['status'], 'constraints_found')

    def test_missing_context_is_explicit_and_cannot_be_empty_insufficiency(self):
        references = [item['quote'] for item in self.packet['context_inventory']['objects']
                      if item['kind'] == 'source_reference']
        self.assertIn('Note 2', references)
        self.assertNotIn('unresolved_note_references', self.packet)
        value = self.assessment(); value['checks'][1]['unresolved_questions'] = []
        with self.assertRaises(ValueError): validate_semantic_assessment(self.packet, value)

    def test_axis_missing_unknown_duplicate_and_unrequested_are_rejected(self):
        for mode in ('missing', 'unknown', 'duplicate', 'unrequested'):
            value = self.assessment()
            if mode == 'missing': value['checks'].pop()
            elif mode == 'duplicate': value['checks'].append(deepcopy(value['checks'][0]))
            else: value['checks'][1]['axis'] = 'nonsense' if mode == 'unknown' else 'geography'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_assessment(self.packet, value)

    def test_constraint_record_scope_and_exact_quotes_are_enforced(self):
        for mode in ('unknown-record', 'duplicate-record', 'wrong-source', 'unknown-block', 'false-quote', 'blank-quote'):
            value = self.assessment(); c = value['checks'][0]['constraints'][0]
            if mode == 'unknown-record': c['record_ids'] = ['unknown']
            elif mode == 'duplicate-record': c['record_ids'] += c['record_ids'][:1]
            elif mode == 'wrong-source': c['citations'][0]['source_snapshot_id'] = 'other-source'
            elif mode == 'unknown-block': c['citations'][0]['block_id'] = 'unknown'
            else: c['citations'][0]['quote'] = ' ' if mode == 'blank-quote' else 'Invented allocation details.'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_assessment(self.packet, value)

    def test_assertion_coverage_and_noninsufficient_citations_are_required(self):
        for mode in ('missing', 'duplicate', 'unknown', 'unsupported'):
            value = self.assessment()
            if mode == 'missing': value['assertions'] = []
            elif mode == 'duplicate': value['assertions'] *= 2
            elif mode == 'unknown': value['assertions'][0]['assertion_id'] = 'unknown'
            else: value['assertions'][0]['verdict'] = 'supported'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_assessment(self.packet, value)

    def test_task_rejects_answer_keys_and_outside_assertion_records(self):
        for update in ({'expected_constraints': []}, {'expected_verdict': 'supported'},
                       {'record_ids': self.fixture.ids*2}, {'axes': ['comparability']*2},
                       {'assertions': [{'assertion_id': 'claim', 'record_ids': ['outside'], 'text': 'Claim'}]}):
            with self.subTest(update=update), self.assertRaises(ValueError): SemanticTask.model_validate({**self.task, **update})

    def test_packet_record_and_block_hashes_and_cross_source_are_enforced(self):
        for mode in ('packet', 'record', 'block', 'record-source', 'block-source', 'scope'):
            packet = deepcopy(self.packet)
            if mode == 'packet': packet['axes'] = ['allocation']
            elif mode == 'record': packet['records'][0]['record']['value_decimal'] = '999'
            elif mode == 'block': packet['source_blocks'][0]['text'] += ' invented'
            elif mode == 'record-source':
                packet['records'][0]['record']['source_snapshot_id'] = 'other'
                packet['records'][0]['record_sha256'] = digest(packet['records'][0]['record'])
            elif mode == 'block-source': packet['source_blocks'][0]['source_snapshot_id'] = 'other'
            else: packet['scope']['company_ids'] = ['other-company']
            if mode != 'packet': self.reseal(packet)
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_semantic_packet(packet)

    def test_evidence_source_and_hash_must_match_packet_source(self):
        for update in ({'source_snapshot_id': 'other-source'}, {'source_sha256': '0'*64}):
            packet = deepcopy(self.packet); packet['records'][0]['evidence'].update(update)
            self.reseal(packet)
            with self.subTest(update=update), self.assertRaises(ValueError): validate_semantic_packet(packet)

    def test_self_consistent_tampering_cannot_replace_frozen_source_evidence(self):
        for mode in ('source-hash', 'record', 'evidence', 'metric', 'text', 'table', 'compact-html', 'fragment-hash', 'anchor'):
            packet = deepcopy(self.packet)
            if mode == 'source-hash':
                packet['source']['source_sha256'] = '0'*64
                for item in packet['records']: item['evidence']['source_sha256'] = '0'*64
            elif mode == 'record':
                packet['records'][0]['record']['value_decimal'] = '999'
                packet['records'][0]['record_sha256'] = digest(packet['records'][0]['record'])
            elif mode == 'evidence': packet['records'][0]['evidence']['quote'] = '999'
            elif mode == 'metric': packet['metric_definitions']['revenue']['definition'] = 'Invented definition'
            elif mode == 'text':
                packet['source_blocks'][0]['text'] = 'Invented source sentence.'
                packet['source_blocks'][0]['text_hash'] = digest(packet['source_blocks'][0]['text'].encode())
            elif mode == 'table':
                table = next(b['table'] for b in packet['source_blocks'] if b.get('table'))
                table['cells'][0][-1] = 'Invented row'
            elif mode == 'compact-html':
                fragment = next(f for f in packet['source_fragments'] if f.get('compact_html'))
                fragment['compact_html'] = '<p>Invented source HTML</p>'
            elif mode == 'anchor':
                anchor = next(a for a in packet['record_anchors'].values() if a['status'] == 'located')
                anchor['start'] += 1
                anchor['text'] = anchor['text'][1:]
            else: packet['source_fragments'][0]['original_fragment_sha256'] = '0'*64
            self.reseal(packet)
            validate_semantic_packet(packet)
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_dataset_binding(packet, self.dataset)

    def test_unknown_added_block_and_frozen_output_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare_semantic_inputs(self.fixture.output, [{**self.task, 'additional_block_ids': ['other-source-block']}], self.root/'bad-added')
        for output in (self.fixture.output/'nested', self.dataset/'nested'):
            with self.assertRaises(ValueError): prepare_semantic_inputs(self.fixture.output, [self.task], output)
            self.assertFalse(output.exists())

    def test_changed_original_bytes_are_rejected_before_new_output(self):
        source, = json.loads((self.dataset/'sources.json').read_text())
        (self.dataset/source['raw_file']).write_bytes(b'<html>changed original</html>')
        output = self.root/'tampered'
        with self.assertRaises(ValueError): prepare_semantic_inputs(self.fixture.output, [self.task], output)
        self.assertFalse(output.exists())
