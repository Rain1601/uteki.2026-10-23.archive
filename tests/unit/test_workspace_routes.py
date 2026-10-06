"""HTTP boundaries for the workspace, without sockets or real UI-state writes."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.review_workbench import app
from apps.review_workbench.data import workspace_state
from apps.review_workbench.pages import data_workspace, source_preview
from apps.review_workbench.pages import data_evaluation, direct_extractions


class WorkspaceRoutesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with patch.object(app, 'import_rows', return_value=[]):
            self.handler = app.make_handler(app.DEFAULT_DATA, archive_path=Path(temporary.name) / 'state.json')
        self.payload = {'action': 'select_version', 'expected_revision': 7, 'dataset_id': 'cedar-2031',
                        'source_snapshot_id': 'cedar-source', 'task_id': 'capacity', 'run_id': 'cedar-run'}
        self.preview = {'content': b'<html><body>Frozen source copy</body></html>', 'mime_type': 'text/html',
            'dataset_id': 'cedar-2031', 'source_snapshot_id': 'cedar-source', 'source_sha256': 'a' * 64,
            'block_id': 'cedar-block', 'locator_status': 'block', 'locator_precision': 'block',
            'fragment': '#uteki-evidence', 'notice': {'zh': '原文块', 'en': 'Source block'},
            'headers': {'Content-Security-Policy': source_preview.PREVIEW_CSP,
                        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
                        'Referrer-Policy': 'no-referrer'}}

    def request(self, path, *, method='GET', payload=None, raw=None, headers=None):
        request = self.handler.__new__(self.handler)
        request.path = path
        request.wfile = io.BytesIO()
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b'')
        request.rfile = io.BytesIO(body)
        request.headers = {'Host': '127.0.0.1:8765', 'Origin': 'http://127.0.0.1:8765',
            'Sec-Fetch-Site': 'same-origin', 'Content-Type': 'application/json; charset=utf-8',
            'X-Uteki-Request': '1', 'Content-Length': str(len(body))}
        for name, value in (headers or {}).items():
            if value is None:
                request.headers.pop(name, None)
            else:
                request.headers[name] = value
        result = {'statuses': [], 'headers': {}, 'ended': 0}
        request.send_response = lambda status: result['statuses'].append(status)
        request.send_header = lambda name, value: result['headers'].__setitem__(name, value)
        request.end_headers = lambda: result.update(ended=result['ended'] + 1)
        request.send_error = lambda status, *args: result['statuses'].append(status)
        (request.do_POST if method == 'POST' else request.do_GET)()
        self.assertEqual(len(result['statuses']), 1, 'A request must produce exactly one response')
        result['status'] = result['statuses'][0]
        result['body'] = request.wfile.getvalue()
        if 'Content-Length' in result['headers']:
            self.assertEqual(int(result['headers']['Content-Length']), len(result['body']))
        return result

    def post(self, **kwargs):
        return self.request('/api/data-workspace/state', method='POST', **kwargs)

    def test_page_dispatch_preserves_explicit_and_blank_query_scope(self):
        with patch.object(data_workspace, 'render_data_workspace', return_value='<h1>Workspace</h1>') as render:
            response = self.request('/data-workspace?dataset=cedar-2031&source=cedar-source&tab=financials')
            render.assert_called_once_with(app.ROOT,
                {'dataset': ['cedar-2031'], 'source': ['cedar-source'], 'tab': ['financials']})
            self.assertEqual(response['status'], 200)
            self.assertEqual(response['headers']['Cache-Control'], 'no-store')
            self.assertEqual(response['body'], b'<h1>Workspace</h1>')
        with patch.object(data_workspace, 'render_data_workspace', side_effect=ValueError('Explicit source required')) as render:
            response = self.request('/data-workspace?dataset=cedar-2031&source=')
            self.assertEqual(render.call_args.args[1]['source'], [''])
            self.assertEqual(response['status'], 400)

    def test_source_forwards_scriptless_headers_and_exact_bytes(self):
        with patch.object(source_preview, 'load_source_preview', return_value=self.preview) as load:
            response = self.request('/data-workspace/source?dataset=cedar-2031&source=cedar-source&block=cedar-block')
            load.assert_called_once_with(app.ROOT,
                {'dataset': ['cedar-2031'], 'source': ['cedar-source'], 'block': ['cedar-block']})
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['body'], self.preview['content'])
        self.assertEqual(response['headers']['Content-Type'], 'text/html; charset=utf-8')
        for name, value in self.preview['headers'].items():
            self.assertEqual(response['headers'][name], value)
        csp = response['headers']['Content-Security-Policy']
        self.assertIn("script-src 'none'", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertTrue(csp.startswith('sandbox;'))
        self.assertNotIn('allow-scripts', csp)
        self.assertNotIn('allow-same-origin', csp)

    def test_pdf_remains_binary_and_source_meta_excludes_bytes_and_headers(self):
        preview = {**self.preview, 'content': b'%PDF-synthetic\x00\xff', 'mime_type': 'application/pdf'}
        with patch.object(source_preview, 'load_source_preview', return_value=preview):
            source = self.request('/data-workspace/source?dataset=cedar-2031&source=cedar-source')
            metadata = self.request('/data-workspace/source-meta?dataset=cedar-2031&source=cedar-source')
        self.assertEqual(source['headers']['Content-Type'], 'application/pdf')
        self.assertEqual(source['body'], preview['content'])
        self.assertEqual(metadata['status'], 200)
        payload = json.loads(metadata['body'])
        self.assertEqual(payload, {key: value for key, value in preview.items() if key not in {'content', 'headers'}})
        self.assertEqual(metadata['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(metadata['headers']['Cache-Control'], 'no-store')

    def test_source_errors_stay_scriptless_and_are_html_escaped(self):
        for error, expected in [(ValueError('<script>invalid scope</script>'), 400),
                                (OSError('<script>unavailable</script>'), 503)]:
            with self.subTest(error=type(error).__name__), patch.object(source_preview, 'load_source_preview', side_effect=error):
                response = self.request('/data-workspace/source?dataset=cedar-2031&source=missing')
            self.assertEqual(response['status'], expected)
            self.assertEqual(response['headers']['Content-Security-Policy'], source_preview.PREVIEW_CSP)
            self.assertEqual(response['headers']['X-Content-Type-Options'], 'nosniff')
            self.assertIn(b'&lt;script&gt;', response['body'])
            self.assertNotIn(b'<script>', response['body'])

    def test_metadata_errors_are_json_and_preserve_validation_status(self):
        for error, expected in [(ValueError('Cross-company source'), 400), (OSError('Read failed'), 503)]:
            with self.subTest(error=type(error).__name__), patch.object(source_preview, 'load_source_preview', side_effect=error):
                response = self.request('/data-workspace/source-meta?dataset=cedar-2031&source=birch-source')
            self.assertEqual(response['status'], expected)
            self.assertEqual(json.loads(response['body']), {'error': str(error)})
            self.assertNotIn('content', json.loads(response['body']))

    def test_write_rejects_foreign_origins_hosts_and_missing_json_headers(self):
        rejected = [{'Origin': 'https://foreign.example'}, {'Origin': 'null'},
                    {'Origin': 'http://127.0.0.1:9999'}, {'Host': 'foreign.example', 'Origin': None},
                    {'Host': 'localhost.foreign.example', 'Origin': None},
                    {'Sec-Fetch-Site': 'cross-site'}, {'X-Uteki-Request': None},
                    {'X-Uteki-Request': '0'}, {'Content-Type': 'text/plain'}, {'Content-Type': None}]
        with patch.object(workspace_state, 'update_state') as update:
            for headers in rejected:
                with self.subTest(headers=headers):
                    response = self.post(payload=self.payload, headers=headers)
                    self.assertEqual(response['status'], 403)
                    self.assertEqual(json.loads(response['body'])['error'], 'Same-origin JSON requests only')
            update.assert_not_called()

    def test_write_rejects_invalid_json_objects_and_request_lengths(self):
        rejected = [(b'{bad json}', {}), (b'[]', {}), (b'null', {}), (b'"text"', {}),
                    (b'{}', {'Content-Length': '0'}), (b'{}', {'Content-Length': '-1'}),
                    (b'{}', {'Content-Length': '100001'}), (b'{}', {'Content-Length': 'wrong'})]
        with patch.object(workspace_state, 'update_state') as update:
            for raw, headers in rejected:
                with self.subTest(raw=raw, headers=headers):
                    response = self.post(raw=raw, headers=headers)
                    self.assertEqual(response['status'], 400)
                    self.assertIn('error', json.loads(response['body']))
            update.assert_not_called()

    def test_valid_action_passes_exact_scope_and_returns_persisted_revision(self):
        persisted = {'schema_version': 'workspace-ui-state-v1', 'revision': 8,
                     'selections': {}, 'archived_versions': {}, 'audit_events': []}
        with patch.object(workspace_state, 'update_state', return_value=persisted) as update:
            response = self.post(payload=self.payload)
            update.assert_called_once_with(app.ROOT, self.payload)
        self.assertEqual(response['status'], 200)
        self.assertEqual(json.loads(response['body']), persisted)
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        # An explicit null selection must reach validation as null, not a default run.
        with patch.object(workspace_state, 'update_state', return_value=persisted) as update:
            self.post(payload={**self.payload, 'run_id': None})
            self.assertIsNone(update.call_args.args[1]['run_id'])

    def test_state_validation_conflict_and_storage_failure_have_distinct_statuses(self):
        cases = [(workspace_state.WorkspaceStateError('Run outside material'), 400, 'Run outside material'),
                 (workspace_state.WorkspaceConflictError('Revision changed'), 409, 'Revision changed'),
                 (OSError('/private/storage/path must not leak'), 503, 'Workspace display state could not be saved')]
        for error, status, message in cases:
            with self.subTest(error=type(error).__name__), patch.object(workspace_state, 'update_state', side_effect=error):
                response = self.post(payload=self.payload)
            self.assertEqual(response['status'], status)
            self.assertEqual(json.loads(response['body']), {'error': message})

    def test_legacy_evaluation_and_extraction_pages_still_dispatch_with_scope(self):
        for module, function, route, expected in [
                (data_evaluation, 'render_evaluation', '/evaluation?dataset=cedar-2031&source=cedar-source',
                 {'dataset': ['cedar-2031'], 'source': ['cedar-source']}),
                (direct_extractions, 'render_direct_extractions', '/extractions?run=cedar-run',
                 {'run': ['cedar-run']})]:
            with self.subTest(route=route), patch.object(module, function, return_value='<p>Historical view</p>') as render:
                response = self.request(route)
                render.assert_called_once_with(app.ROOT, expected)
                self.assertEqual(response['status'], 200)
                self.assertEqual(response['body'], b'<p>Historical view</p>')


if __name__ == '__main__':
    unittest.main()
