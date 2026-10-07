"""Offline human-score sidecar checks; no model requests or frozen-data writes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.review_workbench.data import run_scores as store


def process_write(path, binding, payload, start, result):
    if not start.wait(timeout=10):
        result.put('timeout')
        return
    try:
        result.put(store.save_score(path, binding, payload)['id'])
    except Exception as error:
        result.put(type(error).__name__)


class RunScoresTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root/'sidecar/scores.json'
        self.binding = {'trace_id': 'cedar-model-a', 'revision': 'a'*64, 'result_sha256': 'b'*64}
        self.payload = {'binding': deepcopy(self.binding), 'rubric_version': 'agent-result-v1',
                        'reviewer': 'Rain', 'scores': {'accuracy': 0, 'coverage': None, 'analysis': 4, 'evidence': 5},
                        'notes': 'Original evidence needs review. 原文仍需核对。'}

    def save(self, **changes):
        return store.save_score(self.path, self.binding, {**self.payload, **changes})

    def test_missing_file_empty_and_save_appends_without_changing_result(self):
        original = self.root/'result.json'
        original.write_text('{"status":"candidate"}')
        raw = original.read_bytes()
        empty = store.load_scores(self.path, self.binding)
        self.assertEqual((empty['current'], empty['stale']), ([], []))
        self.assertFalse(self.path.parent.exists())
        first = self.save()
        second = self.save(notes='Second independent review')
        loaded = store.load_scores(self.path, self.binding)
        self.assertEqual(loaded['current'], [first, second])
        self.assertEqual(loaded['stale'], [])
        self.assertNotEqual(first['id'], second['id'])
        self.assertTrue(first['created_at'].endswith('+00:00'))
        self.assertEqual(first['scores']['accuracy'], 0)
        self.assertIsNone(first['scores']['coverage'])
        self.assertEqual(original.read_bytes(), raw)
        first['scores']['accuracy'] = 5
        self.assertEqual(store.load_scores(self.path, self.binding)['current'][0]['scores']['accuracy'], 0)
        self.assertNotIn('adoption', json.loads(self.path.read_text()))

    def test_trace_isolation_and_exact_binding_revision_hash_staleness(self):
        first = self.save()
        other = {**self.binding, 'trace_id': 'cedar-model-b'}
        second = store.save_score(self.path, other, {**self.payload, 'binding': other})
        self.assertEqual(store.load_scores(self.path, other)['current'], [second])
        for changed in ({'revision': 'c'*64}, {'result_sha256': 'd'*64}, {'revision': 12}):
            binding = {**self.binding, **changed}
            loaded = store.load_scores(self.path, binding)
            self.assertEqual(loaded['current'], [])
            self.assertEqual(loaded['stale'], [first])
            new = store.save_score(self.path, binding, {**self.payload, 'binding': binding})
            self.assertEqual(store.load_scores(self.path, binding)['current'], [new])
            # Restore an isolated history for the next variant.
            self.path.unlink()
            first = self.save()

    def test_stale_submission_is_409_class_and_does_not_touch_store(self):
        for change in ({'revision': 'c'*64}, {'trace_id': 'other-trace'}, {'result_sha256': 'd'*64}):
            with self.subTest(change=change), self.assertRaises(store.StaleScoreError):
                self.save(binding={**self.binding, **change})
        self.assertFalse(self.path.parent.exists())
        self.save()
        raw = self.path.read_bytes()
        with self.assertRaises(store.StaleScoreError):
            self.save(binding={**self.binding, 'revision': 1})
        self.assertEqual(self.path.read_bytes(), raw)

    def test_strict_input_rejects_unknown_fields_boolean_missing_and_unscored(self):
        invalid = [dict(self.payload, surprise=True), dict(self.payload, rubric_version='future-v2'),
                   dict(self.payload, reviewer='  '), dict(self.payload, reviewer='x'*101),
                   dict(self.payload, notes='x'*4001), dict(self.payload, notes=None),
                   {k: v for k, v in self.payload.items() if k != 'notes'}]
        for value in (True, False, -1, 6, 1.0, '0', [], {}):
            invalid.append(dict(self.payload, scores={**self.payload['scores'], 'accuracy': value}))
        invalid.extend([dict(self.payload, scores={k: None for k in store.DIMENSIONS}),
                        dict(self.payload, scores={k: 3 for k in store.DIMENSIONS if k != 'analysis'}),
                        dict(self.payload, scores={**self.payload['scores'], 'extra': 4})])
        for value in invalid:
            with self.subTest(payload=value), self.assertRaises(store.ScoreValidationError):
                store.save_score(self.path, self.binding, value)
        self.assertFalse(self.path.parent.exists())

    def test_binding_types_and_full_sha_are_explicit(self):
        invalid = [{**self.binding, 'revision': value} for value in (None, '', ' ', True, False, -1, 1.0, [], {})]
        invalid += [{**self.binding, 'result_sha256': value} for value in ('', 'a', 'F'*64, None)]
        invalid += [{**self.binding, 'trace_id': value} for value in ('', '../trace', '/absolute', 'x'*201)]
        invalid += [{**self.binding, 'extra': 1}, {'trace_id': 'a'}]
        for value in invalid:
            with self.subTest(binding=value), self.assertRaises(store.ScoreValidationError):
                store.load_scores(self.path, value)
        binding = {**self.binding, 'revision': 0}
        saved = store.save_score(self.path, binding, {**self.payload, 'binding': binding})
        self.assertEqual(saved['binding']['revision'], 0)
        with self.assertRaises(store.StaleScoreError):
            store.save_score(self.path, binding, {**self.payload, 'binding': {**binding, 'revision': '0'}})

    def test_corrupt_history_never_silently_resets_or_overwrites(self):
        self.path.parent.mkdir()
        for raw in ('{', '', 'null', '{"schema_version":"unknown","records":[]}',
                    '{"schema_version":"agent-result-scores-v1","records":[{}]}'):
            self.path.write_text(raw)
            with self.assertRaises(store.CorruptScoreStoreError): store.load_scores(self.path, self.binding)
            with self.assertRaises(store.CorruptScoreStoreError): self.save()
            self.assertEqual(self.path.read_text(), raw)
        self.path.unlink()
        record = self.save()
        state = json.loads(self.path.read_text())
        for mutate in ('duplicate', 'boolean', 'timestamp'):
            invalid = deepcopy(state)
            if mutate == 'duplicate': invalid['records'].append(record)
            elif mutate == 'boolean': invalid['records'][0]['scores']['accuracy'] = True
            else: invalid['records'][0]['created_at'] = '2031-01-01'
            self.path.write_text(json.dumps(invalid))
            with self.assertRaises(store.CorruptScoreStoreError): store.load_scores(self.path, self.binding)

    def test_threaded_writes_preserve_all_history(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(lambda index: self.save(notes=str(index)), range(18)))
        loaded = store.load_scores(self.path, self.binding)['current']
        self.assertEqual(len(loaded), 18)
        self.assertEqual({r['id'] for r in loaded}, {r['id'] for r in records})

    def test_separate_processes_share_the_same_lock(self):
        ctx = multiprocessing.get_context('spawn')
        start, result = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=process_write, args=(str(self.path), self.binding,
                     {**self.payload, 'notes': str(index)}, start, result)) for index in range(4)]
        try:
            for process in processes: process.start()
            start.set()
            identities = [result.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
            loaded = store.load_scores(self.path, self.binding)['current']
            self.assertEqual(len(loaded), 4)
            self.assertEqual({r['id'] for r in loaded}, set(identities))
        finally:
            for process in processes:
                if process.is_alive(): process.terminate(); process.join(timeout=5)
            result.close()
            result.join_thread()

    def test_store_byte_limit_rejects_oversized_reads_and_preserves_full_store(self):
        self.path.parent.mkdir()
        with self.path.open('wb') as stream:
            stream.truncate(store.MAX_STORE_BYTES + 1)
        with patch.object(store.json, 'loads', side_effect=AssertionError('Oversized file must not be parsed')):
            with self.assertRaisesRegex(store.CorruptScoreStoreError, 'size limit'):
                store.load_scores(self.path, self.binding)
        self.path.unlink()
        self.save()
        raw = self.path.read_bytes()
        with patch.object(store, 'MAX_STORE_BYTES', len(raw)), self.assertRaisesRegex(store.ScoreValidationError, 'size limit'):
            self.save(notes='An appended record would exceed the byte cap')
        self.assertEqual(self.path.read_bytes(), raw)

    def test_store_record_limit_rejects_overflow_and_preserves_existing_records(self):
        record = self.save()
        rows = [{**record, 'id': 'score-' + format(index, '032x')} for index in range(store.MAX_RECORDS)]
        self.path.write_text(json.dumps({'schema_version': store.STORE_VERSION, 'records': rows}))
        self.assertEqual(len(store.load_scores(self.path, self.binding)['current']), store.MAX_RECORDS)
        raw = self.path.read_bytes()
        with self.assertRaisesRegex(store.ScoreValidationError, 'record limit'):
            self.save()
        self.assertEqual(self.path.read_bytes(), raw)
        rows.append({**record, 'id': 'score-' + format(store.MAX_RECORDS, '032x')})
        self.path.write_text(json.dumps({'schema_version': store.STORE_VERSION, 'records': rows}))
        with self.assertRaisesRegex(store.CorruptScoreStoreError, 'record limit'):
            store.load_scores(self.path, self.binding)

    def test_atomic_failure_preserves_previous_history(self):
        self.save()
        before = self.path.read_bytes()
        with patch.object(store.os, 'replace', side_effect=OSError('offline write fault')), self.assertRaises(OSError):
            self.save(notes='Must not appear')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['scores.json', 'scores.json.lock'])

    def test_symlink_data_parent_and_lock_are_rejected(self):
        outside = self.root/'outside.json'
        outside.write_text(json.dumps({'schema_version': store.STORE_VERSION, 'records': []}))
        self.path.parent.mkdir()
        self.path.symlink_to(outside)
        with self.assertRaises(store.ScoreValidationError): self.save()
        with self.assertRaises(store.ScoreValidationError): store.load_scores(self.path, self.binding)
        self.path.unlink()
        lock = self.path.with_name(self.path.name+'.lock')
        lock.symlink_to(outside)
        with self.assertRaises(store.CorruptScoreStoreError): self.save()
        parent = self.root/'linked'
        parent.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(store.ScoreValidationError):
            store.save_score(parent/'other.json', self.binding, self.payload)
        self.assertEqual(json.loads(outside.read_text())['records'], [])
