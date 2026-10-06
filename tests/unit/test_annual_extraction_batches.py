"""Document-order batching leaves other tables and prose explicitly pending."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT/'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1'
sys.path.insert(0, str(FOLDER))
try:
    spec = importlib.util.spec_from_file_location('annual_batch_canary', FOLDER/'run_extractor_batch_canary.py')
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
finally:
    sys.path.pop(0)


class AnnualBatchTests(unittest.TestCase):
    def packet(self):
        blocks = [{'block_id': str(n), 'ordinal': n, 'type': kind, 'text': f'Independent source {n}'}
                  for n, kind in [(40, 'paragraph'), (9, 'heading_candidate'), (10, 'table'),
                                  (11, 'paragraph'), (12, 'table'), (13, 'paragraph')]]
        return {'company_id': 'independent-issuer', 'source': {'source_snapshot_id': 'annual-source', 'source_sha256': 'a'*64},
                'packet_id': 'parent-packet', 'blocks': blocks, 'coverage': {'document_block_count': 50}}

    def test_document_order_and_neighbors_exclude_other_tables(self):
        catalog = batch.table_batch_catalog(self.packet(), {'path': 'explicit-parent', 'manifest_sha256': 'b'*64})
        self.assertEqual([b['table_block_id'] for b in catalog['batches']], ['10', '12'])
        self.assertEqual(batch.select_batch(catalog, 0)['block_ids'], ['9', '10', '11'])
        self.assertEqual(batch.select_batch(catalog, 1)['block_ids'], ['11', '12', '13'])
        self.assertEqual(catalog['unassigned_parent_block_ids'], ['40'])
        self.assertEqual(catalog['source_sha256'], 'a'*64)
        self.assertEqual(catalog['source_document_block_count'], 50)

    def test_explicit_index_and_original_ordinals_are_required(self):
        catalog = batch.table_batch_catalog(self.packet(), {})
        for index in (-1, 2, None, True):
            with self.subTest(index=index), self.assertRaises(ValueError):
                batch.select_batch(catalog, index)
        packet = self.packet()
        packet['blocks'][0]['ordinal'] = packet['blocks'][1]['ordinal']
        with self.assertRaises(ValueError):
            batch.table_batch_catalog(packet, {})


if __name__ == '__main__':
    unittest.main()
