import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import duckdb

from apps.review_workbench.data import direct_extraction_views as views
from apps.review_workbench.pages.direct_extractions import render_direct_extractions, processing_record


class DirectExtractionViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'experiments/synthetic'
        self.folder.mkdir(parents=True)
        self.config = {'schema_version': 'direct-extraction-view-v1', 'runs': []}
        self.save(views.REGISTRATION, self.config)

    def save(self, relative, payload):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload))
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def register(self, artifacts):
        hashes = {name: self.save('experiments/synthetic/' + name, payload) for name, payload in artifacts.items()}
        manifest_hash = self.save('experiments/synthetic/manifest.json', {'files': hashes})
        self.config['runs'] = [{'id': 'synthetic', 'path': 'experiments/synthetic', 'manifest_sha256': manifest_hash}]
        self.save(views.REGISTRATION, self.config)

    def packet(self):
        text = 'Synthetic capacity 12'
        return {'company_id': 'cedar', 'source': {'company_id': 'cedar', 'source_snapshot_id': 'cedar-2024',
            'source_sha256': 'a' * 64, 'period_end': '2024-12-31'}, 'task': {'company_id': 'cedar'},
            'blocks': [{'block_id': 'b1', 'text': text, 'text_hash': hashlib.sha256(text.encode()).hexdigest()}],
            'entity_catalog': [{'entity_id': 'cedar'}]}

    def test_empty_real_registration_does_not_invent_runs(self):
        self.assertEqual(views.load_catalog(self.root), [])
        self.assertIn('No real extraction run', render_direct_extractions(self.root, {}))

    def test_failed_run_preserves_error_and_missing_status(self):
        self.register({'result.json': {'status': 'failed', 'error': '<script>alert(1)</script>'},
                       'job.json': {'company_id': 'cedar'}})
        loaded = views.load_run(self.root, 'synthetic')
        self.assertIn('extraction.json', loaded['missing'])
        self.assertEqual(loaded['scope_status'], 'packet_missing')
        rendered = render_direct_extractions(self.root, {'run': ['synthetic']})
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>alert(1)</script>', rendered)
        self.assertIn('Normalization checks were not saved', rendered)
        self.assertIn('No inspectable database artifact', rendered)
        self.assertNotIn('The program recorded 0 unresolved items', rendered)

    def test_processing_record_uses_only_saved_input_prompt_and_database_status(self):
        rendered = processing_record({'artifacts': {
            'job.json': {'task': 'Read Cedar annual cash flows'},
            'packet.json': self.packet(),
            'prompt.json': {'version': 'selected-method-v2'},
            'system-prompt-effective.json': {'text': 'Extract <source> faithfully'},
            'result.json': {'usage': {'summary': {'provider': 'example', 'model': 'model-a'}}},
            'extraction.json': {'records': [{}], 'gaps': ['Only the selected table was provided']},
            'normalized.json': {'records': [], 'unresolved': [{'reason': 'unmapped'}]},
        }, 'db_check': 'payload_matches_normalized', 'db_rows': [], 'review': None})
        self.assertIn('Read Cedar annual cash flows', rendered)
        self.assertIn('Synthetic capacity 12', rendered)
        self.assertIn('Extract &lt;source&gt; faithfully', rendered)
        self.assertNotIn('<source>', rendered)
        self.assertIn('selected-method-v2', rendered)
        self.assertIn('The program recorded 1 unresolved items', rendered)
        self.assertIn('0 candidate database records were checked', rendered)
        self.assertIn('No independent review has been registered', rendered)

    def test_packet_company_and_hash_must_match(self):
        packet = self.packet()
        self.register({'packet.json': packet, 'job.json': {'company_id': 'other'}})
        with self.assertRaisesRegex(ValueError, 'company/source mismatch'):
            views.load_run(self.root, 'synthetic')
        packet['blocks'][0]['text'] = 'tampered'
        self.register({'packet.json': packet})
        with self.assertRaisesRegex(ValueError, 'block hash'):
            views.load_run(self.root, 'synthetic')

    def test_hash_tampering_and_path_injection_are_rejected(self):
        self.register({'result.json': {'status': 'failed'}})
        (self.folder / 'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            views.load_run(self.root, 'synthetic')
        with self.assertRaises(ValueError):
            render_direct_extractions(self.root, {'path': ['/etc/passwd']})
        self.config['runs'][0]['path'] = 'experiments/../../etc'
        self.save(views.REGISTRATION, self.config)
        with self.assertRaises(ValueError):
            views.load_catalog(self.root)

    def test_company_filter_cannot_open_another_company(self):
        self.register({'packet.json': self.packet()})
        with self.assertRaises(ValueError):
            render_direct_extractions(self.root, {'company': ['other'], 'run': ['synthetic']})

    def test_database_payload_is_read_and_must_match(self):
        packet = self.packet()
        record = {'record_id': 'r1', 'entity_id': 'cedar', 'source_snapshot_id': 'cedar-2024', 'value_decimal': '12'}
        self.register({'packet.json': packet, 'normalized.json': {'records': [record], 'evidence': {}}})
        dbpath = self.folder / 'dataset/research.duckdb'
        dbpath.parent.mkdir()
        with duckdb.connect(str(dbpath)) as db:
            db.execute('CREATE TABLE observations(record_id VARCHAR, entity_id VARCHAR, source_snapshot_id VARCHAR, payload JSON)')
            db.execute('CREATE TABLE sources(source_snapshot_id VARCHAR, company_id VARCHAR, payload JSON)')
            db.execute('CREATE TABLE evidence(evidence_id VARCHAR, source_snapshot_id VARCHAR, payload JSON)')
            db.execute('INSERT INTO observations VALUES (?, ?, ?, ?)', ['r1', 'cedar', 'cedar-2024', json.dumps(record)])
            db.execute('INSERT INTO sources VALUES (?, ?, ?)', ['cedar-2024', 'cedar', json.dumps(packet['source'])])
        def repin():
            manifest = json.loads((self.folder / 'manifest.json').read_text())
            manifest['files']['dataset/research.duckdb'] = hashlib.sha256(dbpath.read_bytes()).hexdigest()
            self.config['runs'][0]['manifest_sha256'] = self.save('experiments/synthetic/manifest.json', manifest)
            self.save(views.REGISTRATION, self.config)
        repin()
        self.assertEqual(views.load_run(self.root, 'synthetic')['db_rows'], [record])
        with duckdb.connect(str(dbpath)) as db:
            db.execute('UPDATE observations SET payload=?', [json.dumps({**record, 'value_decimal': '99'})])
        repin()
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            views.load_run(self.root, 'synthetic')

    def test_external_review_must_be_pinned_and_match_scope(self):
        self.register({'packet.json': self.packet()})
        sha = self.save('experiments/review.json', {'run_id': 'some-other-run', 'findings': []})
        self.config['runs'][0]['review'] = {'path': 'experiments/review.json', 'sha256': sha}
        self.save(views.REGISTRATION, self.config)
        with self.assertRaisesRegex(ValueError, 'review scope mismatch'):
            views.load_run(self.root, 'synthetic')

    def test_unstored_draft_retains_context_and_failed_quote(self):
        self.register({'packet.json': self.packet(), 'extraction.json': {'records': [
            {'draft_id': 'unresolved-1', 'evidence': [{'block_id': 'b1', 'quote': 'capacity 12'},
                                                   {'block_id': 'b1', 'quote': 'invented quote'}]}]}})
        contexts = views.load_run(self.root, 'synthetic')['draft_contexts']
        self.assertTrue(contexts[0]['quote_found'])
        self.assertFalse(contexts[1]['quote_found'])
        self.assertEqual(contexts[0]['context'], 'Synthetic capacity 12')


if __name__ == '__main__':
    unittest.main()
