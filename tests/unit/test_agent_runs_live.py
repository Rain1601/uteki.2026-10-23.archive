"""Exercise writer → reader contracts without network or model inference."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.review_workbench.data import agent_runs, agent_runs_live as view
from uteki.agents.runtime.observation import ObservationRecorder


class LiveRunFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = self.root / 'observations'
        self.outputs = self.root / 'business'
        self.scope = {'company_ids': ['cedar'], 'source_snapshot_ids': ['cedar-2031'],
                      'snapshot_id': 'cedar-snapshot', 'knowledge_cutoff': '2032-01-01', 'periods': ['2031']}
        self.recorders = []
        self.addCleanup(self.stop)
        self.rec = self.recorder('first')
        self.context = self.rec.context

    def recorder(self, name, scope=None):
        recorder = ObservationRecorder(self.store, self.outputs / name, kind='query', role='planner',
            origin='scripted_fixture', scope=scope or self.scope, title='Controlled inspection', heartbeat_seconds=3600)
        recorder.output.mkdir(parents=True)
        self.recorders.append(recorder)
        return recorder

    def stop(self):
        for recorder in self.recorders:
            recorder._stop.set()
            recorder._thread.join(timeout=1)

    def load(self, **kwargs):
        return view.load_run(self.store, self.rec.root_run_id, output_roots=(self.outputs,), **kwargs)

    def write(self, context, name, value):
        path = context.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return context.publish(path)

    def step(self, number=1):
        context = self.context.for_step(number)
        ref = self.write(context, f'turn-{number:03d}/input.json', {'request': {'question': 'Inspect Cedar'}, 'active_scope': self.scope})
        context.emit('step.started', ordinal=number, phase='planning', input_ref=ref)
        return context

    def call(self, context, *, terminal=False, call_id='request-one', publish=True):
        record = {'call_id': call_id, 'provider': 'offline', 'requested_model': 'fixture-model',
                  'stage': 'autonomous_planner_decision', 'status': 'succeeded' if terminal else 'started',
                  'usage': {'input_tokens': 30, 'output_tokens': 4,
                            'input_tokens_details': {'cached_tokens': 10},
                            'output_tokens_details': {'reasoning_tokens': 2}} if terminal else None,
                  'usage_presence': 'reported' if terminal else 'unknown',
                  'estimated_usd': '0.00012' if terminal else None, 'actual_billed_usd': None}
        path = context.output / 'model' / 'calls' / (call_id + ('-end.json' if terminal else '-start.json'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        if publish:
            ref = context.publish(path)
            context.emit('model_call.finished' if terminal else 'model_call.started',
                         call_id=call_id, role=context.role, record_ref=ref)
        return path

class LiveRunTests(LiveRunFixture):
    def test_model_end_is_visible_only_after_publication_and_at_requested_revision(self):
        context = self.step()
        self.call(context)
        start_revision = self.load()['revision']
        end = self.call(context, terminal=True, publish=False)
        before = self.load()
        self.assertEqual(before['usage']['requests'], 1)
        self.assertIsNone(before['usage']['input_tokens'])
        ref = context.publish(end)
        context.emit('model_call.finished', call_id='request-one', role='planner', record_ref=ref)
        after = self.load()
        self.assertEqual(after['usage']['input_tokens'], 30)
        self.assertEqual(after['usage']['output_tokens'], 4)
        self.assertEqual(after['usage']['requests'], 1)
        self.assertEqual(after['steps'][0]['call_ids'], ['request-one'])
        self.assertIsNone(self.load(revision=start_revision)['usage']['input_tokens'])
        self.assertEqual(after['scope']['source_snapshot_ids'], ['cedar-2031'])
        self.assertEqual(after['scope']['periods'], ['2031'])

    def test_cursor_preserves_high_watermark_and_reconnects_without_skipping(self):
        self.step()
        first = view.read_events(self.store, self.rec.root_run_id, output_roots=(self.outputs,), limit=1)
        high = first['high_watermark']
        self.step(2)
        next_page = view.read_events(self.store, self.rec.root_run_id, output_roots=(self.outputs,),
                                     after=first['next_cursor'], limit=500)
        self.assertEqual(next_page['high_watermark'], high)
        self.assertFalse(next_page['has_more'])
        self.assertEqual([e['seq'] for e in first['events'] + next_page['events']], list(range(1, high + 1)))
        fresh = view.read_events(self.store, self.rec.root_run_id, output_roots=(self.outputs,), after=next_page['next_cursor'])
        self.assertGreater(fresh['high_watermark'], high)
        self.assertEqual(fresh['events'][0]['seq'], high + 1)
        other = self.recorder('second')
        with self.assertRaises(ValueError):
            view.read_events(self.store, other.root_run_id, output_roots=(self.outputs,), after=first['next_cursor'])

    def test_stale_heartbeat_does_not_override_terminal(self):
        later = datetime.now(timezone.utc) + timedelta(minutes=1)
        self.assertEqual(self.load(now=later)['state']['execution'], 'unknown')
        self.rec.finish(self.context, result={'status': 'partial', 'stop_reason': 'step_limit'})
        ended = self.load(now=later)
        self.assertTrue(ended['root_terminal'])
        self.assertEqual(ended['state']['execution'], 'finished')
        self.assertEqual(ended['state']['delivery'], 'partial')
        self.assertEqual(ended['state']['connection'], 'complete')

    def test_child_owner_reuse_and_call_totals(self):
        step = self.step()
        child = self.rec.child(step, self.rec.output / 'child', kind='extraction', role='extractor',
                               origin='scripted_fixture', scope=self.scope)
        child.output.mkdir()
        self.call(child, terminal=True, call_id='child-call')
        result = self.write(child, 'result.json', {'status': 'candidate'})
        self.rec.finish(child, result={'status': 'candidate'})
        step.emit('artifact.published', ref=result, reused=True)
        loaded = self.load()
        self.assertEqual(loaded['usage']['requests'], 1)
        self.assertEqual(loaded['calls'][0]['run_id'], child.run_id)
        self.assertEqual(loaded['steps'][0]['child_run_ids'], [child.run_id])
        ref = next(a for a in loaded['artifacts'] if a['label'] == 'result.json')
        self.assertEqual(ref['run_id'], child.run_id)
        page = view.read_artifact(self.store, self.rec.root_run_id, ref['id'], output_roots=(self.outputs,))
        self.assertEqual(page['content']['status'], 'candidate')

    def test_child_cannot_borrow_another_company_or_missing_parent_step(self):
        context = self.step()
        self.rec.child(context, self.rec.output / 'foreign', kind='worker', role='worker',
                       origin='scripted_fixture', scope={**self.scope, 'company_ids': ['birch']})
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.load()
        other = self.recorder('other')
        other.child(other.context.for_step(22), other.output / 'missing', kind='worker', role='worker',
                    origin='scripted_fixture', scope=self.scope)
        with self.assertRaisesRegex(ValueError, 'parent step'):
            view.load_run(self.store, other.root_run_id, output_roots=(self.outputs,))

    def test_scope_published_after_preparation_updates_without_defaulting(self):
        recorder = self.recorder('prepared', scope={'company_ids': ['cedar']})
        before = view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))
        self.assertEqual(before['scope']['source_snapshot_ids'], [])
        self.write(recorder.context, 'scope.json', self.scope)
        after = view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))
        self.assertEqual(after['scope']['source_snapshot_ids'], ['cedar-2031'])
        self.assertEqual(after['initial_scope']['source_snapshot_ids'], [])

    def test_child_scope_updates_cannot_escape_parent_source_or_period(self):
        for field, foreign in [('source_snapshot_ids', ['outside-parent']), ('periods', ['2099'])]:
            with self.subTest(field=field):
                recorder = self.recorder('update-' + field)
                child = recorder.child(recorder.context, recorder.output / 'child', kind='extraction',
                    role='extractor', origin='scripted_fixture', scope=self.scope)
                child.output.mkdir()
                self.write(child, 'scope.json', {**self.scope, field: foreign})
                with self.assertRaisesRegex(ValueError, 'outside its parent scope'):
                    view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))

    def test_known_company_cannot_change_or_be_erased_by_scope_update(self):
        for owner in ('root', 'child'):
            for changed in (['birch'], []):
                with self.subTest(owner=owner, changed=changed):
                    recorder = self.recorder(owner + '-company-' + str(len(self.recorders)))
                    context = recorder.context
                    if owner == 'child':
                        context = recorder.child(context, recorder.output / 'child', kind='extraction',
                            role='extractor', origin='scripted_fixture', scope=self.scope)
                        context.output.mkdir()
                    self.write(context, 'scope.json', {**self.scope, 'company_ids': changed})
                    with self.assertRaisesRegex(ValueError, 'selected company'):
                        view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))

    def test_parent_scope_update_rechecks_existing_children_and_keeps_materialization(self):
        child = self.rec.child(self.context, self.rec.output / 'child', kind='extraction',
            role='extractor', origin='scripted_fixture', scope=self.scope)
        child.output.mkdir()
        before = self.load()['revision']
        expanded = {**self.scope, 'source_snapshot_ids': ['cedar-2031', 'cedar-2032'], 'periods': ['2031', '2032']}
        self.write(self.context, 'scope.json', expanded)
        self.assertEqual(self.load()['scope']['source_snapshot_ids'], expanded['source_snapshot_ids'])
        self.assertEqual(self.load(revision=before)['scope']['source_snapshot_ids'], ['cedar-2031'])
        second = self.rec.child(self.context, self.rec.output / 'second', kind='extraction',
            role='extractor', origin='scripted_fixture', scope={**self.scope, 'source_snapshot_ids': ['cedar-2032'], 'periods': ['2032']})
        self.assertIn(second.run_id, [r['id'] for r in self.load()['run_tree']])
        for field, changed in [('source_snapshot_ids', ['outside-parent']), ('periods', ['2099']),
                               ('source_snapshot_ids', []), ('periods', [])]:
            with self.subTest(field=field, changed=changed):
                recorder = self.recorder('narrow-' + str(len(self.recorders)))
                recorder.child(recorder.context, recorder.output / 'child', kind='extraction',
                    role='extractor', origin='scripted_fixture', scope=self.scope)
                self.write(recorder.context, 'scope.json', {**self.scope, field: changed})
                with self.assertRaisesRegex(ValueError, 'scope'):
                    view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))

    def test_period_objects_and_json_strings_share_one_explicit_comparison(self):
        period = {'start': '2031-01-01', 'end': '2031-12-31'}
        parent_scope = {**self.scope, 'company_ids': ['cedar', 'birch'], 'periods': [period]}
        recorder = self.recorder('structured-period', scope=parent_scope)
        child_scope = {**self.scope, 'periods': ['{"end":"2031-12-31", "start":"2031-01-01"}']}
        child = recorder.child(recorder.context, recorder.output / 'child', kind='extraction',
            role='extractor', origin='scripted_fixture', scope=child_scope)
        child.output.mkdir()
        self.write(child, 'scope.json', {**child_scope, 'periods': [period]})
        loaded = view.load_run(self.store, recorder.root_run_id, output_roots=(self.outputs,))
        self.assertEqual(loaded['scope']['periods'], loaded['run_tree'][1]['scope']['periods'])
        bad = self.recorder('foreign-period', scope=parent_scope)
        bad.child(bad.context, bad.output / 'child', kind='extraction', role='extractor',
            origin='scripted_fixture', scope={**child_scope, 'periods': [{'start': '2099-01-01', 'end': '2099-12-31'}]})
        with self.assertRaisesRegex(ValueError, 'outside its parent scope'):
            view.load_run(self.store, bad.root_run_id, output_roots=(self.outputs,))

    def test_artifacts_are_sanitized_and_changed_files_are_not_read(self):
        self.write(self.context, 'model-config.json', {'model': 'fixture', 'credential_origin': '/private/key-file',
                   'api_key': 'private-value', 'shared_budget': {'other_run': 5}})
        loaded = self.load()
        ref = next(r for r in loaded['artifacts'] if r['label'] == 'model-config.json')
        page = view.read_artifact(self.store, self.rec.root_run_id, ref['id'], output_roots=(self.outputs,))
        self.assertNotIn('private-value', json.dumps(page))
        self.assertNotIn('key-file', json.dumps(page))
        (self.rec.output / 'model-config.json').write_text('{}')
        with self.assertRaises(ValueError):
            view.read_artifact(self.store, self.rec.root_run_id, ref['id'], output_roots=(self.outputs,))

    def test_extractor_model_input_is_available_as_a_safe_artifact(self):
        self.write(self.context, 'model/review-0001-input.json',
                   {'packet': {'company_id': 'cedar'}, 'model_input': '{"task":"Inspect Cedar"}',
                    'model_input_sha256': 'a' * 64, 'credential_origin': '/private/key'})
        ref = next(r for r in self.load()['artifacts'] if r['label'] == 'review-0001-input.json')
        self.assertEqual(ref['availability'], 'available')
        page = view.read_artifact(self.store, self.rec.root_run_id, ref['id'], output_roots=(self.outputs,))
        self.assertEqual(page['content']['model_input'], '{"task":"Inspect Cedar"}')
        self.assertNotIn('credential_origin', page['content'])

    def test_host_output_allowlist_and_symlink_boundaries(self):
        with self.assertRaises(ValueError):
            view.load_run(self.store, self.rec.root_run_id, output_roots=(self.root / 'unrelated',))
        ref = self.write(self.context, 'result.json', {'status': 'candidate'})
        path = self.rec.output / 'result.json'
        raw = path.read_bytes()
        path.unlink()
        elsewhere = self.root / 'outside.json'
        elsewhere.write_bytes(raw)
        path.symlink_to(elsewhere)
        loaded = self.load()
        public = next(r for r in loaded['artifacts'] if r['sha256'] == ref['sha256'])
        with self.assertRaises(ValueError):
            view.read_artifact(self.store, self.rec.root_run_id, public['id'], output_roots=(self.outputs,))
        with self.assertRaises(ValueError):
            view.load_run(self.store, '../outside', output_roots=(self.outputs,))

    def test_partial_event_and_sequence_gap_are_visible_as_unavailable(self):
        events = self.rec.directory / 'events'
        (events / '000000000002.json').write_text('{')
        with self.assertRaises(ValueError):
            self.load()
        rows = view.list_runs(self.store, output_roots=(self.outputs,))
        self.assertEqual(rows[0]['state']['connection'], 'unavailable')
        (events / '000000000002.json').unlink()
        (events / '000000000003.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'gap'):
            self.load()

    def test_empty_events_still_contain_connection_and_public_no_paths(self):
        initial = view.read_events(self.store, self.rec.root_run_id, output_roots=(self.outputs,))
        response = view.read_events(self.store, self.rec.root_run_id, output_roots=(self.outputs,), after=initial['next_cursor'])
        self.assertEqual(response['events'], [])
        self.assertEqual(response['connection_state'], 'connected')
        self.assertTrue(response['heartbeat_at'])
        self.assertNotIn(str(self.root), json.dumps(response))
        self.assertNotIn('output_root', json.dumps(self.load()))

    def test_facade_scopes_list_cursor_and_missing_run(self):
        self.recorder('second')
        options = {'observation_root': self.store, 'output_roots': (self.outputs,)}
        first = agent_runs.list_page(self.root, limit=1, **options)
        second = agent_runs.list_page(self.root, cursor=first['next_cursor'], limit=1, **options)
        self.assertNotEqual(first['runs'][0]['id'], second['runs'][0]['id'])
        self.assertEqual(agent_runs.list_page(self.root, agent='risk', **options)['runs'], [])
        with self.assertRaises(ValueError):
            agent_runs.list_page(self.root, agent='risk', cursor=first['next_cursor'], **options)
        with self.assertRaises(KeyError):
            agent_runs.load_run(self.root, 'missing', **options)


class ObservationRoutesTests(LiveRunFixture):
    def test_http_routes_keep_explicit_scope_and_do_not_write_or_expose_errors(self):
        from apps.review_workbench import app
        with patch.object(app, 'import_rows', return_value=[]):
            handler = app.make_handler(app.DEFAULT_DATA, archive_path=self.root / 'archive.json',
                observation_root=self.store, observation_output_roots=(self.outputs,))
        def request(path, headers=None):
            instance = handler.__new__(handler)
            instance.path = path
            instance.headers = {'Host': '127.0.0.1:8765', **(headers or {})}
            instance.wfile = io.BytesIO()
            response = {'headers': {}}
            instance.send_response = lambda value: response.update(status=value)
            instance.send_header = lambda name, value: response['headers'].update({name: value})
            instance.end_headers = lambda: None
            instance.send_error = lambda status, *args: response.update(status=status)
            with patch.object(app, 'ROOT', self.root):
                instance.do_GET()
            response['body'] = instance.wfile.getvalue()
            return response
        self.assertEqual(request('/agent-runs')['status'], 200)
        answer = request('/api/agent-runs/' + self.rec.root_run_id)
        self.assertEqual(json.loads(answer['body'])['id'], self.rec.root_run_id)
        self.assertEqual(answer['headers']['Cache-Control'], 'no-store')
        for suffix in ('?revision=-1', '?revision=1&revision=2', '?path=/etc/passwd', '?revision='):
            self.assertEqual(request('/api/agent-runs/' + self.rec.root_run_id + suffix)['status'], 400)
        self.assertEqual(request('/api/agent-runs/not-registered')['status'], 404)
        self.assertEqual(request('/api/agent-runs', {'Origin': 'https://untrusted.example'})['status'], 403)
        response = request('/api/agent-runs/%2E%2E/artifacts/secrets')
        self.assertEqual(response['status'], 400)
        self.assertNotIn(str(self.root).encode(), response['body'])


if __name__ == '__main__':
    unittest.main()
