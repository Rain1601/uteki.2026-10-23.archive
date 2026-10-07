import io
import json
from pathlib import Path
import tempfile
import unittest

from apps.review_workbench.app import make_handler, DEFAULT_DATA, ROOT
from apps.review_workbench.research_archive_import import import_rows


class ArchiveRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.handler = make_handler(DEFAULT_DATA, Path(self.temp.name) / 'state.json')

    def request(self, path, data=None, headers=None):
        request = object.__new__(self.handler)
        request.path = path
        request.wfile = io.BytesIO()
        payload = json.dumps(data).encode() if data else b''
        request.rfile = io.BytesIO(payload)
        request.headers = {'Host': '127.0.0.1:8765', 'Origin': 'http://127.0.0.1:8765',
            'Content-Type': 'application/json', 'X-Uteki-Request': '1', 'Content-Length': str(len(payload))}
        request.headers.update(headers or {})
        result = {}
        request.send_response = lambda status: result.update(status=status)
        request.send_header = lambda *args: None
        request.end_headers = lambda: None
        request.send_error = lambda status, *args: result.update(status=status)
        (request.do_POST if data else request.do_GET)()
        return result['status'], request.wfile.getvalue()

    def test_imported_runs_are_real_unaccepted_and_precisely_linked(self):
        rows = import_rows(ROOT)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['status'] == 'candidate' for r in rows))
        self.assertEqual(sum(r['validation_status'] == 'passed' for r in rows), 1)
        citation = rows[-1]['answer']['claims'][0]['citations'][0]
        self.assertIn('/source#block-', citation['url'])

    def test_company_tabs_and_legacy_routes(self):
        for path, expected in [('/companies/alphabet', 'report-reading'),
                ('/companies/alphabet/data', '财务指标'), ('/companies', 'Alphabet'), ('/companies/alphabet/data/business-map', 'Data Agent')]:
            status, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(expected, body.decode())

    def test_company_first_hierarchy_and_boundaries(self):
        expected = [('/companies/alphabet', 'report-reading'),
            ('/companies/alphabet/materials', '可检索材料与文档目录'),
            ('/companies/alphabet/data', '财务指标'),
            ('/companies/alphabet/data/business-map', '业务图'),
            ('/companies/alphabet/reports', 'report-reading')]
        for path, label in expected:
            status, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(label, body.decode())
        rows = json.loads(self.request('/api/research-archive')[1])['snapshots']
        status, body = self.request('/companies/alphabet/reports/' + rows[0]['id'])
        self.assertEqual(status, 200)
        self.assertIn('revision-history', body.decode())
        from apps.review_workbench.app import load_json, COMPANY_UNIVERSE_DATA
        other = next(c['id'] for c in load_json(COMPANY_UNIVERSE_DATA)['companies'] if c['id'] != 'alphabet')
        self.assertIn('尚未生成', self.request('/companies/' + other + '/data')[1].decode())
        for path in ['/companies/' + other + '/data/business-map',
                '/companies/' + other + '/reports/' + rows[0]['id'],
                '/companies/alphabet/materials/pdf/../../state.json',
                '/companies/alphabet/reports/missing']:
            self.assertEqual(self.request(path)[0], 404, path)
        manifest = load_json(ROOT / 'data/reading_library/alphabet/download_manifest.json')
        doc = next(d for d in manifest['documents'] if d['status'] == 'downloaded')
        status, body = self.request('/companies/alphabet/materials/pdf/' + Path(doc['path']).stem)
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b'%PDF'))
        from apps.review_workbench.document_library import index_url
        from uteki.agents.material_library import load_catalog
        doc = next(d for d in load_catalog(ROOT)['documents'] if d.get('index_folder'))
        status, body = self.request(index_url(doc))
        self.assertEqual(status, 200)
        self.assertIn('/companies/alphabet/materials', body.decode())

    def test_redundant_pages_redirect_to_company_children(self):
        for path in ['/result', '/benchmark', '/data?company=alphabet', '/companies/alphabet?tab=data']:
            self.assertEqual(self.request(path)[0], 303, path)

    def test_same_origin_and_revision_controls(self):
        rows = json.loads(self.request('/api/research-archive')[1])['snapshots']
        row = rows[0]
        action = {'snapshot_id': row['id'], 'action': 'archive', 'expected_revision': 1}
        self.assertEqual(self.request('/api/research-archive', action, {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/research-archive', action, {'X-Uteki-Request': ''})[0], 403)
        self.assertEqual(self.request('/api/research-archive', action)[0], 200)
        self.assertEqual(self.request('/api/research-archive', action)[0], 409)

    def test_browser_cannot_impersonate_agent_revision(self):
        row = json.loads(self.request('/api/research-archive')[1])['snapshots'][0]
        payload = dict(snapshot_id=row['id'], action='agent_edit', expected_revision=row['revision'],
                       answer=row['answer'], actor='agent', agent_provenance={'model':'fake'})
        self.assertEqual(self.request('/api/research-archive',payload)[0],400)
        payload.update(action='edit', human_notes='Human change')
        status, body = self.request('/api/research-archive',payload)
        self.assertEqual(status,200)
        revision = json.loads(body)['snapshot']
        self.assertEqual(revision['editor_type'],'human')
        self.assertEqual(revision['author'],'user')
        self.assertNotIn('agent_provenance',revision)

    def test_default_context_empty_and_bad_cutoff_rejected(self):
        status, body = self.request('/api/research-archive/context?cutoff=2026-09-13&researcher=single-default')
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)['baseline_snapshot_id'])
        self.assertEqual(self.request('/api/research-archive/context')[0], 400)
        self.assertEqual(self.request('/api/research-archive/context?cutoff=2026-09-13')[0], 400)

    def test_material_aware_context_policy_and_time_boundary(self):
        base='/api/research-archive/context?researcher=single-default&cutoff=2026-09-15&material='
        for identity,policy in [('alphabet-000165204426000018','prior_two_fiscal_years_10k'),
                                ('alphabet-2025q4-call','latest_prior_10k')]:
            status,body=self.request(base+identity)
            self.assertEqual(status,200,body[:200])
            ctx=json.loads(body)
            self.assertEqual(ctx['context_policy'],policy)
            self.assertEqual(ctx['schema_version'],'1.2')
            self.assertEqual(ctx['baselines'],[])
        self.assertEqual(self.request(base+'unknown')[0],400)
        self.assertEqual(self.request(base.replace('2026-09-15','2025-01-01')+'alphabet-2025q4-call')[0],400)

    def test_effective_revision_review_and_atomic_replace_over_http(self):
        rows=json.loads(self.request('/api/research-archive?researcher=team-a')[1])['snapshots']
        parent=next(r for r in rows if r['validation_status']=='passed')
        def post(row, action, **data):
            status, body=self.request('/api/research-archive',dict(snapshot_id=row['id'],action=action,expected_revision=row['revision'],**data))
            self.assertEqual(status,200,body[:400])
            return json.loads(body)['snapshot']
        parent=post(parent,'adopt',confirm_primary=True,expected_slot_revision=parent['slot_revision'])
        child=post(parent,'edit',human_notes='Isolated test revision, no research recommendation')
        self.assertEqual(child['status'],'candidate')
        child=post(child,'review',review_notes='Test verifies lifecycle only')
        all_rows=json.loads(self.request('/api/research-archive?researcher=team-a')[1])['snapshots']
        parent=next(r for r in all_rows if r['id']==parent['id'])
        child=next(r for r in all_rows if r['id']==child['id'])
        adopted=post(child,'adopt',confirm_primary=True,expected_slot_revision=child['slot_revision'],replace_snapshot_id=parent['id'],replace_revision=parent['revision'])
        self.assertEqual(adopted['status'],'adopted')
        context=json.loads(self.request('/api/research-archive/context?researcher=team-a&cutoff=2099-01-01')[1])
        self.assertEqual(context['baseline_snapshot_id'],child['id'])
        self.assertEqual(json.loads(self.request('/api/research-archive/context?researcher=single-default&cutoff=2099-01-01')[1])['baseline_snapshot_id'],None)
