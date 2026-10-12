"""Independent evaluator must distinguish SDK content from stored artifacts."""
from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v3/evaluation-only/projection_visibility.py'
spec = importlib.util.spec_from_file_location('e6_projection_visibility_test', HELPER)
visibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visibility)


class ProjectionVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.query = Path(self.temp.name) / 'query'
        self.query.mkdir()
        self.scope = {'snapshot_id': 'snapshot-a', 'source_snapshot_ids': ['source-a', 'source-b']}
        self.rows = [{'source_snapshot_id': 'source-a', 'block_ids': ['b1', 'b2']},
                     {'source_snapshot_id': 'source-b', 'block_ids': ['b3']}]
        self.packet = {'scope': self.scope, 'source_documents': [
            {'source_snapshot_id': row['source_snapshot_id'], 'blocks': [{'block_id': b} for b in row['block_ids']]}
            for row in self.rows]}
        self.ref = {'artifact_id': 'art-a', 'sha256': 'a' * 64, 'scope_id': 'scope-a',
                    'scope': self.scope, 'path': 'artifacts/art-a.json'}
        self.value = {'delivery_schema_version': 'selected-originals-v4', 'delivery_block_ids': self.rows}

    def sdk_input(self, step, *, value=None, complete=False):
        return (self.query / f'turn-{step:03d}' / 'input.json', {
            'active_scope': deepcopy(self.scope), 'record_selection_effect': {
                'value': deepcopy(value or {'delivery_schema_version': 'selected-originals-v4'}),
                'complete': complete, 'truncated': not complete, 'artifact': deepcopy(self.ref), 'reads': []}})

    def page_input(self, step, offset, end, *, rows=None, total=2):
        path, packet = self.sdk_input(step)
        binding = {k: self.ref[k] for k in ('artifact_id', 'sha256', 'scope_id')}
        binding.update(snapshot_id=self.scope['snapshot_id'], pointer='/delivery_block_ids')
        page = {**binding, 'unit': 'items', 'offset': offset, 'end_offset': end,
            'total_count': total, 'returned_count': end-offset, 'items': deepcopy(self.rows[offset:end] if rows is None else rows),
            'gaps': [], 'status': 'read' if end == total else 'limited',
            'next_cursor': None if end == total else {**binding, 'offset': end}}
        packet['observation'] = {'status': 'tool_returned', 'artifact': deepcopy(self.ref),
                                 'preview_truncated': False, 'result': page}
        return path, packet

    def check(self, inputs, verdict, binding='pass'):
        result = visibility.visible_projection(self.packet, self.query, inputs, {'verdict': binding})
        self.assertEqual(result['verdict'], verdict, result)
        return result

    def test_stored_artifact_and_unread_refs_are_not_visibility(self):
        path = self.query / self.ref['path']
        path.parent.mkdir()
        path.write_text(json.dumps(self.value))
        self.ref['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        sdk = self.sdk_input(1)
        # This exact hash-valid artifact fallback passed in the old evaluator.
        self.check([sdk], 'fail')
        sdk[1]['record_selection_effect']['reads'] = [{'value': self.value, 'status': 'not_previewed'}]
        self.check([sdk], 'fail')

    def test_direct_value_and_partial_navigation_complete_projection_pass(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                self.check([self.sdk_input(1, value=self.value, complete=complete)], 'pass')

    def test_initial_null_observation_supplies_no_page_and_does_not_block_later_evidence(self):
        first = self.sdk_input(1)
        first[1]['observation'] = None
        self.check([first], 'fail')
        self.check([first, self.page_input(2, 0, 2)], 'pass')
        direct = self.sdk_input(1, value=self.value)
        direct[1]['observation'] = None
        self.check([direct], 'pass')

    def test_partial_direct_projection_cannot_claim_completeness(self):
        value = deepcopy(self.value)
        value['delivery_block_ids'][0]['block_ids'].pop()
        self.check([self.sdk_input(1, value=value, complete=True)], 'fail')

    def test_order_duplicate_and_source_mismatch_fail(self):
        for rows in ([{**self.rows[0], 'block_ids': ['b2', 'b1']}, self.rows[1]],
                     [self.rows[0], self.rows[0], self.rows[1]],
                     [self.rows[0], {**self.rows[1], 'source_snapshot_id': 'source-c'}]):
            with self.subTest(rows=rows):
                self.check([self.sdk_input(1, value={**self.value, 'delivery_block_ids': rows})], 'fail')

    def test_actual_complete_pagination_passes(self):
        result = self.check([self.page_input(1, 0, 1), self.page_input(2, 1, 2)], 'pass')
        self.assertEqual(result['matching_pre_finish_sdk_inputs'][0]['visibility_evidence'], 'complete_sdk_artifact_pages')

    def test_missing_first_page_and_repeated_same_page_fail(self):
        self.check([self.page_input(1, 1, 2)], 'fail')
        self.check([self.page_input(1, 0, 1), self.page_input(2, 0, 1)], 'fail')

    def test_out_of_order_pages_use_recorded_offsets(self):
        self.check([self.page_input(1, 1, 2), self.page_input(2, 0, 1)], 'pass')
        wrong = self.page_input(2, 1, 2, rows=[self.rows[0]])
        self.check([self.page_input(1, 0, 1), wrong], 'fail')

    def test_truncated_page_does_not_count(self):
        for change in ('preview', 'missing_items', 'counts'):
            with self.subTest(change=change):
                sdk = self.page_input(2, 1, 2)
                if change == 'preview': sdk[1]['observation']['preview_truncated'] = True
                if change == 'missing_items': sdk[1]['observation']['result'].pop('items')
                if change == 'counts': sdk[1]['observation']['result']['returned_count'] = 2
                self.check([self.page_input(1, 0, 1), sdk], 'fail')

    def test_page_scope_hash_identity_and_cursor_bindings(self):
        for key in ('artifact_id', 'sha256', 'scope_id', 'snapshot_id'):
            with self.subTest(key=key):
                sdk = self.page_input(2, 1, 2)
                sdk[1]['observation']['result'][key] = 'different'
                self.check([self.page_input(1, 0, 1), sdk], 'fail')
        sdk = self.page_input(1, 0, 1)
        sdk[1]['observation']['result']['next_cursor']['offset'] = 0
        self.check([sdk, self.page_input(2, 1, 2)], 'fail')

    def test_other_artifact_cannot_supply_remainder(self):
        sdk = self.page_input(2, 1, 2)
        for target in (sdk[1]['record_selection_effect']['artifact'], sdk[1]['observation']['artifact'], sdk[1]['observation']['result']):
            target['artifact_id'] = 'art-b'
        self.check([self.page_input(1, 0, 1), sdk], 'fail')

    def test_root_entry_page_delivers_atomic_projection_field(self):
        sdk = self.page_input(1, 0, 2)
        page = sdk[1]['observation']['result']
        page.update(pointer='', unit='entries', items=[{'key': k, 'value': v} for k, v in self.value.items()])
        self.check([sdk], 'pass')

    def test_scope_other_query_and_worker_inputs_do_not_count(self):
        sdk = self.sdk_input(1, value=self.value)
        sdk[1]['active_scope'] = {**self.scope, 'snapshot_id': 'other'}
        self.check([sdk], 'fail')
        for directory in (self.query.parent / 'other-query', self.query / 'worker'):
            sdk = self.sdk_input(1, value=self.value)
            self.check([(directory / 'turn-001/input.json', sdk[1])], 'fail')

    def test_actual_artifact_store_preview_and_pagination(self):
        from uteki.domain.research_data.execution_scope import ExecutionScope
        from uteki.infrastructure.research_data.run_artifacts import ArtifactStore
        self.scope = ExecutionScope(snapshot_id='snapshot-a', company_ids=['acme'],
            source_snapshot_ids=['source-a', 'source-b'], source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-06-01').model_dump(mode='json')
        self.packet['scope'] = self.scope
        store = ArtifactStore(self.query)
        # Oversize unrelated metadata makes the artifact too large for a preview.
        full = {**self.value, 'other_metadata': 'x' * 2000}
        self.ref = store.put('record-selection-effect', full, scope=self.scope, step=1)
        preview = store.preview(self.ref['artifact_id'], max_bytes=512)
        self.assertTrue(preview['truncated'])
        sdk = self.sdk_input(1)
        sdk[1]['record_selection_effect'].update(preview)
        self.check([sdk], 'pass')
        inputs = []
        for step, offset in ((1, 0), (2, 1)):
            sdk = self.sdk_input(step)
            page = store.read({'artifact_id': self.ref['artifact_id'],
                'pointer': '/delivery_block_ids', 'offset': offset, 'limit': 1})
            sdk[1]['observation'] = {'status': 'tool_returned', 'artifact': self.ref,
                                     'preview_truncated': False, 'result': page}
            inputs.append(sdk)
        self.check(inputs, 'pass')
        self.check(inputs[:1], 'fail')

    def test_both_evaluator_entrypoints_use_sdk_binding_and_new_policy(self):
        for folder in ('2026-10-10-e6-repeatability-v3', '2026-10-10-e6-delivery-boundary-v1'):
            path = ROOT / 'experiments/agent_design' / folder / 'evaluation-only/independent-real-acceptance.v1.py'
            module_spec = importlib.util.spec_from_file_location('e6_acceptance_test', path)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            module.a.sdk_bound_inputs = lambda root: ([self.sdk_input(1)], {'verdict': 'pass'})
            result = module.visible_projection(self.packet, self.query)
            self.assertEqual(result['verdict'], 'fail')
            self.assertEqual(result['visibility_policy_version'], visibility.VERSION)

    def test_binding_failure_overrides_visible_projection(self):
        self.check([self.sdk_input(1, value=self.value)], 'fail', binding='fail')

    def test_conflicting_overlapping_pages_fail(self):
        conflict = self.page_input(2, 0, 1, rows=[{**self.rows[0], 'block_ids': ['wrong']}])
        self.check([self.page_input(1, 0, 1), conflict, self.page_input(3, 1, 2)], 'fail')


if __name__ == '__main__':
    unittest.main()
