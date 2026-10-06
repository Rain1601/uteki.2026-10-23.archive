"""Scripted planner tests for bounded delivery, pagination and exact read coverage."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import json_size, load_evidence_bundle
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, read


class AutonomousPaginationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dataset = self.root / 'dataset'; self.dataset.mkdir()
        make_scoped_dataset(self.dataset)

    def open_dataset(self, *, paragraphs=8, text_size=700):
        index_dir = self.dataset / 'indexes/acme-annual'
        blocks = [{'block_id': 'b0', 'type': 'heading_candidate', 'text': 'Business'}]
        blocks.extend({'block_id': f'b{i}', 'type': 'paragraph', 'text': f'Block {i}: ' + 'x' * text_size
                       + (' TAIL_REQUIRED' if i == paragraphs else '')} for i in range(1, paragraphs + 1))
        for block in blocks: block['reported_page'] = '1'
        (index_dir / 'blocks.jsonl').write_text(''.join(json.dumps(b) + '\n' for b in blocks))
        index = {'index_id': 'index-acme-annual', 'form_type': '10-K', 'diagnostics': [], 'nodes': [
            {'node_id': 'root', 'kind': 'document', 'start_block_id': 'b0', 'end_block_id': f'b{paragraphs}'},
            {'node_id': 'business', 'kind': 'item', 'start_block_id': 'b0', 'end_block_id': f'b{paragraphs}'}]}
        (index_dir / 'index.json').write_text(json.dumps(index))
        (index_dir / 'manifest.json').write_text(json.dumps({'status': 'candidate', 'artifacts': {
            name: {'sha256': digest((index_dir / name).read_bytes())} for name in ('index.json', 'blocks.jsonl')}}))
        path = self.dataset / 'manifest.json'; manifest = json.loads(path.read_text())
        manifest['files'] = {str(p.relative_to(self.dataset)): digest(p.read_bytes())
                             for p in self.dataset.rglob('*') if p.is_file() and p != path}
        path.write_text(json.dumps(manifest))
        self.port = QueryDataPort(self.dataset); self.addCleanup(self.port.close)
        self.scope = ExecutionScope(snapshot_id=self.port.snapshot_id, company_ids=('acme',),
            source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)
        self.request = {'question': 'Read the complete Business chapter for 2031.', 'scope': self.scope.model_dump(mode='json')}

    def chapter_plan(self):
        return {'action': 'plan', 'reason': 'Read complete source', 'requirements': [{
            'kind': 'read_node', 'requirement_id': 'business', 'description': 'Complete Business',
            'source_id': 'acme-annual', 'node_id': 'business'}]}

    def run_actions(self, actions, *, observation_bytes=2500, name='run'):
        planner = ScriptedPlanner(actions)
        result = asyncio.run(AutonomousDataAgent(self.port, planner, limits={
            'max_steps': len(actions), 'max_packet_bytes': 32000,
            'observation_bytes': observation_bytes, 'page_items': 2}).run(self.request, output=self.root/name))
        return result, planner

    def test_last_page_is_readable_and_saved_body_does_not_complete_reading(self):
        self.open_dataset()
        first = read(); first['read']['count'] = 12
        state = {}
        def early_finish(packet):
            self.assertLess(len(packet['coverage'][0]['returned_block_ids']), 9)
            self.assertTrue(packet['coverage'][0]['unread_block_ids'])
            self.assertNotIn('TAIL_REQUIRED', json.dumps(packet['observation']))
            state['ref'] = packet['observation']['result_artifact']
            state['cursor'] = next(r['next_cursor'] for r in packet['observation']['reads'] if r['pointer'] == '/blocks')
            return {'action': 'finish'}
        def page_or_finish(packet):
            if not packet['coverage'][0]['unread_block_ids']:
                if not state.get('extracted'):
                    self.assertIn('TAIL_REQUIRED', json.dumps(packet['observation']))
                    state['extracted'] = True
                    return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                        'context_id': state['ref']['evidence_id'], 'block_id': 'b8',
                        'quote': 'TAIL_REQUIRED', 'label': 'Evidence from the last page'}]}
                return {'action': 'finish'}
            previous = packet['observation'].get('result', {})
            if previous.get('artifact_id') == state['ref']['artifact_id']:
                state['cursor'] = previous['next_cursor']
            return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': {
                'artifact_id': state['ref']['artifact_id'], 'pointer': '/blocks', 'cursor': state['cursor'], 'limit': 2}}
        result, planner = self.run_actions([self.chapter_plan(), first, early_finish] + [page_or_finish] * 12)
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['trace'][2]['status'], 'rejected')
        self.assertEqual(result['coverage'][0]['unread_block_ids'], [])
        self.assertEqual(result['coverage'][0]['returned_block_ids'], [f'b{i}' for i in range(9)])
        self.assertTrue(any('TAIL_REQUIRED' in json.dumps(p['observation']) for p in planner.packets))
        self.assertLess(json_size(planner.packets[0]), 16000)
        self.assertTrue(all(json_size(p) <= 32000 for p in planner.packets))
        self.assertNotIn('query', planner.packets[0]['catalog']['schema'])
        self.assertNotIn('items', result['evidence_bundle'])
        bundle = load_evidence_bundle(self.root/'run')
        self.assertEqual(len(bundle['items'][0]['value']['blocks']), 9)
        candidate, = [item for item in bundle['items'] if item['kind'] == 'candidate_extract']
        parent = next(item for item in bundle['items'] if item['evidence_id'] == candidate['value']['source_evidence_id'])
        self.assertEqual(candidate['scope'], parent['scope'])
        self.assertEqual(parent['value']['source_snapshot_id'], 'acme-annual')
        self.assertEqual(candidate['value']['block_id'], 'b8')
        self.assertIn(candidate['value']['quote'], next(b['text'] for b in parent['value']['blocks'] if b['block_id'] == 'b8'))
        self.assertEqual(bundle['schema_version'], 'autonomous-evidence-manifest-v2')
        for step in result['trace']:
            receipt = json.loads((self.root/'run'/step['receipt']).read_text())
            ref = receipt['artifact']
            self.assertEqual(digest((self.root/'run'/ref['path']).read_bytes()), ref['sha256'])
            self.assertTrue(receipt['request_fingerprint'])
        first_receipt = json.loads((self.root/'run/turn-002/receipt.json').read_text())
        self.assertTrue(first_receipt['preview_truncated'])
        self.assertFalse(first_receipt['execution_limited'])

    def test_last_step_storage_without_next_planner_delivery_counts_zero_body(self):
        self.open_dataset()
        first = read(); first['read']['count'] = 12
        result, _ = self.run_actions([self.chapter_plan(), first])
        self.assertEqual(result['coverage'][0]['returned_block_ids'], [])
        self.assertEqual(len(result['coverage'][0]['unread_block_ids']), 9)
        self.assertEqual(len(load_evidence_bundle(self.root/'run')['items'][0]['value']['blocks']), 9)
        self.assertEqual(result['status'], 'limited')

    def test_extract_cannot_use_a_block_only_saved_to_disk(self):
        self.open_dataset()
        first = read(); first['read']['count'] = 12
        def extract(packet):
            return {'action': 'extract', 'requirement_ids': ['business'], 'extracts': [{
                'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b8',
                'quote': 'TAIL_REQUIRED', 'label': 'Not yet delivered'}]}
        result, _ = self.run_actions([self.chapter_plan(), first, extract])
        self.assertEqual(result['trace'][-1]['status'], 'rejected')
        self.assertFalse(any(i['kind'] == 'candidate_extract' for i in load_evidence_bundle(self.root/'run')['items']))

    def test_large_block_text_ranges_complete_only_after_all_characters(self):
        self.open_dataset(paragraphs=1, text_size=3200)
        state = {}
        def next_text(packet):
            if not packet['coverage'][0]['unread_block_ids']:
                return {'action': 'finish'}
            if 'ref' not in state:
                state['ref'] = packet['observation']['result_artifact']
            previous = packet['observation'].get('result', {})
            cursor = previous.get('next_cursor') if previous.get('unit') == 'characters' else None
            return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': {
                'artifact_id': state['ref']['artifact_id'], 'pointer': '/blocks/1/text', 'cursor': cursor, 'limit': 1000}}
        result, planner = self.run_actions([self.chapter_plan(), read()] + [next_text] * 12, observation_bytes=1800)
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['coverage'][0]['unread_block_ids'], [])
        self.assertIn('b1', planner.packets[3]['coverage'][0]['unread_block_ids'])

    def test_catalog_and_probe_are_navigable_before_a_plan(self):
        self.open_dataset()
        def probe(packet):
            self.assertEqual(packet['observation']['result']['items'][0]['kind'], 'entity')
            return {'action': 'probe_schema', 'schema_probe': {'metric_ids': ['revenue'], 'limit': 1}}
        def next_probe(packet):
            cursor = packet['observation']['result']['next_cursor']
            return {'action': 'probe_schema', 'schema_probe': {'metric_ids': ['revenue'], 'limit': 1, 'cursor': cursor}}
        result, _ = self.run_actions([
            {'action': 'discover_catalog', 'catalog': {'kind': 'entities', 'limit': 1}}, probe, next_probe])
        self.assertTrue(all(step['status'] == 'tool_returned' for step in result['trace']))
        self.assertEqual([s['consecutive_no_progress'] for s in result['trace']], [0, 0, 0])
        self.assertEqual(result['evidence_bundle']['item_count'], 0)

    def test_repeated_artifact_index_first_page_is_not_new_progress(self):
        self.open_dataset()
        result, _ = self.run_actions([{'action': 'list_artifacts'}] * 12)
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertLess(len(result['trace']), 12)

    def test_repeated_body_page_does_not_increase_read_coverage(self):
        self.open_dataset()
        state = {}
        first = read(); first['read']['count'] = 12
        def repeat_page(packet):
            if not state:
                state['artifact_id'] = packet['observation']['result_artifact']['artifact_id']
                state['cursor'] = next(r['next_cursor'] for r in packet['observation']['reads'] if r['pointer'] == '/blocks')
            return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': {
                **state, 'pointer': '/blocks', 'limit': 1}}
        result, planner = self.run_actions([self.chapter_plan(), first] + [repeat_page] * 7)
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual(planner.packets[3]['coverage'][0]['returned_block_ids'], result['coverage'][0]['returned_block_ids'])
        self.assertLess(len(result['coverage'][0]['returned_block_ids']), 9)
        self.assertTrue(result['coverage'][0]['unread_block_ids'])

    def test_execution_page_limit_is_separate_from_preview_truncation(self):
        self.open_dataset(text_size=40)
        search = {'action': 'search_source', 'requirement_ids': ['business'], 'search': {
            'source_snapshot_id': 'acme-annual', 'node_id': 'business', 'phrase': 'Block', 'limit': 1}}
        result, _ = self.run_actions([self.chapter_plan(), search], observation_bytes=12000)
        receipt = json.loads((self.root/'run/turn-002/receipt.json').read_text())
        full = json.loads((self.root/'run'/receipt['artifact']['path']).read_text())
        self.assertTrue(receipt['execution_limited'], full)
        self.assertFalse(receipt['preview_truncated'])
        self.assertEqual(result['coverage'][0]['returned_block_ids'], [])

    def test_overlapping_prefixes_of_delivered_text_are_not_progress(self):
        self.open_dataset(paragraphs=1, text_size=40)
        state = {}
        def prefix(limit):
            def action(packet):
                if not state: state['artifact_id'] = packet['observation']['result_artifact']['artifact_id']
                return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': {
                    **state, 'pointer': '/blocks/1/text', 'limit': limit}}
            return action
        result, planner = self.run_actions([self.chapter_plan(), read()] + [prefix(i) for i in (5, 6, 7, 8, 9)])
        self.assertEqual(planner.packets[2]['coverage'][0]['unread_block_ids'], [])
        self.assertEqual(result['stop_reason'], 'no_progress_limit')
        self.assertEqual([row['consecutive_no_progress'] for row in result['trace'][2:]], [1, 2, 3])

    def test_query_context_preview_also_marks_its_evidence_artifact_read(self):
        self.open_dataset(paragraphs=1, text_size=40)
        query = {'action': 'query', 'requirement_ids': ['business'], 'plan': {'documents': [{
            'company_id': 'acme', 'form': '10-K', 'period_end': '2031-12-31', 'phrase': 'Block 1'}]}}
        state = {}
        def reread_text(packet):
            if not state:
                self.assertEqual(packet['coverage'][0]['returned_block_ids'], ['b1'])
                self.assertEqual(packet['coverage'][0]['unread_block_ids'], ['b0'])
                context = packet['observation']['result']['documents'][0]['contexts'][0]
                ref = next(r for r in packet['evidence_index'] if r['kind'] == 'context')
                state['artifact_id'] = ref['artifact_id']
                block_index = next(i for i, b in enumerate(context['blocks']) if b['block_id'] == 'b1')
                state['pointer'] = f'/blocks/{block_index}/text'
            return {'action': 'read_artifact', 'requirement_ids': ['business'], 'artifact_read': {**state, 'limit': 5}}
        result, _ = self.run_actions([self.chapter_plan(), query] + [reread_text] * 5, observation_bytes=12000)
        self.assertEqual(result['stop_reason'], 'no_progress_limit', result['trace'])
        self.assertEqual([row['consecutive_no_progress'] for row in result['trace'][2:]], [1, 2, 3])


if __name__ == '__main__': unittest.main()
