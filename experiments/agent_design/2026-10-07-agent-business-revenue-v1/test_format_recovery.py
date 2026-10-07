"""Offline format-recovery boundary checks; no model calls or real-run edits."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from uteki.agents.business_map.product_contract import ProductDraft

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recovery = load('recovery_under_test', 'format_recovery.py')
fixtures = load('recovery_view_fixtures', 'test_build_view.py')
builder = fixtures.builder
ROOT = fixtures.ROOT


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.raw = b'```json\n' + json.dumps(f.draft, ensure_ascii=False, indent=2).encode() + b'\n```'
        (f.run / 'response.txt').write_bytes(self.raw)
        builder.write_json(f.run / 'request.json', {'model': f.result['model'], 'stream': True})
        builder.write_json(f.run / 'output_schema.json', ProductDraft.model_json_schema())
        builder.write_json(f.run / 'configuration.json', {'stream': True})
        result = copy.deepcopy(f.result)
        result.update({k: f.packet[k] for k in ('company_id', 'document_id', 'period_end', 'source_sha256')})
        result.update(status='failed', validation='failed_or_not_reached', stop_reason='StrictJSONError',
                      request_sha256=builder.view.sha(f.run / 'request.json'),
                      output_schema_sha256=recovery.sha(json.dumps(ProductDraft.model_json_schema(), ensure_ascii=False).encode()))
        record = result['costs']['records'][0]
        record.update(status='succeeded', request_sha256=result['request_sha256'], http_status=200,
                      stream_complete=True, visible_text_secret_redacted=False, response_id='offline-response')
        builder.write_json(f.run / 'response_metadata.json', record)
        builder.write_json(f.run / 'manifest.json', result)
        builder.write_json(f.run / 'result.json', result)
        self.original = {p.name: p.read_bytes() for p in f.run.iterdir()}
        self.derived = f.folder / 'derived'

    def derive(self):
        return recovery.derive(ROOT, self.fixture.run, self.derived)

    def test_single_fence_preserves_exact_inner_bytes_and_rejects_ambiguous_inputs(self):
        inner = b'{"value": "x"}\n'
        self.assertEqual(recovery.unwrap(b'```json\n' + inner + b'```'), inner)
        cases = [b'prose\n```json\n{}\n```', b'```json\n{}\n```\nprose',
                 b'```json\n{}\n```\n```json\n{}\n```', b'```json\n{"value":"```"}\n```',
                 b'{}', b'```json\n{"x":1,"x":2}\n```', b'```json\nnot json\n```']
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recovery.unwrap(raw)

    def test_derivation_is_zero_call_and_keeps_original_failure(self):
        result = self.derive()
        self.assertEqual(result['status'], 'derived_candidate')
        self.assertEqual(result['validation'], 'passed_after_format_recovery')
        self.assertEqual(result['additional_model_calls'], 0)
        self.assertNotIn('costs', result)
        self.assertEqual((self.derived / 'normalized-response.json').read_bytes(), self.raw[8:-3])
        self.assertEqual(self.original, {p.name: p.read_bytes() for p in self.fixture.run.iterdir()})

    def test_missing_source_binding_rejected(self):
        self.derive()
        path = self.derived / 'manifest.json'
        manifest = recovery.read(path)
        del manifest['source_binding']
        builder.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'recovery_source_binding_required'):
            recovery.verify_derived(ROOT, self.derived, path)

    def test_inner_edits_rejected_even_with_updated_hash(self):
        self.derive()
        path = self.derived / 'normalized-response.json'
        path.write_bytes(path.read_bytes().replace(b'  ', b' ', 1))
        result = recovery.read(self.derived / 'result.json')
        result['normalized_response_sha256'] = builder.view.sha(path)
        builder.write_json(self.derived / 'result.json', result)
        with self.assertRaisesRegex(ValueError, 'recovery_inner_bytes_changed'):
            recovery.verify_derived(ROOT, self.derived, self.derived / 'manifest.json')

    def test_materialized_edits_rejected_even_with_updated_hash(self):
        self.derive()
        path = self.derived / 'business_map.json'
        data = recovery.read(path)
        data['businesses'][1]['description'] += ' Edited.'
        builder.write_json(path, data)
        result = recovery.read(self.derived / 'result.json')
        result['artifacts_sha256']['business_map.json'] = builder.view.sha(path)
        builder.write_json(self.derived / 'result.json', result)
        with self.assertRaisesRegex(ValueError, 'recovery_materialized_artifact_changed'):
            recovery.verify_derived(ROOT, self.derived, self.derived / 'manifest.json')

    def test_adoption_semantic_status_and_validation_record_cannot_be_promoted(self):
        self.derive()
        result_path = self.derived / 'result.json'
        original = result_path.read_bytes()
        for key in ('adoption', 'semantic_acceptance'):
            with self.subTest(key=key):
                result = json.loads(original)
                result[key] = 'accepted'
                builder.write_json(result_path, result)
                with self.assertRaisesRegex(ValueError, 'explicit_derived_candidate_required'):
                    recovery.verify_derived(ROOT, self.derived, self.derived / 'manifest.json')
                result_path.write_bytes(original)
        validation_path = self.derived / 'validation.json'
        validation = recovery.read(validation_path)
        validation['semantic_acceptance'] = 'accepted'
        builder.write_json(validation_path, validation)
        with self.assertRaisesRegex(ValueError, 'recovery_validation_record_changed'):
            recovery.verify_derived(ROOT, self.derived, self.derived / 'manifest.json')

    def test_page_requires_explicit_proof_and_displays_failure_and_zero_calls(self):
        self.derive()
        args = copy.deepcopy(self.fixture.args)
        args.run_dir, args.reference_map, args.reference_revenue = self.derived, None, None
        with self.assertRaisesRegex(ValueError, 'system_agent_provenance_required'):
            builder.build(args)
        args.format_recovery = self.derived / 'manifest.json'
        args.workbench_url = 'http://127.0.0.1:8765'
        builder.build(args)
        page = (args.output / 'index.html').read_text()
        for text in ('StrictJSONError', 'derived_candidate', 'passed_after_format_recovery',
                     '新增模型调用 0 次', '内部每个字节保持不变', '原失败 Trace 过程'):
            self.assertIn(text, page)
        self.assertNotIn('与 Codex 原文复核候选对照', page)
        self.assertEqual(recovery.read(self.fixture.run / 'result.json')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
