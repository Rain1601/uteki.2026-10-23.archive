"""Historical evidence tests; no network, provider or browser execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.review_workbench.data import agent_runs_history as history
from apps.review_workbench.data.agent_runs_shared import artifact_page, project_artifact, summarize_calls
from scripts.import_agent_run import import_run
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[2]


class HistoricalRunsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        history._CACHE.clear()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False) + '\n')
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def seal(self, path, **metadata):
        folder = self.root / path
        hashes = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(folder.rglob('*')) if p.is_file() and p != folder / 'manifest.json'}
        return self.write(path + '/manifest.json', {**metadata, 'files': hashes})

    def fixture(self, identity='cedar', company='cedar-inc', year=2024, *, duplicate=False, conflict=False, end=True, secret=False):
        run = 'experiments/' + identity
        dataset = 'data/' + identity
        source_id = identity + '-annual'
        scope = {'execution_schema_version': 'research-execution-v1', 'snapshot_id': identity + '-snapshot',
                 'company_ids': [company], 'source_snapshot_ids': [source_id], 'source_policy_id': 'local-frozen-v1',
                 'knowledge_cutoff': f'{year + 1}-03-01', 'include_candidates': True}
        raw_hash = self.write(dataset + '/source.json', {'text': f'{company} fiscal year {year}'})
        self.write(dataset + '/sources.json', [{'source_snapshot_id': source_id, 'company_id': company,
                   'source_sha256': raw_hash, 'raw_file': 'source.json', 'period_end': f'{year}-12-31'}])
        dataset_hash = self.seal(dataset, snapshot_id=scope['snapshot_id'], company={'company_id': company})
        request = {'question': f'Read {company} {year}', 'scope': scope}
        trace = []
        for step, action, status in [(1, 'invalid', 'rejected'), (2, 'finish', 'limited')]:
            prefix = f'{run}/query/turn-{step:03d}'
            self.write(prefix + '/input.json', {'request': request, 'active_scope': scope})
            self.write(prefix + '/receipt.json', {'step': step, 'action': action, 'status': status, 'layer': 'validation' if step == 1 else 'runtime', 'error_code': 'bad_decision' if step == 1 else None})
            self.write(prefix + '/feedback.json', {'status': status, 'error': '<script>untrusted</script>'})
            if step == 2:
                self.write(prefix + '/decision.json', {'action': action})
            trace.append({'step': step, 'action': action, 'status': status, 'receipt': f'turn-{step:03d}/receipt.json', 'feedback': f'turn-{step:03d}/feedback.json'})
        self.write(run + '/query/request.json', request)
        self.write(run + '/query/result.json', {'schema_version': 'autonomous-result-v2', 'request': request, 'active_scope': scope,
                   'plan_origin': 'scripted_fixture', 'status': 'limited', 'stop_reason': 'no_progress_limit', 'trace': trace,
                   'semantic_completeness': 'not_evaluated', 'worker_runs': [], 'financial_extractions': []})
        payload = {'text': '汉' * 70000, 'api_key': 'secret-not-visible'}
        artifact_hash = self.write(run + '/query/artifacts/shared.json', payload)
        self.write(run + '/query/artifact-index.json', [{'schema_version': 'run-artifact-v1', 'artifact_id': 'shared-artifact',
                   'path': 'artifacts/shared.json', 'kind': 'tool_output', 'sha256': artifact_hash,
                   'size_bytes': (self.root / run / 'query/artifacts/shared.json').stat().st_size,
                   'scope': scope, 'scope_id': 'scope-' + digest(scope)[:24], 'source_ids': [source_id], 'created_step': 1}])
        self.write(run + '/model/model-config.json', {'model': 'local-model', 'provider': 'fixture', 'reasoning_effort': 'low',
                   'api_key': 'secret-not-visible', 'credential_origin': '/Users/private/key', 'budget_ledger': '/tmp/private.json',
                   'prompt': 'A plain prompt', 'arbitrary_private_field': 'never-project-me'})
        start = {'call_id': 'shared-call', 'stage': 'autonomous_planner_decision', 'provider': 'fixture', 'requested_model': 'local-model',
                 'started_at': '2025-01-01T00:00:00Z', 'status': 'started', 'usage': None, 'estimated_usd': None}
        refs = []
        for kind, record in [('start', start), ('end', {**start, 'status': 'succeeded', 'ended_at': '2025-01-01T00:00:01Z',
                'usage': {'input_tokens': 10, 'output_tokens': 5, 'input_tokens_details': {'cached_tokens': 2}, 'output_tokens_details': {'reasoning_tokens': 3}},
                'raw_usage': {'prompt_tokens': 10, 'completion_tokens': 5}, 'estimated_usd': '0.001', 'actual_billed_usd': None})]:
            if kind == 'end' and not end:
                continue
            relative = 'calls/shared-call-' + kind + '.json'
            sha = self.write(run + '/model/' + relative, record)
            refs.append({'path': relative, 'sha256': sha})
            if kind == 'end' and duplicate:
                self.write(run + '/model/calls/duplicate-end.json', {**record, **({'estimated_usd': '100'} if conflict else {})})
        self.write(run + '/model/decision-0001-attempt-01.json', {'decision': 1, 'attempt': 1, 'calls': refs, 'status': 'invalid_model_decision'})
        query_hash = self.seal(run + '/query')
        self.write(run + '/result.json', {'schema_version': 'company-agent-result-v1', 'operation': 'query', 'status': 'limited',
                   'active_scope': scope, 'query_run': 'query', 'dataset': {'path': '/Users/old/checkout/' + dataset, 'manifest_sha256': dataset_hash}})
        run_hash = self.seal(run, schema_version='company-agent-run-v1')
        return {'id': identity, 'title': f'{company} {year}', 'adapter': history.ADAPTER, 'path': run, 'manifest_sha256': run_hash,
                'query': {'path': 'query', 'manifest_sha256': query_hash}, 'dataset': {'id': identity + '-data', 'path': dataset, 'manifest_sha256': dataset_hash},
                'scope': scope, 'sources': {source_id: raw_hash}, 'children': []}

    def test_explicit_import_is_read_only_and_rejects_replacing_identity(self):
        spec = self.fixture()
        before = (self.root / spec['path'] / 'manifest.json').read_bytes()
        imported = import_run(self.root, spec)
        self.assertEqual(imported['scope']['company_id'], 'cedar-inc')
        self.assertEqual(imported['scope']['periods'], ['2024-12-31'])
        self.assertEqual(before, (self.root / spec['path'] / 'manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'already registered'):
            import_run(self.root, spec)

    def test_list_is_lightweight_and_marks_stale_registration(self):
        spec = self.fixture()
        import_run(self.root, spec)
        with patch.object(history, '_manifest', side_effect=AssertionError('No bulk reads')):
            rows = history.list_runs(self.root)
        self.assertEqual(rows[0]['usage']['requests'], 1)
        self.assertNotIn('artifacts', rows[0])
        registry = history._registry(self.root)
        registry['runs'][0]['scope']['knowledge_cutoff'] = '2026-01-01'
        self.write(history.REGISTRATION, registry)
        self.assertEqual(history.list_runs(self.root)[0]['integrity']['status'], 'index_missing')

    def test_no_default_and_independent_company_period_scope(self):
        self.assertEqual(history.list_runs(self.root), [])
        import_run(self.root, self.fixture())
        import_run(self.root, self.fixture('birch', 'birch-inc', 2022))
        for identity in ('', 'missing', '../cedar'):
            with self.assertRaises(ValueError):
                history.load_run(self.root, identity)
        cedar, birch = history.load_run(self.root, 'cedar'), history.load_run(self.root, 'birch')
        self.assertEqual(cedar['scope']['source_snapshot_ids'], ['cedar-annual'])
        self.assertEqual(birch['scope']['periods'], ['2022-12-31'])
        with self.assertRaises(ValueError):
            history.load_step(self.root, 'birch', cedar['steps'][0]['id'])

    def test_invalid_decision_is_retained_and_duplicate_calls_do_not_add_cost(self):
        import_run(self.root, self.fixture(duplicate=True))
        view = history.load_run(self.root, 'cedar')
        self.assertEqual(view['usage']['requests'], 1)
        self.assertEqual(view['usage']['known_estimated_usd'], '0.001')
        step = history.load_step(self.root, 'cedar', view['steps'][0]['id'])
        self.assertEqual(step['status'], 'rejected')
        self.assertTrue(any(r['kind'] == 'decision' and r['availability'] == 'missing' for r in step['files']))
        self.assertEqual(step['call_ids'], ['shared-call'])

    def test_conflicting_call_evidence_fails_import(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting duplicate call'):
            import_run(self.root, self.fixture(duplicate=True, conflict=True))
        self.assertEqual(history.registered_ids(self.root), [])

    def test_start_only_call_preserves_unknown_usage_and_cost(self):
        import_run(self.root, self.fixture(end=False))
        view = history.load_run(self.root, 'cedar')
        self.assertEqual(view['usage']['unknown_usage_calls'], 1)
        self.assertEqual(view['usage']['unknown_cost_requests'], 1)
        self.assertIsNone(view['calls'][0]['input_tokens'])
        self.assertIsNone(view['calls'][0]['estimated_usd'])

    def test_recorded_zero_without_provider_usage_stays_unconfirmed(self):
        spec = self.fixture()
        call_path = spec['path'] + '/model/calls/shared-call-end.json'
        call = json.loads((self.root / call_path).read_text())
        call['usage'] = {'input_tokens': 0, 'output_tokens': 0}
        call['raw_usage'] = {}
        sha = self.write(call_path, call)
        attempt_path = spec['path'] + '/model/decision-0001-attempt-01.json'
        attempt = json.loads((self.root / attempt_path).read_text())
        next(ref for ref in attempt['calls'] if ref['path'].endswith('-end.json'))['sha256'] = sha
        self.write(attempt_path, attempt)
        spec['manifest_sha256'] = self.seal(spec['path'], schema_version='company-agent-run-v1')
        import_run(self.root, spec)
        view = history.load_run(self.root, 'cedar')
        self.assertEqual(view['calls'][0]['input_tokens'], 0)
        self.assertEqual(view['calls'][0]['usage_presence'], 'unknown')
        self.assertEqual(view['usage']['unknown_usage_calls'], 1)
        self.assertIsNone(view['usage']['input_tokens'])

    def test_scope_source_and_unsupported_adapter_fail_closed(self):
        original = self.fixture()
        for key in ('missing_scope', 'company', 'source', 'adapter'):
            spec = deepcopy(original)
            if key == 'missing_scope':
                spec['scope']['company_ids'] = []
            elif key == 'company':
                spec['scope']['company_ids'] = ['other-company']
            elif key == 'source':
                spec['sources']['cedar-annual'] = '0' * 64
            else:
                spec['adapter'] = 'guess-by-directory'
            with self.assertRaises(ValueError, msg=key):
                import_run(self.root, spec)

    def test_relocated_historical_path_is_not_opened_and_wrong_binding_fails(self):
        spec = self.fixture()
        import_run(self.root, spec)
        self.assertEqual(history.load_run(self.root, 'cedar')['id'], 'cedar')
        other = self.fixture('wrong')
        result_path = other['path'] + '/result.json'
        result = json.loads((self.root / result_path).read_text())
        result['dataset']['path'] = '/Users/old/checkout/data/not-this-company'
        self.write(result_path, result)
        other['manifest_sha256'] = self.seal(other['path'], schema_version='company-agent-run-v1')
        with self.assertRaisesRegex(ValueError, 'Historical reference'):
            import_run(self.root, other)

    def test_tampered_file_and_symlink_rejected_on_cached_artifact_read(self):
        spec = self.fixture()
        import_run(self.root, spec)
        view = history.load_run(self.root, 'cedar')
        artifact = next(r for r in view['artifacts'] if r['id'] == 'shared-artifact')
        target = self.root / spec['path'] / 'query/artifacts/shared.json'
        target.write_text('{"text":"changed"}')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            history.read_artifact(self.root, 'cedar', artifact['id'])
        self.assertFalse(history._CACHE)
        original = self.fixture('linked')
        raw = self.root / original['path'] / 'query/artifacts/shared.json'
        external = self.root / 'outside.json'
        external.write_bytes(raw.read_bytes())
        raw.unlink(); raw.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            import_run(self.root, original)

    def test_manifest_change_invalidates_cached_index(self):
        spec = self.fixture()
        import_run(self.root, spec)
        history.load_run(self.root, 'cedar')
        manifest = self.root / spec['path'] / 'manifest.json'
        manifest.write_bytes(manifest.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            history.load_run(self.root, 'cedar')
        self.assertFalse(history._CACHE)

    def test_detail_rechecks_selected_file_without_claiming_all_files_still_valid(self):
        spec = self.fixture()
        import_run(self.root, spec)
        view = history.load_run(self.root, 'cedar')
        (self.root / spec['path'] / 'query/artifacts/shared.json').write_text('{"text":"tampered"}')
        config = view['configs'][0]
        self.assertEqual(history.read_artifact(self.root, 'cedar', config['id'])['availability'], 'available')
        self.assertEqual(history.list_runs(self.root)[0]['integrity']['status'], 'verified_at_import')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            history.read_artifact(self.root, 'cedar', 'shared-artifact')

    def test_large_artifact_child_browse_and_text_continuation_are_complete(self):
        import_run(self.root, self.fixture())
        import_run(self.root, self.fixture('birch', 'birch-inc'))
        page = history.read_artifact(self.root, 'cedar', 'shared-artifact')
        self.assertTrue(page['truncated'])
        child = next(c for c in page['children'] if c['label'] == 'text')
        with self.assertRaisesRegex(ValueError, 'cursor run'):
            history.read_artifact(self.root, 'birch', 'shared-artifact', browse=child['browse'])
        page = history.read_artifact(self.root, 'cedar', 'shared-artifact', browse=child['browse'])
        values = [page['content']]
        while page['next_cursor']:
            page = history.read_artifact(self.root, 'cedar', 'shared-artifact', cursor=page['next_cursor'])
            values.append(page['content'])
        self.assertEqual(''.join(values), '汉' * 70000)
        self.assertFalse(page['truncated'])

    def test_config_projection_excludes_private_fields_and_paths(self):
        import_run(self.root, self.fixture())
        view = history.load_run(self.root, 'cedar')
        ref = next(r for r in view['configs'] if r['label'].endswith('model-config.json'))
        page = history.read_artifact(self.root, 'cedar', ref['id'])
        text = json.dumps(page)
        self.assertNotIn('secret-not-visible', text)
        self.assertNotIn('never-project-me', text)
        self.assertNotIn('/Users/', text)
        self.assertNotIn('/tmp/', text)
        self.assertEqual(page['content']['model'], 'local-model')
        self.assertEqual(project_artifact({'company_id': 'cedar', 'source_snapshot_ids': ['s'], 'periods': ['2024']}, 'input')['periods'], ['2024'])

    def test_cursor_binds_hash_projection_and_does_not_expose_restricted_children(self):
        ref = {'id': 'x', 'run_id': 'r', 'sha256': 'a' * 64, 'label': 'x', 'kind': 'artifact', 'availability': 'available'}
        safe = project_artifact({'text': 'a' * 90000, 'metadata': {'api_key': 'secret'}, 'unauthorized': 'secret'}, 'artifact')
        page = artifact_page(ref, safe)
        child = page['children'][0]['browse']
        with self.assertRaisesRegex(ValueError, 'hash or projection'):
            artifact_page({**ref, 'sha256': 'b' * 64}, safe, browse=child)
        self.assertNotIn('secret', json.dumps(page))


class FrozenAMDIntegrationTests(unittest.TestCase):
    def test_real_main_and_no_progress_runs_and_unique_call_totals(self):
        before = {row['path']: (ROOT / row['path'] / 'manifest.json').read_bytes() for row in history._registry(ROOT)['runs']}
        main = history.load_run(ROOT, 'amd-fy2023-main-agent-v2-parent')
        self.assertEqual(len([s for s in main['steps'] if s['run_id'] == main['id']]), 6)
        self.assertEqual(len(main['steps']), 7)
        self.assertEqual([s['ordinal'] for s in main['steps'] if s['status'] == 'rejected'], [1, 3])
        self.assertEqual(len(main['run_tree']), 2)
        self.assertEqual(main['steps'][4]['child_run_ids'], ['amd-fy2023-main-agent-v2--extractor'])
        self.assertEqual((main['usage']['requests'], main['usage']['input_tokens'], main['usage']['output_tokens']), (7, 105812, 17512))
        self.assertEqual(main['usage']['known_estimated_usd'], '0.17045820')
        self.assertEqual(main['usage']['own']['requests'], 6)
        self.assertEqual(main['usage']['own']['input_tokens'], 88320)
        self.assertEqual(main['state']['quality'], 'not_evaluated')
        self.assertEqual(main['state']['adoption'], 'unchanged_candidate')
        self.assertEqual({row['role']: row['requests'] for row in main['usage']['roles']}, {'planner': 6, 'extractor': 1})
        self.assertTrue(main['links'][0]['href'].startswith('/extractions?'))
        child_id = main['steps'][4]['child_run_ids'][0]
        self.assertNotIn(child_id, history.registered_ids(ROOT))
        child_calls = [c for c in main['calls'] if c['run_id'] == child_id]
        self.assertEqual(len(child_calls), 1)
        child_step = next(s for s in main['steps'] if s['run_id'] == child_id)
        self.assertEqual(child_step['origin'], 'direct_extraction_task')
        self.assertEqual(child_calls[0]['step_id'], child_step['id'])
        self.assertEqual(history.load_step(ROOT, main['id'], child_step['id'])['run_id'], child_id)
        child_ref = next(r for r in main['artifacts'] if r['run_id'] == child_id and r['label'].endswith('/packet.json'))
        self.assertEqual(history.read_artifact(ROOT, main['id'], child_ref['id'])['run_id'], child_id)
        cash = history.load_run(ROOT, 'amd-fy2023-cash-flow-main-agent-v2-parent')
        self.assertEqual(cash['state']['stop_reason'], 'no_progress_limit')
        self.assertEqual((len([s for s in cash['steps'] if s['run_id'] == cash['id']]), cash['usage']['requests']), (7, 8))
        self.assertEqual(cash['links'], [])
        for path, frozen in before.items():
            self.assertEqual(frozen, (ROOT / path / 'manifest.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
