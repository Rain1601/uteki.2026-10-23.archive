"""Independent checks for immutable artifact readback and bounded previews."""
import json
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.run_artifacts import ArtifactReadProgress, ArtifactStore, json_size, load_evidence_bundle


class RunArtifactTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scope = {'snapshot_id': 'snapshot-a', 'company_ids': ['acme'],
                      'source_snapshot_ids': ['source-a'], 'source_policy_id': 'local-frozen-v1',
                      'knowledge_cutoff': '2032-06-01', 'include_candidates': True}
        self.store = ArtifactStore(self.root)

    def put(self, value, **kwargs):
        return self.store.put('tool_result', value, scope=self.scope, step=1, **kwargs)

    def test_child_reads_then_parent_pages_do_not_invent_new_content(self):
        cases = [({'x': 'seen', 'y': 'unseen'}, ['/x']),
                 ([{'value': 'a'}, {'value': 'b'}, {'value': 'c'}], ['/0', '/1', '/2'])]
        for value, pointers in cases:
            with self.subTest(value=value):
                ref = self.put(value)
                progress = ArtifactReadProgress()
                for pointer in pointers:
                    page = self.store.read({'artifact_id': ref['artifact_id'], 'pointer': pointer, 'limit': 100})
                    self.assertTrue(progress.apply(progress.page_mark(page)))
                page = self.store.read({'artifact_id': ref['artifact_id'], 'limit': len(pointers)})
                self.assertFalse(progress.apply(progress.page_mark(page)))
                if isinstance(value, dict):
                    page = self.store.read({'artifact_id': ref['artifact_id'], 'offset': 1})
                    self.assertTrue(progress.apply(progress.page_mark(page)))
                self.assertFalse(progress.apply(progress.preview_mark(ref['artifact_id'], value, value)))

    def test_partial_preview_and_child_ranges_share_parent_read_progress(self):
        value = {'x': 'seen', 'y': 'unseen'}
        ref = self.put(value)
        progress = ArtifactReadProgress()
        progress.apply(progress.preview_mark(ref['artifact_id'], value, {'x': 'seen'}))
        page = self.store.read({'artifact_id': ref['artifact_id'], 'limit': 1})
        self.assertFalse(progress.apply(progress.page_mark(page)))
        for offset in (0, 3):
            page = self.store.read({'artifact_id': ref['artifact_id'], 'pointer': '/y', 'offset': offset, 'limit': 3})
            self.assertTrue(progress.apply(progress.page_mark(page)))
        page = self.store.read({'artifact_id': ref['artifact_id']})
        self.assertFalse(progress.apply(progress.page_mark(page)))

    def read_all(self, artifact_id, *, pointer='', limit=3, max_bytes=512):
        request = {'artifact_id': artifact_id, 'pointer': pointer, 'limit': limit, 'max_bytes': max_bytes}
        items, pages = [], []
        while True:
            page = self.store.read(request)
            self.assertFalse(page['gaps'])
            self.assertLessEqual(page['bytes_returned'], max_bytes)
            self.assertLessEqual(page['returned_count'], limit)
            items.extend(page['items'])
            pages.append(page)
            if page['next_cursor'] is None:
                return items, pages
            self.assertLess(len(pages), 100)
            request = {**request, 'cursor': page['next_cursor']}

    def test_last_page_and_complete_rows_survive_item_and_byte_limits(self):
        rows = [{'row': i, 'text': '完整原文' * 20, 'nested': {'value': i}} for i in range(17)]
        ref = self.put({'rows': rows, 'tail': 'unchanged'})
        got, pages = self.read_all(ref['artifact_id'], pointer='/rows')
        self.assertEqual(got, rows)
        self.assertEqual(pages[-1]['end_offset'], len(rows))
        self.assertEqual(pages[-1]['status'], 'read')
        self.assertGreater(len(pages), 2)
        self.assertEqual(self.store.load(ref['artifact_id']), {'rows': rows, 'tail': 'unchanged'})

    def test_cursor_rejects_wrong_identity_hash_scope_pointer_and_offset(self):
        ref = self.put({'rows': list(range(20)), 'other': list(range(20))})
        request = {'artifact_id': ref['artifact_id'], 'pointer': '/rows', 'limit': 2}
        cursor = self.store.read(request)['next_cursor']
        for changes in ({'artifact_id': 'unknown'}, {'sha256': '0' * 64}, {'scope_id': 'wrong'},
                        {'snapshot_id': 'wrong'}, {'pointer': '/other'}, {'offset': 21}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.read({**request, 'cursor': {**cursor, **changes}})
        with self.assertRaises(ValueError):
            self.store.read({**request, 'cursor': cursor, 'offset': 3})
        with self.assertRaises(ValueError):
            self.store.read({**request, 'cursor': cursor, 'pointer': '/other'})

    def test_unknown_id_invalid_pointer_and_out_of_range_fail(self):
        ref = self.put({'a/b~c': [1, 2, 3]})
        self.assertEqual(self.store.read({'artifact_id': ref['artifact_id'], 'pointer': '/a~1b~0c'})['items'], [1, 2, 3])
        for change in ({'artifact_id': 'unknown'}, {'pointer': '/missing'}, {'pointer': '/a~1b~0c/03'},
                       {'pointer': '/a~1b~0c/3'}, {'offset': 2}, {'pointer': 'relative'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.read({'artifact_id': ref['artifact_id'], **change})

    def test_modified_file_and_external_path_are_rejected(self):
        ref = self.put({'value': 'original'})
        (self.root/ref['path']).write_text('{"value":"modified"}')
        with self.assertRaises(ValueError):
            self.store.load(ref['artifact_id'])
        outside = {**ref, 'path': '../outside.json'}
        with self.assertRaises(ValueError):
            ArtifactStore(self.root, refs=[outside]).load(ref['artifact_id'])

    def test_same_root_symlink_cannot_replace_frozen_artifact(self):
        ref = self.put({'value': 'original'})
        path = self.root/ref['path']
        copy = self.root/'copy.json'
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        with self.assertRaises(ValueError):
            self.store.load(ref['artifact_id'])

    def test_old_artifact_keeps_original_scope_after_new_snapshot(self):
        old = self.put(list(range(9)), source_ids=['source-a'])
        cursor = self.store.read({'artifact_id': old['artifact_id'], 'limit': 2})['next_cursor']
        new_scope = {**self.scope, 'snapshot_id': 'snapshot-b', 'source_snapshot_ids': ['source-a', 'source-b']}
        new = self.store.put('tool_result', list(range(10)), scope=new_scope, step=2, source_ids=['source-b'])
        page = self.store.read({'artifact_id': old['artifact_id'], 'cursor': cursor, 'limit': 2})
        self.assertEqual(page['items'], [2, 3])
        self.assertEqual(page['snapshot_id'], 'snapshot-a')
        self.assertEqual(page['scope_id'], old['scope_id'])
        with self.assertRaises(ValueError):
            self.store.read({'artifact_id': new['artifact_id'], 'cursor': cursor})
        reloaded = ArtifactStore(self.root, refs=[old, new])
        self.assertEqual(reloaded.read({'artifact_id': old['artifact_id'], 'cursor': cursor})['offset'], 2)

    def test_oversized_row_exposes_child_pointer_and_full_text_can_be_read(self):
        text = '汉字原文🙂' * 300
        ref = self.put({'rows': [{'text': text, 'label': 'full row'}]})
        page = self.store.read({'artifact_id': ref['artifact_id'], 'pointer': '/rows', 'max_bytes': 512})
        self.assertEqual(page['items'], [])
        self.assertEqual(page['status'], 'item_too_large')
        self.assertEqual(page['gaps'][0]['pointer'], '/rows/0')
        child = self.store.read({'artifact_id': ref['artifact_id'], 'pointer': '/rows/0', 'max_bytes': 512})
        self.assertEqual(child['gaps'][0]['pointer'], '/rows/0/text')
        characters, pages = self.read_all(ref['artifact_id'], pointer='/rows/0/text', limit=1000)
        self.assertEqual(''.join(characters), text)
        self.assertGreater(len(pages), 1)

    def test_required_bytes_is_sufficient_to_retry_complete_single_item(self):
        item = {'text': 'x' * 700}
        ref = self.put([item])
        page = self.store.read({'artifact_id': ref['artifact_id'], 'max_bytes': 512})
        needed = page['gaps'][0]['required_bytes']
        retry = self.store.read({'artifact_id': ref['artifact_id'], 'cursor': page['next_cursor'], 'max_bytes': needed})
        self.assertEqual(retry['items'], [item])
        self.assertEqual(retry['status'], 'read')

    def test_preview_is_bounded_and_every_omitted_value_has_readback(self):
        value = {'status': 'complete', 'blocks': [{'block_id': str(i), 'text': '原文' * 80} for i in range(20)],
                 'huge_text': '正文' * 2000, 'meta': {'complete': True}}
        ref = self.put(value)
        preview = self.store.preview(ref['artifact_id'], max_bytes=1400, limit=3)
        self.assertTrue(preview['truncated'])
        self.assertLessEqual(json_size(preview['value']), 1400)
        if 'blocks' in preview['value']:
            self.assertEqual(preview['value']['blocks'], value['blocks'][:len(preview['value']['blocks'])])
        self.assertTrue(any(read['pointer'] == '/huge_text' for read in preview['reads']))
        self.assertEqual(self.store.load(ref['artifact_id']), value)
        small = self.put({'value': 2})
        self.assertEqual(self.store.preview(small['artifact_id']), {'value': {'value': 2}, 'truncated': False, 'reads': []})

    def test_registered_ref_scope_and_source_ids_cannot_contradict_scope(self):
        ref = self.put({'value': 'original'})
        with self.subTest(boundary='scope_id'), self.assertRaises(ValueError):
            ArtifactStore(self.root, refs=[{**ref, 'scope_id': 'wrong'}])
        with self.subTest(boundary='source_ids'), self.assertRaises(ValueError):
            self.put({'value': 'outside'}, source_ids=['other-company-source'])
        with self.subTest(boundary='duplicate_identity'), self.assertRaises(ValueError):
            self.put({'value': 'original'}, source_ids=['other-company-source'])

    def write_bundle(self, bundle):
        path = self.root/'evidence-bundle.json'
        path.write_text(json.dumps(bundle))
        (self.root/'manifest.json').write_text(json.dumps({'files': {'evidence-bundle.json': digest(path.read_bytes())}}))

    def test_v1_bundle_stays_embedded_and_v2_reads_hash_checked_artifacts(self):
        legacy = {'schema_version': 'autonomous-evidence-manifest-v1', 'items': [{'evidence_id': 'old', 'value': {'text': 'old'}}]}
        self.write_bundle(legacy)
        before = (self.root/'evidence-bundle.json').read_bytes()
        self.assertEqual(load_evidence_bundle(self.root), legacy)
        self.assertEqual((self.root/'evidence-bundle.json').read_bytes(), before)
        value = {'blocks': [{'text': 'complete original'}]}
        ref = self.put(value, evidence_id='evidence-1')
        current = {'schema_version': 'autonomous-evidence-manifest-v2',
                   'items': [{'evidence_id': 'evidence-1', 'artifact': ref}]}
        self.write_bundle(current)
        loaded = load_evidence_bundle(self.root)
        self.assertEqual(loaded['items'][0]['value'], value)
        self.assertEqual(loaded['items'][0]['artifact']['scope'], ref['scope'])
        (self.root/ref['path']).write_text('{}')
        with self.assertRaises(ValueError):
            load_evidence_bundle(self.root)

    def test_bundle_tamper_and_unknown_version_rejected(self):
        self.write_bundle({'schema_version': 'unknown', 'items': []})
        with self.assertRaises(ValueError):
            load_evidence_bundle(self.root)
        self.write_bundle({'schema_version': 'autonomous-evidence-manifest-v1', 'items': []})
        (self.root/'evidence-bundle.json').write_text('{}')
        with self.assertRaises(ValueError):
            load_evidence_bundle(self.root)
