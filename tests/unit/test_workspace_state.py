"""Persistent display state is scoped, concurrent and independent of frozen research."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import duckdb

from apps.review_workbench.data import workspace_state as state
from apps.review_workbench.data import direct_extraction_views as direct
from apps.review_workbench.data import evaluation_artifacts as evaluation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_in_process(root, payload, ready, start, result):
    """Each process has its own thread lock; this exercises the filesystem lock."""
    ready.put(True)
    if not start.wait(timeout=10):
        result.put('start_timeout')
        return
    try:
        result.put(state.update_state(Path(root), payload)['revision'])
    except state.WorkspaceConflictError:
        result.put('conflict')


class WorkspaceStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.datasets = {'schema_version': 'data-evaluation-view-v1', 'datasets': [], 'runs': []}
        self.runs = {'schema_version': 'direct-extraction-view-v1', 'runs': []}
        self.tasks = {'schema_version': state.TASK_VERSION, 'tasks': []}
        self.materials = {}
        for company, year in [('cedar', '2031'), ('birch', '2031'), ('cedar', '2032')]:
            self.add_dataset(company, year)
            self.add_run(company + '-' + year, 'first')
        self.add_run('cedar-2031', 'second')
        self.save('data/mcp/readonly-catalog.json', {'catalog': 'unrelated frozen MCP config'})

    def save(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')
        return sha(path)

    def add_dataset(self, company, year):
        identity = company + '-' + year
        relative = 'data/synthetic/' + identity
        folder = self.root / relative
        raw_text = 'Synthetic ' + company + ' capacity for ' + year + ': 12 units.'
        raw = folder / 'raw/source.txt'
        raw.parent.mkdir(parents=True)
        raw.write_text(raw_text)
        sid = identity + '-source'
        source = {'source_snapshot_id': sid, 'company_id': company,
            'source_url': 'https://example.test/' + identity, 'raw_file': 'raw/source.txt',
            'source_sha256': sha(raw), 'raw_file_sha256': sha(raw),
            'index_folder': 'indexes/document', 'index_id': identity + '-index',
            'form': 'SYNTHETIC', 'parsed_mime_type': 'text/plain', 'period_end': year + '-12-31'}
        block = {'block_id': identity + '-block', 'text': raw_text,
                 'text_hash': sha(raw), 'type': 'paragraph', 'table': None}
        self.save(relative + '/indexes/document/index.json', {'index_id': source['index_id'],
            'source_snapshot_id': sid, 'nodes': [], 'form_type': 'SYNTHETIC'})
        self.save(relative + '/indexes/document/blocks.jsonl', block)
        self.save(relative + '/indexes/document/assets.json', {'assets': []})
        self.save(relative + '/indexes/document/manifest.json', {'source_snapshot_id': sid,
            'source_sha256': sha(raw), 'artifacts': {name: {'sha256': sha(folder / 'indexes/document' / name)}
                for name in ('index.json', 'blocks.jsonl', 'assets.json')}})
        for name, value in [('sources.json', [source]), ('records.json', {'rows': []}),
                            ('evidence.json', {}), ('metrics.json', {})]:
            self.save(relative + '/' + name, value)
        with duckdb.connect(str(folder / 'research.duckdb')) as connection:
            connection.execute('CREATE TABLE observations(record_id VARCHAR, entity_id VARCHAR, source_snapshot_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE sources(source_snapshot_id VARCHAR, company_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE evidence(evidence_id VARCHAR, payload JSON)')
            connection.execute('CREATE TABLE metric_definitions(metric_id VARCHAR, payload JSON)')
            connection.execute('INSERT INTO sources VALUES (?, ?, ?)', [sid, company, json.dumps(source)])
        manifest_sha = self.save(relative + '/manifest.json', {
            'company': {'company_id': company, 'symbol': company.upper(), 'name': 'Synthetic ' + company},
            'snapshot_id': identity + '-snapshot', 'source_policy_id': 'synthetic',
            'status': 'candidate', 'source_count': 1, 'record_count': 0, 'evidence_count': 0,
            'gaps': [], 'limits': [], 'files': {str(path.relative_to(folder)): sha(path)
                for path in sorted(folder.rglob('*')) if path.is_file()}})
        self.datasets['datasets'].append({'id': identity, 'path': relative, 'company_id': company,
            'symbol': company.upper(), 'snapshot_id': identity + '-snapshot', 'manifest_sha256': manifest_sha})
        self.save(evaluation.REGISTRATION, self.datasets)
        self.materials[identity] = {'source': source, 'block': block, 'manifest_sha256': manifest_sha}

    def add_run(self, dataset, suffix):
        material = self.materials[dataset]
        source = material['source']
        rid = dataset + '-' + suffix
        relative = 'experiments/' + rid
        job = {'company_id': source['company_id'], 'source_snapshot_id': source['source_snapshot_id'],
               'task': 'Extract the explicitly delivered capacity disclosure.'}
        packet = {'company_id': source['company_id'], 'source': source, 'task': job,
                  'blocks': [material['block']], 'entity_catalog': [{'entity_id': source['company_id']}]}
        files = {name: self.save(relative + '/' + name, value) for name, value in [
            ('job.json', job), ('packet.json', packet), ('result.json', {'status': 'completed_with_gaps'})]}
        run_sha = self.save(relative + '/manifest.json', {'files': files})
        pin = {'id': dataset, 'manifest_sha256': material['manifest_sha256']}
        self.runs['runs'].append({'id': rid, 'path': relative, 'manifest_sha256': run_sha, 'dataset': pin})
        self.save(direct.REGISTRATION, self.runs)
        tid = dataset + '-capacity'
        task = next((t for t in self.tasks['tasks'] if t['task_id'] == tid), None)
        if task is None:
            task = {'task_id': tid, 'label_zh': '产能披露', 'label_en': 'Capacity disclosure',
                    'dataset': pin, 'company_id': source['company_id'],
                    'source_snapshot_id': source['source_snapshot_id'],
                    'source_sha256': source['source_sha256'], 'versions': []}
            self.tasks['tasks'].append(task)
        task['versions'].append({'run_id': rid, 'manifest_sha256': run_sha,
                                'input_artifacts': {name: files[name] for name in ('job.json', 'packet.json')}})
        self.save(state.REGISTRATION, self.tasks)
        return rid

    def action(self, action='select_version', revision=0, dataset='cedar-2031', run='cedar-2031-first', **changes):
        return {'action': action, 'expected_revision': revision, 'dataset_id': dataset,
                'source_snapshot_id': dataset + '-source', 'task_id': dataset + '-capacity',
                'run_id': run, **changes}

    def view(self, dataset='cedar-2031'):
        return state.material_tasks(self.root, dataset, dataset + '-source')

    def frozen_hashes(self):
        return {str(path.relative_to(self.root)): sha(path) for path in self.root.rglob('*')
                if path.is_file() and 'review_workbench' not in path.parts}

    def test_initial_state_and_material_never_select_first_or_latest(self):
        self.assertEqual(state.read_state(self.root)['revision'], 0)
        self.assertFalse((self.root / state.STATE_PATH).exists())
        view = self.view()
        self.assertEqual(view['gaps'], [])
        self.assertIsNone(view['tasks'][0]['selected_run_id'])
        self.assertFalse(any(version['selected'] for version in view['tasks'][0]['versions']))
        self.assertFalse((self.root / state.STATE_PATH).exists())

    def test_runs_are_validated_once_per_request_and_never_reused_across_reads(self):
        with patch.object(direct, 'load_run', wraps=direct.load_run) as load:
            view = self.view()
        self.assertCountEqual([call.args[1] for call in load.call_args_list],
                              ['cedar-2031-first', 'cedar-2031-second'])
        self.assertCountEqual(view['loaded_runs'], ['cedar-2031-first', 'cedar-2031-second'])
        job = self.root / 'experiments/cedar-2031-first/job.json'
        job.write_text(job.read_text() + ' ')
        self.assertNotIn('cedar-2031-first', self.view()['loaded_runs'])

    def test_selection_survives_read_and_new_run_without_automatic_replacement(self):
        state.update_state(self.root, self.action())
        self.assertEqual(state.read_state(self.root)['revision'], 1)
        self.add_run('cedar-2031', 'third')
        self.assertEqual(self.view()['tasks'][0]['selected_run_id'], 'cedar-2031-first')
        self.assertIsNone(self.view('birch-2031')['tasks'][0]['selected_run_id'])
        self.assertIsNone(self.view('cedar-2032')['tasks'][0]['selected_run_id'])
        with patch.object(state, '_save', side_effect=AssertionError('No redundant write expected')):
            self.assertEqual(state.update_state(self.root, self.action(revision=1))['revision'], 1)

    def test_archive_requires_unselected_version_and_restore_preserves_frozen_bytes(self):
        before = self.frozen_hashes()
        state.update_state(self.root, self.action())
        with self.assertRaisesRegex(state.WorkspaceStateError, 'Selected versions'):
            state.update_state(self.root, self.action('archive', 1))
        state.update_state(self.root, self.action('select_version', 1, run=None))
        state.update_state(self.root, self.action('archive', 2))
        version = self.view()['tasks'][0]['versions'][0]
        self.assertTrue(version['archived'])
        self.assertFalse(version['selectable'])
        # The same frozen run is still loadable through its original interface.
        self.assertEqual(direct.load_run(self.root, 'cedar-2031-first')['id'], 'cedar-2031-first')
        with self.assertRaisesRegex(state.WorkspaceStateError, 'Restore'):
            state.update_state(self.root, self.action(revision=3))
        state.update_state(self.root, self.action('restore', 3))
        self.assertFalse(self.view()['tasks'][0]['versions'][0]['archived'])
        self.assertIsNone(self.view()['tasks'][0]['selected_run_id'])
        self.assertEqual(self.frozen_hashes(), before)
        audit = state.read_state(self.root)['audit_events']
        self.assertEqual([event['action'] for event in audit], ['select_version', 'select_version', 'archive', 'restore'])

    def test_missing_company_source_period_and_cross_run_scopes_fail_without_fallback(self):
        cases = [{'dataset_id': ''}, {'dataset_id': 'unknown'}, {'source_snapshot_id': 'birch-2031-source'},
                 {'source_snapshot_id': 'cedar-2032-source'}, {'task_id': 'birch-2031-capacity'},
                 {'run_id': 'birch-2031-first'}, {'run_id': 'cedar-2032-first'}, {'run_id': 'unknown'},
                 {'expected_revision': True}, {'action': 'delete'}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                state.update_state(self.root, self.action(**change))
        self.assertEqual(state.read_state(self.root)['revision'], 0)

    def test_company_source_dataset_run_and_input_pins_are_enforced(self):
        original = deepcopy(self.tasks)
        changes = [('company_id', 'birch'), ('source_sha256', 'a' * 64),
                   ('dataset.manifest_sha256', 'b' * 64), ('version.manifest_sha256', 'c' * 64),
                   ('input.job.json', 'd' * 64)]
        for field, value in changes:
            self.tasks = deepcopy(original)
            task = self.tasks['tasks'][0]
            if field.startswith('dataset.'):
                task['dataset']['manifest_sha256'] = value
            elif field.startswith('version.'):
                task['versions'][0]['manifest_sha256'] = value
            elif field.startswith('input.'):
                task['versions'][0]['input_artifacts']['job.json'] = value
            else:
                task[field] = value
            self.save(state.REGISTRATION, self.tasks)
            with self.subTest(field=field):
                self.assertTrue(self.view()['gaps'])
                with self.assertRaises(ValueError):
                    state.update_state(self.root, self.action())
        self.assertEqual(state.read_state(self.root)['revision'], 0)

    def test_changed_frozen_file_or_removed_registration_is_an_explicit_gap(self):
        state.update_state(self.root, self.action())
        job = self.root / 'experiments/cedar-2031-first/job.json'
        job.write_text(job.read_text() + ' ')
        view = self.view()
        self.assertIsNone(view['tasks'][0]['selected_run_id'])
        self.assertTrue(view['gaps'])
        self.tasks['tasks'] = self.tasks['tasks'][1:]
        self.save(state.REGISTRATION, self.tasks)
        self.assertIn('saved_task_no_longer_registered', [gap['reason'] for gap in self.view()['gaps']])

    def test_rehashed_packet_still_must_match_its_original_source_blocks(self):
        entry = self.runs['runs'][0]
        packet_path = self.root / entry['path'] / 'packet.json'
        packet = json.loads(packet_path.read_text())
        packet['blocks'][0]['text'] = 'Different but internally hashed source text'
        packet['blocks'][0]['text_hash'] = hashlib.sha256(packet['blocks'][0]['text'].encode()).hexdigest()
        packet_sha = self.save(entry['path'] + '/packet.json', packet)
        manifest_path = self.root / entry['path'] / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['packet.json'] = packet_sha
        entry['manifest_sha256'] = self.save(entry['path'] + '/manifest.json', manifest)
        self.save(direct.REGISTRATION, self.runs)
        version = self.tasks['tasks'][0]['versions'][0]
        version['manifest_sha256'] = entry['manifest_sha256']
        version['input_artifacts']['packet.json'] = packet_sha
        self.save(state.REGISTRATION, self.tasks)
        view = self.view()
        self.assertNotIn(entry['id'], view['loaded_runs'])
        self.assertIn('Extraction packet block differs from selected dataset source',
                      [gap['reason'] for gap in view['gaps']])
        with self.assertRaises(ValueError):
            state.update_state(self.root, self.action())

    def test_unassigned_runs_are_visible_but_cannot_be_selected_or_archived(self):
        self.tasks['tasks'][0]['versions'].pop()
        self.save(state.REGISTRATION, self.tasks)
        view = self.view()
        self.assertEqual([run['run_id'] for run in view['unassigned_runs']], ['cedar-2031-second'])
        self.assertFalse(view['unassigned_runs'][0]['selectable'])
        for action in ['select_version', 'archive']:
            with self.assertRaises(ValueError):
                state.update_state(self.root, self.action(action, run='cedar-2031-second'))

    def test_two_concurrent_writers_cannot_overwrite_the_same_revision(self):
        barrier = threading.Barrier(2)
        def save(run):
            barrier.wait(timeout=5)
            try:
                return state.update_state(self.root, self.action(run=run))['revision']
            except state.WorkspaceConflictError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(save, run) for run in ['cedar-2031-first', 'cedar-2031-second']]
            self.assertCountEqual([future.result(timeout=15) for future in futures], [1, 'conflict'])
        self.assertEqual(len(state.read_state(self.root)['audit_events']), 1)

    def test_failed_atomic_replace_preserves_previous_state(self):
        state.update_state(self.root, self.action())
        path = self.root / state.STATE_PATH
        before = path.read_bytes()
        with patch.object(state.os, 'replace', side_effect=OSError('Synthetic storage error')):
            with self.assertRaises(OSError):
                state.update_state(self.root, self.action(revision=1, run='cedar-2031-second'))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name, path.name + '.lock'])

    def test_separate_server_processes_share_the_revision_lock(self):
        context = multiprocessing.get_context('spawn')
        ready, result = context.Queue(), context.Queue()
        start = context.Event()
        processes = [context.Process(target=save_in_process, args=(str(self.root),
            self.action(run=run), ready, start, result))
            for run in ['cedar-2031-first', 'cedar-2031-second']]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=15))
            start.set()
            self.assertCountEqual([result.get(timeout=15) for _ in processes], [1, 'conflict'])
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            result.close()
        self.assertEqual(len(state.read_state(self.root)['audit_events']), 1)

    def test_invalid_state_and_duplicate_task_registration_are_rejected(self):
        invalid = state.read_state(self.root)
        invalid['revision'] = 1
        self.save(state.STATE_PATH, invalid)
        with self.assertRaisesRegex(ValueError, 'audit history'):
            state.read_state(self.root)
        (self.root / state.STATE_PATH).unlink()
        self.tasks['tasks'].append(deepcopy(self.tasks['tasks'][0]))
        self.save(state.REGISTRATION, self.tasks)
        with self.assertRaisesRegex(ValueError, 'Duplicate task'):
            self.view()


if __name__ == '__main__':
    unittest.main()
