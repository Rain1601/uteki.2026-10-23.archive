"""Real pinned figure-reader integration over two independent synthetic SEC issuers."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import shutil
import unittest

import duckdb

import tests.unit.test_figure_materials as figure_fixtures
from uteki.domain.research_data.query_contract import DataQuery, QueryResult, ResearchRecord, VERSION
from uteki.infrastructure.research_data.company_materialization import _index, extract_inline_records
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import DDL, save
from uteki.infrastructure.research_data.query_service import QueryDataPort


class QueryFiguresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = figure_fixtures.FigureMaterialsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.dataset = self.fixture.dataset
        original = json.loads((self.dataset / 'sources.json').read_text())[0]
        raw = (self.dataset / original['raw_file']).read_bytes()
        # The acquisition fixture has only image locators. Build each issuer's
        # actual Query index from these same original HTML bytes instead of
        # inventing Query metadata or copying another issuer's index identity.
        shutil.rmtree(self.dataset / original['index_folder'])
        identities = [dict(source_snapshot_id=original['source_snapshot_id'],
            company_id=original['company_id'], source_url=original['source_url'],
            period_end='2031-12-31', available_at='2032-02-01'),
            dict(source_snapshot_id='independent-other', company_id='sec-0000000987',
                source_url='https://www.sec.gov/Archives/edgar/data/987/000000098733000001/report.htm',
                period_end='2032-12-31', available_at='2033-02-01')]
        sources = []
        for identity in identities:
            sid = identity['source_snapshot_id']
            doc = dict(source_id=sid, source_url=identity['source_url'], form='10-K',
                period_end=identity['period_end'], filed_at=identity['available_at'],
                mime_type='text/html', content_sha256=digest(raw))
            index_folder, raw_file = 'indexes/' + sid, 'raw/' + sid + '.html'
            original_path = self.dataset / raw_file
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(raw)
            index, blocks, _ = _index(raw, doc, self.dataset / index_folder,
                company_id=identity['company_id'])
            package_manifest_path = self.dataset / index_folder / 'manifest.json'
            package_manifest = json.loads(package_manifest_path.read_bytes())
            _, _, _, fiscal = extract_inline_records(raw, doc,
                {'company_id': identity['company_id'], 'cik': identity['company_id'].removeprefix('sec-')},
                index, blocks, raw_file)
            sources.append({**identity, 'form': doc['form'], 'document_id': sid,
                'source_sha256': digest(raw), 'raw_file_sha256': digest(raw),
                'raw_file': raw_file, 'index_folder': index_folder, 'index_id': index['index_id'],
                'status': 'candidate', 'fiscal_periods': fiscal,
                'parsed_mime_type': doc['mime_type'], 'declared_mime_type': doc['mime_type'],
                'parsed_package': {'export_version': package_manifest['export_version'],
                    'package_id': package_manifest['package_id'], 'manifest_path': index_folder + '/manifest.json',
                    'manifest_sha256': digest(package_manifest_path.read_bytes()),
                    'source_path': index_folder + '/source.json', 'document_path': index_folder + '/document.html',
                    'status': 'candidate_parsed_material', 'semantic_review': 'not_reviewed'},
                'capabilities': ['read_context', 'literal_search', 'source_bytes', 'html_table_structure',
                    'parsed_document_package'], 'block_count': len(blocks),
                'image_block_count': sum(block['type'] == 'image' for block in blocks)})
        save(self.dataset / 'sources.json', sources)
        save(self.dataset / 'metrics.json', {})
        for name, model in [('query', DataQuery), ('record', ResearchRecord), ('result', QueryResult)]:
            save(self.dataset / f'schemas/{name}.schema.json', model.model_json_schema())
        db = duckdb.connect(str(self.dataset / 'research.duckdb'))
        db.execute(DDL)
        for source in sources:
            db.execute('INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)',
                [source[key] for key in ('source_snapshot_id', 'company_id', 'form', 'period_end', 'available_at')]
                + [json.dumps(source)])
        db.close()
        self.fixture.fixture.repin()
        manifest_path = self.dataset / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest.update(schema_version=VERSION, snapshot_id='synthetic-figures-two-issuers',
            source_policy_id='local-frozen-v1', limits=['Synthetic pinned figure supplement'])
        save(manifest_path, manifest)
        self.fixture.acquisition = self.fixture.fixture.root / 'two-issuer-acquisition'
        self.fixture.fixture.output = self.fixture.acquisition
        self.fixture.fixture.run_acquire()
        self.bundle = self.fixture.bundle
        self.fixture.run_materials()
        self.ref = {'path': str(self.bundle.resolve()), 'manifest_sha256': digest((self.bundle / 'manifest.json').read_bytes())}
        self.owner = QueryDataPort(self.dataset)
        self.addCleanup(self.owner.close)
        self.scope = {'snapshot_id': self.owner.snapshot_id, 'company_ids': [s['company_id'] for s in sources],
            'source_snapshot_ids': [s['source_snapshot_id'] for s in sources], 'source_policy_id': 'local-frozen-v1',
            'knowledge_cutoff': '2034-01-01', 'include_candidates': True}
        self.sources = sources

    def bound(self, **scope_changes):
        self.owner.bind_figures(self.ref)
        return self.owner.scoped({**self.scope, **scope_changes})

    def first_only(self):
        return self.bound(company_ids=[self.sources[0]['company_id']],
            source_snapshot_ids=[self.sources[0]['source_snapshot_id']])

    def request(self, figure):
        return {'source_snapshot_id': figure['source_snapshot_id'], 'figure_id': figure['figure_id']}

    def test_unconfigured_inventory_is_explicit_and_cannot_read_or_search_for_bundle(self):
        port = self.owner.scoped(self.scope)
        value = port.list_figures()
        self.assertEqual(value['status'], 'unconfigured')
        self.assertEqual(value['figures'], [])
        self.assertEqual(value['gaps'][0]['reason'], 'explicit_figure_bundle_required')
        self.assertIsNone(self.owner.figure_bundle_ref)
        with self.assertRaisesRegex(ValueError, 'unconfigured'):
            port.read_figure({'source_snapshot_id': 'sample', 'figure_id': 'unknown'})
        self.assertEqual(port.get_schema()['figure_materials']['status'], 'unconfigured')

    def test_navigation_contains_only_scoped_metadata_and_read_returns_bound_original_content(self):
        port = self.first_only()
        inventory = port.list_figures()
        self.assertEqual(inventory['status'], 'complete')
        figure, = inventory['figures']
        self.assertEqual(figure['company_id'], self.sources[0]['company_id'])
        self.assertNotIn('transcription', figure)
        self.assertNotIn('document_context', figure)
        self.assertNotIn('alt', json.dumps(figure))
        read = port.read_figure(self.request(figure))
        self.assertEqual(read['status'], 'read')
        self.assertEqual(read['material_type'], 'figure-evidence-v1')
        self.assertEqual(read['figure_bundle_ref'], self.ref)
        self.assertEqual(read['figure']['transcription']['texts'][0]['text'], 'Series A')
        self.assertEqual(read['figure']['image_sha256'], figure['image_sha256'])
        self.assertEqual(read['figure']['figure_bundle_manifest_sha256'], self.ref['manifest_sha256'])
        self.assertEqual(len(read['figure']['transcription_sha256']), 64)
        self.assertEqual(len(read['figure']['locations']), 2)
        self.assertEqual(read['figure']['independent_acceptance'], 'pending')
        schema = port.get_schema()
        self.assertIn('read_figure', schema['execution_contracts'])
        self.assertEqual(schema['figure_materials']['status'], 'configured')

    def test_wrong_source_other_company_unknown_figure_and_unreadable_candidates_rejected(self):
        all_port = self.bound()
        figures = all_port.list_figures()['figures']
        first = next(f for f in figures if f['source_snapshot_id'] == 'sample')
        other = next(f for f in figures if f['source_snapshot_id'] != 'sample')
        with self.assertRaisesRegex(ValueError, 'requested source'):
            all_port.read_figure({**self.request(other), 'source_snapshot_id': 'sample'})
        narrow = self.first_only()
        with self.assertRaisesRegex(ValueError, 'outside execution scope'):
            narrow.read_figure(self.request(other))
        with self.assertRaisesRegex(ValueError, 'Unknown figure'):
            narrow.read_figure({**self.request(first), 'figure_id': 'unknown'})
        denied = narrow.scoped({**narrow.scope.model_dump(mode='json'), 'include_candidates': False})
        self.assertEqual(denied.list_figures()['figures'], [])
        self.assertEqual(denied.list_figures()['gaps'][0]['reason'], 'quality_filtered')
        with self.assertRaises(PermissionError):
            denied.read_figure(self.request(first))
        with self.assertRaisesRegex(ValueError, 'cannot widen'):
            denied.scoped(narrow.scope)

    def test_cutoff_and_nested_scope_never_restore_future_or_other_issuer_figures(self):
        port = self.bound(knowledge_cutoff='2032-12-31')
        inventory = port.list_figures()
        self.assertEqual([f['source_snapshot_id'] for f in inventory['figures']], ['sample'])
        self.assertEqual(inventory['gaps'][0]['reason'], 'not_available_at_cutoff')
        full = self.owner.scoped(self.scope)
        future = next(f for f in full.list_figures()['figures'] if f['source_snapshot_id'] != 'sample')
        with self.assertRaises(PermissionError):
            port.read_figure(self.request(future))
        with self.assertRaisesRegex(ValueError, 'cannot widen'):
            port.scoped(self.scope)
        narrow = port.scoped({**port.scope.model_dump(mode='json'), 'company_ids': [self.sources[0]['company_id']],
            'source_snapshot_ids': ['sample']})
        self.assertEqual(narrow.figure_bundle_ref, port.figure_bundle_ref)
        self.assertEqual(len(narrow.list_figures()['figures']), 1)

    def test_explicit_bundle_pin_and_dataset_binding_checked_before_binding_and_on_every_read(self):
        with self.assertRaisesRegex(ValueError, 'explicit pin'):
            self.owner.bind_figures({**self.ref, 'manifest_sha256': '0' * 64})
        self.assertIsNone(self.owner.figure_bundle_ref)
        port = self.first_only()
        figure, = port.list_figures()['figures']
        path = self.bundle / 'manifest.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'explicit pin'):
            port.read_figure(self.request(figure))

    def test_dataset_mutation_and_image_artifact_tamper_cannot_be_read(self):
        port = self.first_only()
        figure, = port.list_figures()['figures']
        path = self.dataset / 'manifest.json'
        old = path.read_bytes(); path.write_bytes(old + b' ')
        with self.assertRaisesRegex(ValueError, 'Dataset manifest changed'):
            port.read_figure(self.request(figure))
        path.write_bytes(old)
        original = Path(port.read_figure(self.request(figure))['figure']['original_image_path'])
        original.write_bytes(b'corrupted original')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            port.list_figures()

    def test_partial_bundle_gaps_are_source_scoped_without_fallback_to_another_issuer(self):
        original = self.bound().list_figures()['figures']
        first_id = next(figure['figure_id'] for figure in original if figure['source_snapshot_id'] == 'sample')
        # Select the independent partial bundle through a new owning port, never
        # mutate a previously selected bundle or silently replace its binding.
        partial = self.fixture.fixture.root / 'partial-bundle'
        self.fixture.run_materials(effect=[RuntimeError('temporary transport failure'),
            SimpleNamespace(final_output=figure_fixtures.chart())], output=partial)
        with QueryDataPort(self.dataset) as owner:
            owner.bind_figures({'path': str(partial), 'manifest_sha256': digest((partial / 'manifest.json').read_bytes())})
            first = owner.scoped({**self.scope, 'company_ids': [self.sources[0]['company_id']],
                'source_snapshot_ids': ['sample']})
            result = first.list_figures()
            self.assertEqual(result['status'], 'with_gaps')
            self.assertEqual(result['figures'], [])
            self.assertEqual(result['gaps'][0]['source_snapshot_id'], 'sample')
            self.assertNotIn('independent-other', json.dumps(result))
            with self.assertRaisesRegex(ValueError, 'Unknown figure'):
                first.read_figure({'source_snapshot_id': 'sample', 'figure_id': first_id})
            other = owner.scoped({**self.scope, 'company_ids': [self.sources[1]['company_id']],
                'source_snapshot_ids': ['independent-other']})
            self.assertEqual(other.list_figures()['status'], 'complete')
            self.assertEqual(other.list_figures()['gaps'], [])

    def test_resealed_wrong_dataset_binding_is_rejected_before_query_access(self):
        path = self.bundle / 'manifest.json'
        value = json.loads(path.read_text())
        value['dataset_manifest_sha256'] = '0' * 64
        save(path, value)
        with self.assertRaisesRegex(ValueError, 'dataset binding mismatch'):
            self.owner.bind_figures({'path': str(self.bundle), 'manifest_sha256': digest(path.read_bytes())})
        self.assertIsNone(self.owner.figure_bundle_ref)

    def test_legacy_weaker_coordinate_bundles_are_not_query_figure_evidence(self):
        path = self.bundle / 'manifest.json'
        original = json.loads(path.read_text())
        for version in ('figure-materials-v1', 'figure-materials-v2'):
            value = copy.deepcopy(original)
            value['version'] = version
            if version == 'figure-materials-v1':
                for row in value['figures']:
                    row['status'] = 'protocol_validated'
            save(path, value)
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'strong figure-materials-v3'):
                self.owner.bind_figures({'path': str(self.bundle), 'manifest_sha256': digest(path.read_bytes())})
            self.assertIsNone(self.owner.figure_bundle_ref)

    def test_public_reference_cannot_mutate_pin_and_existing_scopes_cannot_rebind_it(self):
        port = self.first_only()
        public = port.figure_bundle_ref
        public['manifest_sha256'] = '0' * 64
        figure, = port.list_figures()['figures']
        self.assertEqual(port.read_figure(self.request(figure))['figure_bundle_ref'], self.ref)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            port.bind_figures({**self.ref, 'manifest_sha256': '0' * 64})

    def test_catalog_source_hint_is_metadata_and_still_bounded_without_changing_legacy_shape(self):
        self.assertNotIn('figure_inventory', self.owner.scoped(self.scope).discover_catalog({'kind': 'sources'})['items'][0]['metadata'])
        port = self.first_only()
        page = port.discover_catalog({'kind': 'sources', 'max_bytes': 256})
        self.assertEqual(page['status'], 'item_too_large')
        self.assertEqual(page['items'], [])
        full = port.discover_catalog({'kind': 'sources'})
        hint = full['items'][0]['metadata']['figure_inventory']
        self.assertEqual(hint['read_operation'], 'read_figure')
        self.assertEqual(len(hint['figures']), 1)
        self.assertNotIn('transcription', json.dumps(hint))
        self.assertLessEqual(full['bytes_returned'], 12000)


if __name__ == '__main__':
    unittest.main()
