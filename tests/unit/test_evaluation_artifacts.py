"""Integrity boundaries for the read-only evaluation adapter, using synthetic data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from apps.review_workbench.data import evaluation_artifacts as artifacts


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvaluationArtifactIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.relative = 'data/synthetic-corpus/cedar'
        self.folder = self.root / self.relative
        self.folder.mkdir(parents=True)
        self.company = {'company_id': 'cedar-company', 'symbol': 'CEDAR', 'name': 'Synthetic Cedar'}
        self.record = {'record_id': 'record-1', 'entity_id': 'cedar-company',
            'metric_id': 'capacity', 'source_snapshot_id': 'cedar-source',
            'value_decimal': '9007199254740993.123456789012', 'dimensions': {},
            'evidence_ids': ['evidence-1'], 'qualifier_evidence_ids': [], 'question_evidence_ids': []}
        raw = self.folder / 'raw/cedar.txt'
        raw.parent.mkdir()
        raw.write_text('Capacity 9007199254740993.123456789012', encoding='utf-8')
        self.source = {'source_snapshot_id': 'cedar-source', 'company_id': 'cedar-company',
            'source_url': 'https://example.test/cedar', 'raw_file': 'raw/cedar.txt',
            'source_sha256': sha(raw), 'raw_file_sha256': sha(raw),
            'index_folder': 'indexes/cedar', 'index_id': 'index-cedar',
            'form': 'SYNTHETIC', 'parsed_mime_type': 'text/plain'}
        block = {'block_id': 'block-1', 'type': 'paragraph', 'text': raw.read_text(),
                 'text_hash': sha(raw), 'table': None}
        index_folder = self.folder / self.source['index_folder']
        write_json(index_folder / 'index.json', {'index_id': 'index-cedar',
            'source_snapshot_id': 'cedar-source', 'form_type': 'SYNTHETIC',
            'nodes': [{'node_id': 'node-1', 'start_block_id': 'block-1', 'end_block_id': 'block-1'}]})
        write_json(index_folder / 'blocks.jsonl', block)
        write_json(index_folder / 'assets.json', {'assets': []})
        write_json(index_folder / 'manifest.json', {'source_snapshot_id': 'cedar-source',
            'source_sha256': sha(raw), 'artifacts': {name: {'sha256': sha(index_folder / name)}
                for name in ('index.json', 'blocks.jsonl', 'assets.json')}})
        self.evidence = {'evidence-1': {'evidence_id': 'evidence-1',
            'source_snapshot_id': 'cedar-source', 'source_sha256': sha(raw),
            'index_id': 'index-cedar', 'block_id': 'block-1', 'text_hash': sha(raw),
            'quote': self.record['value_decimal'], 'context_block_ids': ['block-1']}}
        self.metrics = {'capacity': {'metric_id': 'capacity', 'unit': 'units'}}
        write_json(self.folder / 'sources.json', [self.source])
        write_json(self.folder / 'records.json', {'rows': [self.record]})
        write_json(self.folder / 'evidence.json', self.evidence)
        write_json(self.folder / 'metrics.json', self.metrics)
        with duckdb.connect(str(self.folder / 'research.duckdb')) as connection:
            connection.execute('CREATE TABLE observations (record_id VARCHAR, entity_id VARCHAR, '
                               'source_snapshot_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE sources (source_snapshot_id VARCHAR, company_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE evidence (evidence_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE metric_definitions (metric_id VARCHAR, payload JSON)')
            connection.execute('INSERT INTO observations VALUES (?, ?, ?, ?)',
                ['record-1', 'cedar-company', 'cedar-source', json.dumps(self.record)])
            connection.execute('INSERT INTO sources VALUES (?, ?, ?)',
                ['cedar-source', 'cedar-company', json.dumps(self.source)])
            connection.execute('INSERT INTO evidence VALUES (?, ?)', ['evidence-1', json.dumps(self.evidence['evidence-1'])])
            connection.execute('INSERT INTO metric_definitions VALUES (?, ?)', ['capacity', json.dumps(self.metrics['capacity'])])
        self.manifest = {'company': self.company, 'snapshot_id': 'cedar-frozen-2031',
            'source_policy_id': 'synthetic-frozen-v1', 'status': 'candidate',
            'source_count': 1, 'record_count': 1, 'evidence_count': 1, 'gaps': [], 'limits': ['Synthetic fixture.']}
        self.repin()

    def repin(self):
        """Model a newly registered snapshot so later checks see semantic mutations."""
        self.manifest['files'] = {str(path.relative_to(self.folder)): sha(path)
            for path in sorted(self.folder.rglob('*')) if path.is_file() and path != self.folder / 'manifest.json'}
        write_json(self.folder / 'manifest.json', self.manifest)
        write_json(self.root / artifacts.REGISTRATION, {'schema_version': 'data-evaluation-view-v1',
            'datasets': [{'id': 'cedar', 'path': self.relative,
                'company_id': 'cedar-company', 'symbol': 'CEDAR', 'snapshot_id': 'cedar-frozen-2031',
                'manifest_sha256': sha(self.folder / 'manifest.json')}], 'runs': []})

    def load(self):
        return artifacts.load_dataset(self.root, 'cedar')

    def test_independent_dataset_reads_exact_payload_without_modifying_database(self):
        before = sha(self.folder / 'research.duckdb')
        result = self.load()
        self.assertEqual(result['records'], [self.record])
        self.assertEqual(result['sources'], [self.source])
        self.assertEqual(result['evidence'], self.evidence)
        self.assertEqual(result['storage']['dataset_path'], self.relative)
        self.assertEqual(result['storage']['database_path'], self.relative + '/research.duckdb')
        self.assertEqual({c['table_name'] for c in result['columns']},
                         {'observations', 'sources', 'evidence', 'metric_definitions'})
        self.assertEqual(sha(self.folder / 'research.duckdb'), before)
        source = artifacts.load_raw_source(self.root, 'cedar', 'cedar-source')
        self.assertEqual(source['content'], (self.folder / 'raw/cedar.txt').read_bytes())
        self.assertEqual(source['sha256'], self.source['source_sha256'])

    def test_blank_unknown_dataset_and_foreign_source_do_not_fall_back(self):
        for identity in ('', 'missing', '../cedar'):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                artifacts.load_dataset(self.root, identity)
        with self.assertRaisesRegex(ValueError, 'Unknown source'):
            artifacts.load_raw_source(self.root, 'cedar', 'birch-source')

    def test_manifest_byte_mutation_is_rejected_against_registered_hash(self):
        path = self.folder / 'manifest.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'Manifest integrity mismatch'):
            self.load()

    def test_listed_file_byte_mutation_is_rejected(self):
        path = self.folder / 'records.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'Frozen file integrity mismatch: records.json'):
            self.load()

    def test_manifest_paths_reject_traversal_absolute_and_symlink_targets(self):
        for relative in ('../outside.json', '/tmp/outside.json', 'raw/../../outside.json'):
            with self.subTest(relative=relative):
                write_json(self.folder / 'manifest.json', {'files': {relative: '0' * 64}})
                with self.assertRaisesRegex(ValueError, 'outside registered root'):
                    artifacts._manifest(self.folder, sha(self.folder / 'manifest.json'))
        (self.folder / 'alias').symlink_to(self.folder / 'raw', target_is_directory=True)
        write_json(self.folder / 'manifest.json', {'files': {'alias/cedar.txt': self.source['source_sha256']}})
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            artifacts._manifest(self.folder, sha(self.folder / 'manifest.json'))

    def test_rehashed_json_cannot_disagree_with_database_payload(self):
        changed = {**self.record, 'value_decimal': '42'}
        write_json(self.folder / 'records.json', {'rows': [changed]})
        self.repin()
        with self.assertRaisesRegex(ValueError, 'DuckDB payload differs from frozen JSON: observations'):
            self.load()

    def test_database_identity_columns_must_match_payload_company_and_source(self):
        for table, column, value, message in (
                ('sources', 'company_id', 'birch-company', 'DuckDB source company mismatch'),
                ('observations', 'source_snapshot_id', 'birch-source', 'DuckDB observation identity mismatch')):
            with self.subTest(table=table):
                with duckdb.connect(str(self.folder / 'research.duckdb')) as connection:
                    old = connection.execute(f'SELECT {column} FROM {table}').fetchone()[0]
                    connection.execute(f'UPDATE {table} SET {column} = ?', [value])
                self.repin()
                with self.assertRaisesRegex(ValueError, message):
                    self.load()
                with duckdb.connect(str(self.folder / 'research.duckdb')) as connection:
                    connection.execute(f'UPDATE {table} SET {column} = ?', [old])

    def test_rehashed_source_cannot_belong_to_another_company(self):
        changed = {**self.source, 'company_id': 'birch-company'}
        write_json(self.folder / 'sources.json', [changed])
        self.repin()
        with self.assertRaisesRegex(ValueError, 'Source belongs to another company'):
            self.load()

    def test_processing_gap_cannot_reference_an_unselected_source(self):
        self.manifest['gaps'] = [{'source_snapshot_id': 'birch-source', 'reason': 'unmapped_concept'}]
        self.repin()
        with self.assertRaisesRegex(ValueError, 'Processing gap refers to a source outside selected dataset'):
            self.load()


if __name__ == '__main__':
    unittest.main()
