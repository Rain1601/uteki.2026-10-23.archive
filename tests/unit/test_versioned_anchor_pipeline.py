"""New parser whitespace must survive dataset -> review -> semantic consumers."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_company_materialization import filing
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.record_review import build_review_packets
from uteki.infrastructure.research_data.semantic_review import prepare_semantic_inputs, validate_dataset_binding


class VersionedAnchorPipelineTests(unittest.TestCase):
    def test_two_explicit_sources_survive_repack_and_reject_version_tampering(self):
        for cik, start, end in [('123', '2024-07-01', '2025-06-30'), ('456', '2023-07-01', '2024-06-30')]:
            with self.subTest(cik=cik), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw = filing(cik, start, end).replace(b'>Operating income<', b'>Operating<br>income<')
                (root/'source.html').write_bytes(raw)
                company = 'sec-'+cik.zfill(10)
                source_id = 'filing-'+cik
                run = {'company': {'company_id': company, 'cik': cik.zfill(10)}, 'as_of': '2025-09-01',
                    'documents': [{'source_id': source_id, 'source_url': 'https://example.invalid/'+source_id,
                        'form': '10-K', 'filed_at': '2025-08-01', 'period_end': end,
                        'content_sha256': digest(raw), 'path': 'source.html',
                        'mime_type': 'text/html', 'status': 'frozen'}]}
                dataset = root/'dataset'
                # Exercise the production default, not a test-only parser override.
                manifest = materialize_sources(run, root, dataset)
                rows = json.loads((dataset/'records.json').read_text())['rows']
                ids = [r['record_id'] for r in rows]
                self.assertEqual(len(ids), 2)
                scope = {'snapshot_id': manifest['snapshot_id'], 'company_ids': [company],
                    'source_snapshot_ids': [source_id], 'source_policy_id': 'local-frozen-v1',
                    'knowledge_cutoff': '2025-09-01', 'include_candidates': True}
                build_review_packets(dataset, scope, ids, root/'review')
                task = {'task_id': 'row-check', 'record_ids': ids, 'axes': ['value'],
                        'assertions': []}
                output = root/'semantic'
                spec = prepare_semantic_inputs(root/'review', [task], output)
                packet = json.loads((output/spec['packets'][0]['path']).read_text())
                self.assertEqual(packet['parser_version'], 'sec-source-blocks-v0.1.13')
                self.assertTrue(all(a['status'] == 'located' for a in packet['record_anchors'].values()))
                self.assertIn('Operating income30', [a['text'] for a in packet['record_anchors'].values()])
                validate_dataset_binding(packet, dataset, artifact_root=output)
                for version in (None, 'sec-source-blocks-v0.1.11'):
                    changed = deepcopy(packet)
                    if version is None:
                        del changed['parser_version']
                    else:
                        changed['parser_version'] = version
                    with self.assertRaisesRegex(ValueError, 'parser version differs'):
                        validate_dataset_binding(changed, dataset)
