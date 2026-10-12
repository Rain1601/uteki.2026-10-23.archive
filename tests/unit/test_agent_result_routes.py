"""Actual local trace → result → separately bound score HTTP integration."""
import io
import json
from unittest.mock import patch

from apps.review_workbench import app
from apps.review_workbench.data import agent_runs
from tests.unit.test_agent_runs_live import LiveRunFixture


class ResultRoutesTests(LiveRunFixture):
    def setUp(self):
        super().setUp()
        self.score_path = self.root / 'reviews.json'
        with patch.object(app, 'import_rows', return_value=[]):
            self.handler = app.make_handler(app.DEFAULT_DATA, archive_path=self.root / 'archive.json',
                observation_root=self.store, observation_output_roots=(self.outputs,), score_path=self.score_path)
        self.trace = self.rec.root_run_id

    def request(self, path, *, method='GET', payload=None, raw=None, headers=None):
        instance = self.handler.__new__(self.handler)
        instance.path = path
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else b''
        instance.headers = {'Host': '127.0.0.1:8765', 'Origin': 'http://127.0.0.1:8765',
            'X-Uteki-Request': '1', 'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        for key, value in (headers or {}).items():
            if value is None:
                instance.headers.pop(key, None)
            else:
                instance.headers[key] = value
        instance.wfile, instance.rfile = io.BytesIO(), io.BytesIO(body)
        result = {'headers': {}}
        instance.send_response = lambda status: result.update(status=status)
        instance.send_header = lambda name, value: result['headers'].update({name: value})
        instance.end_headers = lambda: None
        instance.send_error = lambda status, *args: result.update(status=status)
        with patch.object(app, 'ROOT', self.root):
            (instance.do_POST if method == 'POST' else instance.do_GET)()
        result['body'] = instance.wfile.getvalue()
        if result['headers'].get('Content-Type', '').startswith('application/json'):
            result['json'] = json.loads(result['body'])
        return result

    def path(self, suffix=''):
        return '/api/agent-results/' + self.trace + suffix

    def payload(self):
        result = self.request(self.path())['json']
        return {'binding': result['binding'], 'rubric_version': 'agent-result-v1', 'reviewer': 'Independent reviewer',
                'scores': {'accuracy': None, 'coverage': 0, 'analysis': None, 'evidence': 2}, 'notes': 'Scope checked.'}

    def test_results_process_and_separate_review_round_trip(self):
        self.step()
        listing = self.request('/api/agent-results?agent=data')
        self.assertEqual(listing['status'], 200)
        self.assertEqual([r['id'] for r in listing['json']['results']], [self.trace])
        self.assertEqual(listing['headers']['Cache-Control'], 'no-store')
        detail = self.request(self.path())['json']
        process = self.request('/api/agent-runs/' + self.trace)['json']
        self.assertEqual(detail['trace_id'], process['root_run_id'])
        self.assertEqual(detail['revision'], process['revision'])
        self.assertFalse(self.score_path.exists())
        before = {str(p): p.read_bytes() for p in self.outputs.rglob('*') if p.is_file()}
        payload = self.payload()
        saved = self.request(self.path('/scores'), method='POST', payload=payload)
        self.assertEqual(saved['status'], 201)
        records = self.request(self.path('/scores'))['json']
        self.assertEqual(records['current'], [saved['json']])
        self.assertEqual(records['current'][0]['scores']['coverage'], 0)
        self.assertIsNone(records['current'][0]['scores']['accuracy'])
        self.assertEqual(records['stale'], [])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.outputs.rglob('*') if p.is_file()})

    def test_new_result_revision_rejects_old_submission_and_partitions_history(self):
        payload = self.payload()
        self.assertEqual(self.request(self.path('/scores'), method='POST', payload=payload)['status'], 201)
        saved = self.score_path.read_bytes()
        self.step()
        stale = self.request(self.path('/scores'), method='POST', payload=payload)
        self.assertEqual(stale['status'], 409)
        self.assertEqual(self.score_path.read_bytes(), saved)
        records = self.request(self.path('/scores'))['json']
        self.assertEqual(len(records['stale']), 1)
        self.assertEqual(records['current'], [])

    def test_foreign_trace_binding_and_cross_origin_never_write(self):
        payload = self.payload()
        other = self.recorder('other')
        foreign = '/api/agent-results/' + other.root_run_id + '/scores'
        self.assertEqual(self.request(foreign, method='POST', payload=payload)['status'], 409)
        for headers in ({'Host': 'foreign.example'}, {'Origin': 'https://foreign.example'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'X-Uteki-Request': None}, {'Content-Type': 'text/plain'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.path('/scores'), method='POST', payload=payload, headers=headers)['status'], 403)
        self.assertFalse(self.score_path.exists())

    def test_invalid_paths_inputs_and_storage_remain_explicit_errors(self):
        for path in ('/api/agent-results?agent=', '/api/agent-results?agent=data&agent=risk',
                     '/api/agent-results?path=/etc/passwd', '/api/agent-results/compare?left=a',
                     '/agent-results?run=x&compare=x'):
            self.assertEqual(self.request(path)['status'], 400)
        self.assertEqual(self.request('/api/agent-results/missing')['status'], 404)
        payload = self.payload()
        for raw in (b'null', b'[]', b'{', b'{}'):
            self.assertEqual(self.request(self.path('/scores'), method='POST', raw=raw)['status'], 400)
        self.assertEqual(self.request(self.path('/scores?replace=1'), method='POST', payload=payload)['status'], 400)
        self.assertEqual(self.request(self.path('/scores'), method='POST', payload=payload,
                                     headers={'Content-Length': '20001'})['status'], 400)
        self.score_path.write_text('{broken')
        error = self.request(self.path('/scores'))
        self.assertEqual(error['status'], 503)
        self.assertNotIn(str(self.root).encode(), error['body'])
        self.assertEqual(self.request(self.path('/scores'), method='POST', payload=payload)['status'], 503)
        self.assertEqual(self.score_path.read_text(), '{broken')

    def test_two_main_entries_and_explicit_data_details(self):
        for path in ('/', '/companies', '/data-workspace'):
            response = self.request(path)
            self.assertEqual(response['status'], 303)
            self.assertEqual(response['headers']['Location'], '/agent-results')
        page = self.request('/agent-results?run=' + self.trace)
        self.assertEqual(page['status'], 200)
        self.assertIn(b'data-global-page="results"', page['body'])
        self.assertIn(b'data-global-page="process"', page['body'])
        self.assertNotIn(b'data-global-page="companies"', page['body'])

    def test_historical_hash_revision_reaches_the_scoped_reader(self):
        revision = 'b' * 64
        with patch.object(agent_runs, 'read_artifact', return_value={'id': 'output'}) as reader:
            response = self.request('/api/agent-runs/frozen/artifacts/output?revision=' + revision)
            self.assertEqual(response['status'], 200)
            self.assertEqual(reader.call_args.kwargs['revision'], revision)
        with patch.object(agent_runs, 'read_artifact') as reader:
            self.assertEqual(self.request('/api/agent-runs/frozen/artifacts/output?revision=wrong-hash')['status'], 400)
            reader.assert_not_called()

    def test_missing_registered_history_preserves_routes_and_cannot_be_scored(self):
        from tests.unit.test_agent_runs_e6 import SealedFixture
        entry = SealedFixture(self.root).add('missing-history')
        (self.root / entry['path'] / 'manifest.json').unlink()
        for path in ('/agent-results', '/agent-runs', '/api/agent-results', '/api/agent-runs',
                     '/agent-results?run=missing-history', '/agent-runs?run=missing-history'):
            response = self.request(path)
            self.assertEqual(response['status'], 200, path)
        listing = self.request('/api/agent-results')['json']['results']
        self.assertEqual({r['id'] for r in listing}, {self.trace, 'missing-history'})
        detail = self.request('/api/agent-results/missing-history')['json']
        self.assertEqual(detail['integrity']['reason'], 'missing_files')
        payload = {**self.payload(), 'binding': detail['binding']}
        response = self.request('/api/agent-results/missing-history/scores', method='POST', payload=payload)
        self.assertEqual(response['status'], 400)
        self.assertFalse(self.score_path.exists())
