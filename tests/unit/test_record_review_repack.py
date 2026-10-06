"""Repacking preserves frozen evidence and creates bounded, independently sealed inputs."""
import json
import unittest

from tests.unit import test_record_review_run as run_fixture
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.record_review import build_review_packets, validate_assessment
from uteki.infrastructure.research_data.record_review_repack import repack_review_inputs


class RecordReviewRepackTests(unittest.TestCase):
    setUp = run_fixture.RecordReviewRunTests.setUp
    frozen_hashes = run_fixture.RecordReviewRunTests.frozen_hashes

    def repack(self, **kwargs):
        return repack_review_inputs(self.inputs, self.ids, self.root/'repacked', **kwargs)

    def packet(self, result, index=0):
        return json.loads((self.root/'repacked'/result['packets'][index]['path']).read_text())

    def test_preserves_records_context_fragments_and_sealed_parent_reference(self):
        result = self.repack()
        original = json.loads((self.inputs/self.spec['packets'][0]['path']).read_text())
        packet = self.packet(result)
        self.assertEqual(packet['schema_version'], 'record-review-input-v2')
        self.assertEqual(packet['records'], original['records'])
        self.assertEqual(packet['source_blocks'], original['source_blocks'])
        self.assertEqual(packet['source_fragments'], original['source_fragments'])
        self.assertEqual(packet['target_block_ids'], [original['target_block_id']])
        self.assertNotIn('target_block_id', packet)
        self.assertEqual(result['parent_inputs']['manifest_sha256'], digest((self.inputs/'manifest.json').read_bytes()))
        self.assertEqual(result['dataset_manifest_sha256'], self.spec['dataset_manifest_sha256'])
        self.assertEqual(result['model_calls'], 0)
        validate_assessment(packet, run_fixture.supported(packet))
        _verify_manifest(self.root/'repacked')
        for fragment in packet['source_fragments']:
            name = fragment['original_fragment_path']
            self.assertEqual((self.inputs/name).read_bytes(), (self.root/'repacked'/name).read_bytes())
        self.assertEqual(self.frozen_hashes(), self.before)

    def test_merges_separate_packets_without_duplicate_context(self):
        separate = self.root/'separate'
        spec = build_review_packets(self.dataset, self.spec['scope'], self.ids, separate, batch_size=1)
        self.assertEqual(len(spec['packets']), 2)
        result = repack_review_inputs(separate, self.ids, self.root/'repacked')
        self.assertEqual(len(result['packets']), 1)
        packet = self.packet(result)
        self.assertEqual(len(packet['records']), 2)
        for key in ('source_blocks', 'source_fragments'):
            self.assertEqual(len(packet[key]), len({b['block_id'] for b in packet[key]}))

    def test_selects_explicit_subset_and_retains_original_record_order(self):
        result = repack_review_inputs(self.inputs, [self.ids[1]], self.root/'repacked')
        self.assertEqual(result['record_ids'], [self.ids[1]])
        self.assertEqual([r['record']['record_id'] for r in self.packet(result)['records']], [self.ids[1]])
        metrics = json.loads((self.dataset/'metrics.json').read_text())
        metric_id = self.rows[1]['metric_id']
        self.assertEqual(self.packet(result)['metric_definitions'], {metric_id: metrics[metric_id]})
        second = repack_review_inputs(self.inputs, list(reversed(self.ids)), self.root/'ordered')
        packet = json.loads((self.root/'ordered'/second['packets'][0]['path']).read_text())
        self.assertEqual([r['record']['record_id'] for r in packet['records']], self.ids)

    def test_multiple_targets_keep_all_context_and_nonempty_target_html(self):
        raw = run_fixture.filing().replace(b'<tr><td>Operating income',
            b'</table><p>Accompanying notes apply to both tables.</p><table><tr><td>Operating income')
        raw = raw.replace(b'us-gaap:OperatingIncomeLoss', b'us-gaap:PaymentsToAcquirePropertyPlantAndEquipment')
        (self.root/'multiple.html').write_bytes(raw)
        run = {'company': {'company_id': 'sec-0000000123', 'cik': '0000000123'},
               'as_of': '2025-09-01', 'documents': [{'source_id': 'multiple',
                   'source_url': 'https://example.invalid/multiple.html', 'form': '10-K',
                   'filed_at': '2025-08-01', 'period_end': '2025-06-30', 'content_sha256': digest(raw),
                   'path': 'multiple.html', 'mime_type': 'text/html', 'status': 'frozen'}]}
        dataset, inputs = self.root/'multiple-dataset', self.root/'multiple-inputs'
        manifest = materialize_sources(run, self.root, dataset)
        ids = [row['record_id'] for row in json.loads((dataset/'records.json').read_text())['rows']]
        scope = {**self.spec['scope'], 'snapshot_id': manifest['snapshot_id'], 'source_snapshot_ids': ['multiple']}
        spec = build_review_packets(dataset, scope, ids, inputs)
        originals = [json.loads((inputs/p['path']).read_text()) for p in spec['packets']]
        self.assertEqual(len(originals), 2)
        result = repack_review_inputs(inputs, ids, self.root/'repacked')
        packet = self.packet(result)
        metrics = json.loads((dataset/'metrics.json').read_text())
        self.assertEqual(packet['metric_definitions'],
                         {key: metrics[key] for key in ('revenue', 'capex_cash_payments')})
        self.assertEqual(packet['metric_definitions']['capex_cash_payments']['definition'],
                         'Positive cash payments to acquire PPE; not total investment.')
        self.assertEqual(packet['target_block_ids'], [p['target_block_id'] for p in originals])
        self.assertEqual(packet['records'], [item for p in originals for item in p['records']])
        blocks = {b['block_id']: b for b in packet['source_blocks']}
        fragments = {f['block_id']: f for f in packet['source_fragments']}
        for original in originals:
            for block in original['source_blocks']: self.assertEqual(blocks[block['block_id']], block)
            self.assertTrue(fragments[original['target_block_id']]['compact_html'])
        self.assertEqual(set(packet['unresolved_note_references']),
                         {r for p in originals for r in p['unresolved_note_references']})
        validate_assessment(packet, run_fixture.supported(packet))

    def test_batch_limit_and_compact_bytes_split_packets(self):
        result = self.repack(batch_size=1)
        self.assertEqual(len(result['packets']), 2)
        maximum = max((self.root/'repacked'/ref['path']).stat().st_size for ref in result['packets'])
        other = repack_review_inputs(self.inputs, self.ids, self.root/'byte-limited', max_packet_bytes=maximum)
        self.assertEqual(len(other['packets']), 2)
        for ref in other['packets']:
            self.assertLessEqual((self.root/'byte-limited'/ref['path']).stat().st_size, maximum)
        with self.assertRaisesRegex(ValueError, 'single record context'):
            repack_review_inputs(self.inputs, self.ids, self.root/'too-small', max_packet_bytes=1)
        self.assertFalse((self.root/'too-small').exists())

    def test_invalid_selection_limits_and_output_are_rejected_before_writing(self):
        for ids in ([], self.ids*2, ['unknown']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                repack_review_inputs(self.inputs, ids, self.root/'invalid')
        for size in (0, 25, True):
            with self.subTest(size=size), self.assertRaises(ValueError): self.repack(batch_size=size)
        for output in (self.inputs, self.inputs/'nested', self.dataset/'nested'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                repack_review_inputs(self.inputs, self.ids, output)
        result = self.repack()
        with self.assertRaises(FileExistsError): self.repack()
        self.assertEqual(self.frozen_hashes(), self.before)
        self.assertEqual(len(result['packets']), 1)

    def test_tampered_parent_packet_is_rejected(self):
        path = self.inputs/self.spec['packets'][0]['path']
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'): self.repack()
        self.assertFalse((self.root/'repacked').exists())

    def test_tampered_dataset_is_rejected(self):
        path = self.dataset/'records.json'
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'): self.repack()
        self.assertFalse((self.root/'repacked').exists())

    def test_sealed_dataset_with_missing_selected_definition_is_rejected(self):
        path = self.dataset/'metrics.json'
        metrics = json.loads(path.read_text())
        metrics[self.rows[0]['metric_id']].pop('definition')
        path.write_text(json.dumps(metrics))
        dataset_manifest_path = self.dataset/'manifest.json'
        dataset_manifest = json.loads(dataset_manifest_path.read_text())
        dataset_manifest['files']['metrics.json'] = digest(path.read_bytes())
        dataset_manifest_path.write_text(json.dumps(dataset_manifest))
        spec_path = self.inputs/'input-manifest.json'
        spec = json.loads(spec_path.read_text())
        spec['dataset_manifest_sha256'] = digest(dataset_manifest_path.read_bytes())
        spec_path.write_text(json.dumps(spec))
        manifest_path = self.inputs/'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['input-manifest.json'] = digest(spec_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'metric definition is missing'): self.repack()
        self.assertFalse((self.root/'repacked').exists())


if __name__ == '__main__': unittest.main()
