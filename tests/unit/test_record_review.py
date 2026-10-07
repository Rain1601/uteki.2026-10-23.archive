"""Independent offline checks of review evidence boundaries, not LLM quality."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.record_review import build_review_packets, validate_assessment
from uteki.infrastructure.research_data.semantic_review import validate_dataset_binding
from tests.unit.test_company_materialization import filing


class RecordReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        raw = filing().replace(b'<table>', b'''<p>NOTE 1 - Measurement</p>
            <p>Prior periods were recast. In USD millions, year ended June 30, 2025.</p>
            <p>Unrelated count: 120 customers.</p><table>''', 1).replace(
                b'</table>', b'''</table><p>(a)</p><p>Figures exclude discontinued operations.</p>
                <p>Refer to Note 2.</p><p>NOTE 2 - Other disclosure</p>''', 1)
        (self.root/'source.html').write_bytes(raw)
        source = {'company': {'company_id': 'sec-0000000123', 'cik': '0000000123'},
            'as_of': '2025-09-01', 'documents': [{'source_id': 'fixture-annual',
                'source_url': 'https://example.test/annual', 'form': '10-K',
                'filed_at': '2025-08-01', 'period_end': '2025-06-30',
                'content_sha256': digest(raw), 'path': 'source.html',
                'mime_type': 'text/html', 'status': 'frozen'}]}
        self.dataset = self.root/'dataset'
        manifest = materialize_sources(source, self.root, self.dataset)
        self.scope = {'snapshot_id': manifest['snapshot_id'], 'company_ids': ['sec-0000000123'],
            'source_snapshot_ids': ['fixture-annual'], 'source_policy_id': 'local-frozen-v1',
            'knowledge_cutoff': '2025-09-01', 'include_candidates': True}
        self.ids = [r['record_id'] for r in json.loads((self.dataset/'records.json').read_text())['rows']]
        self.output = self.root/'review'
        self.manifest = build_review_packets(self.dataset, self.scope, self.ids, self.output)
        self.packet = json.loads((self.output/self.manifest['packets'][0]['path']).read_text())

    def assessment(self):
        return {'packet_id': self.packet['packet_id'], 'records': [{
            'record_id': item['record']['record_id'], 'verdict': 'supported',
            'checks': {k: 'supported' for k in ('metric', 'period', 'value_unit_scale_sign',
                                               'entity_dimensions', 'qualifiers')},
            'reason': 'Synthetic source comparison.', 'citations': [{
                'source_snapshot_id': item['record']['source_snapshot_id'],
                'block_id': item['evidence']['block_id'], 'quote': item['evidence']['quote']}],
        } for item in self.packet['records']]}

    def test_context_retains_source_html_table_note_and_explicit_unresolved_reference(self):
        texts = [b['text'] for b in self.packet['source_blocks']]
        self.assertIn('Figures exclude discontinued operations.', texts)
        self.assertTrue(any('Prior periods were recast' in t for t in texts))
        self.assertIn('Note 2', self.packet['unresolved_note_references'])
        target = next(b for b in self.packet['source_blocks'] if b['block_id'] == self.packet['target_block_id'])
        self.assertTrue(target['table']['cells'])
        fragment = next(f for f in self.packet['source_fragments'] if f['block_id'] == target['block_id'])
        original = (self.output/fragment['original_fragment_path']).read_bytes()
        self.assertEqual(digest(original), fragment['original_fragment_sha256'])
        self.assertIn('contextref="c"', fragment['compact_html'])
        self.assertEqual(validate_assessment(self.packet, self.assessment())['records'][0]['verdict'], 'supported')

    def test_parser_version_is_carried_and_bound_to_selected_index(self):
        source = json.loads((self.dataset/'sources.json').read_text())[0]
        index = json.loads((self.dataset/source['index_folder']/'index.json').read_text())
        self.assertEqual(self.packet['parser_version'], index['parser_version'])
        validate_dataset_binding(self.packet, self.dataset, artifact_root=self.output)
        changed = deepcopy(self.packet)
        changed['parser_version'] = 'sec-source-blocks-v0.1.12'
        with self.assertRaisesRegex(ValueError, 'parser version differs'):
            validate_dataset_binding(changed, self.dataset)

    def test_invented_quote_wrong_source_and_unknown_block_are_rejected(self):
        for update in ({'quote': 'invented disclosure'}, {'source_snapshot_id': 'other-company'},
                       {'block_id': 'unknown-block'}):
            value = self.assessment(); value['records'][0]['citations'][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_assessment(self.packet, value)

    def test_missing_duplicate_unknown_record_and_wrong_packet_are_rejected(self):
        for change in ('missing', 'duplicate', 'unknown', 'packet'):
            value = self.assessment()
            if change == 'missing': value['records'].pop()
            elif change == 'duplicate': value['records'].append(deepcopy(value['records'][0]))
            elif change == 'unknown': value['records'][0]['record_id'] = 'unknown-record'
            else: value['packet_id'] = 'wrong-packet'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_assessment(self.packet, value)

    def test_supported_cannot_contradict_a_field_check(self):
        value = self.assessment(); value['records'][0]['checks']['period'] = 'contradicted'
        with self.assertRaises(ValueError): validate_assessment(self.packet, value)

    def test_supported_requires_number_from_original_fact_block(self):
        value = self.assessment()
        index = next(i for i, item in enumerate(self.packet['records']) if item['evidence']['quote'] == '120')
        neighbor = next(b for b in self.packet['source_blocks'] if '120 customers' in b['text'])
        value['records'][index]['citations'] = [{'source_snapshot_id': neighbor['source_snapshot_id'],
                                               'block_id': neighbor['block_id'], 'quote': neighbor['text']}]
        with self.assertRaises(ValueError): validate_assessment(self.packet, value)

    def test_packet_and_record_hash_tampering_are_rejected(self):
        packet = deepcopy(self.packet); packet['source_blocks'][0]['text'] += ' altered'
        with self.assertRaises(ValueError): validate_assessment(packet, self.assessment())
        packet = deepcopy(self.packet); packet['records'][0]['record']['value_decimal'] = '999'
        packet['packet_id'] = 'review-'+digest({k: v for k, v in packet.items() if k != 'packet_id'})[:24]
        value = self.assessment(); value['packet_id'] = packet['packet_id']
        with self.assertRaises(ValueError): validate_assessment(packet, value)

    def test_build_rejects_wrong_scope_before_writing(self):
        changes = [{'company_ids': ['sec-0000000999']}, {'source_snapshot_ids': ['other-source']},
                   {'snapshot_id': 'wrong-snapshot'}, {'knowledge_cutoff': '2025-07-01'},
                   {'include_candidates': False}, {'entity_ids': ['other']}, {'periods': []}]
        for i, update in enumerate(changes):
            output = self.root/f'rejected-{i}'
            with self.subTest(update=update), self.assertRaises(ValueError):
                build_review_packets(self.dataset, {**self.scope, **update}, self.ids, output)
            self.assertFalse(output.exists())

    def test_build_rejects_missing_duplicate_unknown_ids_and_frozen_output(self):
        for i, ids in enumerate(([], self.ids + self.ids[:1], ['unknown-record'])):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                build_review_packets(self.dataset, self.scope, ids, self.root/f'bad-ids-{i}')
        with self.assertRaises(ValueError):
            build_review_packets(self.dataset, self.scope, self.ids, self.dataset/'review')
        self.assertFalse((self.dataset/'review').exists())

    def test_dataset_file_tampering_is_rejected(self):
        path = self.dataset/'evidence.json'; path.write_text('{}')
        with self.assertRaises(ValueError):
            build_review_packets(self.dataset, self.scope, self.ids, self.root/'tampered')

    def test_preparation_has_no_model_verdict_or_fact_mutation(self):
        rows = json.loads((self.dataset/'records.json').read_text())['rows']
        self.assertEqual(self.manifest['status'], 'prepared_not_reviewed')
        self.assertEqual(self.manifest['model_calls'], 0)
        self.assertEqual(self.manifest['record_ids'], self.ids)
        self.assertTrue(all(row['status'] == 'candidate' for row in rows))
