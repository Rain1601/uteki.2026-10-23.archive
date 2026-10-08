"""Previously read locations remain pageable; navigation never grants body credit."""
from copy import deepcopy
import unittest

from uteki.agents.data_query.autonomous import _read_body_catalog_page
from uteki.infrastructure.research_data.run_artifacts import ArtifactStore, load_evidence_bundle
from tests.unit import test_analysis_evidence_runtime as runtime_fixtures
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit import test_answer_handoff as handoff_fixtures


class ReadBodyCatalogPaginationTests(unittest.TestCase):
    setUp = handoff_fixtures.AnswerHandoffTests.setUp

    def make_catalog(self):
        self.store = ArtifactStore(self.root / 'catalog')
        self.evidence, self.refs, self.delivered = {}, {}, {}
        for c in ('A', 'B', 'C'):
            blocks = [{'block_id': f'{c}{n:02}', 'text': f'Original {c} paragraph {n}. ' + 'x' * 200}
                      for n in range(20)]
            value = {'source_snapshot_id': 'acme-annual', 'blocks': blocks}
            self.evidence[c] = {'kind': 'context', 'scope': self.scope.model_dump(mode='json'), 'value': value}
            self.refs[c] = self.store.put('context', value, scope=self.scope, step=1, evidence_id=c)
            self.delivered[c] = {b['block_id'] for b in blocks}

    def page(self, *, step=2, scope=None, max_bytes=1800):
        return _read_body_catalog_page(self.store, self.evidence, self.refs, self.delivered,
            scope=scope or self.scope, step=step, max_bytes=max_bytes)

    def all_rows(self, first):
        page, rows = first, list(first['items'])
        while page['next_cursor']:
            page = self.store.read({'artifact_id': first['artifact_id'],
                'cursor': page['next_cursor'], 'limit': 7, 'max_bytes': 1800})
            self.assertGreater(page['returned_count'], 0)
            rows.extend(page['items'])
        return rows

    def test_sixty_locations_are_pageable_and_exact_original_can_be_reopened(self):
        self.make_catalog()
        page = self.page()
        self.assertTrue(page['navigation_only'])
        self.assertGreater(page['omitted_count'], 0)
        self.assertLessEqual(page['bytes_returned'], page['byte_limit'])
        rows = self.all_rows(page)
        self.assertEqual([r['block_id'] for r in rows], [f'{c}{n:02}' for c in 'ABC' for n in range(20)])
        selected = rows[18]  # Early A context remains reachable after B/C were read.
        self.assertNotIn(selected['block_id'], [r['block_id'] for r in page['items']])
        original = self.store.read(selected['read_request'])
        self.assertEqual(original['items'], self.evidence['A']['value']['blocks'][18]['text'])
        self.assertEqual(self.store.refs[page['artifact_id']].evidence_id, None)
        self.assertFalse(any('text' in row for row in rows))

    def test_unchanged_content_reuses_id_and_cursor_stays_bound_after_new_read(self):
        self.make_catalog()
        old = self.page()
        self.evidence = dict(reversed(list(self.evidence.items())))
        self.assertEqual(self.page(step=20)['artifact_id'], old['artifact_id'])
        self.evidence['D'] = deepcopy(self.evidence['A'])
        self.evidence['D']['value']['blocks'] = [{'block_id': 'D00', 'text': 'Additional original.'}]
        self.refs['D'] = self.store.put('context', self.evidence['D']['value'], scope=self.scope, step=21, evidence_id='D')
        self.delivered['D'] = {'D00'}
        new = self.page(step=22)
        self.assertNotEqual(new['artifact_id'], old['artifact_id'])
        self.assertEqual(len(self.all_rows(old)), 60)
        self.assertEqual(len(self.all_rows(new)), 61)
        for key, value in [('artifact_id', new['artifact_id']), ('sha256', '0' * 64),
                           ('scope_id', 'another-scope'), ('snapshot_id', 'another-snapshot')]:
            cursor = {**old['next_cursor'], key: value}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'cursor scope, hash or pointer mismatch'):
                self.store.read({'artifact_id': old['artifact_id'], 'cursor': cursor})

    def test_catalog_filters_other_scope_sources_unread_layout_and_duplicate_blocks(self):
        self.make_catalog()
        self.delivered['A'].remove('A00')
        self.evidence['A']['value']['blocks'][1]['layout_role'] = 'page_furniture'
        self.evidence['A']['value']['blocks'][2]['text'] = '   '
        self.evidence['old'] = deepcopy(self.evidence['B'])
        self.evidence['old']['scope']['snapshot_id'] = 'old-snapshot'
        self.delivered['old'] = {'B00'}
        self.evidence['foreign'] = deepcopy(self.evidence['B'])
        self.evidence['foreign']['value']['source_snapshot_id'] = 'foreign-source'
        self.delivered['foreign'] = {'B00'}
        self.evidence['duplicate'] = deepcopy(self.evidence['B'])
        self.delivered['duplicate'] = {'B00'}
        self.refs['duplicate'] = self.refs['B']
        before = deepcopy(self.delivered)
        rows = self.all_rows(self.page())
        self.assertEqual(len(rows), 57)
        self.assertFalse({'A00', 'A01', 'A02'} & {r['block_id'] for r in rows})
        self.assertEqual({r['context_id'] for r in rows}, {'A', 'B', 'C'})
        self.assertEqual(self.delivered, before)
        other_scope = self.scope.model_copy(update={'snapshot_id': 'next-snapshot'})
        self.assertEqual(self.page(scope=other_scope)['total_count'], 0)


class ReadBodyCatalogRuntimeTests(unittest.TestCase):
    setUp = handoff_fixtures.AnswerHandoffTests.setUp
    run_actions = runtime_fixtures.AnalysisEvidenceRuntimeTests.run_actions

    def test_catalog_read_is_navigation_not_body_evidence_and_original_read_still_works(self):
        saved = {}
        def read_catalog(packet):
            catalog = packet['read_body_catalog']
            saved['artifact_id'] = catalog['artifact_id']
            return {'action': 'read_artifact', 'artifact_read': {'artifact_id': catalog['artifact_id']},
                    'requirement_ids': ['business']}
        def try_unread(packet):
            self.assertTrue(packet['observation']['result']['navigation_only'])
            self.assertIsNone(packet['observation']['artifact']['evidence_id'])
            self.assertEqual(packet['read_body_catalog']['artifact_id'], saved['artifact_id'])
            self.assertEqual({r['block_id'] for r in packet['read_body_catalog']['items']}, {'b1'})
            row = packet['observation']['result']['items'][0]
            saved['read_request'] = row['read_request']
            return {'action': 'select_evidence', 'requirement_ids': ['business'],
                    'delivery': {'blocks': [{'context_id': row['context_id'], 'block_id': 'b2'}]}}
        def reopen(packet):
            self.assertEqual(packet['observation']['status'], 'rejected')
            return {'action': 'read_artifact', 'requirement_ids': ['business'],
                    'artifact_read': saved['read_request']}
        result, planner, output = self.run_actions([source_plan(), context_read(), read_catalog,
            try_unread, reopen, runtime_fixtures.choose('b1'), {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][3]['status'], 'rejected')
        bundle = load_evidence_bundle(output)
        self.assertFalse(any(item['kind'] == 'read_body_catalog' for item in bundle['items']))
        self.assertEqual({r['block_id'] for r in planner.packets[-1]['read_body_catalog']['items']}, {'b1'})


if __name__ == '__main__':
    unittest.main()
