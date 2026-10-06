"""Catalog pagination and schema samples use the same frozen execution scope."""
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import save
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_scoped_query_service import make_scoped_dataset


class QueryCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        make_scoped_dataset(self.root, schema_metadata=True)
        db = duckdb.connect(str(self.root/'research.duckdb'))
        original = list(db.execute("SELECT * FROM observations WHERE record_id = 'acme-annual-revenue-2031'").fetchone())
        for i in range(31):
            row = original.copy()
            row[0], row[1] = f'large-record-{i:02}', f'acme-department-{i:02}'
            payload = json.loads(row[-1])
            payload.update(record_id=row[0], entity_id=row[1], dimensions={'BusinessAxis': f'Department{i:02}'})
            row[-1] = json.dumps(payload)
            db.execute('INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', row)
        db.close()
        manifest = json.loads((self.root/'manifest.json').read_text())
        manifest['files'] = {name: digest((self.root/name).read_bytes()) for name in manifest['files']}
        save(self.root/'manifest.json', manifest)
        self.owner = QueryDataPort(self.root)
        self.addCleanup(self.owner.close)
        self.scope = {'snapshot_id': self.owner.snapshot_id, 'company_ids': ['acme'],
                      'source_snapshot_ids': ['acme-annual', 'acme-future'], 'source_policy_id': 'local-frozen-v1',
                      'knowledge_cutoff': '2032-06-01', 'include_candidates': True}
        self.port = self.owner.scoped(self.scope)

    def pages(self, method, request):
        result, cursors = [], []
        while True:
            page = method(request)
            self.assertLessEqual(page['bytes_returned'], request.get('max_bytes', 12000))
            self.assertLessEqual(page['returned_count'], request.get('limit', 20))
            self.assertFalse(page['gaps'])
            result.extend(page['items'])
            if page['next_cursor'] is None:
                return result, cursors
            cursors.append(page['next_cursor'])
            self.assertLess(len(cursors), 100)
            request = {**request, 'cursor': page['next_cursor']}

    def test_large_catalog_and_probe_reach_final_page_without_losing_entries(self):
        items, cursors = self.pages(self.port.discover_catalog, {'kind': 'entities', 'limit': 3, 'max_bytes': 1500})
        self.assertGreater(len(cursors), 5)
        self.assertEqual(len(items), 33)
        self.assertEqual(len({i['item_id'] for i in items}), len(items))
        self.assertIn('acme-department-30', {i['entity_id'] for i in items})
        probe, cursors = self.pages(self.port.probe_schema, {'limit': 4, 'max_bytes': 4000})
        examples = [i for i in probe if i['kind'] == 'example']
        self.assertIn('acme-department-30', {i['entity_id'] for i in examples})
        self.assertTrue(all(i['source_snapshot_id'] == 'acme-annual' and i['status'] == 'candidate' for i in examples))
        self.assertNotIn('output_contracts', json.dumps(probe))

    def test_cursor_rejects_wrong_scope_filters_hash_and_offset(self):
        cursor = self.port.discover_catalog({'kind': 'entities', 'limit': 1})['next_cursor']
        for changes in ({'scope_id': 'wrong'}, {'snapshot_id': 'wrong'}, {'content_hash': 'wrong'},
                        {'offset': 999}, {'checksum': 'wrong'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.port.discover_catalog({'kind': 'entities', 'cursor': {**cursor, **changes}})
        with self.assertRaises(ValueError):
            self.port.discover_catalog({'kind': 'sources', 'cursor': cursor})
        denied = self.owner.scoped({**self.scope, 'include_candidates': False})
        with self.assertRaises(ValueError):
            denied.discover_catalog({'kind': 'entities', 'cursor': cursor})
        with self.assertRaises(ValueError):
            self.port.probe_schema({'cursor': cursor})

    def test_oversized_item_has_explicit_retry_and_never_truncates_fields(self):
        request = {'kind': 'sources', 'max_bytes': 256}
        page = self.port.discover_catalog(request)
        self.assertEqual(page['status'], 'item_too_large')
        self.assertEqual(page['items'], [])
        gap, = page['gaps']
        self.assertEqual(gap['item_id'], 'acme-annual')
        retry = self.port.discover_catalog({**request, 'cursor': page['next_cursor'], 'max_bytes': gap['required_bytes']})
        self.assertEqual(retry['status'], 'complete')
        source = next(s for s in self.owner.sources if s['source_snapshot_id'] == 'acme-annual')
        self.assertEqual(retry['items'][0]['metadata'], source)

    def test_scope_and_candidate_permissions_apply_to_every_view(self):
        for kind in ('sources', 'entities', 'metrics', 'fiscal_periods', 'coverage'):
            items, _ = self.pages(self.port.discover_catalog, {'kind': kind})
            rendered = json.dumps(items)
            for hidden in ('other-annual', 'other-services', 'acme-amended', 'acme-future', 'FutureObservationMember'):
                self.assertNotIn(hidden, rendered)
        denied = self.owner.scoped({**self.scope, 'include_candidates': False})
        items, _ = self.pages(denied.probe_schema, {})
        self.assertFalse(any(i['kind'] in ('example', 'fiscal_period') for i in items))
        self.assertTrue(all(not i['reported_dimensions'] and not i['accounting_bases']
                            for i in items if i['kind'] == 'entity'))
        sources = [i for i in items if i['kind'] == 'source']
        self.assertTrue(sources)
        self.assertNotIn('fiscal_periods', sources[0]['metadata'])
        self.assertEqual(denied.discover_catalog({'kind': 'fiscal_periods'})['items'], [])

    def test_explicit_resource_filters_cannot_widen_scope(self):
        for request in ({'entity_ids': ['other-services']}, {'source_snapshot_ids': ['acme-future']},
                        {'source_snapshot_ids': ['acme-amended']}, {'metric_ids': ['unknown']}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.port.probe_schema(request)
        for kind, ids in [('sources', ['other-annual']), ('entities', ['other-services'])]:
            with self.assertRaises(ValueError):
                self.port.discover_catalog({'kind': kind, 'ids': ids})
        items, _ = self.pages(self.port.probe_schema, {'entity_ids': ['acme-services'], 'metric_ids': ['revenue'],
                                                      'source_snapshot_ids': ['acme-annual']})
        examples = [i for i in items if i['kind'] == 'example']
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]['record']['value_decimal'], '90')
        self.assertEqual(examples[0]['period']['end'], '2030-12-31')
        other = self.owner.scoped({**self.scope, 'company_ids': ['other'], 'source_snapshot_ids': ['other-annual']})
        items, _ = self.pages(other.probe_schema, {})
        self.assertEqual({i['record']['value_decimal'] for i in items if i['kind'] == 'example'}, {'800'})
