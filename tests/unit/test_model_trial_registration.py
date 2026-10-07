"""The administrative importer checks real adapter boundaries without model calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from apps.review_workbench.data import agent_runs, agent_run_results
from tests.unit.test_agent_run_results import ExperimentFixture, digest, encode

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'experiments/model_comparison/2026-10-07-reproducibility-pilot-v1/register_trial.py'
spec = importlib.util.spec_from_file_location('register_bounded_trial', PATH)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ModelTrialRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture = ExperimentFixture(self.root)
        row = fixture.add('original', company='birch', year=2030)
        self.files = {}
        for key, pin in row['files'].items():
            if key == 'packet':
                dest = 'experiments/pilot/prepared/packet.json'
            elif key == 'prepared_manifest':
                dest = 'experiments/pilot/prepared/manifest.json'
            elif key in {'request', 'experiment_start'}:
                dest = 'experiments/pilot/output/' + {'request': 'request.json', 'experiment_start': 'experiment-start.json'}[key]
            elif key in {'source_catalog', 'source_bytes'}:
                dest = 'experiments/pilot/source/' + {'source_catalog': 'sources.json', 'source_bytes': 'source.html'}[key]
            else:
                dest = 'experiments/pilot/output/01-model/' + {'start': 'start.json', 'response': 'response-metadata.json',
                    'validation': 'validation.json', 'visible_output': 'visible-output.txt', 'parsed': 'parsed.json'}[key]
            path = self.root / dest
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / pin['path']).read_bytes())
            self.files[key] = path
        self.options = dict(identity='new-trial', title='Birch 2030 bounded experiment', provider='aihubmix', model='sonnet',
            prepared='experiments/pilot/prepared', output='experiments/pilot/output', arm='01-model',
            source_catalog='experiments/pilot/source/sources.json', source_bytes='experiments/pilot/source/source.html')

    def change(self, key, update):
        value = json.loads(self.files[key].read_text())
        update(value)
        self.files[key].write_bytes(encode(value))

    def test_explicit_import_dry_run_and_duplicate_rejection(self):
        registry = self.root / 'data/evaluation_views/model-trials-v1.json'
        original = registry.read_bytes()
        evidence = {key: path.read_bytes() for key, path in self.files.items()}
        entry = importer.register_trial(self.root, dry_run=True, **self.options)
        self.assertEqual(entry['scope']['company_id'], 'birch')
        self.assertEqual(registry.read_bytes(), original)
        importer.register_trial(self.root, **self.options)
        run = agent_runs.load_run(self.root, 'new-trial')
        self.assertEqual(run['scope']['periods'], ['2030-06-30'])
        with self.assertRaisesRegex(ValueError, 'already registered'):
            importer.register_trial(self.root, **self.options)
        self.assertEqual(evidence, {key: path.read_bytes() for key, path in self.files.items()})

    def test_invalid_output_keeps_visible_evidence_without_typed_facts(self):
        self.change('validation', lambda value: value.update(status='invalid', errors=['semantic_scope_check']))
        entry = importer.register_trial(self.root, **self.options)
        self.assertNotIn('parsed', entry['files'])
        result = agent_run_results.load_result(self.root, 'new-trial')
        self.assertEqual(result['result_view']['kind'], 'invalid_output')
        self.assertEqual(result['result_view']['facts'], [])
        self.assertIn('visible-output.txt', [r['label'] for r in result['artifacts']])

    def test_failed_request_preserves_http_status_and_no_success_claim(self):
        self.change('response', lambda value: value.update(status='failed', http_status=503, finish_reason=None,
            provider_finish_reason=None, raw_usage=None, usage_presence='unknown', estimated_usd=None))
        self.change('validation', lambda value: value.update(status='invalid', errors=['request_failed']))
        self.files['visible_output'].write_bytes(b'')
        importer.register_trial(self.root, **self.options)
        result = agent_run_results.load_result(self.root, 'new-trial')
        self.assertEqual(result['state']['execution'], 'failed')
        self.assertEqual(result['calls'][0]['http_status'], 503)
        self.assertIsNone(result['calls'][0]['provider_finish_reason'])
        self.assertEqual(result['usage']['unknown_usage_calls'], 1)
        self.assertEqual(result['result_view']['facts'], [])

    def test_provider_end_turn_and_normalized_stop_are_distinct(self):
        self.change('response', lambda value: value.update(http_status=200, provider_finish_reason='end_turn'))
        importer.register_trial(self.root, **self.options)
        result = agent_run_results.load_result(self.root, 'new-trial')
        self.assertEqual(result['calls'][0]['provider_finish_reason'], 'end_turn')
        self.assertEqual(result['calls'][0]['finish_reason'], 'stop')
        ref = next(r for r in result['artifacts'] if r['label'] == 'response-metadata.json')
        page = agent_runs.read_artifact(self.root, 'new-trial', ref['id'])
        self.assertEqual(page['content']['http_status'], 200)

    def test_wrong_model_company_source_or_request_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Registered model'):
            importer.register_trial(self.root, **{**self.options, 'model': 'other-model'})
        self.change('source_catalog', lambda value: value[0].update(company_id='cedar'))
        with self.assertRaisesRegex(ValueError, 'company'):
            importer.register_trial(self.root, **self.options)
        self.change('source_catalog', lambda value: value[0].update(company_id='birch'))
        self.change('request', lambda value: value['messages'][1].update(content='{}'))
        with self.assertRaisesRegex(ValueError, 'pinned packet'):
            importer.register_trial(self.root, **self.options)

    def test_path_escape_and_source_symlink_are_rejected(self):
        with self.assertRaises(ValueError):
            importer.register_trial(self.root, **{**self.options, 'source_bytes': '../foreign.html'})
        path = self.files['source_bytes']
        other = self.root / 'other-source.html'
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            importer.register_trial(self.root, **self.options)

    def test_wrong_prepared_manifest_hash_is_rejected(self):
        self.change('prepared_manifest', lambda value: value.update(packet_sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'Prepared manifest'):
            importer.register_trial(self.root, **self.options)


if __name__ == '__main__':
    unittest.main()
