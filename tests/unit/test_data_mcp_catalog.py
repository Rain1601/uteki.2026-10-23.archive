"""Independent synthetic catalog tests; fixtures are not model-quality evidence."""
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from uteki.domain.research_data.query_contract import ResearchRecord, VERSION
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import DDL, save
from uteki.interfaces.data_mcp.catalog import Catalog


def freeze(folder, **metadata):
    files = {str(p.relative_to(folder)): digest(p.read_bytes()) for p in folder.rglob('*')
             if p.is_file() and p != folder / 'manifest.json'}
    save(folder / 'manifest.json', {**metadata, 'files': files})
    return digest((folder / 'manifest.json').read_bytes())


def sample(root, company, *, extraction=False):
    """Two companies deliberately share block/draft IDs to test scope isolation."""
    run = root / company
    folder = run / 'dataset'
    folder.mkdir(parents=True)
    sid, rid = company + '-annual', company + '-revenue'
    block = {'block_id': 'same-local-block', 'type': 'paragraph', 'text': company + ' revenue 10 USD',
             'reported_page': '1'}
    block['text_hash'] = digest(block['text'].encode())
    index = folder / 'index'
    save(index / 'index.json', {'index_id': 'index-' + company, 'form_type': '10-K', 'diagnostics': [], 'nodes': [
        {'node_id': 'root', 'kind': 'document', 'start_block_id': block['block_id'], 'end_block_id': block['block_id']}]})
    (index / 'blocks.jsonl').write_text(json.dumps(block) + '\n')
    save(index / 'manifest.json', {'status': 'candidate', 'artifacts': {name: {'sha256': digest((index / name).read_bytes())}
         for name in ('index.json', 'blocks.jsonl')}})
    source = {'company_id': company, 'source_snapshot_id': sid, 'source_url': 'https://example.invalid/' + company,
              'source_sha256': digest(company), 'form': '10-K', 'available_at': '2032-02-01',
              'period_end': '2031-12-31', 'index_folder': 'index', 'index_id': 'index-' + company}
    draft = {'draft_id': 'same-local-draft', 'metric_id': 'revenue', 'metric': 'Revenue', 'value': '10',
             'period_id': 'fy2031', 'entity_id': company}
    unknown = {'draft_id': 'unresolved', 'metric_id': 'debt', 'metric': 'Debt, net',
               'period_id': 'fy2031', 'entity_id': company, 'value': 'unknown'}
    row = ResearchRecord(record_id=rid, record_type='metric', entity_id=company, metric_id='revenue',
        period={'kind': 'year', 'start': '2031-01-01', 'end': '2031-12-31'}, value_kind='actual',
        value_decimal='10', value_relation='eq', unit='USD', accounting_basis='reported_consolidated',
        available_at='2032-02-01', source_snapshot_id=sid, evidence_ids=['evidence-' + company],
        summary='Synthetic', origin={'draft_id': draft['draft_id'], 'raw': draft}).model_dump(mode='json')
    ev = {'source_snapshot_id': sid, 'source_sha256': source['source_sha256'], 'block_id': block['block_id'],
          'text_hash': block['text_hash'], 'source_start': 0, 'source_end': len(block['text']), 'quote': block['text']}
    refs = {'evidence-' + company: ev}
    with duckdb.connect(str(folder / 'research.duckdb')) as db:
        db.execute(DDL)
        db.execute('INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)',
                   [sid, company, '10-K', '2031-12-31', '2032-02-01', json.dumps(source)])
        db.execute('INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [rid, company, 'revenue', 'year', '2031-01-01', '2031-12-31', 'actual', '10', None, 'eq', 'USD',
             'reported_consolidated', '2032-02-01', sid, 'candidate', json.dumps(row)])
        db.execute('INSERT INTO evidence VALUES (?, ?, ?)', ['evidence-' + company, sid, json.dumps(ev)])
    save(folder / 'sources.json', [source])
    save(folder / 'metrics.json', {'revenue': {'metric_id': 'revenue', 'unit': 'USD'}})
    manifest_sha = freeze(folder, schema_version=VERSION, snapshot_id='snapshot-' + company,
                          source_policy_id='synthetic-frozen-v1', limits=['Synthetic test fixture'])
    entry = dict(id=company, label=company + ' annual test', company_id=company, aliases=[company.upper()],
                 dataset_path=str(folder.relative_to(root)), manifest_sha256=manifest_sha)
    if extraction:
        packet = {'company_id': company, 'source': source, 'blocks': [block]}
        save(run / 'packet.json', packet)
        save(run / 'job.json', {'company_id': company, 'source_snapshot_id': sid})
        save(run / 'extraction.json', {'records': [draft, unknown], 'gaps': ['Only a small delivered batch.']})
        save(run / 'normalized.json', {'records': [row], 'evidence': refs, 'raw_candidates': [draft, unknown],
            'unresolved': [{'draft_id': 'unresolved', 'reason': 'unresolved_value'}]})
        save(run / 'result.json', {'projection_snapshot_id': 'snapshot-' + company,
                                  'implementation': {'not-present.py': 'f' * 64}})
        run_sha = freeze(run)
        manifest = json.loads((run / 'manifest.json').read_text())
        review = {'run_id': company, 'company_id': company, 'source_snapshot_id': sid,
            'source_sha256': source['source_sha256'], 'adoption': 'unchanged_candidate', 'overall': 'partial',
            'inputs': {'run_manifest_sha256': run_sha, 'packet_sha256': manifest['files']['packet.json'],
                       'extraction_sha256': manifest['files']['extraction.json']},
            'facts': [{'draft_id': draft['draft_id'], 'record_id': rid, 'verdict': 'value_scope_matched',
                'held_out_fact_id': 'SECRET-GOLD', 'reviewer_scope': 'Value and source only.',
                'source_review': {'record_id': rid, 'draft_id': draft['draft_id'], 'metric_id': 'revenue',
                    'normalized_value_decimal': '10', 'normalized_unit': 'USD', 'verdict': 'supported',
                    'source_support': {'inline_fact_for_reviewer_only': 'PRIVATE'}}}]}
        review_path = root / (company + '-review.json')
        save(review_path, review)
        entry['extraction'] = {'path': company, 'manifest_sha256': run_sha,
                              'review': {'path': review_path.name, 'sha256': digest(review_path.read_bytes())}}
    return entry


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.a = sample(self.root, 'acme', extraction=True)
        self.b = sample(self.root, 'other')
        self.path = self.root / 'catalog.json'
        self.config = {'schema_version': 'data-mcp-catalog-v1', 'root_path': '.', 'datasets': [self.a, self.b]}
        self.write()

    def write(self):
        save(self.path, self.config)

    def open(self):
        catalog = Catalog(self.path)
        self.addCleanup(catalog.close)
        return catalog

    def test_two_companies_and_exact_review_are_discoverable_without_paths_or_gold(self):
        catalog = self.open()
        self.assertEqual(catalog.resolve_company(' ACME '), 'acme')
        self.assertEqual(catalog.resolve_company('other'), 'other')
        public = json.dumps([e.public() for e in catalog.entries.values()])
        self.assertNotIn('dataset_path', public)
        self.assertNotIn('index_folder', public)
        self.assertNotIn(str(self.root), public)
        review = catalog.entries['acme'].record_review('acme-revenue')
        self.assertEqual(review['source_verdict'], 'supported')
        self.assertEqual(review['adoption'], 'unchanged_candidate')
        self.assertNotIn('SECRET-GOLD', json.dumps(review))
        self.assertNotIn('PRIVATE', json.dumps(review))
        self.assertEqual(catalog.entries['other'].record_review('other-revenue')['status'], 'not_reviewed')
        with self.assertRaises(ValueError):
            catalog.entries['acme'].record_review('other-revenue')
        for query in ('', 'unknown', None):
            with self.subTest(query=query), self.assertRaises(ValueError):
                catalog.resolve_company(query)

    def test_scoped_gaps_keep_unmapped_drafts_but_never_grant_adoption(self):
        entry = self.open().entries['acme']
        status = entry.status_for_sources(['acme-annual'], '2032-02-01', True)
        self.assertEqual(status['raw_draft_count'], 2)
        self.assertEqual(status['normalized_record_count'], 1)
        self.assertEqual(status['unresolved_drafts'][0]['metric_id'], 'debt')
        self.assertEqual(status['normalization_diagnostic_counts'], {'unresolved_value': 1})
        self.assertEqual(status['gaps'][0]['reason'], 'implementation_archive_metadata_mismatch')
        self.assertEqual(status['completeness'], 'not_evaluated')
        denied = entry.status_for_sources(['acme-annual'], '2032-02-01', False)
        self.assertEqual(denied['status'], 'quality_filtered')
        self.assertNotIn('raw_draft_count', denied)
        for sources, cutoff in (([], '2032-02-01'), (['other-annual'], '2032-02-01'),
                                 (['acme-annual'], '2032-01-31')):
            with self.subTest(sources=sources, cutoff=cutoff), self.assertRaises(ValueError):
                entry.status_for_sources(sources, cutoff, True)

    def test_registered_file_tampering_is_rejected(self):
        (self.root / self.b['dataset_path'] / 'sources.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            Catalog(self.path)

    def test_foreign_database_source_cannot_hide_without_observations(self):
        folder = self.root / self.b['dataset_path']
        with duckdb.connect(str(folder / 'research.duckdb')) as db:
            db.execute('INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)',
                ['foreign-source', 'foreign-company', '10-K', '2031-12-31', '2032-02-01', '{}'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.b['manifest_sha256'] = freeze(folder, **{k: v for k, v in manifest.items() if k != 'files'})
        self.write()
        with self.assertRaisesRegex(ValueError, 'outside registered company'):
            Catalog(self.path)

    def test_source_index_must_be_frozen_even_when_metadata_is_pinned(self):
        folder = self.root / self.b['dataset_path']
        manifest = json.loads((folder / 'manifest.json').read_text())
        del manifest['files']['index/blocks.jsonl']
        save(folder / 'manifest.json', manifest)
        self.b['manifest_sha256'] = digest((folder / 'manifest.json').read_bytes())
        self.write()
        with self.assertRaisesRegex(ValueError, 'index is not bound'):
            Catalog(self.path)

    def test_manifest_pin_and_company_scope_are_validated(self):
        self.a['manifest_sha256'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(ValueError, 'integrity'):
            Catalog(self.path)
        self.a['manifest_sha256'] = digest((self.root / self.a['dataset_path'] / 'manifest.json').read_bytes())
        self.a['company_id'] = 'other'
        self.write()
        with self.assertRaisesRegex(ValueError, 'company'):
            Catalog(self.path)

    def test_duplicate_identity_and_ambiguous_alias_are_rejected(self):
        self.b['id'] = self.a['id']
        self.write()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            Catalog(self.path)
        self.b['id'] = 'other'
        self.b['aliases'] = ['ACME']
        self.write()
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            Catalog(self.path)

    def test_review_tampering_and_cross_record_binding_are_rejected(self):
        ref = self.a['extraction']['review']
        path = self.root / ref['path']
        review = json.loads(path.read_text())
        review['facts'][0]['record_id'] = 'other-revenue'
        save(path, review)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            Catalog(self.path)
        ref['sha256'] = digest(path.read_bytes())
        self.write()
        with self.assertRaisesRegex(ValueError, 'record binding'):
            Catalog(self.path)

    def test_missing_explicit_root_or_aliases_and_traversal_are_rejected(self):
        del self.config['root_path']
        self.write()
        with self.assertRaises(ValueError):
            Catalog(self.path)
        self.config['root_path'] = '.'
        self.a['aliases'] = []
        self.write()
        with self.assertRaises(ValueError):
            Catalog(self.path)
        self.a['aliases'] = ['acme']
        self.a['dataset_path'] = '../elsewhere'
        self.write()
        with self.assertRaisesRegex(ValueError, 'stay under'):
            Catalog(self.path)


if __name__ == '__main__':
    unittest.main()
